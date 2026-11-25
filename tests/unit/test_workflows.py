"""Règles de sécurité des workflows GitHub, vérifiées sur le texte des fichiers.

- aucune action n'est référencée par une étiquette, qui peut être déplacée : seulement par SHA ;
- aucun checkout ne garde le jeton dans `.git` ;
- le jeton de GitHub n'est donné qu'étape par étape, et jamais à l'étape de la collecte, qui
  ouvre des PDF venus des émetteurs ;
- aucun déclencheur `pull_request_target`, qui donne des droits d'écriture à du code de fork ;
- une valeur venue de l'extérieur (`inputs`, `github.event`) n'est jamais collée dans un script
  shell : elle passe par une variable d'environnement.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))
COLLECTE = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "collecte.yml"
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)")
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
OUTSIDE_VALUE = re.compile(r"\$\{\{[^}]*\b(inputs\.|github\.event\.)")
ENV_ASSIGNMENT = re.compile(r"^\s+[A-Z_][A-Z0-9_]*:\s*\$\{\{")
STEP_START = re.compile(r"^      - ")
TOKEN = re.compile(r"^(\s*)GH_TOKEN:")


def steps(path: Path) -> list[str]:
    """Texte de chaque étape du fichier (les étapes commencent à six espaces)."""
    found: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if STEP_START.match(line):
            found.append([])
        if found:
            found[-1].append(line)
    return ["\n".join(lines) for lines in found]


def test_workflows_are_found() -> None:
    assert COLLECTE in WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_by_commit_sha(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = USES.match(line)
        if match:
            assert PINNED.match(match.group(1)), f"{path.name} : {match.group(1)}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_checkout_keeps_the_token(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    checkouts = len(re.findall(r"uses:\s*actions/checkout@", text))
    assert text.count("persist-credentials: false") == checkouts


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_the_token_is_given_step_by_step_only(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = TOKEN.match(line)
        if match:
            # Dix espaces : l'env d'une étape ; moins, ce serait tout le job ou tout le workflow.
            assert len(match.group(1)) == 10, f"{path.name} : {line.strip()}"


def test_the_step_that_opens_issuer_pdfs_never_gets_the_token() -> None:
    collecting = [s for s in steps(COLLECTE) if "python -m bond_terms.collecte" in s]
    assert len(collecting) == 1
    assert "GH_TOKEN" not in collecting[0] and "github.token" not in collecting[0]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_trigger_gives_write_rights_to_fork_code(path: Path) -> None:
    assert "pull_request_target" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_outside_values_reach_scripts_only_through_the_environment(path: Path) -> None:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if OUTSIDE_VALUE.search(line):
            assert ENV_ASSIGNMENT.match(line), f"{path.name}, ligne {number} : {line.strip()}"
