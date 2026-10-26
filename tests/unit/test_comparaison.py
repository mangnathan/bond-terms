import datetime as dt
from typing import Any

from bond_terms.comparaison import compare, firds_reference, firds_term
from bond_terms.extraction import PERPETUAL, Extraction, Value, accepted, page_of, verify

TRUTH: dict[str, Any] = {
    "devise": "CNY",
    "date_echeance": dt.date(9999, 12, 31),
    "type_taux": "floating",
    "taux_fixe": None,
    "reference_taux_variable": "EU0009652783",
    "duree_reference": "3 MNTH",
    "marge_points_de_base": 150.0,
    "valeur_nominale": 100000.0,
    "montant_nominal_total": 5e8,
    "montant_comparable": False,
    "rang": "SBOD",
}


def test_firds_conventions() -> None:
    assert firds_reference("EU0009652783") == "EURIBOR"
    assert firds_reference("BBSW 3M") == "BBSW"
    assert firds_reference("SONA") == "SONIA"
    assert firds_term("3 MNTH") == "3M"
    assert firds_term("1 DAYS") == "1D"
    assert firds_term("") is None


def test_compare_applies_the_adr_rules() -> None:
    values = {
        "devise": "CNH",
        "date_echeance": PERPETUAL,
        "type_taux": "floating",
        "reference_taux": "EURIBOR",
        "duree_reference": "3M",
        "marge_pb": "150",
        "valeur_nominale": "100000",
        "montant": "1",
        "rang": "senior_non_prefere",
    }
    verdict = compare(values, TRUTH)
    assert verdict == {
        "devise": True,
        "date_echeance": True,
        "type_taux": True,
        "taux_fixe": None,
        "reference_taux": True,
        "duree_reference": True,
        "marge_pb": True,
        "valeur_nominale": True,
        "montant": None,
        "rang": True,
    }


def test_missing_value_is_wrong() -> None:
    verdict = compare({}, TRUTH | {"type_taux": "fixed", "taux_fixe": 3.873, "rang": "SNDB"})
    assert verdict["taux_fixe"] is False
    assert verdict["devise"] is False
    assert verdict["rang"] is False
    assert compare({"taux_fixe": "3.8730"}, TRUTH | {"type_taux": "fixed", "taux_fixe": 3.873})[
        "taux_fixe"
    ]


def test_citation_not_in_the_document_is_refused() -> None:
    pages = ["2. Specified Currency: Euro (EUR)", "9. Maturity Date: 8 July 2027"]
    extraction = Extraction(
        "x",
        "test",
        "0",
        {
            "devise": Value("EUR", "SPECIFIED   currency: euro (eur)"),
            "date_echeance": Value("2027-07-08", "maturity date: 9 july 2027"),
        },
    )
    verify(extraction, pages)
    assert extraction.champs["devise"].page == 1
    assert extraction.champs["date_echeance"].refusee
    assert accepted(extraction.champs["date_echeance"]) is None
    assert page_of("euro (eur) 9. maturity", pages) == 1
