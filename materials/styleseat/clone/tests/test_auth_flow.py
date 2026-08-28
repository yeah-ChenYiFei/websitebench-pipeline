from __future__ import annotations

from fastapi.testclient import TestClient

import app as clone_app
import auth_api
from backend.site_backend_integration import open_site_services
from websitebench.local_clone_auth import (
    LocalAuthStore,
    MAIL_LOCAL_ONLY,
    MAIL_SMTP_PENDING,
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
    assert response.cookies.get("wb_session")
    assert auth.counts()["local_auth_accounts"] == 0
    assert auth.counts()["local_auth_registration_flows"] == 1


def test_smtp_registration_delivery_is_real_and_not_exposed_by_outbox(
    tmp_path, monkeypatch
) -> None:
    """Catches fake delivery, wrong envelope fields, and SMTP challenge leakage."""

    worker_token = "styleseat-test-mail-worker-token"
    auth = LocalAuthStore(
        tmp_path / "styleseat.sqlite3",
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    auth.ensure_schema()
    session = auth.create_anonymous_session()
    auth.start_registration(
        session,
        email="smtp-client@clone.test",
        display_name="SMTP Client",
        password="SMTP-Client-2026!",
    )
    delivered = []

    class CapturingSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 1025, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, message):
            delivered.append(message)

    monkeypatch.setenv("WEBSITEBENCH_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_PORT", "1025")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_FROM", "no-reply@clone.test")
    monkeypatch.setattr(auth_api.smtplib, "SMTP", CapturingSMTP)

    result = auth_api._deliver_smtp(
        auth,
        session,
        "registration",
        worker_token=worker_token,
    )

    assert result == {
        "mail_id": 1,
        "purpose": "registration",
        "status": "SMTP_SENT",
    }
    assert auth.session_mail_status(session, purpose="registration") == "SMTP_SENT"
    assert auth.local_mail_for_session(session, purpose="registration") is None
    assert len(delivered) == 1
    message = delivered[0]
    assert message["To"] == "smtp-client@clone.test"
    assert message["From"] == "no-reply@clone.test"
    assert message["Subject"] == "Verify your StyleSeat account"
    assert "6-digit verification code" in message.get_content()
    assert "10 minutes" in message.get_content()


def test_registration_verification_creates_account_once_and_rotates_session(
    tmp_path, monkeypatch
) -> None:
    """Catches code bypass, pre-verification accounts, and replayable completion."""

    auth = LocalAuthStore(tmp_path / "styleseat.sqlite3")
    auth.ensure_schema()
    monkeypatch.setattr(clone_app, "AUTH", auth)

    with TestClient(clone_app.app, base_url="https://testserver") as client:
        started = client.post(
            "/_local/auth/register/start",
            json={
                "email": "verified-client@clone.test",
                "displayName": "Verified Client",
                "password": "Verified-Client-2026!",
            },
        )
        before_rotation = client.cookies.get("wb_session")
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
        after_rotation = client.cookies.get("wb_session")
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


def test_standard_smtp_environment_selects_a_worker_authorized_store(
    tmp_path, monkeypatch
) -> None:
    """Catches ignored SMTP variables and a Store opened with the wrong mail mode."""

    database = tmp_path / "styleseat.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    monkeypatch.setenv("WEBSITEBENCH_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_PORT", "1025")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_FROM", "no-reply@clone.test")

    options = auth_api.store_mail_options()
    _backend, auth = open_site_services(**options)

    assert options["mail_mode"] == MAIL_SMTP_PENDING
    assert len(options["mail_worker_token"]) >= 20
    assert auth.mail_mode == MAIL_SMTP_PENDING

    monkeypatch.delenv("WEBSITEBENCH_SMTP_FROM")
    assert auth_api.store_mail_options() == {
        "mail_mode": MAIL_LOCAL_ONLY,
        "mail_worker_token": None,
    }


def test_registration_start_dispatches_pending_smtp_mail(
    tmp_path, monkeypatch
) -> None:
    """Catches an API that queues SMTP mail but never hands it to Mailpit."""

    auth = LocalAuthStore(
        tmp_path / "styleseat.sqlite3",
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=auth_api._MAIL_WORKER_TOKEN,
    )
    auth.ensure_schema()
    monkeypatch.setattr(clone_app, "AUTH", auth)
    monkeypatch.setenv("WEBSITEBENCH_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_PORT", "1025")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_FROM", "no-reply@clone.test")
    delivered = []

    class CapturingSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 1025, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, message):
            delivered.append(message)

    monkeypatch.setattr(auth_api.smtplib, "SMTP", CapturingSMTP)

    with TestClient(clone_app.app, base_url="https://testserver") as client:
        response = client.post(
            "/_local/auth/register/start",
            json={
                "email": "mailpit-client@clone.test",
                "displayName": "Mailpit Client",
                "password": "Mailpit-Client-2026!",
            },
        )
        session = client.cookies.get("wb_session")
        outbox = client.get("/_local/auth/outbox", params={"purpose": "registration"})

    assert response.status_code == 200
    assert response.json()["flow"]["state"] == "challenge"
    assert auth.session_mail_status(session, purpose="registration") == "SMTP_SENT"
    assert len(delivered) == 1
    assert outbox.json()["mail"] is None


def test_smtp_network_failure_finishes_claim_as_failed(tmp_path, monkeypatch) -> None:
    """Catches a network exception that strands the outbox claim forever."""

    worker_token = "styleseat-test-mail-worker-token"
    auth = LocalAuthStore(
        tmp_path / "styleseat.sqlite3",
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    auth.ensure_schema()
    session = auth.create_anonymous_session()
    auth.start_registration(
        session,
        email="smtp-failure@clone.test",
        display_name="SMTP Failure",
        password="SMTP-Failure-2026!",
    )

    class FailingSMTP:
        def __init__(self, *_args, **_kwargs):
            raise OSError("Mailpit unavailable")

    monkeypatch.setenv("WEBSITEBENCH_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_PORT", "1025")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_FROM", "no-reply@clone.test")
    monkeypatch.setattr(auth_api.smtplib, "SMTP", FailingSMTP)

    result = auth_api._deliver_smtp(
        auth,
        session,
        "registration",
        worker_token=worker_token,
    )
    state = auth.session_mail_state(session, purpose="registration")

    assert result["status"] == "SMTP_FAILED"
    assert state["status"] == "SMTP_FAILED"
    assert state["claim_token"] is None
    assert state["last_error"] == "network"
    assert state["target_request_count"] == 1
    assert state["accepted_effect_count"] == 0


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
        anonymous_token = client.cookies.get("wb_session")
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
        authenticated_token = client.cookies.get("wb_session")
        member_page = client.get("/m/client-appointments")
        legacy_identity = client.get("/accounts/whoami/")
        signed_out = client.post("/_local/auth/signout")
        signed_out_token = client.cookies.get("wb_session")
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
        before_completion = known.cookies.get("wb_session")
        completed = known.post(
            "/_local/auth/reset/complete",
            json={"password": "New-Password-2026!"},
        )
        after_completion = known.cookies.get("wb_session")
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


def test_password_reset_api_delivers_only_through_smtp(tmp_path, monkeypatch) -> None:
    """Catches a reset route that reports success without dispatching its mail."""

    auth = LocalAuthStore(
        tmp_path / "styleseat.sqlite3",
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=auth_api._MAIL_WORKER_TOKEN,
    )
    auth.ensure_schema()
    auth.seed_account(
        subject_id="styleseat-reset-smtp-test",
        email="reset-mailpit@clone.test",
        display_name="Reset Mailpit",
        password="Reset-Mailpit-2026!",
        email_verified=True,
    )
    monkeypatch.setattr(clone_app, "AUTH", auth)
    monkeypatch.setenv("WEBSITEBENCH_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_PORT", "1025")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_FROM", "no-reply@clone.test")
    delivered = []

    class CapturingSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 1025, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, message):
            delivered.append(message)

    monkeypatch.setattr(auth_api.smtplib, "SMTP", CapturingSMTP)

    with TestClient(clone_app.app, base_url="https://testserver") as client:
        response = client.post(
            "/_local/auth/reset/start",
            json={"email": "reset-mailpit@clone.test"},
        )
        token = client.cookies.get("wb_session")
        outbox = client.get(
            "/_local/auth/outbox", params={"purpose": "password-reset"}
        )

    assert response.status_code == 200
    assert response.json() == {"message": RESET_PUBLIC_MESSAGE}
    assert auth.session_mail_status(token, purpose="password-reset") == "SMTP_SENT"
    assert outbox.json()["mail"] is None
    assert len(delivered) == 1
    assert delivered[0]["To"] == "reset-mailpit@clone.test"
    assert delivered[0]["From"] == "no-reply@clone.test"
    assert delivered[0]["Subject"] == "Reset your StyleSeat password"
    assert "6-digit verification code" in delivered[0].get_content()


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
