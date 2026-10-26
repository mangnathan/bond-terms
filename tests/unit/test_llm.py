"""Extracteur LLM avec un faux modèle : aucun appel réseau en CI."""

import datetime as dt
import json
from pathlib import Path

import pytest

from bond_terms import llm
from bond_terms.lancement import FALLBACK, costs, run, sample

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


def test_sample_is_fixed_and_shared() -> None:
    documents = {str(n): [f"FR{n}"] for n in range(50)}
    first, second = sample(documents, 5), sample(documents, 5)
    assert first == second and len(first) == 5


def test_code_caps_stay_under_the_free_tier() -> None:
    assert llm.LIMITS["gemini-3.8-flash"].per_day < 20
    assert llm.LIMITS["gemini-3.5-flash-lite"].per_day < 500
    assert 60 / llm.LIMITS["gemini-3.8-flash"].min_interval_s < 5
    assert 60 / llm.LIMITS["gemini-3.5-flash-lite"].min_interval_s <= 12


def test_quota_day_follows_pacific_time() -> None:
    # 2 h du matin à Paris le 27 (1 h UTC) : encore le 26 pour Google.
    assert llm.quota_day(dt.datetime(2026, 10, 27, 1, tzinfo=dt.UTC)) == dt.date(2026, 10, 26)


class FlakyModel(FakeModel):
    """Indisponible pour les `failures` premiers appels."""

    def __init__(self, failures: int):
        super().__init__()
        self.failures = failures
        self.attempts = 0

    def generate(self, system: str, user: str) -> llm.Reply:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise llm.UnavailableError("service indisponible : 503 UNAVAILABLE")
        return super().generate(system, user)


def flaky_extractor(tmp: Path, model: FakeModel, waits: list[float]) -> llm.Extractor:
    budget = llm.Budget(tmp / "quota", model.name, 10, today=dt.date(2026, 10, 26))
    return llm.Extractor(model, tmp / "cache", budget, sleep=waits.append)


def test_temporary_unavailability_is_retried_and_counted(tmp_path: Path) -> None:
    waits: list[float] = []
    model = FlakyModel(failures=2)
    extractor = flaky_extractor(tmp_path, model, waits)
    extraction = extractor.extract("1", PAGES, ["X"])
    assert extraction.extracteur == "llm"
    assert waits == [llm.UNAVAILABLE_WAIT_S, llm.UNAVAILABLE_WAIT_S]
    assert extractor.budget.used() == 3


def test_lasting_unavailability_sends_only_that_document_to_the_rules(tmp_path: Path) -> None:
    model = FlakyModel(failures=3)
    extractor = flaky_extractor(tmp_path, model, [])
    documents = {"1": ["X"], "2": ["Y"]}
    extractions, stopped = run(documents, dict.fromkeys(documents, PAGES), extractor.extract)
    assert stopped == ""
    assert extractions["1"].extracteur == "regles"
    assert "indisponible" in extractions["1"].remarque
    assert extractions["2"].extracteur == "llm"
