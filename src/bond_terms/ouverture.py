"""Ouverture unique du nouveau jeu de test de la v0.3 (ADR 0003).

Usage :
    uv run --group llm --env-file .env python -m bond_terms.ouverture --ouvrir-le-test

Les extracteurs sont figés (versions consignées dans l'ADR 0003). Avant toute extraction, un
registre daté est écrit avec le commit et les versions : une seconde ouverture est refusée. Si le
service tombe en cours de route, `--reprendre` relance l'extraction tant qu'aucun résultat n'a été
produit ; le cache évite tout second envoi d'un document.

Une seule extraction donne quatre résultats : l'évaluation (LLM contre règles), la même mesure
avec la vérification de la v0.2 (la vérification v2 n'est gardée que si elle n'accepte pas plus
de valeurs fausses), les indicateurs de la file de revue, et la fiche des exceptions, que le
relecteur remplit ensuite. L'ouverture des jeux de la v0.2 se rejoue avec le tag v0.2.
"""

from __future__ import annotations

import argparse
import copy
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
from bond_terms.comparaison import compare
from bond_terms.documents import normalize
from bond_terms.evaluation import _rounded, evaluate, global_accuracy
from bond_terms.exceptions import exceptions, summarize, write_sheet
from bond_terms.extraction import FIELDS, Extraction, accepted, verify
from bond_terms.lancement import FALLBACK, KNOWN_SETS, TRUTH_SQL, costs, llm_extractor, run, score
from bond_terms.ocr import pages_by_document
from bond_terms.revue import indicators, queue, wrong_documents

TEST_SETS = ("test_v03",)
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
        "verification": "v2 (citation en deux morceaux)",
        "jeux": list(TEST_SETS),
    }


def wrong_accepted(extractions: dict[str, Extraction], truth: list[dict[str, Any]]) -> int:
    """Valeurs acceptées par la vérification mais fausses."""
    count = 0
    for couple in truth:
        extraction = extractions[couple["document_id"]]
        values = {name: accepted(extraction.champs.get(name)) for name in FIELDS}
        verdict = compare(values, couple)
        count += sum(ok is False and values[name] is not None for name, ok in verdict.items())
    return count


def with_v02_verification(
    extractions: dict[str, Extraction], pages: dict[str, list[str]]
) -> dict[str, Extraction]:
    """Les mêmes sorties, vérifiées comme en v0.2 (sans citation en deux morceaux)."""
    replay = copy.deepcopy(extractions)
    for document_id, extraction in replay.items():
        verify(extraction, pages[document_id], two_parts=False)
    return replay


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


def write_jsonl(extractions: dict[str, Extraction], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for document_id in sorted(extractions):
            f.write(json.dumps(extractions[document_id].to_dict(), ensure_ascii=False) + "\n")


def main() -> None:  # pragma: no cover - ouvre le vrai jeu de test
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ouvrir-le-test", action="store_true", required=True)
    parser.add_argument("--reprendre", action="store_true")
    # Répétition : la même commande sur un jeu déjà connu, sorties dans un dossier temporaire.
    parser.add_argument("--repetition-sur", choices=KNOWN_SETS)
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages-v03.parquet"))
    parser.add_argument(
        "--ocr-pages", type=Path, default=Path("data/interim/textes/pages-ocr-v03.parquet")
    )
    parser.add_argument("--llm-cache", type=Path, default=Path("data/interim/llm"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/extractions"))
    parser.add_argument("--sheet-dir", type=Path, default=Path("data/interim/exceptions"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.3-revue/data"))
    args = parser.parse_args()

    sets: tuple[str, ...] = TEST_SETS
    if args.repetition_sur:
        # Une répétition ne doit jamais écrire à côté des vrais résultats.
        rehearsal = Path("data/interim/repetition-ouverture")
        if Path("docs") in args.summary_dir.parents or args.summary_dir == Path("docs"):
            args.summary_dir = rehearsal
        args.output_dir = args.sheet_dir = rehearsal
        args.pages = Path("data/interim/textes/pages.parquet")
        args.ocr_pages = Path("data/interim/textes/pages-ocr.parquet")
        args.summary_dir.mkdir(parents=True, exist_ok=True)
        sets = (args.repetition_sur,)
    register = args.summary_dir / "ouverture-du-test.json"
    results = args.summary_dir / "evaluation-test-v03.json"
    check_opening(register, results, args.reprendre)
    commit = current_commit()
    if not register.exists():
        record = opening_record(commit, dt.datetime.now(dt.UTC))
        register.write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))

    extract_llm, _ = llm_extractor(MODEL, args.llm_cache)
    pages = pages_by_document(pq.read_table(args.pages), pq.read_table(args.ocr_pages))
    texts = {doc: normalize("\n".join(parts)) for doc, parts in pages.items()}
    summary: dict[str, Any] = {"commit": commit}
    with duckdb.connect(str(args.database), read_only=True) as connection:
        truths = {
            name: connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            for name in sets
        }
    missing: list[str] = []
    sheets: dict[str, list[dict[str, Any]]] = {}
    for name in sets:
        truth = truths[name]
        documents: dict[str, list[str]] = defaultdict(list)
        for couple in truth:
            documents[couple["document_id"]].append(couple["isin"])
        rules = {d: regles.extract(d, pages[d]) for d in sorted(documents)}
        model, _ = run(documents, pages, extract_llm)
        missing += incomplete(model)
        write_jsonl(rules, args.output_dir / f"{regles.VERSION}-{name}.jsonl")
        write_jsonl(model, args.output_dir / f"llm-{MODEL}-{llm.PROMPT_VERSION}-{name}.jsonl")
        replay = with_v02_verification(model, pages)
        sheets[name] = exceptions(model, truth, texts)
        flagged = queue(model, rules)
        summary[name] = {
            **evaluate(truth, rules, model),
            "verification": {
                "v2": global_accuracy(score(model, truth)),
                "v1_de_la_v0.2": global_accuracy(score(replay, truth)),
                "valeurs_fausses_acceptees_v2": wrong_accepted(model, truth),
                "valeurs_fausses_acceptees_v1": wrong_accepted(replay, truth),
            },
            "revue": indicators(flagged, len(documents), wrong_documents(model, truth)),
            "exceptions": summarize(sheets[name]),
            "couts_llm": costs(model.values()),
            "couts_regles": costs(rules.values()),
        }
    if missing:
        # Résultats incomplets : rien n'est écrit ni affiché, la reprise finira l'extraction.
        raise SystemExit(
            f"{len(missing)} documents non lus par le LLM (quota ou service indisponible). "
            "Relancer avec --reprendre : seuls ces documents seront envoyés."
        )
    for name, rows in sheets.items():
        # La fiche contient des valeurs lues : elle reste hors du dépôt.
        write_sheet(rows, args.sheet_dir / f"exceptions-{name}.csv")
    results.write_bytes(
        (json.dumps(_rounded(summary), ensure_ascii=False, indent=2, default=str) + "\n").encode(
            "utf-8"
        )
    )
    main_test = summary[sets[0]]
    print(json.dumps(_rounded(main_test["comparaison"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
