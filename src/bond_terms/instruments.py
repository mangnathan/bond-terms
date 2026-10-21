"""Règles métier sur les instruments de dette décrits dans FIRDS."""

from __future__ import annotations

from collections.abc import Mapping

# Codes CFI des obligations (DB) et des titres de dette à moyen terme, dont les EMTN (DT).
BOND_CFI_PREFIXES = ("DB", "DT")


def is_plain_bond(record: Mapping[str, str]) -> bool:
    """Obligation classique : taux fixe positif, ou taux variable indexé sur une vraie référence.

    Beaucoup de produits structurés sont classés en dette dans FIRDS mais affichent un taux
    fixe nul ou une référence « FORMULA » : ils sont exclus du périmètre du projet.
    """
    if not record.get("cfi", "").startswith(BOND_CFI_PREFIXES):
        return False
    rate_type = record.get("rate_type", "")
    if rate_type == "fixed":
        try:
            return float(record.get("fixed_rate") or 0) > 0
        except ValueError:
            return False
    return rate_type == "floating" and record.get("reference_rate", "") not in ("", "FORMULA")
