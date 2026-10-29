"""Contrôle du rattachement entre un document et un ISIN (ADR 0002).

Usage (après `python -m bond_terms.ocr`) :
    uv run python -m bond_terms.rattachement

Le registre rattache parfois un document à un ISIN qu'il ne cite pas : le document porte alors
sur une autre obligation. Un couple n'entre dans la vérité terrain que si le document cite l'ISIN.
Le contrôle ne regarde que l'identifiant, jamais les valeurs à extraire. Le détail par couple reste
hors du dépôt ; le résumé versionné ne contient que des comptes par jeu.

Un second contrôle (ADR 0003) écarte les produits structurés que FIRDS déclare comme des
obligations classiques : documents dont le titre ou une rubrique déclare un coupon indexé
applicable. Il ne regarde que le type de document, jamais les valeurs.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from bond_terms.documents import normalize
from bond_terms.entrepot import read_csv
from bond_terms.ocr import merge_pages
from bond_terms.valeurs import contains_isin

COLUMNS = ("document_id", "isin", "jeu", "isin_cite", "produit_structure")

# Coupon indexé déclaré applicable, dans le titre de l'émission ou dans une rubrique. Mesuré sur
# les jeux connus : 21 documents, tous des produits structurés, et aucun autre document touché.
STRUCTURED = re.compile(
    r"titres a coupon (?:et a remboursement )?indexe[^:]{0,60}:\s*applicable"
    r"|coupon indexe\s*:\s*applicable"
    r"|base d'interet\s*:\s*coupon indexe"
    r"|index[- ]linked interest[^:]{0,60}:\s*applicable"
    r"|emission d.{0,40}de titres a coupon (?:et a remboursement )?indexe"
)
# Le titre et les rubriques d'intérêt figurent au début du document.
STRUCTURED_SCOPE = 60_000


def is_structured(normalized: str) -> bool:
    return STRUCTURED.search(re.sub(r"\s+", " ", normalized)[:STRUCTURED_SCOPE]) is not None


def check(couples: list[dict[str, str]], texts: Mapping[str, str]) -> list[dict[str, str]]:
    """Un document sans texte, même après OCR, ne cite rien : le couple est écarté."""
    normalized: dict[str, str] = {}
    rows = []
    for couple in couples:
        doc = couple["document_id"]
        if doc not in normalized:
            normalized[doc] = normalize(texts.get(doc, ""))
        cited = contains_isin(normalized[doc], couple["isin"])
        rows.append(
            {
                "document_id": doc,
                "isin": couple["isin"],
                "jeu": couple["jeu"],
                "isin_cite": str(cited),
                "produit_structure": str(is_structured(normalized[doc])),
            }
        )
    return rows


def summarize(rows: list[dict[str, str]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for split in sorted({r["jeu"] for r in rows}):
        subset = [r for r in rows if r["jeu"] == split]
        cited = sum(r["isin_cite"] == "True" for r in subset)
        summary[split] = {
            "couples": len(subset),
            "isin_cite": cited,
            "anomalies_de_rattachement": len(subset) - cited,
            "produits_structures": sum(r["produit_structure"] == "True" for r in subset),
        }
    return summary


def main() -> None:  # pragma: no cover - lit les vraies données
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages.parquet"))
    parser.add_argument(
        "--ocr-pages", type=Path, default=Path("data/interim/textes/pages-ocr.parquet")
    )
    parser.add_argument(
        "--split", type=Path, default=Path("docs/v0.1-collecte/data/decoupage-documents.csv")
    )
    parser.add_argument("--output", type=Path, default=Path("data/interim/rattachement.csv"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.2-extraction/data"))
    args = parser.parse_args()

    texts = merge_pages(pq.read_table(args.pages), pq.read_table(args.ocr_pages))
    couples = read_csv(args.split).select(["document_id", "isin", "jeu"]).to_pylist()
    rows = check(couples, texts)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    args.summary_dir.mkdir(parents=True, exist_ok=True)
    (args.summary_dir / "rattachement-resume.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
