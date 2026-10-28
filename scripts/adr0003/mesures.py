"""Mesures de l'ADR 0003, sur les trois jeux déjà ouverts, devenus le développement de la v0.3.

Usage :
    uv run python scripts/adr0003/mesures.py

1. Citation en deux morceaux : valeurs refusées que la règle « intitulé + valeur » récupère,
   justes ou fausses.
2. Taux hybrides (fixe puis variable, révisable) : type déclaré par FIRDS, par année et émetteur.
3. File de revue : part des documents envoyés en revue et documents erronés attrapés.
4. Rapport d'exceptions : valeurs citées et vérifiées qui diffèrent de FIRDS.
Le résumé ne contient que des comptes.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from bond_terms.comparaison import compare
from bond_terms.extraction import compact
from bond_terms.lancement import TRUTH_SQL
from bond_terms.ocr import pages_by_document
from bond_terms.regles import LABELS, flatten, rubric, until_next_rubric

SETS = ("developpement", "test", "test_nouveaux_emetteurs")
EXTRACTIONS = Path("data/interim/extractions")
OUTPUT = Path("docs/v0.3-revue/data/mesures-adr0003.json")
WINDOW = 400
CORE = ("devise", "date_echeance", "type_taux", "taux_fixe", "valeur_nominale", "rang")
HYBRID = re.compile(r"fixe?\s?d\s?(?:/|to)\s?float|resettable|reset")

Doc = dict[str, Any]


def load(name: str) -> dict[str, Doc]:
    lines = (EXTRACTIONS / name).read_text(encoding="utf-8").splitlines()
    return {row["document_id"]: row for row in map(json.loads, lines)}


def values(extraction: Doc) -> dict[str, str | None]:
    return {k: None if v["refusee"] else v["valeur"] for k, v in extraction["champs"].items()}


def two_part_page(citation: str, pages: list[str]) -> int | None:
    """Page où l'intitulé précède la valeur de moins de WINDOW caractères, ou None."""
    if ":" not in citation:
        return None
    label, value = citation.split(":", 1)
    head = compact(label).strip("-\"'.,;:()0123456789ivx ")
    tail = compact(value).strip("-\"'.,;: ")
    if len(head) < 6 or len(tail) < 8:
        return None
    for number, page in enumerate(pages, start=1):
        text = compact(page)
        position = text.find(tail)
        while position >= 0:
            if text.rfind(head, max(0, position - WINDOW), position) >= 0:
                return number
            position = text.find(tail, position + 1)
    return None


def main() -> None:
    pages = pages_by_document(
        pq.read_table("data/interim/textes/pages.parquet"),
        pq.read_table("data/interim/textes/pages-ocr.parquet"),
    )
    texts = {doc: flatten("\n".join(parts)) for doc, parts in pages.items()}
    recovery: Counter[str] = Counter()
    hybrid_year: dict[int, Counter[str]] = defaultdict(Counter)
    review: dict[str, dict[str, Any]] = {}
    exceptions: Counter[str] = Counter()
    with duckdb.connect("data/entrepot/bond_terms.duckdb", read_only=True) as connection:
        dates = dict(
            connection.sql("select document_id, date_approbation from documents").fetchall()
        )
        for name in SETS:
            truth = connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            model = load(f"llm-gemini-3.5-flash-lite-{name}.jsonl")
            rules = load(f"regles-{name}.jsonl")
            flagged = caught = wrong_docs = 0
            for couple in truth:
                document_id = couple["document_id"]
                llm, rule = values(model[document_id]), values(rules[document_id])
                raw = {k: v["valeur"] for k, v in model[document_id]["champs"].items()}
                raw_verdict, verdict = compare(raw, couple), compare(llm, couple)
                for field, value in model[document_id]["champs"].items():
                    if value["refusee"] and raw_verdict.get(field) is not None:
                        kind = "juste" if raw_verdict[field] else "fausse"
                        found = two_part_page(value["citation"] or "", pages[document_id])
                        recovery[f"{kind} {'récupérée' if found else 'toujours refusée'}"] += 1
                    if verdict.get(field) is False and value["valeur"] and not value["refusee"]:
                        exceptions[field] += 1
                found_rubric = rubric(texts[document_id], LABELS["base"], 400)
                zone = until_next_rubric(found_rubric[2]) if found_rubric else ""
                title = re.search(
                    r"issue of .{0,200}?(?:notes|obligations) due", texts[document_id]
                )
                zone += " " + (title.group(0) if title else "")
                if HYBRID.search(zone):
                    hybrid_year[dates[document_id].year][couple["type_taux"]] += 1
                missing = any(
                    llm.get(k) is None
                    for k in CORE
                    if not (k == "taux_fixe" and llm.get("type_taux") == "floating")
                )
                disagree = any(llm.get(k) and rule.get(k) and llm[k] != rule[k] for k in CORE)
                wrong = any(v is False for v in verdict.values())
                flagged += missing or disagree
                wrong_docs += wrong
                caught += wrong and (missing or disagree)
            review[name] = {
                "documents": len(truth),
                "envoyes_en_revue": flagged,
                "documents_errones": wrong_docs,
                "errones_attrapes": caught,
            }
    summary = {
        "citation_en_deux_morceaux": dict(recovery),
        "hybrides_type_firds_par_annee": {str(y): dict(c) for y, c in sorted(hybrid_year.items())},
        "file_de_revue": review,
        "exceptions_par_champ": dict(exceptions),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
