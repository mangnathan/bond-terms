import datetime as dt
from pathlib import Path

import pytest

from bond_terms.extraction import Extraction
from bond_terms.lancement import FALLBACK
from bond_terms.ouverture import OpeningRefusedError, check_opening, incomplete, opening_record


def test_first_opening_is_allowed(tmp_path: Path) -> None:
    check_opening(tmp_path / "registre.json", tmp_path / "resultats.json", resume=False)


def test_a_second_opening_is_refused_once_results_exist(tmp_path: Path) -> None:
    (tmp_path / "resultats.json").write_text("{}")
    with pytest.raises(OpeningRefusedError):
        check_opening(tmp_path / "registre.json", tmp_path / "resultats.json", resume=True)


def test_an_interrupted_opening_needs_an_explicit_resume(tmp_path: Path) -> None:
    (tmp_path / "registre.json").write_text("{}")
    with pytest.raises(OpeningRefusedError):
        check_opening(tmp_path / "registre.json", tmp_path / "resultats.json", resume=False)
    check_opening(tmp_path / "registre.json", tmp_path / "resultats.json", resume=True)


def test_documents_not_read_by_the_llm_block_the_results() -> None:
    done = Extraction("1", "llm", "v")
    fallback = Extraction("2", "regles", "v", remarque=f"{FALLBACK} : service indisponible")
    assert incomplete({"1": done, "2": fallback}) == ["2"]


def test_opening_record_names_the_frozen_extractors() -> None:
    record = opening_record("abc123", dt.datetime(2026, 10, 27, 12, tzinfo=dt.UTC))
    assert record["commit"] == "abc123"
    assert record["llm"] == "gemini-3.5-flash-lite/extraction-v3"
    assert record["jeux"] == ["test", "test_nouveaux_emetteurs"]
