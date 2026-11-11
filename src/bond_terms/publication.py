"""Téléchargement du dernier instantané publié en release (ADR 0004).

L'API déployée n'a pas de disque conservé : à chaque démarrage, elle va chercher l'instantané de
la release `instantane-...` la plus récente du dépôt public. Aucun jeton n'est nécessaire.

Le fichier vient d'internet : seuls les domaines de GitHub sont acceptés, redirections comprises,
sa taille est plafonnée, et l'API le valide ensuite champ par champ avant de le servir.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

PREFIX = "instantane-"
ASSET = "instantane.json"
MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_S = 60.0
ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+")

Opener = Callable[[urllib.request.Request], Any]


class PublicationError(RuntimeError):
    """Aucun instantané utilisable n'a été trouvé ou téléchargé."""


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


def latest_asset(releases: list[dict[str, Any]]) -> str:
    """Adresse de l'instantané de la release `instantane-...` la plus récente."""
    candidates = [
        r for r in releases if r.get("tag_name", "").startswith(PREFIX) and not r.get("draft")
    ]
    # created_at est la date du commit visé, pas celle de la release : deux releases posées sur
    # le même commit seraient à égalité. Seule published_at les départage.
    for release in sorted(candidates, key=lambda r: r["published_at"], reverse=True):
        for asset in release.get("assets", []):
            if asset.get("name") == ASSET:
                url: str = asset["url"]
                return url
    raise PublicationError("aucune release instantane-... ne porte d'instantané")


def fetch(repository: str, destination: Path, opener: Opener = _open) -> Path:
    """Télécharge le dernier instantané publié dans `destination`."""
    if not _REPOSITORY.fullmatch(repository):
        raise PublicationError(f"nom de dépôt invalide : {repository!r}")
    listing = f"https://api.github.com/repos/{repository}/releases?per_page=100"
    check_url(listing)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "bond-terms"}
    with opener(urllib.request.Request(listing, headers=headers)) as response:
        url = latest_asset(json.load(response))
    check_url(url)
    # L'adresse de l'API rend le fichier lui-même avec cet en-tête (après une redirection).
    headers = {"Accept": "application/octet-stream", "User-Agent": "bond-terms"}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - check_url ci-dessus
    with opener(request) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise PublicationError(f"instantané de plus de {MAX_BYTES} octets : refusé")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination
