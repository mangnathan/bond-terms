"""Nouveau jeu de test de la v0.3 : documents d'émetteurs jamais vus, tirés avant toute extraction.

Usage :
    uv run python -m bond_terms.nouveau_test --firds-date 2026-10-17 --collecte-le 2026-10-28

Règle de l'ADR 0003 : parmi les obligations classiques à ISIN français des émetteurs autres que les
huit étudiés, on exclut les 300 obligations tirées en v0.1 et toute obligation déjà présente dans
un jeu ; on tire 450 obligations (graine 20261028), on collecte leurs documents d'émission, on
écarte tout document déjà présent dans un jeu, et on en garde au plus 150, tirés avec la même
graine. Le jeu est versionné avant tout téléchargement de PDF. Le résumé ne contient que des
comptes.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from bond_terms.decoupage import NEW_ISSUER_BONDS
from bond_terms.decoupage import SEED as SEED_V01
from bond_terms.entrepot import read_csv
from bond_terms.esma import PoliteClient
from bond_terms.population import select_other_issuers_bonds
from bond_terms.registre import ISSUE_DOCUMENT_TYPES, document_rows, fetch_documents

SEED = 20261028
BONDS = 450
DOCUMENTS = 150
SET_NAME = "test_v03"
COLUMNS = (
    "document_id",
    "isin",
    "issuer_lei",
    "document_type",
    "approval_date",
    "rfss_file_id",
    "rfss_checksum",
    "languages",
    "jeu",
)

Fetch = Callable[[str], list[dict[str, Any]]]


def drawn_in_v01(pool: list[dict[str, str]]) -> set[str]:
    """Les 300 obligations tirées en v0.1, retrouvées en rejouant le même tirage."""
    rng = random.Random(SEED_V01)  # noqa: S311 - tirage reproductible, pas de la sécurité
    return {bond["isin"] for bond in rng.sample(pool, min(NEW_ISSUER_BONDS, len(pool)))}


def draw(
    pool: list[dict[str, str]],
    excluded_isins: set[str],
    known_documents: set[str],
    fetch: Fetch,
) -> tuple[dict[str, int], list[dict[str, str]]]:
    rng = random.Random(SEED)  # noqa: S311 - tirage reproductible, pas de la sécurité
    remaining = [bond for bond in pool if bond["isin"] not in excluded_isins]
    bonds = rng.sample(remaining, min(BONDS, len(remaining)))
    rows: list[dict[str, str]] = []
    for bond in sorted(bonds, key=lambda b: b["isin"]):
        rows += [
            row
            for row in document_rows(bond["isin"], bond["issuer_lei"], fetch(bond["isin"]))
            if row["document_type"] in ISSUE_DOCUMENT_TYPES
            and row["document_id"] not in known_documents
        ]
    document_ids = sorted({row["document_id"] for row in rows})
    kept = set(rng.sample(document_ids, min(DOCUMENTS, len(document_ids))))
    stats = {
        "vivier_obligations": len(pool),
        "obligations_exclues": len(pool) - len(remaining),
        "obligations_tirees": len(bonds),
        "obligations_avec_document": len({row["isin"] for row in rows}),
        "documents_trouves": len(document_ids),
        "documents_gardes": len(kept),
    }
    chosen = [row | {"jeu": SET_NAME} for row in rows if row["document_id"] in kept]
    return stats, chosen


def write_split(rows: Iterable[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["document_id"], r["isin"])))


def main() -> None:  # pragma: no cover - interroge le registre
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--firds-date", required=True)
    parser.add_argument("--collecte-le", required=True, help="date de la collecte (AAAA-MM-JJ)")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--split-v01", type=Path, default=Path("docs/v0.1-collecte/data/decoupage-documents.csv")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("docs/v0.3-revue/data"))
    args = parser.parse_args()

    target = args.output_dir / "nouveau-test-documents.csv"
    if target.exists():
        raise SystemExit(f"Le nouveau jeu de test est déjà figé : {target}")
    firds_index = args.data_dir / "interim" / "firds" / f"dette-{args.firds_date}.parquet"
    pool = select_other_issuers_bonds(firds_index)
    known = read_csv(args.split_v01).to_pylist()
    excluded = drawn_in_v01(pool) | {row["isin"] for row in known}
    cache = args.data_dir / "raw" / "registre" / f"{args.collecte_le}-nouveau-test"
    client = PoliteClient()

    def fetch(isin: str) -> list[dict[str, Any]]:
        return fetch_documents(client, isin, cache)

    stats, rows = draw(pool, excluded, {row["document_id"] for row in known}, fetch)
    write_split(rows, target)
    summary = {"graine": SEED, "collecte_le": args.collecte_le, **stats}
    (args.output_dir / "nouveau-test-resume.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
