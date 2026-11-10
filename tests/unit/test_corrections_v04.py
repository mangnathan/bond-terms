"""Corrections de lecture de la v0.4 (ADR 0004), sur les cas observés en v0.3."""

import pytest

from bond_terms.comparaison import firds_reference
from bond_terms.extraction import Extraction, Value, verify
from bond_terms.llm import user_message
from bond_terms.rattachement import is_structured
from bond_terms.valeurs import amount_matches_citation, numbers_in, several_bonds


@pytest.mark.parametrize(
    ("value", "citation"),
    [
        (500_000_000, "€500,000,000 1.000 per cent. Notes due 27 July 2029"),
        (1_000_000_000, "(i) Series: EUR 1,0 00,000,000"),
        (100_000, "Valeur nominale indiquée : 100 000,00 €"),
        (1, "ayant une valeur nominale d'un euro."),
    ],
)
def test_amounts_written_in_the_citation_are_accepted(value: float, citation: str) -> None:
    assert amount_matches_citation(value, citation)


@pytest.mark.parametrize(
    ("value", "citation"),
    [
        # Fourchette : ce n'est pas le montant de l'émission.
        (30_000_000, "An amount in Currency between 30,000,000.00 and 100,000,000.00"),
        # Écriture ambiguë : un million ou un milliard, 750 mille ou 750 millions.
        (1_000_000_000, "Emission de EUR 1 000 000,000 d'Obligations"),
        (1_000_000, "Emission de EUR 1 000 000,000 d'Obligations"),
        (750_000_000, "(i) Series: GBP 750 000,000"),
        # Montant absent de la citation.
        (650_000_000, "(i) Series: EUR 500,000,000"),
    ],
)
def test_ranges_ambiguous_or_absent_amounts_are_refused(value: float, citation: str) -> None:
    assert not amount_matches_citation(value, citation)


def test_numbers_in_reads_the_usual_notations() -> None:
    assert {1_500_000.0, 1_500_000_000.0} <= numbers_in("1,500,000 and 1.500.000.000,00")


def test_verify_refuses_an_amount_that_its_citation_does_not_state() -> None:
    pages = ["Aggregate Nominal Amount: (i) Series: EUR 500,000,000"]
    extraction = Extraction(
        "1",
        "llm",
        "v",
        {"montant": Value("650000000", "Aggregate Nominal Amount: (i) Series: EUR 500,000,000")},
    )
    verify(extraction, pages)
    assert extraction.champs["montant"].refusee


def test_several_bonds_are_detected_from_their_issue_titles() -> None:
    text = (
        "€500,000,000 3.625 per cent. bonds due 13 december 2026 issue price: 99.655 per cent. "
        "€700,000,000 3.625 per cent. bonds due 13 june 2031 issue price: 99.251 per cent."
    )
    assert several_bonds(text)
    same = (
        "eur 1,000,000,000 senior preferred notes due december 2027 ... the "
        "eur 1,000,000,000 senior preferred notes due 7 december 2027"
    )
    assert not several_bonds(same)


def test_the_model_is_warned_and_shown_where_the_isin_appears() -> None:
    pages = ["Bonds due 2026: ISIN FR0000000001. Bonds due 2031: ISIN FR0000000002."]
    message = user_message(["FR0000000002"], pages, several=True)
    assert "several bonds" in message and "Bonds due 2031: ISIN FR0000000002" in message
    assert "Warning" not in user_message(["FR0000000002"], pages)


def test_cms_is_a_swap_rate() -> None:
    assert firds_reference("CMS 5Y") == "SWAP"


@pytest.mark.parametrize(
    "text",
    [
        "eur 30,000,000 european barrier autocallable equity linked securities",
        "eur 200,000,000 digital (rate linked) interest securities due 30 november 2038",
        "rate linked interest provisions: applicable",
    ],
)
def test_english_structured_notes_are_detected(text: str) -> None:
    assert is_structured(text)


def test_plain_notes_mentioning_linked_provisions_are_not_structured() -> None:
    assert not is_structured("rate linked interest provisions: not applicable")
    assert not is_structured("index linked interest note provisions: not applicable")
