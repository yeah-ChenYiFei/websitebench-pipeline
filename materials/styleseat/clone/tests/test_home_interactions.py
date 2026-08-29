"""The StyleSeat repair is deliberately limited to the captured homepage."""

from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from typing import Iterator
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from playwright.sync_api import BrowserContext, Page, expect, sync_playwright
import pytest
import uvicorn

from app import app


client = TestClient(app)
SCRIPT = Path(__file__).parents[1] / "static" / "home-actions.js"


@pytest.fixture(scope="module")
def live_browser() -> Iterator[tuple[BrowserContext, str]]:
    """Serve the real clone over local TLS at the frozen desktop viewport."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="styleseat-test-tls-") as tls_dir:
        cert = Path(tls_dir) / "cert.pem"
        key = Path(tls_dir) / "key.pem"
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "1",
                "-subj", "/CN=127.0.0.1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                log_level="warning",
                access_log=False,
                ssl_keyfile=str(key),
                ssl_certfile=str(cert),
            )
        )
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [listener]},
            daemon=True,
        )
        thread.start()

        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
            raise RuntimeError("StyleSeat test server did not start")

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900}, ignore_https_errors=True
                )
                try:
                    yield context, f"https://127.0.0.1:{port}"
                finally:
                    context.close()
                    browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            try:
                listener.close()
            except OSError:
                pass


@pytest.fixture
def home_page(live_browser: tuple[BrowserContext, str]) -> Iterator[tuple[Page, str]]:
    context, base_url = live_browser
    page = context.new_page()
    page.goto(f"{base_url}/m/")
    try:
        yield page, base_url
    finally:
        page.close()


def test_home_loads_the_local_homepage_controller() -> None:
    response = client.get("/m/")
    assert response.status_code == 200
    assert '<script src="/static/home-actions.js" defer></script>' in response.text


def test_controller_is_explicitly_homepage_only() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")
    assert 'return location.pathname.replace(/\\/+$/, "") === "/m"' in javascript
    assert "if (!onHome()) return" in javascript
    assert "bindSearchPageControls" not in javascript
    assert "alignCapturedCityList" not in javascript
    assert "alignCapturedProviderProfile" not in javascript


def test_homepage_menu_search_tiles_and_ctas_have_local_terminals() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        'data-testid="sidebar-toggle"',
        'data-testid^="search-tile-"]:not([data-testid="search-tile-text"])',
        'data-testid="search"',
        'data-testid="header-link-login-button"',
        'data-testid="header-link-setup-my-business"',
        'data-testid="home-hero-set-up-my-business-button"',
        'data-testid="accordion-section"',
    ):
        assert marker in javascript
    assert 'navigate("/m/search"' in javascript
    assert 'params.set("service", slug)' in javascript
    assert 'bindRoute(tile, "/m/search?" + params.toString()' in javascript
    assert "For Professionals" in javascript
    assert "For Clients" in javascript


def test_search_destinations_disclose_the_uncaptured_frontier() -> None:
    for route in (
        "/m/search?q=braids&location=Dallas",
        "/m/search?service=braids",
    ):
        response = client.get(route)
        assert response.status_code == 200, route
        assert "Beyond captured scope" in response.text, route
        assert 'data-testid="searchResultsList"' not in response.text, route


def test_captured_cta_destinations_are_served_locally() -> None:
    for route in (
        "/m/login",
        "/m/pro-signup",
        "/join/run-your-business",
        "/join/grow-your-business",
        "/join/manage-your-business",
        "/join/elevate-your-client-experience",
    ):
        response = client.get(route, follow_redirects=True)
        assert response.status_code == 200, route
        assert "Beyond captured scope" not in response.text, route


def test_hamburger_menu_supports_pointer_keyboard_focus_and_escape(
    home_page: tuple[Page, str],
) -> None:
    page, _base_url = home_page
    trigger = page.locator('[data-testid="sidebar-toggle"]')
    layer = page.locator("#wb-home-drawer-layer")
    close = layer.get_by_role("button", name="Close menu")

    expect(trigger).to_have_attribute("role", "button")
    expect(trigger).to_have_attribute("aria-controls", "wb-home-drawer-layer")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    trigger.press("Enter")
    expect(layer).to_be_visible()
    expect(trigger).to_have_attribute("aria-expanded", "true")
    expect(close).to_be_focused()

    page.keyboard.press("Shift+Tab")
    expect(layer.locator('a[href="/m/search"]')).to_be_focused()
    page.keyboard.press("Tab")
    expect(close).to_be_focused()

    page.keyboard.press("Escape")
    expect(layer).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(trigger).to_be_focused()

    trigger.click()
    expect(layer).to_be_visible()
    close.click()
    expect(layer).to_be_hidden()
    expect(trigger).to_be_focused()

    trigger.click()
    layer.locator('a[href="/m/search"]').click()
    page.wait_for_url("**/m/search")
    expect(page.get_by_role("heading", name="Beyond captured scope")).to_be_visible()


def test_search_entry_preserves_criteria_without_inventing_results(
    home_page: tuple[Page, str],
) -> None:
    page, _base_url = home_page
    page.locator('[data-testid="query-input"]').fill("silk press")
    page.locator('[data-testid="location-input"]').fill("Dallas, TX")
    page.locator('[data-testid="search"]').press("Enter")
    page.wait_for_url("**/m/search?*")

    destination = urlparse(page.url)
    assert destination.path == "/m/search"
    assert parse_qs(destination.query) == {
        "q": ["silk press"],
        "location": ["Dallas, TX"],
    }
    expect(page.get_by_role("heading", name="Beyond captured scope")).to_be_visible()


def test_login_and_logout_keep_the_generated_secure_cookie(
    home_page: tuple[Page, str],
) -> None:
    page, base_url = home_page
    status = page.evaluate(
        """async () => (await fetch('/accounts/ajax-login/', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'email=4280322688%40pu.jyr&password=Fixture-Client-2026%21',
        })).status"""
    )
    assert status == 200
    cookies = page.context.cookies()
    session = next(
        cookie
        for cookie in cookies
        if cookie["name"] == "__Host-websitebench-styleseat-session"
    )
    assert session["secure"] is True
    assert session["httpOnly"] is True
    assert session["sameSite"] == "Lax"
    page.goto(f"{base_url}/m/client-appointments")
    expect(page.locator('[data-testid="client-my-settings-menu"]')).to_be_visible()

    status = page.evaluate(
        """async () => (await fetch('/accounts/ajax-logout/', {method: 'POST'})).status"""
    )
    assert status == 200
    page.goto(f"{base_url}/m/client-appointments")
    expect(page.locator('[data-testid="header-link-login-button"]')).to_be_visible()


def test_service_cards_are_single_keyboard_controls_with_honest_destinations(
    home_page: tuple[Page, str],
) -> None:
    page, _base_url = home_page
    tile = page.locator('[data-testid="search-tile-braids"]')
    inner_labels = page.locator('[data-testid="search-tile-text"]')

    expect(tile).to_have_attribute("role", "button")
    expect(tile).to_have_attribute("tabindex", "0")
    assert page.locator(
        '[data-testid^="search-tile-"][data-clone-action-bound="1"]'
    ).count() == 12
    assert inner_labels.count() == 12
    assert inner_labels.first.get_attribute("data-clone-action-bound") is None
    assert inner_labels.first.get_attribute("tabindex") is None

    tile.press(" ")
    page.wait_for_url("**/m/search?*")
    destination = urlparse(page.url)
    assert destination.path == "/m/search"
    assert parse_qs(destination.query) == {"service": ["braids"]}
    expect(page.get_by_role("heading", name="Beyond captured scope")).to_be_visible()


@pytest.mark.parametrize(
    ("selector", "destination", "keyboard"),
    (
        ('[data-testid="header-link-login-button"]', "/m/login", False),
        ('[data-testid="header-link-setup-my-business"]', "/m/pro-signup", False),
        ('[data-testid="home-hero-set-up-my-business-button"]', "/m/pro-signup", True),
        ('button[aria-label="Learn more about setting up your business"]', "/join/run-your-business", False),
        ('button[aria-label="Learn more about growing your business"]', "/join/grow-your-business", False),
        ('button[aria-label="Learn more about managing your business"]', "/join/manage-your-business", False),
        ('button[aria-label="Learn more about client experience"]', "/join/elevate-your-client-experience", False),
    ),
)
def test_home_ctas_reach_captured_pages(
    home_page: tuple[Page, str],
    selector: str,
    destination: str,
    keyboard: bool,
) -> None:
    page, _base_url = home_page
    control = page.locator(selector)
    if keyboard:
        control.press("Enter")
    else:
        control.click()
    page.wait_for_url(f"**{destination}")

    assert urlparse(page.url).path == destination
    expect(page.get_by_role("heading", name="Beyond captured scope")).to_have_count(0)


def test_accordion_supports_pointer_enter_space_and_single_open_panel(
    home_page: tuple[Page, str],
) -> None:
    page, _base_url = home_page
    first = page.locator('[data-testid="accordion-section"]').nth(0)
    second = page.locator('[data-testid="accordion-section"]').nth(1)
    first_trigger = first.locator('[role="button"]').first
    second_trigger = second.locator('[role="button"]').first
    first_panel = first.locator('[role="region"]')
    second_panel = second.locator('[role="region"]')

    expect(first_trigger).to_have_attribute("aria-controls", first_panel.get_attribute("id"))
    expect(first_trigger).to_have_attribute("aria-expanded", "false")
    expect(first_panel).to_have_attribute("aria-hidden", "true")

    first_trigger.press("Enter")
    expect(first_trigger).to_have_attribute("aria-expanded", "true")
    expect(first_panel).to_have_attribute("aria-hidden", "false")

    first_trigger.press(" ")
    expect(first_trigger).to_have_attribute("aria-expanded", "false")
    expect(first_panel).to_have_attribute("aria-hidden", "true")

    first_trigger.click()
    second_trigger.press("Enter")
    expect(first_trigger).to_have_attribute("aria-expanded", "false")
    expect(first_panel).to_have_attribute("aria-hidden", "true")
    expect(second_trigger).to_have_attribute("aria-expanded", "true")
    expect(second_panel).to_have_attribute("aria-hidden", "false")
