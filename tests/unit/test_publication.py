import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from bond_terms import publication
from bond_terms.publication import PublicationError, check_url, fetch, latest_asset

API = "https://api.github.com/repos/o/r/releases/assets"


def release(tag: str, published: str, asset: str = "instantane.json", draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        # Date du commit visé : identique pour toutes, comme pour deux releases du même jour.
        "created_at": "2026-11-11T14:10:55Z",
        "published_at": published,
        "draft": draft,
        "assets": [{"name": asset, "url": f"{API}/{tag}"}],
    }


def test_the_most_recent_snapshot_release_is_chosen() -> None:
    releases = [
        release("instantane-2026-11-11-graine", "2026-11-11T14:00:00Z"),
        release("instantane-2026-11-16-2", "2026-11-16T06:30:00Z"),
        release("v0.4", "2026-11-20T00:00:00Z"),
        release("instantane-2026-11-23-3", "2026-11-23T06:30:00Z", draft=True),
        release("instantane-2026-11-24-4", "2026-11-24T06:30:00Z", asset="bilan.json"),
    ]
    assert latest_asset(releases) == f"{API}/instantane-2026-11-16-2"


def test_no_snapshot_release_is_an_error() -> None:
    with pytest.raises(PublicationError):
        latest_asset([release("v0.4", "2026-11-20T00:00:00Z")])


@pytest.mark.parametrize(
    "url",
    ["http://api.github.com/x", "https://evil.example/instantane.json", "file:///etc/passwd"],
)
def test_only_github_over_https_is_accepted(url: str) -> None:
    with pytest.raises(PublicationError):
        check_url(url)


def test_a_redirect_outside_github_is_refused() -> None:
    handler = publication._CheckedRedirects()
    request = urllib.request.Request("https://api.github.com/x")
    with pytest.raises(PublicationError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/x")


class FakeOpener:
    def __init__(self, releases: list[dict[str, Any]], data: bytes) -> None:
        self.answers = [json.dumps(releases).encode(), data]
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request) -> io.BytesIO:
        self.urls.append(request.full_url)
        return io.BytesIO(self.answers.pop(0))


def test_the_snapshot_is_written_where_asked(tmp_path: Path) -> None:
    opener = FakeOpener([release("instantane-1", "2026-11-11T00:00:00Z")], b'{"format":2}')
    target = fetch("mangnathan/bond-terms", tmp_path / "i" / "instantane.json", opener)
    assert target.read_bytes() == b'{"format":2}'
    assert (
        opener.urls[0] == "https://api.github.com/repos/mangnathan/bond-terms/releases?per_page=100"
    )


def test_an_oversized_snapshot_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publication, "MAX_BYTES", 10)
    opener = FakeOpener([release("instantane-1", "2026-11-11T00:00:00Z")], b"x" * 11)
    with pytest.raises(PublicationError):
        fetch("mangnathan/bond-terms", tmp_path / "instantane.json", opener)
    assert not (tmp_path / "instantane.json").exists()


@pytest.mark.parametrize("repository", ["../etc", "a/b/c", "a b/c", ""])
def test_a_malformed_repository_name_is_refused(repository: str, tmp_path: Path) -> None:
    with pytest.raises(PublicationError):
        fetch(repository, tmp_path / "instantane.json", FakeOpener([], b""))
