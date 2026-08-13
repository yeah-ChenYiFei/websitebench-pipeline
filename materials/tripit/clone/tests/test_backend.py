"""Persistent-backend contract + domain-semantics tests for the TripIt clone.

Covers the shared backend contract (sqlite3 WAL, single site file under
WEBSITEBENCH_TRIPIT_DATA_DIR, linear migration ledger, admin reset, frozen
clock, __Host- signed sessions) plus every TripIt itinerary semantic the blind
test depends on: server-owned trips/plans, the seeded upcoming/past/unfiled
truth, the anchored "add the Hilton Midtown stay to the existing New York trip"
journey, triple idempotency, illegal-input rejection, cross-account 404
isolation with no existence disclosure, the registration OTP round-trip,
enumeration-safe password reset, restart persistence, and legacy->head
migration determinism.

The registration tests retrieve the emailed OTP for a synthetic account in an
ephemeral database purely to feed it back into /account/verify; the code value
is never logged or asserted on.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"

# Isolate this whole test module into a throwaway data dir, set before import so
# the backend resolves its single sqlite file inside it.
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-backend-tests-"))
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


app_module = load_module(APP_FILE, "tripit_clone_app_backend_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
EXPECTED_MIGRATIONS = [mig_id for mig_id, _ in db.MIGRATIONS]


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    """Re-pin this module's data dir every test; test_frontend.py sets its own
    at import time when the whole suite is collected together."""
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


def lodging_rows(owner: str, trip_id: str) -> list[sqlite3.Row]:
    with closing(db.connect()) as connection:
        return connection.execute(
            "SELECT * FROM tripit_plans WHERE owner_key=? AND trip_id=? "
            "AND plan_type='lodging' AND status='active' ORDER BY plan_id",
            (owner, trip_id),
        ).fetchall()


def lodging_count(owner: str, trip_id: str) -> int:
    return len(lodging_rows(owner, trip_id))


def add_hotel(
    client: TestClient,
    trip_id: str,
    *,
    key: str = "anchor-1",
    check_in: str = CHECK_IN,
    check_out: str = CHECK_OUT,
    confirmation: str = CONFIRMATION,
    hotel: str = HOTEL,
):
    return client.post(
        f"/trips/{trip_id}/plans",
        data={
            "plan_type": "lodging",
            "idempotency_key": key,
            "title": hotel,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "confirmation": confirmation,
        },
        follow_redirects=False,
    )


def registration_code(token: str) -> str:
    # Test-only retrieval of the emailed OTP for a synthetic account in the
    # ephemeral test DB; fed straight into /account/verify, never logged.
    mail = app_module.auth_store().local_mail_for_session(token, purpose="registration")
    assert isinstance(mail, dict)
    return str(mail["verification_code"])


# ---------------------------------------------------------------------------
# shared backend contract
# ---------------------------------------------------------------------------


def test_healthz_body_is_frozen_exact(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == '{"ok":true,"site_id":"tripit"}'


def test_database_is_wal_single_file_in_data_dir(client):
    path = str(db.database_path())
    assert str(DATA_DIR) in path
    assert path.endswith("tripit.sqlite3")
    with closing(db.connect()) as connection:
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(journal).lower() == "wal"


def test_migration_ledger_is_linear_and_complete(client):
    with closing(db.connect()) as connection:
        applied = db.applied_migrations(connection)
    assert applied == EXPECTED_MIGRATIONS
    assert db.SCHEMA_HEAD == EXPECTED_MIGRATIONS[-1]


def test_migration_is_idempotent_from_empty(client):
    probe_dir = Path(tempfile.mkdtemp(prefix="tripit-migrate-probe-"))
    probe = probe_dir / "tripit.sqlite3"
    with closing(db.connect(probe)) as connection:
        first = db.migrate(connection)
        second = db.migrate(connection)
        applied = db.applied_migrations(connection)
    assert first == EXPECTED_MIGRATIONS
    assert second == []
    assert applied == EXPECTED_MIGRATIONS


def test_admin_reset_requires_token(client):
    assert client.post("/__admin/reset").status_code == 403
    denied = client.post("/__admin/reset", headers={"X-WebsiteBench-Admin-Token": "wrong"})
    assert denied.status_code == 403
    assert denied.json() == {"error": "forbidden"}
    ok = client.post(
        "/__admin/reset",
        headers={"X-WebsiteBench-Admin-Token": app_module.ADMIN_TOKEN},
    )
    assert ok.status_code == 200
    assert ok.json() == {"reset": True, "site_id": "tripit"}


def test_two_resets_produce_identical_state(client):
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    with closing(db.connect()) as connection:
        first_counts = db.counts(connection)
    sign_in(client)
    add_hotel(client, trip_id)
    assert lodging_count(owner, trip_id) == 1
    app_module.reset_fixture_state()
    with closing(db.connect()) as connection:
        second_counts = db.counts(connection)
    assert first_counts == second_counts
    assert lodging_count(owner, trip_id) == 0


def test_database_file_is_a_portable_backup_unit(client, tmp_path):
    # The whole site is one sqlite file: checkpoint the WAL, copy the single
    # file, and it reopens as a complete, restorable backup (the migration-copy
    # primitive that the deploy profiles rely on).
    with closing(db.connect()) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    backup = tmp_path / "tripit-backup.sqlite3"
    shutil.copy2(db.database_path(), backup)
    with closing(sqlite3.connect(str(backup))) as restored:
        restored.row_factory = sqlite3.Row
        names = {row["name"] for row in restored.execute("SELECT name FROM tripit_trips")}
        migrations = [
            row["migration_id"]
            for row in restored.execute(
                "SELECT migration_id FROM tripit_schema_migrations ORDER BY applied_at, migration_id"
            )
        ]
    assert "New York" in names
    assert migrations[-1] == db.SCHEMA_HEAD


# ---------------------------------------------------------------------------
# seeded truth
# ---------------------------------------------------------------------------


def test_upcoming_tab_shows_seeded_trips(client):
    sign_in(client)
    body = client.get("/trips").text
    assert "New York" in body
    assert "Kyoto Autumn" in body
    assert "Lisbon Getaway" in body
    assert "Chicago Sprint" not in body


def test_past_and_unfiled_tabs(client):
    sign_in(client)
    assert "Chicago Sprint" in client.get("/trips?tab=past").text
    assert "Blue Bottle" in client.get("/trips?tab=unfiled").text


def test_new_york_itinerary_seed(client):
    sign_in(client)
    owner = owner_for()
    detail = client.get(f"/trips/{ny_trip_id(owner)}")
    assert detail.status_code == 200
    assert "United 512" in detail.text
    assert "Add a hotel" in detail.text
    assert lodging_count(owner, ny_trip_id(owner)) == 0


# ---------------------------------------------------------------------------
# sessions + access control
# ---------------------------------------------------------------------------


def test_anonymous_owner_scoped_pages_redirect_to_login(client):
    for path in ("/trips", "/trips/trip-traveler-new-york", "/account"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == LOGIN_URL


def test_login_sets_host_session_cookie(client):
    response = sign_in(client)
    assert response.status_code == 303
    # Login lands on the authenticated app dashboard, matching the source SPA
    # (logged-in TripIt routes live under /app/*).
    assert response.headers["location"] == "/app/trips"
    assert app_module.SESSION_COOKIE == "__Host-websitebench-tripit-session"
    set_cookie = response.headers.get("set-cookie", "")
    assert app_module.SESSION_COOKIE in set_cookie
    assert "Secure" in set_cookie and "HttpOnly" in set_cookie


def test_login_with_wrong_password_is_rejected_without_session(client):
    response = client.post(
        LOGIN_URL,
        data={"login_email_address": "traveler@example.com", "login_password": "nope"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "login_email_address" in response.text
    assert not client.cookies.get(app_module.SESSION_COOKIE)


def test_logout_clears_session(client):
    sign_in(client)
    out = client.post("/account/logout", follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/"
    assert client.get("/trips", follow_redirects=False).status_code == 303


def test_typeahead_requires_authentication(client):
    anon = client.get("/api/lodging/typeahead?q=hil")
    assert anon.status_code == 401
    assert anon.json() == {"results": []}
    sign_in(client)
    hit = client.get("/api/lodging/typeahead?q=hilton")
    assert hit.status_code == 200
    assert any("Hilton" in item["name"] for item in hit.json()["results"])


# ---------------------------------------------------------------------------
# anchored domain journey: add the Hilton stay to the New York trip
# ---------------------------------------------------------------------------


def test_add_hotel_appears_on_trip_in_order(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    response = add_hotel(client, trip_id)
    assert response.status_code == 303
    assert response.headers["location"] == f"/trips/{trip_id}"
    assert lodging_count(owner, trip_id) == 1
    detail = client.get(f"/trips/{trip_id}").text
    assert HOTEL in detail
    assert "Check-in" in detail
    assert "Check-out" in detail
    assert CONFIRMATION in detail
    # Check-in precedes check-out in the rendered timeline.
    assert detail.index("Check-in") < detail.index("Check-out")


def test_add_hotel_is_idempotent_on_same_key(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    add_hotel(client, trip_id, key="k1")
    add_hotel(client, trip_id, key="k1")
    assert lodging_count(owner, trip_id) == 1


def test_add_hotel_is_idempotent_on_natural_key(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    add_hotel(client, trip_id, key="k1")
    # Fresh idempotency key, same hotel + confirmation -> same natural key.
    add_hotel(client, trip_id, key="k2")
    assert lodging_count(owner, trip_id) == 1


def test_add_hotel_rejects_checkout_before_checkin(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    response = add_hotel(client, trip_id, check_in=CHECK_OUT, check_out=CHECK_IN)
    assert response.status_code == 400
    assert lodging_count(owner, trip_id) == 0


def test_add_hotel_requires_a_hotel_name(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    response = add_hotel(client, trip_id, hotel="")
    assert response.status_code == 400
    assert lodging_count(owner, trip_id) == 0


def test_unknown_plan_type_is_404(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    response = client.post(
        f"/trips/{trip_id}/plans",
        data={"plan_type": "teleport", "title": "x"},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_delete_hotel_removes_it(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    add_hotel(client, trip_id)
    plan_id = lodging_rows(owner, trip_id)[0]["plan_id"]
    response = client.post(
        f"/plans/{plan_id}/delete",
        data={"return_to": f"/trips/{trip_id}"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/trips/{trip_id}"
    assert lodging_count(owner, trip_id) == 0


def test_move_hotel_to_unfiled(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    add_hotel(client, trip_id)
    plan_id = lodging_rows(owner, trip_id)[0]["plan_id"]
    response = client.post(
        f"/plans/{plan_id}/move", data={"trip_id": ""}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/trips?tab=unfiled"
    assert lodging_count(owner, trip_id) == 0
    with closing(db.connect()) as connection:
        unfiled_ids = {p["plan_id"] for p in db.list_unfiled_plans(connection, owner)}
    assert plan_id in unfiled_ids


# ---------------------------------------------------------------------------
# cross-account isolation (404, no existence disclosure)
# ---------------------------------------------------------------------------


def test_foreign_trip_reads_as_404(client):
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    other = TestClient(app, base_url="https://testserver")
    sign_in(other, "other@example.com")
    assert other.get(f"/trips/{trip_id}", follow_redirects=False).status_code == 404


def test_missing_trip_reads_as_404(client):
    sign_in(client)
    assert client.get("/trips/no-such-trip", follow_redirects=False).status_code == 404


def test_foreign_cannot_add_plan(client):
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    other = TestClient(app, base_url="https://testserver")
    sign_in(other, "other@example.com")
    response = add_hotel(other, trip_id, key="intruder")
    assert response.status_code == 404
    assert lodging_count(owner, trip_id) == 0


def test_foreign_cannot_delete_plan(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    add_hotel(client, trip_id)
    plan_id = lodging_rows(owner, trip_id)[0]["plan_id"]
    other = TestClient(app, base_url="https://testserver")
    sign_in(other, "other@example.com")
    response = other.post(
        f"/plans/{plan_id}/delete", data={}, follow_redirects=False
    )
    assert response.status_code == 404
    assert lodging_count(owner, trip_id) == 1


# ---------------------------------------------------------------------------
# registration OTP round-trip + validation
# ---------------------------------------------------------------------------


def test_registration_round_trip_signs_in_and_persists_profile(client):
    reg = TestClient(app, base_url="https://testserver")
    step1 = reg.post(
        "/account/update",
        data={
            "email_address": "newtraveler@example.com",
            "password": "correct-horse-battery",
            "place": "Seattle, WA",
            "toc": "on",
        },
    )
    assert step1.status_code == 200
    assert "Verify your email" in step1.text
    token = reg.cookies.get(app_module.SESSION_COOKIE)
    code = registration_code(token)
    verify = reg.post(
        "/account/verify",
        data={"code": code, "email": "newtraveler@example.com", "place": "Seattle, WA"},
        follow_redirects=False,
    )
    assert verify.status_code == 303
    assert verify.headers["location"] == "/trips"
    account = reg.get("/account")
    assert account.status_code == 200
    assert "Seattle, WA" in account.text
    assert "No upcoming trips" in reg.get("/trips").text


def test_registration_rejects_weak_password(client):
    response = client.post(
        "/account/update",
        data={"email_address": "weak@example.com", "password": "short", "place": "X", "toc": "on"},
    )
    assert response.status_code == 400
    assert "At least 15 characters" in response.text


def test_registration_rejects_email_shaped_password(client):
    response = client.post(
        "/account/update",
        data={
            "email_address": "e@example.com",
            "password": "verylong@example.com",
            "place": "X",
            "toc": "on",
        },
    )
    assert response.status_code == 400


def test_registration_requires_agreement(client):
    response = client.post(
        "/account/update",
        data={"email_address": "noagree@example.com", "password": "correct-horse-battery", "place": "X"},
    )
    assert response.status_code == 400


def test_registration_conflict_on_existing_email(client):
    response = client.post(
        "/account/update",
        data={
            "email_address": "traveler@example.com",
            "password": "correct-horse-battery",
            "place": "X",
            "toc": "on",
        },
    )
    assert response.status_code == 409


def test_registration_rejects_wrong_verification_code(client):
    # Reach the verify stage, then submit a deliberately wrong code. The real
    # emitted code is never read here, so the secret never enters the test.
    reg = TestClient(app, base_url="https://testserver")
    step1 = reg.post(
        "/account/update",
        data={
            "email_address": "wrongcode@example.com",
            "password": "correct-horse-battery",
            "place": "Denver, CO",
            "toc": "on",
        },
    )
    assert step1.status_code == 200
    assert "Verify your email" in step1.text

    rejected = reg.post(
        "/account/verify",
        data={"code": "000000", "email": "wrongcode@example.com", "place": "Denver, CO"},
        follow_redirects=False,
    )
    assert rejected.status_code == 400
    assert "incorrect or expired" in rejected.text
    # No account was minted: signing in with those credentials must fail with no
    # session cookie handed out.
    attempt = TestClient(app, base_url="https://testserver")
    login = attempt.post(
        LOGIN_URL,
        data={
            "login_email_address": "wrongcode@example.com",
            "login_password": "correct-horse-battery",
        },
        follow_redirects=False,
    )
    assert login.status_code == 200
    assert not attempt.cookies.get(app_module.SESSION_COOKIE)


def test_forgot_password_is_enumeration_safe(client):
    known = client.post("/account/forgotPassword", data={"email_address": "traveler@example.com"})
    unknown = client.post("/account/forgotPassword", data={"email_address": "nobody@example.com"})
    assert known.status_code == 200 and unknown.status_code == 200
    assert "Check your email" in known.text
    assert known.text == unknown.text


# ---------------------------------------------------------------------------
# write concurrency
# ---------------------------------------------------------------------------


def test_concurrent_duplicate_add_converges_to_one_row(client):
    # Many writers submit the same reservation at once, each with a *distinct*
    # idempotency key so only the (owner, natural_key) guard can collapse them.
    # BEGIN IMMEDIATE + busy_timeout serialize the writers; the second onward
    # find the prior natural key and must not insert a duplicate or 5xx.
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    token = client.cookies.get(app_module.SESSION_COOKIE)
    assert token

    def submit(n: int) -> int:
        worker = TestClient(app, base_url="https://testserver")
        worker.cookies.set(app_module.SESSION_COOKIE, token)
        return add_hotel(worker, trip_id, key=f"race-{n}").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(submit, range(8)))

    assert all(status in (200, 303) for status in statuses), statuses
    assert lodging_count(owner, trip_id) == 1


# ---------------------------------------------------------------------------
# restart persistence
# ---------------------------------------------------------------------------


def test_reservation_survives_process_restart(client):
    sign_in(client)
    owner = owner_for()
    trip_id = ny_trip_id(owner)
    add_hotel(client, trip_id)
    assert lodging_count(owner, trip_id) == 1

    # Simulate a cold restart: drop the cached backend-db module and reload the
    # app against the same data dir; no reset in between.
    sys.modules.pop("tripit_clone_backend_db", None)
    restarted = load_module(APP_FILE, "tripit_clone_app_backend_tests_restarted")
    with TestClient(restarted.app, base_url="https://testserver") as fresh:
        fresh.post(
            LOGIN_URL,
            data={
                "login_email_address": "traveler@example.com",
                "login_password": PASSWORDS["traveler@example.com"],
            },
            follow_redirects=False,
        )
        detail = fresh.get(f"/trips/{trip_id}")
        assert detail.status_code == 200
        assert HOTEL in detail.text
        assert CONFIRMATION in detail.text
    # Restore this module's backend-db binding for the remaining tests.
    global db
    load_module(APP_FILE, "tripit_clone_app_backend_tests")
    db = sys.modules["tripit_clone_backend_db"]
