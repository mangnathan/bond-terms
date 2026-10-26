"""Recherche d'une valeur connue (date, taux, montant, ISIN) dans le texte normalisé d'un document.

Le texte est celui de `bond_terms.documents.normalize` : minuscules, sans accents. Les documents
écrivent la même valeur de plusieurs façons (« 11 July 2030 », « 11/07/2030 », « 1,500,000,000 »,
« 1 500 000 000 ») : chaque fonction accepte ces variantes, et seulement elles.
"""

from __future__ import annotations

import datetime as dt
import re

MONTHS_EN = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
MONTHS_FR = [
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
]

# Séparateurs de milliers rencontrés : virgule, point, espace, espaces insécables, apostrophe.
_THOUSANDS = r"[,.' \u00a0\u202f]?"
_PERCENT = r"\s*(?:%|per\s*cent|pour\s*cent)"


def date_pattern(day: dt.date) -> re.Pattern[str]:
    d, m, y = day.day, day.month, day.year
    month = f"(?:{MONTHS_EN[m - 1]}|{MONTHS_FR[m - 1]})"
    dd = f"0?{d}"
    suffix = r"(?:st|nd|rd|th|er)?"
    forms = [
        rf"{dd}{suffix}\s+{month}\s*,?\s+{y}",
        rf"{month}\s+{dd}{suffix}\s*,?\s+{y}",
        rf"{dd}\s*[/.-]\s*0?{m}\s*[/.-]\s*{y}",
        rf"{y}-{m:02d}-{d:02d}",
    ]
    return re.compile(r"(?<!\d)(?:" + "|".join(forms) + r")(?!\d)")


def amount_pattern(value: float) -> re.Pattern[str]:
    """Montant entier, avec ou sans séparateurs de milliers."""
    digits = f"{round(value):d}"
    groups = []
    head = len(digits) % 3 or 3
    groups.append(digits[:head])
    groups += [digits[i : i + 3] for i in range(head, len(digits), 3)]
    # Refus d'un groupe de milliers de plus (« ,000 »), mais pas des décimales (« .00 »).
    tail = r"(?!\d|[,.' \u00a0\u202f]\d{3}(?!\d))"
    return re.compile(r"(?<![\d,.])" + _THOUSANDS.join(groups) + tail)


def rate_pattern(rate: float) -> re.Pattern[str]:
    """Taux en pour cent, suivi de « % » ou « per cent » : un nombre nu serait trop ambigu."""
    whole, _, decimals = f"{rate:.6f}".rstrip("0").partition(".")
    number = whole if not decimals else rf"{whole}[.,]{decimals}"
    return re.compile(r"(?<![\d.,])" + number + r"(?:[.,]?0*)?" + _PERCENT)


def contains_isin(text: str, isin: str) -> bool:
    """Un ISIN peut être coupé par un espace ou un retour à la ligne, surtout après une OCR."""
    return isin.lower() in re.sub(r"\s+", "", text)


def contains(pattern: re.Pattern[str], text: str) -> bool:
    return pattern.search(text) is not None
