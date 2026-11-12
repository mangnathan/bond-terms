import datetime as dt

import pytest

from bond_terms.collecte import (
    MAX_NEW_DOCUMENTS,
    SET_NAME,
    TooManyDocumentsError,
    _table,
    new_couples,
    references,
    summary,
)
from bond_terms.documents import DocumentRef
from bond_terms.extraction import Extraction
from bond_terms.lancement import FALLBACK


def register_row(document_id: str, isin: str, kind: str = "FTWS") -> dict[str, str]:
    return {
        "document_id": document_id,
        "isin": isin,
        "issuer_lei": "LEI",
        "document_type": kind,
        "approval_date": "2026-11-12",
        "rfss_file_id": f"f{document_id}",
        "rfss_checksum": "c",
        "languages": "English",
        "last_update": "ignorée",
    }


def test_only_unseen_issue_documents_are_kept() -> None:
    register = [
        register_row("1", "FR0000000001"),
        register_row("2", "FR0000000002"),
        register_row("3", "FR0000000003", kind="BPRO"),
    ]
    couples = new_couples(register, seen={"1"})
    assert [(c["document_id"], c["jeu"]) for c in couples] == [("2", SET_NAME)]
    # Format du découpage : les colonnes du registre inutiles à l'entrepôt sont laissées.
    assert "last_update" not in couples[0]


def test_a_document_covering_two_isins_is_downloaded_once() -> None:
    couples = new_couples(
        [register_row("2", "FR0000000002"), register_row("2", "FR0000000004")], seen=set()
    )
    assert references(couples) == [DocumentRef("2", "f2", "c", SET_NAME)]


def test_too_many_new_documents_stop_the_collection() -> None:
    register = [register_row(str(n), f"FR{n:010d}") for n in range(MAX_NEW_DOCUMENTS + 1)]
    with pytest.raises(TooManyDocumentsError):
        references(new_couples(register, seen=set()))


def test_raw_tables_are_text_like_the_csv_files() -> None:
    table = _table(
        [{"rubrique_echeance": True, "pages": 3, "erreur": None}],
        ["rubrique_echeance", "pages", "erreur"],
    )
    assert table.to_pylist() == [{"rubrique_echeance": "True", "pages": "3", "erreur": ""}]


def test_weekly_summary_counts_what_was_set_aside() -> None:
    register = [register_row("1", "FR0000000001"), register_row("2", "FR0000000002")]
    quality = [
        {"document_id": "1", "erreur": ""},
        {"document_id": "2", "erreur": "téléchargement : 503"},
    ]
    links = [
        {
            "document_id": "1",
            "isin": "FR0000000001",
            "isin_cite": "True",
            "produit_structure": "True",
        },
    ]
    model = {"1": Extraction("1", "regles", "v", remarque=f"{FALLBACK} : quota")}
    report = summary(
        dt.date(2026, 11, 16),
        "2026-11-14",
        [{"isin": "FR0000000001"}],
        register,
        references(new_couples(register, set())),
        quality,
        links,
        model,
        "quota",
    )
    assert report == {
        "date": "2026-11-16",
        "firds": "2026-11-14",
        "obligations_suivies": 1,
        "documents_registre": 2,
        "nouveaux_documents": 2,
        "documents_lus": 1,
        "erreurs_lecture": 1,
        "rattachements_errones": 0,
        "produits_structures": 1,
        "documents_extraits": 1,
        "documents_en_repli": 1,
        "replis_par_raison": {"quota": 1},
        "arret_quota": True,
    }
