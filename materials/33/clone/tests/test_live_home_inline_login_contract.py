"""Contracts for the current live Coursera home and same-document login."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT / "clone"))

from app import app  # noqa: E402
from test_desktop_visual import _clone_server  # noqa: E402


client = TestClient(app)
VIEWPORT = {"width": 1692, "height": 979}


def test_home_uses_current_live_section_identity_and_order() -> None:
    html = client.get("/").text
    expected = (
        "New and popular",
        "Get job-ready for an in-demand career",
        "Learn from 350+ leading universities and companies",
        "Explore categories",
        "Trending searches",
        "What brings you to Coursera today?",
        "91% of learners achieved a positive career outcome",
        "Why people choose Coursera",
        "Frequently asked questions",
    )

    positions = [html.index(marker) for marker in expected]
    assert positions == sorted(positions)
    assert "Online degrees" not in html
    assert "Trending now" not in html
    assert "In-demand skills" not in html
    assert "New releases" not in html
    assert "Leading partners" not in html


def test_home_shell_matches_live_fullscreen_measurement() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")
                shell = page.locator(".source-home-shell").bounding_box()
                assert shell is not None
                assert abs(shell["x"] - 174) <= 2
                assert abs(shell["width"] - 1344) <= 2
        finally:
            context.close()
            browser.close()


def test_home_learning_cards_fill_the_shell_with_loaded_local_images() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")
                shell = page.locator(".source-home-shell").bounding_box()
                first_row = page.locator(".home-new-popular .home-source-columns").bounding_box()
                cards = page.locator(".source-list-card, .source-learning-card")
                images = cards.locator("img.source-card-image")

                assert shell is not None and first_row is not None
                assert abs(first_row["x"] - shell["x"]) <= 2
                assert abs(first_row["width"] - shell["width"]) <= 2
                assert cards.count() >= 30
                assert images.count() == cards.count()
                assert all(
                    images.nth(index).evaluate("image => image.complete && image.naturalWidth > 0")
                    for index in range(images.count())
                )
        finally:
            context.close()
            browser.close()


def test_home_sections_follow_the_source_full_page_vertical_geometry() -> None:
    """Catch compact clone sections accumulating a large lower-page offset."""

    playwright = pytest.importorskip("playwright.sync_api")
    expected_boxes = {
        ".promo-panel:first-of-type": (121, 298),
        ".source-career-ready": (884, 337),
        ".source-promo-row": (1256, 196),
        ".source-pathways": (1594, 110),
        ".source-google-collection": (1889, 302),
        ".source-ai-collection": (2655, 341),
        ".home-purpose": (3027, 104),
        ".source-outcomes": (3580, 196),
        ".home-testimonial-grid figure:first-child": (3844, 224),
    }

    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")

                for selector, (expected_y, expected_height) in expected_boxes.items():
                    box = page.locator(selector).bounding_box()
                    assert box is not None
                    assert abs(box["y"] - expected_y) <= 12, selector
                    assert abs(box["height"] - expected_height) <= 12, selector

                footer = page.locator(".wb-footer").bounding_box()
                footer_secondary = page.locator(
                    ".source-browse-footer-secondary"
                ).bounding_box()
                footer_legal = page.locator(
                    ".source-browse-footer-legal"
                ).bounding_box()
                assert footer is not None
                assert footer_secondary is not None
                assert footer_legal is not None
                assert abs(footer["y"] - 4623) <= 16
                assert abs(footer_secondary["y"] - 5119) <= 16
                assert abs(footer_legal["y"] - 5681) <= 16
                assert abs(page.evaluate("document.documentElement.scrollHeight") - 5826) <= 20
        finally:
            context.close()
            browser.close()


def test_colored_home_collections_match_source_card_and_tab_geometry() -> None:
    """Catch collection cards being compressed or source tabs moving below them."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")

                career_tabs = page.locator(".source-career-tabs").bounding_box()
                career_card = page.locator(
                    ".source-career-ready .source-learning-card"
                ).first.bounding_box()
                google_card = page.locator(
                    ".source-google-collection .source-learning-card"
                ).first.bounding_box()
                ai_tabs = page.locator(".source-ai-tabs")
                ai_card = page.locator(
                    ".source-ai-collection .source-learning-card"
                ).first.bounding_box()

                assert career_tabs is not None
                assert career_card is not None
                assert google_card is not None
                assert ai_card is not None
                assert abs(career_tabs["y"] - 898) <= 12
                assert career_tabs["y"] + career_tabs["height"] <= career_card["y"]
                assert abs(career_card["y"] - 939) <= 12
                assert abs(career_card["height"] - 267) <= 12
                assert abs(career_card["x"] - 477) <= 8
                assert abs(career_card["width"] - 220) <= 8
                assert abs(google_card["y"] - 1909) <= 12
                assert abs(google_card["height"] - 266) <= 12
                assert abs(google_card["x"] - 477) <= 8
                assert abs(google_card["width"] - 220) <= 8
                assert ai_tabs.locator(":scope > *").all_inner_texts() == [
                    "Get Started",
                    "Bestsellers",
                    "Tools",
                    "Advanced",
                    "Agentic AI",
                    "Resume Builder",
                ]
                assert abs(ai_card["y"] - 2710) <= 12
                assert abs(ai_card["height"] - 236) <= 12
                assert abs(ai_card["x"] - 477) <= 8
                assert abs(ai_card["width"] - 220) <= 8
        finally:
            context.close()
            browser.close()


def test_header_login_opens_email_only_dialog_without_navigation() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")
                page.get_by_role("button", name="Log In").click()
                assert page.url == base_url + "/"
                dialog = page.get_by_role("dialog")
                assert dialog.is_visible()
                assert dialog.locator('input[type="email"]').count() == 1
                assert dialog.locator('input[type="password"]').count() == 0
                assert dialog.get_by_text("Log in or create account").is_visible()
                assert dialog.get_by_text("Continue with Google").is_visible()
                assert dialog.get_by_text("Continue with Facebook").is_visible()
                assert dialog.get_by_text("Continue with Apple").is_visible()
        finally:
            context.close()
            browser.close()


def test_login_overlay_preserves_the_invoking_public_page() -> None:
    """Login is a same-document overlay, never a replacement backdrop."""
    playwright = pytest.importorskip("playwright.sync_api")
    cases = (
        ("/", ".home-new-popular .home-source-columns"),
        ("/browse", ".source-browse-categories"),
        ("/search?query=deep%20learning", ".search-results-section"),
        ("/specializations/deep-learning", ".source-specialization-hero"),
        ("/learn/neural-networks-deep-learning", ".source-course-detail-hero"),
    )
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                for path, landmark in cases:
                    page = context.new_page()
                    page.goto(base_url + path, wait_until="networkidle")
                    before_url = page.url
                    before_height = page.evaluate("document.documentElement.scrollHeight")
                    assert page.locator(landmark).is_visible(), path

                    page.get_by_role("button", name="Log In").click()

                    assert page.url == before_url
                    assert page.get_by_role("dialog").is_visible(), path
                    assert page.locator(landmark).is_visible(), path
                    assert page.evaluate("document.documentElement.scrollHeight") == before_height
                    page.close()
        finally:
            context.close()
            browser.close()


def test_direct_login_is_standalone_page_and_synthetic_email_reveals_password() -> None:
    """The observed /login renders its own white page with a centered dialog."""
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/login", wait_until="networkidle")
                assert page.url == base_url + "/login"
                assert page.locator(".source-auth-standalone").is_visible()
                assert page.locator(".source-login-dialog").is_visible()
                dialog = page.get_by_role("dialog")
                assert dialog.is_visible()
                assert dialog.locator('input[type="password"]').count() == 0
                dialog.locator('input[type="email"]').fill("learner@example.test")
                dialog.get_by_role("button", name="Continue", exact=True).click()
                assert dialog.locator('input[type="password"]').count() == 1
        finally:
            context.close()
            browser.close()


def test_signup_uses_the_standalone_page_identity() -> None:
    """Join for Free opens the standalone auth surface, not a promo backdrop."""
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")

                page.get_by_role("link", name="Join for Free").first.click()
                page.wait_for_load_state("networkidle")

                assert page.url == base_url + "/signup"
                assert page.locator(".source-auth-standalone").is_visible()
                dialog = page.locator("[data-login-dialog]")
                assert dialog.is_visible()
                assert dialog.locator('input[type="email"]').is_visible()
                assert dialog.locator('input[type="password"]').count() == 0
                assert page.locator("[data-signup-dialog]").count() == 0
                assert page.locator(".auth-modal-shell").count() == 0
                assert page.locator(".promo-panel").count() == 0
                body_text = page.locator("body").inner_text()
                assert "Log in or create an account" in body_text
        finally:
            context.close()
            browser.close()
