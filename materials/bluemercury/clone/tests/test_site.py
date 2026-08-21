from __future__ import annotations

import io
import atexit
import html
import json
import os
import sqlite3
import tempfile
import urllib.parse
import re
from pathlib import Path

_test_data = tempfile.TemporaryDirectory(prefix="bluemercury-tests-")
atexit.register(_test_data.cleanup)
os.environ["DATA_DIR"] = _test_data.name
os.environ["BLUEMERCURY_ADMIN_RESET_TOKEN"] = "test-reset-token-0123456789abcdef-0123456789"

import app as candidate
from backend import business


def call(path="/", method="GET", query="", data=None, session="test-session-000000000001", *, headers=None, raw_body=None, content_type="application/x-www-form-urlencoded", content_length=None, cookie=None):
    payload = raw_body if raw_body is not None else urllib.parse.urlencode(data or {}).encode()
    captured = {}
    def start(status, headers): captured.update(status=status, headers=dict(headers))
    environ = {
        "PATH_INFO": path, "REQUEST_METHOD": method, "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(payload)) if content_length is None else str(content_length),
        "CONTENT_TYPE": content_type, "wsgi.input": io.BytesIO(payload),
        "HTTP_COOKIE": cookie if cookie is not None else f"__Host-wb-bluemercury={session}",
        "HTTP_HOST": "127.0.0.1:8765", "wsgi.url_scheme": "http",
        "SERVER_NAME": "127.0.0.1", "SERVER_PORT": "8765",
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    body = b"".join(candidate.app(environ, start)).decode("utf-8", "replace")
    return int(captured["status"].split()[0]), captured["headers"], body


def checkout_data(scenario, session):
    return {
        **business.SYNTHETIC_PROFILE,
        "fixture_id": business.SYNTHETIC_PROFILE_ID,
        "scenario_id": scenario,
        "submission_key": business.checkout_submission_key(session),
    }


def add_ce(session):
    return call("/products/skinceuticals-c-e-ferulic", "POST", data={"variant_id":"32352032096331","quantity":"1"}, session=session)


def setup_function():
    business.reset()


def test_catalog_has_more_than_200_unique_source_records_and_local_images():
    assert len(candidate.PRODUCTS_DOC["products"]) == 250
    assert len(candidate.CHANTECAILLE_DOC["products"]) == 108
    assert len(candidate.PRODUCTS) == 387  # current collections refresh overlapping base records
    assert len(candidate.BY_HANDLE) == 387
    assert len({product["handle"] for product in candidate.PRODUCTS}) == len(candidate.PRODUCTS)
    assert sum(bool(candidate.image_for(product)) for product in candidate.PRODUCTS) == 382
    for product in candidate.PRODUCTS:
        assert product["handle"] and product["variants"]
        for variant in product["variants"]:
            assert isinstance(variant["available"], bool)
            assert float(variant["price"]) >= 0


def test_every_product_detail_opens_and_preserves_first_variant_price():
    for product in candidate.PRODUCTS:
        status, _, body = call(f"/products/{product['handle']}")
        assert status == 200
        assert html.escape(product["title"]) in body
        assert product["variants"][0]["price"] in body


def test_single_variant_size_truth_and_multi_variant_price_metadata():
    status, _, ce_body = call("/products/skinceuticals-c-e-ferulic")
    assert status == 200 and "SIZE: 1 FL OZ" in ce_body
    ordinary = next(
        product for product in candidate.PRODUCTS
        if len(product["variants"]) == 1
        and product["variants"][0].get("title") == "Default Title"
    )
    status, _, ordinary_body = call(f"/products/{ordinary['handle']}")
    assert status == 200
    assert "SIZE: 1 FL OZ" not in ordinary_body
    assert 'name="variant_id"' in ordinary_body
    multi = next(
        product for product in candidate.PRODUCTS
        if len({variant["price"] for variant in product["variants"]}) > 1
    )
    status, _, multi_body = call(f"/products/{multi['handle']}")
    assert status == 200
    for variant in multi["variants"]:
        assert f'data-price="{variant["price"]}"' in multi_body


def test_search_results_and_zero_state():
    status, _, body = call("/search", query="q=moisturizer&type=product")
    assert status == 200 and "products" in body and "product-card" in body
    status, _, body = call("/search", query="q=wb-no-match-781&type=product")
    assert status == 200 and "No results found" in body


def test_available_product_adds_to_owner_cart_and_foreign_owner_isolated():
    status, headers, _ = add_ce("owner-session-000000000001")
    assert status == 302 and headers["Location"] == "/cart"
    assert len(business.cart("owner-session-000000000001")) == 1
    assert business.cart("foreign-session-0000000002") == []


def test_unavailable_variant_rejected():
    product = next(p for p in candidate.PRODUCTS if not any(v["available"] for v in p["variants"]))
    variant = product["variants"][0]
    status, _, body = call(f"/products/{product['handle']}", "POST", data={"variant_id":str(variant["id"]),"quantity":"1"})
    assert status == 400 and "currently unavailable" in body


def test_checkout_validation_requires_synthetic_email():
    session = "validation-session-00000001"
    add_ce(session)
    data = checkout_data("sandbox-approved", session); data["email"] = "real@example.com"
    status, _, body = call("/checkout", "POST", data=data, session=session)
    assert status == 400 and "@example.test" in body
    assert business.cart(session)


def test_sandbox_declined_and_retryable_create_no_order():
    for scenario, marker in (("sandbox-declined","declined"),("sandbox-retry","retryable")):
        business.reset(); session = f"session-{scenario}-000001"; add_ce(session)
        status, _, body = call("/checkout", "POST", data=checkout_data(scenario, session), session=session)
        assert status == 400 and marker in body.casefold()
        assert business.cart(session)


def test_sandbox_approved_is_atomic_idempotent_and_clears_cart():
    session = "approved-session-000000001"; add_ce(session)
    first_submission = business.checkout_submission_key(session)
    status, headers, _ = call("/checkout", "POST", data=checkout_data("sandbox-approved", session), session=session)
    assert status == 302 and headers["Location"].startswith("/orders/BM-")
    order_number = headers["Location"].split("/")[-1]
    result = business.order(session, order_number)
    assert result and result["approved"] and result["is_simulation"] and result["mail_id"]
    assert business.cart(session) == []
    duplicate = business.submit_checkout(
        session, {"fixture_id": business.SYNTHETIC_PROFILE_ID},
        "sandbox-approved", submission_key=first_submission,
    )
    assert duplicate["order_number"] == order_number and duplicate["already"] is True
    add_ce(session)
    second_submission = business.checkout_submission_key(session)
    assert second_submission != first_submission
    second = business.submit_checkout(
        session, {"fixture_id": business.SYNTHETIC_PROFILE_ID},
        "sandbox-approved", submission_key=second_submission,
    )
    assert second["order_number"] != order_number and business.cart(session) == []


def test_order_ownership_fails_closed():
    session = "order-owner-session-000001"; add_ce(session)
    _, headers, _ = call("/checkout", "POST", data=checkout_data("sandbox-approved", session), session=session)
    order_number = headers["Location"].split("/")[-1]
    status, _, body = call(f"/orders/{order_number}", session="foreign-order-session-0002")
    assert status == 404 and "Order unavailable" in body


def test_health_and_runtime_contract_are_exact_and_safe():
    status, _, body = call("/__websitebench/health")
    assert status == 200 and body == '{"status":"ok"}'
    runtime = json.loads((Path(__file__).parents[2] / "backend" / "runtime.json").read_text())
    assert runtime["site"]["id"] == "bluemercury"
    assert runtime["site"]["public_origin"] == "https://bluemercury.website-bench.com"
    assert runtime["database"]["filename"] == "bluemercury.sqlite3"
    assert runtime["payments"]["default_adapter"] == "local-sandbox"
    assert runtime["payments"]["stripe_test"] is None


def test_checkout_rejects_non_fixture_and_retains_only_profile_id():
    session = "fixture-retention-session-001"
    add_ce(session)
    key = business.checkout_submission_key(session)
    arbitrary = dict(business.SYNTHETIC_PROFILE)
    arbitrary["first_name"] = "Real Person"
    try:
        business.submit_checkout(session, arbitrary, "sandbox-approved", submission_key=key)
    except ValueError as exc:
        assert "frozen synthetic" in str(exc)
    else:
        raise AssertionError("arbitrary identity was accepted")
    result = business.submit_checkout(
        session, {"fixture_id": business.SYNTHETIC_PROFILE_ID},
        "sandbox-approved", submission_key=key,
    )
    assert result["approved"]
    backend, _ = business.services()
    with backend.lifecycle.connection() as connection:
        contact = json.loads(connection.execute(
            "SELECT contact_json FROM bluemercury_orders WHERE order_number=?",
            (result["order_number"],),
        ).fetchone()["contact_json"])
        recipients = [row["recipient"] for row in connection.execute(
            "SELECT recipient FROM websitebench_mail_jobs"
        ).fetchall()]
    assert contact == {"synthetic_profile_id": business.SYNTHETIC_PROFILE_ID}
    assert recipients and all(address.endswith("@example.test") for address in recipients)


def test_admin_reset_requires_token_site_confirmation_and_same_origin():
    valid = {
        "X-WebsiteBench-Admin-Token": os.environ["BLUEMERCURY_ADMIN_RESET_TOKEN"],
        "X-WebsiteBench-Confirm-Site": "bluemercury",
    }
    assert call("/__admin/reset", "POST", data={})[0] == 403
    assert call("/__admin/reset", "POST", data={}, headers={**valid, "X-WebsiteBench-Admin-Token": "wrong"})[0] == 403
    assert call("/__admin/reset", "POST", data={}, headers={**valid, "Origin": "https://evil.example"})[0] == 403
    status, _, body = call("/__admin/reset", "POST", data={}, headers=valid)
    assert status == 200 and body == '{"status":"ok"}'


def test_request_boundaries_cookie_replacement_and_font_mime():
    product_path = "/products/skinceuticals-c-e-ferulic"
    assert call(product_path, "POST", raw_body=b"", content_length="-1")[0] == 400
    assert call(product_path, "POST", raw_body=b"x", content_length=candidate.MAX_FORM_BYTES + 1)[0] == 413
    assert call(product_path, "POST", raw_body=b"{}", content_type="application/json")[0] == 415
    status, headers, _ = call("/", cookie="__Host-wb-bluemercury=../../attacker")
    assert status == 200 and "Set-Cookie" in headers and "attacker" not in headers["Set-Cookie"]
    status, headers, _ = call("/static/assets/catalog/juanaforbluemercury-lt.woff2")
    assert status == 200 and headers["Content-Type"] == "font/woff2"


def test_unknown_collection_is_honest_landing_not_all_products():
    status, _, body = call("/collections/wb-no-match-781")
    assert status == 200
    assert "does not contain enough first-party evidence" in body
    assert "product-card" not in body


def test_legacy_orders_schema_migrates_without_owner_uniqueness():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
      CREATE TABLE bluemercury_migrations(migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
      CREATE TABLE bluemercury_orders(
        order_id INTEGER PRIMARY KEY AUTOINCREMENT, order_number TEXT UNIQUE,
        owner TEXT NOT NULL UNIQUE, contact_json TEXT NOT NULL, items_json TEXT NOT NULL,
        amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, payment_flow_id TEXT NOT NULL,
        payment_attempt_id TEXT NOT NULL, fingerprint TEXT NOT NULL, mail_id TEXT, created_at TEXT NOT NULL
      );
      INSERT INTO bluemercury_orders VALUES(1,'BM-100001','owner','{}','[]',100,'USD','f','a','legacy-fp',NULL,'now');
    """)
    business._migrate_orders_v2(connection)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(bluemercury_orders)")}
    assert "submission_key" in columns
    connection.execute(
        "INSERT INTO bluemercury_orders(order_number,owner,submission_key,contact_json,items_json,amount_minor,currency,payment_flow_id,payment_attempt_id,fingerprint,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("BM-100002","owner","new_submission_key_123456789","{}","[]",100,"USD","f2","a2","new-fp","now"),
    )


def test_local_account_register_login_logout_and_cart_survives_auth_changes():
    cart_session = "account-cart-session-000001"
    add_ce(cart_session)
    auth_token, state = business.ensure_auth_session(None)
    assert state["authenticated"] is False
    registered = business.register(
        auth_token,
        email="alex.reader@example.test",
        display_name="Alex Reader",
        password="local-password-781",
    )
    assert registered["account"]["display_name"] == "Alex Reader"
    assert registered["account"]["email_normalized"] == "alex.reader@example.test"
    auth_cookie = registered["session_token"]
    cookie = f"__Host-wb-bluemercury={cart_session}; __Host-wb-bluemercury-auth={auth_cookie}"
    status, _, body = call("/account", cookie=cookie)
    assert status == 200 and "Welcome, Alex Reader" in body
    assert business.cart(cart_session)
    business.sign_out(auth_cookie)
    fresh_token, _ = business.ensure_auth_session(None)
    signed_in = business.sign_in(
        fresh_token, email="alex.reader@example.test", password="local-password-781"
    )
    assert signed_in["account"]["display_name"] == "Alex Reader"
    assert business.cart(cart_session)


def test_registration_rejects_non_fixture_email_and_password_is_hashed():
    token, _ = business.ensure_auth_session(None)
    try:
        business.register(token, email="real@example.com", display_name="Real", password="password-781")
    except ValueError as exc:
        assert "@example.test" in str(exc)
    else:
        raise AssertionError("non-fixture email accepted")
    registered = business.register(
        token, email="hash-check@example.test", display_name="Hash Check", password="password-781"
    )
    backend, _ = business.services()
    with backend.lifecycle.connection() as connection:
        row = connection.execute(
            "SELECT password_hash,password_salt,password_scheme FROM local_auth_accounts WHERE account_id=?",
            (registered["account"]["account_id"],),
        ).fetchone()
    assert row["password_scheme"] == "scrypt-v1"
    assert bytes(row["password_hash"]) != b"password-781"
    assert row["password_salt"]


def test_wishlist_requires_login_and_toggles_from_pdp_and_account():
    status, headers, _ = call(
        "/wishlist/toggle", "POST",
        data={"handle": "skinceuticals-c-e-ferulic", "return_to": "/products/skinceuticals-c-e-ferulic"},
    )
    assert status == 302 and headers["Location"].startswith("/account/login")
    token, _ = business.ensure_auth_session(None)
    registered = business.register(
        token, email="wish@example.test", display_name="Wish User", password="password-781"
    )
    auth_token = registered["session_token"]
    subject = registered["account"]["subject_id"]
    cookie = f"__Host-wb-bluemercury=test-session-000000000001; __Host-wb-bluemercury-auth={auth_token}"
    status, headers, _ = call(
        "/wishlist/toggle", "POST",
        data={"handle": "skinceuticals-c-e-ferulic", "return_to": "/account/wishlist"},
        cookie=cookie,
    )
    assert status == 302 and headers["Location"] == "/account/wishlist"
    assert "skinceuticals-c-e-ferulic" in business.wishlist(subject)
    status, _, body = call("/account/wishlist", cookie=cookie)
    assert status == 200 and "C E Ferulic" in body and "♥" in body
    call(
        "/wishlist/toggle", "POST",
        data={"handle": "skinceuticals-c-e-ferulic", "return_to": "/account/wishlist"},
        cookie=cookie,
    )
    assert not business.wishlist(subject)


def test_catalog_get_filters_sort_and_search_query_are_server_effective():
    status, _, body = call(
        "/collections/skin-care",
        query="brand=Goop+Beauty&stock=available&min_price=100&max_price=200&sort=price-desc",
    )
    assert status == 200
    assert "Signature Ritual Collection" in body
    assert 'name="brand"' in body and 'value="Goop Beauty" selected' in body
    status, _, body = call("/collections/skin-care", query="min_price=99999")
    assert status == 200 and "No products match these filters" in body
    status, _, body = call("/search", query="q=moisturizer&sort=price-asc")
    assert status == 200 and 'name="q" value="moisturizer"' in body


def test_homepage_internal_links_are_reachable_and_mobile_menu_is_wired():
    status, _, body = call("/")
    assert status == 200
    hrefs = sorted(set(html.unescape(value) for value in re.findall(r'href="([^"]+)"', body)))
    for href in hrefs:
        if href.startswith(("/static/", "#")):
            continue
        parsed = urllib.parse.urlsplit(href)
        status, _, _ = call(parsed.path or "/", query=parsed.query)
        assert status in {200, 302}, href
    assert 'aria-controls="primary-nav"' in body
    assert 'aria-expanded="false"' in body
    status, headers, script = call("/static/site.js")
    assert status == 200 and headers["Content-Type"] == "text/javascript"
    assert "nav-open" in script and "requestSubmit" in script
    assert "Perfect for Fall" in script and "Fall in Love" in script


def test_current_playwright_home_and_chantecaille_journey_are_local_and_clickable():
    status, _, home = call("/")
    assert status == 200
    assert "15% Off Chantecaille" in home
    assert 'href="/collections/chantecaille"' in home
    assert 'src="/static/assets/home-hero-chantecaille.jpg"' in home
    assert 'data-hero-direction="previous"' in home
    assert 'data-hero-direction="next"' in home
    assert home.count("data-hero-index=") == 3
    assert "LOCAL CLONE" not in home
    status, _, collection = call("/collections/chantecaille")
    assert status == 200
    assert collection.count('class="product-card"') == 116  # 8 carousel cards plus the complete 108-item grid
    assert "preeminent luxury brand" in collection
    assert 'src="/static/assets/chantecaille-brand-hero.png"' in collection
    assert 'data-brand-direction="previous"' in collection
    assert 'data-brand-direction="next"' in collection
    product = next(product for product in candidate.PRODUCTS if product.get("vendor") == "Chantecaille")
    status, _, detail = call(f"/products/{product['handle']}")
    assert status == 200 and html.escape(product["title"]) in detail
    variant = next(variant for variant in product["variants"] if variant.get("available"))
    status, headers, _ = call(
        f"/products/{product['handle']}", "POST",
        data={"variant_id": variant["id"], "quantity": "1"},
        session="chantecaille-journey-0001",
    )
    assert status == 302 and headers["Location"] == "/cart"
    status, _, cart = call("/cart", session="chantecaille-journey-0001")
    assert status == 200 and html.escape(product["title"]) in cart


def test_home_hero_collection_pages_include_every_captured_source_product():
    for handle, expected_count in (("fall-beauty-must-haves", 34), ("m-61-perfect-collection", 12)):
        status, _, body = call(f"/collections/{handle}")
        assert status == 200
        assert body.count('class="product-card"') == expected_count
        captured_handles = set(candidate.COLLECTION_MEMBERSHIPS[handle])
        assert captured_handles <= {product["handle"] for product in candidate.PRODUCTS}


def test_frozen_route_announcements_and_catalog_source_count_are_explicit():
    _, _, home = call("/")
    _, _, product = call("/products/skinceuticals-c-e-ferulic")
    _, _, collection = call("/collections/skin-care")
    _, _, cart = call("/cart")
    assert "15% OFF CHANTECAILLE" in home
    assert "FREE SAMPLES WITH ALL ORDERS" in product
    assert "15% OFF CHANTECAILLE" in product
    assert "15% OFF CHANTECAILLE" in collection
    assert "FREE SHIPPING AND RETURNS FOR BLUEREWARDS MEMBERS" in cart
    assert "FREE GIFTS WITH PURCHASE" in cart
    assert "announcement-mobile-wide" in cart
    assert 'class="source-count">(1707)</span>' in collection
    assert "127 local products" in collection
    assert 'class="active"' in collection and 'href="/collections/skin-care"' in collection
    assert 'aria-current="page"' in collection
    assert 'viewBox="0 0 177 18"' in home
    assert 'viewBox="0 0 25 25"' in home
    assert 'class="crumbs catalog-crumbs"' in collection
    assert 'class="crumbs pdp-crumbs"' in product
    assert 'class="account-link"' in home
    assert 'class="crumb-separator" aria-hidden="true">›</span>' in product
    assert 'class="thumb-arrow"' in product


def test_evidenced_navigation_collections_expose_only_local_intersections():
    expected_nonempty = {
        "hsa-fsa-eligible", "bundles-1", "new-arrivals", "makeup", "hair",
        "suncare", "gifts", "sale",
    }
    for handle in expected_nonempty:
        status, _, body = call(f"/collections/{handle}")
        assert status == 200 and "product-card" in body, handle
    status, _, body = call("/collections/hsa-fsa-eligible")
    assert status == 200 and body.count('class="product-card"') >= 90
    assert "Lift &amp; Firm Duo" in body and "Serene Scalp Densifying Shampoo" in body
    status, _, body = call("/collections/brands")
    assert status == 200 and "brand-list" in body and "SkinCeuticals" in body
    assert "brand=D.S.+%26+Durga" in body and "brand=R%2BCo" in body
    status, _, body = call("/search", query="brand=D.S.+%26+Durga&type=product")
    assert status == 200 and "D.S. &amp; Durga" in body and "product-card" in body
    status, _, body = call("/search", query="brand=R%2BCo&type=product")
    assert status == 200 and "R+Co" in body and "product-card" in body
    for handle in {"best-sellers", "bath-body", "fragrances"}:
        status, _, body = call(f"/collections/{handle}")
        assert status == 200 and "product-card" in body, handle
