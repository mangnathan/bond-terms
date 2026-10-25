"""Copie des tables brutes de DuckDB vers le bac à sable BigQuery.

Usage (après `python -m bond_terms.entrepot`) :
    uv run --group bigquery --env-file .env python -m bond_terms.bigquery

Zéro dépense : le projet Google Cloud n'a aucune facturation liée. Les chargements de fichiers
sont gratuits ; le plafond qui compte est le stockage du bac à sable (10 Gio pour toute la vie du
projet, non rendus quand on supprime une table). Le chargeur refuse donc d'envoyer plus de
quelques mégaoctets et s'arrête au premier refus, sans nouvelle tentative.
"""

from __future__ import annotations

import argparse
import io
import os
from collections.abc import Callable, Mapping
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from bond_terms.entrepot import RAW_SCHEMA, RAW_TABLES

LOCATION = "EU"
MAX_TOTAL_BYTES = 20 * 1024 * 1024
PROJECT_VARIABLE = "BOND_TERMS_GCP_PROJECT"

Loader = Callable[[str, bytes], None]


class UploadRefusedError(RuntimeError):
    """Envoi refusé avant tout appel à BigQuery."""


def export_raw_tables(database: Path) -> dict[str, bytes]:
    """Chaque table brute en Parquet, en mémoire : quelques centaines de lignes par table."""
    files: dict[str, bytes] = {}
    with duckdb.connect(str(database), read_only=True) as connection:
        for name in sorted(RAW_TABLES):
            # Nom tiré d'une liste fermée, jamais d'une saisie.
            table = connection.sql(f"select * from {RAW_SCHEMA}.{name}").to_arrow_table()  # noqa: S608
            buffer = pa.BufferOutputStream()
            pq.write_table(table, buffer)
            files[name] = buffer.getvalue().to_pybytes()
    return files


def upload(files: Mapping[str, bytes], load: Loader, max_total_bytes: int = MAX_TOTAL_BYTES) -> int:
    """Envoie les tables une par une ; la première erreur interrompt tout l'envoi."""
    unknown = set(files) - RAW_TABLES
    if unknown:
        raise UploadRefusedError(f"Tables inconnues : {sorted(unknown)}")
    total = sum(len(data) for data in files.values())
    if total > max_total_bytes:
        raise UploadRefusedError(f"{total} octets à envoyer, plafond local de {max_total_bytes}")
    for name in sorted(files):
        load(name, files[name])
    return total


def bigquery_loader(project: str) -> Loader:  # pragma: no cover - appelle Google Cloud
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=LOCATION)
    dataset = bigquery.Dataset(f"{project}.{RAW_SCHEMA}")
    dataset.location = LOCATION
    client.create_dataset(dataset, exists_ok=True)
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        # Remplacement complet de la table : ce n'est pas une mise à jour, le bac à sable l'accepte.
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    def load(name: str, data: bytes) -> None:
        job = client.load_table_from_file(
            io.BytesIO(data), f"{project}.{RAW_SCHEMA}.{name}", num_retries=0, job_config=config
        )
        job.result(retry=None)
        print(f"{RAW_SCHEMA}.{name} : {job.output_rows} lignes")

    return load


def main() -> None:  # pragma: no cover - appelle Google Cloud
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    args = parser.parse_args()
    project = os.environ.get(PROJECT_VARIABLE)
    if not project:
        raise SystemExit(f"{PROJECT_VARIABLE} manquant (voir .env.example)")
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise SystemExit("GOOGLE_APPLICATION_CREDENTIALS manquant (voir .env.example)")
    total = upload(export_raw_tables(args.database), bigquery_loader(project))
    print(f"{total} octets envoyés")


if __name__ == "__main__":
    main()
