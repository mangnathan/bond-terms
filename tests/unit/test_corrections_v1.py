"""Corrections de la v1.0 (ADR 0005), sur les lectures fausses vérifiées du test de la v0.4."""

import pytest

from bond_terms.comparaison import firds_reference
from bond_terms.extraction import PERPETUAL, Extraction, Value, verify
from bond_terms.instantane import fallback_kind, fallback_reason
from bond_terms.lancement import FALLBACK
from bond_terms.llm import clean


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        # « 2,000 » à la française vaut 2, pas 2 000.
        ("taux_fixe", "2,000", "2"),
        ("taux_fixe", "3,625", "3.625"),
        ("taux_fixe", "2.000", "2"),
        ("marge_pb", "82", "82"),
        # Un montant garde ses séparateurs de milliers.
        ("montant", "1,000,000", "1000000"),
    ],
)
def test_rates_read_their_comma_as_a_decimal_mark(name: str, raw: str, expected: str) -> None:
    assert clean(name, raw) == expected


def checked(name: str, valeur: str, citation: str) -> Value:
    extraction = Extraction("1", "llm", "v", {name: Value(valeur, citation)})
    verify(extraction, [citation])
    return extraction.champs[name]


def test_a_rate_that_its_citation_does_not_state_is_refused() -> None:
    citation = "10. Base d'Intérêt : Taux Fixe de 2,000 % l'an"
    assert checked("taux_fixe", "2000", citation).refusee
    assert not checked("taux_fixe", "2", citation).refusee


def test_a_maturity_that_its_citation_does_not_state_is_refused() -> None:
    citation = "Date d'Echéance : 25 octobre 2033"
    assert checked("date_echeance", "2023-10-25", citation).refusee
    assert not checked("date_echeance", "2033-10-25", citation).refusee


def test_a_maturity_split_by_the_text_extraction_is_still_found() -> None:
    assert not checked("date_echeance", "2027-07-08", "Maturity Date: 8 July 202 7").refusee


def test_a_perpetual_bond_has_no_date_to_find() -> None:
    assert not checked("date_echeance", PERPETUAL, "Maturity Date: Undated").refusee


def test_the_verification_of_the_v04_did_not_check_rates() -> None:
    extraction = Extraction("1", "llm", "v", {"taux_fixe": Value("2000", "Taux Fixe de 2,000 %")})
    verify(extraction, ["Taux Fixe de 2,000 %"], rates_and_dates=False)
    assert not extraction.champs["taux_fixe"].refusee


def test_the_estr_index_code_is_recognised() -> None:
    assert firds_reference("EU000A2X2A25") == "ESTR"


def test_the_reason_of_a_fallback_is_kept_and_classified() -> None:
    done = Extraction("1", "llm", "v")
    timeout = Extraction("2", "regles", "v", remarque=f"{FALLBACK} : pas de réponse en 120 s")
    assert fallback_reason(done) is None
    assert fallback_reason(timeout) == "pas de réponse en 120 s"
    assert fallback_kind("pas de réponse en 120 s") == "délai dépassé"
    assert fallback_kind("service indisponible : 503 UNAVAILABLE") == "service indisponible"
    assert fallback_kind("refus de l'API pour quota : RESOURCE_EXHAUSTED") == "quota"
    assert fallback_kind("plafond local atteint : 60 requêtes sur 60") == "quota"


@pytest.mark.parametrize(
    ("name", "valeur", "citation"),
    [
        ("taux_fixe", "3.625", "Issue of €750,000,000 3. 625 per cent. Fixed Rate Notes"),
        ("date_echeance", "2051-11-08", "Maturity Date:\n8November 2051"),
        (
            "date_echeance",
            "2028-02-09",
            "Maturity Date: Interest Payment Date falling in or nearest to February 2028",
        ),
    ],
)
def test_values_written_in_damaged_or_partial_citations_are_kept(
    name: str, valeur: str, citation: str
) -> None:
    assert not checked(name, valeur, citation).refusee


def test_a_month_and_year_alone_do_not_justify_another_year() -> None:
    citation = "Maturity Date: Interest Payment Date falling in or nearest to February 2028"
    assert checked("date_echeance", "2027-02-09", citation).refusee
