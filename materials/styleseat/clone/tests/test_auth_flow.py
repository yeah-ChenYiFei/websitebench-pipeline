from __future__ import annotations

from fastapi.testclient import TestClient

import app as clone_app
from websitebench.local_clone_auth import (
    LocalAuthStore,
    RESET_PUBLIC_MESSAGE,
)


def test_registration_start_creates_only_a_pending_flow(tmp_path, monkeypatch) -> None:
    """Catches a missing adapter or an adapter that creates an account too early."""

    auth = LocalAuthStore(tmp_path / "styleseat.sqlite3")
    auth.ensure_schema()
    monkeypatch.setattr(clone_app, "AUTH", auth)

    with TestClient(clone_app.app, base_url="https://testserver") as client:
        response = client.post(
            "/_local/auth/register/start",
            json={
                "email": "new-client@clone.test",
                "displayName": "New Client",
                "password": "Local-Client-2026!",
            },
        )

    assert response.status_code == 200
    assert response.json()["stage"] == "pending-verification"
    assert response.cookies.get(clone_app.COOKIE)
    assert auth.counts()["local_auth_accounts"] == 0
    assert auth.counts()["local_auth_registration_flows"] == 1


def test_registration_verification_creates_account_once_and_rotates_session(
    tmp_path, monkeypatch
) -> None:
    """Catches code bypass, pre-verification accounts, and replayable completion."""

    auth = LocalAuthStore(tmp_path / "styleseat.sqlite3")
    auth.ensure_schema()
    monkeypatch.setattr(clone_app, "AUTH", auth)

    with TestClient(clone_app.app, base_url="https://testserver") as client:
        client.post(
            "/_local/auth/register/start",
            json={
                "email": "verified-client@clone.test",
                "displayName": "Verified Client",
                "password": "Verified-Client-2026!",
            },
        )
        before_rotation = client.cookies.get(clone_app.COOKIE)
        outbox = client.get("/_local/auth/outbox", params={"purpose": "registration"})
        code = outbox.json()["mail"]["verification_code"]

        wrong = client.post("/_local/auth/register/verify", json={"code": "000000"})
        assert wrong.status_code == 401
        assert auth.counts()["local_auth_accounts"] == 0

        verified = client.post("/_local/auth/register/verify", json={"code": code})
        assert verified.status_code == 200
        assert verified.json() == {"stage": "verified"}
        assert auth.counts()["local_auth_accounts"] == 0

        completed = client.post("/_local/auth/register/complete", json={})
        after_rotation = client.cookies.get(clone_app.COOKIE)
        session = client.get("/_local/auth/session")
        replay = client.post("/_local/auth/register/complete", json={})

    assert completed.status_code == 200
    assert completed.json() == {
        "stage": "account-created",
        "authenticated": True,
        "email": "verified-client@clone.test",
        "displayName": "Verified Client",
    }
    assert before_rotation and after_rotation and after_rotation != before_rotation
    assert session.json()["authenticated"] is True
    assert session.json()["email"] == "verified-client@clone.test"
    assert replay.status_code == 401
    assert auth.counts()["local_auth_accounts"] == 1


def test_signin_signout_rotate_sessions_and_drive_authenticated_pages(
    tmp_path, monkeypatch
) -> None:
    """Catches missing endpoints, fixed sessions, and a cookie ignored by pages."""

    auth = LocalAuthStore(tmp_path / "styleseat.sqlite3")
    auth.ensure_schema()
    auth.seed_account(
        subject_id="styleseat-signin-test",
        email="returning-client@clone.test",
        display_name="Returning Client",
        password="Returning-Client-2026!",
        email_verified=True,
    )
    monkeypatch.setattr(clone_app, "AUTH", auth)
    with TestClient(clone_app.app, base_url="https://testserver") as client:
        initial = client.get("/_local/auth/session")
        anonymous_token = client.cookies.get(clone_app.COOKIE)
        rejected = client.post(
            "/_local/auth/signin",
            json={
                "email": "returning-client@clone.test",
                "password": "Wrong-Password-2026!",
            },
        )
        signed_in = client.post(
            "/_local/auth/signin",
            json={
                "email": "RETURNING-CLIENT@CLONE.TEST",
                "password": "Returning-Client-2026!",
            },
        )
        authenticated_token = client.cookies.get(clone_app.COOKIE)
        member_page = client.get("/m/client-appointments")
        legacy_identity = client.get("/accounts/whoami/")
        signed_out = client.post("/_local/auth/signout")
        signed_out_token = client.cookies.get(clone_app.COOKIE)
        anonymous_page = client.get("/m/client-appointments")

    assert initial.json()["authenticated"] is False
    assert rejected.status_code == 401
    assert signed_in.status_code == 200
    assert signed_in.json() == {
        "authenticated": True,
        "email": "returning-client@clone.test",
        "displayName": "Returning Client",
    }
    assert anonymous_token and authenticated_token != anonymous_token
    assert auth.resolve_session(anonymous_token) is None
    assert 'data-testid="client-my-settings-menu"' in member_page.text
    assert legacy_identity.json()["isLogin"] is True
    assert legacy_identity.json()["email"] == "returning-client@clone.test"
    assert signed_out.status_code == 200
    assert signed_out.json()["authenticated"] is False
    assert signed_out_token and signed_out_token != authenticated_token
    assert auth.resolve_session(authenticated_token) is None
    assert 'data-testid="header-link-login-button"' in anonymous_page.text
    assert 'data-testid="client-my-settings-menu"' not in anonymous_page.text


def test_password_reset_is_private_consumable_and_changes_credentials(
    tmp_path, monkeypatch
) -> None:
    """Catches enumeration, code bypass/replay, and an unchanged password."""

    auth = LocalAuthStore(tmp_path / "styleseat.sqlite3")
    auth.ensure_schema()
    auth.seed_account(
        subject_id="styleseat-reset-test",
        email="reset-client@clone.test",
        display_name="Reset Client",
        password="Old-Password-2026!",
        email_verified=True,
    )
    monkeypatch.setattr(clone_app, "AUTH", auth)

    with TestClient(clone_app.app, base_url="https://testserver") as known:
        started = known.post(
            "/_local/auth/reset/start",
            json={"email": "reset-client@clone.test"},
        )
        code = known.get(
            "/_local/auth/outbox", params={"purpose": "password-reset"}
        ).json()["mail"]["verification_code"]
        wrong = known.post("/_local/auth/reset/verify", json={"code": "000000"})
        verified = known.post("/_local/auth/reset/verify", json={"code": code})
        before_completion = known.cookies.get(clone_app.COOKIE)
        completed = known.post(
            "/_local/auth/reset/complete",
            json={"password": "New-Password-2026!"},
        )
        after_completion = known.cookies.get(clone_app.COOKIE)
        session_after_completion = known.get("/_local/auth/session")
        replay = known.post(
            "/_local/auth/reset/complete",
            json={"password": "Another-Password-2026!"},
        )
        old_password = known.post(
            "/_local/auth/signin",
            json={
                "email": "reset-client@clone.test",
                "password": "Old-Password-2026!",
            },
        )
        new_password = known.post(
            "/_local/auth/signin",
            json={
                "email": "reset-client@clone.test",
                "password": "New-Password-2026!",
            },
        )

    with TestClient(clone_app.app, base_url="https://testserver") as unknown:
        hidden = unknown.post(
            "/_local/auth/reset/start",
            json={"email": "not-an-account@clone.test"},
        )
        hidden_outbox = unknown.get(
            "/_local/auth/outbox", params={"purpose": "password-reset"}
        )

    assert started.status_code == hidden.status_code == 200
    assert started.json() == hidden.json() == {"message": RESET_PUBLIC_MESSAGE}
    assert hidden_outbox.json()["mail"] is None
    assert wrong.status_code == 401
    assert verified.status_code == 200
    assert verified.json() == {"stage": "verified"}
    assert completed.status_code == 200
    assert completed.json() == {"stage": "consumed", "authenticated": False}
    assert before_completion and after_completion != before_completion
    assert session_after_completion.json()["authenticated"] is False
    assert replay.status_code == 401
    assert old_password.status_code == 401
    assert new_password.status_code == 200
    assert new_password.json()["authenticated"] is True


def test_captured_pages_load_the_styleseat_auth_runtime_and_signup_entry() -> None:
    """Catches a working API that no captured page can actually invoke."""

    with TestClient(clone_app.app, base_url="https://testserver") as client:
        home = client.get("/m/")
        login = client.get("/m/login")
        signup = client.get("/signup")
        runtime = client.get("/static/local-auth.js")

    script = '<script src="/static/local-auth.js" defer></script>'
    assert home.status_code == login.status_code == signup.status_code == 200
    assert script in home.text
    assert script in login.text
    assert script in signup.text
    assert runtime.status_code == 200
    assert 'var API = "/_local/auth"' in runtime.text
    assert 'booking-sign-in-and-up-email-text-field' in runtime.text
    assert 'header-link-login-button' in runtime.text
    assert 'client-my-settings-menu' in runtime.text
    for endpoint in (
        "/register/start",
        "/register/verify",
        "/register/complete",
        "/signin",
        "/signout",
        "/reset/start",
        "/reset/verify",
        "/reset/complete",
    ):
        assert endpoint in runtime.text


def test_registration_errors_keep_conflict_rate_limit_lock_and_expiry_statuses(
    tmp_path, monkeypatch
) -> None:
    """Catches an adapter that collapses distinct Store failures into 401/500."""

    auth = LocalAuthStore(tmp_path / "status.sqlite3")
    auth.ensure_schema()
    auth.seed_account(
        subject_id="styleseat-conflict-test",
        email="taken-client@clone.test",
        display_name="Taken Client",
        password="Taken-Client-2026!",
        email_verified=True,
    )
    monkeypatch.setattr(clone_app, "AUTH", auth)

    with TestClient(clone_app.app, base_url="https://testserver") as client:
        duplicate = client.post(
            "/_local/auth/register/start",
            json={
                "email": "taken-client@clone.test",
                "displayName": "Taken Again",
                "password": "Taken-Again-2026!",
            },
        )
        first = client.post(
            "/_local/auth/register/start",
            json={
                "email": "first-client@clone.test",
                "displayName": "First Client",
                "password": "First-Client-2026!",
            },
        )
        limited = client.post(
            "/_local/auth/register/start",
            json={
                "email": "second-client@clone.test",
                "displayName": "Second Client",
                "password": "Second-Client-2026!",
            },
        )

    with TestClient(clone_app.app, base_url="https://testserver") as locked_client:
        locked_client.post(
            "/_local/auth/register/start",
            json={
                "email": "locked-client@clone.test",
                "displayName": "Locked Client",
                "password": "Locked-Client-2026!",
            },
        )
        attempts = [
            locked_client.post(
                "/_local/auth/register/verify", json={"code": "000000"}
            )
            for _index in range(5)
        ]

    clock = {"now": 1_700_000_000}
    expiring = LocalAuthStore(
        tmp_path / "expired.sqlite3", now=lambda: clock["now"]
    )
    expiring.ensure_schema()
    monkeypatch.setattr(clone_app, "AUTH", expiring)
    with TestClient(clone_app.app, base_url="https://testserver") as expired_client:
        expired_client.post(
            "/_local/auth/register/start",
            json={
                "email": "expired-client@clone.test",
                "displayName": "Expired Client",
                "password": "Expired-Client-2026!",
            },
        )
        clock["now"] += 601
        expired = expired_client.post(
            "/_local/auth/register/verify", json={"code": "000000"}
        )

    assert duplicate.status_code == 409
    assert first.status_code == 200
    assert limited.status_code == 429
    assert [response.status_code for response in attempts] == [401, 401, 401, 401, 423]
    assert expired.status_code == 410
