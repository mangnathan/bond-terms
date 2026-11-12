"""Sortie commune des extracteurs et vérification des citations (ADR 0002).

Chaque champ porte une valeur normalisée, la citation du document qui la justifie et la page où
la citation se trouve. Une valeur dont la citation n'est pas retrouvée dans le document est
refusée : elle ne compte pas comme juste. La comparaison ignore la casse, les accents et les
espaces, que l'extraction de texte des PDF et l'OCR rendent de façon irrégulière.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from bond_terms.documents import normalize
from bond_terms.valeurs import (
    MONTHS_EN,
    MONTHS_FR,
    amount_matches_citation,
    contains,
    date_pattern,
    rate_pattern,
)

FIELDS = (
    "devise",
    "date_echeance",
    "type_taux",
    "taux_fixe",
    "reference_taux",
    "duree_reference",
    "marge_pb",
    "valeur_nominale",
    "montant",
    "rang",
)
PERPETUAL = "perpetuelle"
# Type de taux d'un titre à taux fixe puis variable, ou révisable (ADR 0003).
HYBRID = "fixe_puis_variable"


@dataclass
class Value:
    valeur: str | None = None
    citation: str | None = None
    page: int | None = None
    refusee: bool = False
    # Vrai si la citation n'a été retrouvée qu'en deux morceaux, intitulé et valeur (ADR 0003).
    deux_morceaux: bool = False


@dataclass
class Extraction:
    document_id: str
    extracteur: str
    version: str
    champs: dict[str, Value] = field(default_factory=dict)
    secondes: float | None = None
    jetons_entree: int | None = None
    jetons_sortie: int | None = None
    remarque: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Une citation trop courte (« EUR », « 2027 ») se retrouverait n'importe où dans le document.
MIN_CITATION = 8

# Variantes typographiques d'un même signe : guillemets et tirets.
_TYPOGRAPHY = str.maketrans(
    {"“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "–": "-", "—": "-", "‑": "-", "−": "-"}
)


# Guillemets, et tirets qui ne précèdent pas un chiffre : ils ne portent aucune valeur, et le
# modèle les remplace parfois l'un par l'autre (« Euro (‐ EUR‐) » pour « Euro (“EUR”) »). Un
# tiret devant un chiffre reste : c'est le signe d'une marge ou le séparateur d'une date ISO.
_NEUTRAL_MARKS = re.compile("[\"'`\u2010\u2012\u2015-](?!\\d)|[\"'`]")


def compact(text: str) -> str:
    """Forme de comparaison : minuscules, sans accents ni espaces ; guillemets et tirets sans
    valeur ignorés. Les mots, les chiffres et le signe d'un nombre doivent rester identiques."""
    unified = normalize(text).translate(_TYPOGRAPHY)
    return re.sub(r"\s+", "", _NEUTRAL_MARKS.sub("", unified))


# Numérotation de rubrique en tête de citation : « 24. (i) », « (ix) », « (9) (i) ». Seulement
# entre parenthèses, ou un nombre suivi d'un point puis d'une lettre ou d'une parenthèse : un
# mot qui commence par « i », une date (« 15 March ») ou un taux (« 3.625 ») ne sont pas touchés.
_LEADING_NUMBERING = re.compile(
    r"^(?:\(\s*(?:\d{1,2}|[ivx]{1,5})\s*\)\s*|\d{1,2}\s*\.\s*(?=[a-z(]))+"
)


def page_of(citation: str, pages: list[str]) -> int | None:
    """Première page (numérotée à partir de 1) qui contient la citation, ou None. Les signes de
    ponctuation en tête et en fin (tiret de liste, point final) ne comptent pas, ni la
    numérotation de rubrique en tête, que le modèle recopie parfois mal ; le reste doit figurer
    tel quel dans le document."""
    head = normalize(citation).translate(_TYPOGRAPHY).strip().strip("-\"'•*·.,;: ")
    head = _LEADING_NUMBERING.sub("", head)
    needle = compact(head).strip("-\"'•*·.,;:")
    if len(needle) < MIN_CITATION:
        return None
    for number, text in enumerate(pages, start=1):
        if needle in compact(text):
            return number
    # Une citation peut chevaucher deux pages.
    for number in range(1, len(pages)):
        if needle in compact(pages[number - 1] + pages[number]):
            return number
    return None


# Citation en deux morceaux (ADR 0003) : l'intitulé précède la valeur sur la même page.
TWO_PART_WINDOW = 400
MIN_LABEL = 6


def two_part_page(citation: str, pages: list[str]) -> int | None:
    """Page où l'intitulé (avant le premier deux-points, au moins 6 caractères) précède la
    valeur (au moins 8 caractères) de moins de 400 caractères, ou None. Mesuré sur les jeux
    connus : 29 valeurs justes récupérées, aucune valeur fausse acceptée."""
    if ":" not in citation:
        return None
    label, value = citation.split(":", 1)
    head = compact(_LEADING_NUMBERING.sub("", normalize(label).strip()))
    head = head.strip("-\"'.,;:()")
    tail = compact(value).strip("-\"'•*·.,;:")
    if len(head) < MIN_LABEL or len(tail) < MIN_CITATION:
        return None
    for number, page in enumerate(pages, start=1):
        text = compact(page)
        position = text.find(tail)
        while position >= 0:
            if text.rfind(head, max(0, position - TWO_PART_WINDOW), position) >= 0:
                return number
            position = text.find(tail, position + 1)
    return None


def verify(
    extraction: Extraction,
    pages: list[str],
    two_parts: bool = True,
    amounts: bool = True,
    rates_and_dates: bool = True,
) -> Extraction:
    """Refuse toute valeur sans citation retrouvée ; renseigne la page des autres. Avec
    `two_parts`, une citation peut être retrouvée en deux morceaux (vérification v2, ADR 0003) ;
    avec `amounts`, un montant doit être écrit sans ambiguïté dans sa citation (v3, ADR 0004) ;
    avec `rates_and_dates`, un taux fixe et une échéance doivent l'être aussi (v4, ADR 0005).
    Sans les trois, c'est la vérification de la v0.2 ; sans les deux derniers, celle de la v0.3 ;
    sans le dernier, celle de la v0.4."""
    for name, value in extraction.champs.items():
        value.refusee, value.page, value.deux_morceaux = False, None, False
        if value.valeur is None:
            continue
        page = page_of(value.citation or "", pages)
        if page is None and two_parts:
            page = two_part_page(value.citation or "", pages)
            value.deux_morceaux = page is not None
        if page is not None and amounts and name in AMOUNT_FIELDS and not _amount_cited(value):
            # Fourchette, ou montant mal lu (« 1 000 000,000 » vaut un million) : refusé (ADR 0004).
            page = None
        if page is not None and rates_and_dates and not _value_cited(name, value):
            # Valeur convertie qui n'est pas celle de la citation : « 2,000 % » lu 2 000, année
            # mal recopiée (ADR 0005).
            page = None
        if page is None:
            value.refusee = True
        else:
            value.page = page
    return extraction


AMOUNT_FIELDS = ("montant", "valeur_nominale")


def _amount_cited(value: Value) -> bool:
    try:
        number = float(value.valeur or "")
    except ValueError:
        return False
    return amount_matches_citation(number, value.citation or "")


def _value_cited(name: str, value: Value) -> bool:
    """Un taux fixe ou une échéance doit être écrit dans sa citation ; les autres champs ne sont
    pas contrôlés ici. Une échéance perpétuelle n'a pas de date à retrouver."""
    citation = re.sub(r"\s+", " ", normalize(value.citation or ""))
    try:
        if name == "taux_fixe":
            # « 3. 625 per cent » : nombre coupé après sa virgule par l'extraction de texte.
            variants = [citation, re.sub(r"(?<=\d[.,]) (?=\d)", "", citation)]
            return any(contains(rate_pattern(float(value.valeur or "")), v) for v in variants)
        if name != "date_echeance" or value.valeur == PERPETUAL:
            return True
        day = dt.date.fromisoformat(value.valeur or "")
    except ValueError:
        return False
    variants = [
        citation,
        # « 8 july 202 7 » : année coupée par l'extraction de texte.
        re.sub(r"(?<=\d) (?=\d)", "", citation),
        # « 8november 2051 » : espace perdu entre le jour et le mois.
        re.sub(r"(?<=\d)(?=[a-z]{3})", " ", citation),
    ]
    if any(contains(date_pattern(day), v) for v in variants):
        return True
    # « Interest Payment Date falling in or nearest to February 2028 » : le document ne donne
    # que le mois et l'année, que la citation doit écrire.
    month = f"(?:{MONTHS_EN[day.month - 1]}|{MONTHS_FR[day.month - 1]})"
    return bool(
        re.search(r"nearest|falling in|tombant", citation)
        and re.search(rf"{month}\s+{day.year}\b", citation)
    )


def accepted(value: Value | None) -> str | None:
    """Valeur retenue pour l'évaluation : None si absente ou refusée."""
    if value is None or value.refusee:
        return None
    return value.valeur
