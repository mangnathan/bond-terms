from typing import Any

from bond_terms.evaluation import (
    bootstrap,
    case_right,
    global_accuracy,
    paired_difference,
    regression_table,
    verdict,
)
from bond_terms.extraction import FIELDS


def row(document_id: str, **verdicts: bool | None) -> dict[str, Any]:
    return {"document_id": document_id, "isin": "X", **dict.fromkeys(FIELDS), **verdicts}


def test_verdict_follows_the_adr_reading() -> None:
    assert verdict(0.99, 0.985, 0.98) == "seuil atteint"
    assert verdict(0.99, 0.97, 0.98) == "seuil atteint, marge statistique insuffisante"
    assert verdict(0.9795, 0.96, 0.98) == "seuil non atteint"
    assert verdict(0.88, 0.84, None) == "mesuré sans seuil"


def test_bootstrap_is_reproducible_and_brackets_the_estimate() -> None:
    documents = [str(n) for n in range(40)]
    right = set(documents[:30])

    def statistic(drawn: list[str]) -> float:
        return sum(d in right for d in drawn) / len(drawn)

    low, high = bootstrap(documents, statistic, draws=500)
    assert (low, high) == bootstrap(documents, statistic, draws=500)
    assert low is not None and high is not None
    assert low < 0.75 < high


def test_global_accuracy_counts_only_compared_pairs() -> None:
    rows = [row("1", devise=True, taux_fixe=False), row("2", devise=True)]
    result = global_accuracy(rows)
    assert (result["justes"], result["compares"]) == (2, 3)


def test_the_llm_is_kept_only_with_a_clear_and_solid_margin() -> None:
    rules = [row(str(n), devise=n % 2 == 0, rang=True) for n in range(60)]
    better = [row(str(n), devise=True, rang=True) for n in range(60)]
    assert paired_difference(rules, better)["llm_retenu"]
    slightly = [row(str(n), devise=n % 2 == 0 or n == 1, rang=True) for n in range(60)]
    assert not paired_difference(rules, slightly)["llm_retenu"]


def test_regression_cases_by_category() -> None:
    rules = [row("1", rang=True), row("2", rang=False), row("3")]
    model = [row("1", rang=False), row("2", rang=True), row("3")]
    cases = [
        {"document_id": "1", "champ": "rang", "categorie": "titre"},
        {"document_id": "2", "champ": "rang", "categorie": "titre"},
        {"document_id": "3", "champ": "rang", "categorie": "non comparé"},
    ]
    assert regression_table(cases, rules, model) == {
        "titre": {"cas": 2, "regles": 1, "llm": 1},
        "non comparé": {"cas": 0, "regles": 0, "llm": 0},
    }
    assert case_right(rules, "3", "rang") is None
