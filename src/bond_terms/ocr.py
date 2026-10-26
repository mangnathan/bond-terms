"""Lecture par OCR des pages sans texte (ADR 0002).

Usage :
    uv run --group ocr python -m bond_terms.ocr

Seules les pages dont le PDF ne contient aucun texte sont lues, en local, par RapidOCR. Chaque
page lue est gardée en cache (`data/interim/ocr/<document>/<page>.txt`) : une relance ne refait
que les pages manquantes. Le résumé versionné ne contient que des comptes.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bond_terms.entrepot import read_csv

RENDER_DPI = 200

# Rendu d'une page (numérotée à partir de 1) en image, puis lecture de l'image en lignes de texte.
Renderer = Callable[[Path, int], Any]
Engine = Callable[[Any], list[str]]


def empty_pages(pages: pa.Table) -> dict[str, list[int]]:
    """Pages sans aucun texte, par document."""
    found: dict[str, list[int]] = defaultdict(list)
    for row in pages.select(["document_id", "page", "texte"]).to_pylist():
        if not (row["texte"] or "").strip():
            found[row["document_id"]].append(int(row["page"]))
    return {doc: sorted(numbers) for doc, numbers in found.items()}


def cache_path(cache_dir: Path, document_id: str, page: int) -> Path:
    return cache_dir / document_id / f"{page}.txt"


def read_page(
    pdf: Path, page: int, cache: Path, render: Renderer, engine: Engine
) -> tuple[str, float | None]:
    """Texte de la page et durée de l'OCR ; une page déjà en cache n'est pas relue."""
    if cache.exists():
        return cache.read_text(encoding="utf-8"), None
    image = render(pdf, page)
    start = time.perf_counter()
    text = "\n".join(engine(image))
    seconds = time.perf_counter() - start
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text, seconds


def run(
    todo: dict[str, list[int]], pdf_dir: Path, cache_dir: Path, render: Renderer, engine: Engine
) -> tuple[pa.Table, list[float]]:
    rows: list[dict[str, str]] = []
    durations: list[float] = []
    for document_id in sorted(todo):
        pdf = pdf_dir / f"{document_id}.pdf"
        for page in todo[document_id]:
            cache = cache_path(cache_dir, document_id, page)
            text, seconds = read_page(pdf, page, cache, render, engine)
            if seconds is not None:
                durations.append(seconds)
            rows.append({"document_id": document_id, "page": str(page), "texte": text})
    schema = pa.schema(
        [("document_id", pa.string()), ("page", pa.string()), ("texte", pa.string())]
    )
    return pa.Table.from_pylist(rows, schema=schema), durations


def pages_by_document(pages: pa.Table, ocr_pages: pa.Table) -> dict[str, list[str]]:
    """Pages de chaque document dans l'ordre, celles lues par OCR remplaçant les pages vides."""
    by_page: dict[tuple[str, int], str] = {}
    for row in pages.select(["document_id", "page", "texte"]).to_pylist():
        by_page[(row["document_id"], int(row["page"]))] = row["texte"] or ""
    for row in ocr_pages.select(["document_id", "page", "texte"]).to_pylist():
        by_page[(row["document_id"], int(row["page"]))] = row["texte"] or ""
    texts: dict[str, list[str]] = defaultdict(list)
    for document_id, page in sorted(by_page):
        texts[document_id].append(by_page[(document_id, page)])
    return dict(texts)


def merge_pages(pages: pa.Table, ocr_pages: pa.Table) -> dict[str, str]:
    """Texte complet de chaque document, pages lues par OCR comprises, dans l'ordre des pages."""
    return {doc: "\n".join(parts) for doc, parts in pages_by_document(pages, ocr_pages).items()}


def summarize(
    todo: dict[str, list[int]],
    ocr_pages: pa.Table,
    splits: dict[str, str],
    durations: Iterable[float],
) -> dict[str, Any]:
    still_empty = {
        (row["document_id"], row["page"])
        for row in ocr_pages.to_pylist()
        if not row["texte"].strip()
    }
    summary: dict[str, Any] = {}
    for split in sorted(set(splits.values())):
        docs = [doc for doc in todo if splits.get(doc) == split]
        summary[split] = {
            "documents_avec_pages_sans_texte": len(docs),
            "pages_lues_par_ocr": sum(len(todo[doc]) for doc in docs),
            "pages_toujours_vides": sum(1 for doc, _ in still_empty if splits.get(doc) == split),
        }
    measured = list(durations)
    summary["secondes_par_page_mediane"] = (
        round(statistics.median(measured), 2) if measured else None
    )
    return summary


def rapidocr_engine() -> Engine:  # pragma: no cover - modèles d'OCR absents en CI
    from rapidocr import RapidOCR

    reader = RapidOCR()

    def engine(image: Any) -> list[str]:
        result: Any = reader(image)
        return list(result.txts or ())

    return engine


def pdfium_renderer(pdf: Path, page: int) -> Any:  # pragma: no cover - rendu absent en CI
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf))
    try:
        return document[page - 1].render(scale=RENDER_DPI / 72).to_numpy()
    finally:
        document.close()


def main() -> None:  # pragma: no cover - lit les vrais PDF
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages.parquet"))
    parser.add_argument("--pdf-dir", type=Path, default=Path("data/raw/pdf"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/interim/ocr"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/interim/textes/pages-ocr.parquet")
    )
    parser.add_argument(
        "--split", type=Path, default=Path("docs/v0.1-collecte/data/decoupage-documents.csv")
    )
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.2-extraction/data"))
    args = parser.parse_args()

    todo = empty_pages(pq.read_table(args.pages))
    ocr_pages, durations = run(
        todo, args.pdf_dir, args.cache_dir, pdfium_renderer, rapidocr_engine()
    )
    pq.write_table(ocr_pages, args.output)
    split = read_csv(args.split).select(["document_id", "jeu"]).to_pylist()
    splits = {row["document_id"]: row["jeu"] for row in split}
    summary = summarize(todo, ocr_pages, splits, durations)
    args.summary_dir.mkdir(parents=True, exist_ok=True)
    (args.summary_dir / "ocr-resume.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
