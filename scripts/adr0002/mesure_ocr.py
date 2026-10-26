"""Mesure de l'OCR sur les scans du développement, pour l'ADR 0002.

Usage :
    uv run --group ocr python scripts/adr0002/mesure_ocr.py

Pour chaque couple document-ISIN du développement, on cherche les valeurs de FIRDS dans le texte :
texte du PDF pour les documents lisibles, texte de l'OCR pour les scans. La présence d'une valeur
ne prouve pas qu'un extracteur la trouvera, mais son absence prouve qu'il ne le pourra pas. Seuls
les documents du développement sont lus ; les sorties ne contiennent que des indicateurs.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.compute as pc
import pyarrow.parquet as pq

from bond_terms.documents import normalize
from bond_terms.valeurs import amount_pattern, contains, contains_isin, date_pattern, rate_pattern

RENDER_DPI = 200
FIELDS = ("code_isin", "echeance", "devise", "taux_fixe", "valeur_nominale", "montant")

COUPLES_SQL = """
select v.document_id, v.isin, v.devise, v.date_echeance, v.type_taux, v.taux_fixe,
       v.valeur_nominale, v.montant_nominal_total, v.montant_comparable, d.scanne
from verite_terrain as v
inner join documents as d using (document_id)
where v.jeu = 'developpement' and d.jeu = 'developpement'
order by v.document_id, v.isin
"""


def ocr_document(pdf_path: Path, cache: Path, engine: Any) -> dict[str, list[Any]]:
    """Texte de chaque page par OCR, gardé en cache hors du dépôt."""
    if cache.exists():
        cached: dict[str, list[Any]] = json.loads(cache.read_text(encoding="utf-8"))
        return cached
    import pypdfium2 as pdfium

    pages: list[str] = []
    seconds: list[float] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for page in pdf:
            image = page.render(scale=RENDER_DPI / 72).to_numpy()
            start = time.perf_counter()
            result = engine(image)
            seconds.append(round(time.perf_counter() - start, 2))
            pages.append("\n".join(result.txts or ()))
    finally:
        pdf.close()
    data: dict[str, list[Any]] = {"pages": pages, "secondes": seconds}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def text_layer(pages_file: Path, document_ids: Iterable[str]) -> dict[str, str]:
    table = pq.read_table(pages_file, columns=["document_id", "page", "texte"])
    table = table.filter(pc.is_in(table["document_id"], value_set=_array(document_ids)))
    texts: dict[str, list[str]] = {}
    for row in table.to_pylist():
        texts.setdefault(row["document_id"], []).append(row["texte"])
    return {doc: normalize("\n".join(pages)) for doc, pages in texts.items()}


def _array(values: Iterable[str]) -> Any:
    import pyarrow as pa

    return pa.array(sorted(set(values)))


def presence(text: str, couple: dict[str, Any]) -> dict[str, bool | None]:
    """Vrai si la valeur de FIRDS figure dans le texte ; vide si le champ n'est pas comparé."""
    maturity: dt.date | None = couple["date_echeance"]
    fixed = couple["type_taux"] == "fixed" and couple["taux_fixe"] is not None
    return {
        "code_isin": contains_isin(text, couple["isin"]),
        "echeance": contains(date_pattern(maturity), text) if maturity else None,
        "devise": couple["devise"].lower() in text
        or (couple["devise"] == "EUR" and "euro" in text),
        "taux_fixe": contains(rate_pattern(couple["taux_fixe"]), text) if fixed else None,
        "valeur_nominale": contains(amount_pattern(couple["valeur_nominale"]), text)
        if couple["valeur_nominale"]
        else None,
        "montant": contains(amount_pattern(couple["montant_nominal_total"]), text)
        if couple["montant_comparable"] and couple["montant_nominal_total"]
        else None,
    }


def summarize(rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
    subset = [r for r in rows if r["source"] == source]
    fields = {}
    for field in FIELDS:
        compared = [r[field] for r in subset if r[field] is not None]
        fields[field] = {"trouves": sum(compared), "compares": len(compared)}
    return {"couples": len(subset), "documents": len({r["document_id"] for r in subset}), **fields}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--pages", type=Path, default=Path("data/interim/textes/pages.parquet"))
    parser.add_argument("--pdf-dir", type=Path, default=Path("data/raw/pdf"))
    parser.add_argument("--ocr-dir", type=Path, default=Path("data/interim/ocr"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs/v0.2-extraction/data"))
    args = parser.parse_args()

    with duckdb.connect(str(args.database), read_only=True) as connection:
        couples = connection.sql(COUPLES_SQL).to_arrow_table().to_pylist()

    scans = sorted({c["document_id"] for c in couples if c["scanne"]})
    readable = {c["document_id"] for c in couples if not c["scanne"]}
    texts = text_layer(args.pages, readable)

    from rapidocr import RapidOCR

    engine = RapidOCR()
    ocr_seconds: list[float] = []
    for doc in scans:
        data = ocr_document(args.pdf_dir / f"{doc}.pdf", args.ocr_dir / f"{doc}.json", engine)
        texts[doc] = normalize("\n".join(data["pages"]))
        ocr_seconds += data["secondes"]

    rows = []
    for couple in couples:
        source = "ocr" if couple["scanne"] else "texte"
        found = presence(texts.get(couple["document_id"], ""), couple)
        rows.append(
            {
                "document_id": couple["document_id"],
                "isin": couple["isin"],
                "source": source,
                **found,
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "ocr-presence.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["document_id", "isin", "source", *FIELDS], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "jeu": "developpement",
        "moteur": "rapidocr 3.10 (onnxruntime), rendu à 200 points par pouce",
        "scans": len(scans),
        "pages_ocr": len(ocr_seconds),
        "secondes_par_page_mediane": statistics.median(ocr_seconds) if ocr_seconds else None,
        "secondes_ocr_total": round(sum(ocr_seconds), 1),
        "texte_du_pdf": summarize(rows, "texte"),
        "ocr": summarize(rows, "ocr"),
    }
    (args.output_dir / "ocr-mesure.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
