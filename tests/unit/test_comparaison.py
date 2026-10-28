import datetime as dt
from typing import Any

import pytest

from bond_terms.comparaison import compare, firds_reference, firds_term
from bond_terms.extraction import (
    HYBRID,
    PERPETUAL,
    Extraction,
    Value,
    accepted,
    page_of,
    two_part_page,
    verify,
)

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


def test_typographic_quotes_and_dashes_do_not_reject_a_citation() -> None:
    pages = ["3 Specified Currency: United States Dollar (“USD”)\n– Margin(s): + 0.88 per cent."]
    assert page_of('Specified Currency: United States Dollar ("USD")', pages) == 1
    assert page_of("- Margin(s): + 0.88 per cent.", pages) == 1
    assert page_of('Specified Currency: United States Dollar ("EUR")', pages) is None


def test_list_marks_around_a_citation_do_not_count_but_short_citations_are_refused() -> None:
    pages = [" (xii) Margin(s): + 0.88 per cent. per annum \n"]
    assert page_of("– Margin(s): + 0.88 per cent. per annum.", pages) == 1
    assert page_of("0.88", pages) is None


@pytest.mark.parametrize(
    ("citation", "page"),
    [
        ("(ix) Maturity Date: 5 August 2027", "9. (i) Maturity Date: 5 August 2027"),
        (
            "24. (i) Fixed Rate(s) of Interest: 4.105 per cent.",
            "(i) Fixed Rate(s) of Interest: 4.105 per cent.",
        ),
        ("(9) (i) Maturity Date: 18 August 2029", "9. (i) Maturity Date: 18 August 2029"),
    ],
)
def test_rubric_numbering_copied_wrongly_does_not_reject_a_citation(
    citation: str, page: str
) -> None:
    assert page_of(citation, [page]) == 1


@pytest.mark.parametrize(
    ("citation", "page"),
    [
        # Le jour d'une date et le début d'un taux font partie de la valeur : ils restent vérifiés.
        ("15 March 2030 (Maturity)", "Maturity Date: 16 March 2030 (Maturity)"),
        (
            "3.625 per cent. per annum payable",
            "Rate of Interest: 4.625 per cent. per annum payable",
        ),
        ("(ix) Maturity Date: 6 August 2027", "9. (i) Maturity Date: 5 August 2027"),
    ],
)
def test_values_at_the_start_of_a_citation_are_still_checked(citation: str, page: str) -> None:
    assert page_of(citation, [page]) is None


def test_hybrid_rate_type_is_right_whatever_firds_declares() -> None:
    hybrid = {"type_taux": HYBRID, "taux_fixe": "3.75", "reference_taux": "SWAP"}
    as_fixed = compare(hybrid, TRUTH | {"type_taux": "fixed", "taux_fixe": 3.75})
    assert as_fixed["type_taux"] and as_fixed["taux_fixe"]
    assert as_fixed["reference_taux"] is None
    as_floating = compare(hybrid, TRUTH | {"reference_taux_variable": "SWAP 5Y"})
    assert as_floating["type_taux"] and as_floating["reference_taux"]
    assert as_floating["taux_fixe"] is None
    assert compare({"type_taux": "fixed"}, TRUTH)["type_taux"] is False


def test_two_part_citation_on_a_two_column_layout() -> None:
    pages = [
        "(i) Fixed Rate(s) of Interest:\n(ii) Interest Payment Date(s):\n"
        "2.56 per cent. per annum payable annually\n12 October in each year"
    ]
    extraction = Extraction(
        "x",
        "llm",
        "v",
        {
            "taux_fixe": Value("2.56", "Fixed Rate(s) of Interest: 2.56 per cent. per annum"),
            "rang": Value("senior", "Status of the Notes: Senior Preferred"),
        },
    )
    verify(extraction, pages)
    assert not extraction.champs["taux_fixe"].refusee
    assert extraction.champs["taux_fixe"].deux_morceaux
    assert extraction.champs["rang"].refusee
    verify(extraction, pages, two_parts=False)
    assert extraction.champs["taux_fixe"].refusee


def test_two_parts_need_the_label_shortly_before_the_value() -> None:
    far = "Fixed Rate(s) of Interest:" + " filler" * 100 + " 2.56 per cent. per annum payable"
    assert two_part_page("Fixed Rate(s) of Interest: 2.56 per cent. per annum", [far]) is None
    wrong = "Fixed Rate(s) of Interest: 2.65 per cent. per annum payable"
    assert two_part_page("Fixed Rate(s) of Interest: 2.56 per cent. per annum", [wrong]) is None
