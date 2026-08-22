from __future__ import annotations

import pytest

from browser_settle import settle_page
from test_desktop_visual import VIEWPORT, _clone_server


def _assert_settled(page) -> None:
    result = settle_page(page, max_rounds=12, timeout_ms=12_000, pause_ms=50)
    assert result["complete"] is True, result
    assert result["failed_images"] == []
    assert result["image_count"] == result["loaded_image_count"]
    assert page.evaluate("() => document.documentElement.scrollHeight") == result[
        "scroll_height"
    ]


def test_auth_and_recovery_pages_settle_without_remote_assets() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                for path in ("/login", "/signup", "/account-recovery"):
                    page = context.new_page()
                    failed: list[str] = []
                    page.on("requestfailed", lambda request: failed.append(request.url))
                    page.goto(base_url + path, wait_until="networkidle")
                    _assert_settled(page)
                    assert failed == []
                    assert page.url == base_url + path
                    page.close()
        finally:
            context.close()
            browser.close()


def test_seeded_learner_and_checkout_pages_settle_without_remote_assets() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                failed: list[str] = []
                page.on("requestfailed", lambda request: failed.append(request.url))
                page.goto(base_url + "/login", wait_until="networkidle")
                page.locator('input[name="email"]').fill("empty@coursera.test")
                page.locator('[data-login-continue]').click()
                page.wait_for_load_state("networkidle")
                page.locator('input[name="password"]').fill("Empty-Learner-33")
                page.locator('button[type="submit"]').last.click()
                page.wait_for_load_state("networkidle")
                assert page.url == base_url + "/my-learning"
                _assert_settled(page)
                assert "My Learning" in page.locator("body").inner_text()

                page.goto(base_url + "/checkout/deep-learning", wait_until="networkidle")
                _assert_settled(page)
                assert "Start free trial" in page.locator("body").inner_text()
                assert failed == []
        finally:
            context.close()
            browser.close()


def test_my_learning_uses_source_font_width_and_footer_layout() -> None:
    """Catch fallback glyphs, the narrow 1120px shell, and the global footer grid leak."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1692, "height": 979}, device_scale_factor=1
        )
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/login", wait_until="networkidle")
                page.locator('form[action="/auth/local-learner"] button').click()
                page.wait_for_load_state("networkidle")

                geometry = page.evaluate(
                    """() => {
                      const learning = document.querySelector('.learning-page').getBoundingClientRect();
                      const footer = getComputedStyle(document.querySelector('.wb-footer'));
                      const grid = getComputedStyle(document.querySelector('.wb-footer-grid'));
                      const header = document.querySelector('.wb-header .wb-shell').getBoundingClientRect();
                      return {
                        bodyFont: getComputedStyle(document.body).fontFamily,
                        audienceDisplay: getComputedStyle(document.querySelector('.wb-audience-bar')).display,
                        learning: [learning.x, learning.width],
                        header: [header.x, header.width],
                        sparkleDisplay: getComputedStyle(document.querySelector('.wb-ai-sparkle')).display,
                        footerDisplay: footer.display,
                        footerColumns: grid.gridTemplateColumns.split(' ').length,
                      };
                    }"""
                )

                assert geometry["bodyFont"].startswith('"Source Sans 3"')
                assert geometry["audienceDisplay"] == "none"
                assert geometry["learning"] == [174, 1344]
                assert geometry["header"] == [174, 1344]
                assert geometry["sparkleDisplay"] == "none"
                assert geometry["footerDisplay"] == "block"
                assert geometry["footerColumns"] == 4
                assert page.locator('.wb-search button svg').count() == 1
                assert page.locator('.wb-notification-link svg').count() == 1
        finally:
            context.close()
            browser.close()
