"""AS-2: every interactive control degrades, and the async ones behave.

Two things are asserted here that a functional test cannot reach.

First, degradation: with scripting off, every control this build ships must
still be a real ``<a href>`` or a real ``<form method="post">``. The tests drive
the server with no JavaScript at all — which is exactly what the test client
does — and check that the destructive and stateful controls still work.

Second, the shape of the async control. The lodging typeahead was an ad-hoc
inline fetch with a timer and nothing else: a slow earlier response could
overwrite a newer one, nothing was announced, and the endpoint was hardcoded in
the markup. It now follows the project's async-control shape, and this module
reads that shape off the shipped module so it cannot quietly regress.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"
TEMPLATES = CLONE_DIR / "frontend" / "templates"
JS_DIR = CLONE_DIR / "static" / "site" / "js"

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-interaction-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_interaction_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

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


def owner() -> str:
    signed = TestClient(app, base_url="https://testserver")
    signed.post(
        "/account/login",
        data={"login_email_address": TRAVELER, "login_password": PASSWORDS[TRAVELER]},
    )
    resolved = app_module.auth_store().resolve_session(
        signed.cookies.get(app_module.SESSION_COOKIE)
    )
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, str(resolved["account"]["subject_id"]))


# ---------------------------------------------------------------------------
# degradation: the controls work with no scripting at all
# ---------------------------------------------------------------------------


def test_the_sign_up_form_submits_without_scripting(client):
    # No script has run: the button ships enabled and the server enforces the
    # agreement, so a scriptless visitor can still create an account.
    body = TestClient(app, base_url="https://testserver").get("/account/create").text
    button = re.search(r"<button[^>]*id=\"signup-submit-btn\"[^>]*>", body)
    assert button is not None
    assert "disabled" not in button.group(0)


def test_the_sign_out_control_is_a_real_form(client):
    assert 'action="/app/logout"' in client.get("/app/logout").text
    assert client.post("/app/logout", follow_redirects=False).status_code == 303


def test_the_plan_actions_menu_ships_real_destinations(client):
    with closing(db.connect()) as connection:
        trip = db.list_trips(connection, owner(), "upcoming")[0]
    public_id = app_module._app_uuid(trip["trip_id"], 1)
    body = client.get(f"/app/trips/{public_id}").text
    # move and copy are links; delete is a form, because it changes state
    assert re.search(r'<a href="/app/trips/[^"]+/move"', body)
    assert re.search(r'<a href="/app/trips/[^"]+/copy"', body)
    assert re.search(r'<form method="post" action="/app/trips/[^"]+/delete"', body)


def test_the_delete_menu_item_is_a_submit_button_not_a_link(client):
    with closing(db.connect()) as connection:
        trip = db.list_trips(connection, owner(), "upcoming")[0]
    public_id = app_module._app_uuid(trip["trip_id"], 1)
    body = client.get(f"/app/trips/{public_id}").text
    assert '<button type="submit" class="dropdown-item" role="menuitem"' in body


def test_the_cookie_dialog_trigger_is_a_real_link(client):
    body = client.get("/app/trips").text
    assert 'href="/app/cookie-preferences"' in body
    # and the page behind it renders the same form
    assert 'action="/app/cookie-preferences"' in client.get("/app/cookie-preferences").text


def test_the_print_control_only_appears_once_scripting_can_serve_it(client):
    with closing(db.connect()) as connection:
        trip = db.list_trips(connection, owner(), "upcoming")[0]
    public_id = app_module._app_uuid(trip["trip_id"], 1)
    body = client.get(f"/app/trips/{public_id}/print").text
    assert "data-print-trigger hidden" in body
    assert "hidden = false" in (JS_DIR / "print-ui.js").read_text(encoding="utf-8")


def test_the_lodging_form_still_offers_suggestions_without_scripting(client):
    with closing(db.connect()) as connection:
        trip = db.list_trips(connection, owner(), "upcoming")[0]
    body = client.get(f"/trips/{trip['trip_id']}/add/lodging").text
    assert '<datalist id="hotel-options">' in body
    assert "New York Hilton Midtown" in body


def test_no_authored_template_ships_a_control_that_goes_nowhere():
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert 'href="#"' not in text, path.name
        assert "javascript:void(0)" not in text, path.name


# ---------------------------------------------------------------------------
# the async control's shape
# ---------------------------------------------------------------------------


def typeahead_source() -> str:
    return (JS_DIR / "typeahead.js").read_text(encoding="utf-8")


def test_the_typeahead_debounces():
    source = typeahead_source()
    assert "setTimeout" in source and "clearTimeout" in source
    assert "DEBOUNCE_MS" in source


def test_the_typeahead_aborts_the_request_it_is_replacing():
    source = typeahead_source()
    assert "AbortController" in source
    assert "request.abort()" in source
    assert "signal: request.signal" in source


def test_the_typeahead_guards_against_an_out_of_order_response():
    source = typeahead_source()
    assert "++sequence" in source
    assert "mine !== sequence" in source


def test_the_typeahead_announces_its_result():
    source = typeahead_source()
    assert "data-typeahead-status" in source
    assert "suggestions available" in source


def test_the_typeahead_endpoint_is_read_from_the_markup_not_hardcoded():
    source = typeahead_source()
    assert 'getAttribute("data-typeahead-endpoint")' in source
    assert "/api/lodging/typeahead" not in source


@pytest.mark.parametrize("template", ["add_plan.html", "edit_plan.html"])
def test_both_lodging_forms_wire_the_shared_module(template):
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    assert 'data-typeahead-endpoint="/api/lodging/typeahead"' in text
    assert 'src="/static/site/js/typeahead.js"' in text
    assert 'aria-live="polite" data-typeahead-status' in text
    # the ad-hoc inline fetch is gone
    assert "fetch('/api/lodging/typeahead" not in text


def test_the_typeahead_endpoint_still_answers_the_shape_the_module_reads(client):
    payload = client.get("/api/lodging/typeahead?q=hil").json()
    assert isinstance(payload.get("results"), list)
    assert payload["results"], "expected the anchor journey's hotel to be suggested"
    assert {"name", "address"} <= set(payload["results"][0])
