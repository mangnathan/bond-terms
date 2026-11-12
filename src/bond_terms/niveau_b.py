"""Niveau B : remboursement anticipé au gré de l'émetteur, comparé à une annotation (ADR 0005).

Usage :
    uv run python -m bond_terms.niveau_b fiche --jeu test_v05
    uv run python -m bond_terms.niveau_b mesure --jeu test_v05

La clause est absente de FIRDS : la vérité vient d'une annotation humaine, faite une fois sur le
PDF, après le gel des extracteurs et avant l'ouverture du test. Trente documents sont tirés,
équilibrés entre ceux où la rubrique semble applicable et les autres, d'après la seule recherche
de la rubrique dans le texte (jamais d'après une extraction). La mesure est indicative : un seul
annotateur, non spécialiste, et aucun seuil.

La fiche d'annotation contient les valeurs à saisir et la page où la rubrique a été trouvée ;
elle reste hors du dépôt. Le résumé versionné ne contient que des comptes.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bond_terms.documents import normalize
from bond_terms.extraction import Extraction, accepted

SAMPLE_SIZE = 30
SAMPLE_SEED = 20261112
ANSWERS = ("oui", "non", "absente")
COLUMNS = (
    "numero",
    "document_id",
    "page_rubrique",
    "remboursement_emetteur",
    "date_premier_remboursement",
    "commentaire",
    "fichier_pdf",
)

# Intitulé de la rubrique, un éventuel renvoi aux modalités, puis son statut juste après
# (« Issuer Call: Not Applicable », « Call Option (Condition 6 (c)): Applicable »).
_RUBRIC = re.compile(
    r"(?:issuer call|call option|redemption at the option of the issuer|"
    r"option de remboursement (?:anticipe )?au gre de l.emetteur)"
    # Renvoi entre parenthèses, une parenthèse imbriquée au plus : « (Condition 7(c)) ».
    r"(?:\s*\((?:condition|modalite)[^()]*(?:\([^()]*\))?[^()]*\))?"
    r"[^a-z]{0,20}(not applicable|non applicable|sans objet|applicable)"
)
# Rubriques d'options exclues, dont l'intitulé finit aussi par « call option ».
_EXCLUDED_BEFORE = re.compile(r"(?:residual(?: maturity)?|clean.?up|make.?whole)\s*$")


def rubric(pages: list[str]) -> tuple[str, int | None]:
    """« oui », « non » ou « absente » d'après la seule rubrique, et la page où elle figure."""
    for number, page in enumerate(pages, start=1):
        text = re.sub(r"\s+", " ", normalize(page))
        for match in _RUBRIC.finditer(text):
            if _EXCLUDED_BEFORE.search(text[: match.start()]):
                continue
            applicable = match.group(1) == "applicable"
            return ("oui" if applicable else "non"), number
    return "absente", None


def draw(
    found: Mapping[str, tuple[str, int | None]], size: int = SAMPLE_SIZE, seed: int = SAMPLE_SEED
) -> list[str]:
    """Moitié de documents où la rubrique semble applicable, moitié des autres ; s'il en manque
    d'un côté, l'autre complète."""
    rng = random.Random(seed)  # noqa: S311 - tirage d'échantillon, sans enjeu de sécurité
    applicable = sorted(d for d, (answer, _) in found.items() if answer == "oui")
    others = sorted(d for d, (answer, _) in found.items() if answer != "oui")
    rng.shuffle(applicable)
    rng.shuffle(others)
    half = min(size // 2, len(applicable))
    chosen = applicable[:half] + others[: size - half]
    if len(chosen) < size:
        chosen += applicable[half : half + size - len(chosen)]
    return sorted(chosen)


def write_sheet(
    documents: list[str], found: Mapping[str, tuple[str, int | None]], pdf_dir: Path, path: Path
) -> None:
    """Fiche à remplir. Aucune valeur proposée : l'annotation ne doit rien devoir à l'outil."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";", lineterminator="\n")
        writer.writeheader()
        for number, document_id in enumerate(documents, start=1):
            page = found[document_id][1]
            writer.writerow(
                dict.fromkeys(COLUMNS, "")
                | {
                    "numero": number,
                    "document_id": document_id,
                    "page_rubrique": page or "",
                    "fichier_pdf": str(pdf_dir / f"{document_id}.pdf"),
                }
            )


def read_sheet(path: Path) -> dict[str, dict[str, str | None]]:
    """Annotations remplies ; une ligne sans réponse lisible n'est pas comptée."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    annotations: dict[str, dict[str, str | None]] = {}
    for row in rows:
        answer = (row.get("remboursement_emetteur") or "").strip().lower()
        if answer not in ANSWERS:
            continue
        date = (row.get("date_premier_remboursement") or "").strip() or None
        annotations[row["document_id"]] = {"remboursement_emetteur": answer, "date": date}
    return annotations


def measure(
    annotations: Mapping[str, Mapping[str, str | None]], model: Mapping[str, Extraction]
) -> dict[str, Any]:
    """Accord entre l'annotation et la lecture du modèle : clause, puis date quand les deux
    disent la clause applicable. Une valeur refusée par la vérification compte comme absente."""
    pairs: Counter[str] = Counter()
    dates: Counter[str] = Counter()
    for document_id, truth in annotations.items():
        extraction = model[document_id]
        read = accepted(extraction.champs.get("remboursement_emetteur")) or "absente"
        pairs[f"{truth['remboursement_emetteur']} / {read}"] += 1
        if truth["remboursement_emetteur"] == "oui" and read == "oui":
            date = accepted(extraction.champs.get("date_premier_remboursement"))
            dates["juste" if date == truth["date"] else "fausse ou absente"] += 1
    agreed = sum(n for key, n in pairs.items() if key.split(" / ")[0] == key.split(" / ")[1])
    total = sum(pairs.values())
    return {
        "documents_annotes": total,
        "clause_accord": agreed,
        "clause_part_accord": round(agreed / total, 4) if total else None,
        "annotation_contre_lecture": dict(sorted(pairs.items())),
        "date_premier_remboursement": dict(dates),
        "remarque": "mesure indicative : un seul annotateur, non spécialiste, aucun seuil",
    }


def main() -> None:  # pragma: no cover - lit les vrais documents
    import pyarrow.parquet as pq

    from bond_terms.evaluation import load_extractions
    from bond_terms.ocr import pages_by_document

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("etape", choices=["fiche", "mesure"])
    parser.add_argument("--jeu", required=True)
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--ocr-pages", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, default=Path("data/raw/pdf"))
    parser.add_argument("--fiche", type=Path, default=Path("data/interim/niveau-b/fiche.csv"))
    parser.add_argument("--extractions", type=Path, help="sorties du LLM (JSONL), pour la mesure")
    parser.add_argument("--resume", type=Path, help="résumé versionné de la mesure")
    args = parser.parse_args()

    pages = pages_by_document(pq.read_table(args.pages), pq.read_table(args.ocr_pages))
    if args.etape == "fiche":
        if args.fiche.exists():
            raise SystemExit(f"{args.fiche} existe : la fiche n'est tirée qu'une fois")
        found = {d: rubric(p) for d, p in pages.items()}
        chosen = draw(found)
        write_sheet(chosen, found, args.pdf_dir, args.fiche)
        counts = Counter(found[d][0] for d in chosen)
        print(f"{len(chosen)} documents ; rubrique d'après le texte : {dict(counts)}")
        return
    if args.extractions is None or args.resume is None:
        raise SystemExit("--extractions et --resume sont requis pour la mesure")
    result = measure(read_sheet(args.fiche), load_extractions(args.extractions))
    args.resume.parent.mkdir(parents=True, exist_ok=True)
    args.resume.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
