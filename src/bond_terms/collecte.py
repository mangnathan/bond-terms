"""Collecte hebdomadaire des nouveaux documents d'émission (ADR 0004).

Usage (GitHub Actions, chaque lundi) :
    uv run --group ocr --group llm python -m bond_terms.collecte --precedent instantane.json

1. Publication complète de FIRDS la plus récente, population recalculée (huit émetteurs).
2. Registre interrogé pour chaque obligation : seuls les documents d'émission absents de
   l'instantané précédent sont traités, ceux déjà écartés compris.
3. Téléchargement, lecture, OCR des pages sans texte, contrôles du rattachement et des produits
   structurés.
4. Vérité terrain par les modèles dbt de l'entrepôt, dans une base propre à la semaine : une seule
   définition, celle de l'évaluation.
5. Extraction par les règles et le LLM, sous les plafonds existants, puis revue et exceptions.
6. Nouvel instantané (le précédent plus les documents de la semaine) et bilan de la semaine.

Garde-fou : au-delà de MAX_NEW_DOCUMENTS nouveaux documents, la collecte s'arrête sans rien
écrire. Le flux mesuré est de deux à trois documents par semaine ; un tel nombre signale une
mémoire perdue, qui ferait tout relire.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from bond_terms import instantane, ocr, regles, surveillance
from bond_terms.decoupage import COLUMNS as SPLIT_COLUMNS
from bond_terms.documents import QUALITY_COLUMNS, DocumentRef, process
from bond_terms.entrepot import as_strings, load_duckdb
from bond_terms.extraction import Extraction
from bond_terms.lancement import FALLBACK, TRUTH_SQL, llm_extractor, run
from bond_terms.population import select_population
from bond_terms.rattachement import check
from bond_terms.registre import COLUMNS as REGISTER_COLUMNS
from bond_terms.registre import ISSUE_DOCUMENT_TYPES, document_rows, fetch_documents

SET_NAME = "collecte"
MAX_NEW_DOCUMENTS = 60
PROJECT = Path(__file__).resolve().parents[2] / "entrepot"
PAGE_SCHEMA = pa.schema(
    [("document_id", pa.string()), ("page", pa.string()), ("texte", pa.string())]
)


class TooManyDocumentsError(RuntimeError):
    """Trop de nouveaux documents d'un coup : la mémoire de la collecte est probablement perdue."""


def new_couples(register: Iterable[dict[str, str]], seen: set[str]) -> list[dict[str, str]]:
    """Couples ISIN-document du registre dont le document d'émission n'a jamais été examiné, au
    format du découpage."""
    couples = []
    for row in register:
        if row["document_type"] in ISSUE_DOCUMENT_TYPES and row["document_id"] not in seen:
            couples.append({name: row.get(name, "") for name in SPLIT_COLUMNS} | {"jeu": SET_NAME})
    return sorted(couples, key=lambda c: (c["document_id"], c["isin"]))


def references(couples: list[dict[str, str]]) -> list[DocumentRef]:
    """Un téléchargement par document, même s'il couvre plusieurs ISIN."""
    refs: dict[str, DocumentRef] = {}
    for c in couples:
        refs.setdefault(
            c["document_id"],
            DocumentRef(c["document_id"], c["rfss_file_id"], c["rfss_checksum"], SET_NAME),
        )
    if len(refs) > MAX_NEW_DOCUMENTS:
        raise TooManyDocumentsError(
            f"{len(refs)} nouveaux documents, plus de {MAX_NEW_DOCUMENTS} : la mémoire de la "
            "collecte est probablement perdue, rien n'est traité"
        )
    return sorted(refs.values(), key=lambda r: r.document_id)


def _table(rows: list[dict[str, Any]], columns: Iterable[str]) -> pa.Table:
    """Table brute en texte, comme les fichiers CSV de la collecte : True s'écrit « True »."""
    names = list(columns)
    data = [
        {name: "" if row.get(name) is None else str(row.get(name)) for name in names}
        for row in rows
    ]
    return pa.Table.from_pylist(data, schema=pa.schema([(name, pa.string()) for name in names]))


def raw_tables(
    firds_index: Path,
    population: list[dict[str, str]],
    register: list[dict[str, str]],
    couples: list[dict[str, str]],
    quality: list[dict[str, Any]],
    links: list[dict[str, str]],
) -> dict[str, pa.Table]:
    """Les tables brutes de l'entrepôt, réduites à la semaine."""
    useful = {row["isin"] for row in population} | {c["isin"] for c in couples}
    firds = pq.read_table(firds_index)
    firds = firds.filter(pc.is_in(firds["isin"], value_set=pa.array(sorted(useful))))
    return {
        "firds_titres": as_strings(firds),
        "population": _table(population, ["isin", "issuer_lei"]),
        "registre_documents": _table(register, REGISTER_COLUMNS),
        "decoupage": _table(couples, SPLIT_COLUMNS),
        "pdf_controle": _table(quality, QUALITY_COLUMNS),
        "rattachement": _table(
            links, ["document_id", "isin", "jeu", "isin_cite", "produit_structure"]
        ),
    }


def build_truth(
    tables: dict[str, pa.Table], database: Path, work_dir: Path
) -> list[dict[str, Any]]:
    """Charge les tables de la semaine, lance les modèles et leurs tests, lit la vérité terrain."""
    from dbt.cli.main import dbtRunner

    # dbt lit les chemins relatifs depuis le dossier du projet dbt, pas depuis celui de la
    # commande : tout est passé en absolu.
    database, work_dir = database.resolve(), work_dir.resolve()
    load_duckdb(tables, database)
    previous = os.environ.get("BOND_TERMS_DUCKDB")
    os.environ["BOND_TERMS_DUCKDB"] = str(database)
    try:
        result = dbtRunner().invoke(
            [
                "build",
                "--project-dir",
                str(PROJECT),
                "--profiles-dir",
                str(PROJECT),
                "--target-path",
                str(work_dir / "target"),
                "--log-path",
                str(work_dir / "logs"),
                "--quiet",
            ]
        )
    finally:
        if previous is None:
            os.environ.pop("BOND_TERMS_DUCKDB", None)
        else:
            os.environ["BOND_TERMS_DUCKDB"] = previous
    if not result.success:
        raise RuntimeError("l'entrepôt de la semaine ne passe pas ses tests : rien n'est publié")
    with duckdb.connect(str(database)) as connection:
        rows: list[dict[str, Any]] = (
            connection.sql(TRUTH_SQL, params=[SET_NAME]).to_arrow_table().to_pylist()
        )
    return rows


def summary(
    day: dt.date,
    firds_date: str,
    population: list[dict[str, str]],
    register: list[dict[str, str]],
    refs: list[DocumentRef],
    quality: list[dict[str, Any]],
    links: list[dict[str, str]],
    model: dict[str, Extraction],
    stopped: str,
) -> dict[str, Any]:
    """Bilan de la semaine, publié dans l'instantané et sur la branche `donnees`."""
    issue_documents = {
        r["document_id"] for r in register if r["document_type"] in ISSUE_DOCUMENT_TYPES
    }
    errors = sum(bool(q["erreur"]) for q in quality)
    return {
        "date": day.isoformat(),
        "firds": firds_date,
        "obligations_suivies": len(population),
        "documents_registre": len(issue_documents),
        "nouveaux_documents": len(refs),
        "documents_lus": len(quality) - errors,
        "erreurs_lecture": errors,
        "rattachements_errones": sum(link["isin_cite"] != "True" for link in links),
        "produits_structures": sum(link["produit_structure"] == "True" for link in links),
        "documents_extraits": len(model),
        "documents_en_repli": sum(e.remarque.startswith(FALLBACK) for e in model.values()),
        "replis_par_raison": dict(
            Counter(
                instantane.fallback_kind(reason)
                for e in model.values()
                if (reason := instantane.fallback_reason(e)) is not None
            )
        ),
        "arret_quota": bool(stopped),
    }


def read_documents(
    client: Any, refs: list[DocumentRef], pdf_dir: Path, ocr_dir: Path
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:  # pragma: no cover - vrais PDF
    """Téléchargement, lecture, puis OCR des pages sans texte."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    quality, rows = [], []
    for ref in refs:
        row, pages = process(client, ref, pdf_dir)
        quality.append(row)
        rows += [
            {"document_id": ref.document_id, "page": str(n), "texte": text}
            for n, text in enumerate(pages, start=1)
        ]
    pages_table = pa.Table.from_pylist(rows, schema=PAGE_SCHEMA)
    todo = ocr.empty_pages(pages_table)
    ocr_table = pa.Table.from_pylist([], schema=PAGE_SCHEMA)
    if todo:
        ocr_table, _ = ocr.run(todo, pdf_dir, ocr_dir, ocr.pdfium_renderer, ocr.rapidocr_engine())
    return quality, ocr.pages_by_document(pages_table, ocr_table)


def main() -> None:  # pragma: no cover - collecte réelle
    from bond_terms import firds
    from bond_terms.esma import PoliteClient

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--precedent", type=Path, required=True, help="instantané précédent")
    parser.add_argument("--sortie", type=Path, default=Path("data/instantane/instantane.json"))
    parser.add_argument("--bilan", type=Path, default=Path("data/instantane/bilan.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/collecte"))
    parser.add_argument("--llm-cache", type=Path, default=Path("data/interim/llm"))
    parser.add_argument("--commit", default="", help="commit du code, consigné tel quel")
    args = parser.parse_args()

    previous = instantane.read(args.precedent)
    today = dt.datetime.now(dt.UTC).date()
    client = PoliteClient()
    manifest = firds.collect(client, args.data_dir, None)
    index = args.data_dir / manifest["index"]["chemin"]
    population = select_population(index)
    register: list[dict[str, str]] = []
    cache = args.data_dir / "raw" / "registre" / today.isoformat()
    for position, bond in enumerate(population, start=1):
        register += document_rows(
            bond["isin"], bond["issuer_lei"], fetch_documents(client, bond["isin"], cache)
        )
        if position % 100 == 0:
            print(f"registre : {position}/{len(population)} obligations", flush=True)

    # Les documents que le LLM n'a pas lus la semaine précédente sont repris.
    seen = set(previous["documents_vus"]) - instantane.to_retry(previous)
    couples = new_couples(register, seen)
    refs = references(couples)
    print(f"{len(refs)} nouveaux documents", flush=True)
    quality: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    model: dict[str, Extraction] = {}
    stopped = ""
    sets = {}
    if refs:
        quality, pages = read_documents(
            client, refs, args.data_dir / "raw" / "pdf", args.data_dir / "interim" / "ocr"
        )
        texts = {doc: "\n".join(parts) for doc, parts in pages.items()}
        links = check(couples, texts)
        tables = raw_tables(index, population, register, couples, quality, links)
        work = args.data_dir / "entrepot"
        work.mkdir(parents=True, exist_ok=True)
        truth = build_truth(tables, work / f"collecte-{today.isoformat()}.duckdb", work)
        documents: dict[str, list[str]] = defaultdict(list)
        for couple in truth:
            documents[couple["document_id"]].append(couple["isin"])
        if documents:
            rules = {d: regles.extract(d, pages[d]) for d in sorted(documents)}
            extract, _ = llm_extractor(instantane.MODEL, args.llm_cache)
            model, stopped = run(documents, pages, extract)
            sets[f"{SET_NAME}-{today.isoformat()}"] = (truth, model, rules)
    # Un document illisible n'est pas marqué comme vu : il sera retenté la semaine suivante.
    read_ok = [q["document_id"] for q in quality if not q["erreur"]]
    weekly = instantane.build(sets, dt.datetime.now(dt.UTC), args.commit, read_ok)
    collection = summary(
        today,
        manifest["date_publication"],
        population,
        register,
        refs,
        quality,
        links,
        model,
        stopped,
    )
    merged = instantane.merge(previous, weekly, collection)
    instantane.write(merged, args.sortie)
    args.bilan.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "collecte": collection,
        "indicateurs": weekly["indicateurs"],
        "surveillance": surveillance.check(merged),
    }
    args.bilan.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
