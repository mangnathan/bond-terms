from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from bond_terms.firds import COLUMNS
from bond_terms.population import ISSUERS, select_population

LVMH = "IOG4E947OATN0KJYSD45"
OTHER_ISSUER = "529900YISWVEKZT7CN18"


def security(isin: str, lei: str, **fields: str) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    return row | {"isin": isin, "issuer_lei": lei, "cfi": "DBFTFB", "rate_type": "fixed"} | fields


def test_population_keeps_plain_french_bonds_of_target_issuers(tmp_path: Path) -> None:
    rows = [
        security("FR0000000002", LVMH, fixed_rate="3.5"),
        security("FR0000000001", LVMH, fixed_rate="3.25"),
        security("XS0000000001", LVMH, fixed_rate="3"),  # ISIN international
        security("FR0000000003", OTHER_ISSUER, fixed_rate="3"),  # émetteur hors périmètre
        security("FR0000000004", LVMH, fixed_rate="46"),  # produit structuré
    ]
    path = tmp_path / "dette.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    selected = select_population(path)
    assert [r["isin"] for r in selected] == ["FR0000000001", "FR0000000002"]


def test_eight_issuers_with_valid_lei_format() -> None:
    assert len(ISSUERS) == 8
    assert all(len(lei) == 20 and lei.isalnum() for lei in ISSUERS)
