from pathlib import Path

from bond_terms.entrepot import read_csv


def test_read_csv_keeps_every_value_as_written(tmp_path: Path) -> None:
    source = tmp_path / "valeurs.csv"
    source.write_text("document_id,drapeau,taux,vide\n007,True,3.8730,\n", encoding="utf-8")
    table = read_csv(source)
    assert table.to_pylist() == [
        {"document_id": "007", "drapeau": "True", "taux": "3.8730", "vide": ""}
    ]
