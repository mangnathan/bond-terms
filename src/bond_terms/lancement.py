"""Lance un extracteur sur un jeu et compare ses valeurs à FIRDS.

Usage :
    uv run python -m bond_terms.lancement --extracteur regles

Seul le développement peut être lancé ici. Les jeux de test seront ouverts une seule fois, par
une commande à part, une fois les extracteurs figés (ADR 0001). Les extractions vont dans
`data/interim/extractions` ; le résumé versionné ne contient que des comptes par champ.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from bond_terms import regles
from bond_terms.comparaison import compare
from bond_terms.extraction import FIELDS, Extraction, accepted
from bond_terms.ocr import pages_by_document

DEVELOPMENT = "developpement"
Extractor = Callable[[str, list[str]], Extraction]
EXTRACTORS: dict[str, tuple[Extractor, str]] = {"regles": (regles.extract, regles.VERSION)}

TRUTH_SQL = """
select document_id, isin, devise, date_echeance, type_taux, taux_fixe, reference_taux_variable,
       duree_reference, marge_points_de_base, valeur_nominale, montant_nominal_total,
       montant_comparable, rang
from verite_terrain
where jeu = ? and isin_cite
order by document_id, isin
"""


def score(extractions: dict[str, Extraction], truth: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un verdict par couple document-ISIN et par champ."""
    rows = []
    for couple in truth:
        extraction = extractions[couple["document_id"]]
        values = {name: accepted(extraction.champs.get(name)) for name in FIELDS}
        verdict = compare(values, couple)
        rows.append({"document_id": couple["document_id"], "isin": couple["isin"], **verdict})
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary = {}
    for name in FIELDS:
        compared = [row[name] for row in rows if row[name] is not None]
        summary[name] = {"justes": sum(compared), "compares": len(compared)}
    return summary


def main() -> None:  # pragma: no cover - lit les vraies données
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extracteur", choices=sorted(EXTRACTORS), required=True)
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages.parquet"))
    parser.add_argument(
        "--ocr-pages", type=Path, default=Path("data/interim/textes/pages-ocr.parquet")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/extractions"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.2-extraction/data"))
    args = parser.parse_args()

    extract, version = EXTRACTORS[args.extracteur]
    with duckdb.connect(str(args.database), read_only=True) as connection:
        truth = connection.sql(TRUTH_SQL, params=[DEVELOPMENT]).to_arrow_table().to_pylist()
    documents = sorted({couple["document_id"] for couple in truth})
    pages = pages_by_document(pq.read_table(args.pages), pq.read_table(args.ocr_pages))
    extractions = {doc: extract(doc, pages[doc]) for doc in documents}

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.extracteur}-{version}-{DEVELOPMENT}.jsonl"
    with output.open("w", encoding="utf-8", newline="\n") as f:
        for doc in documents:
            f.write(json.dumps(extractions[doc].to_dict(), ensure_ascii=False) + "\n")

    rows = score(extractions, truth)
    summary = {
        "extracteur": args.extracteur,
        "version": version,
        "jeu": DEVELOPMENT,
        "documents": len(documents),
        "couples": len(rows),
        "champs": summarize(rows),
    }
    target = args.summary_dir / f"{args.extracteur}-{DEVELOPMENT}.json"
    target.write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    for name, counts in summary["champs"].items():
        share = counts["justes"] / counts["compares"] if counts["compares"] else 0
        print(f"{name:16} {counts['justes']:4} / {counts['compares']:4}  {share:6.1%}")


if __name__ == "__main__":
    main()
