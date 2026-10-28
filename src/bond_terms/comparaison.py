"""Comparaison d'une extraction avec la vérité terrain de FIRDS (ADR 0001 et 0002).

Chaque champ comparé est « juste » ou « faux » ; une valeur absente ou refusée est fausse. Un
champ que FIRDS ne permet pas de juger (rang non renseigné, montant non comparable, taux fixe
d'une obligation à taux variable) n'est pas compté.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from bond_terms.extraction import HYBRID, PERPETUAL

FIRDS_PERPETUAL = dt.date(9999, 12, 31)

# Le yuan offshore (CNH) n'a pas de code ISO 4217 : FIRDS le déclare en CNY.
CURRENCY_EQUIVALENTS = {"CNH": "CNY"}

# Rangs de FIRDS acceptés pour chaque rang lu dans le document. « Senior non préférée » est
# déclarée tantôt SNDB, tantôt SBOD selon les déclarants (mesuré sur le développement).
SENIORITY = {
    "senior": {"SNDB"},
    "senior_non_prefere": {"SNDB", "SBOD"},
    "subordonne": {"SBOD", "JUND"},
    "subordonne_profond": {"SBOD", "JUND"},
}

_REFERENCE_PREFIXES = {
    "EU00096527": "EURIBOR",
    "EURI": "EURIBOR",
    "ESTR": "ESTR",
    "EONA": "ESTR",
    "SOFR": "SOFR",
    "SONA": "SONIA",
    "SONIA": "SONIA",
    "SARON": "SARON",
    "SORA": "SORA",
    "BBSW": "BBSW",
    "JIBA": "JIBAR",
    "NONIBOR": "NIBOR",
    "NIBOR": "NIBOR",
    "STIBOR": "STIBOR",
    "SWAP": "SWAP",
}


def firds_reference(reference: str | None) -> str | None:
    """Famille d'un taux de référence de FIRDS, qu'il soit un code, un ISIN ou un texte libre."""
    if not reference:
        return None
    upper = reference.upper()
    for prefix, family in _REFERENCE_PREFIXES.items():
        if upper.startswith(prefix):
            return family
    return upper.split()[0]


def firds_term(term: str | None) -> str | None:
    """« 3 MNTH » devient « 3M », « 1 DAYS » « 1D », « 5 YEAR » « 5Y »."""
    if not term:
        return None
    number, _, unit = term.partition(" ")
    letter = {"DAYS": "D", "WEEK": "W", "MNTH": "M", "YEAR": "Y"}.get(unit)
    return f"{int(number)}{letter}" if letter and number.isdigit() else None


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _close(value: str | None, expected: float | None, tolerance: float) -> bool:
    number = _number(value)
    return number is not None and expected is not None and abs(number - expected) <= tolerance


def compare(values: Mapping[str, str | None], truth: Mapping[str, Any]) -> dict[str, bool | None]:
    """Verdict par champ : vrai si juste, faux si faux, None si le champ n'est pas comparé."""
    floating = truth["type_taux"] == "floating"
    maturity = truth["date_echeance"]
    expected_maturity = PERPETUAL if maturity == FIRDS_PERPETUAL else str(maturity)
    currency = values.get("devise")
    verdict: dict[str, bool | None] = {
        "devise": CURRENCY_EQUIVALENTS.get(currency or "", currency) == truth["devise"],
        "date_echeance": values.get("date_echeance") == expected_maturity,
        # Un taux fixe puis variable, ou révisable, est déclaré tantôt fixe, tantôt variable par
        # FIRDS (ADR 0003) : la lecture « fixe puis variable » est juste dans les deux cas.
        "type_taux": values.get("type_taux") == truth["type_taux"]
        or (values.get("type_taux") == HYBRID and truth["type_taux"] in ("fixed", "floating")),
        "taux_fixe": None,
        "reference_taux": None,
        "duree_reference": None,
        "marge_pb": None,
        "valeur_nominale": _close(values.get("valeur_nominale"), truth["valeur_nominale"], 0.5),
        "montant": None,
        "rang": None,
    }
    if not floating and truth["taux_fixe"] is not None:
        verdict["taux_fixe"] = _close(values.get("taux_fixe"), truth["taux_fixe"], 0.00005)
    if floating:
        verdict["reference_taux"] = values.get("reference_taux") == firds_reference(
            truth["reference_taux_variable"]
        )
        expected_term = firds_term(truth["duree_reference"])
        if expected_term:
            verdict["duree_reference"] = values.get("duree_reference") == expected_term
        if truth["marge_points_de_base"] is not None:
            verdict["marge_pb"] = _close(values.get("marge_pb"), truth["marge_points_de_base"], 0.5)
    if truth["montant_comparable"]:
        verdict["montant"] = _close(values.get("montant"), truth["montant_nominal_total"], 0.5)
    if truth["rang"]:
        verdict["rang"] = truth["rang"] in SENIORITY.get(values.get("rang") or "", set())
    return verdict
