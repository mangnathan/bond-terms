"""Vérifie la couverture des émetteurs visés : obligations dans FIRDS, documents dans le registre.

Pour chaque émetteur, le LEI est contrôlé auprès de GLEIF (nom légal, pays, statut), les
obligations classiques sont comptées dans l'index FIRDS, puis on cherche dans le registre des
prospectus un document pour quelques ISIN français tirés au hasard. Les ISIN « US » ou « CH »
relèvent d'autres régulateurs et les ISIN « XS » ont rarement un document dans le registre : on
cible les ISIN français, qui sont la population collectée en v0.1.

Usage :
    uv run python scripts/feasibility/check_issuer_coverage.py
"""

from __future__ import annotations

import csv
import json
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from bond_terms.instruments import is_plain_bond

GLEIF = "https://api.gleif.org/api/v1/lei-records"
REGISTER = "https://registers.esma.europa.eu/solr/esma_registers_priii_documents/select"
USER_AGENT = "bond-terms (projet personnel ; github.com/mangnathan)"
FIRDS_INDEX = Path("data/interim/firds-dette.csv")
OUTPUT = Path("docs/v0.0-cadrage/data/couverture-emetteurs.csv")
ISINS_CHECKED = 8
SEED = 3
PAUSE_S = 0.5
# Émetteurs des secteurs visés : banque, assurance, luxe, aviation.
ISSUERS = {
    "BNP Paribas": ("banque", "R0MUWSFPU8MPRO8K5P83"),
    "Société Générale": ("banque", "O2RNE8IBXP4R0TD8PU41"),
    "Crédit Agricole S.A.": ("banque", "969500TJ5KRTCJQWXH05"),
    "BPCE": ("banque", "9695005MSX1OYEMGDF46"),
    "AXA": ("assurance", "F5WCUMTUM4RKZ1MAIE39"),
    "LVMH": ("luxe", "IOG4E947OATN0KJYSD45"),
    "Kering": ("luxe", "549300VGEJKB7SVUZR78"),
    "Hermès International": ("luxe", "969500Y4IJGHJE2MTJ13"),
    "Air France-KLM": ("aviation", "969500AQW31GYO8JZD66"),
}


def get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data: dict[str, Any] = json.load(response)
    return data


def gleif_entity(lei: str) -> dict[str, Any]:
    entity: dict[str, Any] = get_json(f"{GLEIF}/{lei}")["data"]["attributes"]["entity"]
    return entity


def register_documents(isin: str) -> int:
    params = [
        ("q", "type_s:parent"),
        ("fq", f'instrument_isins:"{isin}"'),
        ("rows", "0"),
        ("wt", "json"),
    ]
    count: int = get_json(f"{REGISTER}?{urllib.parse.urlencode(params)}")["response"]["numFound"]
    return count


def main() -> None:
    with FIRDS_INDEX.open(encoding="utf-8") as f:
        by_lei: dict[str, list[dict[str, str]]] = {}
        for row in csv.DictReader(f):
            by_lei.setdefault(row["issuer_lei"], []).append(row)
    rng = random.Random(SEED)
    rows = []
    for name, (sector, lei) in ISSUERS.items():
        entity = gleif_entity(lei)
        securities = by_lei.get(lei, [])
        plain = sorted(r["isin"] for r in securities if is_plain_bond(r))
        plain_fr = [isin for isin in plain if isin.startswith("FR")]
        checked = rng.sample(plain_fr, min(ISINS_CHECKED, len(plain_fr)))
        with_document = 0
        for isin in checked:
            with_document += register_documents(isin) > 0
            time.sleep(PAUSE_S)
        row = {
            "emetteur": name,
            "secteur": sector,
            "lei": lei,
            "nom_gleif": entity["legalName"]["name"],
            "pays_gleif": entity["legalAddress"]["country"],
            "statut_gleif": entity["status"],
            "titres_dette_firds": len(securities),
            "obligations_classiques_firds": len(plain),
            "dont_isin_fr": len(plain_fr),
            "isin_fr_verifies": len(checked),
            "isin_fr_avec_document": with_document,
        }
        rows.append(row)
        print(row, flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
