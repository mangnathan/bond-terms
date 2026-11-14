"""Business case de la v1.0 (ADR 0005), à partir des seules mesures du projet.

Usage :
    uv run python scripts/adr0005/business_case.py

Deux mesures réelles sont comparées sur les mêmes champs :
- la saisie manuelle chronométrée du cadrage (10 documents, `chronometrage-resultats.json`) ;
- l'outil sur le quatrième test, jamais vu (`evaluation-test-v10.json`).

Le temps de relecture d'un document signalé n'est pas mesuré : il est borné par le temps d'une
saisie manuelle, puisque le relecteur part des valeurs et des citations déjà lues. Le volume
de référence est celui des huit émetteurs suivis (ADR 0004).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MANUAL = Path("docs/v0.0-cadrage/data/chronometrage-resultats.json")
TOOL = Path("docs/v1.0-publique/data/evaluation-test-v10.json")
OUTPUT = Path("docs/v1.0-publique/data/business-case.json")
# Champs de la saisie manuelle qui correspondent à ceux de l'outil (le LEI n'est pas extrait).
SAME_FIELDS = {
    "devise": "devise",
    "date_echeance": "date_echeance",
    "type_taux": "type_taux",
    "taux_fixe": "taux_fixe",
    "reference_taux_variable": "reference_taux",
    "marge_points_de_base": "marge_pb",
    "valeur_nominale": "valeur_nominale",
    "montant_nominal_total": "montant",
    "rang": "rang",
}
DOCUMENTS_PER_YEAR = 135  # 130 à 140 documents d'émission par an pour les huit émetteurs
TOOL_SECONDS = 2.0


def share(right: int, total: int) -> float:
    return round(right / total, 4)


def main() -> None:
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    tool = json.loads(TOOL.read_text(encoding="utf-8"))["test_v10"]
    fields = manual["exactitude_par_champ"]
    right = sum(fields[name]["justes"] for name in SAME_FIELDS)
    total = sum(fields[name]["compares"] for name in SAME_FIELDS)
    no_amount = [name for name in SAME_FIELDS if name != "montant_nominal_total"]
    right_na = sum(fields[name]["justes"] for name in no_amount)
    total_na = sum(fields[name]["compares"] for name in no_amount)

    minutes = manual["duree_minutes"]["mediane"]
    review = tool["revue"]["part_en_revue"]
    manual_year = DOCUMENTS_PER_YEAR * minutes
    review_year = DOCUMENTS_PER_YEAR * review * minutes
    result: dict[str, Any] = {
        "exactitude_memes_champs": {
            "saisie_manuelle": {"justes": right, "compares": total, "part": share(right, total)},
            "outil": tool["llm"]["global"],
        },
        "exactitude_memes_champs_sans_montant": {
            "saisie_manuelle": {
                "justes": right_na,
                "compares": total_na,
                "part": share(right_na, total_na),
            },
            "outil": tool["llm"]["global_sans_montant"],
        },
        "temps_par_document": {
            "saisie_manuelle_minutes_mediane": minutes,
            "outil_secondes_mediane": tool["couts_llm"]["latence_mediane_s"],
            "part_des_documents_a_relire": review,
            "relecture_humaine_minutes_par_document_au_plus": round(review * minutes, 2),
        },
        "volume_huit_emetteurs": {
            "documents_par_an": DOCUMENTS_PER_YEAR,
            "saisie_manuelle_heures_par_an": round(manual_year / 60, 1),
            "relecture_heures_par_an_au_plus": round(review_year / 60, 1),
            "temps_humain_economise_au_moins": round(1 - review, 3),
        },
        "pour_1000_documents": {
            "saisie_manuelle_heures": round(1000 * minutes / 60, 1),
            "relecture_heures_au_plus": round(1000 * review * minutes / 60, 1),
            "calcul_machine_minutes": round(1000 * TOOL_SECONDS / 60, 1),
        },
        "cout_euros": 0,
        "hypotheses": [
            "Saisie manuelle : 10 documents, une seule personne non spécialiste, au cadrage.",
            "Relecture d'un document signalé : au plus le temps d'une saisie manuelle.",
            "Les documents non signalés ne sont pas relus ; ils restent juste à 93 % environ.",
        ],
    }
    OUTPUT.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
