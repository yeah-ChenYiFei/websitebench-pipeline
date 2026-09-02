import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_backend_database(tmp_path, monkeypatch):
    """Keep every test inside a disposable, contract-named site database."""
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE",
        str(tmp_path / "menufy.sqlite3"),
    )


def test_health():
    assert client.get("/healthz").json() == {"ok": True, "site_id": "menufy"}
    assert client.get("/__websitebench/health").json() == {"status": "ok"}


def test_home_and_deep_routes():
    for route in ["/", "/restaurants", "/restaurant/jaspers", "/checkout", "/signin"]:
        response = client.get(route)
        assert response.status_code == 200
        assert "Hungry? Order Food Online!" in response.text
        assert "https://order.menufy.com" not in response.text
    missing = client.get("/missing")
    assert missing.status_code == 200
    assert "We couldn't find that page." in missing.text


def test_restaurant_catalog_has_more_than_200_records():
    data = client.get("/api/restaurants").json()
    assert data["count"] >= 200
    assert len(data["restaurants"]) >= 200
    assert len({item["name"] for item in data["restaurants"]}) >= 200


def test_all_official_frontend_pages_are_indexed():
    data = client.get("/api/reference-pages").json()
    assert data["page_count"] == 235
    assert len(data["pages"]) == 235
    assert {item["kind"] for item in data["pages"]} == {
        "home",
        "state",
        "city",
        "cuisine",
        "restaurant",
        "brand",
    }
    for page in data["pages"]:
        assert client.get(f"/official/{page['id']}").status_code == 200


def test_search_filter_and_empty_state():
    assert client.get("/api/restaurants", params={"q": "pizza"}).json()["count"] > 0
    assert (
        client.get("/api/restaurants", params={"cuisine": "Chinese"}).json()["count"]
        > 0
    )
    assert (
        client.get(
            "/api/restaurants", params={"q": "zzzz-no-match-websitebench"}
        ).json()["count"]
        == 0
    )


def test_cart_is_server_authoritative_and_isolated():
    a, b = TestClient(app), TestClient(app)
    added = a.post(
        "/api/cart",
        json={
            "item": "meatballs",
            "size": "Large",
            "spice": "Hot",
            "extras": ["Cheese"],
            "note": "No onions",
            "qty": 2,
        },
    )
    assert added.status_code == 200
    body = added.json()
    assert body["items"][0]["qty"] == 2
    assert body["subtotal"] == 64
    assert body["total"] > body["subtotal"]
    assert b.get("/api/cart").json()["items"] == []
    line_id = body["items"][0]["line_id"]
    changed = a.patch(f"/api/cart/{line_id}", json={"qty": 3}).json()
    assert changed["items"][0]["qty"] == 3
    assert a.patch(f"/api/cart/{line_id}", json={"qty": 0}).json()["items"] == []


def test_cart_variants_update_independently():
    c = TestClient(app)
    for size, qty in [("Large", 1), ("Regular", 2)]:
        response = c.post(
            "/api/cart",
            json={
                "item": "meatballs",
                "size": size,
                "spice": "Mild",
                "extras": [],
                "note": size,
                "qty": qty,
            },
        )
        assert response.status_code == 200

    items = c.get("/api/cart").json()["items"]
    large = next(item for item in items if item["size"] == "Large")
    regular = next(item for item in items if item["size"] == "Regular")
    changed = c.patch(f"/api/cart/{large['line_id']}", json={"qty": 3}).json()
    assert {item["size"]: item["qty"] for item in changed["items"]} == {
        "Large": 3,
        "Regular": 2,
    }
    removed = c.patch(f"/api/cart/{large['line_id']}", json={"qty": 0}).json()
    assert [(item["line_id"], item["qty"]) for item in removed["items"]] == [
        (regular["line_id"], 2)
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"item": "meatballs", "qty": "not-a-number"},
        {"item": "meatballs", "size": "Family"},
        {"item": "meatballs", "spice": "Impossible"},
        {"item": "meatballs", "extras": ["not-a-menu-extra"]},
    ],
)
def test_invalid_cart_options_are_rejected(payload):
    response = client.post("/api/cart", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]


def test_https_session_cookie_matches_runtime_contract():
    c = TestClient(app, base_url="https://localhost")
    response = c.get("/api/cart")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-menufy-session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Domain=" not in cookie


def test_unknown_menu_item_rejected():
    assert client.post("/api/cart", json={"item": "not-real"}).status_code == 400


def test_favorite_toggles():
    c = TestClient(app)
    assert c.post("/api/favorites/Test%20Cafe").json()["favorite"] is True
    assert c.post("/api/favorites/Test%20Cafe").json()["favorite"] is False


def test_local_registration_signin_and_signout_closed_loop():
    c = TestClient(app)
    started = c.post(
        "/api/auth/register/start",
        json={
            "display_name": "Review User",
            "email": "review@example.test",
            "password": "Strong-pass-123!",
        },
    )
    assert started.status_code == 200
    code = started.json()["verification_code"]
    assert code and started.json()["delivery"] == "local-sandbox"
    completed = c.post("/api/auth/register/verify", json={"code": code})
    assert completed.status_code == 200
    assert completed.json()["account"]["email_normalized"] == "review@example.test"
    assert c.get("/api/auth/session").json()["authenticated"] is True
    assert c.post("/api/auth/signout").json()["authenticated"] is False
    signed_in = c.post(
        "/api/auth/signin",
        json={"email": "review@example.test", "password": "Strong-pass-123!"},
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["authenticated"] is True


def test_corporate_home_and_auth_routes_are_rendered():
    page = client.get("/official/132")
    assert page.status_code == 200
    assert "corporate-home.png" in page.text
    for route in ("/signin", "/register", "/account"):
        response = client.get(route)
        assert response.status_code == 200
        assert "/api/auth/" in response.text


def test_all_captured_brand_pages_use_singlefile_desktop_snapshots():
    expected = {
        5: "accessibility.png",
        31: "careers.png",
        33: "vietnamese.png",
        44: "terms.png",
        107: "spanish.png",
        131: "help.png",
        146: "hr-demo.png",
        147: "hr-demo.png",
        173: "privacy.png",
        177: "referral.png",
        178: "hungerrush-home.png",
        210: "demo.png",
        231: "arabic.png",
        232: "hindi.png",
        233: "thai.png",
        234: "manager.png",
        235: "chinese.png",
    }
    page = client.get("/official/5")
    assert page.status_code == 200
    for page_id, filename in expected.items():
        assert f"{page_id}:'{filename}'" in page.text
        asset = client.get(f"/static/{filename}")
        assert asset.status_code == 200
        assert asset.headers["content-type"] == "image/png"
    assert "Restaurant technology and online ordering by Menufy" not in page.text
