import pytest

from bond_terms.instruments import is_plain_bond


def bond(**fields: str) -> dict[str, str]:
    base = {"cfi": "DBFTFB", "rate_type": "fixed", "fixed_rate": "2.818", "reference_rate": ""}
    return base | fields


def test_fixed_rate_bond_is_plain() -> None:
    assert is_plain_bond(bond())


def test_medium_term_note_is_plain() -> None:
    assert is_plain_bond(bond(cfi="DTFNFB"))


@pytest.mark.parametrize("rate", ["0", "", "abc"])
def test_zero_or_missing_fixed_rate_is_structured(rate: str) -> None:
    assert not is_plain_bond(bond(fixed_rate=rate))


@pytest.mark.parametrize("rate", ["7.35", "10"])
def test_high_but_plausible_fixed_rate_is_plain(rate: str) -> None:
    # Les obligations en leu roumain ou en rand sud-africain paient jusqu'à environ 10 %.
    assert is_plain_bond(bond(fixed_rate=rate))


@pytest.mark.parametrize("rate", ["10.5", "46", "60"])
def test_fixed_rate_above_ten_percent_is_structured(rate: str) -> None:
    # Coupon cumulé d'un produit structuré, par exemple « SoGenerale 46% 14 12 2032 ».
    assert not is_plain_bond(bond(fixed_rate=rate))


def test_floating_rate_with_real_reference_is_plain() -> None:
    assert is_plain_bond(bond(rate_type="floating", fixed_rate="", reference_rate="EURI"))


@pytest.mark.parametrize("reference", ["", "FORMULA", "OTHER", "other", "AT000BASKET0"])
def test_floating_rate_without_real_reference_is_structured(reference: str) -> None:
    assert not is_plain_bond(bond(rate_type="floating", fixed_rate="", reference_rate=reference))


@pytest.mark.parametrize("cfi", ["DEXXXX", "DSXXXX", "ESVUFR", ""])
def test_other_categories_are_excluded(cfi: str) -> None:
    assert not is_plain_bond(bond(cfi=cfi))
