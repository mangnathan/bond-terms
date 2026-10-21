"""Construit l'index des titres de dette de FIRDS, la base de référence de l'ESMA.

Télécharge les fichiers complets de la catégorie dette (FULINS_D) publiés à une date donnée,
les lit en flux (un fichier décompressé pèse environ 450 Mo) et écrit une ligne par ISIN.
Écrit aussi un résumé chiffré pour le rapport de cadrage.

Usage :
    uv run python scripts/feasibility/build_firds_debt_index.py [--date AAAA-MM-JJ]

Sans --date, prend la publication complète la plus récente.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import tracemalloc
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from bond_terms.firds import COLUMNS, iter_records
from bond_terms.instruments import is_plain_bond

FILES_INDEX = "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select"
USER_AGENT = "bond-terms (projet personnel ; github.com/mangnathan)"
RAW_DIR = Path("data/raw/firds")
INDEX_PATH = Path("data/interim/firds-dette.csv")
SUMMARY_PATH = Path("docs/v0.0-cadrage/data/firds-dette-resume.json")


def fetch_json(url: str, params: list[tuple[str, str]]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data: dict[str, Any] = json.load(response)
    return data


def list_debt_files(date: str | None) -> tuple[str, list[tuple[str, str]]]:
    """Renvoie la date de publication retenue et les fichiers FULINS_D (nom, lien)."""
    params = [
        ("q", "*"),
        ("fq", "file_type:FULINS"),
        ("fq", "file_name:FULINS_D_*"),
        ("sort", "publication_date desc"),
        ("rows", "40"),
        ("wt", "json"),
    ]
    docs = fetch_json(FILES_INDEX, params)["response"]["docs"]
    dates = sorted({d["publication_date"][:10] for d in docs}, reverse=True)
    chosen = date or dates[0]
    files = sorted(
        (d["file_name"], d["download_link"]) for d in docs if d["publication_date"][:10] == chosen
    )
    if not files:
        raise SystemExit(f"Aucun fichier FULINS_D publié le {chosen} (dates connues : {dates})")
    return chosen, files


def download(url: str, destination: Path) -> Path:
    """Télécharge une seule fois ; le fichier partiel n'est renommé qu'une fois complet."""
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    partial.replace(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="date de publication FIRDS (AAAA-MM-JJ)")
    args = parser.parse_args()

    publication_date, files = list_debt_files(args.date)
    tracemalloc.start()
    started = time.monotonic()
    seen: set[str] = set()
    records = 0
    cfi_counts: Counter[str] = Counter()
    filled: Counter[str] = Counter()
    plain_bonds = 0
    plain_by_country: Counter[str] = Counter()
    # Contrôle de lecture : un taux variable sans référence trahit une forme XML non lue.
    floating_without_reference = 0

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for name, link in files:
            zip_path = download(link, RAW_DIR / name)
            with zipfile.ZipFile(zip_path) as archive, archive.open(archive.namelist()[0]) as xml:
                for row in iter_records(xml):
                    records += 1
                    # Un titre apparaît pour chaque plateforme de négociation : on garde le premier.
                    if row["isin"] in seen:
                        continue
                    seen.add(row["isin"])
                    writer.writerow(row)
                    cfi_counts[row["cfi"][:2]] += 1
                    filled.update(
                        k for k in ("maturity_date", "nominal_amount", "seniority") if row[k]
                    )
                    floating_without_reference += (
                        row["rate_type"] == "floating" and not row["reference_rate"]
                    )
                    if is_plain_bond(row):
                        plain_bonds += 1
                        plain_by_country[row["isin"][:2]] += 1
            print(f"{name} : {records} enregistrements, {len(seen)} ISIN", flush=True)

    total = len(seen)
    summary = {
        "date_publication_firds": publication_date,
        "fichiers": [name for name, _ in files],
        "enregistrements": records,
        "isin_distincts": total,
        "categories_cfi": dict(cfi_counts.most_common(10)),
        "taux_de_remplissage": {k: round(v / total, 3) for k, v in filled.items()},
        "taux_variables_sans_reference": floating_without_reference,
        "obligations_classiques": plain_bonds,
        "obligations_classiques_par_pays_isin": dict(plain_by_country.most_common(8)),
        "duree_lecture_s": round(time.monotonic() - started),
        "memoire_pic_mo": tracemalloc.get_traced_memory()[1] // 1_000_000,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
