"""Extracteur LLM : Gemini en offre gratuite, sous plafonds stricts (ADR 0002).

Le prompt est versionné dans `prompts/`. Chaque réponse est gardée en cache, indexée par le
modèle, le prompt et le texte envoyé : un document n'est jamais envoyé deux fois à l'identique.
Un plafond local de requêtes par jour, fixé sous le plafond gratuit, est décompté avant chaque
appel. Au premier refus pour quota, ou quand le plafond local est atteint, l'extracteur s'arrête
et le lanceur bascule sur les règles. Le modèle est injectable : la CI utilise un faux modèle.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from bond_terms.extraction import FIELDS, PERPETUAL, Extraction, Value, verify

PROMPT_VERSION = "extraction-v2"
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt").read_text(
    encoding="utf-8"
)


@dataclass(frozen=True)
class Limits:
    """Plafonds locaux d'un modèle, fixés sous l'offre gratuite."""

    per_day: int
    min_interval_s: float


# Offre gratuite relevée dans AI Studio le 26 octobre 2026 (250 000 jetons par minute pour les
# deux) : gemini-3.8-flash 5 requêtes par minute et 20 par jour ; gemini-3.5-flash-lite 15 par
# minute et 500 par jour. Les plafonds locaux restent en dessous ; `.env` peut les baisser,
# jamais les relever.
LIMITS = {
    "gemini-3.8-flash": Limits(per_day=18, min_interval_s=13.0),
    "gemini-3.5-flash-lite": Limits(per_day=450, min_interval_s=5.0),
}
MODELS = tuple(LIMITS)
# Google remet les compteurs à zéro à minuit, heure du Pacifique : la journée du plafond local
# suit l'heure de Los Angeles en hiver (UTC-8). En été, l'heure d'écart est couverte par l'arrêt
# au premier refus.
QUOTA_DAY_OFFSET = dt.timedelta(hours=-8)


def quota_day(now: dt.datetime | None = None) -> dt.date:
    moment = now or dt.datetime.now(dt.UTC)
    return (moment + QUOTA_DAY_OFFSET).date()


# L'échéance figure toujours dans les 27 000 premiers caractères sur le développement.
MAX_CHARS = 40_000

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        name: {
            "type": "object",
            "properties": {
                "valeur": {"type": ["string", "null"]},
                "citation": {"type": ["string", "null"]},
            },
            "required": ["valeur", "citation"],
        }
        for name in FIELDS
    },
    "required": list(FIELDS),
}

_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")
FORMATS = {
    "devise": re.compile(r"[A-Z]{3}"),
    "date_echeance": re.compile(rf"\d{{4}}-\d{{2}}-\d{{2}}|{PERPETUAL}"),
    "type_taux": re.compile(r"fixed|floating"),
    "taux_fixe": _NUMBER,
    "reference_taux": re.compile(r"[A-Z]{3,8}"),
    "duree_reference": re.compile(r"\d{1,2}[DWMY]"),
    "marge_pb": _NUMBER,
    "valeur_nominale": _NUMBER,
    "montant": _NUMBER,
    "rang": re.compile(r"senior|senior_non_prefere|subordonne|subordonne_profond"),
}


class QuotaError(RuntimeError):
    """Refus pour quota, ou plafond local atteint : plus aucun appel ce jour-là."""


class UnavailableError(RuntimeError):
    """Surcharge passagère du service (erreur 5xx) : le document passe par les règles."""


UNAVAILABLE_ATTEMPTS = 3
UNAVAILABLE_WAIT_S = 30.0


@dataclass
class Reply:
    text: str
    tokens_in: int | None
    tokens_out: int | None
    seconds: float


class Model(Protocol):
    name: str

    def generate(self, system: str, user: str) -> Reply: ...


class Budget:
    """Plafond local de requêtes par jour et par modèle, décompté avant l'appel."""

    def __init__(self, directory: Path, model: str, per_day: int, today: dt.date | None = None):
        self.path = directory / f"{(today or quota_day()).isoformat()}-{model}.json"
        self.per_day = per_day

    def used(self) -> int:
        if not self.path.exists():
            return 0
        count: int = json.loads(self.path.read_text(encoding="utf-8"))["requetes"]
        return count

    def take(self) -> None:
        used = self.used()
        if used >= self.per_day:
            raise QuotaError(f"plafond local atteint : {used} requêtes sur {self.per_day}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"requetes": used + 1}), encoding="utf-8")


def document_text(pages: list[str]) -> str:
    """Pages numérotées, tronquées à MAX_CHARS caractères."""
    text = "\n".join(f"[page {number}]\n{page}" for number, page in enumerate(pages, start=1))
    return text[:MAX_CHARS]


def user_message(isins: list[str], pages: list[str]) -> str:
    return f"ISIN: {', '.join(isins)}\n\nDocument:\n{document_text(pages)}"


def cache_key(model: str, user: str) -> str:
    material = "\n".join([model, PROMPT_VERSION, SYSTEM_PROMPT, user])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def clean(name: str, raw: Any) -> str | None:
    """Valeur au format attendu, ou None : la réponse du modèle est une entrée non fiable."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if name in ("taux_fixe", "marge_pb", "valeur_nominale", "montant"):
        value = value.replace(",", "").replace(" ", "").replace("+", "")
    if name in ("devise", "reference_taux", "duree_reference"):
        value = value.upper()
    if not FORMATS[name].fullmatch(value):
        return None
    if name in ("taux_fixe", "marge_pb", "valeur_nominale", "montant"):
        number = float(value)
        value = str(int(number)) if number == int(number) else repr(number)
    return value


def parse(text: str) -> tuple[dict[str, Value], str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {name: Value() for name in FIELDS}, "réponse illisible"
    if not isinstance(data, dict):
        return {name: Value() for name in FIELDS}, "réponse illisible"
    champs: dict[str, Value] = {}
    rejected = []
    for name in FIELDS:
        item = data.get(name)
        item = item if isinstance(item, dict) else {}
        value = clean(name, item.get("valeur"))
        citation = item.get("citation") if isinstance(item.get("citation"), str) else None
        if item.get("valeur") is not None and value is None:
            rejected.append(name)
        champs[name] = Value(value, citation if value is not None else None)
    remark = f"format refusé : {', '.join(rejected)}" if rejected else ""
    return champs, remark


class Extractor:
    def __init__(
        self,
        model: Model,
        cache_dir: Path,
        budget: Budget,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.model = model
        self.cache_dir = cache_dir / model.name / PROMPT_VERSION
        self.budget = budget
        self.sleep = sleep
        self.calls = 0
        self.cache_hits = 0

    def generate(self, user: str) -> Reply:
        """Appel au modèle ; une surcharge passagère est retentée deux fois, 30 s plus tard,
        chaque essai étant décompté du plafond. Un refus pour quota n'est jamais retenté."""
        for attempt in range(UNAVAILABLE_ATTEMPTS):
            self.budget.take()
            try:
                return self.model.generate(SYSTEM_PROMPT, user)
            except UnavailableError:
                if attempt == UNAVAILABLE_ATTEMPTS - 1:
                    raise
                self.sleep(UNAVAILABLE_WAIT_S)
        raise UnavailableError("aucun essai")  # inaccessible : la boucle renvoie ou lève

    def reply(self, document_id: str, user: str) -> Reply:
        key = cache_key(self.model.name, user)
        cached = self.cache_dir / f"{document_id}.json"
        if cached.exists():
            data = json.loads(cached.read_text(encoding="utf-8"))
            if data["cle"] == key:
                self.cache_hits += 1
                return Reply(
                    data["reponse"], data["jetons_entree"], data["jetons_sortie"], data["secondes"]
                )
        reply = self.generate(user)
        self.calls += 1
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "cle": key,
            "reponse": reply.text,
            "jetons_entree": reply.tokens_in,
            "jetons_sortie": reply.tokens_out,
            "secondes": reply.seconds,
        }
        cached.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return reply

    def extract(self, document_id: str, pages: list[str], isins: list[str]) -> Extraction:
        reply = self.reply(document_id, user_message(isins, pages))
        champs, remark = parse(reply.text)
        extraction = Extraction(
            document_id, "llm", f"{self.model.name}/{PROMPT_VERSION}", champs, remarque=remark
        )
        extraction.secondes = reply.seconds
        extraction.jetons_entree = reply.tokens_in
        extraction.jetons_sortie = reply.tokens_out
        return verify(extraction, pages)


class GeminiModel:  # pragma: no cover - appelle l'API Gemini
    """Appel réel : température 0, sortie JSON contrainte, aucune nouvelle tentative."""

    def __init__(self, name: str, api_key: str, min_interval_s: float):
        from google import genai
        from google.genai import types

        self.name = name
        self.types = types
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self.min_interval_s = min_interval_s
        self.last_call = 0.0

    def generate(self, system: str, user: str) -> Reply:
        from google.genai import errors

        wait = self.min_interval_s - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        config = self.types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=SCHEMA,
            thinking_config=self.types.ThinkingConfig(
                thinking_level=self.types.ThinkingLevel.MINIMAL
            ),
        )
        start = time.perf_counter()
        self.last_call = time.monotonic()
        try:
            response = self.client.models.generate_content(
                model=self.name, contents=user, config=config
            )
        except errors.APIError as error:
            if error.code == 429 or error.status == "RESOURCE_EXHAUSTED":
                raise QuotaError(f"refus de l'API pour quota : {error.status}") from error
            if error.code is not None and error.code >= 500:
                raise UnavailableError(
                    f"service indisponible : {error.code} {error.status}"
                ) from error
            raise
        seconds = round(time.perf_counter() - start, 3)
        usage = response.usage_metadata
        tokens_in = usage.prompt_token_count if usage else None
        tokens_out = usage.candidates_token_count if usage else None
        return Reply(response.text or "", tokens_in, tokens_out, seconds)
