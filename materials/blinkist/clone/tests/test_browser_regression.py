from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright


CLONE_ROOT = Path(__file__).resolve().parents[1]
VIEWPORTS = (
    (1440, 900),
    (1024, 768),
    (768, 1024),
    (390, 844),
)
ROUTES = (
    "/en/app/for-you",
    "/app/explore",
    "/search?q=Atomic+Habits",
    "/search?q=NoSuchSyntheticTitle",
    "/app/books/atomic-habits",
    "/app/books/atomic-habits-en",
    "/app/library",
    "/register",
    "/verify",
    "/login",
    "/forgot-password",
    "/reset-password",
    "/subscribe",
    "/subscribe/review",
    "/settings",
)


def _unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def browser_server() -> Iterator[tuple[str, str]]:
    port = _unused_port()
    base_url = f"http://127.0.0.1:{port}"
    verifier_token = "local-browser-matrix-fixture-2026"
    environment = {
        **os.environ,
        "WEBSITEBENCH_TEST_MODE": "1",
        "WEBSITEBENCH_DIAGNOSTIC_SESSION": "1",
        "WEBSITEBENCH_DIAGNOSTIC_SESSION_TOKEN": verifier_token,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:APP",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=CLONE_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Blinkist browser fixture exited before becoming ready")
            try:
                with urlopen(base_url + "/healthz", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("Blinkist browser fixture did not become ready")
        yield base_url, verifier_token
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_four_width_browser_matrix_has_no_runtime_or_layout_regressions(
    browser_server: tuple[str, str],
) -> None:
    base_url, verifier_token = browser_server
    base_origin = base_url.rstrip("/")
    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(headless=True)
        for width, height in VIEWPORTS:
            context = browser.new_context(viewport={"width": width, "height": height})
            authenticated = context.request.post(
                base_url + "/__websitebench/session",
                headers={"X-WebsiteBench-Session-Token": verifier_token},
            )
            assert authenticated.status == 200
            page = context.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            failed_requests: list[str] = []
            external_requests: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("requestfailed", lambda request: failed_requests.append(request.url))
            page.on(
                "request",
                lambda request: external_requests.append(request.url)
                if not (
                    request.url.startswith(base_origin + "/")
                    or request.url.startswith("data:")
                )
                else None,
            )
            for route in ROUTES:
                console_errors.clear()
                page_errors.clear()
                failed_requests.clear()
                external_requests.clear()
                response = page.goto(base_url + route, wait_until="networkidle")

                assert response is not None and response.status < 400, route
                assert page.title().strip(), route
                assert page.locator("h1").count() == 1, route
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                ), f"horizontal overflow at {width}px on {route}"
                assert not console_errors, (route, console_errors)
                assert not page_errors, (route, page_errors)
                assert not failed_requests, (route, failed_requests)
                assert not external_requests, (route, external_requests)

                if width == 390:
                    undersized = page.locator(
                        "a[href]:visible, button:visible, input:not([type=hidden]):visible, "
                        "select:visible, summary:visible"
                    ).evaluate_all(
                        "elements => elements.filter(element => {"
                        "const target = element.closest('label') || element;"
                        "const box = target.getBoundingClientRect();"
                        "return box.width < 44 || box.height < 44"
                        "}).map(element => element.outerHTML.slice(0, 100))"
                    )
                    assert not undersized, (route, undersized)
            context.close()
        browser.close()
