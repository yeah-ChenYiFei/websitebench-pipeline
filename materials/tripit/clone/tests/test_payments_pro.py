"""TripIt Pro membership journeys (Phase 7).

Offline runs use the frozen ``local-sandbox`` adapter. The hosted review profile
starts a server-owned Stripe test Checkout Session and activates Pro only after
the returned Session is retrieved and verified. These tests pin both surfaces:

* the three frozen sandbox outcomes — approval activates Pro, decline leaves the
  traveler free, and a retryable result converges to approval on resubmit
  exactly like the edX reference;
* a repeat submit while already Pro is an idempotent no-op — one subscription,
  one receipt — and the one-active partial unique index is the concurrency
  backstop against a double activation;
* an unknown scenario token is rejected without a charge or an entitlement;
* cancellation keeps the paid term (benefits persist, ``cancel_at_period_end``
  flips) and resume undoes it;
* the Stripe webhook rejects an unsigned, empty, oversize, or (under the
  local-sandbox profile) dormant event with 400, so no webhook can ever activate
  Pro off the hosted-checkout profile;
* Pro state is owner-scoped; and
* subscribing never touches the trips/plans the anchor "add a hotel to the New
  York trip" journey writes.
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
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-pro-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"
NY_TRIP_ID = "trip-traveler-new-york"

APPROVE = "sandbox-pro-approved"
DECLINE = "sandbox-pro-declined"
RETRY = "sandbox-pro-retryable"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_pro_tests")
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


def subscribe(client: TestClient, scenario: str):
    return client.post(
        "/pro/subscribe", data={"scenario": scenario}, follow_redirects=False
    )


def owner_for(subject: str = "traveler") -> str:
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, subject)


def pro_status(subject: str = "traveler") -> dict:
    with closing(db.connect()) as connection:
        return db.pro_status(connection, owner_for(subject))


def subscription_rows(subject: str = "traveler") -> list[dict]:
    with closing(db.connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM tripit_pro_subscriptions WHERE owner_key=? "
            "ORDER BY created_at, subscription_id",
            (owner_for(subject),),
        ).fetchall()
    return [dict(row) for row in rows]


def active_count(subject: str = "traveler") -> int:
    return sum(1 for row in subscription_rows(subject) if row["status"] == "active")


def receipt_jobs() -> list[dict]:
    with closing(db.connect()) as connection:
        rows = connection.execute(
            "SELECT purpose, recipient, status, is_simulation, variables_json, "
            "idempotency_key FROM websitebench_mail_jobs "
            "WHERE purpose='pro-receipt' ORDER BY created_at, idempotency_key"
        ).fetchall()
    return [dict(row) for row in rows]


def ny_plan_ids(subject: str = "traveler") -> set[str]:
    with closing(db.connect()) as connection:
        plans = db.list_plans_for_trip(connection, owner_for(subject), NY_TRIP_ID)
    return {plan["plan_id"] for plan in plans}


# ---------------------------------------------------------------------------
# free tier + upsell
# ---------------------------------------------------------------------------


def test_free_traveler_sees_upsell_and_manage_redirects(client: TestClient):
    sign_in(client)
    account = client.get("/account")
    assert account.status_code == 200
    assert 'data-pro-state="free"' in account.text
    assert "/pro/upgrade" in account.text

    upgrade = client.get("/pro/upgrade")
    assert upgrade.status_code == 200
    assert "$49" in upgrade.text
    for scenario in (APPROVE, DECLINE, RETRY):
        assert scenario in upgrade.text

    # A free traveler asking for the member dashboard is upsold, not shown it.
    manage = client.get("/pro/manage", follow_redirects=False)
    assert manage.status_code == 303
    assert manage.headers["location"] == "/pro/upgrade"


def test_stripe_profile_hides_scenarios_and_redirects_to_checkout(
    client: TestClient, monkeypatch
):
    sign_in(client)
    captured = {}

    class FakeGateway:
        def __init__(self, runtime):
            captured["runtime"] = runtime

        def create_checkout_session(self, *, flow, customer_email, line_items):
            captured["flow"] = flow
            captured["customer_email"] = customer_email
            captured["line_items"] = line_items
            return {"url": "https://checkout.stripe.com/c/pay/cs_test_tripit"}

    preparation = {
        "completed": False,
        "flow": {"flow_id": "payflow-tripit-test"},
        "customer_email": OWNER_EMAIL,
        "amount_minor": 4900,
    }
    monkeypatch.setattr(app_module, "_pro_stripe_enabled", lambda: True)
    monkeypatch.setattr(db, "prepare_pro_stripe_checkout", lambda owner: preparation)
    monkeypatch.setattr(app_module, "StripeTestGateway", FakeGateway)

    upgrade = client.get("/pro/upgrade")
    assert upgrade.status_code == 200
    assert "Continue to Stripe test checkout" in upgrade.text
    assert "no real charge will be made" in upgrade.text
    for scenario in (APPROVE, DECLINE, RETRY):
        assert scenario not in upgrade.text

    response = client.post("/pro/subscribe", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == (
        "https://checkout.stripe.com/c/pay/cs_test_tripit"
    )
    assert captured["customer_email"] == OWNER_EMAIL
    assert captured["line_items"] == (
        app_module.StripeTestLineItem(name="TripIt Pro (annual)", amount_minor=4900),
    )
    assert pro_status()["is_pro"] is False


def test_stripe_checkout_failure_is_generic_and_does_not_activate(
    client: TestClient, monkeypatch
):
    sign_in(client)
    monkeypatch.setattr(app_module, "_pro_stripe_enabled", lambda: True)
    monkeypatch.setattr(
        db,
        "prepare_pro_stripe_checkout",
        lambda owner: {
            "completed": False,
            "flow": {"flow_id": "payflow-tripit-test"},
            "customer_email": OWNER_EMAIL,
            "amount_minor": 4900,
        },
    )

    class UnavailableGateway:
        def __init__(self, runtime):
            raise app_module.StripeTestUnavailable("provider detail")

    monkeypatch.setattr(app_module, "StripeTestGateway", UnavailableGateway)
    response = client.post("/pro/subscribe", follow_redirects=False)
    assert response.status_code == 503
    assert "Stripe test checkout is temporarily unavailable" in response.text
    assert "provider detail" not in response.text
    assert pro_status()["is_pro"] is False


# ---------------------------------------------------------------------------
# the three frozen sandbox outcomes
# ---------------------------------------------------------------------------


def test_subscribe_approved_activates_and_receipts(client: TestClient):
    sign_in(client)
    response = subscribe(client, APPROVE)
    assert response.status_code == 303
    assert response.headers["location"] == "/pro/manage"

    status = pro_status()
    assert status["is_pro"] is True
    assert status["cancel_at_period_end"] is False
    assert status["current_period_end"] == "2027-08-04T13:00:00Z"

    jobs = receipt_jobs()
    assert len(jobs) == 1
    assert jobs[0]["recipient"] == OWNER_EMAIL
    assert jobs[0]["is_simulation"] == 1
    variables = json.loads(jobs[0]["variables_json"])
    assert variables["total"] == "$49.00"
    assert variables["receipt_id"] == status["receipt_id"]

    manage = client.get("/pro/manage")
    assert manage.status_code == 200
    assert 'data-pro-state="active"' in manage.text
    assert "August 4, 2027" in manage.text
    assert status["receipt_id"] in manage.text


def test_subscribe_declined_leaves_free(client: TestClient):
    sign_in(client)
    response = subscribe(client, DECLINE)
    assert response.status_code == 200
    assert 'data-payment-result="declined"' in response.text
    assert pro_status()["is_pro"] is False
    assert subscription_rows() == []
    assert receipt_jobs() == []


def test_retryable_converges_on_resubmit(client: TestClient):
    sign_in(client)
    first = subscribe(client, RETRY)
    assert first.status_code == 200
    assert 'data-payment-result="retryable"' in first.text
    assert pro_status()["is_pro"] is False

    # Resubmitting the retryable outcome converges to approval on the same flow.
    second = subscribe(client, RETRY)
    assert second.status_code == 303
    assert second.headers["location"] == "/pro/manage"
    assert pro_status()["is_pro"] is True
    assert active_count() == 1
    assert len(receipt_jobs()) == 1


# ---------------------------------------------------------------------------
# idempotency + concurrency backstop
# ---------------------------------------------------------------------------


def test_duplicate_subscribe_single_activation_single_receipt(client: TestClient):
    sign_in(client)
    assert subscribe(client, APPROVE).status_code == 303
    # A second submit while already Pro is a no-op that lands on the dashboard.
    again = subscribe(client, APPROVE)
    assert again.status_code == 303
    assert again.headers["location"] == "/pro/manage"
    assert active_count() == 1
    assert len(subscription_rows()) == 1
    assert len(receipt_jobs()) == 1


def test_one_active_subscription_index_is_enforced(client: TestClient):
    sign_in(client)
    assert subscribe(client, APPROVE).status_code == 303
    owner = owner_for()
    # The one-active partial unique index is the backstop a racing second
    # activation would hit: a direct second active row is rejected.
    with closing(db.connect()) as connection:
        with pytest.raises(Exception):
            connection.execute(
                "INSERT INTO tripit_pro_subscriptions "
                "(subscription_id, owner_key, plan_code, status, "
                "current_period_start, current_period_end, cancel_at_period_end, "
                "payment_flow_id, receipt_id, created_at, updated_at) "
                "VALUES (?, ?, 'pro-annual', 'active', ?, ?, 0, NULL, ?, ?, ?)",
                (
                    "prosub-duplicate",
                    owner,
                    "2026-08-04T13:00:00Z",
                    "2027-08-04T13:00:00Z",
                    "TPRO-DUP",
                    "2026-08-04T13:00:00Z",
                    "2026-08-04T13:00:00Z",
                ),
            )
            connection.commit()
    assert active_count() == 1


def test_unknown_scenario_rejected(client: TestClient):
    sign_in(client)
    response = subscribe(client, "sandbox-pro-freebie")
    assert response.status_code == 400
    assert pro_status()["is_pro"] is False
    assert subscription_rows() == []
    assert receipt_jobs() == []


# ---------------------------------------------------------------------------
# cancel keeps the paid term; resume undoes it
# ---------------------------------------------------------------------------


def test_cancel_keeps_period_end_then_resume(client: TestClient):
    sign_in(client)
    assert subscribe(client, APPROVE).status_code == 303
    before = pro_status()

    cancel = client.post("/pro/cancel", follow_redirects=False)
    assert cancel.status_code == 303
    assert cancel.headers["location"] == "/pro/manage"

    after = pro_status()
    # Benefits persist through the paid term: still Pro, still same end date.
    assert after["is_pro"] is True
    assert after["cancel_at_period_end"] is True
    assert after["current_period_end"] == before["current_period_end"]

    manage = client.get("/pro/manage")
    assert manage.status_code == 200
    assert "will end on" in manage.text
    assert "Resume membership" in manage.text

    resume = client.post("/pro/resume", follow_redirects=False)
    assert resume.status_code == 303
    resumed = pro_status()
    assert resumed["is_pro"] is True
    assert resumed["cancel_at_period_end"] is False


# ---------------------------------------------------------------------------
# Stripe webhook + return are dormant and safe
# ---------------------------------------------------------------------------


COMPLETED_EVENT = (
    '{"type":"checkout.session.completed","data":{"object":{"id":"cs_test_dormant"}}}'
)


def test_unsigned_webhook_rejected(client: TestClient):
    response = client.post("/api/stripe/webhook", content=COMPLETED_EVENT)
    assert response.status_code == 400
    assert response.json() == {"received": False}


def test_signed_but_dormant_webhook_rejected(client: TestClient):
    # Edge-verified, well-formed, but the local-sandbox profile has no stripe-test
    # adapter: it must still be refused so a webhook can never activate Pro here.
    response = client.post(
        "/api/stripe/webhook",
        content=COMPLETED_EVENT,
        headers={"x-websitebench-stripe-verified": "1"},
    )
    assert response.status_code == 400
    assert response.json() == {"received": False}


def test_empty_and_oversize_webhook_rejected(client: TestClient):
    headers = {"x-websitebench-stripe-verified": "1"}
    empty = client.post("/api/stripe/webhook", content=b"", headers=headers)
    assert empty.status_code == 400
    oversize = client.post(
        "/api/stripe/webhook", content=b"x" * (64 * 1024 + 1), headers=headers
    )
    assert oversize.status_code == 400


def test_stripe_return_dormant(client: TestClient):
    sign_in(client)
    response = client.get(
        "/pro/stripe-return?session_id=cs_test_dormant", follow_redirects=False
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# isolation + auth
# ---------------------------------------------------------------------------


def test_pro_state_is_owner_scoped(client: TestClient):
    sign_in(client, OWNER_EMAIL)
    assert subscribe(client, APPROVE).status_code == 303
    assert pro_status("traveler")["is_pro"] is True

    # The second account shares no entitlement and is upsold on /pro/manage.
    other = TestClient(app, base_url="https://testserver")
    sign_in(other, OTHER_EMAIL)
    assert pro_status("other")["is_pro"] is False
    manage = other.get("/pro/manage", follow_redirects=False)
    assert manage.status_code == 303
    assert manage.headers["location"] == "/pro/upgrade"
    assert active_count("other") == 0


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/pro/upgrade"),
        ("get", "/pro/manage"),
        ("post", "/pro/subscribe"),
        ("post", "/pro/cancel"),
        ("post", "/pro/resume"),
    ],
)
def test_pro_routes_require_auth(client: TestClient, method: str, path: str):
    call = getattr(client, method)
    response = call(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/account/login"


# ---------------------------------------------------------------------------
# the anchor journey's data is never touched by billing
# ---------------------------------------------------------------------------


def test_subscribe_does_not_touch_trips(client: TestClient):
    sign_in(client)
    before = ny_plan_ids()
    assert subscribe(client, APPROVE).status_code == 303
    client.post("/pro/cancel", follow_redirects=False)
    client.post("/pro/resume", follow_redirects=False)
    assert ny_plan_ids() == before
