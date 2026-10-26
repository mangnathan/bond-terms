"""Extracteur à règles sur des conditions définitives fabriquées, avec les pièges observés."""

from bond_terms.extraction import PERPETUAL, Value
from bond_terms.regles import extract, glue_number

FIXED = [
    "Final Terms dated 6 July 2021\nIssue of EUR 1,000,000,000 0.250 per cent. "
    "Senior Preferred Notes due 8 July 2027\nPART A\n"
    "2. Specified Currency: Euro (“EUR”)\n"
    "3. Aggregate Nominal Amount:\n(i) Series: EUR 1,0 00,000,000\n"
    "5. Issue Price: 99.513 per cent. of the Aggregate Nominal Amount\n"
    "6. Specified Denomination(s): EUR 100,000\n",
    "9. (i) Maturity Date: 8 July 202 7\n"
    "(ii) Business Day Convention for Maturity Date: Following\n"
    "10. Interest Basis: 0.250 per cent. Fixed Rate\n"
    "12. (i) Status: \n(ii) Date of corporate authorisations: 1 June 2021\n"
    "Redemption at 100 per cent. of their nominal amount on the Maturity Date\n",
]

FLOATING = [
    "3 Specified Currency or Currencies: United States Dollar (“USD”)\n"
    "4 Aggregate Nominal Amount: (i) Series: USD 52,000,000\n"
    "6 Specified Denomination(s): USD 200,000\n"
    "8 Interest Basis: SOFR + 1.00 per cent. per annum Floating Rate\n"
    "9 Maturity Date: Specified Interest Payment Date falling on or nearest to 30 November 2031\n"
    "13 (i) Status of the Notes: Senior Non Preferred Notes\n"
    "– Reference Rate: SOFR\n(xii) Margin(s): + 1.00 per cent. per annum\n"
]

PERPETUAL_DOC = [
    "2. Specified Currency: Euro (“EUR”)\n8. Maturity Date: Not Applicable\n"
    "9. Interest Basis: 6.875 per cent. Fixed Rate (Resettable)\n"
    "13. Status of the Notes: Deeply Subordinated Notes\n"
]

FRENCH = [
    "3. Devise ou Devises Prévue(s) : Euro (€)\n"
    "4. Montant Nominal Total : 500 000 000 euros\n"
    "6. Valeur(s) Nominale(s) Indiquée(s) : 100 000 €\n"
    "8. Date d'Échéance : 15 mars 2030\n"
]


def values(pages: list[str]) -> dict[str, str | None]:
    champs = extract("x", pages).champs
    return {name: (None if v.refusee else v.valeur) for name, v in champs.items()}


def test_fixed_rate_notes_with_split_numbers_and_seniority_in_the_title() -> None:
    found = values(FIXED)
    assert found["devise"] == "EUR"
    assert found["montant"] == "1000000000"
    assert found["valeur_nominale"] == "100000"
    # « Business Day Convention for Maturity Date » n'est pas la rubrique de l'échéance.
    assert found["date_echeance"] == "2027-07-08"
    assert found["type_taux"] == "fixed"
    assert found["taux_fixe"] == "0.25"
    assert found["rang"] == "senior"


def test_every_value_carries_a_citation_found_on_its_page() -> None:
    champs = extract("x", FIXED).champs
    assert champs["date_echeance"].page == 2
    assert champs["devise"].page == 1
    assert all(v.citation for v in champs.values() if v.valeur is not None)


def test_floating_rate_notes() -> None:
    found = values(FLOATING)
    assert found["devise"] == "USD"
    assert found["type_taux"] == "floating"
    assert found["reference_taux"] == "SOFR"
    assert found["duree_reference"] == "1D"
    assert found["marge_pb"] == "100"
    assert found["date_echeance"] == "2031-11-30"
    assert found["rang"] == "senior_non_prefere"
    assert found["taux_fixe"] is None


def test_perpetual_resettable_notes() -> None:
    found = values(PERPETUAL_DOC)
    assert found["date_echeance"] == PERPETUAL
    assert found["type_taux"] == "fixed"
    assert found["taux_fixe"] == "6.875"
    assert found["rang"] == "subordonne_profond"


def test_french_final_terms() -> None:
    found = values(FRENCH)
    assert found["devise"] == "EUR"
    assert found["montant"] == "500000000"
    assert found["valeur_nominale"] == "100000"
    assert found["date_echeance"] == "2030-03-15"


def test_a_redemption_price_is_not_taken_for_a_coupon() -> None:
    pages = ["8. Interest Basis: Fixed Rate\n9. Redemption at 100 per cent.\n"]
    assert values(pages)["taux_fixe"] is None


def test_glue_number_only_rejoins_valid_shapes() -> None:
    assert glue_number("1,0 00,000") == (1_000_000, 10)
    assert glue_number("500 000 000") == (500_000_000, 11)
    assert glue_number("200,000 7") == (200_000, 7)
    assert glue_number("100 7") == (100, 3)


def test_empty_document_gives_no_value() -> None:
    assert all(v == Value() for v in extract("x", [""]).champs.values())
