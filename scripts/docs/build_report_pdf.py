"""Compile un rapport LaTeX en PDF avec Tectonic.

Usage :
    python scripts/docs/build_report_pdf.py <source.tex> <sortie.pdf>
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def find_tectonic() -> str:
    path = shutil.which("tectonic")
    if path is None:
        sys.exit("Tectonic est introuvable : https://tectonic-typesetting.github.io")
    return path


def compile_pdf(source: Path, output: Path) -> None:
    with tempfile.TemporaryDirectory() as build_dir:
        # Compilation depuis le dossier du rapport : les chemins des figures restent relatifs.
        subprocess.run(
            [find_tectonic(), "-X", "compile", source.name, "--outdir", build_dir],
            cwd=source.parent,
            check=True,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(build_dir) / f"{source.stem}.pdf", output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    compile_pdf(args.source.resolve(), args.output.resolve())
    print(f"PDF généré : {args.output}")


if __name__ == "__main__":
    main()
