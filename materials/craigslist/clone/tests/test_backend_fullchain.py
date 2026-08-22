"""Full-chain backend tests: registration verification, password reset,
and the mail outbox flows (backend fully implemented, not just entry pages)."""

from __future__ import annotations

import sqlite3


def _outbox_code(token: str, purpose: str) -> str:
    """Read the verification/reset code via the public local-mail API."""
    from backend import craigslist_db

    auth = craigslist_db.services()[1]
    mail = auth.local_mail_for_session(token, purpose=purpose)
    assert mail is not None, f"no LOCAL_ONLY {purpose} mail for session"
    return mail["verification_code"]


def test_registration_full_chain_with_outbox_code(client) -> None:
    """Register -> verification code in outbox -> verify -> account usable."""
    response = client.post(
        "/account/register",
        data={
            "email": "fullchain@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "agree_terms": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "verify your email" in response.text.lower()
    token = response.cookies.get("__Host-websitebench-craigslist-session")
    assert token

    code = _outbox_code(token, "registration")
    assert len(code) >= 4

    verified = client.post(
        "/account/register/verify",
        data={"code": code},
        cookies={"__Host-websitebench-craigslist-session": token},
        follow_redirects=False,
    )
    assert verified.status_code == 303  # redirected to account home

    # the new account can sign in with its password
    client.cookies.clear()
    login = client.post(
        "/account/login",
        data={"email": "fullchain@example.com", "password": "Password123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    home = client.get("/account/home")
    assert home.status_code == 200
    assert "fullchain@example.com" in home.text


def test_password_reset_full_chain_with_outbox_code(client) -> None:
    """Forgot -> reset code in outbox -> set new password -> sign in works."""
    sent = client.post("/account/forgot", data={"email": "poster@example.com"})
    assert sent.status_code == 200
    token = sent.cookies.get("__Host-websitebench-craigslist-session")
    assert token

    code = _outbox_code(token, "password-reset")
    assert len(code) >= 4

    reset = client.post(
        "/account/reset",
        data={"code": code, "password": "NewPassword456!", "confirm_password": "NewPassword456!"},
        cookies={"__Host-websitebench-craigslist-session": token},
        follow_redirects=False,
    )
    assert reset.status_code == 303

    client.cookies.clear()
    old_login = client.post(
        "/account/login",
        data={"email": "poster@example.com", "password": "Websitebench1!"},
    )
    assert old_login.status_code == 401  # old password no longer works
    new_login = client.post(
        "/account/login",
        data={"email": "poster@example.com", "password": "NewPassword456!"},
        follow_redirects=False,
    )
    assert new_login.status_code == 303


def test_reset_code_single_use(client) -> None:
    """A used reset code cannot be reused."""
    sent = client.post("/account/forgot", data={"email": "poster@example.com"})
    token = sent.cookies.get("__Host-websitebench-craigslist-session")
    code = _outbox_code(token, "password-reset")
    first = client.post(
        "/account/reset",
        data={"code": code, "password": "Reused456!", "confirm_password": "Reused456!"},
        cookies={"__Host-websitebench-craigslist-session": token},
        follow_redirects=False,
    )
    assert first.status_code == 303
    # a fresh session can no longer verify the same flow
    again = client.post(
        "/account/reset",
        data={"code": code, "password": "Again456!", "confirm_password": "Again456!"},
        cookies={"__Host-websitebench-craigslist-session": token},
    )
    assert again.status_code in (401, 422)


def test_reply_lands_in_outbox_and_persists(client) -> None:
    """A reply to a listing is stored and enqueued for the poster."""
    sent = client.post(
        "/toronto/housing/reply/1000001",
        data={"name": "Seeker", "email": "seeker@example.com", "message": "August still open?"},
    )
    assert sent.status_code == 200
    from contextlib import closing
    from backend import craigslist_db

    with closing(craigslist_db.connect()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT posting_id, name, email, message, recipient FROM cl_reply_messages"
            " WHERE posting_id=1000001 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["recipient"] == "poster@example.com"
    assert "August still open?" in row["message"]
