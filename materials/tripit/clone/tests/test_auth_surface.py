"""Auth-surface contract for the TripIt clone.

/account/login and /account/create are live templates rather than frozen
replays, because a frozen page cannot report why a submission was rejected.
This module pins what that conversion is allowed to change:

* the default render of each surface still matches the frozen capture, so the
  visual contract is untouched (the sign-in page byte for byte, and the create
  page everywhere except the documented form changes);
* the captured field names are unchanged, since they are part of the structural
  contract a source comparison checks;
* "Keep me signed in." decides the session cookie's lifetime instead of being
  accepted and discarded;
* the User Agreement checkbox is enforced by the server rather than by a
  client-side gate over a hidden always-true field;
* the Google control on both surfaces lands on a page that says third-party
  sign-in is not completed here, and signs nobody in;
* registration still round-trips end to end, wrong codes are rejected, and two
  browsers never share a session.

The Home City picker behind the create form has its own module,
``test_place_completion.py``.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"
PAGES_DIR = CLONE_DIR / "frontend" / "pages"

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-auth-surface-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"
CREATE_URL = "/account/create"
STRONG_PASSWORD = "correct-horse-battery-staple"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_auth_surface_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app
SESSION_COOKIE = app_module.SESSION_COOKIE

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
TRAVELER = "traveler@example.com"


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


def set_cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


def registration_code(token: str) -> str:
    """Read the emitted challenge for a synthetic account back out of the local
    store, purely to feed it into /account/verify. The value is never asserted."""

    mail = app_module.auth_store().local_mail_for_session(token, purpose="registration")
    assert isinstance(mail, dict), "expected a local registration mail"
    return str(mail["verification_code"])


# ---------------------------------------------------------------------------
# the live surfaces still are the captured surfaces
# ---------------------------------------------------------------------------


def test_sign_in_default_render_matches_the_frozen_capture(client):
    frozen = (PAGES_DIR / "login.html").read_text(encoding="utf-8")
    assert client.get(LOGIN_URL).text == frozen


def test_sign_up_default_render_changes_only_the_documented_form_controls(client):
    frozen = (PAGES_DIR / "create.html").read_text(encoding="utf-8")
    live = client.get(CREATE_URL).text

    # 1. the always-true hidden toc is gone, 2. the checkbox carries its name,
    # 3. the submit button is usable without scripting, 4. the enhancement that
    # restores the gated appearance is loaded. Nothing else may differ.
    normalized = live.replace(
        '<input type="checkbox" id="user-agreement-and-privacy" name="toc" value="1"'
        ' data-required-checkbox="1" style="">',
        '<input type="checkbox" id="user-agreement-and-privacy"'
        ' data-required-checkbox="1" style="">',
    ).replace(
        'class="btn btn-md btn-primary btn-dark-blue signin-submit-btn"'
        ' data-requires-checkbox="user-agreement-and-privacy">Create an Account</button>',
        'class="btn btn-md btn-primary btn-dark-blue signin-submit-btn'
        ' should-not-enable" disabled="">Create an Account</button>',
    ).replace(
        '<script src="/static/site/js/auth-ui.js"></script>', ""
    )
    normalized = normalized.replace(
        '<input type="hidden" name="errors" style="">',
        '<input type="hidden" name="errors" style=""><input type="hidden" name="toc"'
        ' value="1" style="">',
    )
    assert normalized == frozen


def test_public_registration_form_issues_the_session_required_by_send_code(
    client, monkeypatch
):
    monkeypatch.setattr(app_module, "PUBLIC_REGISTRATION_VERIFICATION", object())
    monkeypatch.setitem(
        app_module.templates.env.globals, "public_registration_enabled", True
    )

    response = client.get(CREATE_URL)

    assert response.status_code == 200
    assert client.cookies.get(SESSION_COOKIE)
    assert SESSION_COOKIE in set_cookie_header(response)
    assert 'data-external-registration="true"' in response.text
    assert 'href="/static/site/css/registration-verification.css"' in response.text
    assert 'class="verification-code-panel"' in response.text
    assert 'placeholder="6-digit code"' in response.text
    assert 'aria-describedby="verification-code-help verification-status"' in response.text


@pytest.mark.parametrize(
    "url,names",
    [
        (LOGIN_URL, ("login_email_address", "login_password", "remember_me")),
        (CREATE_URL, ("email_address", "password", "place")),
    ],
)
def test_captured_field_names_are_unchanged(client, url, names):
    body = client.get(url).text
    for name in names:
        assert f'name="{name}"' in body, (url, name)


def test_both_surfaces_render_their_captured_google_control(client):
    assert 'href="/account/signInGoogle"' in client.get(LOGIN_URL).text
    assert 'href="/account/signUpGoogle"' in client.get(CREATE_URL).text


def test_sign_in_page_is_deterministic_across_requests(client):
    assert client.get(LOGIN_URL).text == client.get(LOGIN_URL).text
    assert client.get(CREATE_URL).text == client.get(CREATE_URL).text


# ---------------------------------------------------------------------------
# rejected submissions say why, in the source's own error markup
# ---------------------------------------------------------------------------


def test_wrong_password_re_renders_with_an_error_and_no_session(client):
    response = client.post(
        LOGIN_URL,
        data={"login_email_address": TRAVELER, "login_password": "not-the-password"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "do not match an account" in response.text
    assert 'role="alert"' in response.text
    assert SESSION_COOKIE not in set_cookie_header(response)
    assert client.cookies.get(SESSION_COOKIE) is None


def test_a_rejected_sign_in_does_not_show_the_registration_password_rule(client):
    """The password field's captured helper reads "At least 15 characters.
    Cannot be an email." — a registration rule. Revealing it next to a sign-in
    field would tell the visitor their existing password is wrong when it is
    only unmatched, so a credential mismatch never flags that field."""

    response = client.post(
        LOGIN_URL,
        data={"login_email_address": TRAVELER, "login_password": "wrong"},
        follow_redirects=False,
    )
    assert "input-wrapper-error" not in response.text
    assert "floating-label-input-error" not in response.text


def test_wrong_password_error_does_not_disclose_whether_the_account_exists(client):
    known = client.post(
        LOGIN_URL,
        data={"login_email_address": TRAVELER, "login_password": "not-the-password"},
        follow_redirects=False,
    )
    unknown = client.post(
        LOGIN_URL,
        data={
            "login_email_address": "nobody-at-all@example.com",
            "login_password": "not-the-password",
        },
        follow_redirects=False,
    )
    assert known.status_code == unknown.status_code == 200
    strip = lambda text: re.sub(r"value=\"[^\"]*\"", "", text)  # noqa: E731
    assert strip(known.text) == strip(unknown.text)


def test_malformed_email_is_rejected_before_the_store_is_touched(client):
    response = client.post(
        LOGIN_URL,
        data={"login_email_address": "not-an-email", "login_password": "whatever"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "input-wrapper-error" in response.text
    assert 'value="not-an-email"' in response.text
    assert client.cookies.get(SESSION_COOKIE) is None


def test_a_rejected_sign_in_keeps_the_typed_address(client):
    response = client.post(
        LOGIN_URL,
        data={"login_email_address": TRAVELER, "login_password": "wrong"},
        follow_redirects=False,
    )
    assert f'value="{TRAVELER}"' in response.text


# ---------------------------------------------------------------------------
# "Keep me signed in." is real
# ---------------------------------------------------------------------------


def test_remember_me_checked_issues_a_cookie_that_survives_the_browser(client):
    response = client.post(
        LOGIN_URL,
        data={
            "login_email_address": TRAVELER,
            "login_password": PASSWORDS[TRAVELER],
            "remember_me": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    header = set_cookie_header(response)
    assert SESSION_COOKIE in header
    assert "Max-Age=" in header


def test_remember_me_unchecked_issues_a_session_only_cookie(client):
    response = client.post(
        LOGIN_URL,
        data={"login_email_address": TRAVELER, "login_password": PASSWORDS[TRAVELER]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    header = set_cookie_header(response)
    assert SESSION_COOKIE in header
    assert "Max-Age=" not in header
    assert "expires=" not in header.lower()


def test_both_remember_me_choices_sign_the_traveler_in(client):
    for value in ({}, {"remember_me": "on"}):
        fresh = TestClient(app, base_url="https://testserver")
        response = fresh.post(
            LOGIN_URL,
            data={
                "login_email_address": TRAVELER,
                "login_password": PASSWORDS[TRAVELER],
                **value,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert fresh.get("/trips", follow_redirects=False).status_code == 200


# ---------------------------------------------------------------------------
# third-party sign-in lands on an honest boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/account/signInGoogle", "/account/signUpGoogle"])
def test_provider_control_answers_with_a_boundary_page(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert "Google" in response.text
    assert "not one of the sign-in methods" in response.text


@pytest.mark.parametrize("path", ["/account/signInGoogle", "/account/signUpGoogle"])
def test_provider_control_signs_nobody_in(client, path):
    client.get(path)
    assert client.cookies.get(SESSION_COOKIE) is None
    assert client.get("/trips", follow_redirects=False).status_code == 303


def test_provider_boundary_points_back_at_the_email_form(client):
    assert 'href="/account/login"' in client.get("/account/signInGoogle").text
    assert 'href="/account/create"' in client.get("/account/signUpGoogle").text


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_registration_requires_the_user_agreement_checkbox(client):
    response = client.post(
        "/account/update",
        data={
            "email_address": "needs-toc@example.com",
            "password": STRONG_PASSWORD,
            "place": "Denver, CO",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "User Agreement" in response.text
    # and no account was started: the address is still free
    accepted = client.post(
        "/account/update",
        data={
            "email_address": "needs-toc@example.com",
            "password": STRONG_PASSWORD,
            "place": "Denver, CO",
            "toc": "1",
        },
    )
    assert accepted.status_code == 200
    assert "Verify your email" in accepted.text


def test_registration_rejects_a_short_password_on_the_create_surface(client):
    response = client.post(
        "/account/update",
        data={
            "email_address": "short-secret@example.com",
            "password": "tiny",
            "place": "",
            "toc": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "At least 15 characters" in response.text
    assert 'value="short-secret@example.com"' in response.text


def test_registration_round_trip_then_sign_out_and_back_in(client):
    email = "round-trip@example.com"
    started = client.post(
        "/account/update",
        data={
            "email_address": email,
            "password": STRONG_PASSWORD,
            "place": "Lisbon, Portugal",
            "toc": "1",
        },
    )
    assert started.status_code == 200
    token = client.cookies.get(SESSION_COOKIE)
    assert token

    verified = client.post(
        "/account/verify",
        data={"code": registration_code(token), "email": email, "place": "Lisbon, Portugal"},
        follow_redirects=False,
    )
    assert verified.status_code == 303
    assert client.get("/trips", follow_redirects=False).status_code == 200

    # the Home City the create form collected reached the profile
    assert "Lisbon, Portugal" in client.get("/account").text

    out = client.post("/account/logout", follow_redirects=False)
    assert out.status_code == 303
    assert client.get("/trips", follow_redirects=False).status_code == 303

    back = client.post(
        LOGIN_URL,
        data={"login_email_address": email, "login_password": STRONG_PASSWORD},
        follow_redirects=False,
    )
    assert back.status_code == 303
    assert client.get("/trips", follow_redirects=False).status_code == 200


def test_registration_can_be_posted_to_the_surfaces_own_path(client):
    response = client.post(
        CREATE_URL,
        data={
            "email_address": "posted-to-create@example.com",
            "password": STRONG_PASSWORD,
            "place": "",
            "toc": "1",
        },
    )
    assert response.status_code == 200
    assert "Verify your email" in response.text


def test_a_wrong_verification_code_mints_no_account(client):
    email = "bad-code@example.com"
    client.post(
        "/account/update",
        data={
            "email_address": email,
            "password": STRONG_PASSWORD,
            "place": "",
            "toc": "1",
        },
    )
    rejected = client.post(
        "/account/verify",
        data={"code": "000000", "email": email, "place": ""},
        follow_redirects=False,
    )
    assert rejected.status_code == 400
    other = TestClient(app, base_url="https://testserver")
    attempt = other.post(
        LOGIN_URL,
        data={"login_email_address": email, "login_password": STRONG_PASSWORD},
        follow_redirects=False,
    )
    assert attempt.status_code == 200
    assert other.cookies.get(SESSION_COOKIE) is None


def test_two_browsers_do_not_share_a_session(client):
    signed_in = TestClient(app, base_url="https://testserver")
    signed_in.post(
        LOGIN_URL,
        data={"login_email_address": TRAVELER, "login_password": PASSWORDS[TRAVELER]},
    )
    anonymous = TestClient(app, base_url="https://testserver")
    assert signed_in.get("/trips", follow_redirects=False).status_code == 200
    assert anonymous.get("/trips", follow_redirects=False).status_code == 303
