import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from bond_terms.esma import DownloadedFile, sha256_of
from bond_terms.firds import COLUMNS, build_index, collect, iter_records
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


def test_isin_of_an_underlying_is_not_taken_for_a_reference_rate() -> None:
    # Un produit structuré cite l'ISIN de son sous-jacent ailleurs que dans le taux.
    rate = (
        "<Fxd>0</Fxd></IntrstRate>"
        "<UndrlygInstrm><ISIN>FR0000120271</ISIN></UndrlygInstrm><IntrstRate>"
    )
    (row,) = iter_records(firds_file(rate))
    assert row["reference_rate"] == ""


def zipped(tmp_path: Path, name: str, content: BytesIO) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name.replace(".zip", ".xml"), content.getvalue())
    return path


def test_index_keeps_one_row_per_isin_across_files(tmp_path: Path) -> None:
    first = zipped(tmp_path, "FULINS_D_1.zip", firds_file("<Fxd>3</Fxd>", floating("<Nm>X</Nm>")))
    # Le même ISIN publié une seconde fois, pour une autre plateforme de négociation.
    second = zipped(tmp_path, "FULINS_D_2.zip", firds_file("<Fxd>3</Fxd>"))
    output = tmp_path / "index" / "dette.parquet"
    stats = build_index([first, second], output)
    table = pq.read_table(output)
    assert table.column_names == COLUMNS
    assert table.column("isin").to_pylist() == ["FR0000000000", "FR0000000001"]
    assert (stats.records, stats.isins, stats.plain_bonds) == (3, 2, 2)
    assert stats.floating_without_reference == 0
    assert not list(output.parent.glob("*.part"))


def test_floating_rate_without_reference_is_counted(tmp_path: Path) -> None:
    path = zipped(tmp_path, "FULINS_D_1.zip", firds_file("<Fltg><BsisPtSprd>5</BsisPtSprd></Fltg>"))
    assert build_index([path], tmp_path / "dette.parquet").floating_without_reference == 1


class FakeClient:
    """Index des fichiers de l'ESMA et téléchargements préparés, sans réseau."""

    def __init__(self, archives: dict[str, Path]) -> None:
        self.archives = archives

    def get_json(self, url: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        docs = [
            {"file_name": n, "download_link": f"https://firds.esma.europa.eu/firds/{n}", **d}
            for n, d in [
                ("FULINS_D_20261017_01of01.zip", {"publication_date": "2026-10-17T00:00:00Z"}),
                ("FULINS_D_20261010_01of01.zip", {"publication_date": "2026-10-10T00:00:00Z"}),
            ]
        ]
        return {"response": {"docs": docs}}

    def download(self, url: str, destination: Path) -> DownloadedFile:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.archives[destination.name].read_bytes())
        return DownloadedFile(destination, destination.stat().st_size, sha256_of(destination))


def test_collect_takes_the_latest_publication_and_describes_it(tmp_path: Path) -> None:
    archive = zipped(tmp_path, "source.zip", firds_file("<Fxd>3</Fxd>"))
    client = FakeClient({"FULINS_D_20261017_01of01.zip": archive})
    manifest = collect(client, tmp_path / "data", None)  # type: ignore[arg-type]
    assert manifest["date_publication"] == "2026-10-17"
    assert [f["nom"] for f in manifest["fichiers"]] == ["FULINS_D_20261017_01of01.zip"]
    assert manifest["fichiers"][0]["sha256"] == sha256_of(archive)
    assert manifest["index"] == {"chemin": "interim/firds/dette-2026-10-17.parquet", "lignes": 1}
    assert (tmp_path / "data/raw/firds/FULINS/2026-10-17/FULINS_D_20261017_01of01.zip").exists()
