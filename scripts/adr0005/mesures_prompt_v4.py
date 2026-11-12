"""Effet du prompt v4 (niveau B, tranche et série) sur le niveau A, sur deux jeux déjà ouverts.

Usage :
    uv run --group llm --env-file .env python scripts/adr0005/mesures_prompt_v4.py

Les tests de la v0.3 et de la v0.4 sont relus par le modèle avec le prompt v4, sous les plafonds
existants ; le résultat est comparé à la mesure du prompt v3 avec le même code
(`mesures-adr0005.json`, configuration « v1.0 »). Pour le niveau B, la lecture du modèle est
rapprochée de la seule recherche de la rubrique : un contrôle de cohérence, pas une vérité.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent))
from mesures_corrections import summary  # noqa: E402

from bond_terms import llm  # noqa: E402
from bond_terms.evaluation import load_extractions  # noqa: E402
from bond_terms.extraction import accepted  # noqa: E402
from bond_terms.lancement import RUN_DIR, TRUTH_SQL, known_pages, llm_extractor, run  # noqa: E402
from bond_terms.niveau_b import rubric  # noqa: E402
from bond_terms.ocr import pages_by_document  # noqa: E402

SETS = ("test_v03", "test_v04")
MODEL = "gemini-3.5-flash-lite"
BASELINE = Path("docs/v1.0-publique/data/mesures-adr0005.json")
OUTPUT = Path("docs/v1.0-publique/data/mesures-prompt-v4.json")


def main() -> None:
    pages = known_pages()
    pages |= pages_by_document(
        pq.read_table("data/interim/textes/pages-v04.parquet"),
        pq.read_table("data/interim/textes/pages-ocr-v04.parquet"),
    )
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    extract, _ = llm_extractor(MODEL, Path("data/interim/llm"))
    result: dict[str, Any] = {"prompt": llm.PROMPT_VERSION}
    with duckdb.connect("data/entrepot/bond_terms.duckdb", read_only=True) as connection:
        for name in SETS:
            truth = connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            rules = load_extractions(RUN_DIR / f"regles-2-{name}.jsonl")
            documents: dict[str, list[str]] = {}
            for couple in truth:
                documents.setdefault(couple["document_id"], []).append(couple["isin"])
            model, stopped = run(documents, pages, extract)
            clause = Counter(
                f"{rubric(pages[d])[0]} / {accepted(e.champs.get('remboursement_emetteur'))}"
                for d, e in model.items()
            )
            result[name] = {
                "prompt_v3": baseline[name]["v1.0"],
                "prompt_v4": summary(model, rules, truth),
                "replis": sum(e.extracteur != "llm" for e in model.values()),
                "arret_quota": bool(stopped),
                "rubrique_contre_lecture_du_modele": dict(sorted(clause.items())),
            }
            v3, v4 = (
                result[name][k]["exactitude"]["exactitude"] for k in ("prompt_v3", "prompt_v4")
            )
            print(f"{name} : v3 {v3:.4f}, v4 {v4:.4f}", flush=True)
    OUTPUT.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
