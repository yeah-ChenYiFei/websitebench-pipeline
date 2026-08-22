"""Contracts for the supplied signed-out Business page snapshot."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SITE_ROOT = Path(__file__).resolve().parents[2]
CLONE_ROOT = SITE_ROOT / "clone"
SNAPSHOT = CLONE_ROOT / "snapshots" / "business-current.html"
sys.path.insert(0, str(CLONE_ROOT))

from app import app  # noqa: E402
from test_desktop_visual import _clone_server  # noqa: E402


client = TestClient(app)
VIEWPORT = {"width": 1692, "height": 979}

EXPECTED_SECTIONS = (
    "Most popular",
    "Explore roles",
    "Trending now",
    "Core skills",
    "Dive into Neural Networks: Bridging Deep Learning and Business Intelligence",
    "Online degrees",
    "Explore Categories",
    "All results",
    "New releases",
    "What brings you to Coursera today?",
    "Leading partners",
    "Frequently asked questions",
)

EXPECTED_CARDS = (
    "Generative AI for Project Managers",
    "Generative AI for Business Analysts",
    "Business Foundations",
    "Generative AI for Digital Marketing",
    "Content Creator",
    "Scrum Master",
    "Generative AI Strategic Leader",
    "Generative AI Leadership &amp; Strategy",
    "IBM Product Owner",
    "ChatGPT for Project Management - Leveraging AI for Success",
    "Deep Learning for Business",
    "AI For Business",
    "AI Fundamentals for Non-Data Scientists",
    "GenAI for Business Analysts: Faster Insights",
    "Bachelor of Arts in Liberal Studies",
    "Bachelor of Science in General Business",
    "Master of Business Administration",
    "Master of Science in Engineering Management",
    "Google Project Management",
    "Google Digital Marketing &amp; E-commerce",
    "AI For Everyone",
    "Introduction to Finance and Accounting",
    "Financial Markets",
    "Intuit Academy Bookkeeping",
    "IBM Business Analyst",
    "Key Technologies for Business",
    "Finance &amp; Quantitative Modeling for Analysts",
    "Excel Skills for Business",
    "Introduction to Business Strategy",
    "Business Analysis with AI",
    "Claude Skills: Automating Business Workflows",
    "Boost Your Business Skills",
)


def _product_card(page, title: str):
    heading = page.get_by_role("heading", name=title, exact=True).first
    return heading.locator(
        "xpath=ancestor::div[contains(@class, 'cds-ProductCard-base')]"
    ).first


def test_business_route_contains_the_complete_supplied_snapshot_inventory() -> None:
    response = client.get("/browse/business")

    assert response.status_code == 200
    assert "<title>Business Online Courses | Coursera</title>" in response.text
    for section in EXPECTED_SECTIONS:
        assert section in response.text
    for card in EXPECTED_CARDS:
        assert card in response.text


def test_business_snapshot_is_scriptless_and_network_closed() -> None:
    html = SNAPSHOT.read_text(encoding="utf-8")
    hrefs = re.findall(r'href="([^"]*)"', html)

    assert 'data-websitebench-snapshot="business-2026-08-19-233413"' in html
    assert "<script" not in html.lower()
    assert "http://" not in html
    assert "https://" not in html
    assert html.count("<img") == 90
    assert html.count("data:image/") >= 75
    assert hrefs
    assert all(
        not href.startswith(("http:", "https:", "//", "data:")) for href in hrefs
    )


def test_business_route_allows_only_its_local_interaction_script() -> None:
    response = client.get("/browse/business")
    policy = response.headers["content-security-policy"]

    assert "script-src 'self'" in policy
    assert "connect-src 'none'" in policy
    assert "object-src 'none'" in policy
    assert "img-src 'self' data:" in policy
    assert "style-src 'self' 'unsafe-inline'" in policy
    assert '<script src="/static/public-interactions.js" defer></script>' in response.text
    assert re.findall(r'<script[^>]+src="https?://', response.text) == []


def test_business_login_hash_opens_over_the_unchanged_snapshot() -> None:
    """The scriptless snapshot still keeps Business behind its login surface."""
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/browse/business", wait_until="networkidle")
                before_height = page.evaluate("document.documentElement.scrollHeight")
                assert page.get_by_role("heading", name="Business", exact=True).is_visible()

                page.get_by_role("button", name="Log In").click()

                assert page.url == base_url + "/browse/business#authMode=login"
                assert page.get_by_role("heading", name="Business", exact=True).is_visible()
                assert page.locator("[data-business-login-overlay]").is_visible()
                assert page.locator('[data-business-login-overlay] input[type="email"]').is_visible()
                assert page.evaluate("document.documentElement.scrollHeight") == before_height
        finally:
            context.close()
            browser.close()


def test_business_fullscreen_geometry_matches_the_supplied_page() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                failed_requests: list[str] = []
                page.on("requestfailed", lambda request: failed_requests.append(request.url))
                page.goto(base_url + "/browse/business", wait_until="networkidle")

                assert page.title() == "Business Online Courses | Coursera"
                assert page.evaluate(
                    "() => [document.documentElement.clientWidth, "
                    "document.documentElement.clientHeight]"
                ) == [1692, 979]
                assert page.evaluate("() => document.documentElement.scrollHeight") == 8990
                assert failed_requests == []
                assert page.locator("main h2").count() == 13
                assert page.locator(".cds-ProductCard-base").count() == 34
                assert page.locator("img").count() == 90
                assert page.locator("img").evaluate_all(
                    "images => images.filter(image => image.complete && "
                    "image.naturalWidth > 0).length"
                ) >= 60

                business = page.get_by_role("heading", name="Business", exact=True)
                popular = _product_card(page, "Generative AI for Project Managers")
                role = _product_card(page, "Content Creator")
                second_role = _product_card(page, "Scrum Master")
                result = _product_card(page, "Google Project Management")

                business_box = business.bounding_box()
                popular_box = popular.bounding_box()
                role_box = role.bounding_box()
                second_role_box = second_role.bounding_box()
                result_box = result.bounding_box()

                assert all(
                    box is not None
                    for box in (
                        business_box,
                        popular_box,
                        role_box,
                        second_role_box,
                        result_box,
                    )
                )
                assert abs(business_box["x"] - 174) <= 1
                assert abs(popular_box["x"] - 174) <= 1
                assert abs(popular_box["width"] - 324) <= 1
                assert abs(role_box["width"] - 452) <= 1
                assert abs(role_box["height"] - 226) <= 1
                assert abs(second_role_box["x"] - role_box["x"] - 490) <= 1
                assert abs(result_box["width"] - 333) <= 1

                expected_y = {
                    "Most popular": 316,
                    "Explore roles": 866,
                    "Trending now": 1120,
                    "Core skills": 1583,
                    "Online degrees": 2196,
                    "Explore Categories": 2948,
                    "All results": 3161,
                    "New releases": 5700,
                    "What brings you to Coursera today?": 6178,
                    "Leading partners": 6275,
                    "Frequently asked questions": 6344,
                }
                for title, y in expected_y.items():
                    box = page.get_by_role("heading", name=title, exact=True).bounding_box()
                    assert box is not None
                    assert abs(box["y"] - y) <= 2
        finally:
            context.close()
            browser.close()
