"""Population étudiée : obligations classiques à ISIN français des émetteurs visés (ADR 0001)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from bond_terms.instruments import is_plain_bond


@dataclass(frozen=True)
class Issuer:
    name: str
    sector: str


# Identifiants LEI contrôlés auprès de GLEIF pendant le cadrage. Hermès n'a aucune obligation
# dans FIRDS.
ISSUERS = {
    "R0MUWSFPU8MPRO8K5P83": Issuer("BNP Paribas", "banque"),
    "O2RNE8IBXP4R0TD8PU41": Issuer("Société Générale", "banque"),
    "969500TJ5KRTCJQWXH05": Issuer("Crédit Agricole S.A.", "banque"),
    "9695005MSX1OYEMGDF46": Issuer("BPCE", "banque"),
    "F5WCUMTUM4RKZ1MAIE39": Issuer("AXA", "assurance"),
    "IOG4E947OATN0KJYSD45": Issuer("LVMH", "luxe"),
    "549300VGEJKB7SVUZR78": Issuer("Kering", "luxe"),
    "969500AQW31GYO8JZD66": Issuer("Air France-KLM", "aviation"),
}
ISIN_PREFIX = "FR"


def _french_plain_bonds(firds_index: Path, target_issuers: bool) -> list[dict[str, str]]:
    table = pq.read_table(firds_index)
    # Filtre grossier en colonnes avant de passer aux lignes : l'index compte 600 000 titres.
    issuer = pc.is_in(
        table["issuer_lei"], value_set=pc.cast(list(ISSUERS), table["issuer_lei"].type)
    )
    mask = pc.and_(
        issuer if target_issuers else pc.invert(issuer),
        pc.starts_with(table["isin"], ISIN_PREFIX),
    )
    candidates = table.filter(mask).to_pylist()
    return sorted((row for row in candidates if is_plain_bond(row)), key=lambda r: r["isin"])


def select_population(firds_index: Path) -> list[dict[str, str]]:
    """Obligations classiques à ISIN français des émetteurs visés, triées par ISIN."""
    return _french_plain_bonds(firds_index, target_issuers=True)


def select_other_issuers_bonds(firds_index: Path) -> list[dict[str, str]]:
    """Obligations classiques à ISIN français des autres émetteurs : le vivier du second test."""
    return _french_plain_bonds(firds_index, target_issuers=False)
