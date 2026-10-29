"""Lance un extracteur sur le développement et compare ses valeurs à FIRDS.

Usage :
    uv run python -m bond_terms.lancement --extracteur regles
    uv run --group llm --env-file .env python -m bond_terms.lancement --extracteur llm \\
        --modele gemini-3.5-flash-lite

Seul le développement peut être lancé ici. Les jeux de test seront ouverts une seule fois, par
une commande à part, une fois les extracteurs figés (ADR 0001). Les extractions vont dans
`data/interim/extractions` ; le résumé versionné ne contient que des comptes par champ, la
latence et les jetons.

Pour le LLM, la clé et le plafond local viennent de l'environnement (`.env`, jamais versionné) :
GEMINI_API_KEY, BOND_TERMS_LLM_MAX_JOUR (requêtes par jour, sous le plafond gratuit) et
BOND_TERMS_LLM_INTERVALLE_S (secondes entre deux requêtes). Au premier refus pour quota, les
documents restants passent par l'extracteur à règles et sont marqués comme tels.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from bond_terms import llm, regles
from bond_terms.comparaison import compare
from bond_terms.extraction import FIELDS, Extraction, accepted
from bond_terms.ocr import pages_by_document

DEVELOPMENT = "developpement"
# Jeux déjà ouverts, devenus le développement de la v0.3 (ADR 0003). Le nouveau test n'en fait
# pas partie : seule la commande d'ouverture peut le lire.
KNOWN_SETS = (DEVELOPMENT, "test", "test_nouveaux_emetteurs")
FALLBACK = "repli sur les règles"
# Extracteur : identifiant du document, ses pages et les ISIN qu'il couvre.
Extract = Callable[[str, list[str], list[str]], Extraction]

TRUTH_SQL = """
select document_id, isin, devise, date_echeance, type_taux, taux_fixe, reference_taux_variable,
       duree_reference, marge_points_de_base, valeur_nominale, montant_nominal_total,
       montant_comparable, rang
from verite_terrain
where jeu = ? and isin_cite and not produit_structure
order by document_id, isin
"""


def run(
    documents: dict[str, list[str]], pages: dict[str, list[str]], extract: Extract
) -> tuple[dict[str, Extraction], str]:
    """Extrait chaque document. Au premier refus pour quota, tous les documents restants passent
    par les règles ; si le service reste indisponible, seul le document concerné y passe."""
    extractions: dict[str, Extraction] = {}
    stopped = ""
    for document_id in sorted(documents):
        isins = documents[document_id]
        reason = stopped
        if not stopped:
            try:
                extractions[document_id] = extract(document_id, pages[document_id], isins)
                continue
            except llm.QuotaError as error:
                stopped = reason = str(error)
            except llm.UnavailableError as error:
                reason = str(error)
        fallback = regles.extract(document_id, pages[document_id])
        fallback.remarque = f"{FALLBACK} : {reason}"
        extractions[document_id] = fallback
    return extractions, stopped


SAMPLE_SEED = 20261026


def sample(documents: dict[str, list[str]], size: int) -> dict[str, list[str]]:
    """Tirage fixe : le même échantillon pour tous les extracteurs comparés."""
    rng = random.Random(SAMPLE_SEED)  # noqa: S311 - tirage reproductible, pas de la sécurité
    chosen = rng.sample(sorted(documents), min(size, len(documents)))
    return {document_id: documents[document_id] for document_id in sorted(chosen)}


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


def percentile(values: Iterable[float], share: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, round(share * (len(ordered) - 1)))
    return round(ordered[index], 3)


def costs(extractions: Iterable[Extraction]) -> dict[str, Any]:
    """Latence et jetons par document, et nombre de documents passés par le repli."""
    done = list(extractions)
    seconds = [e.secondes for e in done if e.secondes is not None]
    tokens_in = [e.jetons_entree for e in done if e.jetons_entree is not None]
    tokens_out = [e.jetons_sortie for e in done if e.jetons_sortie is not None]
    return {
        "latence_mediane_s": percentile(seconds, 0.5),
        "latence_p95_s": percentile(seconds, 0.95),
        "jetons_entree_moyenne": round(statistics.mean(tokens_in)) if tokens_in else None,
        "jetons_sortie_moyenne": round(statistics.mean(tokens_out)) if tokens_out else None,
        "documents_en_repli": sum(e.remarque.startswith(FALLBACK) for e in done),
        "formats_refuses": sum(e.remarque.startswith("format refusé") for e in done),
        "cout_euros": 0,
    }


def llm_extractor(model_name: str, cache_dir: Path) -> tuple[Extract, str]:  # pragma: no cover
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY est requise (voir .env.example)")
    limits = llm.LIMITS[model_name]
    # `.env` peut durcir les plafonds du code, jamais les relâcher.
    per_day = min(limits.per_day, int(os.environ.get("BOND_TERMS_LLM_MAX_JOUR") or limits.per_day))
    interval = max(limits.min_interval_s, float(os.environ.get("BOND_TERMS_LLM_INTERVALLE_S") or 0))
    model = llm.GeminiModel(model_name, key, interval)
    budget = llm.Budget(cache_dir / "quota", model_name, per_day)
    extractor = llm.Extractor(model, cache_dir, budget)
    return extractor.extract, f"{model_name}/{llm.PROMPT_VERSION}"


def main() -> None:  # pragma: no cover - lit les vraies données
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extracteur", choices=["regles", "llm"], required=True)
    parser.add_argument("--modele", choices=llm.MODELS)
    parser.add_argument("--jeu", choices=KNOWN_SETS, default=DEVELOPMENT)
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages.parquet"))
    parser.add_argument(
        "--ocr-pages", type=Path, default=Path("data/interim/textes/pages-ocr.parquet")
    )
    parser.add_argument(
        "--echantillon", type=int, help="nombre de documents tirés au hasard (graine fixe)"
    )
    parser.add_argument("--llm-cache", type=Path, default=Path("data/interim/llm"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/extractions"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.3-revue/data"))
    args = parser.parse_args()

    if args.extracteur == "llm":
        if not args.modele:
            raise SystemExit("--modele est requis pour l'extracteur llm")
        extract, version = llm_extractor(args.modele, args.llm_cache)
        # La version du prompt figure dans le nom : les sorties de la v0.2 ne sont pas écrasées.
        name = f"llm-{args.modele}-{llm.PROMPT_VERSION}"
    else:

        def extract(document_id: str, pages: list[str], isins: list[str]) -> Extraction:
            return regles.extract(document_id, pages)

        version, name = regles.VERSION, regles.VERSION

    with duckdb.connect(str(args.database), read_only=True) as connection:
        truth = connection.sql(TRUTH_SQL, params=[args.jeu]).to_arrow_table().to_pylist()
    documents: dict[str, list[str]] = defaultdict(list)
    for couple in truth:
        documents[couple["document_id"]].append(couple["isin"])
    if args.echantillon:
        documents = sample(documents, args.echantillon)
        truth = [couple for couple in truth if couple["document_id"] in documents]
        name = f"{name}-echantillon{args.echantillon}"
    pages = pages_by_document(pq.read_table(args.pages), pq.read_table(args.ocr_pages))
    extractions, stopped = run(documents, pages, extract)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{name}-{args.jeu}.jsonl"
    with output.open("w", encoding="utf-8", newline="\n") as f:
        for document_id in sorted(extractions):
            f.write(json.dumps(extractions[document_id].to_dict(), ensure_ascii=False) + "\n")

    rows = score(extractions, truth)
    summary: dict[str, Any] = {
        "extracteur": name,
        "version": version,
        "jeu": args.jeu,
        "documents": len(extractions),
        "couples": len(rows),
        "arret": stopped,
        "couts": costs(extractions.values()),
        "champs": summarize(rows),
    }
    args.summary_dir.mkdir(parents=True, exist_ok=True)
    target = args.summary_dir / f"{name}-{args.jeu}.json"
    target.write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    for field, counts in summary["champs"].items():
        share = counts["justes"] / counts["compares"] if counts["compares"] else 0
        print(f"{field:16} {counts['justes']:4} / {counts['compares']:4}  {share:6.1%}")
    print(json.dumps(summary["couts"], ensure_ascii=False))
    if stopped:
        print(f"Arrêt de l'extracteur : {stopped}")


if __name__ == "__main__":
    main()
