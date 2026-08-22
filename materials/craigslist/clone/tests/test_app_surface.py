"""App-surface tests: every public route renders, key journeys work end to end,
and the 404/help/contact surfaces behave as declared."""

from __future__ import annotations


import pytest


ROUTES_OK = [
    "/",
    "/toronto/",
    "/vancouver/",
    "/toronto/housing/",
    "/toronto/housing/sub/",
    "/toronto/housing/apa/",
    "/toronto/housing/roo/",
    "/toronto/housing/rea/",
    "/toronto/search/housing",
    "/toronto/search/housing/sub?query=annex",
    "/toronto/search/housing?min_price=2000&max_price=3000&postal=M6G&postedToday=1",
    "/toronto/search/housing?query=zzzz-no-match-websitebench",
    "/toronto/housing/sub/d/1000001/1br-near-annex-furnished-sublet-jul-aug",
    "/toronto/housing/apa/d/1000021/2br-apartment-leslieville",
    "/toronto/housing/roo/d/1000031/room-kensington-market",
    "/toronto/housing/reply/1000001",
    "/flag/1000001",
    "/account/login",
    "/account/register",
    "/account/forgot",
    "/account/reset",
    "/about",
    "/about/help",
    "/about/help/posting",
    "/about/help/account",
    "/about/help/housing",
    "/about/terms",
    "/about/privacy",
    "/contact",
]


@pytest.mark.parametrize("path", ROUTES_OK)
def test_public_routes_render(client, path) -> None:
    response = client.get(path)
    assert response.status_code == 200, path
    assert "<!DOCTYPE html>" in response.text or "<!doctype html>" in response.text


def test_health_endpoints(client) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"ok": True, "site_id": "craigslist"}
    harbor = client.get("/__websitebench/health")
    assert harbor.status_code == 200
    assert harbor.json() == {"status": "ok"}


def test_branded_not_found_preserves_navigation(client) -> None:
    response = client.get("/toronto/housing/d/999999999/does-not-exist")
    assert response.status_code == 404
    assert "oops!" in response.text
    assert "craigslist home" in response.text
    assert "/toronto/housing/" in response.text


def test_front_page_links_to_housing_and_regions(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "/search/area/toronto?cat=hhh" in page.text or "/area/toronto" in page.text
    assert "/area/newyork" in page.text or "/newyork/" in page.text
    assert "post an ad" in page.text or "create a posting" in page.text or "post" in page.text


def test_housing_navigation_from_entry(client) -> None:
    """User task 1: public entry -> housing section with visible heading."""
    page = client.get("/")
    assert page.status_code == 200
    assert "housing" in page.text
    housing = client.get("/search/area/toronto?cat=hhh")
    assert housing.status_code == 200
    assert "housing" in housing.text.lower()
    assert "sublet" in housing.text.lower()


def test_listing_detail_surface(client) -> None:
    detail = client.get("/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93")
    assert detail.status_code == 200
    for marker in (
        "post id",
        "posted by",
        "reply",
        "avoid scams",
        "$2,400",
        "furnished",
    ):
        assert marker in detail.text.lower()
    assert "annex" in detail.text.lower()  # description content


def test_registration_verify_only_surface(client) -> None:
    page = client.get("/account/register")
    assert page.status_code == 200
    for marker in ("email address", "password", "terms of use", "verification"):
        assert marker in page.text.lower()


def test_signin_verify_only_surface(client) -> None:
    page = client.get("/account/login")
    assert page.status_code == 200
    assert "email" in page.text.lower()
    assert "password" in page.text.lower()


def test_help_surface_no_private_data(client) -> None:
    for path in ("/about/help", "/about/help/posting", "/about/help/account", "/about/help/housing"):
        page = client.get(path)
        assert page.status_code == 200
        assert "poster@example.com" not in page.text  # never expose account data


def test_contact_validation_and_sent(client) -> None:
    empty = client.post("/contact", data={"category": "", "message": ""})
    assert empty.status_code == 422
    sent = client.post(
        "/contact",
        data={"category": "report an issue", "subject": "hello", "message": "test message"},
    )
    assert sent.status_code == 200
    assert "received" in sent.text.lower()


def test_region_shells(client) -> None:
    for region in ("vancouver", "montreal", "newyork", "losangeles", "chicago", "seattle", "london", "sydney"):
        page = client.get(f"/{region}/")
        assert page.status_code == 200, region


def test_static_assets_served(client) -> None:
    css = client.get("/static/css/site.css")
    assert css.status_code == 200
    js = client.get("/static/js/site.js")
    assert js.status_code == 200
    photo = client.get("/static/assets/seed-photos/apt-annex-1.svg")
    assert photo.status_code == 200
