"""Chargement des tables brutes de l'entrepôt de données.

Usage :
    uv run python -m bond_terms.entrepot --firds-date AAAA-MM-JJ --registre-date AAAA-MM-JJ

Les tables brutes reprennent les sorties de la collecte sans les transformer ; dbt les nettoie
et les assemble ensuite. Seuls les titres utiles au projet sont chargés (population et
documents du découpage) : l'entrepôt reste petit, ce qui compte pour le bac à sable BigQuery,
dont la limite de stockage vaut pour toute la vie du projet.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from bond_terms.population import select_population
from bond_terms.registre import COLUMNS as REGISTER_COLUMNS
from bond_terms.registre import document_rows

RAW_SCHEMA = "brut"
RAW_TABLES = frozenset(
    {"firds_titres", "population", "registre_documents", "decoupage", "pdf_controle"}
)


def _strings(table: pa.Table) -> pa.Table:
    """Toutes les colonnes en texte : les types sont posés par dbt, pas au chargement."""
    return table.cast(pa.schema([(name, pa.string()) for name in table.column_names]))


def read_csv(path: Path) -> pa.Table:
    options = pacsv.ConvertOptions(strings_can_be_null=False, column_types={})
    table = pacsv.read_csv(path, convert_options=options)
    return _strings(table)


def new_issuer_documents(cache_dir: Path, isins: set[str]) -> list[dict[str, str]]:
    """Documents des émetteurs jamais vus, relus dans le cache de la collecte du découpage."""
    rows: list[dict[str, str]] = []
    for isin in sorted(isins):
        cached = cache_dir / f"{isin}.json"
        if cached.exists():
            docs = json.loads(cached.read_text(encoding="utf-8"))
            rows += document_rows(isin, "", docs)
    return rows


def build_raw_tables(
    firds_index: Path,
    registre: Path,
    new_issuer_cache: Path,
    decoupage: Path,
    pdf_quality: Path,
) -> dict[str, pa.Table]:
    split = read_csv(decoupage)
    population = select_population(firds_index)
    useful = {row["isin"] for row in population} | set(split.column("isin").to_pylist())
    firds = pq.read_table(firds_index)
    firds = firds.filter(pc.is_in(firds["isin"], value_set=pa.array(sorted(useful))))

    documents = pq.read_table(registre)
    new_isins = set(
        split.filter(pc.equal(split["jeu"], "test_nouveaux_emetteurs")).column("isin").to_pylist()
    )
    new_rows = new_issuer_documents(new_issuer_cache, new_isins)
    lei_by_isin = dict(zip(firds["isin"].to_pylist(), firds["issuer_lei"].to_pylist(), strict=True))
    for row in new_rows:
        row["issuer_lei"] = lei_by_isin.get(row["isin"], "")
    schema = pa.schema([(name, pa.string()) for name in REGISTER_COLUMNS])
    documents = pa.concat_tables([documents, pa.Table.from_pylist(new_rows, schema=schema)])

    return {
        "firds_titres": _strings(firds),
        "population": pa.table(
            {
                "isin": [row["isin"] for row in population],
                "issuer_lei": [row["issuer_lei"] for row in population],
            }
        ),
        "registre_documents": _strings(documents),
        "decoupage": split,
        "pdf_controle": read_csv(pdf_quality),
    }


def load_duckdb(tables: dict[str, pa.Table], database: Path) -> None:
    """Remplace les tables brutes ; la base se reconstruit entièrement à chaque chargement."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database)) as connection:
        connection.execute(f"create schema if not exists {RAW_SCHEMA}")
        for name, table in tables.items():
            # Un nom de table ne peut pas être un paramètre SQL : il est vérifié contre la liste.
            if name not in RAW_TABLES:
                raise ValueError(f"Table brute inconnue : {name}")
            connection.register("source_table", table)
            sql = f"create or replace table {RAW_SCHEMA}.{name} as select * from source_table"  # noqa: S608
            connection.execute(sql)
            connection.unregister("source_table")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firds-date", required=True)
    parser.add_argument("--registre-date", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--collecte-dir", type=Path, default=Path("docs/v0.1-collecte/data"))
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    args = parser.parse_args()
    tables = build_raw_tables(
        firds_index=args.data_dir / "interim" / "firds" / f"dette-{args.firds_date}.parquet",
        registre=args.data_dir / "interim" / "registre" / f"documents-{args.registre_date}.parquet",
        new_issuer_cache=args.data_dir
        / "raw"
        / "registre"
        / f"{args.registre_date}-nouveaux-emetteurs",
        decoupage=args.collecte_dir / "decoupage-documents.csv",
        pdf_quality=args.collecte_dir / "pdf-controle.csv",
    )
    load_duckdb(tables, args.database)
    for name, table in tables.items():
        print(f"{RAW_SCHEMA}.{name} : {table.num_rows} lignes")


if __name__ == "__main__":
    main()
