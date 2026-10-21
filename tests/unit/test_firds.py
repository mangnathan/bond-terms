from io import BytesIO

from bond_terms.firds import COLUMNS, iter_records
from bond_terms.instruments import is_plain_bond

NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:auth.017.001.02"


def firds_file(*interest_rates: str) -> BytesIO:
    records = "".join(
        f"""<RefData>
          <FinInstrmGnlAttrbts><Id>FR000000000{i}</Id><FullNm>TEST {i}</FullNm>
            <ClssfctnTp>DBFTFB</ClssfctnTp><NtnlCcy>EUR</NtnlCcy></FinInstrmGnlAttrbts>
          <Issr>R0MUWSFPU8MPRO8K5P83</Issr>
          <TradgVnRltdAttrbts><Id>XPAR</Id><FrstTradDt>2026-01-15T08:00:00Z</FrstTradDt>
          </TradgVnRltdAttrbts>
          <DebtInstrmAttrbts><TtlIssdNmnlAmt Ccy="EUR">500000000</TtlIssdNmnlAmt>
            <MtrtyDt>2031-01-15</MtrtyDt><NmnlValPerUnit Ccy="EUR">100000</NmnlValPerUnit>
            <IntrstRate>{rate}</IntrstRate><DebtSnrty>SNDB</DebtSnrty></DebtInstrmAttrbts>
        </RefData>"""
        for i, rate in enumerate(interest_rates)
    )
    return BytesIO(f'<Document xmlns="{NAMESPACE}"><Pyld>{records}</Pyld></Document>'.encode())


def floating(reference: str) -> str:
    return (
        f"<Fltg><RefRate>{reference}</RefRate><Term><Unit>MNTH</Unit><Val>3</Val></Term>"
        "<BsisPtSprd>70</BsisPtSprd></Fltg>"
    )


def test_fixed_rate_record() -> None:
    (row,) = iter_records(firds_file("<Fxd>3.125</Fxd>"))
    assert set(row) == set(COLUMNS)
    assert row["isin"] == "FR0000000000"
    assert row["rate_type"] == "fixed"
    assert row["fixed_rate"] == "3.125"
    assert row["maturity_date"] == "2031-01-15"
    assert row["nominal_amount"] == "500000000"
    assert row["denomination"] == "100000"
    assert row["seniority"] == "SNDB"
    assert row["first_trade_date"] == "2026-01-15"
    assert row["reference_rate"] == ""


def test_floating_rate_reference_in_its_three_forms() -> None:
    rows = list(
        iter_records(
            firds_file(
                floating("<Indx>EURI</Indx>"),
                floating("<Nm>EURIBOR</Nm>"),
                floating("<ISIN>EU0009652783</ISIN>"),
            )
        )
    )
    assert [r["reference_rate"] for r in rows] == ["EURI", "EURIBOR", "EU0009652783"]
    assert all(r["rate_type"] == "floating" for r in rows)
    assert all(r["reference_term"] == "3 MNTH" and r["spread_bps"] == "70" for r in rows)
    # Une référence par code (Indx) ne doit pas faire exclure l'obligation du périmètre.
    assert all(is_plain_bond(r) for r in rows)


def test_record_without_interest_rate() -> None:
    (row,) = iter_records(firds_file(""))
    assert row["rate_type"] == ""
    assert not is_plain_bond(row)
