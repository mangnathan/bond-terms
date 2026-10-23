"""Choisit les documents de la saisie manuelle chronométrée qui sert de référence au business case.

Dix documents d'obligations classiques à ISIN français, approuvés en 2022 ou 2023. Le test
regroupe les documents les plus récents : ceux-ci devraient être dans la partie développement,
ce qui sera vérifié une fois la date de coupure calculée ; un document tombé dans le test en sera
retiré (ADR 0001). Les secteurs sont répartis selon des quotas fixés à l'avance. La fiche produite
ne montre pas les valeurs de FIRDS : la saisie doit se faire en lisant le document.

Usage :
    uv run python scripts/feasibility/select_timing_documents.py
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

REGISTER = "https://registers.esma.europa.eu/solr/esma_registers_priii_documents/select"
DOWNLOAD = "https://registers.esma.europa.eu/publication/downloadFile"
USER_AGENT = "bond-terms (projet personnel ; github.com/mangnathan)"
FIRDS_INDEX = Path("data/interim/firds-dette.csv")
OUTPUT = Path("docs/v0.0-cadrage/data/chronometrage-saisie-manuelle.csv")
PERIOD = ("2022-01-01", "2023-12-31")
DOCUMENT_TYPES = ("Final terms", "Standalone prospectus")
SEED = 21
PAUSE_S = 1.0
# Nombre de documents par émetteur, dans cet ordre ; les places non pourvues vont aux banques.
QUOTAS = {
    "LVMH": ("IOG4E947OATN0KJYSD45", 2),
    "Kering": ("549300VGEJKB7SVUZR78", 2),
    "Air France-KLM": ("969500AQW31GYO8JZD66", 1),
    "AXA": ("F5WCUMTUM4RKZ1MAIE39", 1),
    "BNP Paribas": ("R0MUWSFPU8MPRO8K5P83", 1),
    "Société Générale": ("O2RNE8IBXP4R0TD8PU41", 1),
    "Crédit Agricole S.A.": ("969500TJ5KRTCJQWXH05", 1),
    "BPCE": ("9695005MSX1OYEMGDF46", 1),
}
TOTAL = 10
FIELDS_TO_FILL = [
    "heure_debut",
    "heure_fin",
    "devise",
    "date_echeance",
    "type_taux",
    "taux_fixe",
    "reference_taux_variable",
    "marge_points_de_base",
    "valeur_nominale",
    "montant_nominal_total",
    "rang",
    "lei_emetteur",
    "remarques",
]


def documents_for(isin: str) -> list[dict[str, Any]]:
    params = [
        ("q", "type_s:parent"),
        ("fq", f'instrument_isins:"{isin}"'),
        ("fq", f"approval_filing_date:[{PERIOD[0]}T00:00:00Z TO {PERIOD[1]}T23:59:59Z]"),
        ("rows", "20"),
        ("wt", "json"),
        ("fl", "id,document_type_descr,approval_filing_date,document_rfss_id,instrument_isins"),
    ]
    request = urllib.request.Request(
        f"{REGISTER}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        docs: list[dict[str, Any]] = json.load(response)["response"]["docs"]
    return [d for d in docs if str(d.get("document_type_descr", "")).startswith(DOCUMENT_TYPES)]


def pick(isins: list[str], wanted: int, rng: random.Random) -> list[tuple[str, dict[str, Any]]]:
    """Parcourt les ISIN dans un ordre aléatoire et garde un document par ISIN."""
    chosen: list[tuple[str, dict[str, Any]]] = []
    for isin in rng.sample(isins, len(isins)):
        if len(chosen) == wanted:
            break
        docs = documents_for(isin)
        time.sleep(PAUSE_S)
        # Un document qui couvre une seule émission : la saisie reste comparable d'un cas à l'autre.
        single = [d for d in docs if "," not in str(d.get("instrument_isins", ""))]
        if single:
            chosen.append((isin, min(single, key=lambda d: str(d["approval_filing_date"]))))
    return chosen


def main() -> None:
    with FIRDS_INDEX.open(encoding="utf-8") as f:
        plain = [r for r in csv.DictReader(f) if is_plain_bond(r) and r["isin"].startswith("FR")]
    by_lei: dict[str, list[str]] = {}
    for row in plain:
        by_lei.setdefault(row["issuer_lei"], []).append(row["isin"])
    rng = random.Random(SEED)
    selection: list[tuple[str, str, dict[str, Any]]] = []
    for issuer, (lei, quota) in QUOTAS.items():
        isins = sorted(by_lei.get(lei, []))
        found = pick(isins, quota, rng)
        selection += [(issuer, isin, doc) for isin, doc in found]
        print(f"{issuer} : {len(found)}/{quota}", flush=True)
    banks = [name for name in QUOTAS if QUOTAS[name][1] == 1][2:]
    taken = {isin for _, isin, _ in selection}
    for issuer in banks:
        if len(selection) >= TOTAL:
            break
        lei = QUOTAS[issuer][0]
        isins = sorted(set(by_lei.get(lei, [])) - taken)
        selection += [(issuer, isin, doc) for isin, doc in pick(isins, 1, rng)]
    selection = selection[:TOTAL]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as out:
        columns = ["numero", "emetteur", "isin", "date_approbation", "type_document", "lien_pdf"]
        writer = csv.DictWriter(out, fieldnames=columns + FIELDS_TO_FILL, lineterminator="\n")
        writer.writeheader()
        for number, (issuer, isin, doc) in enumerate(selection, start=1):
            file_id, checksum = str(doc["document_rfss_id"]).split(",")
            link = f"{DOWNLOAD}?{urllib.parse.urlencode({'fileId': file_id, 'checksum': checksum})}"
            writer.writerow(
                {
                    "numero": number,
                    "emetteur": issuer,
                    "isin": isin,
                    "date_approbation": str(doc["approval_filing_date"])[:10],
                    "type_document": doc["document_type_descr"],
                    "lien_pdf": link,
                }
                | dict.fromkeys(FIELDS_TO_FILL, "")
            )
    print(f"{len(selection)} documents écrits dans {OUTPUT}")


if __name__ == "__main__":
    main()
