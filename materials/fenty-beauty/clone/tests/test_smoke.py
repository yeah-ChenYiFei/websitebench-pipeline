from fastapi.testclient import TestClient

from app import app
from backend import store


client = TestClient(app, base_url="https://testserver")


def setup_function() -> None:
    store.reset()
    client.cookies.clear()


def test_health_and_routes() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "site_id": "fenty-beauty"}
    for path in (
        "/en-ca",
        "/en-ca/collections/makeup-shop-all",
        "/en-ca/search?q=foundation",
        "/en-ca/products/pro-filtr-soft-matte-longwear-foundation-420",
        "/en-ca/cart",
        "/en-ca/checkout",
        "/en-ca/account/login",
        "/en-ca/pages/help-center",
    ):
        assert client.get(path).status_code == 200
    missing = client.get("/en-ca/not-a-real-page")
    assert missing.status_code == 404
    assert "Fenty Beauty" in missing.text
    assert 'data-route="/en-ca/not-a-real-page"' in missing.text


def test_catalog_search_sort_and_no_results() -> None:
    found = client.get("/api/catalog?q=foundation&sort=price-low").json()
    assert found["products"][0]["id"] == "foundation"
    assert "185N" in found["products"][0]["variants"]
    assert client.get("/api/catalog?q=zzzz-no-match-websitebench").json()["products"] == []
    sorted_rows = client.get("/api/catalog?sort=price-high").json()["products"]
    assert sorted_rows[0]["price"] >= sorted_rows[-1]["price"]


def test_core_cart_checkout_and_restore() -> None:
    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    foundation = client.post(
        "/api/cart/add",
        json={"product_id": "foundation", "variant": "185N", "size": "Standard 32 mL", "quantity": 1},
    )
    assert foundation.status_code == 201
    powder = client.post(
        "/api/cart/add",
        json={"product_id": "powder", "variant": "Universal", "size": "Standard 8.5 g", "quantity": 1},
    )
    assert powder.status_code == 201
    cart = powder.json()
    assert cart["count"] == 2
    assert {row["product"]["id"] for row in cart["items"]} == {"foundation", "powder"}
    preview = client.post("/api/checkout/preview", json={"promo": "FENTY10"}).json()
    assert preview["discount"] > 0
    assert preview["payment_adapter"] == "local-sandbox"
    assert preview["is_simulation"] is True
    removed = client.post(
        "/api/cart/update",
        json={"product_id": "powder", "variant": "Universal", "size": "Standard 8.5 g", "removed": True},
    ).json()
    assert any(row["removed"] for row in removed["items"])
    restored = client.post(
        "/api/cart/update",
        json={"product_id": "powder", "variant": "Universal", "size": "Standard 8.5 g", "removed": False},
    ).json()
    assert restored["count"] == 2


def test_registration_login_favorites_address_and_orders() -> None:
    client.get("/api/bootstrap")
    registered = client.post(
        "/api/auth/register",
        json={"display_name": "WebsiteBench Shopper", "email": "shopper@example.test", "password": "WebsiteBench!23"},
    )
    assert registered.status_code == 201
    assert registered.json()["account"]["email_normalized"] == "shopper@example.test"
    saved = client.post("/api/favorites/toggle", json={"product_id": "foundation"})
    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    address = client.post(
        "/api/account/address",
        json={"full_name": "WebsiteBench Shopper", "line1": "100 Test Street", "city": "Toronto", "province": "Ontario", "postal_code": "M5V 2T6", "country": "Canada"},
    )
    assert address.status_code == 200
    assert address.json()["addresses"][0]["postal_code"] == "M5V 2T6"
    orders = client.get("/api/account").json()["orders"]
    assert len(orders) == 1
    reordered = client.post(f"/api/orders/{orders[0]['order_id']}/reorder", json={})
    assert reordered.status_code == 200
    assert reordered.json()["cart"]["count"] == 2
    assert client.post("/api/auth/logout", json={}).json()["signed_out"] is True
    assert client.get("/api/account").status_code == 401


def test_required_field_and_recovery_validation() -> None:
    client.get("/api/bootstrap")
    invalid = client.post("/api/auth/register", json={"display_name": "", "email": "bad", "password": "short"})
    assert invalid.status_code == 422
    assert client.post("/api/auth/recovery-preview", json={"email": ""}).status_code == 422
    preview = client.post("/api/auth/recovery-preview", json={"email": "nobody@example.test"})
    assert preview.status_code == 200
    assert preview.json()["sent"] is False


def test_runtime_headers_block_remote_dependencies() -> None:
    response = client.get("/en-ca")
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "https://" not in response.text
    assert "http://" not in response.text
