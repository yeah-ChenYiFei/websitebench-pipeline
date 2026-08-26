"""App-surface tests: every public route renders, key journeys work end to end,
and the 404/help/contact surfaces behave as declared."""

from __future__ import annotations


import pytest

import app as app_module
from backend import craigslist_db


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


def _detail_path_for(category: str, title: str) -> str:
    rows = craigslist_db.search_postings("toronto", category=category, query=title)
    posting = next(row for row in rows if row["title"] == title)
    return f"/view/d/{posting['slug']}/{app_module._posting_code(posting['id'])}"


def test_reviewed_fishing_buddy_body_and_community_family(client) -> None:
    path = _detail_path_for("act", "Fishing Buddy")
    detail = client.get(path)
    assert detail.status_code == 200
    assert 'data-detail-family="community"' in detail.text
    assert (
        "Looking for a fishing buddy in and around the london area. "
        "If interested to find out more get back to me."
    ) in detail.text
    assert 'aria-label="housing details"' not in detail.text
    assert "posted:" in detail.text.lower()


def test_reviewed_sale_post_has_rich_body_dates_and_local_gallery(client) -> None:
    title = "Supercycle Dreamweaver Freestyle purple bicycle with colourful streamers"
    path = _detail_path_for("bia", title)
    detail = client.get(path)
    assert detail.status_code == 200
    assert 'data-detail-family="for-sale"' in detail.text
    assert "Stylish purple Super cycle dreamweaver bicycle" in detail.text
    assert "updated:" in detail.text.lower()
    assert detail.text.count("dreamweaver-bike-") >= 13  # main image + 12 thumbs
    for index in range(1, 13):
        image = client.get(f"/static/assets/seed-photos/dreamweaver-bike-{index:02d}.jpg")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"


def test_every_seeded_posting_has_nontrivial_body_copy(client) -> None:
    with craigslist_db.connect() as connection:
        incomplete = connection.execute(
            "SELECT id, title, description FROM cl_postings "
            "WHERE status != 'removed' AND "
            "(length(trim(description)) < 40 OR trim(description) = trim(title))"
        ).fetchall()
    assert incomplete == []


@pytest.mark.parametrize(
    ("category", "family", "absent_filter", "summary"),
    [
        ("act", "community", "bedrooms", "community-summary"),
        ("bia", "for-sale", "bedrooms", "posted-date"),
        ("sof", "jobs", "housing type", "job-summary"),
        ("aos", "services", "housing type", "service-summary"),
        ("apa", "housing", "never-present-filter", "housing-summary"),
    ],
)
def test_category_pages_use_section_specific_search_cards(
    client, category: str, family: str, absent_filter: str, summary: str
) -> None:
    page = client.get(f"/search/area/toronto?cat={category}")
    assert page.status_code == 200
    assert f'data-search-family="{family}"' in page.text
    assert summary in page.text
    assert absent_filter not in page.text.lower()
    assert 'href="#"' not in page.text


def test_homepage_expando_controls_have_local_behavior(client) -> None:
    home = client.get("/area/toronto")
    assert home.status_code == 200
    assert "cl-link-expando-group" in home.text
    assert "cl-local-storage" not in home.text
    script = client.get("/static/js/site.js")
    assert "aria-expanded" in script.text
    assert 'querySelectorAll(".cl-link-expando-group")' in script.text
