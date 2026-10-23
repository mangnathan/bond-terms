"""Collecte, dans le registre des prospectus de l'ESMA, des documents de la population étudiée.

Usage :
    uv run python -m bond_terms.registre --firds-date AAAA-MM-JJ

Pour chaque ISIN de la population, la réponse brute du registre est gardée en cache : la
collecte reprend là où elle s'est arrêtée et garde une photographie datée du registre, qui
évolue en continu. Une ligne par couple ISIN-document est écrite en Parquet, et un résumé
versionné décrit la collecte.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bond_terms.esma import PoliteClient
from bond_terms.population import ISSUERS, select_population

REGISTER = "https://registers.esma.europa.eu/solr/esma_registers_priii_documents/select"
PAGE_ROWS = 100
REGISTER_FIELDS = [
    "id",
    "document_type",
    "document_type_descr",
    "approval_filing_date",
    "doc_last_update_date",
    "document_rfss_id",
    "instrument_isins",
    "home_member_state_code",
    "party_name",
    "document_languages",
    "request_type",
    "national_document_id",
]
COLUMNS = [
    "isin",
    "issuer_lei",
    "document_id",
    "document_type",
    "document_type_descr",
    "approval_date",
    "last_update",
    "rfss_file_id",
    "rfss_checksum",
    "isins_in_document",
    "home_member_state",
    "party_name",
    "languages",
    "request_type",
    "national_document_id",
]
# Conditions définitives et prospectus d'émission isolée : les deux décrivent une émission.
ISSUE_DOCUMENT_TYPES = ("FTWS", "STDA")


def fetch_documents(client: PoliteClient, isin: str, cache_dir: Path) -> list[dict[str, Any]]:
    """Documents du registre qui citent l'ISIN, lus dans le cache s'ils y sont déjà."""
    cached = cache_dir / f"{isin}.json"
    if cached.exists():
        docs: list[dict[str, Any]] = json.loads(cached.read_text(encoding="utf-8"))
        return docs
    docs, start = [], 0
    while True:
        params = [
            ("q", "type_s:parent"),
            ("fq", f'instrument_isins:"{isin}"'),
            ("fl", ",".join(REGISTER_FIELDS)),
            ("sort", "id asc"),
            ("rows", str(PAGE_ROWS)),
            ("start", str(start)),
            ("wt", "json"),
        ]
        response = client.get_json(REGISTER, params)["response"]
        docs += response["docs"]
        start += PAGE_ROWS
        if start >= response["numFound"]:
            break
    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = cached.with_name(cached.name + ".part")
    partial.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    partial.replace(cached)
    return docs


def document_rows(isin: str, issuer_lei: str, docs: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for doc in docs:
        file_id, _, checksum = str(doc.get("document_rfss_id", "")).partition(",")
        isins = [i.strip() for i in str(doc.get("instrument_isins", "")).split(",") if i.strip()]
        rows.append(
            {
                "isin": isin,
                "issuer_lei": issuer_lei,
                "document_id": str(doc["id"]),
                "document_type": str(doc.get("document_type", "")),
                "document_type_descr": str(doc.get("document_type_descr", "")).strip(),
                "approval_date": str(doc.get("approval_filing_date", ""))[:10],
                "last_update": str(doc.get("doc_last_update_date", ""))[:10],
                "rfss_file_id": file_id,
                "rfss_checksum": checksum,
                "isins_in_document": str(len(isins)),
                "home_member_state": str(doc.get("home_member_state_code", "")),
                "party_name": str(doc.get("party_name", "")),
                "languages": str(doc.get("document_languages", "")),
                "request_type": str(doc.get("request_type", "")),
                "national_document_id": str(doc.get("national_document_id", "")),
            }
        )
    return rows


def summarize(population: list[dict[str, str]], rows: list[dict[str, str]]) -> dict[str, Any]:
    issue_rows = [r for r in rows if r["document_type"] in ISSUE_DOCUMENT_TYPES]
    per_isin = Counter(r["isin"] for r in issue_rows)
    by_issuer = []
    for lei, issuer in ISSUERS.items():
        isins = [p["isin"] for p in population if p["issuer_lei"] == lei]
        by_issuer.append(
            {
                "emetteur": issuer.name,
                "secteur": issuer.sector,
                "obligations": len(isins),
                "obligations_avec_document": sum(per_isin[i] > 0 for i in isins),
                "documents": sum(per_isin[i] for i in isins),
            }
        )
    dates = sorted(r["approval_date"] for r in issue_rows if r["approval_date"])
    return {
        "obligations": len(population),
        "couples_isin_document": len(rows),
        "types_de_documents": dict(Counter(r["document_type"] for r in rows).most_common()),
        "couples_documents_d_emission": len(issue_rows),
        "documents_d_emission_distincts": len({r["document_id"] for r in issue_rows}),
        "obligations_avec_document": len(per_isin),
        "obligations_a_document_unique": sum(n == 1 for n in per_isin.values()),
        "documents_par_obligation_mediane": statistics.median(per_isin.values()) if per_isin else 0,
        "date_approbation_min": dates[0] if dates else "",
        "date_approbation_max": dates[-1] if dates else "",
        "par_emetteur": by_issuer,
    }


def collect(
    client: PoliteClient, firds_index: Path, data_dir: Path, collected_on: str
) -> dict[str, Any]:
    population = select_population(firds_index)
    cache_dir = data_dir / "raw" / "registre" / collected_on
    rows: list[dict[str, str]] = []
    for position, bond in enumerate(population, start=1):
        docs = fetch_documents(client, bond["isin"], cache_dir)
        rows += document_rows(bond["isin"], bond["issuer_lei"], docs)
        if position % 100 == 0:
            print(f"{position}/{len(population)} obligations", flush=True)
    output = data_dir / "interim" / "registre" / f"documents-{collected_on}.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(name, pa.string()) for name in COLUMNS])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), output)
    return {
        "source": "ESMA, registre des prospectus",
        "date_collecte": collected_on,
        "index_firds": firds_index.name,
        "fichier": output.relative_to(data_dir).as_posix(),
    } | summarize(population, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firds-date", required=True, help="publication FIRDS (AAAA-MM-JJ)")
    parser.add_argument("--collected-on", default=dt.date.today().isoformat())
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.1-collecte/data"))
    args = parser.parse_args()
    firds_index = args.data_dir / "interim" / "firds" / f"dette-{args.firds_date}.parquet"
    summary = collect(PoliteClient(), firds_index, args.data_dir, args.collected_on)
    args.summary_dir.mkdir(parents=True, exist_ok=True)
    path = args.summary_dir / f"registre-resume-{args.collected_on}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
