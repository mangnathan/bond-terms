"""Analyse des erreurs du LLM sur les jeux de test, faite après leur ouverture.

Usage :
    uv run python scripts/v0.2/analyse_erreurs_test.py

Cette analyse ne change ni les extracteurs ni la décision, prise selon la règle figée. Elle
explique la baisse entre le développement et le test :
- valeurs justes refusées par la vérification des citations (mise en page sur deux colonnes, où
  l'intitulé et la valeur sont séparés dans le texte extrait du PDF) ;
- types de taux comptés faux sur les titres à taux fixe puis variable, ou révisable, que FIRDS
  déclare en taux variable alors que la convention majoritaire du développement était le taux fixe.
Le résumé ne contient que des comptes.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from bond_terms.comparaison import compare
from bond_terms.extraction import FIELDS
from bond_terms.lancement import TRUTH_SQL

SETS = ("test", "test_nouveaux_emetteurs")
MODEL = "gemini-3.5-flash-lite"
EXTRACTIONS = Path("data/interim/extractions")
OUTPUT = Path("docs/v0.2-extraction/data/analyse-erreurs-test.json")
HYBRID = re.compile(r"fixe?\s?d.{0,3}(?:/|to).{0,3}float")


def load(path: Path) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return {row["document_id"]: row for row in rows}


def analyse(truth: list[dict[str, Any]], extractions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    right_verified = right_raw = compared = 0
    refused_right: Counter[str] = Counter()
    type_errors: Counter[str] = Counter()
    for couple in truth:
        champs = extractions[couple["document_id"]]["champs"]
        verified = compare(
            {k: None if v["refusee"] else v["valeur"] for k, v in champs.items()}, couple
        )
        raw = compare({k: v["valeur"] for k, v in champs.items()}, couple)
        for name in FIELDS:
            if verified[name] is None:
                continue
            compared += 1
            right_verified += bool(verified[name])
            right_raw += bool(raw[name])
            if raw[name] and not verified[name]:
                refused_right[name] += 1
        if verified["type_taux"] is False:
            citation = re.sub(r"\s+", " ", champs["type_taux"]["citation"] or "").lower()
            kind = (
                "fixe puis variable"
                if HYBRID.search(citation)
                else "révisable"
                if "reset" in citation
                else "autre"
            )
            type_errors[kind] += 1
    return {
        "paires_comparees": compared,
        "exactitude_avec_verification": round(right_verified / compared, 4),
        "valeurs_justes_avant_verification": round(right_raw / compared, 4),
        "valeurs_justes_refusees_par_champ": dict(refused_right),
        "erreurs_de_type_de_taux": dict(type_errors),
    }


def main() -> None:
    summary: dict[str, Any] = {"modele": MODEL}
    with duckdb.connect("data/entrepot/bond_terms.duckdb", read_only=True) as connection:
        for name in SETS:
            truth = connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            extractions = load(EXTRACTIONS / f"llm-{MODEL}-{name}.jsonl")
            summary[name] = analyse(truth, extractions)
    OUTPUT.write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
