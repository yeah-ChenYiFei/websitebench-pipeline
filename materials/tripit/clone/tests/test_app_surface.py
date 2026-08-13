"""The logged-in /app/* surface: liveness, ownership, and write semantics.

Every path exercised here is one the live app links to. They were previously
unregistered, so the whole signed-in surface offered controls that answered 404;
this module pins that each one now resolves, that it resolves only for the
account that owns the row behind it, and that the writes it exposes follow the
same rules as the rest of the backend: authentication required, ownership taken
from the session rather than from a request parameter, enums checked against a
named constant, POST answered with a redirect, and a foreign id answered with a
404 that discloses nothing.

Cookie Preferences and the chrome's boundary destinations have their own
modules, ``test_cookie_preferences.py`` and ``test_content_boundary.py``.
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

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-app-surface-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_app_surface_tests")
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
        LOGIN_URL,
        data={"login_email_address": email, "login_password": PASSWORDS[email]},
        follow_redirects=False,
    )
    assert response.status_code == 303, email
    return client


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    yield sign_in(TRAVELER)
    app_module.reset_fixture_state()


def owner_key(email: str) -> str:
    store = app_module.auth_store()
    account = store.account_for_email(email) if hasattr(store, "account_for_email") else None
    if account is not None:
        with closing(db.connect()) as connection:
            return db.owner_for_subject(connection, str(account["subject_id"]))
    # Fall back to the fixture's own owner key when the store exposes no lookup.
    signed = sign_in(email)
    token = signed.cookies.get(SESSION_COOKIE)
    resolved = app_module.auth_store().resolve_session(token)
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, str(resolved["account"]["subject_id"]))


def first_trip(email: str) -> dict:
    with closing(db.connect()) as connection:
        trips = db.list_trips(connection, owner_key(email), "upcoming")
    assert trips, email
    return trips[0]


def public_trip_id(trip: dict) -> str:
    return app_module._app_uuid(trip["trip_id"], 1)


def first_plan(email: str, trip: dict) -> dict:
    with closing(db.connect()) as connection:
        plans = db.list_plans_for_trip(connection, owner_key(email), trip["trip_id"])
    assert plans, trip["trip_id"]
    return plans[0]


def plan_locator(plan: dict) -> tuple[str, str]:
    return (
        app_module._APP_PLAN_PATH[plan["plan_type"]],
        app_module._app_plan_uuid(plan),
    )


# ---------------------------------------------------------------------------
# liveness: every linked /app path answers
# ---------------------------------------------------------------------------


def test_shell_destinations_answer(client):
    for path in (
        "/app/trips",
        "/app/account/profile",
        "/app/settings/notifications",
        "/app/logout",
        "/app/trip/create",
        "/app/cookie-preferences",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code in (200, 303), (path, response.status_code)


def test_requested_tripit_navigation_and_help_center_surfaces(client):
    trips = client.get("/app/trips")
    assert trips.status_code == 200
    assert "Support" in trips.text
    assert 'href="/en/support/home"' in trips.text
    assert 'href="/web/pro"' in trips.text

    help_home = client.get("/en/support/home")
    assert help_home.status_code == 200
    assert "Hi, how can we help you?" in help_home.text
    assert "TripIt Help Center (8)" in help_home.text
    assert "Account, Email, Settings" in help_home.text

    article = client.get(
        "/en/support/solutions/articles/103000063431-add-a-new-trip-on-the-tripit-website"
    )
    assert article.status_code == 200
    assert "Add a new trip on the TripIt website" in article.text


def test_requested_add_trip_layout_and_unfiled_empty_state(client):
    add_trip = client.get("/app/trip/create")
    assert add_trip.status_code == 200
    assert "Add a trip manually below" in add_trip.text
    assert "plans@tripit.com" in add_trip.text
    assert "Trip Description" in add_trip.text
    assert "/images/places/themes/generic.jpg?res=2x" in add_trip.text
    assert "Change Photo" in add_trip.text

    unfiled = client.get("/app/trips?trips_filter=unassigned")
    assert unfiled.status_code == 200
    assert "No unfiled items" in unfiled.text
    assert 'id="add-trip-button"' not in unfiled.text


def test_requested_pro_and_social_destinations(client):
    pro = client.get("/web/pro")
    assert pro.status_code == 200
    assert 'href="/app/account/billing"' in pro.text

    billing = client.get("/app/account/billing")
    assert billing.status_code == 200

    shell = client.get("/app/trips").text
    for destination in (
        "https://www.instagram.com/tripitcom",
        "https://www.facebook.com/tripitcom",
        "https://twitter.com/TripIt",
        "https://www.linkedin.com/company/tripit",
        "https://www.youtube.com/user/tripitvideos",
    ):
        assert f'href="{destination}"' in shell


def test_trip_destinations_answer(client):
    public_id = public_trip_id(first_trip(TRAVELER))
    for suffix in ("", "/edit", "/sharing", "/print", "/cost"):
        response = client.get(f"/app/trips/{public_id}{suffix}", follow_redirects=False)
        assert response.status_code in (200, 303), (suffix, response.status_code)


def test_trip_detail_keeps_the_source_timeline_menu_and_english_date_label(client):
    public_id = public_trip_id(first_trip(TRAVELER))
    response = client.get(f"/app/trips/{public_id}")
    assert response.status_code == 200
    assert '/static/site/css/app-trip-timeline.css' in response.text
    assert client.get("/static/site/css/app-trip-timeline.css").status_code == 200
    assert 'data-cy="trip-timeline-section-header"' in response.text
    assert 'data-cy="create-plan-dropdown"' in response.text
    assert 'class="dropdown-menu overflow-auto custom-plans-dropdown px-2 py-2"' in response.text
    assert 'data-cy="plan-button-activity"' in response.text
    assert 'data-cy="plan-button-transportation"' in response.text

    date_span = re.search(
        r'data-cy="trip-date-span"><span class="p-0">([^<]+)</span>', response.text
    )
    assert date_span is not None
    assert " day" in date_span.group(1)
    assert "天" not in date_span.group(1)


def test_dropdown_script_uses_source_show_state_and_live_viewport_positioning():
    script = (CLONE_DIR / "static/site/js/app-ui.js").read_text(encoding="utf-8")
    assert 'menu.classList.toggle("show", open);' in script
    assert 'menu.style.position = "fixed";' in script
    assert 'menu.style.transform = "none";' in script


def test_every_add_plan_menu_destination_answers(client):
    public_id = public_trip_id(first_trip(TRAVELER))
    for segment in app_module._APP_CREATE_PLAN_TYPE:
        response = client.get(
            f"/app/trips/{public_id}/{segment}/create", follow_redirects=False
        )
        assert response.status_code == 303, segment
        assert response.headers["location"].startswith("/trips/"), segment


def test_menu_type_refinements_reach_the_right_form(client):
    public_id = public_trip_id(first_trip(TRAVELER))
    response = client.get(
        f"/app/trips/{public_id}/activity/create?type=meeting", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/add/meeting")


def test_an_unknown_type_refinement_is_not_widened_to_the_base_form(client):
    public_id = public_trip_id(first_trip(TRAVELER))
    response = client.get(
        f"/app/trips/{public_id}/activity/create?type=not-a-thing",
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_plan_destinations_answer(client):
    trip = first_trip(TRAVELER)
    plan = first_plan(TRAVELER, trip)
    path, plan_public = plan_locator(plan)
    base = f"/app/trips/{public_trip_id(trip)}/{path}/{plan_public}"
    for suffix in ("", "/edit", "/move", "/copy"):
        response = client.get(base + suffix, follow_redirects=False)
        assert response.status_code in (200, 303), (suffix, response.status_code)


def test_plan_detail_rejects_a_mismatched_type_segment(client):
    trip = first_trip(TRAVELER)
    plan = first_plan(TRAVELER, trip)
    _, plan_public = plan_locator(plan)
    wrong = "note" if plan["plan_type"] != "note" else "map"
    response = client.get(
        f"/app/trips/{public_trip_id(trip)}/{wrong}/{plan_public}",
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_trips_filter_is_accepted_as_the_sources_own_tab_name(client):
    for query, expected in (
        ("your_upcoming", "upcoming-your"),
        ("others_upcoming", "upcoming-others"),
        ("past", "past"),
        ("unassigned", "unfiled"),
    ):
        response = client.get(f"/app/trips?trips_filter={query}&page=1")
        assert response.status_code == 200, query
        assert f'trips-list-tab-{expected}' in response.text, query


# ---------------------------------------------------------------------------
# authentication and ownership
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/app/trips",
        "/app/account/profile",
        "/app/settings/notifications",
        "/app/trip/create",
    ],
)
def test_signed_out_visitors_are_sent_to_sign_in(path):
    app_module.reset_fixture_state()
    anonymous = TestClient(app, base_url="https://testserver")
    response = anonymous.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == LOGIN_URL


def test_another_accounts_trip_is_a_404_that_discloses_nothing(client):
    app_module.reset_fixture_state()
    mine = sign_in(TRAVELER)
    theirs = public_trip_id(first_trip(OTHER))
    real = mine.get(f"/app/trips/{theirs}", follow_redirects=False)
    invented = mine.get(
        "/app/trips/00000000-0000-9000-0001-000000000000", follow_redirects=False
    )
    assert real.status_code == invented.status_code == 404
    assert real.text == invented.text


@pytest.mark.parametrize("suffix", ["/edit", "/sharing", "/print", "/cost"])
def test_another_accounts_trip_surfaces_are_404(client, suffix):
    app_module.reset_fixture_state()
    mine = sign_in(TRAVELER)
    theirs = public_trip_id(first_trip(OTHER))
    assert mine.get(f"/app/trips/{theirs}{suffix}", follow_redirects=False).status_code == 404


def test_a_foreign_plan_cannot_be_deleted_through_the_app_surface():
    app_module.reset_fixture_state()
    their_trip = first_trip(OTHER)
    their_plan = first_plan(OTHER, their_trip)
    path, plan_public = plan_locator(their_plan)
    mine = sign_in(TRAVELER)
    response = mine.post(
        f"/app/trips/{public_trip_id(their_trip)}/{path}/{plan_public}/delete",
        follow_redirects=False,
    )
    assert response.status_code == 404
    with closing(db.connect()) as connection:
        still_there = db.get_plan(connection, owner_key(OTHER), their_plan["plan_id"])
    assert still_there["plan_id"] == their_plan["plan_id"]


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def test_delete_plan_removes_it_and_redirects_back_to_the_trip(client):
    trip = first_trip(TRAVELER)
    plan = first_plan(TRAVELER, trip)
    path, plan_public = plan_locator(plan)
    public_id = public_trip_id(trip)
    response = client.post(
        f"/app/trips/{public_id}/{path}/{plan_public}/delete", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/app/trips/{public_id}"
    with closing(db.connect()) as connection:
        remaining = db.list_plans_for_trip(connection, owner_key(TRAVELER), trip["trip_id"])
    assert plan["plan_id"] not in [row["plan_id"] for row in remaining]


def test_copy_plan_duplicates_it_onto_the_chosen_trip(client):
    with closing(db.connect()) as connection:
        trips = db.list_trips(connection, owner_key(TRAVELER), "upcoming")
    assert len(trips) >= 2, "seed needs two upcoming trips to exercise a copy"
    source, target = trips[0], trips[1]
    plan = first_plan(TRAVELER, source)
    path, plan_public = plan_locator(plan)

    form = client.get(
        f"/app/trips/{public_trip_id(source)}/{path}/{plan_public}/copy"
    )
    assert form.status_code == 200
    assert target["name"] in form.text

    response = client.post(
        f"/app/trips/{public_trip_id(source)}/{path}/{plan_public}/copy",
        data={"trip_id": target["trip_id"], "form_token": "copy-token-1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with closing(db.connect()) as connection:
        owner = owner_key(TRAVELER)
        assert plan["plan_id"] in [
            row["plan_id"] for row in db.list_plans_for_trip(connection, owner, source["trip_id"])
        ]
        copied = [
            row
            for row in db.list_plans_for_trip(connection, owner, target["trip_id"])
            if row["title"] == plan["title"]
        ]
    assert copied, "the copy did not land on the target trip"


def test_copying_twice_with_the_same_token_does_not_duplicate(client):
    with closing(db.connect()) as connection:
        trips = db.list_trips(connection, owner_key(TRAVELER), "upcoming")
    source, target = trips[0], trips[1]
    plan = first_plan(TRAVELER, source)
    path, plan_public = plan_locator(plan)
    url = f"/app/trips/{public_trip_id(source)}/{path}/{plan_public}/copy"
    payload = {"trip_id": target["trip_id"], "form_token": "copy-token-replay"}

    client.post(url, data=payload, follow_redirects=False)
    client.post(url, data=payload, follow_redirects=False)

    with closing(db.connect()) as connection:
        landed = [
            row
            for row in db.list_plans_for_trip(connection, owner_key(TRAVELER), target["trip_id"])
            if row["title"] == plan["title"]
        ]
    assert len(landed) == 1


def test_copy_rejects_a_trip_the_caller_does_not_own(client):
    app_module.reset_fixture_state()
    mine = sign_in(TRAVELER)
    my_trip = first_trip(TRAVELER)
    plan = first_plan(TRAVELER, my_trip)
    path, plan_public = plan_locator(plan)
    their_trip = first_trip(OTHER)
    response = mine.post(
        f"/app/trips/{public_trip_id(my_trip)}/{path}/{plan_public}/copy",
        data={"trip_id": their_trip["trip_id"], "form_token": "copy-cross"},
        follow_redirects=False,
    )
    assert response.status_code == 404
    with closing(db.connect()) as connection:
        theirs = db.list_plans_for_trip(connection, owner_key(OTHER), their_trip["trip_id"])
    assert plan["title"] not in [row["title"] for row in theirs]


def test_move_plan_relocates_it(client):
    with closing(db.connect()) as connection:
        trips = db.list_trips(connection, owner_key(TRAVELER), "upcoming")
    source, target = trips[0], trips[1]
    plan = first_plan(TRAVELER, source)
    path, plan_public = plan_locator(plan)
    response = client.post(
        f"/app/trips/{public_trip_id(source)}/{path}/{plan_public}/move",
        data={"trip_id": target["trip_id"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with closing(db.connect()) as connection:
        moved = db.get_plan(connection, owner_key(TRAVELER), plan["plan_id"])
    assert moved["trip_id"] == target["trip_id"]


def test_move_to_unfiled_is_accepted(client):
    trip = first_trip(TRAVELER)
    plan = first_plan(TRAVELER, trip)
    path, plan_public = plan_locator(plan)
    response = client.post(
        f"/app/trips/{public_trip_id(trip)}/{path}/{plan_public}/move",
        data={"trip_id": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with closing(db.connect()) as connection:
        moved = db.get_plan(connection, owner_key(TRAVELER), plan["plan_id"])
    assert moved["trip_id"] is None


# ---------------------------------------------------------------------------
# sign out
# ---------------------------------------------------------------------------


def test_the_sign_out_link_does_not_end_the_session_on_a_get(client):
    page = client.get("/app/logout")
    assert page.status_code == 200
    assert 'action="/app/logout"' in page.text
    assert client.get("/trips", follow_redirects=False).status_code == 200


def test_posting_the_sign_out_form_ends_the_session(client):
    response = client.post("/app/logout", follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/trips", follow_redirects=False).status_code == 303
