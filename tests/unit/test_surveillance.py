from typing import Any

from bond_terms.surveillance import MIN_DOCUMENTS, check, issue_body, percent, window

ACCEPTED = {"valeur": "EUR", "citation": "c", "page": 1, "statut": "acceptee"}
REFUSED = {"valeur": "EUR", "citation": "c", "page": 1, "statut": "refusee"}


def entry(document_id: str, day: str, review: bool = False, gap: bool = False) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "jeu": f"collecte-{day}",
        "champs": {"devise": ACCEPTED, "rang": REFUSED if review else ACCEPTED},
        "en_revue": review,
        "raisons_revue": [],
        "exceptions": [{"champ": "montant"}] if gap else [],
    }


def snapshot(entries: list[dict[str, Any]], quota: bool = False) -> dict[str, Any]:
    bonds: dict[str, list[dict[str, Any]]] = {}
    for n, e in enumerate(entries):
        bonds.setdefault(f"FR{n:010d}", []).append(e)
    # Les documents évalués avant la mise en service ne comptent pas dans la surveillance.
    bonds["FR9999999999"] = [{**entry("old", "x"), "jeu": "test_v04", "en_revue": True}]
    collecte = {"date": "2026-11-16", "arret_quota": quota, "documents_en_repli": 2}
    return {"obligations": bonds, "collectes": [collecte]}


def test_the_window_goes_back_until_enough_documents() -> None:
    entries = [entry(f"a{n}", "2026-11-16") for n in range(3)]
    entries += [entry(f"b{n}", "2026-11-09") for n in range(MIN_DOCUMENTS)]
    entries += [entry(f"c{n}", "2026-11-02") for n in range(5)]
    days, found = window(snapshot(entries))
    assert days == ["2026-11-16", "2026-11-09"]
    assert len(found) == 3 + MIN_DOCUMENTS


def test_a_small_window_shows_its_shares_without_alerting() -> None:
    result = check(snapshot([entry("1", "2026-11-16", gap=True) for _ in range(3)]))
    assert not result["jugee"]
    assert result["parts"]["part_documents_avec_exception"] == 1.0
    assert result["alertes"] == []


def test_a_threshold_crossed_on_a_full_window_alerts() -> None:
    entries = [entry(str(n), "2026-11-16", gap=n < 10) for n in range(MIN_DOCUMENTS)]
    result = check(snapshot(entries))
    assert result["jugee"]
    assert result["parts"]["part_documents_avec_exception"] == 0.5
    assert result["alertes"] == [
        "Documents avec exception : 50,0 % sur les 20 derniers documents, "
        "au-dessus du seuil de 40,0 %."
    ]


def test_shares_under_their_thresholds_do_not_alert() -> None:
    entries = [entry(str(n), "2026-11-16", review=n < 2) for n in range(MIN_DOCUMENTS)]
    assert check(snapshot(entries))["alertes"] == []


def test_a_quota_stop_alerts_at_once() -> None:
    result = check(snapshot([entry("1", "2026-11-16")], quota=True))
    assert result["alertes"] == [
        "Arrêt pour quota lors de la collecte du 2026-11-16 : "
        "2 documents lus par les règles au lieu du LLM."
    ]
    body = issue_body(result)
    assert (
        "- Arrêt pour quota" in body and "Fenêtre : collectes du 2026-11-16, 1 documents." in body
    )


def test_percent_is_written_the_french_way() -> None:
    assert percent(0.305) == "30,5 %"
