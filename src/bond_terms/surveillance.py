"""Surveillance de la qualité de la collecte et alertes (ADR 0004).

Usage :
    uv run python -m bond_terms.surveillance --instantane data/instantane/instantane.json

Les seuils de l'ADR 0004 (part des documents en revue, des valeurs refusées, des documents avec
exception) sont jugés sur une fenêtre glissante : les dernières collectes, jusqu'à réunir au moins
MIN_DOCUMENTS documents. Avec deux à trois documents par semaine, une part hebdomadaire varie trop
pour être jugée : un seul document avec exception sur trois fait déjà 33 %. Tant que la fenêtre
compte moins de documents, les parts sont affichées sans alerte.

Un arrêt pour quota alerte tout de suite : des documents ont été lus par les règles. Le texte des
alertes n'est écrit que s'il y en a ; le workflow ouvre alors une issue GitHub.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bond_terms import instantane

THRESHOLDS = {
    "part_en_revue": 0.30,
    "part_valeurs_refusees": 0.10,
    "part_documents_avec_exception": 0.40,
}
LABELS = {
    "part_en_revue": "Documents envoyés en revue",
    "part_valeurs_refusees": "Valeurs refusées",
    "part_documents_avec_exception": "Documents avec exception",
}
MIN_DOCUMENTS = 20
PREFIX = "collecte-"


def collected(snapshot: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Documents lus par chaque collecte : {date: {document: entrée}}. Un document qui couvre
    plusieurs ISIN n'est compté qu'une fois."""
    by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for documents in snapshot["obligations"].values():
        for entry in documents:
            if entry["jeu"].startswith(PREFIX):
                day = entry["jeu"].removeprefix(PREFIX)
                by_date.setdefault(day, {})[entry["document_id"]] = entry
    return by_date


def window(snapshot: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Dernières collectes, de la plus récente à la plus ancienne, jusqu'à MIN_DOCUMENTS."""
    days: list[str] = []
    entries: list[dict[str, Any]] = []
    for day, documents in sorted(collected(snapshot).items(), reverse=True):
        days.append(day)
        entries += documents.values()
        if len(entries) >= MIN_DOCUMENTS:
            break
    return days, entries


def shares(entries: list[dict[str, Any]]) -> dict[str, float | None]:
    given = [c for e in entries for c in e["champs"].values() if c["statut"] != "absente"]

    def share(count: int, total: int) -> float | None:
        return round(count / total, 4) if total else None

    return {
        "part_en_revue": share(sum(e["en_revue"] for e in entries), len(entries)),
        "part_valeurs_refusees": share(sum(c["statut"] == "refusee" for c in given), len(given)),
        "part_documents_avec_exception": share(
            sum(bool(e["exceptions"]) for e in entries), len(entries)
        ),
    }


def percent(value: float) -> str:
    return f"{value * 100:.1f} %".replace(".", ",")


def check(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Parts de la fenêtre et alertes ; une liste d'alertes vide signifie que tout va bien."""
    days, entries = window(snapshot)
    measured = shares(entries)
    judged = len(entries) >= MIN_DOCUMENTS
    alerts = []
    if judged:
        for name, threshold in THRESHOLDS.items():
            value = measured[name]
            if value is not None and value > threshold:
                alerts.append(
                    f"{LABELS[name]} : {percent(value)} sur les {len(entries)} derniers documents, "
                    f"au-dessus du seuil de {percent(threshold)}."
                )
    if snapshot["collectes"] and snapshot["collectes"][-1]["arret_quota"]:
        last = snapshot["collectes"][-1]
        alerts.append(
            f"Arrêt pour quota lors de la collecte du {last['date']} : "
            f"{last['documents_en_repli']} documents lus par les règles au lieu du LLM."
        )
    return {
        "fenetre": days,
        "documents": len(entries),
        "jugee": judged,
        "parts": measured,
        "seuils": THRESHOLDS,
        "alertes": alerts,
    }


def issue_body(result: dict[str, Any]) -> str:
    """Texte de l'issue GitHub ouverte par le workflow."""
    lines = ["La collecte hebdomadaire a franchi un seuil de surveillance (ADR 0004).", ""]
    lines += [f"- {alert}" for alert in result["alertes"]]
    if result["fenetre"]:
        lines += [
            "",
            f"Fenêtre : collectes du {', '.join(result['fenetre'])}, "
            f"{result['documents']} documents.",
        ]
    return "\n".join(lines) + "\n"


def main() -> None:  # pragma: no cover - lit l'instantané publié
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instantane", type=Path, default=Path("data/instantane/instantane.json"))
    parser.add_argument("--alertes", type=Path, default=Path("data/instantane/alertes.md"))
    args = parser.parse_args()
    result = check(instantane.read(args.instantane))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    args.alertes.unlink(missing_ok=True)
    if result["alertes"]:
        args.alertes.parent.mkdir(parents=True, exist_ok=True)
        args.alertes.write_bytes(issue_body(result).encode("utf-8"))


if __name__ == "__main__":
    main()
