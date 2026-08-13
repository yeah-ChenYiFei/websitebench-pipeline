"""Full-stack auth journeys that the frozen coverage models as backend-only.

The source site's password-reset *completion* page was never captured (it lives
behind a one-time emailed link), so ``scope/coverage.json`` files these journeys
under ``source-unavailable-states`` / ``p0-auth-journeys`` with
``required_evidence_kinds == ["full-suite"]`` and "no visual acceptance
claimed". This module supplies that full-suite evidence:

* ``auth.sign-in.retry-corrected`` -- a rejected sign-in can be corrected on the
  same session and then succeeds.
* ``auth.password-reset.success`` -- a reset issued to a real account, verified
  with the emitted challenge and completed with a fresh secret, lets the account
  sign in with the new secret (and no longer with the old one).
* ``auth.password-reset.failure-invalid-challenge`` -- a wrong challenge is
  rejected by server authority and leaves the existing secret intact.

Completion is driven through the vendored store's server-authoritative API
(``verify_password_reset_code`` + ``complete_password_reset``) and the *outcome*
is asserted through the real HTTP ``/account/login`` route -- no uncaptured UI
page is invented. No secret value is ever asserted on or logged: the reset
challenge is read only to hand straight back to the store, and the wrong-code
case uses a literal ``"000000"`` without ever reading the real code.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"

# Pin a throwaway data dir before importing the app so it resolves its single
# sqlite file inside it.
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-fullstack-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"
FORGOT_URL = "/account/forgotPassword"
TRIPS_HOME = "/app/trips"
NEW_SECRET = "reset-secret-horse-staple-2027"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_fullstack_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
SESSION_COOKIE = app_module.SESSION_COOKIE


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app_module.reset_fixture_state()


def sign_in(client, email: str, password: str):
    return client.post(
        LOGIN_URL,
        data={"login_email_address": email, "login_password": password},
        follow_redirects=False,
    )


def reset_code(token: str) -> str:
    """Read back the emitted password-reset challenge for a session.

    Only used to hand the challenge straight back to the store's verifier; the
    value is never asserted on or logged.
    """

    mail = app_module.auth_store().local_mail_for_session(
        token, purpose="password-reset"
    )
    assert isinstance(mail, dict), "expected a local password-reset mail"
    return str(mail["verification_code"])


def test_sign_in_retry_after_correction(client):
    email = "traveler@example.com"

    rejected = sign_in(client, email, "wrong-password-2027")
    assert rejected.status_code == 200
    assert "Set-Cookie" not in rejected.headers or SESSION_COOKIE not in rejected.headers.get(
        "set-cookie", ""
    )
    assert client.cookies.get(SESSION_COOKIE) is None

    corrected = sign_in(client, email, PASSWORDS[email])
    assert corrected.status_code == 303
    assert corrected.headers.get("location") == TRIPS_HOME
    assert client.cookies.get(SESSION_COOKIE)


def test_password_reset_success_signs_in_with_new_secret(client):
    email = "traveler@example.com"
    old_password = PASSWORDS[email]

    requested = client.post(FORGOT_URL, data={"email_address": email})
    assert requested.status_code == 200
    assert "Check your email" in requested.text
    token = client.cookies.get(SESSION_COOKIE)
    assert token

    # Drive completion through server authority: verify the emitted challenge,
    # then set a fresh secret. This mirrors the emailed-link flow whose landing
    # page the source never exposed for capture.
    store = app_module.auth_store()
    store.verify_password_reset_code(token, reset_code(token))
    store.complete_password_reset(token, new_password=NEW_SECRET)

    # Assert the outcome purely through the real login route. The reset request
    # left an anonymous session cookie on the client, so "rejected" is signalled
    # by the re-rendered 200 that issues no authenticated session -- not by an
    # absent cookie; "accepted" is the 303 that does issue one.
    stale = sign_in(client, email, old_password)
    assert stale.status_code == 200
    assert stale.headers.get("location") is None
    assert SESSION_COOKIE not in stale.headers.get("set-cookie", "")

    fresh = sign_in(client, email, NEW_SECRET)
    assert fresh.status_code == 303
    assert fresh.headers.get("location") == TRIPS_HOME
    assert SESSION_COOKIE in fresh.headers.get("set-cookie", "")


def test_password_reset_rejects_invalid_challenge(client):
    email = "traveler@example.com"

    requested = client.post(FORGOT_URL, data={"email_address": email})
    assert requested.status_code == 200
    token = client.cookies.get(SESSION_COOKIE)
    assert token

    # A wrong challenge is rejected by server authority. "000000" is a literal
    # placeholder; the real emitted code is never read here.
    with pytest.raises(app_module.AuthError):
        app_module.auth_store().verify_password_reset_code(token, "000000")

    # The existing secret still authenticates -- the failed challenge changed
    # nothing.
    intact = sign_in(client, email, PASSWORDS[email])
    assert intact.status_code == 303
    assert intact.headers.get("location") == TRIPS_HOME
