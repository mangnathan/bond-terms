"""Extracteur LLM avec un faux modèle : aucun appel réseau en CI."""

import datetime as dt
import json
from pathlib import Path

import pytest

from bond_terms import llm
from bond_terms.lancement import FALLBACK, costs, run

PAGES = ["2. Specified Currency: Euro (EUR)\n", "9. Maturity Date: 8 July 2027\n"]

ANSWER = {
    "devise": {"valeur": "eur", "citation": "Specified Currency: Euro (EUR)"},
    "date_echeance": {"valeur": "2027-07-08", "citation": "Maturity Date: 8 July 2027"},
    "taux_fixe": {"valeur": "3.875", "citation": "Rate of Interest: 3.875 per cent"},
    "montant": {"valeur": "1,000,000", "citation": None},
    "rang": {"valeur": "très senior", "citation": "Status: Senior"},
}


class FakeModel:
    name = "faux-modele"

    def __init__(self, answer: object = ANSWER, refuse_after: int | None = None):
        self.answer = answer
        self.refuse_after = refuse_after
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, system: str, user: str) -> llm.Reply:
        if self.refuse_after is not None and self.calls >= self.refuse_after:
            raise llm.QuotaError("refus de l'API pour quota : RESOURCE_EXHAUSTED")
        self.calls += 1
        self.prompts.append(user)
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return llm.Reply(text, 1200, 150, 1.5)


def extractor(tmp: Path, model: FakeModel, per_day: int = 10) -> llm.Extractor:
    budget = llm.Budget(tmp / "quota", model.name, per_day, today=dt.date(2026, 10, 26))
    return llm.Extractor(model, tmp / "cache", budget)


def test_values_are_cleaned_checked_and_cited(tmp_path: Path) -> None:
    extraction = extractor(tmp_path, FakeModel()).extract("1", PAGES, ["FR0000000001"])
    champs = extraction.champs
    assert champs["devise"].valeur == "EUR" and champs["devise"].page == 1
    assert champs["date_echeance"].page == 2
    # Valeur bien formée mais citation absente du document : refusée.
    assert champs["taux_fixe"].valeur == "3.875" and champs["taux_fixe"].refusee
    # Montant sans citation : refusé aussi.
    assert champs["montant"].refusee
    # Valeur hors format : écartée et signalée.
    assert champs["rang"].valeur is None
    assert extraction.remarque == "format refusé : rang"
    assert extraction.jetons_entree == 1200 and extraction.version == "faux-modele/extraction-v1"


def test_the_isin_and_the_numbered_pages_are_sent(tmp_path: Path) -> None:
    model = FakeModel()
    extractor(tmp_path, model).extract("1", PAGES, ["FR0000000001"])
    assert model.prompts[0].startswith("ISIN: FR0000000001")
    assert "[page 2]" in model.prompts[0]


def test_a_document_is_never_sent_twice(tmp_path: Path) -> None:
    model = FakeModel()
    first = extractor(tmp_path, model)
    first.extract("1", PAGES, ["FR0000000001"])
    second = extractor(tmp_path, model)
    second.extract("1", PAGES, ["FR0000000001"])
    assert model.calls == 1 and second.cache_hits == 1
    # Un texte différent invalide le cache.
    second.extract("1", [*PAGES, "page 3"], ["FR0000000001"])
    assert model.calls == 2


def test_unreadable_answer_gives_no_value(tmp_path: Path) -> None:
    extraction = extractor(tmp_path, FakeModel("pas du json")).extract("1", PAGES, ["X"])
    assert extraction.remarque == "réponse illisible"
    assert all(v.valeur is None for v in extraction.champs.values())


def test_local_cap_stops_before_calling(tmp_path: Path) -> None:
    model = FakeModel()
    capped = extractor(tmp_path, model, per_day=1)
    capped.extract("1", PAGES, ["X"])
    with pytest.raises(llm.QuotaError):
        capped.extract("2", PAGES, ["Y"])
    assert model.calls == 1


def test_quota_refusal_switches_the_rest_to_the_rules(tmp_path: Path) -> None:
    model = FakeModel(refuse_after=1)
    documents = {"1": ["X"], "2": ["Y"], "3": ["Z"]}
    pages = dict.fromkeys(documents, PAGES)
    extractions, stopped = run(documents, pages, extractor(tmp_path, model).extract)
    assert "RESOURCE_EXHAUSTED" in stopped
    assert extractions["1"].extracteur == "llm"
    assert [extractions[d].extracteur for d in ("2", "3")] == ["regles", "regles"]
    assert extractions["3"].remarque.startswith(FALLBACK)
    assert model.calls == 1
    summary = costs(extractions.values())
    assert summary["documents_en_repli"] == 2 and summary["cout_euros"] == 0


def test_long_documents_are_truncated() -> None:
    assert len(llm.document_text(["x" * 100_000])) == llm.MAX_CHARS
