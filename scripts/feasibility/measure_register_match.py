"""Mesure la part des documents du registre des prospectus qui décrivent des obligations classiques.

Tire au hasard des documents déposés entre janvier et septembre 2026, segment par segment
(pays de l'autorité qui a approuvé le document, type de document), et cherche leurs ISIN
dans l'index FIRDS construit par build_firds_debt_index.py.

Usage :
    uv run python scripts/feasibility/measure_register_match.py
"""

from __future__ import annotations

import csv
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from bond_terms.instruments import is_plain_bond

REGISTER = "https://registers.esma.europa.eu/solr/esma_registers_priii_documents/select"
USER_AGENT = "bond-terms (projet personnel ; github.com/mangnathan)"
FIRDS_INDEX = Path("data/interim/firds-dette.csv")
OUTPUT = Path("docs/v0.0-cadrage/data/correspondance-registre-firds.csv")
PERIOD = "approval_filing_date:[2026-01-01T00:00:00Z TO 2026-09-30T23:59:59Z]"
SAMPLE_SIZE = 60
SEED = 11
# Pause entre deux requêtes : le registre ne publie pas de limite, on reste prudent.
PAUSE_S = 0.5
SEGMENTS: dict[str, list[str]] = {
    "Tous pays": [],
    "France, conditions définitives": ["home_member_state_code:FR", "document_type:FTWS"],
    "Irlande": ["home_member_state_code:IE"],
    "Luxembourg": ["home_member_state_code:LU"],
    "Pays-Bas": ["home_member_state_code:NL"],
    "Hors conditions définitives": ["-document_type:FTWS"],
}


def query(filters: list[str], rows: int, start: int = 0) -> dict[str, Any]:
    params = [("q", "type_s:parent"), ("fq", PERIOD), ("rows", str(rows)), ("start", str(start))]
    params += [("fq", f) for f in filters]
    params += [("wt", "json"), ("fl", "id,instrument_isins")]
    request = urllib.request.Request(
        f"{REGISTER}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result: dict[str, Any] = json.load(response)["response"]
                return result
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(5)
    raise AssertionError("inaccessible")


def isins_of(document: dict[str, Any]) -> list[str]:
    return [i.strip() for i in str(document.get("instrument_isins", "")).split(",") if i.strip()]


def main() -> None:
    with FIRDS_INDEX.open(encoding="utf-8") as f:
        firds = {row["isin"]: row for row in csv.DictReader(f)}
    rng = random.Random(SEED)
    rows = []
    for segment, filters in SEGMENTS.items():
        total = query(filters, rows=0)["numFound"]
        documents = []
        for start in sorted(rng.sample(range(total), min(SAMPLE_SIZE, total))):
            documents += query(filters, rows=1, start=start)["docs"]
            time.sleep(PAUSE_S)
        matched = [[firds[i] for i in isins_of(d) if i in firds] for d in documents]
        row = {
            "segment": segment,
            "documents_periode": total,
            "echantillon": len(documents),
            "avec_isin": sum(bool(isins_of(d)) for d in documents),
            "dans_firds_dette": sum(bool(m) for m in matched),
            "obligations_classiques": sum(any(is_plain_bond(r) for r in m) for m in matched),
        }
        rows.append(row)
        print(row, flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
