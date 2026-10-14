import base64
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from bot.dashboard import build_dashboard_payload, start_dashboard


def test_dashboard_exposes_only_consented_business_view_without_telegram_id():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    rows = [{
        "telegram_user_id": 999999,
        "track": "etudes",
        "first_name": "Nora",
        "last_name": "Test",
        "contact_detail": "+213000000000",
        "project_summary": "Projet synthétique de master.",
        "profile_json": {"facts": {
            "desired_degree": {"value": "master", "status": "declared"},
            "desired_field": {"value": "informatique", "status": "declared"},
            "country": {"value": "supposition", "status": "hypothesis"},
        }},
        "open_questions": ["Question synthétique ?"],
        "consent_at": now - timedelta(hours=2),
        "updated_at": now - timedelta(hours=1),
        "lead_source": "canal_gratuit",
        "funnel_route": "consultation",
        "offer_status": "consultation_requested",
    }]

    payload = build_dashboard_payload(rows, {"needs_answer": 2, "faq_candidate": 3}, now=now)

    assert payload["metrics"] == {"total": 1, "last_7_days": 1, "today": 1, "open_questions": 2}
    assert payload["faq_candidates"] == 3
    assert payload["distribution"][0] == {"key": "etudes", "label": "Études", "count": 1}
    record = payload["records"][0]
    assert record["name"] == "Nora Test" and record["track_label"] == "Études"
    assert [item["value"] for item in record["facts"]] == ["master", "informatique"]
    assert "telegram_user_id" not in record
    assert "conversation" not in record
    assert record["lead_source"] == "canal_gratuit"
    assert record["funnel_route"] == "consultation"


def test_dashboard_keeps_all_four_requested_track_sections_even_when_empty():
    payload = build_dashboard_payload([], {}, now=datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert [item["key"] for item in payload["distribution"]] == [
        "etudes", "emploi", "ausbildung", "volontariat"
    ]
    assert all(item["count"] == 0 for item in payload["distribution"])


def test_hosted_dashboard_requires_authentication_but_health_stays_public():
    readiness = {"ready": False}
    server = start_dashboard(
        "postgresql://unused",
        host="127.0.0.1",
        port=0,
        username="rdw-admin",
        password="a-strong-test-password",
        health_ready=lambda: readiness["ready"],
    )
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(HTTPError) as starting:
            urlopen(base + "/health", timeout=2)
        assert starting.value.code == 503

        readiness["ready"] = True
        with urlopen(base + "/health", timeout=2) as response:
            assert response.status == 200

        with pytest.raises(HTTPError) as denied:
            urlopen(base + "/", timeout=2)
        assert denied.value.code == 401
        assert denied.value.headers["WWW-Authenticate"].startswith("Basic ")

        credentials = base64.b64encode(b"rdw-admin:a-strong-test-password").decode("ascii")
        request = Request(base + "/", headers={"Authorization": f"Basic {credentials}"})
        with urlopen(request, timeout=2) as response:
            assert response.status == 200
            assert b"<!doctype html>" in response.read().lower()
    finally:
        server.shutdown()
        server.server_close()


def test_telegram_webhook_requires_secret_and_accepts_valid_json(caplog):
    received = []
    secret = "A_secure_webhook_secret_1234567890"
    server = start_dashboard(
        "postgresql://unused",
        host="127.0.0.1",
        port=0,
        webhook_path="/telegram/webhook",
        webhook_secret=secret,
        webhook_callback=lambda payload: received.append(payload) is None,
    )
    url = f"http://127.0.0.1:{server.server_address[1]}/telegram/webhook"
    try:
        payload = b'{"update_id":123,"message":{"text":"contenu-prive-test"}}'
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(url, data=payload, headers={"Content-Type": "application/json"}), timeout=2)
        assert denied.value.code == 401
        assert received == []

        request = Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": secret,
        })
        with urlopen(request, timeout=2) as response:
            assert response.status == 200
        assert received == [{"update_id": 123, "message": {"text": "contenu-prive-test"}}]
        assert "contenu-prive-test" not in caplog.text
    finally:
        server.shutdown()
        server.server_close()


def test_telegram_webhook_rejects_invalid_and_oversized_payloads():
    secret = "A_secure_webhook_secret_1234567890"
    server = start_dashboard(
        "postgresql://unused",
        host="127.0.0.1",
        port=0,
        webhook_path="/telegram/webhook",
        webhook_secret=secret,
        webhook_callback=lambda _payload: True,
        webhook_max_body_bytes=32,
    )
    url = f"http://127.0.0.1:{server.server_address[1]}/telegram/webhook"
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
    try:
        with pytest.raises(HTTPError) as malformed:
            urlopen(Request(url, data=b"not-json", headers=headers), timeout=2)
        assert malformed.value.code == 400

        with pytest.raises(HTTPError) as oversized:
            urlopen(Request(url, data=b"x" * 33, headers=headers), timeout=2)
        assert oversized.value.code == 413
    finally:
        server.shutdown()
        server.server_close()
