"""Téléchargement de l'instantané en service (ADR 0004).

L'API déployée n'a pas de disque conservé : à chaque démarrage, elle télécharge l'instantané de
la release `en-service`, que la collecte hebdomadaire met à jour. C'est un simple téléchargement
de fichier depuis github.com, sans jeton : l'API de GitHub n'est pas appelée. Sans jeton, elle
n'accepte que 60 appels par heure et par adresse IP, et les serveurs de Render partagent leurs
adresses : un déploiement a échoué sur ce refus (403, rate limit exceeded).

Le fichier vient d'internet : seuls les domaines de GitHub sont acceptés, redirections comprises,
sa taille est plafonnée, et l'API le valide ensuite champ par champ avant de le servir.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

SERVING_TAG = "en-service"
ASSET = "instantane.json"
MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_S = 60.0
ATTEMPTS = 3
RETRY_DELAY_S = 5.0
ALLOWED_HOSTS = frozenset(
    {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
)
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+")

Opener = Callable[[urllib.request.Request], Any]


class PublicationError(RuntimeError):
    """L'instantané en service n'a pas pu être téléchargé."""


def check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise PublicationError(f"adresse refusée : {url}")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Une redirection vers un domaine hors de GitHub est refusée."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request: urllib.request.Request) -> Any:
    # Adresse contrôlée avant l'appel, et à chaque redirection par _CheckedRedirects.
    return urllib.request.build_opener(_CheckedRedirects).open(request, timeout=TIMEOUT_S)


def serving_url(repository: str) -> str:
    if not _REPOSITORY.fullmatch(repository):
        raise PublicationError(f"nom de dépôt invalide : {repository!r}")
    return f"https://github.com/{repository}/releases/download/{SERVING_TAG}/{ASSET}"


def fetch(
    repository: str,
    destination: Path,
    opener: Opener = _open,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Télécharge l'instantané en service dans `destination`. Une erreur passagère du réseau ou
    de GitHub est retentée ; un fichier trop gros est refusé sans nouvelle tentative."""
    url = serving_url(repository)
    check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "bond-terms"})  # noqa: S310
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with opener(request) as response:
                data = response.read(MAX_BYTES + 1)
            break
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == ATTEMPTS:
                raise PublicationError(f"téléchargement impossible : {error}") from error
            sleep(RETRY_DELAY_S * attempt)
    if len(data) > MAX_BYTES:
        raise PublicationError(f"instantané de plus de {MAX_BYTES} octets : refusé")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination
