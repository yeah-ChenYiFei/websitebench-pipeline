import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app import DB_PATH, MOVIES, app


client = TestClient(app)


def test_healthz(monkeypatch) -> None:
    build_id = "a" * 40
    monkeypatch.setenv("DEPLOYMENT_BUILD_ID", build_id)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.headers["X-WebsiteBench-Container-Build-ID"] == build_id


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "AMC STUBS MEMBER EXCLUSIVE" in response.text
    assert "Get 50% off* Tickets Two Days a Week" in response.text
    assert "Movies at AMC" in response.text
    assert "data-carousel" in response.text
    assert "Movies are better with the app" in response.text


def test_core_routes_render() -> None:
    for route, expected in [
        ("/movies", "Movies at AMC"),
        ("/movies/superman", "Choose a showtime"),
        ("/movie-theatres", "Find a Theatre"),
        ("/movie-theatres/ny/amc-empire-25", "234 West 42nd Street"),
        ("/showtimes", "Select a theatre to view showtimes"),
        ("/showtimes?theatre=amc-empire-25", "Movies start 25-30 minutes after showtime"),
        ("/checkout/superman", "Choose your seats"),
        ("/login", "Sign in to My AMC"),
        ("/sign-up", "Join for free"),
        ("/verify-account", "Enter your local code"),
        ("/password-reset/verify", "Choose a new password"),
        ("/food-and-drink", "Make movie night delicious"),
        ("/group-events", "Bring your group to the big screen"),
        ("/merchandise", "Collect a piece of movie night"),
        ("/gift-cards", "Give the gift of movies"),
        ("/offers", "More ways to enjoy AMC"),
        ("/on-demand", "Movies wherever your screen is"),
        ("/more", "Explore More Ways to Enjoy the Movies"),
    ]:
        response = client.get(route)
        assert response.status_code == 200
        assert expected in response.text


def test_review_feedback_routes_are_complete_and_movie_specific() -> None:
    home = client.get("/").text
    assert 'data-movie-category="Now Playing"' in home
    assert 'data-movie-category="Events"' in home
    assert 'data-movie-category="Coming Soon"' in home

    offers = client.get("/offers").text
    assert offers.count('class="offer-card"') >= 8
    for action in ["Get Tickets", "Learn More", "Join for Free", "Order Now"]:
        assert action in offers

    food = client.get("/food-and-drink").text
    assert food.count('class="offer-card"') >= 6
    assert '/food-and-drink/perfectly-popcorn' in food
    detail = client.get("/food-and-drink/perfectly-popcorn")
    assert detail.status_code == 200
    assert "Freshly popped at AMC" in detail.text

    more = client.get("/more").text
    assert "Offers &amp; Promotions" in more
    assert "Group Events" in more
    assert "Help Center" in more

    login = client.get("/login").text
    assert 'name="captcha"' in login
    rejected = client.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345", "captcha": False},
    )
    assert rejected.status_code == 400
    assert "verification" in rejected.json()["message"].lower()

    showtimes = client.get(
        "/showtimes?movie=the-magic-faraway-tree&theatre=amc-century-city-15"
    ).text
    assert "The Magic Faraway Tree" in showtimes
    assert "AMC Century City 15" in showtimes
    assert '/checkout/the-magic-faraway-tree?' in showtimes
    assert "No remaining showtimes" not in showtimes

    listing = client.get("/movies").text
    assert "background:#" not in listing
    movie_page = client.get("/movies/the-magic-faraway-tree").text
    assert "Movie details" in movie_page
    assert "Scenes from the movie" in movie_page

    browser = TestClient(app)
    browser.post("/api/reset")
    signed_in = browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    )
    assert signed_in.status_code == 200
    account = browser.get("/account").text
    assert 'class="account-sidebar"' in account
    assert "Rewards" in account


def test_theatre_directory_public_structure_and_controls() -> None:
    response = client.get("/movie-theatres")
    assert response.status_code == 200
    assert 'placeholder="Search by City, Zip or Theatre"' in response.text
    assert "Use Current Location" in response.text
    assert 'data-directory-tab="markets"' in response.text
    assert 'data-directory-tab="states"' in response.text
    assert response.text.count('href="/movie-theatres/') >= 150
    assert client.get("/movie-theatres/new-york-city", follow_redirects=False).status_code == 303


def test_every_theatre_detail_uses_its_own_address_and_favorite_identity() -> None:
    for region, slug, address in [
        ("ny", "amc-empire-25", "234 West 42nd Street"),
        ("ny", "amc-34th-street-14", "312 W 34th St"),
        ("ny", "amc-lincoln-square-13", "1998 Broadway"),
        ("ny", "amc-village-7", "66 Third Ave"),
        ("ca", "amc-century-city-15", "10250 Santa Monica Blvd"),
        ("il", "amc-river-east-21", "322 E Illinois St"),
    ]:
        detail = client.get(f"/movie-theatres/{region}/{slug}")
        assert detail.status_code == 200
        assert address in detail.text
        assert f'data-theatre="{slug}"' in detail.text


def test_filter_search_and_not_found_states() -> None:
    assert "Superman" in client.get("/movies?q=superman").text
    assert "No movies found" in client.get("/movies?q=definitely-missing").text
    assert "AMC Empire 25" in client.get("/movie-theatres?q=empire").text
    assert client.get("/movies/definitely-missing").status_code == 404


def test_discovery_sort_showtime_help_and_exact_local_scenario_contracts() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    filtered = browser.get("/movies?q=the&sort=A-Z")
    assert filtered.status_code == 200
    assert 'name="sort"' in filtered.text
    assert 'value="the"' in filtered.text
    assert filtered.text.index("The End of Oak Street") < filtered.text.index("The Odyssey")
    tomorrow = browser.get("/showtimes?date=tomorrow&format=premium&theatre=amc-empire-25")
    assert tomorrow.status_code == 200
    assert "Tomorrow" in tomorrow.text
    assert "Premium Offerings" in tomorrow.text
    assert "IMAX and Dolby Cinema" in tomorrow.text
    assert "/checkout/insidious-out-of-the-further?" in tomorrow.text
    help_page = browser.get("/help?topic=refund")
    assert help_page.status_code == 200
    assert "Request a Refund" in help_page.text
    assert "Manage Communication" in help_page.text
    highest = max(MOVIES, key=lambda item: item["score"])
    created = browser.post(
        "/api/orders",
        json={
            "movie_slug": highest["slug"],
            "theatre_slug": "amc-empire-25",
            "showtime": "Friday 7:00 PM",
            "seats": ["E4", "E5"],
            "scenario": "sandbox-approved",
            "ticket_type": "Adult",
            "format_name": "IMAX",
            "attendee_name": "Synthetic Friday Guest",
        },
    )
    assert created.status_code == 200
    assert created.json()["order_id"].startswith("AMC-")
    assert browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    ).status_code == 200
    ticket = browser.get(f'/account/orders/{created.json()["order_id"]}')
    assert highest["title"] in ticket.text
    assert "Friday 7:00 PM" in ticket.text
    assert "Seats" in ticket.text and "E4, E5" in ticket.text
    assert "IMAX" in ticket.text
    browser.post("/api/reset")


def test_favorite_persists_in_session() -> None:
    browser = TestClient(app)
    browser.get("/")
    result = browser.post("/api/favorites", json={"movie_slug": "superman"})
    assert result.status_code == 200
    assert result.json()["saved"] is True
    assert "saved" in browser.get("/movies/superman").text
    result = browser.post("/api/favorites", json={"movie_slug": "superman"})
    assert result.json()["saved"] is False


def test_login_and_account() -> None:
    browser = TestClient(app)
    browser.get("/login")
    result = browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    )
    assert result.status_code == 200
    assert result.json()["ok"] is True
    account = browser.get("/account")
    assert account.status_code == 200
    assert "Hello, AMC Guest" in account.text


def test_local_sandbox_order_outcomes() -> None:
    browser = TestClient(app)
    browser.get("/checkout/superman")
    payload = {
        "movie_slug": "superman",
        "theatre_slug": "amc-empire-25",
        "showtime": "7:00 PM",
        "seats": ["A1", "A2"],
    }
    declined = browser.post(
        "/api/orders", json={**payload, "scenario": "sandbox-declined"}
    )
    assert declined.status_code == 402
    approved = browser.post(
        "/api/orders", json={**payload, "scenario": "sandbox-approved"}
    )
    assert approved.status_code == 200
    assert approved.json()["order_id"].startswith("AMC-")
    assert approved.json()["total"] == "$33.97"
    signed_in = browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    )
    assert signed_in.status_code == 200
    account = browser.get("/account")
    assert approved.json()["order_id"][-8:] in account.text
    assert "Seats A1, A2" in account.text


def test_membership_ticket_tier_format_attendee_and_review_persist() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    assert browser.post(
        "/api/signup",
        json={
            "name": "Invalid Plan",
            "email": "invalid-plan@example.test",
            "password": "valid-local-pass-123",
            "plan": "production-paid-plan",
        },
    ).status_code == 400
    started = browser.post(
        "/api/signup",
        json={
            "name": "Premiere Member",
            "email": "premiere-member@example.test",
            "password": "valid-local-pass-123",
            "plan": "premiere",
        },
    )
    assert started.status_code == 200
    code = browser.get("/api/local-outbox/registration").json()["message"][
        "verification_code"
    ]
    assert browser.post("/api/signup/verify", json={"code": code}).status_code == 200
    account = browser.get("/account")
    assert "AMC Stubs Premiere" in account.text
    assert "Active" in account.text
    browser.post("/api/reset")
    checkout = browser.get("/checkout/the-odyssey")
    assert checkout.status_code == 200
    for control in [
        'id="ticket-type"',
        'id="format-name"',
        'id="attendee-name"',
        'aria-label="Booking review"',
        'id="review-ticket-type"',
        'id="review-format"',
        'id="review-attendee"',
    ]:
        assert control in checkout.text
    base = {
        "movie_slug": "the-odyssey",
        "theatre_slug": "amc-empire-25",
        "showtime": "7:00 PM",
        "seats": ["E4", "E5"],
        "scenario": "sandbox-approved",
    }
    assert browser.post(
        "/api/orders", json={**base, "ticket_type": "Unknown"}
    ).status_code == 400
    assert browser.post(
        "/api/orders", json={**base, "format_name": "Unknown"}
    ).status_code == 400
    assert browser.post(
        "/api/orders", json={**base, "attendee_name": " "}
    ).status_code == 400
    created = browser.post(
        "/api/orders",
        json={
            **base,
            "ticket_type": "Child",
            "format_name": "IMAX",
            "attendee_name": "Synthetic Attendee",
        },
    )
    assert created.status_code == 200
    assert created.json()["total"] == "$35.95"
    assert browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    ).status_code == 200
    ticket = browser.get(f'/account/orders/{created.json()["order_id"]}')
    assert ticket.status_code == 200
    assert "Child" in ticket.text
    assert "IMAX" in ticket.text
    assert "Synthetic Attendee" in ticket.text
    browser.post("/api/reset")


def test_order_management_ticket_and_preferences_close_locally() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    created = browser.post(
        "/api/orders",
        json={
            "movie_slug": "the-odyssey",
            "theatre_slug": "amc-empire-25",
            "showtime": "7:00 PM",
            "seats": ["E4", "E5"],
            "scenario": "sandbox-approved",
        },
    ).json()
    assert browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    ).status_code == 200
    order_id = created["order_id"]
    ticket_page = browser.get(f"/account/orders/{order_id}")
    assert ticket_page.status_code == 200
    for visible_control in [
        'data-order-action="reschedule"',
        'data-order-action="cancel"',
        'data-order-action="refund"',
        'data-order-action="reminder"',
        'data-order-action="concessions"',
        'data-order-action="notes"',
        'data-order-action="promo"',
        'data-order-action="share"',
        "data-review-rating",
        "data-review-visibility",
        "data-review-body",
        "data-review-save",
        "Concessions preorder",
        "Special requests",
        "Promo or voucher",
        "Transfer or share booking",
        "Review and rating",
    ]:
        assert visible_control in ticket_page.text
    intruder = TestClient(app)
    assert intruder.post(
        "/api/signup",
        json={
            "name": "Foreign Member",
            "email": "foreign-order-owner@example.test",
            "password": "valid-local-pass-123",
            "plan": "insider",
        },
    ).status_code == 200
    intruder_code = intruder.get("/api/local-outbox/registration").json()[
        "message"
    ]["verification_code"]
    assert intruder.post(
        "/api/signup/verify", json={"code": intruder_code}
    ).status_code == 200
    assert intruder.post(
        f"/api/orders/{order_id}/manage", json={"action": "cancel"}
    ).status_code == 404
    assert browser.get(f"/account/orders/{order_id}").status_code == 200
    rescheduled = browser.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "reschedule", "showtime": "8:45 PM"},
    )
    assert rescheduled.status_code == 200
    assert rescheduled.json()["order"]["showtime"] == "8:45 PM"
    assert browser.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "concessions", "concessions": ["popcorn", "soft-drink"]},
    ).json()["order"]["concessions"] == ["popcorn", "soft-drink"]
    assert browser.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "share", "recipient": "person@realmail.invalid"},
    ).status_code == 400
    assert browser.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "share", "recipient": "friend@example.com"},
    ).json()["order"]["shared_with"] == "friend@example.com"
    assert browser.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "promo", "promo_code": "AMCLOCAL10"},
    ).json()["order"]["promo_code"] == "AMCLOCAL10"
    assert browser.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "notes", "notes": "Synthetic accessibility request"},
    ).json()["order"]["notes"] == "Synthetic accessibility request"
    assert browser.post(
        f"/api/orders/{order_id}/review",
        json={
            "rating": 4,
            "body": "Synthetic local review",
            "visibility": "public",
        },
    ).json()["review"] == {
        "order_id": order_id,
        "rating": 4,
        "body": "Synthetic local review",
        "visibility": "public",
    }
    reviewed_ticket = browser.get(f"/account/orders/{order_id}")
    assert "4 stars · public" in reviewed_ticket.text
    assert "Synthetic local review" in reviewed_ticket.text
    assert browser.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "reminder", "reminder_enabled": True},
    ).json()["order"]["reminder_enabled"] is True
    metadata_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3,sys;"
                "c=sqlite3.connect(sys.argv[1]);"
                "r=c.execute('SELECT shared_with,reminder_enabled,notes,promo_code FROM amc_order_metadata WHERE order_id=?',(sys.argv[2],)).fetchone();"
                "assert r == ('friend@example.com',1,'Synthetic accessibility request','AMCLOCAL10'), r"
            ),
            str(DB_PATH),
            order_id,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert metadata_probe.returncode == 0, metadata_probe.stderr
    assert browser.post(
        f"/api/orders/{order_id}/manage", json={"action": "cancel"}
    ).json()["order"]["status"] == "cancelled"
    assert browser.post(
        f"/api/orders/{order_id}/manage", json={"action": "cancel"}
    ).json()["order"]["status"] == "cancelled"
    assert browser.post(
        f"/api/orders/{order_id}/manage", json={"action": "refund"}
    ).json()["order"]["status"] == "refunded"
    assert browser.post(
        f"/api/orders/{order_id}/manage", json={"action": "cancel"}
    ).status_code == 409
    saved = browser.post(
        "/api/preferences",
        json={
            "preferred_theatre": "amc-lincoln-square-13",
            "notifications_enabled": True,
            "privacy_mode": "minimal",
        },
    )
    assert saved.status_code == 200
    assert browser.get("/api/preferences").json()["preferences"] == {
        "preferred_theatre": "amc-lincoln-square-13",
        "notifications_enabled": True,
        "privacy_mode": "minimal",
    }


def test_order_management_rejects_unsigned_access() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    assert browser.get("/api/preferences").status_code == 401
    assert browser.post(
        "/api/orders/AMC-NOT-FOUND/manage", json={"action": "cancel"}
    ).status_code == 401
    assert browser.post(
        "/api/orders/AMC-NOT-FOUND/review",
        json={"rating": 5, "body": "Synthetic", "visibility": "private"},
    ).status_code == 401


def test_unknown_route() -> None:
    response = client.get("/not-in-scope")
    assert response.status_code == 404
    assert "We could not find that page" in response.text
    assert client.get("/favicon.ico").status_code == 200


def test_current_public_titles_have_working_details() -> None:
    for slug, title in [
        ("the-odyssey", "The Odyssey"),
        ("spider-man-brand-new-day", "Spider-Man: Brand New Day"),
        ("paw-patrol-dino-movie", "PAW Patrol: The Dino Movie"),
    ]:
        response = client.get(f"/movies/{slug}")
        assert response.status_code == 200
        assert title in response.text


def test_movie_collection_closes_observed_two_batch_minimum() -> None:
    now_playing = client.get("/movies").text
    coming_soon = client.get("/movies?movie-list=coming-soon").text
    assert "23 movies" in now_playing
    assert "22 movies" in coming_soon
    now_slugs = set(re.findall(r'href="/movies/([^"?]+)"', now_playing))
    coming_slugs = set(re.findall(r'href="/movies/([^"?]+)"', coming_soon))
    assert len(now_slugs) == 23
    assert len(coming_slugs) == 22
    assert len(now_slugs | coming_slugs) == 40
    assert now_slugs | coming_slugs == {item["slug"] for item in MOVIES}
    for item in MOVIES:
        slug, title = item["slug"], item["title"]
        detail = client.get(f"/movies/{slug}")
        assert detail.status_code == 200
        assert title in detail.text


def test_local_assets_match_manifest_and_are_served() -> None:
    site = Path(__file__).resolve().parents[2]
    manifest = json.loads((site / "source-assets/manifest.json").read_text())
    assert manifest["closure_status"] == "declared"
    assert len(manifest["assets"]) == 57
    for asset in manifest["assets"]:
        source = site / asset["source_path"]
        runtime = site / asset["runtime_path"]
        assert source.read_bytes() == runtime.read_bytes()
        assert source.stat().st_size == asset["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == asset["sha256"]
        if asset["mime_type"] == "font/woff2":
            asset_prefix = "/local-fonts/"
        elif asset["mime_type"] == "image/svg+xml":
            asset_prefix = "/local-icons/"
        else:
            asset_prefix = "/local-assets/"
        response = client.get(asset_prefix + source.name)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(asset["mime_type"])


def test_no_remote_runtime_references_or_visible_demo_password() -> None:
    for route in ["/", "/movies", "/movie-theatres", "/showtimes", "/help", "/login"]:
        text = client.get(route).text
        assert not re.search(r"(?:src|href)=[\"']https?://", text)
    login = client.get("/login").text
    assert "demo12345" not in login
    assert 'value="guest@example.com"' not in login
    assert client.get("/password-reset").status_code == 200
    reset = client.post("/api/password-reset", json={"email": "missing@example.test"})
    assert reset.status_code == 200
    assert reset.json()["ok"] is True


def test_interactive_contracts_are_deterministic() -> None:
    home = client.get("/").text
    assert "setInterval" not in client.get("/assets/amc.js").text
    assert home.count('data-slide="') == 11
    assert "data-movie-tab" in home
    theatre = client.get("/movie-theatres/ny/amc-empire-25").text
    assert 'href="#"' not in theatre
    assert 'aria-label="Movie date"' in theatre
    assert theatre.count('class="showtime"') == 15
    assert "data-favorite-theatre" in theatre


def test_homepage_promotions_are_complete_and_ordered() -> None:
    home = client.get("/").text
    headings = [
        "Collect Yours Before They Are Extinct",
        "Snack and Sip All Summer Long",
        "This Big Poppin Deal Just Got Better",
        "Where A Legends Story Began",
        "Float Away with a New Classic",
        "The Official Fuel for Shenanigans",
    ]
    assert home.count('class="home-promotion') == 6
    assert [home.index(heading) for heading in headings] == sorted(
        home.index(heading) for heading in headings
    )
    assert home.count('class="home-promotion reverse"') == 3
    for filename in [
        "promo-pawpatrol-collectibles.jpg",
        "promo-snack-sip.jpg",
        "promo-popcorn-pass.jpg",
        "promo-tony.jpg",
        "promo-cherry-coke.jpg",
        "promo-super-troopers.jpg",
    ]:
        assert f"/local-assets/{filename}" in home


def test_homepage_has_no_remote_or_dead_links() -> None:
    home = client.get("/").text
    assert not re.search(r"(?:src|href)=[\"']https?://", home)
    hrefs = re.findall(r'href="([^"]+)"', home)
    assert "#" not in hrefs
    for href in hrefs:
        if href.startswith("#"):
            assert f'id="{href[1:]}"' in home
            continue
        path = href.split("#", 1)[0]
        response = client.get(path, follow_redirects=False)
        assert response.status_code in {200, 303}, href


def test_desktop_home_geometry_contract_is_declared() -> None:
    css = client.get("/assets/amc.css").text
    for declaration in [
        "--max:1248px",
        ".movies-home{height:906px",
        ".app-promo{height:221px",
        ".home-promotion{height:585px",
        ".offers-cta{height:118px",
        ".pre-footer-space{height:64px",
        "footer{height:876px",
    ]:
        assert declaration in css


def test_public_home_shell_visual_contract_is_complete() -> None:
    home = client.get("/").text
    css = client.get("/assets/amc.css").text
    assert '<a href="/food-and-drink">Buy</a> the 2026 AMC Popcorn Pass™' in home
    assert '<strong>get 50% off a daily large popcorn</strong>.' in home
    assert "Get 50% off* Tickets Two Days a Week" in home
    assert 'class="header-search"' in home
    assert 'class="mobile-tools"' in home
    assert home.count('class="dot') == 9
    assert "url('/local-assets/hero-stubs-desktop.jpg')" in css
    assert "url('/local-assets/hero-stubs-mobile.jpg')" in css
    assert "font-family:Gordita" in css
    assert css.count("/local-fonts/gordita-") == 4
    assert home.count('/local-icons/') >= 5
    assert "radial-gradient(transparent 50%,#000 100%),linear-gradient(45deg,#000,transparent 50%)" in css
    assert "grid-template-columns:292px 278px 306px 278px 278px" in css
    assert ".movies-home .movie-card:nth-child(3){order:-1;margin-left:0}" in css


def test_order_validation_and_retry_state() -> None:
    browser = TestClient(app)
    browser.get("/checkout/the-odyssey")
    base = {"movie_slug":"the-odyssey","theatre_slug":"amc-empire-25","showtime":"7:00 PM"}
    assert browser.post("/api/orders", json={**base,"seats":[],"scenario":"sandbox-approved"}).status_code == 400
    retry = browser.post("/api/orders", json={**base,"seats":["E4","E5"],"scenario":"sandbox-retry"})
    assert retry.status_code == 503
    assert "retry" in retry.json()["message"].lower()


def test_password_reset_uses_session_local_outbox() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    response = browser.post(
        "/api/password-reset", json={"email": "guest@example.com"}
    )
    assert response.status_code == 200
    outbox = browser.get("/api/local-outbox/password-reset").json()["message"]
    assert outbox["purpose"] == "password-reset"
    assert outbox["recipient"] == "guest@example.com"
    assert outbox["status"] == "LOCAL_ONLY"
    assert len(outbox["verification_code"]) == 6
    assert TestClient(app).get("/api/local-outbox/password-reset").json()["message"] is None


def test_auth_duplicate_stale_foreign_owner_and_session_revocation() -> None:
    owner = TestClient(app)
    owner.post("/api/reset")
    assert owner.post(
        "/api/signup",
        json={"name": "Weak", "email": "weak@example.test", "password": "short"},
    ).status_code == 400
    assert owner.post(
        "/api/signup",
        json={
            "name": "Duplicate",
            "email": "guest@example.com",
            "password": "valid-local-pass-123",
        },
    ).status_code == 409
    started = owner.post(
        "/api/signup",
        json={
            "name": "Expiring Member",
            "email": "expiring-member@example.test",
            "password": "valid-local-pass-123",
        },
    )
    assert started.status_code == 200
    code = owner.get("/api/local-outbox/registration").json()["message"][
        "verification_code"
    ]
    foreign = TestClient(app)
    assert foreign.post("/api/signup/verify", json={"code": code}).status_code == 400
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("UPDATE local_auth_registration_flows SET expires_at=0")
        connection.commit()
    assert owner.post("/api/signup/verify", json={"code": code}).status_code == 400
    assert owner.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "incorrect-pass"},
    ).status_code == 400
    assert owner.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    ).status_code == 200
    assert owner.get("/account").status_code == 200
    assert owner.post("/api/logout").status_code == 200
    assert owner.get("/account", follow_redirects=False).status_code == 303
    owner.post("/api/reset")


def test_verified_account_restart_concurrent_sign_in_and_password_reset_completion() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    assert browser.post(
        "/api/signup",
        json={
            "name": "Restart Member",
            "email": "restart-member@example.test",
            "password": "restart-local-pass-123",
        },
    ).status_code == 200
    code = browser.get("/api/local-outbox/registration").json()["message"][
        "verification_code"
    ]
    assert browser.post("/api/signup/verify", json={"code": code}).status_code == 200
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3,sys;"
                "c=sqlite3.connect(sys.argv[1]);"
                "r=c.execute('SELECT email_normalized,email_verified FROM local_auth_accounts WHERE email_normalized=?',(sys.argv[2],)).fetchone();"
                "assert r == (sys.argv[2], 1), r"
            ),
            str(DB_PATH),
            "restart-member@example.test",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr

    def sign_in(_index: int) -> int:
        response = TestClient(app).post(
            "/api/login",
            json={
                "email": "restart-member@example.test",
                "password": "restart-local-pass-123",
            },
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(sign_in, range(6))) == [200] * 6
    browser.post("/api/reset")
    started = browser.post(
        "/api/signup",
        json={
            "name": "Synthetic Member",
            "email": "synthetic-member@example.test",
            "password": "local-pass-123",
        },
    )
    assert started.status_code == 200
    assert started.json()["verification_required"] is True
    registration_mail = browser.get("/api/local-outbox/registration").json()["message"]
    assert registration_mail["status"] == "LOCAL_ONLY"
    verified = browser.post(
        "/api/signup/verify", json={"code": registration_mail["verification_code"]}
    )
    assert verified.status_code == 200
    assert "Hello, Synthetic Member" in browser.get("/account").text
    browser.post("/api/logout")
    assert browser.post(
        "/api/login",
        json={
            "email": "synthetic-member@example.test",
            "password": "local-pass-123",
        },
    ).status_code == 200

    browser.post("/api/logout")
    requested = browser.post(
        "/api/password-reset", json={"email": "synthetic-member@example.test"}
    )
    assert requested.status_code == 200
    reset_mail = browser.get("/api/local-outbox/password-reset").json()["message"]
    completed = browser.post(
        "/api/password-reset/complete",
        json={
            "code": reset_mail["verification_code"],
            "new_password": "replacement-pass-456",
        },
    )
    assert completed.status_code == 200
    browser.post("/api/logout")
    assert browser.post(
        "/api/login",
        json={
            "email": "synthetic-member@example.test",
            "password": "replacement-pass-456",
        },
    ).status_code == 200
    browser.post("/api/reset")


def test_account_state_survives_fresh_login_and_is_isolated_from_other_accounts() -> None:
    owner = TestClient(app)
    owner.post("/api/reset")
    assert owner.post(
        "/api/signup",
        json={
            "name": "Persistent Premiere Member",
            "email": "persistent-owner@example.test",
            "password": "persistent-local-pass-123",
            "plan": "premiere",
        },
    ).status_code == 200
    registration_code = owner.get("/api/local-outbox/registration").json()["message"][
        "verification_code"
    ]
    assert owner.post(
        "/api/signup/verify", json={"code": registration_code}
    ).status_code == 200
    assert owner.post(
        "/api/favorites", json={"movie_slug": "the-odyssey"}
    ).json()["saved"] is True
    assert owner.post(
        "/api/preferences",
        json={
            "preferred_theatre": "amc-lincoln-square-13",
            "notifications_enabled": True,
            "privacy_mode": "minimal",
        },
    ).status_code == 200
    order = owner.post(
        "/api/orders",
        json={
            "movie_slug": "the-odyssey",
            "theatre_slug": "amc-empire-25",
            "showtime": "7:00 PM",
            "seats": ["C3"],
            "scenario": "sandbox-approved",
        },
    ).json()
    order_id = order["order_id"]
    assert owner.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "notes", "notes": "Persistent synthetic metadata"},
    ).status_code == 200
    assert owner.post(
        f"/api/orders/{order_id}/review",
        json={
            "rating": 5,
            "body": "Persistent synthetic review",
            "visibility": "private",
        },
    ).status_code == 200
    assert owner.post("/api/logout").status_code == 200

    returning_owner = TestClient(app)
    assert returning_owner.post(
        "/api/login",
        json={
            "email": "persistent-owner@example.test",
            "password": "persistent-local-pass-123",
        },
    ).status_code == 200
    account = returning_owner.get("/account")
    assert "AMC Stubs Premiere" in account.text
    assert "The Odyssey" in account.text
    assert order_id[-8:] in account.text
    assert returning_owner.get("/api/preferences").json()["preferences"] == {
        "preferred_theatre": "amc-lincoln-square-13",
        "notifications_enabled": True,
        "privacy_mode": "minimal",
    }
    ticket = returning_owner.get(f"/account/orders/{order_id}")
    assert ticket.status_code == 200
    assert "Persistent synthetic metadata" in ticket.text
    assert "Persistent synthetic review" in ticket.text

    other = TestClient(app)
    assert other.post(
        "/api/signup",
        json={
            "name": "Other Local Member",
            "email": "other-member@example.test",
            "password": "other-local-pass-123",
        },
    ).status_code == 200
    other_code = other.get("/api/local-outbox/registration").json()["message"][
        "verification_code"
    ]
    assert other.post("/api/signup/verify", json={"code": other_code}).status_code == 200
    assert other.get(f"/account/orders/{order_id}").status_code == 404
    assert other.post(
        f"/api/orders/{order_id}/manage",
        json={"action": "notes", "notes": "Cross-account overwrite"},
    ).status_code == 404
    assert other.post(
        f"/api/orders/{order_id}/review",
        json={"rating": 1, "body": "Cross-account review", "visibility": "public"},
    ).status_code == 404
    other_account = other.get("/account")
    assert "The Odyssey" not in other_account.text
    assert order_id[-8:] not in other_account.text
    owner.post("/api/reset")


def test_reset_is_amc_only_and_restores_anonymous_seed_baseline() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    browser.post("/api/favorites", json={"movie_slug": "the-odyssey"})
    browser.post(
        "/api/orders",
        json={
            "movie_slug": "the-odyssey",
            "theatre_slug": "amc-empire-25",
            "showtime": "7:00 PM",
            "seats": ["A1"],
            "scenario": "sandbox-approved",
        },
    )
    browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    )
    reset = browser.post("/api/reset")
    assert reset.status_code == 200
    assert reset.json() == {
        "ok": True,
        "site_id": "amc-theatres",
        "auth_state": "anonymous",
        "authenticated": False,
        "favorites": [],
        "orders": [],
    }
    assert browser.get("/account", follow_redirects=False).status_code == 303
    assert "saved" not in browser.get("/movies/the-odyssey").text
    login = browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200
    assert "Your completed sandbox orders" in browser.get("/account").text


def test_database_location_schema_and_migrations_are_verifiable() -> None:
    clone_root = Path(__file__).resolve().parents[1]
    assert DB_PATH.resolve().parent.name == "data"
    assert clone_root.resolve() not in DB_PATH.resolve().parents
    with sqlite3.connect(DB_PATH) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "websitebench_backend_migrations",
            "local_auth_schema_migrations",
            "local_auth_accounts",
            "local_auth_sessions",
            "amc_favorites",
            "amc_orders",
            "amc_order_metadata",
            "amc_reviews",
            "amc_preferences",
            "amc_memberships",
        } <= tables
        order_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(amc_orders)")
        }
        assert {"ticket_type", "format_name", "attendee_name"} <= order_columns
        assert connection.execute(
            "SELECT COUNT(*) FROM websitebench_backend_migrations"
        ).fetchone()[0] >= 1
        assert connection.execute(
            "SELECT COUNT(*) FROM local_auth_schema_migrations"
        ).fetchone()[0] >= 4


def test_order_persists_across_an_independent_process() -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    created = browser.post(
        "/api/orders",
        json={
            "movie_slug": "the-odyssey",
            "theatre_slug": "amc-empire-25",
            "showtime": "7:00 PM",
            "seats": ["E4", "E5"],
            "scenario": "sandbox-approved",
        },
    ).json()
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3,sys;"
                "c=sqlite3.connect(sys.argv[1]);"
                "r=c.execute('SELECT status,seats_json FROM amc_orders WHERE order_id=?',(sys.argv[2],)).fetchone();"
                "assert r == ('approved', '[\"E4\", \"E5\"]'), r"
            ),
            str(DB_PATH),
            created["order_id"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
    browser.post("/api/reset")


def test_database_backup_restore_round_trip(tmp_path: Path) -> None:
    browser = TestClient(app)
    browser.post("/api/reset")
    order_id = browser.post(
        "/api/orders",
        json={
            "movie_slug": "the-odyssey",
            "theatre_slug": "amc-empire-25",
            "showtime": "8:45 PM",
            "seats": ["D4", "D5"],
            "scenario": "sandbox-approved",
        },
    ).json()["order_id"]
    backup_path = tmp_path / "amc-backup.sqlite3"
    with sqlite3.connect(DB_PATH) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("DELETE FROM amc_orders WHERE order_id=?", (order_id,))
        connection.commit()
        assert connection.execute(
            "SELECT 1 FROM amc_orders WHERE order_id=?", (order_id,)
        ).fetchone() is None
    with sqlite3.connect(backup_path) as backup, sqlite3.connect(DB_PATH) as target:
        backup.backup(target)
    with sqlite3.connect(DB_PATH) as connection:
        assert connection.execute(
            "SELECT status FROM amc_orders WHERE order_id=?", (order_id,)
        ).fetchone() == ("approved",)
    browser.post("/api/reset")


def test_wal_concurrency_preserves_distinct_orders() -> None:
    TestClient(app).post("/api/reset")

    def create(index: int) -> tuple[int, str]:
        browser = TestClient(app)
        response = browser.post(
            "/api/orders",
            json={
                "movie_slug": "the-odyssey",
                "theatre_slug": "amc-empire-25",
                "showtime": "7:00 PM",
                "seats": [f"A{index + 1}"],
                "scenario": "sandbox-approved",
            },
        )
        return response.status_code, response.json().get("order_id", "")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(8)))
    assert [status for status, _ in results] == [200] * 8
    order_ids = [order_id for _, order_id in results]
    assert len(set(order_ids)) == 8
    with sqlite3.connect(DB_PATH) as connection:
        placeholders = ",".join("?" for _ in order_ids)
        assert connection.execute(
            f"SELECT COUNT(*) FROM amc_orders WHERE order_id IN ({placeholders})",
            order_ids,
        ).fetchone()[0] == 8
    TestClient(app).post("/api/reset")
