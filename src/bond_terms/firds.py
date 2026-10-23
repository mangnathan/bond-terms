"""Collecte et lecture des données de référence FIRDS (ESMA) pour les titres de dette.

Usage :
    uv run python -m bond_terms.firds [--date AAAA-MM-JJ]

Télécharge la publication complète de la catégorie dette, la range par date, écrit l'index en
Parquet (une ligne par ISIN, valeurs telles que publiées) et un manifeste versionné : fichiers,
tailles, empreintes et comptes. Sans --date, prend la publication complète la plus récente.
"""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import IO, Any
from xml.etree.ElementTree import Element

import pyarrow as pa
import pyarrow.parquet as pq
from defusedxml.ElementTree import iterparse

from bond_terms.esma import PoliteClient, sha256_of
from bond_terms.instruments import is_plain_bond

FILES_INDEX = "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select"
COLUMNS = [
    "isin",
    "cfi",
    "issuer_lei",
    "currency",
    "nominal_amount",
    "denomination",
    "maturity_date",
    "rate_type",
    "fixed_rate",
    "reference_rate",
    "reference_term",
    "spread_bps",
    "seniority",
    "first_trade_date",
    "full_name",
]
BATCH_ROWS = 50_000


def namespace_of(tag: str) -> str:
    return tag[: tag.index("}") + 1] if tag.startswith("{") else ""


@lru_cache(maxsize=4)
def _paths(ns: str) -> dict[str, str]:
    """Chemins de chaque champ dans un <RefData>, avec l'espace de noms du fichier."""

    def path(*names: str) -> str:
        return "/".join(ns + name for name in names)

    general = ("FinInstrmGnlAttrbts",)
    debt = ("DebtInstrmAttrbts",)
    rate = (*debt, "IntrstRate")
    return {
        "isin": path(*general, "Id"),
        "cfi": path(*general, "ClssfctnTp"),
        "currency": path(*general, "NtnlCcy"),
        "full_name": path(*general, "FullNm"),
        "issuer_lei": path("Issr"),
        "first_trade_date": path("TradgVnRltdAttrbts", "FrstTradDt"),
        "nominal_amount": path(*debt, "TtlIssdNmnlAmt"),
        "denomination": path(*debt, "NmnlValPerUnit"),
        "maturity_date": path(*debt, "MtrtyDt"),
        "seniority": path(*debt, "DebtSnrty"),
        "fixed": path(*rate, "Fxd"),
        "floating": path(*rate, "Fltg"),
        # Dans un taux variable : la référence a trois formes, un code (Indx), un nom libre (Nm)
        # ou l'ISIN d'un indice. La durée fait partie de la référence : 3 mois n'est pas 6 mois.
        "reference_code": path("RefRate", "Indx"),
        "reference_name": path("RefRate", "Nm"),
        "reference_isin": path("RefRate", "ISIN"),
        "term_value": path("Term", "Val"),
        "term_unit": path("Term", "Unit"),
        "spread": path("BsisPtSprd"),
    }


def _text(element: Element | None, path: str) -> str:
    found = element.find(path) if element is not None else None
    return (found.text or "").strip() if found is not None else ""


def parse_record(record: Element) -> dict[str, str]:
    """Champs utiles d'un enregistrement <RefData>, chacun lu à son emplacement exact."""
    p = _paths(namespace_of(record.tag))
    fixed = record.find(p["fixed"])
    floating = record.find(p["floating"])
    reference = (
        _text(floating, p["reference_code"])
        or _text(floating, p["reference_name"])
        or _text(floating, p["reference_isin"])
    )
    term_value = _text(floating, p["term_value"])
    if fixed is not None:
        rate_type = "fixed"
    elif floating is not None:
        rate_type = "floating"
    else:
        rate_type = ""
    return {
        "isin": _text(record, p["isin"]),
        "cfi": _text(record, p["cfi"]),
        "issuer_lei": _text(record, p["issuer_lei"]),
        "currency": _text(record, p["currency"]),
        "nominal_amount": _text(record, p["nominal_amount"]),
        "denomination": _text(record, p["denomination"]),
        "maturity_date": _text(record, p["maturity_date"]),
        "rate_type": rate_type,
        "fixed_rate": (fixed.text or "").strip() if fixed is not None else "",
        "reference_rate": reference,
        "reference_term": f"{term_value} {_text(floating, p['term_unit'])}" if term_value else "",
        "spread_bps": _text(floating, p["spread"]),
        "seniority": _text(record, p["seniority"]),
        "first_trade_date": _text(record, p["first_trade_date"])[:10],
        "full_name": _text(record, p["full_name"]),
    }


def iter_records(xml_file: IO[bytes]) -> Iterator[dict[str, str]]:
    """Lit un fichier FIRDS en flux : un fichier décompressé pèse environ 450 Mo."""
    for _, element in iterparse(xml_file, events=("end",)):
        if element.tag.endswith("RefData"):
            yield parse_record(element)
            element.clear()


@dataclass
class IndexStats:
    records: int = 0
    isins: int = 0
    plain_bonds: int = 0
    # Contrôle de lecture : un taux variable sans référence trahit une forme XML non lue.
    floating_without_reference: int = 0
    cfi: Counter[str] = field(default_factory=Counter)
    filled: Counter[str] = field(default_factory=Counter)
    plain_by_country: Counter[str] = field(default_factory=Counter)
    seconds: float = 0.0


def build_index(zip_paths: list[Path], output: Path) -> IndexStats:
    """Écrit une ligne par ISIN en Parquet ; un titre est répété pour chaque plateforme."""
    started = time.monotonic()
    stats = IndexStats()
    seen: set[str] = set()
    schema = pa.schema([(name, pa.string()) for name in COLUMNS])
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".part")
    batch: dict[str, list[str]] = {name: [] for name in COLUMNS}

    with pq.ParquetWriter(partial, schema) as writer:

        def flush() -> None:
            writer.write_table(pa.table(batch, schema=schema))
            for values in batch.values():
                values.clear()

        for zip_path in zip_paths:
            with zipfile.ZipFile(zip_path) as archive, archive.open(archive.namelist()[0]) as xml:
                for row in iter_records(xml):
                    stats.records += 1
                    if row["isin"] in seen:
                        continue
                    seen.add(row["isin"])
                    for name in COLUMNS:
                        batch[name].append(row[name])
                    stats.cfi[row["cfi"][:2]] += 1
                    stats.filled.update(
                        k for k in ("maturity_date", "nominal_amount", "seniority") if row[k]
                    )
                    if row["rate_type"] == "floating" and not row["reference_rate"]:
                        stats.floating_without_reference += 1
                    if is_plain_bond(row):
                        stats.plain_bonds += 1
                        stats.plain_by_country[row["isin"][:2]] += 1
                    if len(batch["isin"]) >= BATCH_ROWS:
                        flush()
        if batch["isin"]:
            flush()
    partial.replace(output)
    stats.isins = len(seen)
    stats.seconds = time.monotonic() - started
    return stats


@dataclass(frozen=True)
class FirdsFile:
    name: str
    link: str


def list_full_debt_files(
    client: PoliteClient, publication_date: str | None = None
) -> tuple[str, list[FirdsFile]]:
    """Date de publication retenue et fichiers complets de la catégorie dette (FULINS_D)."""
    params = [
        ("q", "*"),
        ("fq", "file_type:FULINS"),
        ("fq", "file_name:FULINS_D_*"),
        ("sort", "publication_date desc"),
        ("rows", "40"),
        ("wt", "json"),
    ]
    docs = client.get_json(FILES_INDEX, params)["response"]["docs"]
    dates = sorted({d["publication_date"][:10] for d in docs}, reverse=True)
    chosen = publication_date or dates[0]
    files = sorted(
        (
            FirdsFile(d["file_name"], d["download_link"])
            for d in docs
            if d["publication_date"][:10] == chosen
        ),
        key=lambda f: f.name,
    )
    if not files:
        raise SystemExit(f"Aucun fichier FULINS_D publié le {chosen} (dates connues : {dates})")
    return chosen, files


def collect(client: PoliteClient, data_dir: Path, publication_date: str | None) -> dict[str, Any]:
    """Télécharge, indexe et décrit une publication complète ; renvoie le manifeste."""
    chosen, files = list_full_debt_files(client, publication_date)
    raw_dir = data_dir / "raw" / "firds" / "FULINS" / chosen
    downloaded = [client.download(f.link, raw_dir / f.name) for f in files]
    index_path = data_dir / "interim" / "firds" / f"dette-{chosen}.parquet"
    stats = build_index([d.path for d in downloaded], index_path)
    return {
        "source": "ESMA, FIRDS, publication complète de la catégorie dette (FULINS_D)",
        "date_publication": chosen,
        "fichiers": [
            {"nom": d.path.name, "octets": d.size_bytes, "sha256": d.sha256} for d in downloaded
        ],
        "index": {"chemin": index_path.relative_to(data_dir).as_posix(), "lignes": stats.isins},
        "index_sha256": sha256_of(index_path),
        "enregistrements": stats.records,
        "isin_distincts": stats.isins,
        "categories_cfi": dict(stats.cfi.most_common(10)),
        "taux_de_remplissage": {
            k: round(v / stats.isins, 3) for k, v in sorted(stats.filled.items())
        },
        "obligations_classiques": stats.plain_bonds,
        "obligations_classiques_par_pays_isin": dict(stats.plain_by_country.most_common(8)),
        "taux_variables_sans_reference": stats.floating_without_reference,
        "duree_lecture_s": round(stats.seconds),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="date de publication FIRDS (AAAA-MM-JJ)")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--manifest-dir", type=Path, default=Path("docs/v0.1-collecte/data"))
    args = parser.parse_args()
    manifest = collect(PoliteClient(), args.data_dir, args.date)
    args.manifest_dir.mkdir(parents=True, exist_ok=True)
    path = args.manifest_dir / f"firds-manifeste-{manifest['date_publication']}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
