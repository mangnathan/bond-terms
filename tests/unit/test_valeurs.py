import datetime as dt

import pytest

from bond_terms.valeurs import amount_pattern, contains, contains_isin, date_pattern, rate_pattern

MATURITY = dt.date(2030, 7, 1)


@pytest.mark.parametrize(
    "text",
    [
        "maturity date: 1 july 2030",
        "maturity date: 01 july 2030",
        "maturity date: 1st july, 2030",
        "date d'echeance : 1er juillet 2030",
        "july 1, 2030",
        "01/07/2030",
        "2030-07-01",
        "1\njuly\n2030",
    ],
)
def test_date_forms(text: str) -> None:
    assert contains(date_pattern(MATURITY), text)


@pytest.mark.parametrize("text", ["11 july 2030", "1 july 20301", "1 june 2030", "21/07/2030"])
def test_date_rejects_other_dates(text: str) -> None:
    assert not contains(date_pattern(MATURITY), text)


@pytest.mark.parametrize(
    "text",
    [
        "eur 1,500,000,000",
        "eur 1.500.000.000",
        "eur 1 500 000 000",
        "1500000000",
        "1,500,000,000.00",
    ],
)
def test_amount_forms(text: str) -> None:
    assert contains(amount_pattern(1_500_000_000), text)


@pytest.mark.parametrize("text", ["eur 11,500,000,000", "eur 1,500,000", "eur 1,500,000,000,000"])
def test_amount_rejects_other_amounts(text: str) -> None:
    assert not contains(amount_pattern(1_500_000_000), text)


@pytest.mark.parametrize(
    "text", ["3.32 per cent. per annum", "3,32 %", "3.320 per cent", "3.32%", "3,32 pour cent"]
)
def test_rate_forms(text: str) -> None:
    assert contains(rate_pattern(3.32), text)


@pytest.mark.parametrize(
    "text", ["13.32 per cent", "3.325 per cent", "3.32 eur", "issue price: 99.513 per cent"]
)
def test_rate_rejects_other_numbers(text: str) -> None:
    assert not contains(rate_pattern(3.32), text)


def test_whole_rate() -> None:
    assert contains(rate_pattern(4.0), "4.00 per cent")
    assert contains(rate_pattern(4.0), "4 per cent")
    assert not contains(rate_pattern(4.0), "4.5 per cent")


def test_isin_split_by_ocr() -> None:
    assert contains_isin("isin code: fr0014 007lk5\n", "FR0014007LK5")
    assert not contains_isin("isin code: fr0014007lk6", "FR0014007LK5")
