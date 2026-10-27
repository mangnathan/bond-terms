"""Ouverture unique des deux jeux de test (ADR 0001 et 0002).

Usage :
    uv run --group llm --env-file .env python -m bond_terms.ouverture --ouvrir-le-test

Les deux extracteurs sont figés (versions consignées dans l'ADR 0002). Avant toute extraction,
un registre daté est écrit avec le commit et les versions : une seconde ouverture est refusée.
Si le service tombe en cours de route, `--reprendre` relance l'extraction tant qu'aucun résultat
n'a été produit ; le cache évite tout second envoi d'un document. La décision entre les règles
et le LLM se prend sur le test principal ; le test des émetteurs jamais vus est publié à côté.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from bond_terms import llm, regles
from bond_terms.evaluation import _rounded, evaluate
from bond_terms.extraction import Extraction
from bond_terms.lancement import FALLBACK, TRUTH_SQL, costs, llm_extractor, run
from bond_terms.ocr import pages_by_document

TEST_SETS = ("test", "test_nouveaux_emetteurs")
MODEL = "gemini-3.5-flash-lite"


class OpeningRefusedError(RuntimeError):
    """Le test a déjà été ouvert, ou ses résultats existent déjà."""


def check_opening(register: Path, results: Path, resume: bool) -> None:
    """Une seule ouverture : refus si des résultats existent, ou si le registre existe sans
    demande explicite de reprise."""
    if results.exists():
        raise OpeningRefusedError(f"le test a déjà été ouvert : {results} existe")
    if register.exists() and not resume:
        raise OpeningRefusedError(
            f"ouverture déjà commencée ({register}) : relancer avec --reprendre pour la finir"
        )


def incomplete(extractions: dict[str, Extraction]) -> list[str]:
    """Documents que le LLM n'a pas lus (quota ou service indisponible) : tant qu'il en reste,
    aucun résultat n'est écrit, pour ne pas juger le LLM sur la lecture des règles."""
    return sorted(d for d, e in extractions.items() if e.remarque.startswith(FALLBACK))


def opening_record(commit: str, now: dt.datetime) -> dict[str, Any]:
    return {
        "ouvert_le": now.isoformat(timespec="seconds"),
        "commit": commit,
        "regles": regles.VERSION,
        "llm": f"{MODEL}/{llm.PROMPT_VERSION}",
        "jeux": list(TEST_SETS),
    }


def current_commit() -> str:  # pragma: no cover - lit le dépôt
    """Commit des extracteurs figés ; refus si un fichier suivi est modifié."""
    git = shutil.which("git")
    if git is None:
        raise OpeningRefusedError("git est introuvable : le commit ne peut pas être consigné")
    # Arguments fixes, aucune saisie : rien ne peut être injecté dans la commande.
    output = subprocess.run(  # noqa: S603
        [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    dirty = subprocess.run(  # noqa: S603
        [git, "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    )
    if dirty.stdout.strip():
        raise OpeningRefusedError("des fichiers suivis sont modifiés : committer avant d'ouvrir")
    return output.stdout.strip()


def main() -> None:  # pragma: no cover - ouvre les vrais jeux de test
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ouvrir-le-test", action="store_true", required=True)
    parser.add_argument("--reprendre", action="store_true")
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages.parquet"))
    parser.add_argument(
        "--ocr-pages", type=Path, default=Path("data/interim/textes/pages-ocr.parquet")
    )
    parser.add_argument("--llm-cache", type=Path, default=Path("data/interim/llm"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/extractions"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.2-extraction/data"))
    args = parser.parse_args()

    register = args.summary_dir / "ouverture-du-test.json"
    results = args.summary_dir / "evaluation-test.json"
    check_opening(register, results, args.reprendre)
    commit = current_commit()
    if not register.exists():
        record = opening_record(commit, dt.datetime.now(dt.UTC))
        register.write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))

    extract_llm, _ = llm_extractor(MODEL, args.llm_cache)
    pages = pages_by_document(pq.read_table(args.pages), pq.read_table(args.ocr_pages))
    summary: dict[str, Any] = {"commit": commit}
    with duckdb.connect(str(args.database), read_only=True) as connection:
        truths = {
            name: connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            for name in TEST_SETS
        }
    missing: list[str] = []
    for name in TEST_SETS:
        truth = truths[name]
        documents: dict[str, list[str]] = defaultdict(list)
        for couple in truth:
            documents[couple["document_id"]].append(couple["isin"])
        rules = {d: regles.extract(d, pages[d]) for d in sorted(documents)}
        model, _ = run(documents, pages, extract_llm)
        missing += incomplete(model)
        for label, extractions in (("regles", rules), (f"llm-{MODEL}", model)):
            output = args.output_dir / f"{label}-{name}.jsonl"
            with output.open("w", encoding="utf-8", newline="\n") as f:
                for document_id in sorted(extractions):
                    line = json.dumps(extractions[document_id].to_dict(), ensure_ascii=False)
                    f.write(line + "\n")
        summary[name] = {
            **evaluate(truth, rules, model),
            "couts_llm": costs(model.values()),
            "couts_regles": costs(rules.values()),
        }
    if missing:
        # Résultats incomplets : rien n'est écrit ni affiché, la reprise finira l'extraction.
        raise SystemExit(
            f"{len(missing)} documents non lus par le LLM (quota ou service indisponible). "
            "Relancer avec --reprendre : seuls ces documents seront envoyés."
        )
    results.write_bytes(
        (json.dumps(_rounded(summary), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    main_test = summary["test"]["comparaison"]
    print(json.dumps(_rounded(main_test), ensure_ascii=False))
