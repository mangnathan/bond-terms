import hashlib
import io
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from bond_terms.esma import USER_AGENT, PoliteClient, SourceError


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeOpener:
    """Renvoie des réponses préparées et garde la trace des requêtes."""

    def __init__(self, *responses: bytes | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)


def client(opener: FakeOpener, clock: FakeClock) -> PoliteClient:
    return PoliteClient(opener=opener, clock=clock, sleep=clock.sleep)


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://registers.esma.europa.eu", code, "", {}, None)  # type: ignore[arg-type]


URL = "https://registers.esma.europa.eu/solr/x/select"


def test_get_json_identifies_itself() -> None:
    clock = FakeClock()
    opener = FakeOpener(b'{"ok": 1}')
    assert client(opener, clock).get_json(URL, [("q", "*")]) == {"ok": 1}
    assert opener.requests[0].get_header("User-agent") == USER_AGENT
    assert opener.requests[0].full_url == URL + "?q=%2A"


def test_requests_are_spaced_by_one_second() -> None:
    clock = FakeClock()
    polite = client(FakeOpener(b"{}", b"{}", b"{}"), clock)
    polite.get_json(URL, [])
    clock.now += 0.3
    polite.get_json(URL, [])
    polite.get_json(URL, [])
    assert clock.sleeps == pytest.approx([0.7, 1.0])


@pytest.mark.parametrize(
    "url",
    [
        "http://registers.esma.europa.eu/solr",
        "https://example.com/solr",
        "https://registers.esma.europa.eu.example.com/",
        "file:///etc/passwd",
    ],
)
def test_unexpected_addresses_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="refusée"):
        PoliteClient.check_url(url)


def test_server_errors_are_retried_then_succeed() -> None:
    clock = FakeClock()
    opener = FakeOpener(http_error(504), urllib.error.URLError("réseau"), b'{"ok": 1}')
    assert client(opener, clock).get_json(URL, []) == {"ok": 1}
    assert len(opener.requests) == 3


def test_client_errors_are_not_retried() -> None:
    clock = FakeClock()
    opener = FakeOpener(http_error(404), b"{}")
    with pytest.raises(SourceError, match="404"):
        client(opener, clock).get_json(URL, [])
    assert len(opener.requests) == 1


def test_retries_are_limited() -> None:
    clock = FakeClock()
    opener = FakeOpener(*[http_error(503)] * 4)
    with pytest.raises(SourceError, match="503"):
        client(opener, clock).get_json(URL, [])
    assert len(opener.requests) == 4


def test_download_is_complete_and_done_once(tmp_path: Path) -> None:
    clock = FakeClock()
    content = b"x" * 3_000_000
    opener = FakeOpener(content)
    destination = tmp_path / "firds" / "FULINS_D_test.zip"
    polite = client(opener, clock)
    first = polite.download("https://firds.esma.europa.eu/firds/FULINS_D_test.zip", destination)
    second = polite.download("https://firds.esma.europa.eu/firds/FULINS_D_test.zip", destination)
    assert first == second
    assert first.size_bytes == len(content)
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert len(opener.requests) == 1
    assert not list(tmp_path.rglob("*.part"))


def test_interrupted_download_leaves_no_file(tmp_path: Path) -> None:
    class Broken(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            raise ConnectionResetError("coupure")

    clock = FakeClock()
    polite = PoliteClient(opener=lambda request, timeout: Broken(), clock=clock, sleep=clock.sleep)
    destination = tmp_path / "FULINS_D_test.zip"
    with pytest.raises(ConnectionResetError):
        polite.download("https://firds.esma.europa.eu/firds/FULINS_D_test.zip", destination)
    assert not destination.exists()
