from pathlib import Path
from typing import Any

from bond_terms.entrepot import read_csv
from bond_terms.nouveau_test import SET_NAME, draw, drawn_in_v01, write_split


def bonds(count: int) -> list[dict[str, str]]:
    return [{"isin": f"FR{n:010d}", "issuer_lei": f"LEI{n}"} for n in range(count)]


def documents_of(isin: str) -> list[dict[str, Any]]:
    number = int(isin[2:])
    return [
        {
            "id": f"d{number}",
            "document_type": "FTWS",
            "approval_filing_date": "2025-01-01T00:00:00Z",
        },
        {
            "id": f"p{number}",
            "document_type": "BPRO",
            "approval_filing_date": "2025-01-01T00:00:00Z",
        },
    ]


def test_the_v01_draw_is_replayed_identically() -> None:
    pool = bonds(1000)
    assert drawn_in_v01(pool) == drawn_in_v01(pool)
    assert len(drawn_in_v01(pool)) == 300


def test_draw_excludes_known_bonds_and_documents_and_keeps_issue_documents_only() -> None:
    pool = bonds(2000)
    excluded = {bond["isin"] for bond in pool[:1000]}
    stats, rows = draw(pool, excluded, {"d1500"}, documents_of)
    isins = {row["isin"] for row in rows}
    assert not isins & excluded
    assert all(row["document_type"] == "FTWS" and row["jeu"] == SET_NAME for row in rows)
    assert "d1500" not in {row["document_id"] for row in rows}
    assert stats["obligations_tirees"] == 450 and stats["documents_gardes"] == 150
    assert draw(pool, excluded, {"d1500"}, documents_of) == (stats, rows)


def test_split_file_is_read_back_as_written(tmp_path: Path) -> None:
    _, rows = draw(bonds(600), set(), set(), documents_of)
    target = tmp_path / "jeu.csv"
    write_split(rows, target)
    assert len(read_csv(target).to_pylist()) == len(rows)
