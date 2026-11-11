import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from bond_terms.api import Instantane
from bond_terms.extraction import Extraction, Value
from bond_terms.instantane import build, merge, read, status, to_retry, write
from bond_terms.lancement import FALLBACK

TRUTH = {
    "document_id": "1",
    "isin": "FR0014007NG9",
    "devise": "EUR",
    "date_echeance": dt.date(2027, 1, 12),
    "type_taux": "fixed",
    "taux_fixe": 2.0,
    "reference_taux_variable": None,
    "duree_reference": None,
    "marge_points_de_base": None,
    "valeur_nominale": 1000.0,
    "montant_nominal_total": 1_500_000.0,
    "montant_comparable": True,
    "rang": "SNDB",
}


def extraction(document_id: str, **champs: Value) -> Extraction:
    return Extraction(document_id, "llm", "v", dict(champs))


def test_status_of_a_value() -> None:
    assert status(None) == "absente"
    assert status(Value("EUR", "Euro")) == "acceptee"
    assert status(Value("EUR", "Euro", refusee=True)) == "refusee"


def test_snapshot_gives_values_review_and_exceptions_per_isin() -> None:
    model = {
        "1": extraction(
            "1",
            devise=Value("EUR", "Specified Currency: Euro", 2),
            montant=Value("5000000", "Emission de EUR 5 000 000", 1),
            rang=Value("senior", "Status: Senior", 3, refusee=True),
        )
    }
    rules = {"1": extraction("1")}
    snapshot = build(
        {"test_v04": ([TRUTH], model, rules)}, dt.datetime(2026, 11, 10, tzinfo=dt.UTC), "abc"
    )
    document = snapshot["obligations"]["FR0014007NG9"][0]
    assert document["champs"]["devise"] == {
        "valeur": "EUR",
        "citation": "Specified Currency: Euro",
        "page": 2,
        "statut": "acceptee",
    }
    assert document["champs"]["rang"]["statut"] == "refusee"
    assert document["en_revue"]
    assert {gap["champ"] for gap in document["exceptions"]} == {"montant"}
    assert snapshot["indicateurs"]["test_v04"]["part_valeurs_refusees"] == round(1 / 3, 4)
    # Le fichier produit est exactement celui que l'API accepte de charger.
    Instantane.model_validate(snapshot)


def test_documents_read_by_the_rules_are_counted() -> None:
    model = {"1": Extraction("1", "regles", "v", remarque=f"{FALLBACK} : quota")}
    snapshot = build(
        {"jeu": ([TRUTH], model, {"1": extraction("1")})},
        dt.datetime(2026, 11, 10, tzinfo=dt.UTC),
        "abc",
    )
    assert snapshot["indicateurs"]["jeu"]["documents_en_repli"] == 1


def test_a_document_covering_two_isins_is_counted_once() -> None:
    other = {**TRUTH, "isin": "FR001400IIR9"}
    model = {"1": extraction("1", montant=Value("5000000", "Emission de EUR 5 000 000", 1))}
    snapshot = build(
        {"jeu": ([TRUTH, other], model, {"1": extraction("1")})},
        dt.datetime(2026, 11, 10, tzinfo=dt.UTC),
        "abc",
    )
    assert set(snapshot["obligations"]) == {"FR0014007NG9", "FR001400IIR9"}
    indicators = snapshot["indicateurs"]["jeu"]
    assert indicators["documents"] == 1
    assert indicators["part_documents_avec_exception"] == 1.0


def doc(document_id: str, jeu: str = "test", extracteur: str | None = "llm") -> dict[str, object]:
    return {"document_id": document_id, "jeu": jeu, "extracteur": extracteur}


def snapshot_of(documents: dict[str, list[dict[str, object]]], seen: list[str]) -> dict[str, Any]:
    return {
        "format": 2,
        "cree_le": "2026-11-10T00:00:00+00:00",
        "commit": "a",
        "extracteurs": {},
        "obligations": documents,
        "indicateurs": {"ancien": {"documents": 1}},
        "documents_vus": seen,
        "collectes": [],
    }


def test_merge_adds_the_new_documents_once_and_keeps_the_memory() -> None:
    previous = snapshot_of({"FR0014007NG9": [doc("1")]}, ["1", "2"])
    weekly = snapshot_of({"FR0014007NG9": [doc("3")], "FR001400IIR9": [doc("3")]}, ["3", "4"])
    weekly["indicateurs"] = {"collecte-2026-11-16": {"documents": 1}}
    merged = merge(previous, weekly, {"date": "2026-11-16"})
    assert merged["obligations"]["FR0014007NG9"] == [doc("1"), doc("3")]
    assert merged["obligations"]["FR001400IIR9"] == [doc("3")]
    assert merged["documents_vus"] == ["1", "2", "3", "4"]
    assert set(merged["indicateurs"]) == {"ancien", "collecte-2026-11-16"}
    assert merged["collectes"] == [{"date": "2026-11-16"}]


def test_a_document_read_by_the_rules_is_published_but_retried() -> None:
    fallback = doc("5", "collecte-2026-11-11", "regles")
    merged = merge(snapshot_of({}, ["1"]), snapshot_of({"FR001401BOR0": [fallback]}, ["5"]), {})
    # La fiche est servie, marquée comme lue par les règles, mais le document n'est pas « vu ».
    assert merged["obligations"]["FR001401BOR0"] == [fallback]
    assert merged["documents_vus"] == ["1"]
    assert to_retry(merged) == {"5"}


def test_a_retried_document_replaces_its_previous_version() -> None:
    old = doc("5", "collecte-2026-11-11", None)
    new = doc("5", "collecte-2026-11-16", "llm")
    previous = snapshot_of({"FR001401BOR0": [old]}, ["5"])
    # Lu avant que l'extracteur ne soit noté : relu par prudence.
    assert to_retry(previous) == {"5"}
    merged = merge(previous, snapshot_of({"FR001401BOR0": [new]}, ["5"]), {})
    assert merged["obligations"]["FR001401BOR0"] == [new]
    assert merged["documents_vus"] == ["5"]
    assert to_retry(merged) == set()


def test_evaluation_sets_are_never_retried() -> None:
    assert to_retry(snapshot_of({"FR0014007NG9": [doc("1", "test_v04", None)]}, ["1"])) == set()


def test_documents_set_aside_are_remembered_as_seen() -> None:
    snapshot = build({}, dt.datetime(2026, 11, 10, tzinfo=dt.UTC), "abc", seen=["7", "8"])
    assert snapshot["documents_vus"] == ["7", "8"]


def test_an_old_snapshot_format_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "instantane.json"
    path.write_text(json.dumps({"format": 1}), encoding="utf-8")
    with pytest.raises(SystemExit):
        read(path)
    write(snapshot_of({}, []), path)
    assert read(path)["format"] == 2
