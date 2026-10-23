"""Accès prudent aux services publics de l'ESMA et de GLEIF.

Les registres de l'ESMA ne publient pas de limite de débit : le client s'identifie, espace ses
requêtes d'au moins une seconde, reprend quelques fois après une erreur du serveur et refuse
toute adresse hors des domaines prévus.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_AGENT = "bond-terms (projet personnel ; github.com/mangnathan)"
ALLOWED_HOSTS = frozenset({"registers.esma.europa.eu", "firds.esma.europa.eu", "api.gleif.org"})
CHUNK_BYTES = 1 << 20

Opener = Callable[[urllib.request.Request, float], Any]


def _urlopen(request: urllib.request.Request, timeout: float) -> Any:
    # L'adresse a été contrôlée par PoliteClient.check_url : https et domaine autorisé.
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


class SourceError(RuntimeError):
    """Le service public n'a pas répondu correctement après les reprises prévues."""


@dataclass(frozen=True)
class DownloadedFile:
    path: Path
    size_bytes: int
    sha256: str


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


class PoliteClient:
    def __init__(
        self,
        min_interval_s: float = 1.0,
        retries: int = 3,
        timeout_s: float = 120.0,
        opener: Opener = _urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.retries = retries
        self.timeout_s = timeout_s
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    @staticmethod
    def check_url(url: str) -> None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"Adresse refusée : {url}")

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            remaining = self.min_interval_s - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def _open(self, url: str) -> Any:
        """Ouvre l'adresse ; reprend après une panne du serveur ou du réseau, pas après un refus."""
        self.check_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
        for attempt in range(self.retries + 1):
            self._wait_turn()
            try:
                return self._opener(request, self.timeout_s)
            except urllib.error.HTTPError as error:
                if error.code < 500 or attempt == self.retries:
                    raise SourceError(f"{url} : HTTP {error.code}") from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == self.retries:
                    raise SourceError(f"{url} : {error}") from error
            self._sleep(5.0 * 2**attempt)
        raise AssertionError("inaccessible")

    def get_json(self, url: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        with self._open(f"{url}?{urllib.parse.urlencode(params)}") as response:
            data: dict[str, Any] = json.load(response)
        return data

    def download(self, url: str, destination: Path) -> DownloadedFile:
        """Télécharge une seule fois ; le fichier n'apparaît qu'une fois complet."""
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(destination.name + ".part")
            with self._open(url) as response, partial.open("wb") as out:
                while chunk := response.read(CHUNK_BYTES):
                    out.write(chunk)
            partial.replace(destination)
        return DownloadedFile(destination, destination.stat().st_size, sha256_of(destination))
