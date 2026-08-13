"""Cookie Preferences: the footer control's destination and the choice it records.

In the source the footer's Cookie Preferences link is ``href="#"`` with a
consent script bound to it — so with that script absent, the control does
nothing. Here it is a real link to a real page, enhanced into an in-place
dialog by the shell. This module pins both halves: the page works on its own,
and the dialog it is enhanced into carries the overlay contract (a paired
aria-expanded/aria-hidden, a labelled dialog, a close control, and a trigger
that is still a real link so a modifier-click opens the page).
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
SHELL = CLONE_DIR / "frontend" / "templates" / "app" / "base.html"
SHELL_JS = CLONE_DIR / "static" / "site" / "js" / "app-ui.js"

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-cookie-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_cookie_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app
CHOICE_COOKIE = app_module.COOKIE_CHOICE_COOKIE

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
TRAVELER = "traveler@example.com"


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    signed_in = TestClient(app, base_url="https://testserver")
    response = signed_in.post(
        "/account/login",
        data={"login_email_address": TRAVELER, "login_password": PASSWORDS[TRAVELER]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    yield signed_in
    app_module.reset_fixture_state()


# ---------------------------------------------------------------------------
# the page works on its own
# ---------------------------------------------------------------------------


def test_the_page_answers_and_offers_both_choices(client):
    response = client.get("/app/cookie-preferences")
    assert response.status_code == 200
    assert 'value="all"' in response.text
    assert 'value="necessary"' in response.text
    assert 'method="post"' in response.text


def test_the_page_is_reachable_signed_out():
    # A cookie choice is not an account setting; a visitor must be able to make
    # one before signing in.
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get("/app/cookie-preferences").status_code == 200


def test_a_choice_is_recorded_and_replayed_on_the_form(client):
    response = client.post(
        "/app/cookie-preferences",
        data={"cookie_choice": "necessary", "return_to": "/app/trips"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/app/trips"
    assert client.cookies.get(CHOICE_COOKIE) == "necessary"
    assert "checked" in client.get("/app/cookie-preferences").text


def test_the_choice_is_validated_against_the_named_constant(client):
    response = client.post(
        "/app/cookie-preferences",
        data={"cookie_choice": "everything-please"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert client.cookies.get(CHOICE_COOKIE) is None
    assert app_module.COOKIE_CHOICES == ("all", "necessary")


def test_an_absent_choice_is_rejected_rather_than_defaulted(client):
    response = client.post("/app/cookie-preferences", data={}, follow_redirects=False)
    assert response.status_code == 400
    assert client.cookies.get(CHOICE_COOKIE) is None


def test_the_return_target_cannot_leave_the_site(client):
    for hostile in ("https://example.com/", "//example.com/", "javascript:alert(1)"):
        response = client.post(
            "/app/cookie-preferences",
            data={"cookie_choice": "all", "return_to": hostile},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/app/trips", hostile


# ---------------------------------------------------------------------------
# the control in the shell, and the overlay it is enhanced into
# ---------------------------------------------------------------------------


def test_the_footer_control_is_a_real_link(client):
    body = client.get("/app/trips").text
    assert 'href="/app/cookie-preferences"' in body
    assert 'id="footer-link-cookie_preferences"' in body


def test_the_trigger_and_the_dialog_carry_a_paired_state(client):
    body = client.get("/app/trips").text
    assert 'aria-expanded="false"' in body
    assert 'aria-controls="cookie-preferences-dialog"' in body
    assert 'aria-haspopup="dialog"' in body
    assert 'id="cookie-preferences-dialog"' in body
    assert 'aria-hidden="true"' in body


def test_the_dialog_is_labelled_and_modal(client):
    body = client.get("/app/trips").text
    assert 'role="dialog"' in body
    assert 'aria-modal="true"' in body
    assert 'aria-labelledby="cookie-preferences-dialog-title"' in body
    assert 'id="cookie-preferences-dialog-title"' in body


def test_the_dialog_contains_the_same_form_the_page_posts(client):
    body = client.get("/app/trips").text
    assert 'action="/app/cookie-preferences"' in body
    assert "data-dialog-close" in body


def test_the_overlay_handler_implements_the_overlay_contract():
    source = SHELL_JS.read_text(encoding="utf-8")
    # escape closes, tab is trapped, focus is restored to the opener, and a
    # modifier-click is left to the browser so the real page still opens.
    assert '"Escape"' in source
    assert "trapTab" in source
    assert "dialogOpener.focus()" in source
    assert "modifierClick" in source
    assert 'setAttribute("aria-hidden", "false")' in source
    assert 'setAttribute("aria-expanded", "true")' in source
