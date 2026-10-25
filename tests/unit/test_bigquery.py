from pathlib import Path

import pyarrow as pa
import pytest

from bond_terms.bigquery import UploadRefusedError, export_raw_tables, upload
from bond_terms.entrepot import RAW_TABLES, load_duckdb


def test_upload_sends_every_table_in_order() -> None:
    sent: list[str] = []
    total = upload({"population": b"ab", "decoupage": b"c"}, lambda name, _: sent.append(name))
    assert sent == ["decoupage", "population"]
    assert total == 3


def test_upload_refuses_above_the_local_cap_before_any_call() -> None:
    sent: list[str] = []
    with pytest.raises(UploadRefusedError):
        upload({"population": b"x" * 11}, lambda name, _: sent.append(name), max_total_bytes=10)
    assert sent == []


def test_upload_refuses_unknown_tables() -> None:
    with pytest.raises(UploadRefusedError):
        upload({"population; drop table x": b""}, lambda *_: None)


def test_upload_stops_at_the_first_refusal() -> None:
    sent: list[str] = []

    def load(name: str, _: bytes) -> None:
        sent.append(name)
        raise RuntimeError("quota")

    with pytest.raises(RuntimeError):
        upload({"population": b"a", "decoupage": b"b"}, load)
    assert sent == ["decoupage"]


def test_export_reads_every_raw_table(tmp_path: Path) -> None:
    database = tmp_path / "entrepot.duckdb"
    load_duckdb({name: pa.table({"isin": ["FR0000000001"]}) for name in RAW_TABLES}, database)
    files = export_raw_tables(database)
    assert set(files) == RAW_TABLES
    assert all(data.startswith(b"PAR1") for data in files.values())
