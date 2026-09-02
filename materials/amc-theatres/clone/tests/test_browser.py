"""Real headless browser closure for the local AMC replica.

These tests never contact the source site. They exercise only the isolated
loopback clone and fail on any request that escapes that boundary.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect, sync_playwright


VIEWPORTS = [
    pytest.param({"width": 1440, "height": 900}, id="desktop"),
    pytest.param({"width": 390, "height": 844}, id="mobile"),
]


def new_page(browser, base: str, viewport: dict[str, int]):
    context = browser.new_context(viewport=viewport)
    escaped: list[str] = []
    page_errors: list[str] = []

    def inspect_request(request) -> None:
        parsed = urlparse(request.url)
        if parsed.scheme in {"http", "https"} and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            escaped.append(request.url)

    context.on("request", inspect_request)
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page._amc_base = base
    page._amc_escaped = escaped
    page._amc_errors = page_errors
    return context, page


def goto(page: Page, path: str, *, status: int = 200) -> None:
    response = page.goto(page._amc_base + path, wait_until="networkidle")
    assert response is not None
    assert response.status == status
    expect(page.locator("body")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def assert_clean(page: Page) -> None:
    assert page._amc_escaped == []
    assert page._amc_errors == []


def reset(page: Page) -> None:
    goto(page, "/")
    payload = page.evaluate(
        """async () => {
          const response = await fetch('/api/reset', {method: 'POST'});
          return {status: response.status, body: await response.json()};
        }"""
    )
    assert payload["status"] == 200
    assert payload["body"]["auth_state"] == "anonymous"
    goto(page, "/")


def local_outbox_code(page: Page, purpose: str) -> str:
    payload = page.evaluate(
        f"""async () => await (await fetch('/api/local-outbox/{purpose}')).json()"""
    )
    code = payload["message"]["verification_code"]
    assert re.fullmatch(r"\d{6}", code)
    return code


def click_reload(page: Page, selector: str) -> None:
    with page.expect_navigation(wait_until="networkidle"):
        page.locator(selector).click()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_public_shell_search_collections_details_and_filters(clone_server, viewport):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context, page = new_page(browser, clone_server.base, viewport)
        try:
            reset(page)

            # Home shell: dismissible offer, carousel, tabs, search, and mobile nav.
            page.locator(".alert-close").click()
            expect(page.locator(".alert-strip")).to_be_hidden()
            page.locator("[data-slide='next']").click()
            expect(page.locator(".carousel-controls .dot.on")).to_have_attribute(
                "aria-pressed", "true"
            )
            page.get_by_role("tab", name="Coming Soon").click()
            expect(page.get_by_role("tab", name="Coming Soon")).to_have_attribute(
                "aria-selected", "true"
            )
            if viewport["width"] <= 560:
                page.locator("[data-menu]").click()
                expect(page.locator("header .nav")).to_have_class(re.compile("open"))
                page.locator("[data-open-search]").click()
                expect(page.locator("#search-panel")).to_be_visible()
                page.locator("#global-q").fill("Odyssey")
                page.locator("#search-panel button").click()
            else:
                page.locator("#header-q").fill("Odyssey")
                page.locator(".header-search button").click()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name=re.compile("Results for"))).to_be_visible()
            expect(page.get_by_text("The Odyssey", exact=True).first).to_be_visible()

            goto(page, "/search?q=not-a-real-amc-item")
            expect(page.get_by_text("No matching movies.")).to_be_visible()
            expect(page.get_by_text("No matching theatres.")).to_be_visible()

            # Six reachable first-party feature pages.
            for path in [
                "/food-and-drink",
                "/group-events",
                "/merchandise",
                "/gift-cards",
                "/offers",
                "/on-demand",
            ]:
                goto(page, path)
                expect(page.locator("main h1")).to_be_visible()

            # Collection page one, filters/sort/empty, page two, and two details.
            goto(page, "/movies")
            expect(page.locator(".movies-page-grid article")).to_have_count(23)
            page.locator(".featured-select").click()
            expect(page.locator("#featured-menu")).to_be_visible()
            page.locator("#featured-menu a", has_text="A-Z").click()
            page.wait_for_load_state("networkidle")
            assert "sort=A-Z" in page.url
            goto(page, "/movies?q=no-such-movie")
            expect(page.get_by_role("heading", name="No movies found")).to_be_visible()
            goto(page, "/movies?movie-list=coming-soon")
            expect(page.locator(".movies-page-grid article")).not_to_have_count(0)
            goto(page, "/movies/insidious-out-of-the-further")
            expect(page.get_by_role("heading", name="Insidious: Out of the Further")).to_be_visible()
            page.locator("[data-favorite]").click()
            expect(page.locator("[data-favorite]")).to_have_attribute("aria-pressed", "true")
            page.reload(wait_until="networkidle")
            expect(page.locator("[data-favorite]")).to_have_attribute("aria-pressed", "true")
            goto(page, "/movies/the-odyssey")
            expect(page.get_by_role("heading", name="The Odyssey")).to_be_visible()

            # Directory tabs/search/location, market redirect, theatre detail and auth guard.
            goto(page, "/movie-theatres")
            page.get_by_role("tab", name="States").click()
            expect(page.locator("[data-directory-panel='states']")).to_be_visible()
            page.get_by_role("tab", name="Markets").click()
            page.locator("[data-current-location]").click()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_text(re.compile("theatres found"))).to_be_visible()
            goto(page, "/movie-theatres/new-york-city")
            assert "/movie-theatres?q=" in page.url
            goto(page, "/movie-theatres/ny/amc-empire-25")
            expect(page.get_by_role("heading", name="AMC Empire 25")).to_be_visible()
            page.locator("[data-favorite-theatre]").click()
            page.wait_for_load_state("networkidle")
            assert "/login" in page.url

            # Showtime picker and all four navigable filters.
            goto(page, "/showtimes")
            expect(page.get_by_role("dialog", name="Find a Theatre")).to_be_visible()
            page.get_by_role("link", name="Use Current Location").click()
            page.wait_for_load_state("networkidle")
            assert "theatre=amc-empire-25" in page.url
            expect(page.locator(".showtimes-filters a")).to_have_count(4)
            page.locator(".showtimes-filters a").nth(1).click()
            page.wait_for_load_state("networkidle")
            assert "date=tomorrow" in page.url
            goto(page, "/showtimes?theatre=amc-empire-25&format=premium")
            expect(page.get_by_text("Premium Offerings")).to_be_visible()

            # Help search and disclosure controls.
            goto(page, "/help")
            page.locator("#help-q").fill("refund")
            page.locator(".help-search").press("Enter")
            page.wait_for_load_state("networkidle")
            assert "q=refund" in page.url
            page.locator("details").nth(1).locator("summary").click()
            expect(page.locator("details").nth(1)).to_have_attribute("open", "")
            assert_clean(page)
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_auth_checkout_order_management_reset_restart_and_isolation(clone_server, viewport):
    email = f"amc-{viewport['width']}-{uuid.uuid4().hex[:8]}@example.test"
    original_password = "SyntheticPass123!"
    new_password = "SyntheticPass456!"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context, page = new_page(browser, clone_server.base, viewport)
        try:
            reset(page)

            # Registration, local verification, account preference persistence.
            goto(page, "/sign-up?plan=insider")
            page.locator("#signup-form input[name='name']").fill("Synthetic AMC Guest")
            page.locator("#signup-form input[name='email']").fill(email)
            page.locator("#signup-form input[name='password']").fill(original_password)
            page.locator("#signup-form button").click()
            page.wait_for_url(re.compile(r".*/verify-account$"))
            page.locator("#verify-signup-form input[name='code']").fill(
                local_outbox_code(page, "registration")
            )
            page.locator("#verify-signup-form button").click()
            page.wait_for_url(re.compile(r".*/account$"))
            page.locator("#preferences-form select[name='preferred_theatre']").select_option(
                "amc-century-city-15"
            )
            page.locator("#preferences-form input[name='notifications_enabled']").check()
            page.locator("#preferences-form select[name='privacy_mode']").select_option("minimal")
            page.locator("#preferences-form button").click()
            expect(page.locator("#preferences-form .form-message")).to_have_text(
                "Preferences saved locally."
            )
            page.reload(wait_until="networkidle")
            expect(page.locator("#preferences-form select[name='preferred_theatre']")).to_have_value(
                "amc-century-city-15"
            )

            # Movie and theatre favorites now bind to the authenticated owner.
            goto(page, "/movies/insidious-out-of-the-further")
            if page.locator("[data-favorite]").get_attribute("aria-pressed") != "true":
                page.locator("[data-favorite]").click()
            goto(page, "/movie-theatres/ny/amc-empire-25")
            page.locator("[data-favorite-theatre]").click()
            expect(page.locator("[data-favorite-theatre]")).to_have_attribute("aria-pressed", "true")

            # Checkout review controls and all payment sandbox branches.
            goto(page, "/checkout/insidious-out-of-the-further?theatre=amc-empire-25&time=7%3A00%20PM")
            page.locator("[data-seat='A1']").click()
            page.locator("[data-seat='A2']").click()
            page.locator("#ticket-type").select_option("Senior")
            page.locator("#format-name").select_option("IMAX")
            page.locator("#attendee-name").fill("Synthetic Attendee")
            expect(page.locator("#ticket-count")).to_have_text("2")
            expect(page.locator("#review-format")).to_have_text("IMAX")
            page.locator("#scenario").select_option("sandbox-declined")
            page.locator("#place-order").click()
            expect(page.locator("#toast")).to_contain_text("declined")
            page.locator("#scenario").select_option("sandbox-retry")
            page.locator("#place-order").click()
            expect(page.locator("#toast")).to_contain_text("retry")
            page.locator("#scenario").select_option("sandbox-approved")
            page.locator("#place-order").click()
            order_heading = page.locator(".checkout-grid .empty h1")
            expect(order_heading).to_have_text(re.compile(r"AMC-[A-F0-9]{12}"))
            order_id = order_heading.inner_text()
            page.get_by_role("link", name="View My AMC").click()
            page.wait_for_url(re.compile(r".*/account$"))
            page.get_by_role("link", name="Manage ticket").click()
            page.wait_for_url(re.compile(r".*/account/orders/AMC-"))

            # Book-again route is real and retains movie/theatre/time semantics.
            reorder_href = page.locator("[data-order-reorder]").get_attribute("href")
            assert reorder_href and "/checkout/insidious-out-of-the-further" in reorder_href
            page.locator("[data-order-reorder]").click()
            page.wait_for_url(re.compile(r".*/checkout/insidious-out-of-the-further"))
            expect(page.get_by_role("heading", name="Choose your seats")).to_be_visible()
            goto(page, f"/account/orders/{order_id}")

            # Every management control persists across its page reload.
            page.locator("[data-manage-showtime]").select_option("8:45 PM")
            click_reload(page, "[data-order-action='reschedule']")
            expect(page.locator(".page-head")).to_contain_text("rescheduled")
            click_reload(page, "[data-order-action='reminder']")
            expect(page.get_by_text("On", exact=True)).to_be_visible()
            page.locator("[data-manage-concession][value='popcorn']").check()
            page.locator("[data-manage-concession][value='soft-drink']").check()
            click_reload(page, "[data-order-action='concessions']")
            expect(page.get_by_text("popcorn, soft-drink", exact=True)).to_be_visible()
            page.locator("[data-manage-notes]").fill("Synthetic aisle assistance")
            click_reload(page, "[data-order-action='notes']")
            expect(page.locator("dd", has_text="Synthetic aisle assistance")).to_be_visible()
            page.locator("[data-manage-promo]").fill("AMCLOCAL10")
            click_reload(page, "[data-order-action='promo']")
            expect(page.locator("dd", has_text="AMCLOCAL10")).to_be_visible()
            page.locator("[data-manage-recipient]").fill("friend@example.test")
            click_reload(page, "[data-order-action='share']")
            expect(page.locator("dd", has_text="friend@example.test")).to_be_visible()
            page.locator("[data-review-rating]").select_option("4")
            page.locator("[data-review-visibility]").select_option("public")
            page.locator("[data-review-body]").fill("Synthetic local review")
            click_reload(page, "[data-review-save]")
            expect(page.get_by_text("4 stars · public", exact=True)).to_be_visible()

            # Tracking is owner-scoped; signed-out and a different account cannot read it.
            page.get_by_role("link", name="Track order").click()
            page.wait_for_url(re.compile(r".*/track-order\?order_id="))
            expect(page.locator(".track-result")).to_contain_text(order_id)
            goto(page, f"/account/orders/{order_id}")
            click_reload(page, "[data-order-action='cancel']")
            expect(page.locator(".page-head")).to_contain_text("cancelled")
            click_reload(page, "[data-order-action='refund']")
            expect(page.locator(".page-head")).to_contain_text("refunded")
            page.locator("#logout").click() if page.locator("#logout").count() else goto(page, "/account")
            if "/account" in page.url:
                page.locator("#logout").click()
            page.wait_for_url(re.compile(r".*/$"))
            goto(page, f"/track-order?order_id={order_id}")
            expect(page.get_by_role("heading", name="Sign in to track this order")).to_be_visible()
            goto(page, "/login")
            page.locator("#login-form input[name='email']").fill("guest@example.com")
            page.locator("#login-form input[name='password']").fill("demo12345")
            page.locator("#login-form input[name='captcha']").check()
            page.locator("#login-form button").click()
            page.wait_for_url(re.compile(r".*/account$"))
            goto(page, f"/track-order?order_id={order_id}")
            expect(page.get_by_role("heading", name="Order not found")).to_be_visible()
            goto(page, "/account")
            page.locator("#logout").click()
            page.wait_for_url(re.compile(r".*/$"))

            # Password recovery, old-password rejection, new login, and data persistence.
            goto(page, "/password-reset")
            page.locator("#reset-form input[name='email']").fill(email)
            page.locator("#reset-form button").click()
            page.wait_for_url(re.compile(r".*/password-reset/verify$"))
            page.locator("#complete-reset-form input[name='code']").fill(
                local_outbox_code(page, "password-reset")
            )
            page.locator("#complete-reset-form input[name='new_password']").fill(new_password)
            page.locator("#complete-reset-form button").click()
            page.wait_for_url(re.compile(r".*/account$"))
            expect(page.get_by_text(order_id[-8:], exact=False)).to_be_visible()
            page.locator("#logout").click()
            page.wait_for_url(re.compile(r".*/$"))
            goto(page, "/login")
            page.locator("#login-form input[name='email']").fill(email)
            page.locator("#login-form input[name='password']").fill(original_password)
            page.locator("#login-form input[name='captcha']").check()
            page.locator("#login-form button").click()
            expect(page.locator("#login-form .form-message")).to_have_text(
                "Email or password is incorrect."
            )
            page.locator("#login-form input[name='password']").fill(new_password)
            page.locator("#login-form input[name='captcha']").check()
            page.locator("#login-form button").click()
            page.wait_for_url(re.compile(r".*/account$"))
            expect(page.get_by_text(order_id[-8:], exact=False)).to_be_visible()
            assert_clean(page)
        finally:
            context.close()
            browser.close()

        # A fresh browser after a real process restart must recover persisted ownership.
        clone_server.stop()
        clone_server.start()
        browser = playwright.chromium.launch(headless=True)
        context, page = new_page(browser, clone_server.base, viewport)
        try:
            goto(page, "/login")
            page.locator("#login-form input[name='email']").fill(email)
            page.locator("#login-form input[name='password']").fill(new_password)
            page.locator("#login-form input[name='captcha']").check()
            page.locator("#login-form button").click()
            page.wait_for_url(re.compile(r".*/account$"))
            expect(page.get_by_text(order_id[-8:], exact=False)).to_be_visible()
            expect(page.locator("#preferences-form select[name='preferred_theatre']")).to_have_value(
                "amc-empire-25"
            )
            expect(page.locator("#preferences-form select[name='privacy_mode']")).to_have_value(
                "minimal"
            )
            goto(page, f"/track-order?order_id={order_id}")
            expect(page.locator(".track-result")).to_contain_text("refunded")
            assert_clean(page)
        finally:
            context.close()
            browser.close()
