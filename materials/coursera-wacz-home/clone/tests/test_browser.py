from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, expect, sync_playwright


@pytest.fixture()
def page(live_server: str):
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1191, "height": 979})
        page = context.new_page()
        requests: list[str] = []
        page.on("request", lambda request: requests.append(request.url))
        page.goto(live_server + "/", wait_until="networkidle")
        yield page, live_server, requests
        context.close()
        browser.close()


def visible_promos(page: Page) -> list[str]:
    return page.locator("[data-promo-card]:visible").evaluate_all(
        "cards => cards.map(card => card.dataset.promoCard)"
    )


def test_promotions_change_only_after_explicit_controls(page) -> None:
    """Catch manual promo controls breaking or a timer advancing the cards."""

    browser_page, _, _ = page
    assert visible_promos(browser_page) == ["google-vibe", "join-free"]

    browser_page.get_by_role("button", name="Next featured items").click()
    assert visible_promos(browser_page) == ["join-free", "coursera-business"]
    expect(browser_page.get_by_role("button", name="Go to item 2")).to_have_attribute(
        "aria-current", "true"
    )

    browser_page.wait_for_timeout(800)
    assert visible_promos(browser_page) == ["join-free", "coursera-business"]

    browser_page.get_by_role("button", name="Next featured items").press("ArrowRight")
    assert visible_promos(browser_page) == ["coursera-business", "google-vibe"]
    browser_page.get_by_role("button", name="Next featured items").press("ArrowLeft")
    assert visible_promos(browser_page) == ["join-free", "coursera-business"]

    browser_page.get_by_role("button", name="Go to item 1").click()
    assert visible_promos(browser_page) == ["google-vibe", "join-free"]


def test_cookie_explanation_and_archive_boundary_stay_local(page) -> None:
    """Catch homepage-only actions navigating away or contacting a remote origin."""

    browser_page, base_url, requests = page
    browser_page.get_by_role("button", name="Cookie preferences").click()
    expect(browser_page.get_by_role("dialog", name="Cookie preferences")).to_be_visible()
    browser_page.get_by_role("button", name="Close cookie preferences").click()
    expect(browser_page.get_by_role("dialog", name="Cookie preferences")).to_be_hidden()

    browser_page.get_by_placeholder("What do you want to learn?").fill("machine learning")
    browser_page.get_by_role("button", name="Search").click()
    expect(browser_page.locator("[data-archive-notice]")).to_contain_text(
        "supplied archive contains the homepage only"
    )
    assert browser_page.url == base_url + "/"

    browser_page.get_by_role("button", name="Log In").click()
    expect(browser_page.locator("[data-archive-notice]")).to_be_visible()
    assert browser_page.url == base_url + "/"

    assert requests
    assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)


def test_mobile_layout_has_no_horizontal_overflow(page) -> None:
    """Catch the desktop reconstruction forcing sideways scrolling on mobile."""

    browser_page, _, _ = page
    browser_page.set_viewport_size({"width": 390, "height": 844})
    browser_page.reload(wait_until="networkidle")

    overflow = browser_page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0
    assert len(visible_promos(browser_page)) == 2


def test_business_offer_uses_the_archived_portrait_art(page) -> None:
    """Catch the business tile stretching its short wordmark as portrait art."""

    browser_page, _, _ = page
    image = browser_page.locator(".business-card > img")

    assert image.evaluate("element => element.naturalHeight") >= 120
    assert image.evaluate("element => element.naturalWidth") >= 150


def test_learning_pathways_match_the_archived_illustrated_cards(page) -> None:
    """Catch the three WACZ pathway illustrations regressing to text glyphs."""

    browser_page, _, _ = page
    cards = browser_page.locator("[data-pathway-card]")

    assert cards.count() == 3
    assert cards.evaluate_all(
        "buttons => buttons.map(button => button.innerText.trim())"
    ) == [
        "Launch a new career",
        "Try Coursera for Business",
        "Earn a degree",
    ]

    expected_art_heights = [41, 51, 50]
    for index, expected_height in enumerate(expected_art_heights):
        card_bounds = cards.nth(index).bounding_box()
        assert card_bounds is not None
        assert abs(card_bounds["width"] - 354.33) <= 0.6
        assert card_bounds["height"] == 110

        art = cards.nth(index).locator("[data-pathway-art]")
        expect(art).to_be_visible()
        bounds = art.bounding_box()
        assert bounds is not None
        assert bounds["width"] == 50
        assert abs(bounds["height"] - expected_height) <= 0.5


def test_learning_pathways_use_the_original_wacz_art_assets(page) -> None:
    """Catch the archived pathway art being replaced by approximate drawings."""

    browser_page, _, _ = page
    artwork = browser_page.locator("[data-pathway-card] [data-pathway-art]")
    expected = [
        ("/static/assets/pathway-career.avif", 100, 82),
        ("/static/assets/pathway-business.avif", 100, 102),
        ("/static/assets/pathway-degree.avif", 100, 100),
    ]

    assert artwork.count() == len(expected)
    for index, (source, width, height) in enumerate(expected):
        image = artwork.nth(index)
        assert image.evaluate("element => element.tagName") == "IMG"
        assert image.get_attribute("src") == source
        assert image.evaluate("element => element.naturalWidth") == width
        assert image.evaluate("element => element.naturalHeight") == height


def test_purpose_choices_match_the_archived_blue_icon_tiles(page) -> None:
    """Catch the four WACZ purpose pictograms regressing to plain characters."""

    browser_page, _, _ = page
    choices = browser_page.locator("[data-purpose-choice]")

    assert choices.count() == 4
    for index in range(4):
        choice_bounds = choices.nth(index).bounding_box()
        assert choice_bounds is not None
        assert choice_bounds["height"] == 56
        assert choices.nth(index).evaluate(
            "element => getComputedStyle(element).borderRadius"
        ) == "16px"

        icon = choices.nth(index).locator("[data-purpose-icon]")
        expect(icon).to_be_visible()
        bounds = icon.bounding_box()
        assert bounds is not None
        assert bounds["width"] == 40
        assert abs(bounds["width"] - bounds["height"]) <= 1
        assert icon.evaluate("element => getComputedStyle(element).backgroundColor") == (
            "rgb(0, 96, 235)"
        )

        pictogram = icon.locator("svg")
        expect(pictogram).to_be_visible()
        pictogram_bounds = pictogram.bounding_box()
        assert pictogram_bounds is not None
        assert pictogram_bounds["width"] > 0
        assert pictogram_bounds["height"] > 0


def test_purpose_choices_use_the_original_wacz_single_path_icons(page) -> None:
    """Catch the archived purpose icons being replaced by generic line symbols."""

    browser_page, _, _ = page
    pictograms = browser_page.locator("[data-purpose-icon] svg")

    assert pictograms.count() == 4
    for index in range(4):
        pictogram = pictograms.nth(index)
        assert pictogram.get_attribute("viewBox") == "0 0 24 24"
        assert pictogram.locator("path").count() == 1
        assert pictogram.locator("rect, circle, polygon, polyline, line").count() == 0
        assert pictogram.locator("path").get_attribute("fill") == "white"
