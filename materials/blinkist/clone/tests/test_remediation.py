import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("WEBSITEBENCH_TEST_MODE", "1")

from app import (  # noqa: E402 - enable the in-process test seam before import
    APP,
    LOCAL_SESSION_COOKIE,
    SESSION_COOKIE,
    test_challenge_code as challenge_code,
)


MEMBER_GET_ROUTES = (
    "/en/app/for-you",
    "/app/explore",
    "/search?q=Atomic+Habits",
    "/app/books/atomic-habits",
    "/app/library",
    "/en/app/library",
    "/app/daily",
    "/app/spaces",
    "/app/highlights",
    "/app/infographics",
    "/app/masterclasses",
    "/app/check",
    "/app/progress",
    "/app/history",
    "/settings/profile",
    "/settings/content",
    "/settings/email_optins",
    "/settings/external_services",
    "/settings/payment-history",
    "/en/nc/settings/invoices",
    "/subscribe",
    "/subscribe/review",
    "/subscribe/cancel",
    "/settings",
)


def register_member(test_client: TestClient, email: str) -> None:
    started = test_client.post(
        "/register",
        data={
            "email": email,
            "display_name": "Remediation Reader",
            "password": "Local-remediation-pass-2026",
            "terms": "on",
        },
        follow_redirects=False,
    )
    assert started.headers["location"] == "/verify"
    token = test_client.cookies.get(LOCAL_SESSION_COOKIE) or test_client.cookies.get(
        SESSION_COOKIE
    )
    assert token is not None
    code = challenge_code(token, purpose="registration")
    completed = test_client.post(
        "/verify",
        data={"code": code},
        follow_redirects=False,
    )
    assert completed.status_code == 303


@pytest.mark.parametrize("route", MEMBER_GET_ROUTES)
def test_anonymous_member_routes_redirect_to_login_with_safe_next(route: str) -> None:
    response = TestClient(APP).get(route, follow_redirects=False)

    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/login"
    assert parse_qs(location.query)["next"] == [route]


@pytest.mark.parametrize(
    "next_value",
    (
        "//evil.invalid/path",
        "https://evil.invalid/path",
        "/%5cevil.invalid/path",
        "/%255cevil.invalid/path",
        "/%25255cevil.invalid/path",
        "/%00evil",
    ),
)
def test_login_rejects_unsafe_next_values(next_value: str) -> None:
    page = TestClient(APP).get(f"/login?next={next_value}")

    assert page.status_code == 200
    assert "name='next' value='/en/app/for-you'" in page.text


def test_default_runtime_has_no_http_otp_endpoint() -> None:
    response = TestClient(APP).get("/api/local/outbox")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("route", "data"),
    (
        ("/app/books/atomic-habits/favorite", {}),
        ("/app/books/atomic-habits/progress", {"mode": "preview", "position": "35"}),
        ("/subscribe", {"scenario": "sandbox-approved"}),
    ),
)
def test_anonymous_member_writes_redirect_without_mutation(route: str, data: dict[str, str]) -> None:
    response = TestClient(APP).post(route, data=data, follow_redirects=False)

    assert response.status_code == 303
    assert urlsplit(response.headers["location"]).path == "/login"


def test_login_safe_next_round_trip_preserves_query() -> None:
    test_client = TestClient(APP)
    email = f"safe-next-{uuid4().hex}@example.invalid"
    register_member(test_client, email)
    test_client.post("/logout", follow_redirects=False)

    login = test_client.post(
        "/login",
        data={
            "email": email,
            "password": "Local-remediation-pass-2026",
            "next": "/search?q=Atomic+Habits",
        },
        follow_redirects=False,
    )

    assert login.status_code == 303
    assert login.headers["location"] == "/search?q=Atomic+Habits"


def test_logout_revokes_authority_and_returns_to_public_home() -> None:
    test_client = TestClient(APP)
    register_member(
        test_client, f"logout-{uuid4().hex}@example.invalid"
    )

    old_token = test_client.cookies.get(LOCAL_SESSION_COOKIE) or test_client.cookies.get(
        SESSION_COOKIE
    )
    logout = test_client.post("/logout", follow_redirects=False)
    revisit = test_client.get("/app/library", follow_redirects=False)
    assert old_token is not None
    test_client.cookies.set(LOCAL_SESSION_COOKIE, old_token)
    stale_revisit = test_client.get("/app/library", follow_redirects=False)

    assert logout.status_code == 303
    assert logout.headers["location"] == "/"
    assert revisit.status_code == 303
    assert urlsplit(revisit.headers["location"]).path == "/login"
    assert stale_revisit.status_code == 303
    assert urlsplit(stale_revisit.headers["location"]).path == "/login"


def test_known_and_unknown_recovery_have_same_public_http_response() -> None:
    known_client = TestClient(APP)
    known_email = f"known-recovery-{uuid4().hex}@example.invalid"
    register_member(known_client, known_email)
    known_client.post("/logout", follow_redirects=False)
    unknown_client = TestClient(APP)

    known = known_client.post(
        "/forgot-password", data={"email": known_email}, follow_redirects=False
    )
    unknown = unknown_client.post(
        "/forgot-password",
        data={"email": f"unknown-{uuid4().hex}@example.invalid"},
        follow_redirects=False,
    )

    assert (known.status_code, known.headers["location"], known.content) == (
        unknown.status_code,
        unknown.headers["location"],
        unknown.content,
    )


def test_diagnostic_session_is_loopback_explicit_and_token_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client = TestClient(APP, base_url="http://127.0.0.1")
    verifier_secret = "local-verifier-fixture-2026"
    monkeypatch.delenv("WEBSITEBENCH_DIAGNOSTIC_SESSION", raising=False)
    monkeypatch.delenv("WEBSITEBENCH_DIAGNOSTIC_SESSION_TOKEN", raising=False)
    assert test_client.post("/__websitebench/session").status_code == 404

    monkeypatch.setenv("WEBSITEBENCH_DIAGNOSTIC_SESSION", "1")
    monkeypatch.setenv("WEBSITEBENCH_DIAGNOSTIC_SESSION_TOKEN", verifier_secret)
    assert test_client.post("/__websitebench/session").status_code == 404
    opened = test_client.post(
        "/__websitebench/session",
        headers={"X-WebsiteBench-Session-Token": verifier_secret},
    )

    assert opened.status_code == 200
    assert opened.json() == {"status": "authenticated", "site_id": "blinkist"}
    assert test_client.get("/api/status").json()["authenticated"] is True


def test_authentication_errors_are_announced_without_echoing_credentials() -> None:
    response = TestClient(APP).post(
        "/login",
        data={
            "email": "missing-reader@example.invalid",
            "password": "Local-missing-pass-2026",
        },
    )

    assert response.status_code == 401
    assert "class='error' role='alert'" in response.text


def test_cross_site_post_is_rejected_and_csp_blocks_framing() -> None:
    test_client = TestClient(APP)
    cross_site = test_client.post(
        "/login",
        data={"email": "reader@example.invalid", "password": "Local-pass-2026"},
        headers={"Origin": "https://cross-site.example.invalid"},
    )
    page = test_client.get("/")

    assert cross_site.status_code == 403
    csp = page.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'none'" in csp


def test_public_drawer_traps_keyboard_focus_and_restores_opener() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    script = (Path(__file__).resolve().parents[1] / "static" / "site.js").read_text(
        encoding="utf-8"
    )
    document = TestClient(APP).get("/").text.replace(
        "<script src='/static/site.js' defer></script>", f"<script>{script}</script>"
    )

    with playwright.sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_content(document, wait_until="load")
        opener = page.locator("[data-drawer-open]")
        drawer = page.locator("[data-public-drawer]")

        assert drawer.get_attribute("aria-hidden") == "true"
        assert drawer.evaluate("element => element.inert") is True
        opener.focus()
        page.keyboard.press("Enter")
        assert drawer.get_attribute("aria-hidden") == "false"
        assert drawer.evaluate("element => element.inert") is False
        assert page.evaluate(
            "document.activeElement.matches('[data-drawer-close]')"
        )

        focusable_count = drawer.evaluate(
            """element => [...element.querySelectorAll(
              'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
            )].filter(item => item.getClientRects().length > 0 && (
              !item.closest('details:not([open])') || item.tagName === 'SUMMARY'
            )).length"""
        )
        for _ in range(focusable_count + 2):
            page.keyboard.press("Tab")
            assert drawer.evaluate("element => element.contains(document.activeElement)")

        page.locator("[data-drawer-close]").focus()
        page.keyboard.press("Shift+Tab")
        assert drawer.evaluate("element => element.contains(document.activeElement)")
        page.keyboard.press("Escape")
        assert drawer.get_attribute("aria-hidden") == "true"
        assert drawer.evaluate("element => element.inert") is True
        assert page.evaluate(
            "document.activeElement.matches('[data-drawer-open]')"
        )
        page.keyboard.press("Tab")
        assert not drawer.evaluate("element => element.contains(document.activeElement)")
        browser.close()
