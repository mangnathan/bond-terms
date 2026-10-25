import csv
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bond_terms.decoupage import (
    DEVELOPMENT,
    EXCLUDED_TIMED,
    NEW_ISSUERS_TEST,
    TEST,
    cutoff_date,
    exclude_timed,
    sample_new_issuers,
    split_main,
    timed_documents,
)
from bond_terms.firds import COLUMNS as FIRDS_COLUMNS

LVMH = "IOG4E947OATN0KJYSD45"


def doc(doc_id: str, date: str, isin: str = "FR1", file_id: str = "") -> dict[str, str]:
    return {
        "document_id": doc_id,
        "isin": isin,
        "issuer_lei": LVMH,
        "document_type": "FTWS",
        "approval_date": date,
        "rfss_file_id": file_id or doc_id,
    }


def test_cutoff_covers_at_least_the_test_share() -> None:
    dates = [f"2024-01-{d:02d}" for d in range(1, 11)]
    assert cutoff_date(dates, share=0.3) == "2024-01-08"


def test_documents_of_the_same_date_stay_together() -> None:
    dates = ["2024-01-01"] * 6 + ["2024-01-02"] * 4
    # 4 sur 10 dépassent déjà 30 % : la date du 2 janvier suffit, rien n'est coupé.
    assert cutoff_date(dates, share=0.3) == "2024-01-02"
    assert cutoff_date(["2024-01-01"] * 6 + ["2024-01-02"] * 2, share=0.3) == "2024-01-01"


def test_split_is_by_document_not_by_row() -> None:
    rows = [doc("1", "2022-01-01"), doc("2", "2023-01-01"), doc("3", "2025-01-01")]
    # Un même document cité pour deux ISIN ne compte qu'une fois et reste d'un seul côté.
    rows.append(doc("3", "2025-01-01", isin="FR2"))
    cutoff, split = split_main(rows)
    assert cutoff == "2025-01-01"
    assert [r["jeu"] for r in split] == [DEVELOPMENT, DEVELOPMENT, TEST, TEST]


def test_timed_documents_are_removed_from_the_test(tmp_path: Path) -> None:
    sheet = tmp_path / "fiche.csv"
    with sheet.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["isin", "lien_pdf"])
        writer.writeheader()
        writer.writerow(
            {
                "isin": "FR1",
                "lien_pdf": "https://registers.esma.europa.eu/publication/downloadFile?fileId=77&checksum=ab",
            }
        )
    timed = timed_documents(sheet)
    assert timed == {("FR1", "77")}
    rows = [
        doc("1", "2025-01-01", file_id="77") | {"jeu": TEST},
        doc("2", "2022-01-01") | {"jeu": DEVELOPMENT},
    ]
    assert [r["jeu"] for r in exclude_timed(rows, timed)] == [EXCLUDED_TIMED, DEVELOPMENT]


class FakeRegister:
    def get_json(self, url: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        isin = dict(params)["fq"].split('"')[1]
        docs = [
            {
                "id": f"D{isin}",
                "document_type": "FTWS",
                "approval_filing_date": "2024-01-01T00:00:00Z",
                "document_rfss_id": "1,a",
                "instrument_isins": isin,
            }
        ]
        return {"response": {"numFound": 1, "docs": docs}}


def test_new_issuers_sample_is_reproducible_and_excludes_target_issuers(tmp_path: Path) -> None:
    bonds = [
        dict.fromkeys(FIRDS_COLUMNS, "")
        | {"isin": f"FR{i:010d}", "issuer_lei": f"OTHER{i:015d}", "cfi": "DBFTFB"}
        | {"rate_type": "fixed", "fixed_rate": "3"}
        for i in range(400)
    ]
    bonds.append(bonds[0] | {"isin": "FR9999999999", "issuer_lei": LVMH})
    index = tmp_path / "dette.parquet"
    pq.write_table(pa.Table.from_pylist(bonds), index)
    stats, rows = sample_new_issuers(FakeRegister(), index, tmp_path / "cache")  # type: ignore[arg-type]
    again = sample_new_issuers(FakeRegister(), index, tmp_path / "cache2")  # type: ignore[arg-type]
    assert stats == {
        "vivier_obligations": 400,
        "obligations_tirees": 300,
        "obligations_avec_document": 300,
        "documents_trouves": 300,
        "documents_gardes": 100,
    }
    assert rows == again[1]
    assert all(r["jeu"] == NEW_ISSUERS_TEST and r["issuer_lei"] != LVMH for r in rows)
