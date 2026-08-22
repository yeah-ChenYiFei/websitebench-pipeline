from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import uuid

from fastapi.testclient import TestClient
from urllib.parse import urlencode

from app import ADMIN_TOKEN, BACKEND, FIXTURE, SESSION_COOKIE, SESSION_SECRET, _encode_session, _load_session_secret, app


client = TestClient(app)


def reset() -> None:
    response = client.post("/__admin/reset", headers={"X-WebsiteBench-Admin-Token": ADMIN_TOKEN})
    assert response.status_code == 200


def configured_owner(owner: str, quantity: str = "trace-six-cup") -> None:
    client.cookies.set(SESSION_COOKIE, _encode_session(owner))
    response = client.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "to-quantity", "preparation": "freshly-ground", "taste": "curators-choice"},
    )
    assert response.status_code == 200
    response = client.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "to-review", "quantity": quantity, "cadence": "4"},
    )
    assert response.status_code == 200
    response = client.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "checkout", "plan": "pay-per-delivery"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def checkout_payload(owner: str, scenario: str = "sandbox-approved") -> dict[str, str]:
    return {
        **FIXTURE,
        "owner": owner,
        "scenario_id": scenario,
        "idempotency_key": f"checkout-{owner}",
    }


def test_health_and_catalogue_count() -> None:
    assert client.get("/__websitebench/health").json() == {"status": "ok"}
    assert client.get("/healthz").json() == {"ok": True, "site_id": "bean-box"}
    result = client.get("/api/catalogue/count").json()
    assert result["coffee_records"] == 240


def test_catalogue_search_filter_pagination_detail_and_zero_result() -> None:
    response = client.get("/coffee?q=Morning&roast=light&page=1")
    assert response.status_code == 200
    assert "coffees · page" in response.text
    assert client.get("/coffee?page=14").status_code == 200
    detail = client.get("/coffee/morning-bloom-001")
    assert detail.status_code == 200
    assert "Morning Bloom 001" in detail.text
    zero = client.get("/coffee?q=definitely-no-such-coffee")
    assert zero.status_code == 200
    assert "No coffees found" in zero.text
    assert client.get("/coffee?page=abc").status_code == 422
    assert client.get("/coffee?page=1001").status_code == 422


def test_subscription_has_more_than_five_meaningful_operations_and_local_approval() -> None:
    reset()
    owner = "fixture-actor-mainline"
    configured_owner(owner)
    checkout = client.get(f"/checkout?owner={owner}")
    assert checkout.status_code == 200
    assert "Payment simulation" in checkout.text
    review = client.get("/coffee-subscription/configure")
    assert "6 cups" in review.text
    assert "Freshly Ground" in review.text
    assert "data-quantity-option='trace-six-cup'" in review.text
    assert "TRACE COMPATIBILITY" in review.text
    response = client.post("/checkout", data=checkout_payload(owner))
    assert response.status_code == 200
    assert "Simulation complete" in response.text
    assert "6 cups" in response.text
    assert "No subscription, email, address or payment was sent" in response.text
    duplicate = client.post("/checkout", data=checkout_payload(owner))
    assert duplicate.status_code == 200
    assert "Simulation complete" in duplicate.text
    client.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "back-quantity"},
    )
    client.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "to-review", "quantity": "duo", "cadence": "4"},
    )
    stale = client.post("/checkout", data=checkout_payload(owner))
    assert stale.status_code == 409
    assert "different order configuration" in stale.text


def test_checkout_declined_retryable_and_forbidden_payment_fields() -> None:
    reset()
    declined_owner = "fixture-actor-declined"
    configured_owner(declined_owner)
    declined = client.post("/checkout", data=checkout_payload(declined_owner, "sandbox-declined"))
    assert declined.status_code == 402
    assert "declined" in declined.text
    retry_owner = "fixture-actor-retryable"
    configured_owner(retry_owner)
    retry = client.post("/checkout", data=checkout_payload(retry_owner, "sandbox-retry"))
    assert retry.status_code == 409
    assert "retryable" in retry.text
    forbidden_owner = "fixture-actor-forbidden"
    configured_owner(forbidden_owner)
    payload = checkout_payload(forbidden_owner)
    payload["card_number"] = "synthetic-but-forbidden"
    forbidden = client.post("/checkout", data=payload)
    assert forbidden.status_code == 422
    assert "payment credentials are forbidden" in forbidden.text
    payload = checkout_payload(forbidden_owner)
    payload["pan"] = "unknown-payment-alias"
    assert client.post("/checkout", data=payload).status_code == 422


def test_checkout_accepts_only_exact_synthetic_fixture() -> None:
    reset()
    owner = "fixture-actor-boundary"
    configured_owner(owner)
    payload = checkout_payload(owner)
    payload["address"] = "A real or arbitrary address is rejected"
    response = client.post("/checkout", data=payload)
    assert response.status_code == 422
    assert "synthetic fixture exactly" in response.text
    duplicate_items = list(checkout_payload(owner).items())
    duplicate_items.extend([("address", "real-value-forbidden"), ("address", FIXTURE["address"])])
    duplicate = client.post(
        "/checkout",
        content=urlencode(duplicate_items),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert duplicate.status_code == 422
    assert "Duplicate or oversized" in duplicate.text


def test_cart_isolated_by_actor() -> None:
    reset()
    first = "fixture-actor-cart-a"
    second = "fixture-actor-cart-b"
    client.cookies.set(SESSION_COOKIE, _encode_session(first))
    added = client.post("/cart/add", data={"owner": first, "coffee_id": "1"}, follow_redirects=False)
    assert added.status_code == 303
    assert "Morning Bloom 001" in client.get("/cart").text
    foreign = TestClient(app)
    foreign.cookies.set(SESSION_COOKIE, _encode_session(second))
    assert "Your cart is empty" in foreign.get("/cart").text
    assert foreign.post("/cart/add", data={"owner": first, "coffee_id": "1"}).status_code == 403


def test_runtime_database_is_site_bound() -> None:
    assert BACKEND.config.site_id == "bean-box"
    assert BACKEND.lifecycle.database_path.name == "bean-box.sqlite3"
    assert BACKEND.lifecycle.database_path.parent == (BACKEND.lifecycle.runtime.source_path.parent.parent / "data").resolve()
    assert BACKEND.session_cookie["name"].startswith("__Host-")
    assert BACKEND.session_cookie["secure"] is True
    assert _load_session_secret() == _load_session_secret()


def test_session_secret_survives_process_restart() -> None:
    observed = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import app,hashlib;print(hashlib.sha256(app.SESSION_SECRET).hexdigest())",
        ],
        text=True,
    ).strip()
    assert observed == hashlib.sha256(SESSION_SECRET).hexdigest()


def test_runtime_html_contains_no_remote_dependency() -> None:
    for route in ("/", "/coffee", "/coffee-subscription/configure", "/checkout"):
        response = client.get(route)
        assert response.status_code == 200
        assert "https://beanbox.com" not in response.text
        assert "http://" not in response.text
        assert "https://" not in response.text


def test_dialog_and_dynamic_status_accessibility_semantics() -> None:
    home = client.get("/")
    assert "role='dialog'" in home.text
    assert "aria-modal='true'" in home.text
    owner = "fixture-actor-accessible-status"
    configured_owner(owner)
    declined = client.post("/checkout", data=checkout_payload(owner, "sandbox-declined"))
    assert "role='alert'" in declined.text
    approved = client.post("/checkout", data=checkout_payload(owner, "sandbox-approved"))
    assert "role='status'" in approved.text


def test_json_semantic_seams_follow_session_and_payment_boundaries() -> None:
    reset()
    owner = "fixture-actor-json-seam"
    client.cookies.set(SESSION_COOKIE, _encode_session(owner))
    added = client.post("/api/cart/items", json={"coffee_id": 1})
    assert added.status_code == 201
    assert added.json()["cart_count"] == 1
    assert client.get("/api/cart").json()["cart_count"] == 1
    assert client.get("/api/cart?owner=fixture-actor-foreign").status_code == 403
    valid = client.post("/api/checkout/validate", json={"scenario_id": "sandbox-approved"})
    assert valid.status_code == 200
    assert valid.json()["adapter"] == "local-sandbox"
    assert client.post("/api/checkout/validate", json={"scenario_id": "sandbox-approved", "pan": "forbidden"}).status_code == 422
    assert client.post("/api/cart/items", content="{", headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/api/cart/items", content="coffee_id=1", headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 415
    assert client.post("/api/cart/items", json={"coffee_id": True}).status_code == 422
    assert client.post("/api/cart/items", json={"coffee_id": 1.9}).status_code == 422
    assert client.post("/api/checkout/validate", content="[", headers={"content-type": "application/json"}).status_code == 400


def test_not_found_and_account_boundary() -> None:
    for route in ("/roasters", "/about", "/contact", "/blog", "/resources", "/terms", "/privacy", "/returns"):
        response = client.get(route)
        assert response.status_code == 200
        assert "data-content-status='scope-limited'" in response.text
        assert "https://" not in response.text
    assert client.get("/missing-route").status_code == 404
    account = client.get("/account")
    assert account.status_code == 200
    assert "Create an account" in account.text


def test_local_auth_subscription_lifecycle_orders_and_recovery() -> None:
    reset()
    browser = TestClient(app, base_url="https://testserver")
    email = f"student-{uuid.uuid4().hex[:12]}@example.test"
    password = "local-password-123"
    assert browser.get("/account/register").status_code == 200
    started = browser.post(
        "/account/register",
        data={"phase": "start", "display_name": "Local Student", "email": email, "password": password},
    )
    assert started.status_code == 200
    code = re.search(r"data-local-code>(\d+)<", started.text)
    assert code is not None
    verified = browser.post(
        "/account/register", data={"phase": "verify", "code": code.group(1)}, follow_redirects=False
    )
    assert verified.status_code == 303
    account = browser.get("/account")
    assert "Welcome, Local Student" in account.text

    configured = browser.get("/coffee-subscription/configure")
    owner_match = re.search(r"name='owner' value='([^']+)'", configured.text)
    assert owner_match is not None
    owner = owner_match.group(1)
    assert owner.startswith("account:")
    assert browser.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "to-quantity", "preparation": "freshly-ground", "taste": "curators-choice"},
    ).status_code == 200
    assert browser.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "to-review", "quantity": "trace-six-cup", "cadence": "4"},
    ).status_code == 200
    assert browser.post(
        "/coffee-subscription/configure",
        data={"owner": owner, "action": "checkout", "plan": "pay-per-delivery"},
        follow_redirects=False,
    ).status_code == 303
    checkout = browser.post("/checkout", data=checkout_payload(owner))
    assert checkout.status_code == 200
    assert "Simulation complete" in checkout.text

    management = browser.get("/account/subscriptions")
    assert management.status_code == 200
    subscription_id = re.search(r"(SUB-[A-F0-9]{10})", management.text)
    assert subscription_id is not None
    sid = subscription_id.group(1)
    assert browser.post(
        f"/account/subscriptions/{sid}",
        data={"action": "modify", "preparation": "whole-bean", "cadence": "6"},
        follow_redirects=False,
    ).status_code == 303
    for action in ("skip", "pause", "reactivate", "cancel", "reactivate"):
        assert browser.post(
            f"/account/subscriptions/{sid}", data={"action": action}, follow_redirects=False
        ).status_code == 303
    final = browser.get("/account/subscriptions")
    assert "Status: <strong>active</strong>" in final.text
    assert "skipped 1" in final.text
    orders = browser.get("/account/orders")
    assert "BB-" in orders.text and "$22.45" in orders.text

    assert browser.post("/account/signout", follow_redirects=False).status_code == 303
    signed_in = browser.post(
        "/account/signin", data={"email": email, "password": password}, follow_redirects=False
    )
    assert signed_in.status_code == 303
    assert "Welcome, Local Student" in browser.get("/account").text
    browser.post("/account/signout", follow_redirects=False)

    reset_started = browser.post("/account/password-reset", data={"phase": "start", "email": email})
    reset_code = re.search(r"data-local-code>(\d+)<", reset_started.text)
    assert reset_code is not None
    completed = browser.post(
        "/account/password-reset",
        data={"phase": "complete", "code": reset_code.group(1), "new_password": "new-local-password-123"},
        follow_redirects=False,
    )
    assert completed.status_code == 303
    browser.post("/account/signout", follow_redirects=False)
    assert browser.post(
        "/account/signin", data={"email": email, "password": "new-local-password-123"}, follow_redirects=False
    ).status_code == 303


def test_auth_and_subscription_permissions_fail_closed() -> None:
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get("/account/subscriptions").status_code == 401
    assert anonymous.get("/account/orders").status_code == 401
    assert anonymous.post(
        "/account/register",
        data={"phase": "start", "display_name": "Real Data", "email": "person@example.com", "password": "local-password-123"},
    ).status_code == 422
    assert anonymous.post(
        "/account/password-reset", data={"phase": "start", "email": "person@example.com"}
    ).status_code == 422
    assert anonymous.post("/account/subscriptions/SUB-FOREIGN", data={"action": "cancel"}).status_code == 401


def test_admin_reset_clears_accounts_sessions_and_allows_fixture_reseed() -> None:
    browser = TestClient(app, base_url="https://testserver")
    email = f"reset-{uuid.uuid4().hex[:12]}@example.test"
    password = "local-password-123"
    browser.get("/account/register")
    started = browser.post(
        "/account/register",
        data={"phase": "start", "display_name": "Reset Fixture", "email": email, "password": password},
    )
    code = re.search(r"data-local-code>(\d+)<", started.text)
    assert code is not None
    assert browser.post(
        "/account/register", data={"phase": "verify", "code": code.group(1)}, follow_redirects=False
    ).status_code == 303
    assert "Reset Fixture" in browser.get("/account").text

    reset_response = browser.post(
        "/__admin/reset", headers={"X-WebsiteBench-Admin-Token": ADMIN_TOKEN}
    )
    assert reset_response.status_code == 200
    anonymous_account = browser.get("/account")
    assert "Create an account" in anonymous_account.text
    assert browser.get("/account/subscriptions").status_code == 401
    assert browser.get("/account/orders").status_code == 401
    assert browser.post(
        "/account/signin", data={"email": email, "password": password}
    ).status_code == 401
    reseed = browser.post(
        "/account/register",
        data={"phase": "start", "display_name": "Reset Fixture", "email": email, "password": password},
    )
    assert reseed.status_code == 200
    assert re.search(r"data-local-code>(\d+)<", reseed.text) is not None


def test_forward_migration_from_v1_preserves_existing_order() -> None:
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE bean_box_orders(order_id TEXT PRIMARY KEY,owner TEXT NOT NULL,idempotency_key TEXT NOT NULL,payment_flow_id TEXT NOT NULL,status TEXT NOT NULL,amount_minor INTEGER NOT NULL,snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(owner,idempotency_key))"
    )
    connection.execute(
        "INSERT INTO bean_box_orders VALUES ('BB-V1','fixture-v1','key-v1','flow-v1','local-confirmed',2245,'{}','2026-01-01T00:00:00Z')"
    )
    from backend import business

    business.migrate(connection)
    business.migrate(connection)
    assert connection.execute("SELECT order_id FROM bean_box_orders").fetchone()[0] == "BB-V1"
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('bean_box_subscriptions','bean_box_subscription_events')"
    ).fetchone()[0] == 2
    assert [row[0] for row in connection.execute("SELECT version FROM bean_box_schema_versions ORDER BY version")] == [1, 2]
