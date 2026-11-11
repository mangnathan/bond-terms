"""Instantané servi par l'API (ADR 0004).

Usage :
    uv run python -m bond_terms.instantane

L'API ne lit jamais l'entrepôt ni les extractions : elle charge au démarrage un seul fichier JSON,
construit ici. Pour chaque ISIN, il donne les documents lus par le LLM, chaque valeur avec sa
citation, sa page et son statut, le statut de revue du document et ses exceptions avec FIRDS ;
il donne aussi les indicateurs de surveillance par jeu. Il ne contient ni PDF ni texte de
document, seulement des citations courtes.

L'instantané sert aussi de mémoire à la collecte hebdomadaire (`bond_terms.collecte`) : la liste
des documents déjà vus, écartés compris, et l'historique des collectes. Le premier instantané est
construit ici à partir des extractions déjà faites, sans aucune requête au modèle.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from bond_terms import llm, regles
from bond_terms.evaluation import load_extractions
from bond_terms.exceptions import exceptions
from bond_terms.extraction import FIELDS, Extraction, Value
from bond_terms.lancement import FALLBACK, KNOWN_SETS, RUN_DIR, TRUTH_SQL
from bond_terms.revue import queue

MODEL = "gemini-3.5-flash-lite"
SETS = (*KNOWN_SETS, "test_v04")
FORMAT = 2


def status(value: Value | None) -> str:
    if value is None or value.valeur is None:
        return "absente"
    return "refusee" if value.refusee else "acceptee"


def document_entry(
    extraction: Extraction, set_name: str, reasons: list[str], gaps: list[dict[str, Any]]
) -> dict[str, Any]:
    champs = {}
    for name in FIELDS:
        value = extraction.champs.get(name)
        champs[name] = {
            "valeur": value.valeur if value else None,
            "citation": value.citation if value else None,
            "page": value.page if value else None,
            "statut": status(value),
        }
    return {
        "document_id": extraction.document_id,
        "jeu": set_name,
        "champs": champs,
        # Les raisons commencent par les valeurs non justifiées ; les désaccords avec les règles
        # suivent, à titre d'information.
        "en_revue": bool(reasons),
        "raisons_revue": reasons,
        "exceptions": [
            {
                "champ": gap["champ"],
                "valeur_firds": None if gap["valeur_firds"] is None else str(gap["valeur_firds"]),
                "valeur_lue": gap["valeur_lue"],
            }
            for gap in gaps
        ],
    }


def set_indicators(entries: list[dict[str, Any]], fallbacks: int) -> dict[str, Any]:
    """Indicateurs de surveillance d'un jeu : ceux que l'ADR 0004 suit à chaque collecte.

    Un document qui couvre plusieurs ISIN a une entrée par ISIN : il n'est compté qu'une fois."""
    by_document: dict[str, dict[str, Any]] = {}
    with_exception: set[str] = set()
    for entry in entries:
        by_document[entry["document_id"]] = entry
        if entry["exceptions"]:
            with_exception.add(entry["document_id"])
    documents = len(by_document)
    given = [
        c for e in by_document.values() for c in e["champs"].values() if c["statut"] != "absente"
    ]
    refused = sum(c["statut"] == "refusee" for c in given)

    def share(count: int, total: int) -> float | None:
        return round(count / total, 4) if total else None

    return {
        "documents": documents,
        "part_en_revue": share(sum(e["en_revue"] for e in by_document.values()), documents),
        "part_valeurs_refusees": share(refused, len(given)),
        "part_documents_avec_exception": share(len(with_exception), documents),
        "documents_en_repli": fallbacks,
    }


def build(
    sets: dict[str, tuple[list[dict[str, Any]], dict[str, Extraction], dict[str, Extraction]]],
    created: dt.datetime,
    commit: str,
    seen: Iterable[str] = (),
) -> dict[str, Any]:
    """`sets` : pour chaque jeu, la vérité terrain (couples document-ISIN), les sorties du LLM
    et celles des règles. `seen` : documents déjà examinés sans entrer dans un jeu (rattachement
    erroné, produit structuré), à ne pas reprendre."""
    examined = set(seen) | {c["document_id"] for truth, _, _ in sets.values() for c in truth}
    bonds: dict[str, list[dict[str, Any]]] = defaultdict(list)
    indicators = {}
    for name, (truth, model, rules) in sets.items():
        flagged = queue(model, rules)
        gaps: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in exceptions(model, truth, {}):
            gaps[(row["document_id"], row["isin"])].append(row)
        entries = []
        for couple in truth:
            document_id, isin = couple["document_id"], couple["isin"]
            entry = document_entry(
                model[document_id], name, flagged.get(document_id, []), gaps[(document_id, isin)]
            )
            bonds[isin].append(entry)
            entries.append(entry)
        fallbacks = sum(e.remarque.startswith(FALLBACK) for e in model.values())
        indicators[name] = set_indicators(entries, fallbacks)
    return {
        "format": FORMAT,
        "cree_le": created.isoformat(timespec="seconds"),
        "commit": commit,
        "extracteurs": {"llm": f"{MODEL}/{llm.PROMPT_VERSION}", "regles": regles.VERSION},
        "obligations": dict(sorted(bonds.items())),
        "indicateurs": indicators,
        "documents_vus": sorted(examined),
        "collectes": [],
    }


def merge(
    previous: dict[str, Any], weekly: dict[str, Any], collection: dict[str, Any]
) -> dict[str, Any]:
    """Instantané de la semaine : le précédent, plus les documents nouvellement lus. Un document
    déjà présent pour un ISIN n'est jamais ajouté deux fois."""
    bonds = {isin: list(documents) for isin, documents in previous["obligations"].items()}
    for isin, documents in weekly["obligations"].items():
        known = {d["document_id"] for d in bonds.get(isin, [])}
        bonds[isin] = bonds.get(isin, []) + [d for d in documents if d["document_id"] not in known]
    return {
        **weekly,
        "obligations": dict(sorted(bonds.items())),
        "indicateurs": previous["indicateurs"] | weekly["indicateurs"],
        "documents_vus": sorted(set(previous["documents_vus"]) | set(weekly["documents_vus"])),
        "collectes": [*previous["collectes"], collection],
    }


def read(path: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("format") != FORMAT:
        raise SystemExit(f"{path} : format {snapshot.get('format')}, {FORMAT} attendu")
    return snapshot


def write(snapshot: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    path.write_bytes((text + "\n").encode("utf-8"))


def main() -> None:  # pragma: no cover - lit les vraies données
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--extractions", type=Path, default=RUN_DIR)
    parser.add_argument("--commit", default="", help="commit des extracteurs, consigné tel quel")
    parser.add_argument("--sortie", type=Path, default=Path("data/instantane/instantane.json"))
    # Registre de la collecte de la v0.1 : tous ses documents ont déjà été examinés, même ceux
    # écartés avant l'extraction.
    parser.add_argument(
        "--registre", type=Path, default=Path("data/interim/registre/documents-2026-10-23.parquet")
    )
    args = parser.parse_args()

    prefix = f"llm-{MODEL}-{llm.PROMPT_VERSION}"
    sets = {}
    with duckdb.connect(str(args.database), read_only=True) as connection:
        for name in SETS:
            truth = connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            model = load_extractions(args.extractions / f"{prefix}-{name}.jsonl")
            rules = load_extractions(args.extractions / f"{regles.VERSION}-{name}.jsonl")
            sets[name] = (truth, model, rules)
    seen = pq.read_table(args.registre, columns=["document_id"]).column("document_id").to_pylist()
    snapshot = build(sets, dt.datetime.now(dt.UTC), args.commit, seen)
    write(snapshot, args.sortie)
    print(
        f"{len(snapshot['obligations'])} ISIN, {len(snapshot['documents_vus'])} documents vus ; "
        + json.dumps(snapshot["indicateurs"], ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
