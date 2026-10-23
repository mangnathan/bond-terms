"""Règles métier sur les instruments de dette décrits dans FIRDS."""

from __future__ import annotations

from collections.abc import Mapping

# Codes CFI des obligations (DB) et des titres de dette à moyen terme, dont les EMTN (DT).
BOND_CFI_PREFIXES = ("DB", "DT")
# Au-delà, un « taux fixe » est en pratique un coupon cumulé de produit structuré (46 %, 60 %...).
# Mesuré sur la population visée : 722 titres jusqu'à 10 %, devises émergentes comprises, puis
# presque uniquement des produits structurés en euros.
MAX_PLAIN_FIXED_RATE = 10.0
# Références qui ne désignent pas un vrai taux de marché.
NOT_A_REFERENCE = ("", "FORMULA", "OTHER")


def is_plain_bond(record: Mapping[str, str]) -> bool:
    """Obligation classique : taux fixe plausible, ou taux variable indexé sur une vraie référence.

    Beaucoup de produits structurés sont classés en dette dans FIRDS : taux fixe nul ou
    anormalement élevé, référence « FORMULA » ou « OTHER », panier d'indices. Ils sont exclus du
    périmètre du projet.
    """
    if not record.get("cfi", "").startswith(BOND_CFI_PREFIXES):
        return False
    rate_type = record.get("rate_type", "")
    if rate_type == "fixed":
        try:
            rate = float(record.get("fixed_rate") or 0)
        except ValueError:
            return False
        return 0 < rate <= MAX_PLAIN_FIXED_RATE
    reference = record.get("reference_rate", "")
    return (
        rate_type == "floating"
        and reference.upper() not in NOT_A_REFERENCE
        and "BASKET" not in reference.upper()
    )
