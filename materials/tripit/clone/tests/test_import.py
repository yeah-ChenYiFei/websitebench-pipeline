"""Email-import journeys for the TripIt clone.

Email import models TripIt's "forward a confirmation to plans@tripit.com"
pipeline as a deterministic site capability: a forwarded message is parsed by a
pure, offline parser (:mod:`backend.importer`), then filed by
:func:`backend.db.import_email` into the trip whose dates overlap the plan — or
into Unfiled Items when nothing overlaps. These tests pin the behaviour the
blind test depends on:

* every fixture in the library parses to its declared outcome and routes where
  the library says (Hilton -> the seeded New York trip; the July flight/car ->
  Unfiled);
* a reschedule (same confirmation, new body) updates the plan the original
  import created, in place, rather than duplicating it, and a cancellation flips
  that same plan to canceled instead of creating a new one;
* the fingerprint makes a re-forwarded message a first-class ``duplicate`` — no
  second plan, no second receipt mail;
* an unrecognised message is a first-class ``unparseable`` outcome, never an
  exception;
* a plan-affecting import enqueues a simulated ``import-receipt`` to the owner;
* imports are owner-scoped (one traveler's import is invisible to another); and
* the unlinked ``/__sim/inbox`` injector requires a session and files through the
  same path as the backend.
"""

from __future__ import annotations

import importlib.util
import json
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
FIXTURES_DIR = CLONE_DIR / "backend" / "data" / "import_fixtures"

# Isolate this module into a throwaway data dir, set before import so the backend
# resolves its single sqlite file inside it.
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-import-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"
INBOX_URL = "/__sim/inbox"
NY_TRIP_ID = "trip-traveler-new-york"

HILTON = "hotel-hilton-newyork.eml"
UNITED_ITINERARY = "flight-united-itinerary.eml"
UNITED_SCHEDULE_CHANGE = "flight-united-schedule-change.eml"
UNITED_CANCELLATION = "flight-united-cancellation.eml"
HERTZ = "car-hertz-confirmation.eml"
OPENTABLE = "restaurant-opentable.eml"
NEWSLETTER = "newsletter-unparseable.eml"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_import_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
OWNER_EMAIL = "traveler@example.com"
OTHER_EMAIL = "other@example.com"


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


def sign_in(client: TestClient, email: str = OWNER_EMAIL) -> None:
    response = client.post(
        LOGIN_URL,
        data={"login_email_address": email, "login_password": PASSWORDS[email]},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def fixture_raw(name: str) -> str:
    return (FIXTURES_DIR / name).read_text("utf-8")


def fixture_index() -> list[dict]:
    return json.loads((FIXTURES_DIR / "index.json").read_text("utf-8"))["fixtures"]


def owner_for(subject: str = "traveler") -> str:
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, subject)


def do_import(name: str, owner_subject: str = "traveler") -> dict:
    """File a fixture straight through the backend, as the injector route does."""

    return db.import_email(owner_for(owner_subject), fixture_raw(name))


def unfiled(owner: str) -> list[dict]:
    with closing(db.connect()) as connection:
        return db.list_unfiled_plans(connection, owner)


def unfiled_ids(owner: str) -> set[str]:
    return {p["plan_id"] for p in unfiled(owner)}


def trip_plans(owner: str, trip_id: str = NY_TRIP_ID) -> list[dict]:
    with closing(db.connect()) as connection:
        return db.list_plans_for_trip(connection, owner, trip_id)


def history(owner: str) -> list[dict]:
    with closing(db.connect()) as connection:
        return db.list_import_messages(connection, owner)


def plan_row(plan_id: str) -> dict | None:
    with closing(db.connect()) as connection:
        row = connection.execute(
            "SELECT * FROM tripit_plans WHERE plan_id=?", (plan_id,)
        ).fetchone()
        return dict(row) if row is not None else None


def receipt_jobs() -> list[dict]:
    with closing(db.connect()) as connection:
        rows = connection.execute(
            "SELECT purpose, recipient, status, is_simulation, variables_json,"
            " idempotency_key FROM websitebench_mail_jobs "
            "WHERE purpose='import-receipt' ORDER BY created_at, idempotency_key"
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# fixture library: every message parses and routes as declared
# ---------------------------------------------------------------------------


def test_fixture_library_parses_and_routes_as_declared(client: TestClient):
    """Import the library in index order on one account.

    The order matters and is the point: the United itinerary lands first, so the
    later schedule-change and cancellation match it by natural key and resolve to
    ``updated`` / ``canceled`` — exactly what the index declares.
    """

    owner = owner_for("traveler")
    base_unfiled = unfiled_ids(owner)
    for entry in fixture_index():
        result = do_import(entry["file"])
        assert result["parse_status"] == entry["expected_parse"], entry["file"]

        expected_routing = entry["expected_routing"]
        if expected_routing == NY_TRIP_ID:
            assert result["trip_id"] == NY_TRIP_ID, entry["file"]
            assert result["routing"] == "trip", entry["file"]
        elif expected_routing == "unfiled":
            assert result["routing"] == "unfiled", entry["file"]
            assert result["trip_id"] is None, entry["file"]
        else:  # null — no plan filed at all (unparseable)
            assert result["routing"] is None, entry["file"]
            assert result["plan_id"] is None, entry["file"]

    # Net effect of the whole library: Hilton + dinner filed into New York, the
    # United flight canceled (gone from Unfiled), only the Hertz car newly added
    # to Unfiled (the seed's Blue Bottle plan is left untouched).
    titles = {p["title"] for p in trip_plans(owner)}
    assert "New York Hilton Midtown" in titles
    assert "Gramercy Tavern" in titles
    new_unfiled = [p for p in unfiled(owner) if p["plan_id"] not in base_unfiled]
    # Only Hertz is newly filed to Unfiled; the imported United flight is canceled
    # (never an active Unfiled plan) and the seed's Blue Bottle plan is untouched.
    assert {p["title"] for p in new_unfiled} == {
        "Hertz rental · San Francisco Airport (SFO)"
    }


# ---------------------------------------------------------------------------
# routing by date overlap
# ---------------------------------------------------------------------------


def test_hilton_confirmation_files_into_the_new_york_trip(client: TestClient):
    owner = owner_for("traveler")
    before = len(trip_plans(owner))
    result = do_import(HILTON)
    assert result["parse_status"] == "parsed"
    assert result["plan_type"] == "lodging"
    assert result["title"] == "New York Hilton Midtown"
    assert result["trip_id"] == NY_TRIP_ID
    assert result["trip_name"] == "New York"
    assert result["routing"] == "trip"
    filed = trip_plans(owner)
    assert len(filed) == before + 1
    assert result["plan_id"] in {p["plan_id"] for p in filed}


def test_flight_without_overlap_lands_in_unfiled(client: TestClient):
    owner = owner_for("traveler")
    base = unfiled_ids(owner)
    result = do_import(UNITED_ITINERARY)
    assert result["parse_status"] == "parsed"
    assert result["plan_type"] == "air"
    assert result["trip_id"] is None
    assert result["routing"] == "unfiled"
    added = [p for p in unfiled(owner) if p["plan_id"] not in base]
    assert [p["plan_id"] for p in added] == [result["plan_id"]]
    assert added[0]["title"] == "United 512 · SFO → JFK"


# ---------------------------------------------------------------------------
# reschedule updates in place; cancellation flips the same plan
# ---------------------------------------------------------------------------


def test_schedule_change_updates_the_existing_plan_in_place(client: TestClient):
    owner = owner_for("traveler")
    base = len(unfiled(owner))
    created = do_import(UNITED_ITINERARY)
    assert len(unfiled(owner)) == base + 1
    original_ts = plan_row(created["plan_id"])["start_ts_utc"]

    updated = do_import(UNITED_SCHEDULE_CHANGE)
    assert updated["parse_status"] == "updated"
    # Same plan, same natural key, same slot in Unfiled — not a second row.
    assert updated["plan_id"] == created["plan_id"]
    assert len(unfiled(owner)) == base + 1
    # The departure moved 8:15 AM -> 10:05 AM, so the stored UTC start changed.
    assert plan_row(updated["plan_id"])["start_ts_utc"] != original_ts
    # History records both events against the same account.
    statuses = [m["parse_status"] for m in history(owner)]
    assert statuses.count("updated") == 1
    assert statuses.count("parsed") == 1


def test_cancellation_flips_the_existing_plan_not_a_new_one(client: TestClient):
    owner = owner_for("traveler")
    base_ids = unfiled_ids(owner)
    created = do_import(UNITED_ITINERARY)
    assert created["plan_id"] in unfiled_ids(owner)

    canceled = do_import(UNITED_CANCELLATION)
    assert canceled["parse_status"] == "canceled"
    assert canceled["plan_id"] == created["plan_id"]
    # The plan is gone from the active timeline (back to baseline) but still
    # exists as a canceled row.
    assert unfiled_ids(owner) == base_ids
    assert plan_row(created["plan_id"])["status"] == "canceled"


def test_cancellation_without_prior_plan_files_no_plan(client: TestClient):
    owner = owner_for("traveler")
    base_ids = unfiled_ids(owner)
    canceled = do_import(UNITED_CANCELLATION)
    assert canceled["parse_status"] == "canceled"
    assert canceled["plan_id"] is None
    assert unfiled_ids(owner) == base_ids
    # It is still recorded in history so the traveler sees it was processed.
    assert [m["parse_status"] for m in history(owner)] == ["canceled"]


# ---------------------------------------------------------------------------
# fingerprint idempotency
# ---------------------------------------------------------------------------


def test_reforwarding_the_same_message_is_a_duplicate(client: TestClient):
    owner = owner_for("traveler")
    before = len(trip_plans(owner))
    first = do_import(HILTON)
    assert len(trip_plans(owner)) == before + 1
    second = do_import(HILTON)
    assert second["parse_status"] == "duplicate"
    assert second["duplicate"] is True
    assert second["message_id"] == first["message_id"]
    # No second plan and no second history row.
    assert len(trip_plans(owner)) == before + 1
    assert len(history(owner)) == 1


def test_duplicate_does_not_send_a_second_receipt(client: TestClient):
    do_import(HILTON)
    assert len(receipt_jobs()) == 1
    do_import(HILTON)  # duplicate
    assert len(receipt_jobs()) == 1


# ---------------------------------------------------------------------------
# unparseable is a first-class outcome
# ---------------------------------------------------------------------------


def test_unparseable_message_files_nothing_and_never_raises(client: TestClient):
    owner = owner_for("traveler")
    base_ids = unfiled_ids(owner)
    result = do_import(NEWSLETTER)
    assert result["parse_status"] == "unparseable"
    assert result["plan_id"] is None
    assert result["trip_id"] is None
    assert unfiled_ids(owner) == base_ids
    recorded = history(owner)
    assert [m["parse_status"] for m in recorded] == ["unparseable"]
    assert receipt_jobs() == []  # nothing filed, nothing mailed


# ---------------------------------------------------------------------------
# receipt mail
# ---------------------------------------------------------------------------


def test_parsed_import_enqueues_a_simulated_receipt(client: TestClient):
    do_import(HILTON)
    jobs = receipt_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["recipient"] == OWNER_EMAIL
    assert job["status"] == "LOCAL_SIMULATION"
    assert job["is_simulation"] == 1
    variables = json.loads(job["variables_json"])
    assert variables["trip_name"] == "New York"
    assert variables["provider"] == "Hilton"
    assert variables["plan_count"] == "1"


def test_unfiled_import_receipt_names_unfiled_items(client: TestClient):
    do_import(UNITED_ITINERARY)
    jobs = receipt_jobs()
    assert len(jobs) == 1
    variables = json.loads(jobs[0]["variables_json"])
    assert variables["trip_name"] == "Unfiled Items"


# ---------------------------------------------------------------------------
# owner isolation
# ---------------------------------------------------------------------------


def test_imports_are_owner_scoped(client: TestClient):
    owner_for("traveler")
    other = owner_for("other")
    other_base = unfiled_ids(other)
    do_import(HILTON, owner_subject="traveler")

    # The other account sees none of it: no history, no receipt to them, and
    # their own unfiled is untouched.
    assert history(other) == []
    assert unfiled_ids(other) == other_base
    assert all(job["recipient"] == OWNER_EMAIL for job in receipt_jobs())
    # And the same message filed by 'other' is a distinct record (different
    # owner -> different message id), not a cross-owner duplicate.
    mine = do_import(HILTON, owner_subject="traveler")
    theirs = do_import(HILTON, owner_subject="other")
    assert mine["parse_status"] == "duplicate"  # traveler already had it
    assert theirs["parse_status"] == "parsed"  # first time for 'other'
    assert theirs["message_id"] != mine["message_id"]
    # 'other' has no overlapping trip, so it lands in their Unfiled.
    assert len(history(other)) == 1
    other_added = [p for p in unfiled(other) if p["plan_id"] not in other_base]
    assert [p["title"] for p in other_added] == ["New York Hilton Midtown"]


# ---------------------------------------------------------------------------
# /__sim/inbox injector route
# ---------------------------------------------------------------------------


def test_inbox_requires_authentication(client: TestClient):
    got = client.get(INBOX_URL, follow_redirects=False)
    assert got.status_code == 303
    assert got.headers["location"] == LOGIN_URL
    posted = client.post(
        INBOX_URL, data={"mode": "paste", "raw_text": "x"}, follow_redirects=False
    )
    assert posted.status_code == 303
    assert posted.headers["location"] == LOGIN_URL


def test_inbox_page_lists_samples_for_the_signed_in_traveler(client: TestClient):
    sign_in(client)
    response = client.get(INBOX_URL)
    assert response.status_code == 200
    assert OWNER_EMAIL in response.text
    assert "plans@tripit.com" in response.text
    # Every fixture is offered as a selectable sample.
    for entry in fixture_index():
        assert entry["file"] in response.text


def test_inbox_fixture_submission_files_a_plan(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    response = client.post(
        INBOX_URL, data={"mode": "fixture", "fixture": HILTON}, follow_redirects=False
    )
    assert response.status_code == 200
    assert "New York" in response.text
    filed = {p["title"] for p in trip_plans(owner)}
    assert "New York Hilton Midtown" in filed
    # The import now shows in the on-page history.
    assert "New York Hilton Midtown" in client.get(INBOX_URL).text


def test_inbox_paste_submission_files_a_plan(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    response = client.post(
        INBOX_URL,
        data={"mode": "paste", "raw_text": fixture_raw(OPENTABLE)},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Gramercy Tavern" in {p["title"] for p in trip_plans(owner)}


def test_inbox_upload_submission_files_a_plan(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    response = client.post(
        INBOX_URL,
        data={"mode": "upload"},
        files={"eml_file": (HILTON, fixture_raw(HILTON).encode("utf-8"), "message/rfc822")},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "New York Hilton Midtown" in {p["title"] for p in trip_plans(owner)}


def test_inbox_rejects_empty_submission(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    response = client.post(
        INBOX_URL, data={"mode": "paste", "raw_text": "   "}, follow_redirects=False
    )
    assert response.status_code == 400
    assert history(owner) == []


def test_inbox_ignores_unknown_fixture_name(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    response = client.post(
        INBOX_URL,
        data={"mode": "fixture", "fixture": "../../../etc/passwd"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert history(owner) == []
