"""Rapport d'exceptions : écarts entre FIRDS et le document (ADR 0003).

Usage :
    uv run python -m bond_terms.exceptions

Une exception est une valeur que le LLM justifie par une citation retrouvée dans le document, mais
qui diffère de la valeur de FIRDS. Pour chacune, le rapport donne le document, la page, la valeur
de FIRDS, la valeur lue et sa citation, et une colonne à remplir par le relecteur : « vrai écart »
si le document dit bien la valeur lue, « lecture fausse » sinon. Le seuil du cadrage, au moins
80 % de vrais écarts, se calcule sur ces réponses.

Une aide automatique est jointe : la valeur de FIRDS figure-t-elle quelque part dans le document ?
Elle oriente le relecteur, sans le remplacer. Les fiches contiennent des valeurs lues : elles
restent hors du dépôt ; le résumé versionné ne donne que des comptes.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from bond_terms import llm
from bond_terms.comparaison import compare
from bond_terms.documents import normalize
from bond_terms.evaluation import load_extractions
from bond_terms.extraction import FIELDS, Extraction, accepted
from bond_terms.lancement import KNOWN_SETS, TRUTH_SQL
from bond_terms.valeurs import amount_pattern, contains, date_pattern, rate_pattern

MIN_TRUE_SHARE = 0.80
TRUE_GAP = "vrai écart"
WRONG_READING = "lecture fausse"
COLUMNS = (
    "document_id",
    "isin",
    "champ",
    "valeur_firds",
    "valeur_lue",
    "page",
    "citation",
    "valeur_firds_dans_le_document",
    "verdict",
)
TRUTH_COLUMN = {
    "devise": "devise",
    "date_echeance": "date_echeance",
    "type_taux": "type_taux",
    "taux_fixe": "taux_fixe",
    "reference_taux": "reference_taux_variable",
    "duree_reference": "duree_reference",
    "marge_pb": "marge_points_de_base",
    "valeur_nominale": "valeur_nominale",
    "montant": "montant_nominal_total",
    "rang": "rang",
}


def firds_value_in_document(field: str, value: Any, text: str) -> str:
    """« oui » ou « non » quand la recherche est possible, vide sinon."""
    if value is None:
        return ""
    if field == "date_echeance" and isinstance(value, dt.date) and value.year < 9999:
        return "oui" if contains(date_pattern(value), text) else "non"
    if field in ("valeur_nominale", "montant"):
        return "oui" if contains(amount_pattern(float(value)), text) else "non"
    if field == "taux_fixe":
        return "oui" if contains(rate_pattern(float(value)), text) else "non"
    return ""


def exceptions(
    model: dict[str, Extraction], truth: list[dict[str, Any]], texts: dict[str, str]
) -> list[dict[str, Any]]:
    rows = []
    for couple in truth:
        extraction = model[couple["document_id"]]
        values = {name: accepted(extraction.champs.get(name)) for name in FIELDS}
        verdict = compare(values, couple)
        for field, ok in verdict.items():
            if ok is not False or values[field] is None:
                continue
            value = extraction.champs[field]
            expected = couple[TRUTH_COLUMN[field]]
            rows.append(
                {
                    "document_id": couple["document_id"],
                    "isin": couple["isin"],
                    "champ": field,
                    "valeur_firds": expected,
                    "valeur_lue": values[field],
                    "page": value.page,
                    "citation": value.citation,
                    "valeur_firds_dans_le_document": firds_value_in_document(
                        field, expected, texts.get(couple["document_id"], "")
                    ),
                    "verdict": "",
                }
            )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_field = Counter(row["champ"] for row in rows)
    checked = [row for row in rows if row["verdict"] in (TRUE_GAP, WRONG_READING)]
    true_gaps = sum(row["verdict"] == TRUE_GAP for row in checked)
    share = true_gaps / len(checked) if checked else None
    return {
        "exceptions": len(rows),
        "documents": len({row["document_id"] for row in rows}),
        "par_champ": dict(by_field.most_common()),
        "verifiees": len(checked),
        "vrais_ecarts": true_gaps,
        "part_de_vrais_ecarts": round(share, 4) if share is not None else None,
        "seuil_atteint": share >= MIN_TRUE_SHARE if share is not None else None,
    }


def write_sheet(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:  # pragma: no cover - lit les vraies données
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--extractions", type=Path, default=Path("data/interim/extractions"))
    parser.add_argument("--jeux", nargs="+", default=list(KNOWN_SETS), choices=KNOWN_SETS)
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages.parquet"))
    parser.add_argument(
        "--ocr-pages", type=Path, default=Path("data/interim/textes/pages-ocr.parquet")
    )
    parser.add_argument("--sheet-dir", type=Path, default=Path("data/interim/exceptions"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.3-revue/data"))
    args = parser.parse_args()

    import pyarrow.parquet as pq

    from bond_terms.ocr import merge_pages

    texts = {
        doc: normalize(text)
        for doc, text in merge_pages(
            pq.read_table(args.pages), pq.read_table(args.ocr_pages)
        ).items()
    }
    prefix = f"llm-gemini-3.5-flash-lite-{llm.PROMPT_VERSION}"
    summary: dict[str, Any] = {}
    with duckdb.connect(str(args.database), read_only=True) as connection:
        for name in args.jeux:
            truth = connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            model = load_extractions(args.extractions / f"{prefix}-{name}.jsonl")
            rows = exceptions(model, truth, texts)
            write_sheet(rows, args.sheet_dir / f"exceptions-{name}.csv")
            summary[name] = summarize(rows)
    args.summary_dir.mkdir(parents=True, exist_ok=True)
    target = args.summary_dir / "exceptions-connus.json"
    target.write_bytes(
        (json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
