"""Évaluation d'un ou deux extracteurs selon les règles fixées à l'avance (ADR 0001 et 0002).

Usage :
    uv run python -m bond_terms.evaluation

- Exactitude par champ, avec son intervalle à 95 % (bootstrap par document), jugée sur
  l'estimation : « seuil atteint », « seuil atteint, marge statistique insuffisante » ou
  « seuil non atteint ». Le montant est mesuré sans seuil (ADR 0002).
- Exactitude globale sur toutes les paires (document, champ) qui ont une valeur dans FIRDS,
  montant compris, comme le définit l'ADR 0001.
- Règle de choix : le LLM n'est retenu que s'il dépasse les règles d'au moins 2 points
  d'exactitude globale, avec une borne basse de l'intervalle de l'écart (bootstrap apparié par
  document) au-dessus de zéro.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import duckdb

from bond_terms import llm, regles
from bond_terms.extraction import FIELDS, Extraction, Value
from bond_terms.lancement import KNOWN_SETS, TRUTH_SQL, score

THRESHOLDS: dict[str, float | None] = {
    "devise": 0.98,
    "date_echeance": 0.98,
    "type_taux": 0.98,
    "taux_fixe": 0.98,
    "reference_taux": 0.95,
    "duree_reference": 0.95,
    "marge_pb": 0.95,
    "valeur_nominale": 0.95,
    "montant": None,
    "rang": 0.95,
}
MARGIN_POINTS = 0.02
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261027

Rows = list[dict[str, Any]]


def load_extractions(path: Path) -> dict[str, Extraction]:
    extractions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        champs = {name: Value(**value) for name, value in data.pop("champs").items()}
        extraction = Extraction(**data, champs=champs)
        extractions[extraction.document_id] = extraction
    return extractions


def by_document(rows: Rows) -> dict[str, Rows]:
    grouped: dict[str, Rows] = defaultdict(list)
    for row in rows:
        grouped[row["document_id"]].append(row)
    return grouped


def counts(rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> tuple[int, int]:
    """Justes et comparés sur les champs donnés."""
    right = compared = 0
    for row in rows:
        for name in fields:
            if row[name] is not None:
                compared += 1
                right += bool(row[name])
    return right, compared


def share(right: int, compared: int) -> float | None:
    return right / compared if compared else None


def bootstrap(
    documents: list[str],
    statistic: Callable[[list[str]], float | None],
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    """Intervalle à 95 % par tirage de documents entiers, avec remise."""
    rng = random.Random(seed)  # noqa: S311 - tirage reproductible, pas de la sécurité
    values = []
    for _ in range(draws):
        drawn = [rng.choice(documents) for _ in documents]
        value = statistic(drawn)
        if value is not None:
            values.append(value)
    if not values:
        return None, None
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def verdict(estimate: float | None, low: float | None, threshold: float | None) -> str:
    if threshold is None:
        return "mesuré sans seuil"
    if estimate is None:
        return "non mesuré"
    if estimate < threshold:
        return "seuil non atteint"
    if low is not None and low < threshold:
        return "seuil atteint, marge statistique insuffisante"
    return "seuil atteint"


def field_table(rows: Rows) -> dict[str, dict[str, Any]]:
    grouped = by_document(rows)
    documents = sorted(grouped)
    table = {}
    for name in FIELDS:

        def statistic(drawn: list[str], name: str = name) -> float | None:
            return share(*counts((r for d in drawn for r in grouped[d]), [name]))

        right, compared = counts(rows, [name])
        estimate = share(right, compared)
        low, high = bootstrap(documents, statistic)
        table[name] = {
            "justes": right,
            "compares": compared,
            "exactitude": estimate,
            "intervalle_95": [low, high],
            "seuil": THRESHOLDS[name],
            "verdict": verdict(estimate, low, THRESHOLDS[name]),
        }
    return table


def global_accuracy(rows: Rows, fields: Iterable[str] = FIELDS) -> dict[str, Any]:
    names = list(fields)
    grouped = by_document(rows)

    def statistic(drawn: list[str]) -> float | None:
        return share(*counts((r for d in drawn for r in grouped[d]), names))

    right, compared = counts(rows, names)
    low, high = bootstrap(sorted(grouped), statistic)
    return {
        "justes": right,
        "compares": compared,
        "exactitude": share(right, compared),
        "intervalle_95": [low, high],
    }


def paired_difference(rules: Rows, model: Rows) -> dict[str, Any]:
    """Écart d'exactitude globale (LLM moins règles), mêmes documents tirés pour les deux."""
    rules_by_doc, model_by_doc = by_document(rules), by_document(model)
    documents = sorted(set(rules_by_doc) & set(model_by_doc))

    def difference(drawn: list[str]) -> float | None:
        a = share(*counts((r for d in drawn for r in model_by_doc[d]), FIELDS))
        b = share(*counts((r for d in drawn for r in rules_by_doc[d]), FIELDS))
        return None if a is None or b is None else a - b

    estimate = difference(documents)
    low, high = bootstrap(documents, difference)
    keep = estimate is not None and estimate >= MARGIN_POINTS and low is not None and low > 0
    return {
        "ecart": estimate,
        "intervalle_95": [low, high],
        "marge_exigee": MARGIN_POINTS,
        "llm_retenu": keep,
    }


def case_right(rows: Rows, document_id: str, field: str) -> bool | None:
    """Juste si le champ est juste pour tous les ISIN du document ; None s'il n'est pas comparé."""
    verdicts = [row[field] for row in rows if row["document_id"] == document_id]
    compared = [v for v in verdicts if v is not None]
    return all(compared) if compared else None


def regression_table(cases: Rows, rules: Rows, model: Rows) -> dict[str, dict[str, int]]:
    """Par catégorie de cas observés : cas comparés et cas justes pour chaque extracteur."""
    table: dict[str, dict[str, int]] = {}
    for case in cases:
        line = table.setdefault(case["categorie"], {"cas": 0, "regles": 0, "llm": 0})
        rule, llm = (
            case_right(rows, case["document_id"], case["champ"]) for rows in (rules, model)
        )
        if rule is None and llm is None:
            continue
        line["cas"] += 1
        line["regles"] += bool(rule)
        line["llm"] += bool(llm)
    return table


def evaluate(
    truth: Rows,
    rules: dict[str, Extraction],
    model: dict[str, Extraction],
    cases: Rows | None = None,
) -> dict[str, Any]:
    rules_rows, model_rows = score(rules, truth), score(model, truth)
    without_amount = [name for name in FIELDS if name != "montant"]
    return {
        "documents": len({row["document_id"] for row in truth}),
        "couples": len(truth),
        "regles": {
            "champs": field_table(rules_rows),
            "global": global_accuracy(rules_rows),
            "global_sans_montant": global_accuracy(rules_rows, without_amount),
        },
        "llm": {
            "champs": field_table(model_rows),
            "global": global_accuracy(model_rows),
            "global_sans_montant": global_accuracy(model_rows, without_amount),
        },
        "comparaison": paired_difference(rules_rows, model_rows),
        "cas_de_regression": regression_table(cases or [], rules_rows, model_rows),
    }


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def main() -> None:  # pragma: no cover - lit les vraies données
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=Path("data/entrepot/bond_terms.duckdb"))
    parser.add_argument("--extractions", type=Path, default=Path("data/interim/extractions"))
    # Par défaut, la v0.3 : les trois jeux connus réunis, règles v2 et prompt v3. La v0.2 se
    # rejoue avec --jeux developpement --regles regles --llm llm-gemini-3.5-flash-lite.
    parser.add_argument("--jeux", nargs="+", default=list(KNOWN_SETS), choices=KNOWN_SETS)
    parser.add_argument("--regles", default=regles.VERSION, help="préfixe des sorties des règles")
    parser.add_argument(
        "--llm",
        default=f"llm-gemini-3.5-flash-lite-{llm.PROMPT_VERSION}",
        help="préfixe des sorties du LLM",
    )
    parser.add_argument(
        "--cas", type=Path, default=Path("docs/v0.2-extraction/data/cas-de-regression.csv")
    )
    parser.add_argument("--nom", default="connus-v03", help="nom du fichier de résultats")
    parser.add_argument("--summary-dir", type=Path, default=Path("docs/v0.3-revue/data"))
    args = parser.parse_args()

    truth: Rows = []
    rules: dict[str, Extraction] = {}
    model: dict[str, Extraction] = {}
    with duckdb.connect(str(args.database), read_only=True) as connection:
        for name in args.jeux:
            truth += connection.sql(TRUTH_SQL, params=[name]).to_arrow_table().to_pylist()
            rules |= load_extractions(args.extractions / f"{args.regles}-{name}.jsonl")
            model |= load_extractions(args.extractions / f"{args.llm}-{name}.jsonl")
    with args.cas.open(encoding="utf-8", newline="") as f:
        cases = list(csv.DictReader(f))
    evaluation = evaluate(truth, rules, model, cases)
    result = _rounded({"jeux": args.jeux, "regles": args.regles, "llm": args.llm} | evaluation)
    args.summary_dir.mkdir(parents=True, exist_ok=True)
    target = args.summary_dir / f"evaluation-{args.nom}.json"
    target.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    for name in FIELDS:
        r, m = result["regles"]["champs"][name], result["llm"]["champs"][name]
        low, high = m["intervalle_95"]
        interval = f"[{low:.1%} ; {high:.1%}]"
        print(f"{name:16} règles {r['exactitude']:.1%}  llm {m['exactitude']:.1%} {interval}")
        print(f"{'':16} {m['verdict']}")
    for label in ("global", "global_sans_montant"):
        r, m = result["regles"][label], result["llm"][label]
        print(label, "règles", r["exactitude"], "llm", m["exactitude"], m["intervalle_95"])
    print("comparaison", result["comparaison"])


if __name__ == "__main__":
    main()
