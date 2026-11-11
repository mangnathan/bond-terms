import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bond_terms import publication
from bond_terms.publication import PublicationError, check_url, fetch, serving_url


def test_the_snapshot_has_a_fixed_address_outside_the_github_api() -> None:
    assert serving_url("mangnathan/bond-terms") == (
        "https://github.com/mangnathan/bond-terms/releases/download/en-service/instantane.json"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x",
        "https://evil.example/instantane.json",
        "file:///etc/passwd",
        # L'API de GitHub n'est plus appelée : elle limite les appels sans jeton.
        "https://api.github.com/repos/o/r/releases",
    ],
)
def test_only_github_downloads_over_https_are_accepted(url: str) -> None:
    with pytest.raises(PublicationError):
        check_url(url)


def test_a_redirect_outside_github_is_refused() -> None:
    handler = publication._CheckedRedirects()
    request = urllib.request.Request("https://github.com/x")
    with pytest.raises(PublicationError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/x")


class FakeOpener:
    """Échoue `failures` fois, puis rend `data`."""

    def __init__(self, data: bytes, failures: int = 0) -> None:
        self.data = data
        self.failures = failures
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request) -> io.BytesIO:
        self.urls.append(request.full_url)
        if self.failures:
            self.failures -= 1
            raise urllib.error.URLError("réseau indisponible")
        return io.BytesIO(self.data)


def test_the_snapshot_is_written_where_asked(tmp_path: Path) -> None:
    opener = FakeOpener(b'{"format":2}')
    target = fetch("mangnathan/bond-terms", tmp_path / "i" / "instantane.json", opener)
    assert target.read_bytes() == b'{"format":2}'
    assert opener.urls == [serving_url("mangnathan/bond-terms")]


def test_a_passing_failure_is_retried(tmp_path: Path) -> None:
    waits: list[float] = []
    opener = FakeOpener(b"{}", failures=2)
    fetch("mangnathan/bond-terms", tmp_path / "instantane.json", opener, waits.append)
    assert len(opener.urls) == 3
    assert waits == [5.0, 10.0]


def test_a_lasting_failure_stops_the_start(tmp_path: Path) -> None:
    opener = FakeOpener(b"{}", failures=3)
    with pytest.raises(PublicationError):
        fetch("mangnathan/bond-terms", tmp_path / "instantane.json", opener, lambda _: None)
    assert not (tmp_path / "instantane.json").exists()


def test_an_oversized_snapshot_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publication, "MAX_BYTES", 10)
    with pytest.raises(PublicationError):
        fetch("mangnathan/bond-terms", tmp_path / "instantane.json", FakeOpener(b"x" * 11))
    assert not (tmp_path / "instantane.json").exists()


@pytest.mark.parametrize("repository", ["../etc", "a/b/c", "a b/c", ""])
def test_a_malformed_repository_name_is_refused(repository: str, tmp_path: Path) -> None:
    with pytest.raises(PublicationError):
        fetch(repository, tmp_path / "instantane.json", FakeOpener(b""))
