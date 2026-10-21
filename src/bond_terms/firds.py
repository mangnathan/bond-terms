"""Lecture des enregistrements de référence FIRDS (ESMA) pour les titres de dette."""

from __future__ import annotations

from collections.abc import Iterator
from typing import IO
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import iterparse

COLUMNS = [
    "isin",
    "cfi",
    "issuer_lei",
    "currency",
    "nominal_amount",
    "denomination",
    "maturity_date",
    "rate_type",
    "fixed_rate",
    "reference_rate",
    "reference_term",
    "spread_bps",
    "seniority",
    "first_trade_date",
    "full_name",
]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(element: Element | None, *path: str) -> Element | None:
    """Descend dans l'arbre par noms locaux (sans espace de noms) ; None si absent."""
    for name in path:
        if element is None:
            return None
        element = next((c for c in element if local_name(c.tag) == name), None)
    return element


def text(element: Element | None, *path: str) -> str:
    found = child(element, *path)
    return (found.text or "").strip() if found is not None else ""


def parse_record(record: Element) -> dict[str, str]:
    """Champs utiles d'un enregistrement <RefData>, chacun lu à son emplacement exact."""
    debt = child(record, "DebtInstrmAttrbts")
    rate = child(debt, "IntrstRate")
    floating = child(rate, "Fltg")
    # La référence d'un taux variable a trois formes : un code (Indx), un nom libre (Nm) ou l'ISIN
    # d'un indice. La durée (Term) fait partie de la référence : Euribor 3 mois n'est pas 6 mois.
    reference = text(floating, "RefRate", "Indx") or text(floating, "RefRate", "Nm")
    reference = reference or text(floating, "RefRate", "ISIN")
    term_value = text(floating, "Term", "Val")
    term_unit = text(floating, "Term", "Unit")
    if child(rate, "Fxd") is not None:
        rate_type = "fixed"
    elif floating is not None:
        rate_type = "floating"
    else:
        rate_type = ""
    return {
        "isin": text(record, "FinInstrmGnlAttrbts", "Id"),
        "cfi": text(record, "FinInstrmGnlAttrbts", "ClssfctnTp"),
        "issuer_lei": text(record, "Issr"),
        "currency": text(record, "FinInstrmGnlAttrbts", "NtnlCcy"),
        "nominal_amount": text(debt, "TtlIssdNmnlAmt"),
        "denomination": text(debt, "NmnlValPerUnit"),
        "maturity_date": text(debt, "MtrtyDt"),
        "rate_type": rate_type,
        "fixed_rate": text(rate, "Fxd"),
        "reference_rate": reference,
        "reference_term": f"{term_value} {term_unit}" if term_value else "",
        "spread_bps": text(floating, "BsisPtSprd"),
        "seniority": text(debt, "DebtSnrty"),
        "first_trade_date": text(record, "TradgVnRltdAttrbts", "FrstTradDt")[:10],
        "full_name": text(record, "FinInstrmGnlAttrbts", "FullNm"),
    }


def iter_records(xml_file: IO[bytes]) -> Iterator[dict[str, str]]:
    """Lit un fichier FIRDS en flux : un fichier décompressé pèse environ 450 Mo."""
    for _, element in iterparse(xml_file, events=("end",)):
        if local_name(element.tag) == "RefData":
            yield parse_record(element)
            element.clear()
