"""Read-only surfaces the app menus point at: plan details, print, cost, alerts.

These four pages had no route at all before, so the menu items that name them
answered 404. Each is owner-scoped and renders from the same seeded truth as the
timeline. Two of them also carry a stated boundary — trip cost has no amounts to
total, and notifications has no delivery channels — and the tests below pin that
those boundaries are stated rather than papered over with a fabricated zero or a
switch that changes nothing.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-plan-surface-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_plan_surface_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app
SESSION_COOKIE = app_module.SESSION_COOKIE

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
TRAVELER = "traveler@example.com"
OTHER = "other@example.com"


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


def sign_in(email: str) -> TestClient:
    client = TestClient(app, base_url="https://testserver")
    response = client.post(
        "/account/login",
        data={"login_email_address": email, "login_password": PASSWORDS[email]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


def owner_key(email: str) -> str:
    signed = sign_in(email)
    resolved = app_module.auth_store().resolve_session(signed.cookies.get(SESSION_COOKIE))
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, str(resolved["account"]["subject_id"]))


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    yield sign_in(TRAVELER)
    app_module.reset_fixture_state()


def trip_and_plan(email: str = TRAVELER):
    owner = owner_key(email)
    with closing(db.connect()) as connection:
        trip = db.list_trips(connection, owner, "upcoming")[0]
        plans = db.list_plans_for_trip(connection, owner, trip["trip_id"])
    return trip, plans[0], plans


def locate(trip, plan) -> str:
    return (
        f"/app/trips/{app_module._app_uuid(trip['trip_id'], 1)}"
        f"/{app_module._APP_PLAN_PATH[plan['plan_type']]}"
        f"/{app_module._app_plan_uuid(plan)}"
    )


# ---------------------------------------------------------------------------
# plan details
# ---------------------------------------------------------------------------


def test_plan_details_render_the_plan(client):
    trip, plan, _ = trip_and_plan()
    response = client.get(locate(trip, plan))
    assert response.status_code == 200
    assert plan["title"] in response.text
    assert app_module.PLAN_TYPE_LABELS[plan["plan_type"]] in response.text


def test_plan_details_offer_the_actions_the_menu_names(client):
    trip, plan, _ = trip_and_plan()
    body = client.get(locate(trip, plan)).text
    for action in ("/edit", "/move", "/copy", "/delete"):
        assert action in body, action


def test_plan_details_show_stored_detail_values(client):
    owner = owner_key(TRAVELER)
    with closing(db.connect()) as connection:
        trip = db.list_trips(connection, owner, "upcoming")[0]
        plans = db.list_plans_for_trip(connection, owner, trip["trip_id"])
    with_details = [p for p in plans if p.get("details")]
    if not with_details:
        pytest.skip("no seeded plan carries details on this trip")
    plan = with_details[0]
    body = client.get(locate(trip, plan)).text
    for value in plan["details"].values():
        if isinstance(value, str) and value:
            assert value in body
            break


def test_plan_details_are_owner_scoped(client):
    app_module.reset_fixture_state()
    their_trip, their_plan, _ = trip_and_plan(OTHER)
    mine = sign_in(TRAVELER)
    assert mine.get(locate(their_trip, their_plan), follow_redirects=False).status_code == 404


# ---------------------------------------------------------------------------
# printable itinerary
# ---------------------------------------------------------------------------


def test_the_printable_itinerary_lists_every_plan(client):
    trip, _, plans = trip_and_plan()
    body = client.get(f"/app/trips/{app_module._app_uuid(trip['trip_id'], 1)}/print").text
    for plan in plans:
        assert plan["title"] in body, plan["title"]


def test_the_printable_itinerary_names_the_trip(client):
    trip, _, _ = trip_and_plan()
    body = client.get(f"/app/trips/{app_module._app_uuid(trip['trip_id'], 1)}/print").text
    assert trip["name"] in body


def test_the_printable_itinerary_is_owner_scoped(client):
    app_module.reset_fixture_state()
    their_trip, _, _ = trip_and_plan(OTHER)
    mine = sign_in(TRAVELER)
    public_id = app_module._app_uuid(their_trip["trip_id"], 1)
    assert mine.get(f"/app/trips/{public_id}/print", follow_redirects=False).status_code == 404


# ---------------------------------------------------------------------------
# trip cost — a stated boundary, not a fabricated total
# ---------------------------------------------------------------------------


def test_trip_cost_says_no_amounts_are_recorded(client):
    trip, _, _ = trip_and_plan()
    body = client.get(f"/app/trips/{app_module._app_uuid(trip['trip_id'], 1)}/cost").text
    assert "No amounts are recorded" in body
    assert "Not recorded" in body


def test_trip_cost_prints_no_invented_total(client):
    trip, _, _ = trip_and_plan()
    body = client.get(f"/app/trips/{app_module._app_uuid(trip['trip_id'], 1)}/cost").text
    for fabricated in ("$0.00", "0.00", "$0"):
        assert fabricated not in body, fabricated


def test_trip_cost_still_lists_the_plans_a_total_would_be_built_from(client):
    trip, _, plans = trip_and_plan()
    body = client.get(f"/app/trips/{app_module._app_uuid(trip['trip_id'], 1)}/cost").text
    for plan in plans:
        assert plan["title"] in body, plan["title"]


def test_the_data_layer_really_has_no_cost_column():
    """The boundary above is only honest while this stays true."""

    with closing(db.connect()) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tripit_plans)")
        }
    assert not columns & {"cost", "amount_minor", "price", "currency"}


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------


def test_the_notifications_surface_answers_and_states_its_boundary(client):
    response = client.get("/app/settings/notifications")
    assert response.status_code == 200
    assert "Delivery to an email address or a phone is not" in response.text


def test_the_notifications_surface_offers_no_switch_that_changes_nothing(client):
    body = client.get("/app/settings/notifications").text
    assert 'type="checkbox"' not in body
    assert "<select" not in body


def test_notifications_are_owner_scoped(client):
    owner = owner_key(TRAVELER)
    with closing(db.connect()) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO tripit_notifications "
            "(notification_id, owner_key, kind, subject_key, title, body, "
            " dedupe_key, read_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "notification-scoped-probe",
                owner,
                "trip",
                None,
                "Only the owner sees this",
                None,
                "scoped-probe",
                None,
                "2026-08-01T00:00:00Z",
            ),
        )
        connection.commit()
    assert "Only the owner sees this" in client.get("/app/settings/notifications").text
    theirs = sign_in(OTHER)
    assert "Only the owner sees this" not in theirs.get("/app/settings/notifications").text


def test_the_privacy_statements_unsubscribe_link_reaches_that_surface(client):
    response = client.get(
        "/account/edit?section=email_settings", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/app/settings/notifications"
