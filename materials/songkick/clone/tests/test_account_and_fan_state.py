from __future__ import annotations

from fastapi.testclient import TestClient
import os

from app import app


def register(client: TestClient, email: str) -> dict[str, object]:
    assert client.get("/api/auth/session").json()["authenticated"] is False
    started = client.post(
        "/api/auth/register/start",
        json={"email": email, "display_name": "Concert Fan", "password": "correct-horse-9"},
    )
    assert started.status_code == 200
    mail = client.get("/api/auth/local-mail/registration").json()["message"]
    assert mail["status"] == "LOCAL_ONLY"
    finished = client.post("/api/auth/register/verify", json={"code": mail["verification_code"]})
    assert finished.status_code == 200
    assert finished.json()["authenticated"] is True
    return finished.json()["account"]


def test_registration_signout_relogin_and_account_isolation() -> None:
    first = TestClient(app, base_url="https://songkick.local")
    second = TestClient(app, base_url="https://songkick.local")
    account = register(first, "fan-one@example.test")
    assert account["display_name"] == "Concert Fan"

    tracked = first.put("/api/me/artists/10355080", json={"tracked": True})
    interested = first.put("/api/me/events/43365625", json={"status": "interested"})
    assert tracked.json()["tracked"] is True
    assert interested.json()["status"] == "interested"
    assert first.get("/api/me/library").json() == {
        "tracked_artist_ids": ["10355080"],
        "events": [{"event_id": "43365625", "status": "interested"}],
    }
    assert second.get("/api/me/library").status_code == 401

    assert first.post("/api/auth/sign-out").json() == {"signed_out": True}
    assert first.get("/api/auth/session").json()["authenticated"] is False
    signed_in = first.post(
        "/api/auth/sign-in",
        json={"email": "fan-one@example.test", "password": "correct-horse-9"},
    )
    assert signed_in.status_code == 200
    assert first.get("/api/me/library").json()["tracked_artist_ids"] == ["10355080"]


def test_event_state_and_preferences_have_exact_inverse_transitions() -> None:
    client = TestClient(app, base_url="https://songkick.local")
    register(client, "fan-two@example.test")
    assert client.put("/api/me/events/43365625", json={"status": "attended"}).json()["status"] == "attended"
    assert client.put("/api/me/events/43365625", json={"status": "none"}).json()["status"] == "none"
    assert client.get("/api/me/library").json()["events"] == []

    updated = client.put(
        "/api/me/preferences",
        json={"location": "Toronto", "theme": "dark", "locale": "fr", "cookie_preferences": {"analytics": False}},
    )
    assert updated.status_code == 200
    assert updated.json()["location"] == "Toronto"
    assert client.get("/api/me/preferences").json() == updated.json()


def test_password_reset_is_enumeration_resistant_and_changes_credentials() -> None:
    client = TestClient(app, base_url="https://songkick.local")
    register(client, "reset-fan@example.test")
    client.post("/api/auth/sign-out")

    known = client.post("/api/auth/password-reset/start", json={"email": "reset-fan@example.test"})
    public_message = known.json()["message"]
    mail = client.get("/api/auth/local-mail/password-reset").json()["message"]
    assert mail["status"] == "LOCAL_ONLY"
    assert client.post("/api/auth/password-reset/verify", json={"code": mail["verification_code"]}).status_code == 200
    complete = client.post("/api/auth/password-reset/complete", json={"password": "new-correct-horse-10"})
    assert complete.status_code == 200
    client.post("/api/auth/sign-out")
    assert client.post("/api/auth/sign-in", json={"email": "reset-fan@example.test", "password": "new-correct-horse-10"}).status_code == 200

    unknown_client = TestClient(app, base_url="https://songkick.local")
    unknown = unknown_client.post("/api/auth/password-reset/start", json={"email": "missing@example.test"})
    assert unknown.status_code == 200
    assert unknown.json()["message"] == public_message
    assert unknown_client.get("/api/auth/local-mail/password-reset").json()["message"] is None


def test_business_mutations_reject_anonymous_and_invalid_states() -> None:
    anonymous = TestClient(app, base_url="https://songkick.local")
    assert anonymous.put("/api/me/artists/10355080", json={"tracked": True}).status_code == 401
    register(anonymous, "fan-three@example.test")
    assert anonymous.put("/api/me/events/43365625", json={"status": "maybe"}).status_code == 422


def test_verifier_fixture_session_is_disabled_by_default_and_token_guarded(monkeypatch) -> None:
    client = TestClient(app, base_url="https://songkick.local")
    monkeypatch.delenv("WEBSITEBENCH_FIXTURE_TOKEN", raising=False)
    assert client.post("/__websitebench/session").status_code == 404

    monkeypatch.setenv("WEBSITEBENCH_FIXTURE_TOKEN", "fixture-secret-123")
    assert client.post("/__websitebench/session").status_code == 404
    seeded = client.post(
        "/__websitebench/session",
        headers={"x-websitebench-fixture-token": "fixture-secret-123"},
    )
    assert seeded.status_code == 200
    assert seeded.json() == {"authenticated": True}
    assert "websitebench-songkick-fixture-session" in client.cookies
    assert "__Host-websitebench-songkick-session" not in client.cookies
    assert client.get("/api/auth/session").json()["authenticated"] is True


def test_ordinary_sessions_keep_the_secure_host_only_cookie_contract(monkeypatch) -> None:
    monkeypatch.delenv("WEBSITEBENCH_FIXTURE_TOKEN", raising=False)
    client = TestClient(app, base_url="https://songkick.local")
    response = client.get("/api/auth/session")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-websitebench-songkick-session=")
    assert "Secure" in cookie


def test_explicit_verifier_boot_uses_loopback_fixture_cookie(monkeypatch) -> None:
    monkeypatch.setenv("WEBSITEBENCH_FIXTURE_TOKEN", "test-only-verifier-boundary")
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get("/api/auth/session")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("websitebench-songkick-fixture-session=")
    assert "Secure" not in cookie
    assert "__Host-websitebench-songkick-session" not in cookie
    assert "HttpOnly" in cookie
    assert "Domain=" not in cookie
