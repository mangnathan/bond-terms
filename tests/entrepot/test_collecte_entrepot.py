"""Vérité terrain de la collecte hebdomadaire : mêmes modèles dbt que l'évaluation."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from bond_terms.collecte import build_truth, new_couples, raw_tables
from bond_terms.firds import COLUMNS as FIRDS_COLUMNS
from bond_terms.registre import COLUMNS as REGISTER_COLUMNS

LVMH = "IOG4E947OATN0KJYSD45"


def bond(isin: str) -> dict[str, str]:
    return dict.fromkeys(FIRDS_COLUMNS, "") | {
        "isin": isin,
        "issuer_lei": LVMH,
        "cfi": "DBFTFB",
        "currency": "EUR",
        "maturity_date": "2031-11-20",
        "rate_type": "fixed",
        "fixed_rate": "3.125",
        "nominal_amount": "750000000",
    }


def register_row(isin: str, document_id: str) -> dict[str, str]:
    return dict.fromkeys(REGISTER_COLUMNS, "") | {
        "isin": isin,
        "issuer_lei": LVMH,
        "document_id": document_id,
        "document_type": "FTWS",
        "approval_date": "2026-11-12",
        "isins_in_document": "1",
        "rfss_file_id": document_id,
        "rfss_checksum": "x",
    }


def test_weekly_truth_keeps_only_documents_citing_their_isin(tmp_path: Path) -> None:
    index = tmp_path / "dette.parquet"
    pq.write_table(pa.Table.from_pylist([bond("FR0000000001"), bond("FR0000000002")]), index)
    population = [
        {"isin": "FR0000000001", "issuer_lei": LVMH},
        {"isin": "FR0000000002", "issuer_lei": LVMH},
    ]
    register = [register_row("FR0000000001", "11"), register_row("FR0000000002", "12")]
    couples = new_couples(register, seen=set())
    quality = [
        {
            "document_id": d,
            "jeu": "collecte",
            "pages": 9,
            "pages_sans_texte": 0,
            "caracteres": 900,
            "rubrique_echeance": True,
            "erreur": "",
        }
        for d in ("11", "12")
    ]
    links = [
        {
            "document_id": "11",
            "isin": "FR0000000001",
            "jeu": "collecte",
            "isin_cite": "True",
            "produit_structure": "False",
        },
        # Le document 12 ne cite pas son ISIN : il est écarté de la vérité terrain.
        {
            "document_id": "12",
            "isin": "FR0000000002",
            "jeu": "collecte",
            "isin_cite": "False",
            "produit_structure": "False",
        },
    ]
    tables = raw_tables(index, population, register, couples, quality, links)
    truth = build_truth(tables, tmp_path / "semaine.duckdb", tmp_path)
    assert [(row["document_id"], row["isin"], row["taux_fixe"]) for row in truth] == [
        ("11", "FR0000000001", 3.125)
    ]
    # Seul document d'émission de son ISIN : le montant est comparable à FIRDS.
    assert truth[0]["montant_comparable"]
