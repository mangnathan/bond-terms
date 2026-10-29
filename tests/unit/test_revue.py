import datetime as dt
from typing import Any

from bond_terms.extraction import Extraction, Value
from bond_terms.revue import disagreements, indicators, queue, reasons, wrong_documents


def extraction(document_id: str, **values: str | None) -> Extraction:
    champs = {name: Value(value, "citation") for name, value in values.items()}
    return Extraction(document_id, "test", "v", champs)


CLEAN = {
    "devise": "EUR",
    "date_echeance": "2030-01-15",
    "type_taux": "fixed",
    "taux_fixe": "3.875",
    "valeur_nominale": "100000",
    "rang": "senior",
}


def test_a_fully_justified_document_is_not_reviewed() -> None:
    assert reasons(extraction("1", **CLEAN)) == []


def test_missing_or_refused_values_send_to_review() -> None:
    model = extraction("1", **CLEAN | {"rang": None})
    model.champs["devise"].refusee = True
    assert reasons(model) == ["devise : valeur non justifiée", "rang : valeur non justifiée"]


def test_floating_notes_need_no_fixed_rate() -> None:
    assert reasons(extraction("1", **CLEAN | {"type_taux": "floating", "taux_fixe": None})) == []


def test_a_disagreement_alone_does_not_send_to_review_but_is_shown() -> None:
    model = {"1": extraction("1", **CLEAN), "2": extraction("2", **CLEAN | {"rang": None})}
    rules = {
        "1": extraction("1", **CLEAN | {"taux_fixe": "3.75"}),
        "2": extraction("2", **CLEAN | {"taux_fixe": "3.75"}),
    }
    flagged = queue(model, rules)
    assert list(flagged) == ["2"]
    assert flagged["2"] == [
        "rang : valeur non justifiée",
        "information, taux_fixe : règles 3.75, LLM 3.875",
    ]
    assert disagreements(model["1"], extraction("1", **CLEAN | {"rang": None})) == []


def test_indicators() -> None:
    result = indicators({"2": ["x"]}, documents=2, wrong={"2", "1"})
    assert result["part_en_revue"] == 0.5 and not result["sous_le_plafond"]
    assert result["errones_attrapes"] == 1


def test_wrong_documents_ignore_the_amount() -> None:
    truth: dict[str, Any] = {
        "document_id": "1",
        "isin": "X",
        "devise": "EUR",
        "date_echeance": dt.date(2030, 1, 15),
        "type_taux": "fixed",
        "taux_fixe": 3.875,
        "reference_taux_variable": None,
        "duree_reference": None,
        "marge_points_de_base": None,
        "valeur_nominale": 100000.0,
        "montant_nominal_total": 1.0,
        "montant_comparable": True,
        "rang": "SNDB",
    }
    model = {"1": extraction("1", **CLEAN | {"montant": "500"})}
    assert wrong_documents(model, [truth]) == set()
    model = {"1": extraction("1", **CLEAN | {"devise": "USD"})}
    assert wrong_documents(model, [truth]) == {"1"}
