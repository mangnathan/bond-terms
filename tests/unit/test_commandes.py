"""Chaque commande du projet se lance et affiche son aide.

Un module sans `if __name__ == "__main__": main()` s'importe sans erreur mais ne fait rien :
l'ouverture du test a été lancée une première fois pour rien à cause de cet oubli.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "bond_terms"
COMMANDS = sorted(
    path.stem for path in SOURCE.glob("*.py") if "\ndef main(" in path.read_text(encoding="utf-8")
)


def test_commands_are_found() -> None:
    assert "ouverture" in COMMANDS and "lancement" in COMMANDS


@pytest.mark.parametrize("module", COMMANDS)
def test_command_prints_its_help(module: str) -> None:
    result = subprocess.run(  # noqa: S603 - module du projet, arguments fixes
        [sys.executable, "-m", f"bond_terms.{module}", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        # Sous Windows, l'aide accentuée serait écrite en cp1252 sans cette variable.
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
