from pathlib import Path
from typing import Any

import pyarrow as pa

from bond_terms.ocr import empty_pages, merge_pages, run, summarize
from bond_terms.rattachement import check
from bond_terms.rattachement import summarize as summarize_links


def pages(rows: list[tuple[str, str, str]]) -> pa.Table:
    return pa.Table.from_pylist([{"document_id": d, "page": p, "texte": t} for d, p, t in rows])


PAGES = pages(
    [("1", "1", "isin: fr0000000001"), ("1", "2", "  \n"), ("2", "1", ""), ("2", "2", "")]
)


def test_empty_pages_lists_only_pages_without_text() -> None:
    assert empty_pages(PAGES) == {"1": [2], "2": [1, 2]}


def test_run_reads_each_page_once_thanks_to_the_cache(tmp_path: Path) -> None:
    rendered: list[tuple[str, int]] = []

    def render(pdf: Path, page: int) -> Any:
        rendered.append((pdf.stem, page))
        return f"image {pdf.stem}-{page}"

    def engine(image: Any) -> list[str]:
        return [f"lu sur {image}", "isin fr0000000002"]

    todo = {"2": [1, 2]}
    first, durations = run(todo, tmp_path, tmp_path / "cache", render, engine)
    second, again = run(todo, tmp_path, tmp_path / "cache", render, engine)
    assert rendered == [("2", 1), ("2", 2)]
    assert len(durations) == 2 and again == []
    assert first.to_pylist() == second.to_pylist()
    assert first.column("texte").to_pylist()[0] == "lu sur image 2-1\nisin fr0000000002"


def test_merge_pages_puts_ocr_text_back_in_page_order() -> None:
    ocr = pages([("2", "2", "page deux"), ("2", "1", "page un")])
    texts = merge_pages(PAGES, ocr)
    assert texts["2"] == "page un\npage deux"
    assert texts["1"] == "isin: fr0000000001\n  \n"


def test_summary_counts_pages_left_empty() -> None:
    ocr = pages([("2", "1", "texte"), ("2", "2", " ")])
    summary = summarize({"2": [1, 2]}, ocr, {"1": "test", "2": "test"}, [1.0, 3.0])
    assert summary["test"] == {
        "documents_avec_pages_sans_texte": 1,
        "pages_lues_par_ocr": 2,
        "pages_toujours_vides": 1,
    }
    assert summary["secondes_par_page_mediane"] == 2.0


def test_link_check_keeps_only_documents_that_cite_the_isin() -> None:
    couples = [
        {"document_id": "1", "isin": "FR0000000001", "jeu": "developpement"},
        {"document_id": "1", "isin": "FR0000000009", "jeu": "developpement"},
        {"document_id": "3", "isin": "FR0000000003", "jeu": "test"},
    ]
    rows = check(couples, {"1": "ISIN : FR0000 000001"})
    assert [r["isin_cite"] for r in rows] == ["True", "False", "False"]
    assert summarize_links(rows) == {
        "developpement": {
            "couples": 2,
            "isin_cite": 1,
            "anomalies_de_rattachement": 1,
            "produits_structures": 0,
        },
        "test": {
            "couples": 1,
            "isin_cite": 0,
            "anomalies_de_rattachement": 1,
            "produits_structures": 0,
        },
    }


def test_structured_notes_declared_as_plain_bonds_are_detected() -> None:
    from bond_terms.rattachement import is_structured

    assert is_structured("emission d'eur 30.000.000 de titres a coupon et a remboursement indexe")
    assert is_structured("15 titres a coupon indexe : applicable - titres a coupon indexe sur taux")
    assert not is_structured(
        "15 titres a coupon indexe : sans objet\n16 titres a taux fixe : applicable"
    )
    assert not is_structured("index linked interest note provisions: not applicable")
