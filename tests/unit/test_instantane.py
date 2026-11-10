import datetime as dt

from bond_terms.api import Instantane
from bond_terms.extraction import Extraction, Value
from bond_terms.instantane import build, status
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
