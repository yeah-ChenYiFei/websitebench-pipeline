from fastapi.testclient import TestClient

import app as app_module
from app import app


# HTTPS base so the runtime's Secure session cookie (__Host- prefixed) is
# stored and replayed exactly as in production; http:// would drop it.
client = TestClient(app, base_url="https://testserver")


def _order_payload(scenario: str = "sandbox-approved", box: str = "6-pack") -> dict:
    flavors = [
        "creme-brulee-cookie",
        "cannoli-cookie",
        "chocolate-tiramisu-cake",
        "swedish-candy-cookie-ft-bubs",
        "vanilla-chocolate-gelato-cookie",
        "stroopwafel-sandwich-cookie",
    ]
    size = {"4-pack": 4, "6-pack": 6, "12-pack": 12}[box]
    chosen = (flavors * 2)[:size]
    return {
        "mode": "pickup",
        "store_slug": "tx114th",
        "items": [{"box": box, "flavors": chosen}],
        "contact": {"name": "WebsiteBench Test " + box, "time": "ASAP"},
        "scenario_id": scenario,
    }


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["site_id"] == "crumbl-cookies"


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Crumbl Cookies" in response.text
    assert "Weekly Flavors" in response.text
    assert "Classic Flavors" in response.text
    assert "Creme Brûlée Cookie" in response.text
    assert "https://" not in response.text


def test_home_csp() -> None:
    response = client.get("/")
    policy = response.headers.get("content-security-policy", "")
    assert "default-src 'self'" in policy


def test_menu_answers_branded_not_found() -> None:
    # Anonymous /menu on the source answers the branded 404; the weekly menu
    # surface lives on the home page. The clone reproduces that answer.
    response = client.get("/menu")
    assert response.status_code == 404
    assert "Oh no!" in response.text


def test_flavor_profile() -> None:
    response = client.get("/profiles/creme-brulee-cookie")
    assert response.status_code == 200
    assert "Creme Brûlée Cookie" in response.text
    assert "620 cal" in response.text
    assert "Nutrition" in response.text
    assert "https://" not in response.text


def test_flavor_profile_unknown() -> None:
    assert client.get("/profiles/not-a-real-flavor").status_code == 404


def test_stores() -> None:
    response = client.get("/stores")
    assert response.status_code == 200
    assert "Select a Store" in response.text
    assert "114th" in response.text
    assert len(app_module.FROZEN_STORES) >= 5


def test_store_detail() -> None:
    response = client.get("/stores/tx114th")
    assert response.status_code == 200
    assert "114th" in response.text
    assert "Lubbock" in response.text


def test_store_detail_unknown() -> None:
    assert client.get("/stores/not-a-store").status_code == 404


def test_order_landing() -> None:
    response = client.get("/order")
    assert response.status_code == 200
    assert "Start an Order" in response.text
    assert "Pickup" in response.text
    assert "Delivery" in response.text


def test_order_app_shell() -> None:
    for path in ("/order/pickup", "/order/delivery", "/order/carry_out"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'src="/static/site/order-boot.js"' in response.text
        assert 'src="/static/site/order.js"' in response.text
    boot = client.get("/static/site/order-boot.js")
    assert boot.status_code == 200
    assert "__CRUMBL_FLAVORS__" in boot.text
    assert "__CRUMBL_STORES__" in boot.text


def _place_order(box: str = "6-pack") -> str:
    response = client.post(
        "/api/orders", json=_order_payload("sandbox-approved", box=box)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["placed"] is True
    assert body["order_id"].startswith("CR-")
    assert body["amount_minor"] > 0
    return body["order_id"]


def test_order_approved() -> None:
    order_id = _place_order(box="6-pack")
    assert order_id.startswith("CR-")


def test_order_lookup() -> None:
    order_id = _place_order(box="4-pack")
    response = client.get(f"/api/orders/{order_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["mode"] == "pickup"
    assert body["amount_minor"] > 0
    assert body["status"] == "placed"


def test_order_lookup_unknown() -> None:
    assert client.get("/api/orders/CR-999999").status_code == 404


def test_order_voucher_and_tip() -> None:
    payload = _order_payload("sandbox-approved", box="4-pack")
    payload["voucher_code"] = "CRUMBL10"
    payload["tip_minor"] = 300
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 201
    body = response.json()
    # 4-pack subtotal 1599 -> 10% off 160 -> tax on 1439 -> tip 300
    assert body["amount_minor"] == 1439 + round(1439 * 0.0825) + 300


def test_order_invalid_voucher() -> None:
    payload = _order_payload("sandbox-approved", box="4-pack")
    payload["voucher_code"] = "BOGUS"
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422
    assert "incorrect" in response.json()["error"].lower()


def test_order_excessive_tip_rejected() -> None:
    payload = _order_payload("sandbox-approved", box="4-pack")
    payload["tip_minor"] = 100001
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422


def test_order_confirmation_mail_enqueued() -> None:
    order_id = _place_order(box="12-pack")
    from backend import orders as orders_module

    backend, _auth = orders_module.services()
    with backend.lifecycle.connection() as connection:
        row = connection.execute(
            "SELECT purpose, status FROM websitebench_mail_jobs "
            "WHERE idempotency_key = ?",
            (f"crumbl.mail:{order_id}",),
        ).fetchone()
    assert row is not None
    assert row["purpose"] == "order-confirmation"
    assert row["status"] == "LOCAL_SIMULATION"


def test_order_declined() -> None:
    response = client.post("/api/orders", json=_order_payload("sandbox-declined", box="4-pack"))
    assert response.status_code == 402
    assert response.json()["placed"] is False
    assert response.json()["status"] == "declined"


def test_order_retryable() -> None:
    payload = _order_payload("sandbox-retry", box="12-pack")
    payload["items"] = [
        {"box": "12-pack", "flavors": ["creme-brulee-cookie"] * 12}
    ]
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 402
    assert response.json()["status"] == "retryable"


def test_order_validation() -> None:
    bad = _order_payload(box="4-pack")
    bad["contact"] = {"name": ""}
    assert client.post("/api/orders", json=bad).status_code == 422
    bad2 = _order_payload(box="6-pack")
    bad2["items"] = [
        {"box": "6-pack", "flavors": ["creme-brulee-cookie"] * 7}
    ]
    assert client.post("/api/orders", json=bad2).status_code == 422


def test_order_rejects_payment_fields() -> None:
    bad = _order_payload(box="4-pack")
    bad["card_number"] = "4242424242424242"
    response = client.post("/api/orders", json=bad)
    assert response.status_code == 422
    assert "card" in response.json()["error"].lower()


def test_delivery_requires_address() -> None:
    bad = _order_payload(box="4-pack")
    bad["mode"] = "delivery"
    bad["contact"] = {"name": "X"}
    assert client.post("/api/orders", json=bad).status_code == 422


def test_login_shell() -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign In" in response.text
    assert "Send Confirmation Code" in response.text
    assert "no real text messages" in response.text
    assert 'src="/static/site/auth.js"' in response.text
    assert "https://" not in response.text


def test_account_fail_closed() -> None:
    # Anonymous member surface is unavailable; the source answers with the
    # sign-in shell. The clone reproduces that fail-closed behavior.
    response = client.get("/account")
    assert response.status_code == 200
    assert "Sign In" in response.text


def test_marketing_pages() -> None:
    # Every marketing path must render its own title and body — a classic
    # loop-closure bug would make them all render the last page instead.
    from app import _MARKETING_PAGES

    for path, (title, _body) in _MARKETING_PAGES.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert f"<title>{title} | Crumbl Cookies</title>" in response.text, path
        assert f"<h1>{title}</h1>" in response.text, path
        assert "https://" not in response.text, path


def test_unknown_route() -> None:
    assert client.get("/not-in-scope").status_code == 404


def test_external_boundary() -> None:
    response = client.get("/external/merch.crumbl.com")
    assert response.status_code == 200
    assert "External link" in response.text
    assert "merch.crumbl.com" in response.text


def test_external_boundary_slash_path() -> None:
    # Footer legal link embeds a host/path slug; {slug:path} must accept it.
    response = client.get("/external/www.openstreetmap.org/copyright")
    assert response.status_code == 200
    assert "www.openstreetmap.org/copyright" in response.text


def test_static_asset_mirror() -> None:
    response = client.get(
        "/static/assets/2026-08-20.crumbl-cookies-r1/crumblcookies.com/favicons/apple-touch-icon.png"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_profile_image_served() -> None:
    # The creme-brulee profile references its frozen OverheadAerial image.
    response = client.get(
        "/static/assets/2026-08-20.crumbl-cookies-r1/crumbl.video/"
        "8672b58c-8b80-4b5d-ae7e-f2cdf65d8664_CremeBruleeCookie_OverheadAerial_NoShadow_TECH.png"
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# local simulated auth
# ---------------------------------------------------------------------------


def test_auth_register_and_signin() -> None:
    # register a new phone
    r = client.post(
        "/api/auth/begin", json={"phone": "5551112222", "display_name": "Reg User"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_existing"] is False
    assert len(body["verification_code"]) == 6

    # wrong code rejected
    r = client.post(
        "/api/auth/verify",
        json={
            "session_token": body["session_token"],
            "code": "000000",
            "is_existing": False,
            "expected_code": body["verification_code"],
            "email": body.get("email"),
        },
    )
    assert r.status_code == 422

    # correct code -> authenticated
    r = client.post(
        "/api/auth/verify",
        json={
            "session_token": body["session_token"],
            "code": body["verification_code"],
            "is_existing": False,
            "expected_code": body["verification_code"],
            "email": body.get("email"),
        },
    )
    assert r.status_code == 200
    assert r.json()["authenticated"] is True

    # me + account page
    me = client.get("/api/auth/me")
    assert me.json()["authenticated"] is True
    assert me.json()["display_name"] == "Reg User"
    account = client.get("/account")
    assert "My Account" in account.text

    # signout clears
    client.post("/api/auth/signout")
    assert client.get("/api/auth/me").json()["authenticated"] is False


def test_auth_login_existing() -> None:
    # register once
    r = client.post(
        "/api/auth/begin", json={"phone": "5553334444", "display_name": "Dana"}
    )
    d = r.json()
    client.post(
        "/api/auth/verify",
        json={
            "session_token": d["session_token"],
            "code": d["verification_code"],
            "is_existing": False,
            "expected_code": d["verification_code"],
            "email": d.get("email"),
        },
    )
    client.post("/api/auth/signout")

    # sign in again with the same phone
    r = client.post(
        "/api/auth/begin", json={"phone": "5553334444", "display_name": "Dana"}
    )
    assert r.status_code == 200
    d = r.json()
    assert d["is_existing"] is True
    r = client.post(
        "/api/auth/verify",
        json={
            "session_token": d["session_token"],
            "code": d["verification_code"],
            "is_existing": True,
            "expected_code": d["verification_code"],
            "email": d.get("email"),
        },
    )
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    me = client.get("/api/auth/me")
    assert me.json()["display_name"] == "Dana"
    client.post("/api/auth/signout")


def test_auth_invalid_phone() -> None:
    r = client.post(
        "/api/auth/begin", json={"phone": "555", "display_name": "X"}
    )
    assert r.status_code == 422
    assert "invalid" in r.json()["error"].lower()


def test_auth_begin_rate_limited() -> None:
    """Re-begging the same phone inside the store cooldown is 429, not 500."""

    r = client.post(
        "/api/auth/begin", json={"phone": "5552226666", "display_name": "R"}
    )
    assert r.status_code == 200
    r = client.post(
        "/api/auth/begin", json={"phone": "5552226666", "display_name": "R"}
    )
    assert r.status_code == 429
    assert "rate limited" in r.json()["error"].lower()


def test_duplicate_order_conflict() -> None:
    """Re-submitting an identical cart must not 500; it returns 409."""

    order_id = _place_order(box="6-pack")
    payload = _order_payload("sandbox-approved", box="6-pack")
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 409
    assert order_id.startswith("CR-")
