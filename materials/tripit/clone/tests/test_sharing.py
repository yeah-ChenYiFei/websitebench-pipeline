"""Trip-sharing journeys for the TripIt clone.

Sharing is a free-tier feature: a trip owner invites a companion by email under a
role (viewer / editor / fellow traveler), optionally hiding confirmation and
ticketing numbers, and can change the role, toggle the sensitive-field mask, or
revoke access. The invitee discovers the invitation on their own trips page,
accepts it from their signed-in session (delivery is by email match — no bearer
token is ever minted or mailed), and reads a masked, read-only copy of the trip.

These tests pin the P0 items the blind test depends on — invite → accept →
role-and-revoke and the sensitive-field masking — plus the invariants that keep
the feature honest: the seed holds zero shares, an invite enqueues exactly one
simulated ``share-invite`` mail, invites are idempotent by email while a role
change legitimately re-notifies, a masked viewer's HTML never contains a
sensitive identifier, and a foreign or mismatched actor is a 404 that never
discloses existence.
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

# Isolate this module into a throwaway data dir, set before import so the backend
# resolves its single sqlite file inside it.
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-sharing-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"
NY_TRIP_ID = "trip-traveler-new-york"
# Sensitive identifiers seeded on the New York trip's plans. The first two are
# confirmation numbers (revealed only when the owner opts in); the record
# locator is never surfaced on the shared view at all.
NY_FLIGHT_CONFIRMATION = "UA512NYC"
NY_DINNER_CONFIRMATION = "OT-88213"
NY_RECORD_LOCATOR = "H7QK2P"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_sharing_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
OWNER_EMAIL = "traveler@example.com"
INVITEE_EMAIL = "other@example.com"


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


def fresh_client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def owner_for(subject: str = "traveler") -> str:
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, subject)


def shares_for(trip_id: str = NY_TRIP_ID, owner: str | None = None) -> list[dict]:
    owner = owner or owner_for("traveler")
    with closing(db.connect()) as connection:
        return db.list_shares_for_trip(connection, owner, trip_id)


def only_share(trip_id: str = NY_TRIP_ID) -> dict:
    shares = shares_for(trip_id)
    assert len(shares) == 1, shares
    return shares[0]


def share_count() -> int:
    with closing(db.connect()) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM tripit_trip_shares"
        ).fetchone()[0]


def membership_role(trip_id: str, traveler_key: str) -> str | None:
    with closing(db.connect()) as connection:
        row = connection.execute(
            "SELECT role FROM tripit_trip_travelers "
            "WHERE trip_id=? AND traveler_key=?",
            (trip_id, traveler_key),
        ).fetchone()
    return row["role"] if row else None


def invite_jobs() -> list[dict]:
    with closing(db.connect()) as connection:
        rows = connection.execute(
            "SELECT purpose, recipient, status, is_simulation, variables_json,"
            " idempotency_key FROM websitebench_mail_jobs "
            "WHERE purpose='share-invite' ORDER BY created_at, idempotency_key"
        ).fetchall()
    return [dict(row) for row in rows]


def invite(
    client: TestClient,
    *,
    email: str = INVITEE_EMAIL,
    role: str = "viewer",
    show_sensitive: bool = False,
    trip_id: str = NY_TRIP_ID,
):
    data = {"invitee_email": email, "role": role}
    if show_sensitive:
        data["show_sensitive"] = "on"
    return client.post(
        f"/trips/{trip_id}/share", data=data, follow_redirects=False
    )


def invite_and_accept(
    *, role: str = "viewer", show_sensitive: bool = False
) -> str:
    """Owner invites the fixture invitee, who accepts. Returns the share id."""

    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        assert invite(
            owner_client, role=role, show_sensitive=show_sensitive
        ).status_code == 303
    share_id = only_share()["share_id"]
    with fresh_client() as invitee_client:
        sign_in(invitee_client, INVITEE_EMAIL)
        accepted = invitee_client.post(
            f"/shares/{share_id}/accept", follow_redirects=False
        )
        assert accepted.status_code == 303
    return share_id


# ---------------------------------------------------------------------------
# seed invariants
# ---------------------------------------------------------------------------


def test_seed_holds_no_shares(client: TestClient):
    # Frozen data assertion trip-share::tripit_trip_shares::count=0.
    assert share_count() == 0


def test_unshared_trips_page_hides_discovery_section(client: TestClient):
    # With no incoming shares the "Shared with you" surface must not render, so
    # the seeded /trips response stays byte-for-byte what the visual set froze.
    sign_in(client, INVITEE_EMAIL)
    response = client.get("/trips")
    assert response.status_code == 200
    assert "Shared with you" not in response.text


def test_trip_detail_exposes_sharing_entry_point(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    detail = client.get(f"/trips/{NY_TRIP_ID}")
    assert detail.status_code == 200
    assert f"/trips/{NY_TRIP_ID}/share" in detail.text


# ---------------------------------------------------------------------------
# invite + mail (P0)
# ---------------------------------------------------------------------------


def test_owner_can_invite_and_mail_is_simulated(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    response = invite(client, role="viewer")
    assert response.status_code == 303
    assert response.headers["location"] == f"/trips/{NY_TRIP_ID}/share"

    share = only_share()
    assert share["invitee_email"] == INVITEE_EMAIL
    assert share["status"] == "invited"
    assert share["role"] == "viewer"
    assert share["show_sensitive"] is False

    jobs = invite_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["recipient"] == INVITEE_EMAIL
    assert job["status"] == "LOCAL_SIMULATION"
    assert job["is_simulation"] == 1
    variables = json.loads(job["variables_json"])
    assert variables == {
        "inviter_name": "Avery Chen",
        "trip_name": "New York",
        "role": "viewer",
    }


def test_share_page_lists_the_invitation(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    invite(client, role="editor")
    page = client.get(f"/trips/{NY_TRIP_ID}/share")
    assert page.status_code == 200
    assert INVITEE_EMAIL in page.text
    assert "invited" in page.text


def test_invalid_email_is_rejected(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    response = invite(client, email="not-an-email")
    assert response.status_code == 400
    assert share_count() == 0
    assert invite_jobs() == []


def test_owner_cannot_share_with_self(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    response = invite(client, email=OWNER_EMAIL)
    assert response.status_code == 400
    assert "own" in response.text.lower()
    assert share_count() == 0


def test_invite_is_idempotent_by_email(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    assert invite(client, role="viewer").status_code == 303
    assert invite(client, role="viewer").status_code == 303
    # Same address + same role: one share row, one (idempotent) mail job.
    assert share_count() == 1
    assert len(invite_jobs()) == 1


def test_role_change_via_reinvite_sends_fresh_mail(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    assert invite(client, role="viewer").status_code == 303
    assert invite(client, role="editor").status_code == 303
    # The role is folded into the idempotency key, so a genuine role change
    # re-notifies without conflicting with the immutable earlier job.
    assert share_count() == 1
    assert only_share()["role"] == "editor"
    jobs = invite_jobs()
    assert len(jobs) == 2
    assert {json.loads(j["variables_json"])["role"] for j in jobs} == {
        "viewer",
        "editor",
    }


def test_traveler_role_can_be_invited_and_syncs_membership(client: TestClient):
    # The share role matrix registers three roles: viewer, editor, and
    # "traveler" (a fellow traveler carried as trip membership). The traveler
    # role must be invitable, notify by mail, and — once accepted — sync into
    # tripit_trip_travelers exactly like the other roles.
    share_id = invite_and_accept(role="traveler")
    assert share_id
    assert only_share()["role"] == "traveler"
    assert membership_role(NY_TRIP_ID, "other") == "traveler"
    jobs = invite_jobs()
    assert jobs, "a traveler invite must enqueue a simulated mail job"
    last = jobs[-1]
    assert last["status"] == "LOCAL_SIMULATION"
    assert last["is_simulation"] == 1
    assert json.loads(last["variables_json"])["role"] == "traveler"


# ---------------------------------------------------------------------------
# accept + read (P0)
# ---------------------------------------------------------------------------


def test_invitation_appears_on_invitee_trips(client: TestClient):
    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        invite(owner_client, role="viewer")
    share_id = only_share()["share_id"]

    sign_in(client, INVITEE_EMAIL)
    trips = client.get("/trips")
    assert "Shared with you" in trips.text
    assert "New York" in trips.text
    assert "Avery Chen" in trips.text
    assert f"/shares/{share_id}/accept" in trips.text


def test_accept_grants_masked_read_access(client: TestClient):
    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        invite(owner_client, role="viewer")
    share_id = only_share()["share_id"]

    sign_in(client, INVITEE_EMAIL)
    # Before acceptance the trip is invisible — indistinguishable from absent.
    assert client.get(f"/shared/{NY_TRIP_ID}").status_code == 404

    accepted = client.post(f"/shares/{share_id}/accept", follow_redirects=False)
    assert accepted.status_code == 303
    assert accepted.headers["location"] == f"/shared/{NY_TRIP_ID}"

    assert only_share()["status"] == "active"
    assert membership_role(NY_TRIP_ID, "other") == "viewer"

    view = client.get(f"/shared/{NY_TRIP_ID}")
    assert view.status_code == 200
    assert "New York" in view.text
    assert "Avery Chen" in view.text


def test_accept_is_idempotent(client: TestClient):
    share_id = invite_and_accept()
    sign_in(client, INVITEE_EMAIL)
    again = client.post(f"/shares/{share_id}/accept", follow_redirects=False)
    assert again.status_code == 303
    assert only_share()["status"] == "active"
    assert membership_role(NY_TRIP_ID, "other") == "viewer"


# ---------------------------------------------------------------------------
# sensitive-field masking (P0)
# ---------------------------------------------------------------------------


def test_sensitive_fields_masked_by_default(client: TestClient):
    invite_and_accept(show_sensitive=False)
    sign_in(client, INVITEE_EMAIL)
    view = client.get(f"/shared/{NY_TRIP_ID}")
    assert view.status_code == 200
    # No confirmation or ticketing identifier may reach a masked viewer's HTML.
    assert NY_FLIGHT_CONFIRMATION not in view.text
    assert NY_DINNER_CONFIRMATION not in view.text
    assert NY_RECORD_LOCATOR not in view.text


def test_owner_can_reveal_sensitive_fields(client: TestClient):
    share_id = invite_and_accept(show_sensitive=False)
    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        toggled = owner_client.post(
            f"/shares/{share_id}/sensitive",
            data={"show_sensitive": "on"},
            follow_redirects=False,
        )
        assert toggled.status_code == 303
    assert only_share()["show_sensitive"] is True

    sign_in(client, INVITEE_EMAIL)
    view = client.get(f"/shared/{NY_TRIP_ID}")
    assert NY_FLIGHT_CONFIRMATION in view.text
    assert NY_DINNER_CONFIRMATION in view.text
    # The record locator is still never surfaced on the shared read view.
    assert NY_RECORD_LOCATOR not in view.text


def test_owner_can_hide_sensitive_fields_again(client: TestClient):
    share_id = invite_and_accept(show_sensitive=True)
    sign_in(client, INVITEE_EMAIL)
    assert NY_FLIGHT_CONFIRMATION in client.get(f"/shared/{NY_TRIP_ID}").text

    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        owner_client.post(
            f"/shares/{share_id}/sensitive",
            data={},
            follow_redirects=False,
        )
    assert only_share()["show_sensitive"] is False
    assert NY_FLIGHT_CONFIRMATION not in client.get(f"/shared/{NY_TRIP_ID}").text


# ---------------------------------------------------------------------------
# role change + revoke (P0)
# ---------------------------------------------------------------------------


def test_owner_can_change_role_and_membership_syncs(client: TestClient):
    share_id = invite_and_accept(role="viewer")
    assert membership_role(NY_TRIP_ID, "other") == "viewer"

    sign_in(client, OWNER_EMAIL)
    changed = client.post(
        f"/shares/{share_id}/role",
        data={"role": "editor"},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert only_share()["role"] == "editor"
    assert membership_role(NY_TRIP_ID, "other") == "editor"


def test_unknown_role_is_not_found(client: TestClient):
    share_id = invite_and_accept()
    sign_in(client, OWNER_EMAIL)
    response = client.post(
        f"/shares/{share_id}/role",
        data={"role": "administrator"},
        follow_redirects=False,
    )
    assert response.status_code == 404
    assert only_share()["role"] == "viewer"


def test_revoke_ends_access_and_membership(client: TestClient):
    share_id = invite_and_accept()
    assert membership_role(NY_TRIP_ID, "other") == "viewer"

    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        revoked = owner_client.post(
            f"/shares/{share_id}/revoke", follow_redirects=False
        )
        assert revoked.status_code == 303

    assert only_share()["status"] == "revoked"
    assert membership_role(NY_TRIP_ID, "other") is None

    sign_in(client, INVITEE_EMAIL)
    assert client.get(f"/shared/{NY_TRIP_ID}").status_code == 404
    # The revoked trip drops off the invitee's discovery surface.
    trips = client.get("/trips")
    assert "New York" not in trips.text


def test_revoked_invite_can_be_reissued(client: TestClient):
    share_id = invite_and_accept()
    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        owner_client.post(f"/shares/{share_id}/revoke", follow_redirects=False)
        assert only_share()["status"] == "revoked"
        # Re-inviting the same address reuses the row and returns it to invited.
        assert invite(owner_client, role="viewer").status_code == 303
    assert share_count() == 1
    assert only_share()["status"] == "invited"


def test_accept_after_revoke_is_forbidden(client: TestClient):
    share_id = invite_and_accept()
    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        owner_client.post(f"/shares/{share_id}/revoke", follow_redirects=False)

    sign_in(client, INVITEE_EMAIL)
    # A revoked invitation cannot be re-accepted from a stale page.
    assert client.post(
        f"/shares/{share_id}/accept", follow_redirects=False
    ).status_code == 404


# ---------------------------------------------------------------------------
# authorization / isolation / non-disclosure
# ---------------------------------------------------------------------------


def test_sharing_requires_authentication(client: TestClient):
    share_id = "share-does-not-matter"
    getters = [f"/trips/{NY_TRIP_ID}/share", f"/shared/{NY_TRIP_ID}"]
    for url in getters:
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == LOGIN_URL
    posts = [
        f"/trips/{NY_TRIP_ID}/share",
        f"/shares/{share_id}/role",
        f"/shares/{share_id}/sensitive",
        f"/shares/{share_id}/revoke",
        f"/shares/{share_id}/accept",
    ]
    for url in posts:
        response = client.post(url, data={}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == LOGIN_URL


def test_foreign_user_cannot_open_share_page(client: TestClient):
    # other@ does not own the New York trip and must not reach its share admin.
    sign_in(client, INVITEE_EMAIL)
    assert client.get(f"/trips/{NY_TRIP_ID}/share").status_code == 404
    assert invite(client).status_code == 404
    assert share_count() == 0


def test_invitee_cannot_administer_the_share(client: TestClient):
    # The invitee holds the share but only the owner may administer it. Each
    # foreign attempt is a 404 that never distinguishes "not yours" from
    # "missing", and leaves the share untouched.
    share_id = invite_and_accept()
    sign_in(client, INVITEE_EMAIL)
    assert client.post(
        f"/shares/{share_id}/role", data={"role": "editor"}, follow_redirects=False
    ).status_code == 404
    assert client.post(
        f"/shares/{share_id}/sensitive",
        data={"show_sensitive": "on"},
        follow_redirects=False,
    ).status_code == 404
    assert client.post(
        f"/shares/{share_id}/revoke", follow_redirects=False
    ).status_code == 404
    share = only_share()
    assert share["status"] == "active"
    assert share["role"] == "viewer"
    assert share["show_sensitive"] is False


def test_unshared_viewer_cannot_read_trip(client: TestClient):
    # No share exists for other@ yet: the trip is a 404, not an empty page.
    sign_in(client, INVITEE_EMAIL)
    assert client.get(f"/shared/{NY_TRIP_ID}").status_code == 404


def test_mismatched_account_cannot_accept_invite(client: TestClient):
    # An invite addressed to other@ cannot be accepted by a different signed-in
    # account; the 404 keeps the invitation's existence undisclosed.
    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        invite(owner_client, email=INVITEE_EMAIL)
    share_id = only_share()["share_id"]

    # Re-sign the same fixture owner as the "wrong" acceptor.
    sign_in(client, OWNER_EMAIL)
    assert client.post(
        f"/shares/{share_id}/accept", follow_redirects=False
    ).status_code == 404
    assert only_share()["status"] == "invited"


def test_invite_token_digest_is_never_exposed(client: TestClient):
    # Delivery is by email match; the stored digest is bookkeeping only and must
    # never surface through the API surface (share page or read view).
    share_id = invite_and_accept()
    with closing(db.connect()) as connection:
        digest = connection.execute(
            "SELECT invite_token_digest FROM tripit_trip_shares WHERE share_id=?",
            (share_id,),
        ).fetchone()[0]
    assert digest  # the column is populated
    with fresh_client() as owner_client:
        sign_in(owner_client, OWNER_EMAIL)
        assert digest not in owner_client.get(f"/trips/{NY_TRIP_ID}/share").text
    sign_in(client, INVITEE_EMAIL)
    assert digest not in client.get(f"/shared/{NY_TRIP_ID}").text
