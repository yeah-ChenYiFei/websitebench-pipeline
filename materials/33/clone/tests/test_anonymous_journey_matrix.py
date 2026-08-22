"""Anonymous route and boundary coverage for the frozen Coursera journeys."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import app
from test_desktop_visual import _clone_server


SITE_ROOT = Path(__file__).resolve().parents[2]
CURRENT_PHASE_PATH = SITE_ROOT / "scope" / "current-accessible-fullscreen-phase.json"
VIEWPORT = {"width": 1692, "height": 979}

PUBLIC_STATES = (
    ("/", "New and popular", "/browse"),
    ("/browse", "Explore Categories", "/browse/business"),
    ("/browse/business", "Business", "/browse"),
    ("/search?q=Deep+Learning", "All Results", "/professional-certificates/google-ai"),
    (
        "/search?q=zzzz-no-match-websitebench",
        "No results for zzzz-no-match-websitebench",
        "/browse",
    ),
    (
        "/specializations/deep-learning",
        "Deep Learning Specialization",
        "/browse",
    ),
    (
        "/learn/neural-networks-deep-learning",
        "Neural Networks and Deep Learning",
        "/specializations/deep-learning",
    ),
    ("/login", "Log in or create account", "/help"),
    ("/signup", "Log in or create account", "/help"),
    ("/account-recovery", "Reset your Coursera password", "/login"),
    ("/help", "Troubleshooting login and account issues", "/browse"),
    ("/about/contact", "Contact Us", "/help"),
)


def _assert_local_presentation(html: str) -> None:
    references = re.findall(r'\b(action|href|src)="([^"]+)"', html)
    assert references
    assert all(
        not reference.startswith(("http://", "https://", "//"))
        and (not reference.startswith("data:") or attribute == "src")
        for attribute, reference in references
    )


def test_anonymous_public_route_matrix_has_canonical_local_recovery() -> None:
    with TestClient(app) as client:
        for requested, landmark, recovery_href in PUBLIC_STATES:
            response = client.get(requested)
            requested_url = urlsplit(requested)
            actual_url = urlsplit(str(response.url))

            assert response.status_code == 200, requested
            assert response.history == [], requested
            assert actual_url.path == requested_url.path, requested
            assert parse_qs(actual_url.query) == parse_qs(requested_url.query), requested
            assert landmark in response.text, requested
            assert '<html lang="en"' in response.text, requested
            assert f'href="{recovery_href}"' in response.text, requested
            _assert_local_presentation(response.text)


def test_home_login_control_opens_a_same_document_identity_dialog() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")
                original_url = page.url

                page.locator("[data-login-open]").first.click()

                dialog = page.locator("[data-login-dialog]")
                assert page.url == original_url
                assert dialog.is_visible()
                assert dialog.locator('input[name="email"]').is_visible()
                assert dialog.locator('a[href="/auth/provider/google"]').is_visible()
                assert dialog.locator('a[href="/auth/provider/apple"]').is_visible()
                assert dialog.locator('a[href="/terms"]').first.is_visible()
                assert dialog.locator('a[href="/privacy"]').first.is_visible()
        finally:
            context.close()
            browser.close()


@pytest.mark.parametrize(
    ("path", "next_path"),
    (
        ("/learn/neural-networks-deep-learning", "/learn/neural-networks-deep-learning"),
        ("/specializations/deep-learning", "/checkout/deep-learning"),
    ),
)
def test_course_enrollment_cta_opens_login_over_the_invoking_page(
    path: str, next_path: str
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + path, wait_until="networkidle")
                original_url = page.url
                page.locator("[data-enrollment-login-open]").click()

                assert page.url == original_url
                dialog = page.locator("[data-login-dialog]")
                assert dialog.is_visible()
                assert dialog.locator(
                    f'input[name="next"][value="{next_path}"]'
                ).count() == 3
        finally:
            context.close()
            browser.close()


def test_auth_and_recovery_entries_expose_guidance_without_submission() -> None:
    with TestClient(app) as client:
        login = client.get("/login").text
        signup = client.get("/signup").text
        recovery = client.get("/account-recovery").text

    assert 'name="email"' in login
    assert 'href="/auth/provider/google"' in login
    assert 'href="/auth/provider/facebook"' in login
    assert 'href="/auth/provider/apple"' in login
    assert 'href="/terms"' in login
    assert 'href="/privacy"' in login
    assert 'href="/help"' in login

    assert 'data-login-dialog' in signup
    assert 'data-open-on-load="true"' in signup
    assert 'name="email"' in signup
    assert 'name="full_name"' not in signup
    assert 'name="password"' not in signup
    assert 'href="/terms"' in signup
    assert 'href="/privacy"' in signup
    assert 'href="/help"' in signup

    assert 'name="address"' in recovery
    assert "No reset message is sent" in recovery
    assert "verification guidance" in recovery
    assert 'href="/login"' in recovery


def test_anonymous_recovery_enrollment_and_preview_boundaries_remain_non_mutating() -> None:
    with TestClient(app) as client:
        no_results = client.get("/search?q=zzzz-no-match-websitebench")
        missing = client.get("/websitebench-anonymous-missing-route")
        specialization = client.get("/specializations/deep-learning")
        enrollment_prompt = client.get("/login?next=/checkout/deep-learning")
        course = client.get("/learn/neural-networks-deep-learning")
        preview = client.get(
            "/learn/neural-networks-deep-learning/lesson/lesson-neural-intro"
        )

    assert no_results.status_code == 200
    assert "No results for zzzz-no-match-websitebench" in no_results.text
    assert 'href="/browse"' in no_results.text

    assert missing.status_code == 404
    assert "We were not able to find the page you're looking for." in missing.text
    for path in ("/", "/browse", "/search"):
        assert f'href="{path}"' in missing.text

    assert specialization.status_code == 200
    assert 'data-enrollment-login-open' in specialization.text
    assert 'name="next" value="/checkout/deep-learning"' in specialization.text
    assert '<form action="/enrollments" method="post">' not in specialization.text
    assert enrollment_prompt.status_code == 200
    assert 'data-open-on-load="true"' in enrollment_prompt.text
    assert 'name="next" value="/checkout/deep-learning"' in enrollment_prompt.text
    assert "Log in or create account" in enrollment_prompt.text

    assert course.status_code == 200
    assert (
        'href="/learn/neural-networks-deep-learning/lesson/lesson-neural-intro"'
        in course.text
    )
    assert "Preview the first lesson" in course.text
    assert preview.status_code == 200
    assert "Welcome to neural networks" in preview.text
    assert "Public offline preview" in preview.text
    assert (
        'href="/learn/neural-networks-deep-learning/lesson/lesson-forward-propagation"'
        in preview.text
    )
    assert 'action="/learning/progress/' not in preview.text
    assert 'action="/learning/quizzes/' not in preview.text

    second_preview = client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-forward-propagation"
    )
    assert second_preview.status_code == 200
    assert "Forward propagation" in second_preview.text
    assert "Public offline preview" in second_preview.text
    assert (
        'href="/learn/neural-networks-deep-learning/lesson/lesson-neural-intro"'
        in second_preview.text
    )
    assert 'action="/learning/progress/' not in second_preview.text


def test_authenticated_empty_states_and_deferred_payment_boundaries_are_explicit() -> None:
    current = json.loads(CURRENT_PHASE_PATH.read_text(encoding="utf-8"))
    coverage = {entry["journey_id"]: entry for entry in current["coverage"]}

    for journey_id in (
        "learning.lesson",
        "learning.quiz-feedback",
        "learning.progress",
    ):
        assert coverage[journey_id]["phase_status"] == "deferred"

    assert coverage["auth.login-dashboard"]["phase_status"] == "current-complete"
    assert coverage["auth.login-dashboard"]["source_evidence_status"] == (
        "captured-authenticated-empty-account-en"
    )

    for journey_id in ("learning.preferences", "history.seeded"):
        assert coverage[journey_id]["phase_status"] == "current-partial"
        assert coverage[journey_id]["source_evidence_status"].startswith("captured-")

    for journey_id in (
        "enrollment.deep-learning-review",
        "enrollment.paid-review",
        "task265.deep-learning-review",
    ):
        assert coverage[journey_id]["phase_status"] == "current-partial"
        assert coverage[journey_id]["stop_state"] == "empty-payment-fields"
        assert "payment" in coverage[journey_id]["deferred_boundary"].lower()

    assert current["source_mutation_policy"]["public_methods"] == ["GET"]
    assert current["sensitive_data_policy"] == {
        "credential_entry": "user-only-in-temporary-browser",
        "payment_entry": "forbidden",
        "persist_browser_profile": False,
        "persist_storage_state": False,
        "persist_personal_identifiers": False,
    }
