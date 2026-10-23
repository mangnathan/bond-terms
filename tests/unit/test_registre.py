from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bond_terms.firds import COLUMNS as FIRDS_COLUMNS
from bond_terms.registre import COLUMNS, collect, document_rows, fetch_documents

LVMH = "IOG4E947OATN0KJYSD45"


def register_doc(
    doc_id: str, isins: str, doc_type: str = "FTWS", date: str = "2024-06-03"
) -> dict[str, Any]:
    return {
        "id": doc_id,
        "document_type": doc_type,
        "document_type_descr": "Final terms, including the  summary ",
        "approval_filing_date": f"{date}T00:00:00Z",
        "document_rfss_id": f"{doc_id}0,abcdef",
        "instrument_isins": isins,
        "home_member_state_code": "FR",
    }


class FakeRegister:
    """Répond à partir d'un dictionnaire ISIN -> documents, par pages comme le registre."""

    def __init__(self, documents: dict[str, list[dict[str, Any]]]) -> None:
        self.documents = documents
        self.calls: list[str] = []

    def get_json(self, url: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        values = dict(params)
        isin = values["fq"].split('"')[1]
        self.calls.append(isin)
        docs = self.documents.get(isin, [])
        start, rows = int(values["start"]), int(values["rows"])
        return {"response": {"numFound": len(docs), "docs": docs[start : start + rows]}}


def test_document_rows_split_identifiers_and_count_isins() -> None:
    (row,) = document_rows("FR1", LVMH, [register_doc("42", "FR1, FR2")])
    assert set(row) == set(COLUMNS)
    assert (row["rfss_file_id"], row["rfss_checksum"]) == ("420", "abcdef")
    assert row["isins_in_document"] == "2"
    assert row["approval_date"] == "2024-06-03"
    assert row["document_type_descr"] == "Final terms, including the  summary"


def test_documents_are_fetched_by_page_and_cached(tmp_path: Path) -> None:
    docs = [register_doc(str(i), "FR1") for i in range(250)]
    register = FakeRegister({"FR1": docs})
    first = fetch_documents(register, "FR1", tmp_path)  # type: ignore[arg-type]
    second = fetch_documents(register, "FR1", tmp_path)  # type: ignore[arg-type]
    assert len(first) == len(second) == 250
    assert register.calls == ["FR1", "FR1", "FR1"]  # trois pages, puis le cache
    assert not list(tmp_path.glob("*.part"))


def test_collect_summarizes_documents_per_issuer(tmp_path: Path) -> None:
    firds = [
        dict.fromkeys(FIRDS_COLUMNS, "")
        | {
            "isin": isin,
            "issuer_lei": LVMH,
            "cfi": "DBFTFB",
            "rate_type": "fixed",
            "fixed_rate": "3",
        }
        for isin in ("FR0000000001", "FR0000000002", "FR0000000003")
    ]
    index = tmp_path / "dette.parquet"
    pq.write_table(pa.Table.from_pylist(firds), index)
    register = FakeRegister(
        {
            "FR0000000001": [register_doc("1", "FR0000000001", date="2022-05-25")],
            "FR0000000002": [
                register_doc("2", "FR0000000002", date="2023-02-24"),
                register_doc("3", "FR0000000002", doc_type="STDA", date="2025-05-19"),
                register_doc("4", "FR0000000002", doc_type="SUPP"),
            ],
        }
    )
    summary = collect(register, index, tmp_path / "data", "2026-10-23")  # type: ignore[arg-type]
    assert summary["obligations"] == 3
    assert summary["couples_isin_document"] == 4
    assert summary["couples_documents_d_emission"] == 3
    assert summary["obligations_avec_document"] == 2
    assert summary["obligations_a_document_unique"] == 1
    assert (summary["date_approbation_min"], summary["date_approbation_max"]) == (
        "2022-05-25",
        "2025-05-19",
    )
    lvmh = next(i for i in summary["par_emetteur"] if i["emetteur"] == "LVMH")
    assert (lvmh["obligations"], lvmh["obligations_avec_document"], lvmh["documents"]) == (3, 2, 3)
    written = pq.read_table(tmp_path / "data" / summary["fichier"])
    assert written.num_rows == 4
