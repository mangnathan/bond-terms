"""API en lecture seule des conditions extraites (ADR 0004).

Usage :
    uv run uvicorn bond_terms.api:app

Les routes sont versionnées (/v1/...) : un changement incompatible ouvrira /v2 sans casser les
clients existants.

L'API charge l'instantané au démarrage (chemin dans BOND_TERMS_INSTANTANE) et ne fait ensuite que
le lire : elle n'appelle jamais le modèle, si bien qu'aucune requête extérieure ne peut consommer
le quota gratuit. L'ISIN est vérifié (format et clé de contrôle) avant toute recherche, et le
nombre d'appels par client est limité.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

API_VERSION = "0.4"
DEFAULT_SNAPSHOT = Path("data/instantane/instantane.json")
# Appels par client et par minute : large pour un humain ou un script raisonnable.
MAX_CALLS = 60
WINDOW_S = 60.0
# Plafond tous clients confondus : il borne l'usage même si un client fausse son adresse.
MAX_TOTAL_CALLS = 600

# uvicorn ne configure que ses propres journaux : celui de l'API reçoit sa sortie console.
log = logging.getLogger("bond_terms.api")
if not log.handlers:
    _console = logging.StreamHandler()
    _console.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    log.addHandler(_console)
    log.setLevel(logging.INFO)

_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def is_valid_isin(isin: str) -> bool:
    """Format ISO 6166 et clé de contrôle (Luhn sur les lettres converties en nombres)."""
    if not _ISIN.fullmatch(isin):
        return False
    digits = "".join(str(int(char, 36)) for char in isin[:-1])
    total = 0
    # De droite à gauche, en partant du chiffre voisin de la clé : un chiffre sur deux est doublé.
    for position, char in enumerate(reversed(digits)):
        number = int(char) * (2 if position % 2 == 0 else 1)
        total += number // 10 + number % 10
    return (10 - total % 10) % 10 == int(isin[-1])


# L'instantané vient d'un fichier téléchargé : il est validé champ par champ au chargement.
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Champ(_Strict):
    valeur: str | None
    citation: str | None
    page: int | None
    statut: Literal["acceptee", "refusee", "absente"]


class Ecart(_Strict):
    champ: str
    valeur_firds: str | None
    valeur_lue: str


class Document(_Strict):
    document_id: str
    jeu: str
    champs: dict[str, Champ]
    en_revue: bool
    raisons_revue: list[str]
    exceptions: list[Ecart]


class Indicateurs(_Strict):
    documents: int
    part_en_revue: float | None
    part_valeurs_refusees: float | None
    part_documents_avec_exception: float | None
    documents_en_repli: int


class Collecte(_Strict):
    """Bilan d'une collecte hebdomadaire (`bond_terms.collecte`)."""

    date: str
    firds: str
    obligations_suivies: int
    documents_registre: int
    nouveaux_documents: int
    documents_lus: int
    erreurs_lecture: int
    rattachements_errones: int
    produits_structures: int
    documents_extraits: int
    documents_en_repli: int
    arret_quota: bool


class Instantane(_Strict):
    format: Literal[2]
    cree_le: str
    commit: str
    extracteurs: dict[str, str]
    obligations: dict[str, list[Document]]
    indicateurs: dict[str, Indicateurs]
    # Mémoire de la collecte : documents déjà examinés, écartés compris, et bilans.
    documents_vus: list[str]
    collectes: list[Collecte]


class Obligation(_Strict):
    isin: str
    instantane: str
    documents: list[Document]


class Sante(_Strict):
    statut: Literal["ok"]
    version_api: str
    instantane: str
    commit: str
    extracteurs: dict[str, str]
    obligations: int
    # Une collecte arrêtée (workflow désactivé, panne) se voit ici : la date ne bouge plus.
    derniere_collecte: str | None


class RateLimiter:
    """Fenêtre fixe par client : au plus `max_calls` appels par fenêtre de `window_s` secondes."""

    def __init__(
        self, max_calls: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self.clock = clock
        self._calls: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> int:
        """0 si l'appel est permis, sinon les secondes à attendre."""
        now = self.clock()
        with self._lock:
            # Les fenêtres expirées sont oubliées : la mémoire ne grandit pas avec les clients.
            if len(self._calls) > 10_000:
                self._calls = {k: v for k, v in self._calls.items() if now - v[0] < self.window_s}
            start, count = self._calls.get(client, (now, 0))
            if now - start >= self.window_s:
                start, count = now, 0
            if count >= self.max_calls:
                return max(1, int(self.window_s - (now - start)) + 1)
            self._calls[client] = (start, count + 1)
            return 0


def load_snapshot(path: Path) -> Instantane:
    return Instantane.model_validate_json(path.read_bytes())


def create_app(
    snapshot_path: Path | None = None,
    limiter: RateLimiter | None = None,
    total_limiter: RateLimiter | None = None,
    client_header: str | None = None,
) -> FastAPI:
    limiter = limiter or RateLimiter(MAX_CALLS, WINDOW_S)
    total_limiter = total_limiter or RateLimiter(MAX_TOTAL_CALLS, WINDOW_S)
    # Derrière un proxy, l'adresse vue par l'API est celle du proxy : l'en-tête qui porte la
    # vraie adresse du client se configure ici (True-Client-IP sur Render). X-Forwarded-For
    # n'est pas utilisé : le proxy de Render le complète au lieu de le remplacer, un client
    # pourrait y écrire une fausse adresse.
    header = client_header or os.environ.get("BOND_TERMS_EN_TETE_CLIENT") or None
    state: dict[str, Instantane] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Sans instantané valide, le service refuse de démarrer plutôt que de servir du vide.
        # Une variable vide (ligne laissée vide dans .env) vaut le chemin par défaut.
        path = snapshot_path or Path(os.environ.get("BOND_TERMS_INSTANTANE") or DEFAULT_SNAPSHOT)
        # Déployée, l'API n'a pas de disque conservé : elle prend le dernier instantané publié.
        repository = os.environ.get("BOND_TERMS_DEPOT")
        if repository and snapshot_path is None:
            from bond_terms.publication import fetch

            fetch(repository, path)
        state["instantane"] = load_snapshot(path)
        log.info("instantané du %s chargé", state["instantane"].cree_le)
        yield

    app = FastAPI(
        title="bond-terms",
        summary="Conditions d'émission d'obligations lues dans les prospectus, avec citations.",
        version=API_VERSION,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def limit_calls(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        client = request.client.host if request.client else "inconnu"
        if header and (forwarded := request.headers.get(header, "").strip()):
            client = forwarded
        wait = limiter.retry_after(client) or total_limiter.retry_after("tous")
        if wait:
            response: Response = JSONResponse(
                {"detail": "trop d'appels, réessayer plus tard"},
                status_code=429,
                headers={"Retry-After": str(wait)},
            )
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Journal d'une ligne par appel, pour la surveillance. L'adresse du client n'y figure
        # pas : c'est une donnée personnelle, inutile pour suivre le service.
        log.info(
            "%s %s %d %.1f ms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    v1 = APIRouter(prefix="/v1")

    @v1.get("/sante")
    def sante() -> Sante:
        snapshot = state["instantane"]
        return Sante(
            statut="ok",
            version_api=API_VERSION,
            instantane=snapshot.cree_le,
            commit=snapshot.commit,
            extracteurs=snapshot.extracteurs,
            obligations=len(snapshot.obligations),
            derniere_collecte=snapshot.collectes[-1].date if snapshot.collectes else None,
        )

    @v1.get("/obligations/{isin}")
    def obligation(isin: str) -> Obligation:
        isin = isin.strip().upper()
        if not is_valid_isin(isin):
            raise HTTPException(422, "ISIN invalide : 12 caractères et une clé de contrôle juste")
        snapshot = state["instantane"]
        documents = snapshot.obligations.get(isin)
        if documents is None:
            raise HTTPException(404, "ISIN absent de l'instantané")
        return Obligation(isin=isin, instantane=snapshot.cree_le, documents=documents)

    @v1.get("/indicateurs")
    def indicateurs() -> dict[str, Indicateurs]:
        return state["instantane"].indicateurs

    app.include_router(v1)
    return app


app = create_app()
