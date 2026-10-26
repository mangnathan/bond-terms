"""Sortie commune des extracteurs et vérification des citations (ADR 0002).

Chaque champ porte une valeur normalisée, la citation du document qui la justifie et la page où
la citation se trouve. Une valeur dont la citation n'est pas retrouvée dans le document est
refusée : elle ne compte pas comme juste. La comparaison ignore la casse, les accents et les
espaces, que l'extraction de texte des PDF et l'OCR rendent de façon irrégulière.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from bond_terms.documents import normalize

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


@dataclass
class Value:
    valeur: str | None = None
    citation: str | None = None
    page: int | None = None
    refusee: bool = False


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


def compact(text: str) -> str:
    """Forme de comparaison : minuscules, sans accents ni espaces, guillemets et tirets unifiés.
    Les mots et les chiffres doivent rester identiques."""
    return re.sub(r"\s+", "", normalize(text).translate(_TYPOGRAPHY))


def page_of(citation: str, pages: list[str]) -> int | None:
    """Première page (numérotée à partir de 1) qui contient la citation, ou None. Les signes de
    ponctuation en tête et en fin (tiret de liste, point final) ne comptent pas."""
    needle = compact(citation).strip("-\"'•*·.,;:")
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


def verify(extraction: Extraction, pages: list[str]) -> Extraction:
    """Refuse toute valeur sans citation retrouvée ; renseigne la page des autres."""
    for value in extraction.champs.values():
        if value.valeur is None:
            continue
        page = page_of(value.citation or "", pages)
        if page is None:
            value.refusee = True
        else:
            value.page = page
    return extraction


def accepted(value: Value | None) -> str | None:
    """Valeur retenue pour l'évaluation : None si absente ou refusée."""
    if value is None or value.refusee:
        return None
    return value.valeur
