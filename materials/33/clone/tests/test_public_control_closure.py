"""Browser and route closure for anonymous public discovery controls."""

from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app import app
from test_desktop_visual import _clone_server


VIEWPORT = {"width": 1692, "height": 979}


class _LocalAnchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.add(href)


def _catalog_ids(markup: str) -> set[str]:
    return set(re.findall(r'data-catalog-record="([^"]+)"', markup))


def test_home_tabs_and_promo_controls_change_real_visible_content() -> None:
    """Catch home switches that remain labels or swap no rendered content."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")

                bestsellers = page.get_by_role("button", name="Bestsellers")
                bestsellers.click()
                panel = page.locator("[data-collection-panel]:visible")
                assert panel.get_attribute("data-key") == "bestsellers"
                assert bestsellers.get_attribute("aria-selected") == "true"

                before = page.locator(
                    '[data-promo-panel][aria-hidden="false"] .promo-title'
                ).inner_text()
                page.get_by_role("button", name="Next promotion").click()
                after = page.locator(
                    '[data-promo-panel][aria-hidden="false"] .promo-title'
                ).inner_text()
                assert after != before
        finally:
            context.close()
            browser.close()


def test_every_anchor_on_public_discovery_pages_resolves_locally() -> None:
    """Catch a visible public card or source path that ends at a missing route."""

    pages = (
        "/",
        "/browse",
        "/browse/data-science",
        "/browse/business",
        "/search?query=deep%20learning",
    )
    failures: list[tuple[str, int]] = []
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        anchors: set[str] = set()
        for path in pages:
            response = client.get(path)
            assert response.status_code == 200
            parser = _LocalAnchors()
            parser.feed(response.text)
            anchors.update(parser.hrefs)

        for href in sorted(anchors):
            parsed = urlsplit(href)
            if (
                href.startswith("#")
                or parsed.scheme
                or parsed.netloc
                or not parsed.path.startswith("/")
            ):
                continue
            response = client.get(href, follow_redirects=True)
            if response.status_code in {404, 405}:
                failures.append((href, response.status_code))

    assert failures == []


@pytest.mark.parametrize(
    ("path", "heading"),
    (
        ("/courseraplus", "Coursera Plus"),
        ("/business/teams", "Coursera for Teams"),
        ("/career-academy", "Career Academy"),
        ("/degrees", "Degrees"),
        ("/partners/google", "Google"),
        ("/explore/ibm-online-courses", "IBM"),
    ),
)
def test_source_path_aliases_show_matching_records_and_browse_recovery(
    path: str, heading: str
) -> None:
    """Catch source-path aliases that are generic fake-success pages."""

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert f"<h1>{heading}</h1>" in response.text
    assert 'data-public-landing-record="' in response.text
    assert 'href="/browse"' in response.text


def test_search_filters_change_the_rendered_catalog_record_ids() -> None:
    """Catch a filter form that reloads without applying its query state."""

    with TestClient(app) as client:
        broad = client.get(
            "/search", params={"q": "", "rating": "4.0"}
        )
        filtered = client.get(
            "/search", params={"q": "", "rating": "4.8"}
        )

    broad_ids = _catalog_ids(broad.text)
    filtered_ids = _catalog_ids(filtered.text)
    assert broad_ids
    assert filtered_ids
    assert filtered_ids < broad_ids


def test_faq_controls_update_expanded_state_and_visible_answer() -> None:
    """Catch FAQ controls whose label changes but answer state does not."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")
                question = page.get_by_role(
                    "button",
                    name=(
                        "Is Coursera accredited, and are Coursera certificates "
                        "recognized by employers?"
                    ),
                )
                assert question.get_attribute("aria-expanded") == "false"
                question.click()
                assert question.get_attribute("aria-expanded") == "true"
                answer_id = question.get_attribute("aria-controls")
                assert answer_id
                assert page.locator(f"#{answer_id}").is_visible()

                page.goto(base_url + "/browse/business", wait_until="networkidle")
                business_question = page.get_by_role(
                    "button",
                    name="What skills can I develop with business courses on Coursera?",
                )
                assert business_question.get_attribute("aria-expanded") == "false"
                business_question.click()
                assert business_question.get_attribute("aria-expanded") == "true"
                business_answer = page.locator(
                    '[role="region"][aria-labelledby="'
                    + business_question.get_attribute("id")
                    + '"]'
                )
                assert business_answer.is_visible()
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize(
    ("path", "landmark"),
    (
        ("/", ".source-home-shell"),
        ("/browse", ".source-browse-categories"),
        ("/search?query=deep%20learning", ".search-results-section"),
    ),
)
def test_login_preserves_the_invoking_public_document(
    path: str, landmark: str
) -> None:
    """Catch login navigation that discards the public page underneath it."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + path, wait_until="networkidle")
                before_url = page.url
                assert page.locator(landmark).is_visible()

                page.get_by_role("button", name="Log In").click()

                assert page.url == before_url
                assert page.locator(landmark).is_visible()
                assert page.get_by_role("dialog").is_visible()
        finally:
            context.close()
            browser.close()
