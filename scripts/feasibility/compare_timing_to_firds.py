"""Compare la saisie manuelle chronométrée à FIRDS : temps par document et exactitude humaine.

Les règles de comparaison sont celles de l'ADR 0001. Les documents dont le titre n'est pas une
obligation classique (bond_terms.instruments.is_plain_bond) comptent dans la mesure du temps
mais pas dans celle de l'exactitude. Le montant total n'est comparé que pour les ISIN qui n'ont
qu'un seul document dans le registre des prospectus.

Usage :
    uv run python scripts/feasibility/compare_timing_to_firds.py
"""

from __future__ import annotations

import csv
import json
import statistics
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from bond_terms.instruments import is_plain_bond

REGISTER = "https://registers.esma.europa.eu/solr/esma_registers_priii_documents/select"
USER_AGENT = "bond-terms (projet personnel ; github.com/mangnathan)"
FIRDS_INDEX = Path("data/interim/firds-dette.csv")
SHEET = Path("docs/v0.0-cadrage/data/chronometrage-saisie-manuelle.csv")
DETAIL = Path("docs/v0.0-cadrage/data/chronometrage-comparaison.csv")
SUMMARY = Path("docs/v0.0-cadrage/data/chronometrage-resultats.json")
PAUSE_S = 1.0
RATE_TYPES = {"fixe": "fixed", "variable": "floating"}
# Rang de la dette dans FIRDS : SNDB senior, SBOD subordonné, MZZD mezzanine, JUND junior.
FIRDS_SENIORITY = {"SNDB": "senior", "SBOD": "subordonne", "MZZD": "mezzanine", "JUND": "junior"}
# Codes de référence de FIRDS et noms courants dans les documents.
REFERENCE_NAMES = {"EURI": "EURIBOR", "ESTR": "ESTR", "SOFR": "SOFR", "SONA": "SONIA"}


def minutes(start: str, end: str) -> float:
    def seconds(clock: str) -> int:
        parts = [int(p) for p in clock.split(":")] + [0]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    return (seconds(end) - seconds(start)) / 60


def seniority_of(entered: str) -> str:
    text = entered.lower()
    if "unsubordinated" in text or "senior" in text:
        return "senior"
    if "subordinated" in text:
        return "subordonne"
    # « Unsecured » décrit l'absence de garantie, pas le rang.
    return ""


def same_number(entered: str, expected: str, decimals: int = 0) -> bool:
    try:
        return round(float(entered), decimals) == round(float(expected), decimals)
    except ValueError:
        return False


def documents_in_register(isin: str) -> int:
    params = [("q", "type_s:parent"), ("fq", f'instrument_isins:"{isin}"'), ("rows", "0")]
    request = urllib.request.Request(
        f"{REGISTER}?{urllib.parse.urlencode(params + [('wt', 'json')])}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        count: int = json.load(response)["response"]["numFound"]
    return count


def compare(entry: dict[str, str], truth: dict[str, str], documents: int) -> list[tuple[str, str]]:
    """Renvoie (champ, verdict) avec verdict « juste », « faux » ou « non comparé : raison »."""
    verdicts = [
        ("devise", entry["devise"].strip().upper() == truth["currency"]),
        ("date_echeance", entry["date_echeance"] == truth["maturity_date"]),
        ("type_taux", RATE_TYPES.get(entry["type_taux"], "") == truth["rate_type"]),
        ("valeur_nominale", same_number(entry["valeur_nominale"], truth["denomination"])),
        ("lei_emetteur", entry["lei_emetteur"].strip() == truth["issuer_lei"]),
    ]
    results = [(field, "juste" if ok else "faux") for field, ok in verdicts]
    if truth["rate_type"] == "fixed":
        ok = same_number(entry["taux_fixe"], truth["fixed_rate"], decimals=4)
        results.append(("taux_fixe", "juste" if ok else "faux"))
    if truth["rate_type"] == "floating":
        expected = REFERENCE_NAMES.get(truth["reference_rate"], truth["reference_rate"])
        ok = entry["reference_taux_variable"].strip().upper() == expected.upper()
        results.append(("reference_taux_variable", "juste" if ok else "faux"))
        ok = same_number(entry["marge_points_de_base"], truth["spread_bps"])
        results.append(("marge_points_de_base", "juste" if ok else "faux"))
        # La fiche n'avait pas de colonne pour la durée de la référence.
        results.append(("duree_reference", "non comparé : absente de la fiche"))
    if documents == 1:
        ok = same_number(entry["montant_nominal_total"], truth["nominal_amount"])
        results.append(("montant_nominal_total", "juste" if ok else "faux"))
    else:
        results.append(("montant_nominal_total", f"non comparé : {documents} documents"))
    if truth["seniority"]:
        ok = seniority_of(entry["rang"]) == FIRDS_SENIORITY.get(truth["seniority"], "?")
        results.append(("rang", "juste" if ok else "faux"))
    else:
        results.append(("rang", "non comparé : absent de FIRDS"))
    return results


def main() -> None:
    with FIRDS_INDEX.open(encoding="utf-8") as f:
        firds = {row["isin"]: row for row in csv.DictReader(f)}
    with SHEET.open(encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))

    durations = {e["numero"]: minutes(e["heure_debut"], e["heure_fin"]) for e in sheet}
    detail_rows = []
    excluded = {}
    per_field: dict[str, Counter[str]] = {}
    for entry in sheet:
        truth = firds[entry["isin"]]
        if not is_plain_bond(truth):
            excluded[entry["numero"]] = "pas une obligation classique selon FIRDS"
            continue
        documents = documents_in_register(entry["isin"])
        time.sleep(PAUSE_S)
        for field, verdict in compare(entry, truth, documents):
            per_field.setdefault(field, Counter())[verdict] += 1
            row = {"numero": entry["numero"], "isin": entry["isin"], "champ": field}
            detail_rows.append(row | {"verdict": verdict})

    compared = {f: c["juste"] + c["faux"] for f, c in per_field.items()}
    correct = sum(c["juste"] for c in per_field.values())
    summary = {
        "documents": len(sheet),
        "duree_minutes": {
            "par_document": durations,
            "total": sum(durations.values()),
            "mediane": statistics.median(durations.values()),
            "moyenne": round(statistics.mean(durations.values()), 2),
            "resolution": "heures relevées à la minute : chaque durée est connue à 1 minute près",
        },
        "exclus_de_l_exactitude": excluded,
        "exactitude_par_champ": {
            f: {"justes": per_field[f]["juste"], "compares": n} for f, n in compared.items() if n
        },
        "exactitude_globale": {
            "justes": correct,
            "compares": sum(compared.values()),
            "taux": round(correct / sum(compared.values()), 3),
        },
    }
    with DETAIL.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(detail_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(detail_rows)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
