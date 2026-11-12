"""Mesures des corrections de l'ADR 0005, sur les cinq jeux déjà ouverts.

Usage :
    uv run python scripts/adr0005/mesures_corrections.py

Les réponses du modèle sont relues dans le cache avec le code de la v1.0 (taux à la française,
vérification v4) : aucune requête n'est envoyée, un modèle qui refuse tout appel le garantit.
Trois configurations sont comparées sur les mêmes réponses :
- v0.4 : sorties publiées en v0.4 (ancienne conversion, vérification v3) ;
- conversion : nouvelle conversion des taux, vérification v3 ;
- v1.0 : nouvelle conversion et vérification v4 (taux et échéance contrôlés dans leur citation).
Le résumé ne contient que des comptes.
"""

from __future__ import annotations

import copy
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from bond_terms import llm, regles
from bond_terms.comparaison import compare
from bond_terms.evaluation import global_accuracy, load_extractions
from bond_terms.exceptions import exceptions
from bond_terms.extraction import FIELDS, Extraction, accepted, verify
from bond_terms.lancement import KNOWN_SETS, RUN_DIR, TRUTH_SQL, known_pages, score
from bond_terms.ocr import pages_by_document
from bond_terms.revue import indicators, queue, wrong_documents

SETS = (*KNOWN_SETS, "test_v04")
MODEL = "gemini-3.5-flash-lite"
OUTPUT = Path("docs/v1.0-publique/data/mesures-adr0005.json")


class NoCall:
    """Modèle qui refuse tout appel : la mesure ne lit que le cache."""

    name = MODEL

    def generate(self, system: str, user: str) -> llm.Reply:
        raise RuntimeError("réponse absente du cache : aucune requête n'est envoyée")


def wrong_and_right(
    extractions: dict[str, Extraction], truth: list[dict[str, Any]]
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for couple in truth:
        extraction = extractions[couple["document_id"]]
        values = {name: accepted(extraction.champs.get(name)) for name in FIELDS}
        for name, ok in compare(values, couple).items():
            if values[name] is not None and ok is not None:
                counts["justes_acceptees" if ok else "fausses_acceptees"] += 1
    return counts


def summary(
    extractions: dict[str, Extraction], rules: dict[str, Extraction], truth: list[dict[str, Any]]
) -> dict[str, Any]:
    documents = len({c["document_id"] for c in truth})
    return {
        "exactitude": global_accuracy(score(extractions, truth)),
        **wrong_and_right(extractions, truth),
        "revue": indicators(
            queue(extractions, rules), documents, wrong_documents(extractions, truth)
        ),
        "exceptions": len(exceptions(extractions, truth, {})),
    }


def main() -> None:
    pages = known_pages()
    pages |= pages_by_document(
        pq.read_table("data/interim/textes/pages-v04.parquet"),
        pq.read_table("data/interim/textes/pages-ocr-v04.parquet"),
    )
    budget = llm.Budget(Path(tempfile.mkdtemp()), MODEL, 0)
    extractor = llm.Extractor(NoCall(), Path("data/interim/llm"), budget)
    prefix = f"llm-{MODEL}-{llm.PROMPT_VERSION}"
    result: dict[str, Any] = {}
    with duckdb.connect("data/entrepot/bond_terms.duckdb", read_only=True) as connection:
        for name in SETS:
            truth = connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            published = load_extractions(RUN_DIR / f"{prefix}-{name}.jsonl")
            rules = load_extractions(RUN_DIR / f"{regles.VERSION}-{name}.jsonl")
            isins: dict[str, list[str]] = {}
            for couple in truth:
                isins.setdefault(couple["document_id"], []).append(couple["isin"])
            # Les documents lus par les règles à l'ouverture le restent : seule la lecture change.
            reread = {
                d: extractor.extract(d, pages[d], isins[d]) if e.extracteur == "llm" else e
                for d, e in published.items()
            }
            conversion = copy.deepcopy(reread)
            for d, e in conversion.items():
                verify(e, pages[d], rates_and_dates=False)
            result[name] = {
                "v0.4": summary(published, rules, truth),
                "conversion": summary(conversion, rules, truth),
                "v1.0": summary(reread, rules, truth),
            }
            print(name, json.dumps({k: v["exactitude"] for k, v in result[name].items()}))
    result["requetes_envoyees"] = extractor.calls
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
