import datetime as dt
from pathlib import Path
from typing import Any

from bond_terms.entrepot import read_csv
from bond_terms.exceptions import (
    TRUE_GAP,
    WRONG_READING,
    exceptions,
    firds_value_in_document,
    summarize,
    write_sheet,
)
from bond_terms.extraction import Extraction, Value

TRUTH: dict[str, Any] = {
    "document_id": "1",
    "isin": "FR0000000001",
    "devise": "EUR",
    "date_echeance": dt.date(2030, 1, 15),
    "type_taux": "fixed",
    "taux_fixe": 3.875,
    "reference_taux_variable": None,
    "duree_reference": None,
    "marge_points_de_base": None,
    "valeur_nominale": 100000.0,
    "montant_nominal_total": 500_000_000.0,
    "montant_comparable": True,
    "rang": None,
}


def model(**values: str) -> dict[str, Extraction]:
    champs = {name: Value(value, f"citation de {name}", page=2) for name, value in values.items()}
    return {"1": Extraction("1", "llm", "v", champs)}


def test_only_cited_values_that_differ_from_firds_are_exceptions() -> None:
    extractions = model(devise="EUR", montant="750000000", taux_fixe="3.875")
    extractions["1"].champs["date_echeance"] = Value("2031-01-15", "x", refusee=True)
    rows = exceptions(extractions, [TRUTH], {"1": "aggregate nominal amount: eur 750,000,000"})
    assert [(r["champ"], r["valeur_lue"], r["page"]) for r in rows] == [("montant", "750000000", 2)]
    assert rows[0]["valeur_firds_dans_le_document"] == "non"
    assert rows[0]["verdict"] == ""


def test_firds_value_search_helps_the_reader() -> None:
    text = "maturity date: 15 january 2030 ... 3.875 per cent"
    assert firds_value_in_document("date_echeance", dt.date(2030, 1, 15), text) == "oui"
    assert firds_value_in_document("taux_fixe", 3.875, text) == "oui"
    assert firds_value_in_document("rang", "SNDB", text) == ""
    assert firds_value_in_document("date_echeance", dt.date(9999, 12, 31), text) == ""


def test_summary_measures_the_share_of_true_gaps_on_checked_rows() -> None:
    rows = [
        {"document_id": "1", "champ": "montant", "verdict": TRUE_GAP},
        {"document_id": "1", "champ": "devise", "verdict": TRUE_GAP},
        {"document_id": "2", "champ": "montant", "verdict": TRUE_GAP},
        {"document_id": "3", "champ": "rang", "verdict": WRONG_READING},
        {"document_id": "4", "champ": "rang", "verdict": ""},
    ]
    summary = summarize(rows)
    assert summary["exceptions"] == 5 and summary["documents"] == 4
    assert summary["verifiees"] == 4 and summary["part_de_vrais_ecarts"] == 0.75
    assert summary["seuil_atteint"] is False
    assert summarize([])["part_de_vrais_ecarts"] is None


def test_sheet_round_trip(tmp_path: Path) -> None:
    rows = exceptions(model(montant="750000000"), [TRUTH], {})
    write_sheet(rows, tmp_path / "fiche.csv")
    read = read_csv(tmp_path / "fiche.csv").to_pylist()
    assert read[0]["champ"] == "montant" and read[0]["verdict"] == ""
