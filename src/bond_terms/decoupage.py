"""Découpage des documents en développement et test, fixé avant toute extraction (ADR 0001).

Usage :
    uv run python -m bond_terms.decoupage --firds-date AAAA-MM-JJ --registre-date AAAA-MM-JJ

Le découpage n'utilise que les métadonnées du registre (dates d'approbation) : aucun PDF n'est
téléchargé. Il produit deux fichiers versionnés, la liste des documents avec leur jeu et un
résumé, qui figent ce que la v0.2 pourra regarder et ce qu'elle ne verra qu'une fois.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from bond_terms.esma import PoliteClient
from bond_terms.population import ISSUERS, select_other_issuers_bonds
from bond_terms.registre import ISSUE_DOCUMENT_TYPES, document_rows, fetch_documents

SEED = 20261025
TEST_SHARE = 0.30
NEW_ISSUER_BONDS = 300
NEW_ISSUER_DOCUMENTS = 100
DEVELOPMENT = "developpement"
TEST = "test"
NEW_ISSUERS_TEST = "test_nouveaux_emetteurs"
EXCLUDED_TIMED = "exclu_chronometre"
COLUMNS = [
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


def cutoff_date(dates: list[str], share: float = TEST_SHARE) -> str:
    """Plus récente date telle que les documents de cette date ou après font au moins la part."""
    counts = Counter(dates)
    covered = 0
    for date in sorted(counts, reverse=True):
        covered += counts[date]
        if covered >= share * len(dates):
            return date
    raise ValueError("aucun document")


def split_main(rows: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    """Affecte chaque document au développement ou au test, selon sa date d'approbation."""
    dates = {r["document_id"]: r["approval_date"] for r in rows}
    cutoff = cutoff_date(list(dates.values()))
    return cutoff, [
        r | {"jeu": TEST if r["approval_date"] >= cutoff else DEVELOPMENT} for r in rows
    ]


def timed_documents(sheet: Path) -> set[tuple[str, str]]:
    """(ISIN, identifiant de fichier) des documents de la saisie chronométrée."""
    with sheet.open(encoding="utf-8") as f:
        return {
            (
                row["isin"],
                urllib.parse.parse_qs(urllib.parse.urlsplit(row["lien_pdf"]).query)["fileId"][0],
            )
            for row in csv.DictReader(f)
        }


def exclude_timed(rows: list[dict[str, str]], timed: set[tuple[str, str]]) -> list[dict[str, str]]:
    """Un document chronométré qui tombe dans le test en est retiré (ADR 0001)."""
    return [
        r | {"jeu": EXCLUDED_TIMED}
        if r["jeu"] == TEST and (r["isin"], r["rfss_file_id"]) in timed
        else r
        for r in rows
    ]


def sample_new_issuers(
    client: PoliteClient, firds_index: Path, cache_dir: Path
) -> tuple[dict[str, int], list[dict[str, str]]]:
    """Second jeu de test : documents d'obligations d'émetteurs jamais vus, tirés au hasard."""
    # Tirage d'évaluation reproductible, sans enjeu de sécurité.
    rng = random.Random(SEED)  # noqa: S311
    pool = select_other_issuers_bonds(firds_index)
    bonds = rng.sample(pool, min(NEW_ISSUER_BONDS, len(pool)))
    rows: list[dict[str, str]] = []
    for bond in sorted(bonds, key=lambda b: b["isin"]):
        docs = fetch_documents(client, bond["isin"], cache_dir)
        rows += [
            r
            for r in document_rows(bond["isin"], bond["issuer_lei"], docs)
            if r["document_type"] in ISSUE_DOCUMENT_TYPES
        ]
    document_ids = sorted({r["document_id"] for r in rows})
    kept = set(rng.sample(document_ids, min(NEW_ISSUER_DOCUMENTS, len(document_ids))))
    stats = {
        "vivier_obligations": len(pool),
        "obligations_tirees": len(bonds),
        "obligations_avec_document": len({r["isin"] for r in rows}),
        "documents_trouves": len(document_ids),
        "documents_gardes": len(kept),
    }
    return stats, [r | {"jeu": NEW_ISSUERS_TEST} for r in rows if r["document_id"] in kept]


def summarize(
    cutoff: str, rows: list[dict[str, str]], new_issuers: dict[str, int]
) -> dict[str, Any]:
    documents_by_set: Counter[str] = Counter()
    for split in (DEVELOPMENT, TEST, NEW_ISSUERS_TEST, EXCLUDED_TIMED):
        documents_by_set[split] = len({r["document_id"] for r in rows if r["jeu"] == split})
    by_issuer = []
    for lei, issuer in ISSUERS.items():
        mine = [r for r in rows if r["issuer_lei"] == lei]
        by_issuer.append(
            {
                "emetteur": issuer.name,
                DEVELOPMENT: len({r["document_id"] for r in mine if r["jeu"] == DEVELOPMENT}),
                TEST: len({r["document_id"] for r in mine if r["jeu"] == TEST}),
            }
        )
    return {
        "graine": SEED,
        "part_du_test": TEST_SHARE,
        "date_de_coupure": cutoff,
        "documents_par_jeu": dict(documents_by_set),
        "documents_chronometres_dans_le_test": documents_by_set[EXCLUDED_TIMED],
        "par_emetteur": by_issuer,
        "nouveaux_emetteurs": new_issuers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firds-date", required=True)
    parser.add_argument("--registre-date", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs/v0.1-collecte/data"))
    parser.add_argument(
        "--timed-sheet",
        type=Path,
        default=Path("docs/v0.0-cadrage/data/chronometrage-saisie-manuelle.csv"),
    )
    args = parser.parse_args()
    firds_index = args.data_dir / "interim" / "firds" / f"dette-{args.firds_date}.parquet"
    registre = args.data_dir / "interim" / "registre" / f"documents-{args.registre_date}.parquet"

    main_rows = [
        r for r in pq.read_table(registre).to_pylist() if r["document_type"] in ISSUE_DOCUMENT_TYPES
    ]
    cutoff, rows = split_main(main_rows)
    rows = exclude_timed(rows, timed_documents(args.timed_sheet))
    cache_dir = args.data_dir / "raw" / "registre" / f"{args.registre_date}-nouveaux-emetteurs"
    new_stats, new_rows = sample_new_issuers(PoliteClient(), firds_index, cache_dir)
    rows += new_rows

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "decoupage-documents.csv").open(
        "w", newline="", encoding="utf-8"
    ) as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            sorted(rows, key=lambda r: (r["jeu"], r["approval_date"], r["document_id"]))
        )
    summary = summarize(cutoff, rows, new_stats)
    (args.output_dir / "decoupage-resume.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
