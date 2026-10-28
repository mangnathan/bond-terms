"""Téléchargement des documents d'émission et extraction de leur texte.

Usage :
    uv run python -m bond_terms.documents

Les documents listés dans le découpage (développement, test, émetteurs jamais vus) sont
téléchargés une seule fois, puis leur texte est extrait page par page. Les documents de test
sont figés maintenant, avant que le registre ne change, mais leur contenu n'est jamais lu
pendant le développement : le contrôle de qualité versionné ne contient que des comptes.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import unicodedata
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pypdf import PdfReader

from bond_terms.esma import PoliteClient, SourceError

DOWNLOAD = "https://registers.esma.europa.eu/publication/downloadFile"
PDF_MAGIC = b"%PDF"
# Rubrique présente dans toute condition définitive d'obligation, en anglais ou en français :
# son absence signale un texte illisible ou un document d'un autre type. Les marqueurs sont
# comparés au texte normalisé (minuscules, sans accents, apostrophes droites).
MATURITY_MARKERS = ("maturity date", "date d'echeance")
QUALITY_COLUMNS = [
    "document_id",
    "jeu",
    "octets",
    "sha256",
    "pages",
    "pages_sans_texte",
    "caracteres",
    "rubrique_echeance",
    "erreur",
]


@dataclass(frozen=True)
class DocumentRef:
    document_id: str
    rfss_file_id: str
    rfss_checksum: str
    jeu: str


def load_documents(split_csv: Path) -> list[DocumentRef]:
    """Documents du découpage, une fois chacun (un document peut citer deux ISIN)."""
    with split_csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    seen: dict[str, DocumentRef] = {}
    for row in rows:
        seen.setdefault(
            row["document_id"],
            DocumentRef(row["document_id"], row["rfss_file_id"], row["rfss_checksum"], row["jeu"]),
        )
    return sorted(seen.values(), key=lambda d: d.document_id)


def download_url(ref: DocumentRef) -> str:
    query = urllib.parse.urlencode({"fileId": ref.rfss_file_id, "checksum": ref.rfss_checksum})
    return f"{DOWNLOAD}?{query}"


def normalize(text: str) -> str:
    """Minuscules, sans accents, apostrophes droites : les PDF rendent « ' » de façons variées."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def extract_pages(path: Path) -> list[str]:
    """Texte de chaque page ; une page illisible donne une chaîne vide plutôt qu'un arrêt."""
    reader = PdfReader(path)
    if reader.is_encrypted:
        reader.decrypt("")
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - une page mal formée ne doit pas arrêter la collecte
            pages.append("")
    return pages


def process(
    client: PoliteClient, ref: DocumentRef, pdf_dir: Path
) -> tuple[dict[str, Any], list[str]]:
    """Télécharge et lit un document ; renvoie son contrôle de qualité et ses pages."""
    quality: dict[str, Any] = dict.fromkeys(QUALITY_COLUMNS, "") | {
        "document_id": ref.document_id,
        "jeu": ref.jeu,
    }
    path = pdf_dir / f"{ref.document_id}.pdf"
    try:
        downloaded = client.download(download_url(ref), path)
    except SourceError as error:
        return quality | {"erreur": f"téléchargement : {error}"}, []
    # Le fichier est refermé avant d'être supprimé : Windows refuse d'effacer un fichier ouvert.
    with path.open("rb") as file:
        header = file.read(len(PDF_MAGIC))
    if header != PDF_MAGIC:
        path.unlink()
        return quality | {"erreur": "le registre n'a pas renvoyé un PDF"}, []
    try:
        pages = extract_pages(path)
    except Exception as error:  # noqa: BLE001 - un PDF corrompu est compté, pas fatal
        return quality | {"erreur": f"lecture : {type(error).__name__}"}, []
    text = normalize("\n".join(pages))
    return quality | {
        "octets": downloaded.size_bytes,
        "sha256": downloaded.sha256,
        "pages": len(pages),
        "pages_sans_texte": sum(not p.strip() for p in pages),
        "caracteres": len(text),
        "rubrique_echeance": any(marker in text for marker in MATURITY_MARKERS),
    }, pages


def summarize(quality: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for split in sorted({q["jeu"] for q in quality}):
        rows = [q for q in quality if q["jeu"] == split]
        read = [q for q in rows if not q["erreur"]]
        summary[split] = {
            "documents": len(rows),
            "lus": len(read),
            "erreurs": dict(Counter(q["erreur"].split(" :")[0] for q in rows if q["erreur"])),
            "pages_mediane": statistics.median(q["pages"] for q in read) if read else 0,
            "documents_avec_pages_sans_texte": sum(q["pages_sans_texte"] > 0 for q in read),
            # Aucune page avec du texte : document scanné, illisible sans reconnaissance d'image.
            "documents_sans_texte": sum(q["pages_sans_texte"] == q["pages"] for q in read),
            "documents_sans_rubrique_echeance": sum(not q["rubrique_echeance"] for q in read),
        }
    return summary


def collect(
    client: PoliteClient,
    split_csv: Path,
    data_dir: Path,
    output_dir: Path,
    pages_file: Path | None = None,
) -> dict[str, Any]:
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    pdf_dir = data_dir / "raw" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    quality, pages_rows = [], []
    documents = load_documents(split_csv)
    for position, ref in enumerate(documents, start=1):
        row, pages = process(client, ref, pdf_dir)
        quality.append(row)
        pages_rows += [
            {"document_id": ref.document_id, "page": str(n), "texte": text}
            for n, text in enumerate(pages, start=1)
        ]
        if position % 50 == 0:
            print(f"{position}/{len(documents)} documents", flush=True)

    # Un nouveau jeu écrit ses textes à part, sans écraser ceux des jeux déjà traités.
    texts = pages_file or data_dir / "interim" / "textes" / "pages.parquet"
    texts.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [("document_id", pa.string()), ("page", pa.string()), ("texte", pa.string())]
    )
    pq.write_table(pa.Table.from_pylist(pages_rows, schema=schema), texts)

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "pdf-controle.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=QUALITY_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(quality)
    summary = summarize(quality)
    (output_dir / "pdf-resume.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split", type=Path, default=Path("docs/v0.1-collecte/data/decoupage-documents.csv")
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs/v0.1-collecte/data"))
    parser.add_argument(
        "--pages", type=Path, help="fichier des textes (par défaut, celui de la v0.1)"
    )
    args = parser.parse_args()
    summary = collect(PoliteClient(), args.split, args.data_dir, args.output_dir, args.pages)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
