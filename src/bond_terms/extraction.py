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


def compact(text: str) -> str:
    """Forme de comparaison : minuscules, sans accents ni espaces."""
    return re.sub(r"\s+", "", normalize(text))


def page_of(citation: str, pages: list[str]) -> int | None:
    """Première page (numérotée à partir de 1) qui contient la citation, ou None."""
    needle = compact(citation)
    if not needle:
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
