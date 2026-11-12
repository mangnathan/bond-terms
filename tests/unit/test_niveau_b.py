from pathlib import Path

from bond_terms.extraction import CLAUSE_FIELDS, FIELDS, Extraction, Value, verify
from bond_terms.llm import parse
from bond_terms.niveau_b import draw, measure, read_sheet, rubric, write_sheet


def test_clause_fields_stay_out_of_the_level_a_evaluation() -> None:
    assert not set(CLAUSE_FIELDS) & set(FIELDS)


def test_the_model_answer_carries_the_clause() -> None:
    champs, remark = parse(
        '{"remboursement_emetteur": {"valeur": "oui", "citation": "Issuer Call: Applicable"},'
        ' "date_premier_remboursement": {"valeur": "2029-06-15",'
        ' "citation": "Optional Redemption Date(s): 15 June 2029"}}'
    )
    assert champs["remboursement_emetteur"].valeur == "oui"
    assert champs["date_premier_remboursement"].valeur == "2029-06-15"
    assert remark == ""
    bad, remark = parse('{"remboursement_emetteur": {"valeur": "peut-être", "citation": "x"}}')
    assert bad["remboursement_emetteur"].valeur is None and "remboursement_emetteur" in remark


def test_a_call_date_must_be_written_in_its_citation() -> None:
    citation = "Optional Redemption Date(s): 15 June 2029"
    extraction = Extraction(
        "1", "llm", "v", {"date_premier_remboursement": Value("2028-06-15", citation)}
    )
    verify(extraction, [citation])
    assert extraction.champs["date_premier_remboursement"].refusee


def test_the_rubric_is_found_with_its_status_and_page() -> None:
    assert rubric(["Part A", "17. Issuer Call: Not Applicable"]) == ("non", 2)
    assert rubric(["21 Call Option : Applicable"]) == ("oui", 1)
    assert rubric(["Option de remboursement au gré de l'Émetteur : Sans objet"]) == ("non", 1)
    assert rubric(["Make-Whole Redemption: Applicable"]) == ("absente", None)


def test_the_sample_is_balanced_and_reproducible() -> None:
    found = {f"y{n}": ("oui", 1) for n in range(20)} | {f"n{n}": ("non", 1) for n in range(40)}
    chosen = draw(found, size=10)
    assert sum(d.startswith("y") for d in chosen) == 5
    assert draw(found, size=10) == chosen


def test_when_applicable_clauses_are_rare_the_others_fill_the_sample() -> None:
    found = {"y1": ("oui", 1)} | {f"n{n}": ("absente", None) for n in range(20)}
    assert len(draw(found, size=10)) == 10


def test_the_sheet_proposes_no_value_and_is_read_back(tmp_path: Path) -> None:
    path = tmp_path / "fiche.csv"
    write_sheet(["7", "8"], {"7": ("oui", 12), "8": ("absente", None)}, tmp_path, path)
    text = path.read_text(encoding="utf-8-sig")
    assert ";12;;;" in text
    filled = text.replace(";12;;;", ";12;OUI;2029-06-15;").replace("\n2;8;;;", "\n2;8;;non;")
    path.write_text(filled, encoding="utf-8-sig")
    assert read_sheet(path) == {
        "7": {"remboursement_emetteur": "oui", "date": "2029-06-15"},
        "8": {"remboursement_emetteur": "non", "date": None},
    }


def test_agreement_with_the_annotation() -> None:
    def read(answer: str, date: str | None = None, refused: bool = False) -> Extraction:
        clause = Value(answer, "c", refusee=refused)
        return Extraction(
            "d",
            "llm",
            "v",
            {
                "remboursement_emetteur": clause,
                "date_premier_remboursement": Value(date, "c"),
            },
        )

    annotations = {
        "1": {"remboursement_emetteur": "oui", "date": "2029-06-15"},
        "2": {"remboursement_emetteur": "non", "date": None},
        "3": {"remboursement_emetteur": "oui", "date": "2030-01-01"},
    }
    model = {"1": read("oui", "2029-06-15"), "2": read("non"), "3": read("oui", refused=True)}
    result = measure(annotations, model)
    assert result["clause_accord"] == 2
    assert result["annotation_contre_lecture"]["oui / absente"] == 1
    assert result["date_premier_remboursement"] == {"juste": 1}


def test_excluded_options_do_not_justify_the_general_issuer_call() -> None:
    def clause(citation: str) -> bool:
        extraction = Extraction("1", "llm", "v", {"remboursement_emetteur": Value("oui", citation)})
        verify(extraction, [citation])
        return not extraction.champs["remboursement_emetteur"].refusee

    assert not clause("Residual Maturity Call Option: Applicable")
    assert not clause("Make-Whole Redemption (Condition 7.2.2) Applicable")
    assert not clause("Residual Call Option Make-Whole Call Option Clean-Up Call Option")
    assert clause("20. Call Option (Condition 6 (c)): Applicable")
    assert clause("Optional Redemption from the First Call Date (Condition 6(b)) Applicable")
    assert clause("Option de remboursement au gré de l'Émetteur : Applicable")


def test_the_rubric_skips_excluded_options_and_condition_references() -> None:
    assert rubric(["Residual Maturity Call Option: Applicable"]) == ("absente", None)
    assert rubric(["Clean-up Call Option: Applicable 20. Call Option: Not Applicable"]) == (
        "non",
        1,
    )
    assert rubric(["20. Call Option (Condition 6 (c)): Applicable"]) == ("oui", 1)


def test_a_condition_reference_does_not_hide_not_applicable() -> None:
    assert rubric(["16. Call Option (Condition 7(c)) Not Applicable"]) == ("non", 1)
    assert rubric(
        ["(a) Option de remboursement au gré de l'Émetteur (Modalité 16.4) Non Applicable"]
    ) == (
        "non",
        1,
    )
