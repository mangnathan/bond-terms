import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bond_terms.api import RateLimiter, create_app, is_valid_isin

FIELD = {"valeur": "EUR", "citation": "Specified Currency: Euro", "page": 2, "statut": "acceptee"}


def snapshot(**changes: Any) -> dict[str, Any]:
    data = {
        "format": 1,
        "cree_le": "2026-11-10T18:00:00+00:00",
        "commit": "abc123",
        "extracteurs": {"llm": "modele/prompt", "regles": "regles-2"},
        "obligations": {
            "FR0014007NG9": [
                {
                    "document_id": "14947257",
                    "jeu": "test_v04",
                    "champs": {"devise": FIELD},
                    "en_revue": False,
                    "raisons_revue": [],
                    "exceptions": [
                        {"champ": "montant", "valeur_firds": "1500000.0", "valeur_lue": "5000000"}
                    ],
                }
            ]
        },
        "indicateurs": {
            "test_v04": {
                "documents": 1,
                "part_en_revue": 0.0,
                "part_valeurs_refusees": 0.0,
                "part_documents_avec_exception": 1.0,
                "documents_en_repli": 0,
            }
        },
    }
    data.update(changes)
    return data


def client(tmp_path: Path, data: dict[str, Any], limiter: RateLimiter | None = None) -> TestClient:
    path = tmp_path / "instantane.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return TestClient(create_app(path, limiter))


@pytest.mark.parametrize("isin", ["US0378331005", "FR0014007NG9", "FR001400IIR9", "DE000BAY0017"])
def test_real_isins_are_valid(isin: str) -> None:
    assert is_valid_isin(isin)


@pytest.mark.parametrize(
    "isin", ["US0378331006", "FR0014007NG", "fr0014007ng9", "FR0014007NG9X", "' OR 1=1 --"]
)
def test_wrong_check_digit_or_format_is_refused(isin: str) -> None:
    assert not is_valid_isin(isin)


def test_a_bond_is_served_with_its_citations(tmp_path: Path) -> None:
    with client(tmp_path, snapshot()) as api:
        response = api.get("/obligations/fr0014007ng9")
    assert response.status_code == 200
    body = response.json()
    assert body["isin"] == "FR0014007NG9"
    assert body["documents"][0]["champs"]["devise"]["citation"] == "Specified Currency: Euro"
    assert body["documents"][0]["exceptions"][0]["champ"] == "montant"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_invalid_and_unknown_isins_are_told_apart(tmp_path: Path) -> None:
    with client(tmp_path, snapshot()) as api:
        assert api.get("/obligations/FR0014007NG8").status_code == 422
        assert api.get("/obligations/US0378331005").status_code == 404


def test_health_and_indicators(tmp_path: Path) -> None:
    with client(tmp_path, snapshot()) as api:
        assert api.get("/sante").json() == {
            "statut": "ok",
            "instantane": "2026-11-10T18:00:00+00:00",
            "obligations": 1,
        }
        assert api.get("/indicateurs").json()["test_v04"]["documents"] == 1


def test_the_api_only_reads(tmp_path: Path) -> None:
    with client(tmp_path, snapshot()) as api:
        assert api.post("/obligations/FR0014007NG9").status_code == 405
        assert api.delete("/obligations/FR0014007NG9").status_code == 405


def test_a_malformed_snapshot_stops_the_start(tmp_path: Path) -> None:
    broken = snapshot(obligations={"FR0014007NG9": [{"document_id": "1", "piege": True}]})
    with pytest.raises(ValueError), client(tmp_path, broken):
        pass


def test_too_many_calls_are_refused_with_a_delay(tmp_path: Path) -> None:
    now = [0.0]
    limiter = RateLimiter(max_calls=2, window_s=60, clock=lambda: now[0])
    with client(tmp_path, snapshot(), limiter) as api:
        assert api.get("/sante").status_code == 200
        assert api.get("/sante").status_code == 200
        refused = api.get("/sante")
        assert refused.status_code == 429
        assert refused.headers["Retry-After"] == "61"
        now[0] = 60.0
        assert api.get("/sante").status_code == 200


def test_each_client_has_its_own_window() -> None:
    limiter = RateLimiter(max_calls=1, window_s=60, clock=lambda: 0.0)
    assert limiter.retry_after("a") == 0
    assert limiter.retry_after("b") == 0
    assert limiter.retry_after("a") > 0
