"""File de revue humaine (ADR 0003).

Usage :
    uv run python -m bond_terms.revue

Un document part en revue si le LLM n'a pas justifié une valeur clé (devise, échéance, type de
taux, taux fixe pour un taux fixe ou hybride, valeur nominale, rang). La règle n'utilise que ce
que l'outil sait : elle s'applique telle quelle en production, sans vérité terrain. Chaque
document en revue garde ses raisons, et les désaccords avec l'extracteur à règles y sont affichés
pour le relecteur, sans envoyer à eux seuls un document en revue : sur les émetteurs jamais vus,
où les règles lisent mal, ils poussaient la file au-dessus du plafond de 30 % (précision de
l'ADR 0003, décidée sur les jeux connus avant l'ouverture du nouveau test).

Indicateurs : part des documents envoyés en revue (au plus 30 %, seuil du cadrage) et part des
documents erronés que la revue attrape. Un document est erroné si au moins un de ses champs
comparés est faux, montant exclu : le montant de FIRDS est l'encours, pas le montant émis
(ADR 0002), et ses écarts vont au rapport d'exceptions.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import duckdb

from bond_terms import llm, regles
from bond_terms.comparaison import compare
from bond_terms.evaluation import load_extractions
from bond_terms.extraction import FIELDS, Extraction, accepted
from bond_terms.lancement import KNOWN_SETS, TRUTH_SQL

CORE = ("devise", "date_echeance", "type_taux", "taux_fixe", "valeur_nominale", "rang")
MAX_SHARE = 0.30


def reasons(model: Extraction) -> list[str]:
    """Raisons d'envoyer le document en revue ; vide s'il n'y part pas."""
    found = {name: accepted(value) for name, value in model.champs.items()}
    return [
        f"{name} : valeur non justifiée"
        for name in CORE
        if found.get(name) is None
        and not (name == "taux_fixe" and found.get("type_taux") == "floating")
    ]


def disagreements(model: Extraction, rules: Extraction) -> list[str]:
    """Désaccords avec l'extracteur à règles, affichés au relecteur à titre d'information."""
    found = {name: accepted(value) for name, value in model.champs.items()}
    other = {name: accepted(value) for name, value in rules.champs.items()}
    return [
        f"{name} : règles {other[name]}, LLM {found[name]}"
        for name in CORE
        if found.get(name) is not None
        and other.get(name) is not None
        and other[name] != found[name]
    ]


def queue(model: dict[str, Extraction], rules: dict[str, Extraction]) -> dict[str, list[str]]:
    """Documents envoyés en revue, avec leurs raisons puis les désaccords à titre d'information."""
    flagged = {}
    for document_id in sorted(model):
        if found := reasons(model[document_id]):
            notes = disagreements(model[document_id], rules[document_id])
            flagged[document_id] = found + [f"information, {note}" for note in notes]
    return flagged


def wrong_documents(model: dict[str, Extraction], truth: list[dict[str, Any]]) -> set[str]:
    """Documents dont au moins un champ comparé est faux, montant exclu."""
    wrong = set()
    for couple in truth:
        extraction = model[couple["document_id"]]
        verdict = compare({name: accepted(extraction.champs.get(name)) for name in FIELDS}, couple)
        if any(ok is False for name, ok in verdict.items() if name != "montant"):
            wrong.add(couple["document_id"])
    return wrong


def indicators(flagged: dict[str, list[str]], documents: int, wrong: set[str]) -> dict[str, Any]:
    share = len(flagged) / documents if documents else 0.0
    caught = len(wrong & set(flagged))
    return {
        "documents": documents,
        "envoyes_en_revue": len(flagged),
        "part_en_revue": round(share, 4),
        "sous_le_plafond": share <= MAX_SHARE,
        "documents_errones": len(wrong),
        "errones_attrapes": caught,
        "part_des_errones_attrapes": round(caught / len(wrong), 4) if wrong else None,
    }


def main() -> None:  # pragma: no cover - lit les vraies données
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--extractions", type=Path, default=Path("data/interim/extractions"))
    parser.add_argument("--jeux", nargs="+", default=list(KNOWN_SETS), choices=KNOWN_SETS)
    parser.add_argument("--file-dir", type=Path, default=Path("data/interim/revue"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.3-revue/data"))
    args = parser.parse_args()

    model_prefix = f"llm-gemini-3.5-flash-lite-{llm.PROMPT_VERSION}"
    summary: dict[str, Any] = {}
    args.file_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(args.database), read_only=True) as connection:
        for name in args.jeux:
            truth = connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            model = load_extractions(args.extractions / f"{model_prefix}-{name}.jsonl")
            rules = load_extractions(args.extractions / f"{regles.VERSION}-{name}.jsonl")
            flagged = queue(model, rules)
            # La file contient des valeurs lues : elle reste hors du dépôt.
            with (args.file_dir / f"file-{name}.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(["document_id", "raisons"])
                writer.writerows((doc, " ; ".join(found)) for doc, found in flagged.items())
            documents = len({couple["document_id"] for couple in truth})
            summary[name] = indicators(flagged, documents, wrong_documents(model, truth))
    args.summary_dir.mkdir(parents=True, exist_ok=True)
    target = args.summary_dir / "revue-connus.json"
    target.write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
