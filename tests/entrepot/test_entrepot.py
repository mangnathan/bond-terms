"""Chaîne de l'entrepôt sur de petites données fabriquées : chargement DuckDB, puis dbt build."""

import csv
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from dbt.cli.main import dbtRunner

from bond_terms.entrepot import build_raw_tables, load_duckdb
from bond_terms.firds import COLUMNS as FIRDS_COLUMNS
from bond_terms.population import ISSUERS
from bond_terms.registre import COLUMNS as REGISTER_COLUMNS

PROJECT = Path(__file__).resolve().parents[2] / "entrepot"
LVMH = "IOG4E947OATN0KJYSD45"
OTHER = "OTHERISSUER000000000"


def test_issuer_seed_matches_the_package() -> None:
    with (PROJECT / "seeds" / "emetteurs.csv").open(encoding="utf-8") as f:
        seed = {row["lei"]: (row["nom"], row["secteur"]) for row in csv.DictReader(f)}
    assert seed == {lei: (i.name, i.sector) for lei, i in ISSUERS.items()}


def bond(isin: str, lei: str) -> dict[str, str]:
    return dict.fromkeys(FIRDS_COLUMNS, "") | {
        "isin": isin,
        "issuer_lei": lei,
        "cfi": "DBFTFB",
        "currency": "EUR",
        "maturity_date": "2030-01-15",
        "rate_type": "fixed",
        "fixed_rate": "3.873",
        "nominal_amount": "500000000",
    }


def register_row(isin: str, doc_id: str, date: str) -> dict[str, str]:
    return dict.fromkeys(REGISTER_COLUMNS, "") | {
        "isin": isin,
        "issuer_lei": LVMH,
        "document_id": doc_id,
        "document_type": "FTWS",
        "approval_date": date,
        "isins_in_document": "1",
    }


def write_inputs(tmp: Path, test_date: str) -> dict[str, Path]:
    firds = tmp / "dette.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [bond("FR0000000001", LVMH), bond("FR0000000002", LVMH), bond("FR0000000009", OTHER)]
        ),
        firds,
    )
    registre = tmp / "documents.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                register_row("FR0000000001", "1", "2023-03-01"),
                register_row("FR0000000002", "2", test_date),
                register_row("FR0000000002", "3", "2025-06-01"),
            ]
        ),
        registre,
    )
    cache = tmp / "cache"
    cache.mkdir()
    (cache / "FR0000000009.json").write_text(
        json.dumps(
            [{"id": "9", "document_type": "FTWS", "approval_filing_date": "2024-01-01T00:00:00Z"}]
        ),
        encoding="utf-8",
    )
    decoupage = tmp / "decoupage.csv"
    rows = [
        ("1", "FR0000000001", LVMH, "2023-03-01", "developpement"),
        ("2", "FR0000000002", LVMH, test_date, "test"),
        ("9", "FR0000000009", OTHER, "2024-01-01", "test_nouveaux_emetteurs"),
    ]
    with decoupage.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            [
                "document_id",
                "isin",
                "issuer_lei",
                "document_type",
                "approval_date",
                "rfss_file_id",
                "rfss_checksum",
                "languages",
                "jeu",
            ]
        )
        writer.writerows(
            [(d, i, lei, "FTWS", date, d, "x", "English", jeu) for d, i, lei, date, jeu in rows]
        )
    controle = tmp / "pdf-controle.csv"
    with controle.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            [
                "document_id",
                "jeu",
                "octets",
                "sha256",
                "pages",
                "pages_sans_texte",
                "caracteres",
                "rubrique_echeance",
                "erreur",
            ]
        )
        writer.writerow(["1", "developpement", "10", "a", "9", "9", "0", "False", ""])
        writer.writerow(["2", "test", "10", "b", "10", "1", "900", "True", ""])
        writer.writerow(["9", "test_nouveaux_emetteurs", "10", "c", "8", "0", "800", "True", ""])
    return {
        "firds": firds,
        "registre": registre,
        "cache": cache,
        "decoupage": decoupage,
        "controle": controle,
    }


def build(tmp: Path, test_date: str, monkeypatch: pytest.MonkeyPatch) -> tuple[bool, Path]:
    inputs = write_inputs(tmp, test_date)
    tables = build_raw_tables(
        inputs["firds"],
        inputs["registre"],
        inputs["cache"],
        inputs["decoupage"],
        inputs["controle"],
    )
    database = tmp / "entrepot.duckdb"
    load_duckdb(tables, database)
    monkeypatch.setenv("BOND_TERMS_DUCKDB", str(database))
    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(PROJECT),
            "--profiles-dir",
            str(PROJECT),
            "--target-path",
            str(tmp / "target"),
            "--log-path",
            str(tmp / "logs"),
            "--quiet",
        ]
    )
    return result.success, database


def test_warehouse_builds_and_applies_the_comparability_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    success, database = build(tmp_path, "2024-11-01", monkeypatch)
    assert success
    # dbt garde sa connexion ouverte dans ce processus : même configuration, sinon DuckDB refuse.
    with duckdb.connect(str(database)) as connection:
        rows = connection.sql(
            "select isin, jeu, emetteur, taux_fixe, montant_comparable"
            " from verite_terrain order by isin"
        ).fetchall()
        scanned = connection.sql("select document_id from documents where scanne").fetchall()
    assert rows == [
        ("FR0000000001", "developpement", "LVMH", 3.873, True),
        # Deux documents d'émission pour cet ISIN : le montant n'est pas comparable.
        ("FR0000000002", "test", "LVMH", 3.873, False),
        ("FR0000000009", "test_nouveaux_emetteurs", "autre émetteur", 3.873, True),
    ]
    assert scanned == [("1",)]


def test_warehouse_detects_a_test_document_older_than_development(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    success, _ = build(tmp_path, "2022-01-01", monkeypatch)
    assert not success
