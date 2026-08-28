import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import app


client = TestClient(app, base_url="https://testserver")


def register_local_account(client: TestClient, email: str) -> None:
    started = client.post(
        "/api/auth/register",
        json={"email": email, "password": "local-test-password", "name": "Test Driver"},
    )
    assert started.status_code == 202
    assert started.json()["state"] == "challenge"
    assert "__Host-websitebench-autotrader-session=" in started.headers["set-cookie"]

    message = client.get("/api/auth/local-mail", params={"purpose": "registration"})
    assert message.status_code == 200
    verified = client.post(
        "/api/auth/register/verify",
        json={"code": message.json()["verification_code"]},
    )
    assert verified.status_code == 200
    assert verified.json()["authenticated"] is True


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "site_id": "autotrader"}


def test_websitebench_health_contract() -> None:
    response = client.get("/__websitebench/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_candidate_runtime_is_self_contained_and_matches_site_contract() -> None:
    clone_root = Path(__file__).resolve().parents[1]
    candidate_runtime = json.loads(
        (clone_root / "backend" / "runtime.json").read_text(encoding="utf-8")
    )
    assert candidate_runtime["site"]["id"] == "autotrader"
    assert candidate_runtime["database"]["filename"] == "autotrader.sqlite3"
    site_runtime_path = clone_root.parent / "backend" / "runtime.json"
    if site_runtime_path.is_file():
        site_runtime = json.loads(site_runtime_path.read_text(encoding="utf-8"))
        assert candidate_runtime == site_runtime
    compile_script = (clone_root / "compile.sh").read_text(encoding="utf-8")
    assert '$ROOT/backend/runtime.json' in compile_script
    assert '$ROOT/../backend/runtime.json' not in compile_script


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Autotrader" in response.text


def test_home_csp_allows_local_session_state_sync() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "connect-src 'self'" in response.text


def test_unknown_route() -> None:
    assert client.get("/not-in-scope").status_code == 404


def test_used_car_search_filters_results() -> None:
    response = client.get("/cars/used?make=Ford&price=15000")
    assert response.status_code == 200
    assert "2022 Ford Fiesta" in response.text
    assert "2021 BMW 3 Series 320d" not in response.text


def test_used_car_search_has_no_results_state() -> None:
    response = client.get("/cars/used?keyword=no-such-vehicle-zzzz")
    assert response.status_code == 200
    assert "No cars found" in response.text


def test_listing_preview_rejects_missing_required_fields() -> None:
    response = client.post("/api/listings/preview", json={})
    assert response.status_code == 200
    assert response.json() == {
        "status": "validation",
        "missing": ["make", "year", "mileage", "price"],
        "submission_enabled": False,
        "offline": True,
    }


def test_listing_preview_accepts_complete_vehicle() -> None:
    response = client.post(
        "/api/listings/preview",
        json={"make": "Ford", "year": 2022, "mileage": 24100, "price": 14995},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "preview",
        "missing": [],
        "submission_enabled": True,
        "offline": True,
    }


def test_protected_account_pages_require_a_server_session() -> None:
    anonymous = TestClient(app, base_url="https://testserver")
    for path in ("/secure/my-auto-trader", "/account/history", "/account/address"):
        response = anonymous.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/secure/signin")


def test_registration_requires_local_verification_before_account_creation() -> None:
    browser = TestClient(app, base_url="https://testserver")
    email = "verification-required@example.test"

    started = browser.post(
        "/api/auth/register",
        json={"email": email, "password": "local-test-password", "name": "Verified Driver"},
    )
    assert started.status_code == 202
    assert started.json()["state"] == "challenge"
    assert browser.get("/api/auth/session").json()["authenticated"] is False

    message = browser.get("/api/auth/local-mail", params={"purpose": "registration"})
    assert message.status_code == 200
    completed = browser.post(
        "/api/auth/register/verify",
        json={"code": message.json()["verification_code"]},
    )
    assert completed.status_code == 200
    assert completed.json()["authenticated"] is True
    account = browser.get("/secure/my-auto-trader")
    assert account.status_code == 200
    assert email in account.text


def test_listing_is_persistent_owner_scoped_and_concurrency_checked() -> None:
    owner = TestClient(app, base_url="https://testserver")
    stranger = TestClient(app, base_url="https://testserver")
    register_local_account(owner, "listing-owner@example.test")
    register_local_account(stranger, "listing-stranger@example.test")

    created = owner.post(
        "/api/listings",
        json={
            "make": "Ford",
            "year": 2022,
            "mileage": 24100,
            "price": 14995,
            "description": "One owner, full service history.",
        },
    )
    assert created.status_code == 201
    listing = created.json()["listing"]
    assert listing["status"] == "pending-review"
    assert listing["version"] == 1

    assert owner.get(f"/api/listings/{listing['id']}").status_code == 200
    assert stranger.get(f"/api/listings/{listing['id']}").status_code == 404
    assert listing["id"] in owner.get("/account/history").text

    paused = owner.post(
        f"/api/listings/{listing['id']}/actions",
        json={"action": "pause", "expected_version": 1},
    )
    assert paused.status_code == 200
    assert paused.json()["listing"]["status"] == "paused"
    stale = owner.post(
        f"/api/listings/{listing['id']}/actions",
        json={"action": "renew", "expected_version": 1},
    )
    assert stale.status_code == 409


def test_existing_listing_can_be_prefilled_and_edited_by_owner_only() -> None:
    owner = TestClient(app, base_url="https://testserver")
    stranger = TestClient(app, base_url="https://testserver")
    register_local_account(owner, "edit-owner@example.test")
    register_local_account(stranger, "edit-stranger@example.test")
    created = owner.post(
        "/api/listings",
        json={
            "make": "Volvo",
            "year": 2021,
            "mileage": 31000,
            "price": 21995,
            "description": "Original description",
            "photo_count": 2,
        },
    ).json()["listing"]

    edit_surface = owner.get(f"/selling/find-car?edit={created['id']}")
    assert edit_surface.status_code == 200
    assert 'value="Volvo"' in edit_surface.text
    assert 'value="31000"' in edit_surface.text
    assert f'data-edit-listing="{created["id"]}"' in edit_surface.text
    assert stranger.get(f"/selling/find-car?edit={created['id']}").status_code == 404

    updated = owner.patch(
        f"/api/listings/{created['id']}",
        json={
            "make": "Volvo",
            "year": 2021,
            "mileage": 30500,
            "price": 20995,
            "description": "Updated locally",
            "photo_count": 3,
            "expected_version": 1,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["listing"]["price"] == 20995
    assert updated.json()["listing"]["version"] == 2
    assert updated.json()["listing"]["photo_count"] == 3
    assert stranger.patch(
        f"/api/listings/{created['id']}", json={"expected_version": 1}
    ).status_code == 404
    assert owner.patch(
        f"/api/listings/{created['id']}",
        json={
            "make": "Volvo",
            "year": 2021,
            "mileage": 30000,
            "price": 19995,
            "expected_version": 1,
        },
    ).status_code == 409


def test_delivery_address_is_persistent_and_owner_scoped() -> None:
    owner = TestClient(app, base_url="https://testserver")
    other = TestClient(app, base_url="https://testserver")
    register_local_account(owner, "address-owner@example.test")
    register_local_account(other, "address-other@example.test")

    saved = owner.put(
        "/api/account/address",
        json={
            "address": "10 High Street",
            "city": "London",
            "postcode": "SW1A 1AA",
            "delivery_option": "dealer-pickup",
        },
    )
    assert saved.status_code == 200
    assert owner.get("/api/account/address").json()["postcode"] == "SW1A 1AA"
    assert other.get("/api/account/address").status_code == 404


def test_catalog_has_200_openable_local_records() -> None:
    response = client.get("/api/search")
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 200
    assert all(client.get(f"/cars/used/listing/{car['id']}").status_code == 200 for car in results)


def test_anonymous_saved_compare_and_alert_state_is_session_scoped() -> None:
    browser = TestClient(app, base_url="https://testserver")
    other = TestClient(app, base_url="https://testserver")

    assert browser.post("/api/saved", json={"kind": "car", "item_id": "ford-fiesta"}).status_code == 201
    assert browser.post("/api/saved", json={"kind": "compare", "item_id": "ford-fiesta"}).status_code == 201
    assert browser.post("/api/saved", json={"kind": "compare", "item_id": "bmw-320d"}).status_code == 201
    assert browser.post("/api/saved", json={"kind": "alert", "item_id": "ford-london-under-15000"}).status_code == 201

    state = browser.get("/api/saved").json()["items"]
    assert {(item["kind"], item["item_id"]) for item in state} == {
        ("car", "ford-fiesta"),
        ("compare", "ford-fiesta"),
        ("compare", "bmw-320d"),
        ("alert", "ford-london-under-15000"),
    }
    assert other.get("/api/saved").json()["items"] == []


def test_saved_collection_is_visible_after_refresh_and_session_scoped() -> None:
    browser = TestClient(app, base_url="https://testserver")
    other = TestClient(app, base_url="https://testserver")

    assert browser.post(
        "/api/saved", json={"kind": "car", "item_id": "ford-fiesta"}
    ).status_code == 201
    assert browser.post(
        "/api/saved", json={"kind": "alert", "item_id": "ford-search"}
    ).status_code == 201

    collection = browser.get("/cars/saved")
    assert collection.status_code == 200
    assert "2022 Ford Fiesta 1.0 EcoBoost" in collection.text
    assert "Ford search" in collection.text
    assert "Saved cars and alerts" in collection.text

    empty_collection = other.get("/cars/saved")
    assert empty_collection.status_code == 200
    assert "No saved cars or alerts yet" in empty_collection.text
    assert "2022 Ford Fiesta 1.0 EcoBoost" not in empty_collection.text


def test_primary_navigation_opens_saved_collection() -> None:
    response = client.get("/cars/used")

    assert response.status_code == 200
    assert 'class=nav-icon href=/cars/saved' in response.text


def test_vehicle_detail_uses_server_owned_saved_state_controls() -> None:
    response = client.get("/cars/used/listing/ford-fiesta")

    assert response.status_code == 200
    assert "data-save=ford-fiesta" in response.text
    assert "data-compare=ford-fiesta" in response.text
    assert "localStorage.setItem('saved-car-" not in response.text


def test_contact_seller_requires_sign_in_and_persists_only_locally() -> None:
    anonymous = TestClient(app, base_url="https://testserver")
    permission = anonymous.get("/contact-seller?car=ford-fiesta")
    assert permission.status_code == 200
    assert "Sign in is required" in permission.text
    assert 'href="/secure/signin?next=/contact-seller%3Fcar%3Dford-fiesta"' in permission.text

    owner = TestClient(app, base_url="https://testserver")
    stranger = TestClient(app, base_url="https://testserver")
    register_local_account(owner, "contact-owner@example.test")
    register_local_account(stranger, "contact-stranger@example.test")

    created = owner.post(
        "/api/contact-requests",
        json={
            "car_id": "ford-fiesta",
            "request_type": "test-drive",
            "message": "Please share locally available appointment guidance.",
        },
    )
    assert created.status_code == 201
    assert created.json()["request"]["status"] == "saved-locally"
    assert created.json()["offline"] is True

    owner_requests = owner.get("/api/contact-requests")
    assert owner_requests.status_code == 200
    assert owner_requests.json()["requests"][0]["car_id"] == "ford-fiesta"
    assert stranger.get("/api/contact-requests").json()["requests"] == []


def test_signed_in_contact_surface_submits_to_local_api() -> None:
    owner = TestClient(app, base_url="https://testserver")
    register_local_account(owner, "contact-surface@example.test")

    response = owner.get("/contact-seller?car=ford-fiesta")
    assert response.status_code == 200
    assert 'id="contact-seller-form"' in response.text
    assert "/api/contact-requests" in response.text
    assert "No message or test-drive request is sent externally" in response.text


def test_public_sell_submission_persists_with_session_ownership() -> None:
    seller = TestClient(app, base_url="https://testserver")
    other = TestClient(app, base_url="https://testserver")
    payload = {
        "make": "Volvo",
        "year": 2023,
        "mileage": 12000,
        "price": 27995,
        "description": "One local owner",
        "photo_count": 2,
    }

    created = seller.post("/api/listings/session", json=payload)
    assert created.status_code == 201
    listing_id = created.json()["listing"]["id"]

    confirmation = seller.get(f"/selling/confirmation?id={listing_id}")
    assert confirmation.status_code == 200
    assert "2023 Volvo" in confirmation.text
    assert "£27995" in confirmation.text
    assert seller.get(f"/selling/confirmation?id={listing_id}").status_code == 200
    assert other.get(f"/selling/confirmation?id={listing_id}").status_code == 404


def test_sell_review_submit_control_uses_persistent_session_endpoint() -> None:
    response = client.get(
        "/selling/review?make=Ford&year=2022&mileage=24100&price=14995"
    )

    assert response.status_code == 200
    assert 'id="submit-listing"' in response.text
    assert 'method="post"' in response.text
    assert 'action="/selling/submit"' in response.text


def test_sell_photo_count_is_carried_honestly_into_review_and_confirmation() -> None:
    seller = TestClient(app, base_url="https://testserver")
    form = seller.get("/selling/find-car")
    assert "sell.elements.photos.files.length" in form.text

    review = seller.get(
        "/selling/review?make=Ford&year=2022&mileage=24100&price=14995&photo_count=2"
    )
    assert review.status_code == 200
    assert "2 selected for local preview" in review.text
    assert 'name="photo_count" value="2"' in review.text

    submitted = seller.post(
        "/selling/submit",
        data={
            "make": "Ford",
            "year": "2022",
            "mileage": "24100",
            "price": "14995",
            "description": "Local photo preview",
            "photo_count": "2",
        },
        follow_redirects=True,
    )
    assert submitted.status_code == 200
    assert "Vehicle photos" in submitted.text
    assert ">2<" in submitted.text


def test_signed_in_native_sell_submission_appears_in_account_history() -> None:
    seller = TestClient(app, base_url="https://testserver")
    register_local_account(seller, "native-seller@example.test")

    submitted = seller.post(
        "/selling/submit",
        data={
            "make": "Volvo",
            "year": "2021",
            "mileage": "31000",
            "price": "21995",
            "description": "Visible in account history",
            "photo_count": "1",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    listing_id = submitted.headers["location"].split("id=", 1)[1]
    history = seller.get("/account/history")
    assert history.status_code == 200
    assert listing_id in history.text
    assert "2021 Volvo" in history.text


def test_registration_terms_links_are_local_and_available() -> None:
    registration = client.get("/secure/register")
    assert registration.status_code == 200
    assert "href='/terms-and-conditions/advertising'" in registration.text
    assert "href='/privacy-notice'" in registration.text
    for path in ("/terms-and-conditions/advertising", "/privacy-notice"):
        response = client.get(path)
        assert response.status_code == 200
        assert "offline clone" in response.text.lower()
        assert "Return to registration" in response.text
