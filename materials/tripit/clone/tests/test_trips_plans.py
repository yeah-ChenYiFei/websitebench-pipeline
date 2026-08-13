"""Trips CRUD + plan edit tests for the TripIt offline clone (Phase 6).

Exercises the authenticated, server-authoritative surfaces layered on top of the
seeded itinerary truth: creating / editing / deleting trips, editing and
deleting plans across all twelve plan types, the anchored "add the Hilton
Midtown stay to the existing New York trip" journey end to end, form-level
validation, three-level idempotency, and cross-account isolation (foreign
resources 404 without disclosing existence). The anchor journey must join the
existing trip and must never create a trip as a side effect.
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

# Own throwaway data dir, pinned before import so the backend resolves its single
# sqlite file inside it (and re-pinned per test when collected with sibling suites).
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-trips-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"
HOTEL = "New York Hilton Midtown"
CONFIRMATION = "4482210417"
CHECK_IN = "2027-05-23"
CHECK_OUT = "2027-05-26"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_trips_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
PLAN_TYPES = list(app_module.PLAN_TYPE_LABELS.keys())


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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sign_in(client: TestClient, email: str = "traveler@example.com"):
    return client.post(
        LOGIN_URL,
        data={"login_email_address": email, "login_password": PASSWORDS[email]},
        follow_redirects=False,
    )


def owner_for(subject: str = "traveler") -> str:
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, subject)


def ny_trip_id(owner: str) -> str:
    with closing(db.connect()) as connection:
        trips = db.list_trips(connection, owner, "upcoming")
    return next(t["trip_id"] for t in trips if t["name"] == "New York")


def trip_count(owner: str) -> int:
    with closing(db.connect()) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM tripit_trips WHERE owner_key=?", (owner,)
        ).fetchone()[0]


def plan_count(owner: str, trip_id: str | None) -> int:
    with closing(db.connect()) as connection:
        if trip_id is None:
            return connection.execute(
                "SELECT COUNT(*) FROM tripit_plans WHERE owner_key=? AND trip_id IS NULL",
                (owner,),
            ).fetchone()[0]
        return connection.execute(
            "SELECT COUNT(*) FROM tripit_plans WHERE owner_key=? AND trip_id=?",
            (owner, trip_id),
        ).fetchone()[0]


def hilton_plans(owner: str, trip_id: str) -> int:
    with closing(db.connect()) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM tripit_plans "
            "WHERE owner_key=? AND trip_id=? AND title=? AND status='active'",
            (owner, trip_id, HOTEL),
        ).fetchone()[0]


def pro_subscription_count() -> int:
    with closing(db.connect()) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM tripit_pro_subscriptions"
        ).fetchone()[0]


def create_trip(
    client: TestClient,
    *,
    name: str = "Paris",
    destination: str = "Paris, France",
    start_date: str = "2027-08-10",
    end_date: str = "2027-08-14",
    timezone: str = "Europe/Paris",
    key: str = "trip-create-1",
):
    return client.post(
        "/trips",
        data={
            "name": name,
            "destination": destination,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": timezone,
            "idempotency_key": key,
        },
        follow_redirects=False,
    )


def created_trip_id(response) -> str:
    location = response.headers.get("location", "")
    assert location.startswith("/trips/"), location
    return location.split("/trips/", 1)[1]


# ---------------------------------------------------------------------------
# trip create
# ---------------------------------------------------------------------------


def test_new_trip_form_requires_auth(client):
    resp = client.get("/trips/new", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/account/login"


def test_new_trip_form_is_not_shadowed_by_trip_detail(client):
    # `/trips/new` must resolve to the create form, not `/trips/{trip_id="new"}`.
    sign_in(client)
    resp = client.get("/trips/new")
    assert resp.status_code == 200
    assert "Add Trip" in resp.text
    assert "plans@tripit.com" in resp.text
    assert "Trip Description" in resp.text
    assert 'name="name"' in resp.text


def test_trip_form_uses_the_authenticated_app_shell_and_english_date_fields(client):
    sign_in(client)
    for path in ("/trips/new", "/app/trip/create"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200
        assert 'href="/app/assets/app-DU16U4UP.css"' in response.text
        assert 'href="/static/site/css/app-trip-form.css"' in response.text
        assert 'id="trip-start-date"' in response.text
        assert 'id="trip-end-date"' in response.text
        assert 'placeholder="YYYY-MM-DD"' in response.text
        assert 'type="date"' not in response.text

    app_form = client.get("/app/trip/create")
    assert 'name="return_to_app" value="1"' in app_form.text


def test_app_trip_create_returns_to_the_app_timeline(client):
    sign_in(client)
    response = client.post(
        "/trips",
        data={
            "name": "App trip",
            "destination": "Chicago, IL",
            "start_date": "2027-08-10",
            "end_date": "2027-08-14",
            "timezone": "America/Chicago",
            "idempotency_key": "app-trip-create-1",
            "return_to_app": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/trips/")
    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    assert "App trip" in detail.text


def test_create_trip_happy_path(client):
    sign_in(client)
    owner = owner_for()
    before = trip_count(owner)
    resp = create_trip(client)
    assert resp.status_code == 303
    trip_id = created_trip_id(resp)
    assert trip_count(owner) == before + 1
    detail = client.get(f"/trips/{trip_id}")
    assert detail.status_code == 200
    assert "Paris" in detail.text
    listing = client.get("/trips?tab=upcoming")
    assert "Paris" in listing.text


def test_create_trip_anonymous_rejected(client):
    owner = owner_for()
    before = trip_count(owner)
    resp = create_trip(client)  # not signed in
    assert resp.status_code == 303
    assert resp.headers["location"] == "/account/login"
    assert trip_count(owner) == before


def test_create_trip_rejects_reversed_dates(client):
    sign_in(client)
    owner = owner_for()
    before = trip_count(owner)
    resp = create_trip(client, start_date="2027-08-14", end_date="2027-08-10")
    assert resp.status_code == 400
    assert trip_count(owner) == before


def test_create_trip_requires_name(client):
    sign_in(client)
    owner = owner_for()
    before = trip_count(owner)
    resp = create_trip(client, name="")
    assert resp.status_code == 400
    assert trip_count(owner) == before


def test_create_trip_rejects_bad_timezone(client):
    sign_in(client)
    owner = owner_for()
    before = trip_count(owner)
    resp = create_trip(client, timezone="Mars/Phobos")
    assert resp.status_code == 400
    assert trip_count(owner) == before


def test_create_trip_idempotent_on_key(client):
    sign_in(client)
    owner = owner_for()
    before = trip_count(owner)
    first = create_trip(client, key="dup-key")
    second = create_trip(client, key="dup-key")
    assert first.status_code == 303 and second.status_code == 303
    assert created_trip_id(first) == created_trip_id(second)
    assert trip_count(owner) == before + 1


def test_create_trip_slug_collision_disambiguated(client):
    sign_in(client)
    owner = owner_for()
    a = create_trip(client, name="Reunion", destination="", key="k1")
    b = create_trip(client, name="Reunion", destination="", key="k2")
    assert created_trip_id(a) != created_trip_id(b)
    with closing(db.connect()) as connection:
        slugs = [
            r["slug"]
            for r in connection.execute(
                "SELECT slug FROM tripit_trips WHERE owner_key=? AND name='Reunion' "
                "ORDER BY slug",
                (owner,),
            ).fetchall()
        ]
    assert slugs == ["reunion", "reunion-2"]


# ---------------------------------------------------------------------------
# trip edit / delete
# ---------------------------------------------------------------------------


def test_edit_trip_updates_fields_and_keeps_slug(client):
    sign_in(client)
    owner = owner_for()
    trip_id = created_trip_id(create_trip(client, key="edit-seed"))
    with closing(db.connect()) as connection:
        slug_before = db.get_trip(connection, owner, trip_id)["slug"]
    resp = client.post(
        f"/trips/{trip_id}/edit",
        data={
            "name": "Paris Redux",
            "destination": "Paris, FR",
            "start_date": "2027-08-11",
            "end_date": "2027-08-15",
            "timezone": "Europe/Paris",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with closing(db.connect()) as connection:
        trip = db.get_trip(connection, owner, trip_id)
    assert trip["name"] == "Paris Redux"
    assert trip["start_date"] == "2027-08-11"
    assert trip["slug"] == slug_before  # stable across rename


def test_edit_trip_rejects_reversed_dates(client):
    sign_in(client)
    trip_id = created_trip_id(create_trip(client, key="edit-bad"))
    resp = client.post(
        f"/trips/{trip_id}/edit",
        data={
            "name": "Paris",
            "destination": "",
            "start_date": "2027-08-15",
            "end_date": "2027-08-11",
            "timezone": "Europe/Paris",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_edit_trip_foreign_is_not_found(client):
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    other = TestClient(app, base_url="https://testserver")
    sign_in(other, "other@example.com")
    form = other.get(f"/trips/{trip_id}/edit", follow_redirects=False)
    assert form.status_code == 404
    post = other.post(
        f"/trips/{trip_id}/edit",
        data={
            "name": "Hijacked",
            "destination": "",
            "start_date": "2027-05-22",
            "end_date": "2027-05-27",
            "timezone": "America/New_York",
        },
        follow_redirects=False,
    )
    assert post.status_code == 404
    with closing(db.connect()) as connection:
        assert db.get_trip(connection, owner, trip_id)["name"] == "New York"


def test_delete_trip_cascades_plans(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    assert plan_count(owner, trip_id) > 0
    resp = client.post(f"/trips/{trip_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/trips"
    assert client.get(f"/trips/{trip_id}").status_code == 404
    assert plan_count(owner, trip_id) == 0


def test_delete_trip_foreign_is_not_found(client):
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    other = TestClient(app, base_url="https://testserver")
    sign_in(other, "other@example.com")
    resp = other.post(f"/trips/{trip_id}/delete", follow_redirects=False)
    assert resp.status_code == 404
    with closing(db.connect()) as connection:
        assert db.get_trip(connection, owner, trip_id)["name"] == "New York"


# ---------------------------------------------------------------------------
# plan add / edit across every plan type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plan_type", PLAN_TYPES)
def test_add_each_plan_type_via_route(client, plan_type):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    form = client.get(f"/trips/{trip_id}/add/{plan_type}")
    assert form.status_code == 200
    if plan_type == "lodging":
        data = {
            "plan_type": "lodging",
            "idempotency_key": f"add-{plan_type}",
            "title": HOTEL,
            "check_in_date": CHECK_IN,
            "check_out_date": CHECK_OUT,
            "confirmation": CONFIRMATION,
        }
    else:
        data = {
            "plan_type": plan_type,
            "idempotency_key": f"add-{plan_type}",
            "title": f"{plan_type} entry",
        }
    resp = client.post(f"/trips/{trip_id}/plans", data=data, follow_redirects=False)
    assert resp.status_code == 303
    with closing(db.connect()) as connection:
        rows = connection.execute(
            "SELECT 1 FROM tripit_plans WHERE owner_key=? AND trip_id=? "
            "AND plan_type=? AND status='active'",
            (owner, trip_id, plan_type),
        ).fetchall()
    assert len(rows) >= 1


@pytest.mark.parametrize("plan_type", [t for t in PLAN_TYPES if t != "lodging"])
def test_edit_each_nonlodging_plan_type(client, plan_type):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    seeded = db.add_plan(
        owner,
        trip_id=trip_id,
        plan_type=plan_type,
        title=f"{plan_type} original",
    )
    plan_id = seeded["plan_id"]
    form = client.get(f"/plans/{plan_id}/edit")
    assert form.status_code == 200
    assert f"{plan_type} original" in form.text
    resp = client.post(
        f"/plans/{plan_id}/edit",
        data={
            "title": f"{plan_type} revised",
            "start_date": "",
            "start_time": "",
            "end_date": "",
            "end_time": "",
            "notes": "updated note",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with closing(db.connect()) as connection:
        plan = db.get_plan(connection, owner, plan_id)
    assert plan["title"] == f"{plan_type} revised"
    assert plan["details"].get("notes") == "updated note"


def test_edit_lodging_plan_prefills_and_updates(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    add = client.post(
        f"/trips/{trip_id}/plans",
        data={
            "plan_type": "lodging",
            "idempotency_key": "lodging-edit-seed",
            "title": HOTEL,
            "check_in_date": CHECK_IN,
            "check_out_date": CHECK_OUT,
            "confirmation": CONFIRMATION,
        },
        follow_redirects=False,
    )
    assert add.status_code == 303
    with closing(db.connect()) as connection:
        plan_id = connection.execute(
            "SELECT plan_id FROM tripit_plans WHERE owner_key=? AND trip_id=? "
            "AND plan_type='lodging'",
            (owner, trip_id),
        ).fetchone()["plan_id"]
    form = client.get(f"/plans/{plan_id}/edit")
    assert form.status_code == 200
    assert HOTEL in form.text
    assert CHECK_IN in form.text and CONFIRMATION in form.text
    resp = client.post(
        f"/plans/{plan_id}/edit",
        data={
            "title": HOTEL,
            "check_in_date": "2027-05-24",
            "check_out_date": "2027-05-26",
            "confirmation": "9990001112",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    detail = client.get(f"/trips/{trip_id}")
    assert "9990001112" in detail.text
    with closing(db.connect()) as connection:
        plan = db.get_plan(connection, owner, plan_id)
    assert plan["details"]["check_in_date"] == "2027-05-24"


def test_edit_lodging_rejects_reversed_dates(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    seeded = db.add_plan(
        owner,
        trip_id=trip_id,
        plan_type="lodging",
        title=HOTEL,
        details={"check_in_date": CHECK_IN, "check_out_date": CHECK_OUT},
        natural_key="lodging:test:edit",
    )
    resp = client.post(
        f"/plans/{seeded['plan_id']}/edit",
        data={
            "title": HOTEL,
            "check_in_date": CHECK_OUT,
            "check_out_date": CHECK_IN,
            "confirmation": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_edit_plan_foreign_is_not_found(client):
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    seeded = db.add_plan(
        owner, trip_id=trip_id, plan_type="activity", title="Owner-only activity"
    )
    other = TestClient(app, base_url="https://testserver")
    sign_in(other, "other@example.com")
    assert other.get(f"/plans/{seeded['plan_id']}/edit").status_code == 404
    resp = other.post(
        f"/plans/{seeded['plan_id']}/edit",
        data={"title": "hijack", "notes": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 404
    with closing(db.connect()) as connection:
        assert (
            db.get_plan(connection, owner, seeded["plan_id"])["title"]
            == "Owner-only activity"
        )


def test_edit_unfiled_plan_returns_to_unfiled(client):
    sign_in(client)
    owner = owner_for()
    seeded = db.add_plan(
        owner, trip_id=None, plan_type="note", title="Loose note"
    )
    form = client.get(f"/plans/{seeded['plan_id']}/edit")
    assert form.status_code == 200
    assert "Unfiled Items" in form.text
    resp = client.post(
        f"/plans/{seeded['plan_id']}/edit",
        data={"title": "Filed-away note", "notes": "n"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/trips?tab=unfiled"
    with closing(db.connect()) as connection:
        assert db.get_plan(connection, owner, seeded["plan_id"])["title"] == "Filed-away note"


# ---------------------------------------------------------------------------
# anchor journey — add the Hilton stay to the *existing* New York trip
# ---------------------------------------------------------------------------


def test_anchor_journey_joins_existing_trip_without_creating_one(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    trips_before = trip_count(owner)

    detail = client.get(f"/trips/{trip_id}")
    assert "United 512" in detail.text  # seeded flight is present
    assert "Add a hotel" in detail.text

    resp = client.post(
        f"/trips/{trip_id}/plans",
        data={
            "plan_type": "lodging",
            "idempotency_key": "anchor-journey",
            "title": HOTEL,
            "check_in_date": CHECK_IN,
            "check_out_date": CHECK_OUT,
            "confirmation": CONFIRMATION,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/trips/{trip_id}"

    # No new trip was created — the reservation joined the seeded trip.
    assert trip_count(owner) == trips_before

    after = client.get(f"/trips/{trip_id}")
    assert HOTEL in after.text
    assert "Check-in" in after.text and "Check-out" in after.text
    assert CONFIRMATION in after.text

    # The reservation path is free-tier: it never touches Pro/payment state.
    assert pro_subscription_count() == 0


def test_anchor_journey_is_idempotent_on_resubmit(client):
    # A double submit (same idempotency key) files exactly one Hilton stay — the
    # traveler double-clicking "Add" must not create two reservations.
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    before = plan_count(owner, trip_id)

    payload = {
        "plan_type": "lodging",
        "idempotency_key": "anchor-journey",
        "title": HOTEL,
        "check_in_date": CHECK_IN,
        "check_out_date": CHECK_OUT,
        "confirmation": CONFIRMATION,
    }
    first = client.post(f"/trips/{trip_id}/plans", data=payload, follow_redirects=False)
    second = client.post(f"/trips/{trip_id}/plans", data=payload, follow_redirects=False)
    assert first.status_code == 303 and second.status_code == 303

    assert plan_count(owner, trip_id) == before + 1
    assert hilton_plans(owner, trip_id) == 1


def test_anchor_journey_survives_restart(client):
    # The stay is persisted in the single on-disk sqlite file, so a fresh
    # "process" over the same data dir still serves it after the trip is saved.
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    client.post(
        f"/trips/{trip_id}/plans",
        data={
            "plan_type": "lodging",
            "idempotency_key": "anchor-journey",
            "title": HOTEL,
            "check_in_date": CHECK_IN,
            "check_out_date": CHECK_OUT,
            "confirmation": CONFIRMATION,
        },
        follow_redirects=False,
    )
    with TestClient(app, base_url="https://testserver") as reborn:
        sign_in(reborn)
        after = reborn.get(f"/trips/{trip_id}")
    assert after.status_code == 200
    assert HOTEL in after.text
    assert CONFIRMATION in after.text
    assert hilton_plans(owner, trip_id) == 1


def test_anchor_journey_is_invisible_to_other_travelers(client):
    # After the owner adds the stay, a different account cannot see the trip or
    # the reservation, and the 404 does not disclose that the trip exists.
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    client.post(
        f"/trips/{trip_id}/plans",
        data={
            "plan_type": "lodging",
            "idempotency_key": "anchor-journey",
            "title": HOTEL,
            "check_in_date": CHECK_IN,
            "check_out_date": CHECK_OUT,
            "confirmation": CONFIRMATION,
        },
        follow_redirects=False,
    )
    fresh = TestClient(app, base_url="https://testserver")
    sign_in(fresh, "other@example.com")
    denied = fresh.get(f"/trips/{trip_id}")
    assert denied.status_code == 404
    assert HOTEL not in denied.text
