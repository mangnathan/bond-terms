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


# Nombre écrit avec séparateurs : « 1,000,000 », « 1.000.000,00 », « 1 000 000,000 ».
_NUMBER_TOKEN = re.compile(r"\d{1,3}(?:[ \u00a0\u202f,.']\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
_RANGE = re.compile(r"\bbetween\b.{0,40}\band\b|\bentre\b.{0,40}\bet\b|\bfrom\b.{0,30}\bto\b")


def numbers_in(text: str) -> set[float]:
    """Toutes les lectures plausibles des nombres d'un texte, en notation anglaise
    (« 1,000,000.00 »), européenne (« 1.000.000,00 ») ou française à espaces (« 1 000 000,000 »,
    où la virgule est décimale : un million)."""
    found: set[float] = set()
    # Variante recollée : l'extraction de texte coupe parfois un nombre (« 1,0 00,000,000 »).
    glued = re.sub(r"(?<=[\d,.]) (?=[\d,.])", "", text)
    for token in _NUMBER_TOKEN.findall(text) + _NUMBER_TOKEN.findall(glued):
        compact = re.sub(r"[ \u00a0\u202f']", "", token)
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", compact):
            found.add(float(compact.replace(",", "")))
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", compact):
            found.add(float(compact.replace(".", "").replace(",", ".")))
        if re.fullmatch(r"\d+(?:[.,]\d+)?", compact):
            found.add(float(compact.replace(",", ".")))
        # « 1 000 000,000 » : groupes séparés par des espaces, puis des décimales après la virgule.
        if re.fullmatch(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+,\d+", token):
            found.add(float(compact.replace(",", ".")))
    return found


# Groupes séparés par des espaces puis trois chiffres après une virgule : « 750 000,000 » vaut
# 750 millions (virgule des milliers) et « 1 000 000,000 » un million (virgule décimale) dans les
# documents mesurés. L'écriture ne permet pas de trancher : le montant part en revue.
_AMBIGUOUS = re.compile(r"\d{1,3}(?:[   ]\d{3})+,\d{3}(?!\d)")
# Montant écrit en lettres : « une valeur nominale d'un euro ».
_ONE_IN_WORDS = re.compile(r"\b(?:un|une|one)\s+(?:euro|eur|dollar|pound|livre)")


def amount_matches_citation(value: float, citation: str) -> bool:
    """Un montant n'est accepté que si sa citation l'écrit sans ambiguïté, et ne donne pas une
    fourchette."""
    lowered = citation.lower()
    if _RANGE.search(lowered) or _AMBIGUOUS.search(lowered):
        return False
    if abs(value - 1) < 0.5 and _ONE_IN_WORDS.search(lowered):
        return True
    return any(abs(number - value) < 0.5 for number in numbers_in(citation))


# Titre d'émission en tête de document, par exemple « €500,000,000 3.625 per cent. Bonds
# due 13 December 2026 ».
_ISSUE_TITLE = re.compile(
    r"(?:€|eur|usd|\$|£|gbp|chf)\s?\d[\d,. ]{4,}\d\s.{0,80}?(?:notes|bonds|obligations)\s+due\s+"
    r"(?:\d{1,2}\s+)?([a-z]+\s+\d{4})"
)
TITLE_SCOPE = 4_000


def several_bonds(normalized: str) -> bool:
    """Vrai si le début du document annonce des obligations d'échéances différentes : le
    prospectus décrit plusieurs titres, et le modèle risque de lire le voisin."""
    head = re.sub(r"\s+", " ", normalized)[:TITLE_SCOPE]
    return len({match.group(1) for match in _ISSUE_TITLE.finditer(head)}) >= 2
