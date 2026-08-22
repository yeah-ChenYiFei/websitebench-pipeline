from __future__ import annotations

import sys
from html import unescape
from pathlib import Path

from fastapi.testclient import TestClient

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT / "clone"))

from app import app  # noqa: E402


def _login(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        data={"email": "empty@coursera.test", "password": "Empty-Learner-33"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_authenticated_account_surfaces_require_login_and_render_observed_empty_states() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        for path in (
            "/my-purchases/transactions",
            "/account-settings",
            "/updates",
            "/onboarding/learning-goal",
        ):
            response = client.get(path)
            assert response.status_code == 401, path
            assert "Sign in" in response.text, path

        _login(client)
        purchases = client.get("/my-purchases/transactions")
        settings = client.get("/account-settings")
        updates = client.get("/updates")
        goals = client.get("/onboarding/learning-goal")

    assert purchases.status_code == 200
    assert "Purchases" in purchases.text
    assert "Recently Viewed Products" in purchases.text
    assert "Payment History" in purchases.text
    assert settings.status_code == 200
    for heading in ("Account settings", "Personal information", "Change password", "Two factor authentication", "Delete account"):
        assert heading in settings.text
    assert updates.status_code == 200
    assert "Updates" in updates.text
    assert "Please confirm your email" in updates.text
    assert goals.status_code == 200
    assert "what's your goal" in goals.text


def test_purchase_recommendations_resolve_to_local_project_details() -> None:
    """Catch recommendation cards whose exposed project destinations still 404."""

    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        purchases = client.get("/my-purchases/transactions")
        assert purchases.status_code == 200
        for path, heading in (
            (
                "/projects/chatgpt-prompt-engineering-for-developers-project",
                "ChatGPT Prompt Engineering for Developers",
            ),
            (
                "/projects/langchain-for-llm-application-development-project",
                "LangChain for LLM Application Development",
            ),
        ):
            assert f'href="{path}"' in purchases.text
            destination = client.get(path)
            assert destination.status_code == 200
            assert f"<h1>{heading}</h1>" in destination.text
            assert 'href="/browse"' in destination.text


def test_authenticated_header_exposes_observed_account_navigation() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        html = client.get("/my-learning").text

    for path in (
        "/my-learning",
        "/my-purchases/transactions",
        "/account-settings",
        "/updates",
    ):
        assert f'href="{path}"' in html
    assert 'action="/auth/logout"' in html


def test_empty_my_learning_has_no_seeded_enrollment_claims() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        html = client.get("/my-learning").text

    assert "Start your learning journey" in html
    assert "Continue learning" not in html
    assert "Course review" not in html
    assert "Certificate available" not in html


def test_empty_my_learning_uses_observed_english_structure_and_local_illustration() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        html = client.get("/my-learning").text

    assert 'data-authenticated-surface="my-learning-empty"' in html
    assert 'data-learning-greeting' in html
    assert 'class="learning-illustration learning-empty-illustration"' in html
    assert 'aria-label="My Learning sections"' in html
    for label in ("In Progress", "Completed", "Certificates"):
        assert label in html
    assert "Enrollments, progress, and bookmarks stay inside this offline clone." not in html
    assert "No local enrollments yet" not in html
    assert "Enrollment history" not in html


def test_local_learner_entry_signs_into_empty_account_without_real_credentials() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        response = client.post(
            "/auth/local-learner",
            data={"next": "/my-learning"},
            follow_redirects=False,
        )
        dashboard = client.get("/my-learning")

    assert response.status_code == 303
    assert response.headers["location"] == "/my-learning"
    assert dashboard.status_code == 200
    assert 'data-authenticated-surface="my-learning-empty"' in dashboard.text


def test_seeded_learning_demo_entry_exposes_authenticated_journey_state() -> None:
    """The 23-journey learning states must be reachable during manual review."""

    with TestClient(app, base_url="https://33.offline.invalid") as client:
        login = client.get("/login")
        response = client.post(
            "/auth/learning-demo",
            data={"next": "/my-learning"},
            follow_redirects=False,
        )
        dashboard = client.get("/my-learning")

    assert 'action="/auth/learning-demo"' in login.text
    assert "Continue with learning demo" in login.text
    assert response.status_code == 303
    assert response.headers["location"] == "/my-learning"
    assert 'data-authenticated-surface="my-learning-enrolled"' in dashboard.text
    assert "Continue learning" in dashboard.text
    assert 'href="/account/preferences"' in dashboard.text
    assert 'href="/account/history"' in dashboard.text


def test_login_dialog_offers_safe_local_entry_without_test_email_warning() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        html = client.get("/login").text
        script = client.get("/static/auth-dialog.js").text

    assert 'action="/auth/local-learner"' in html
    assert "Continue with local learner" in html
    assert 'name="next" value="/my-learning"' in html
    assert "Use a synthetic .test email address" not in script


def test_document_versions_css_and_javascript_as_one_release() -> None:
    """Catch new HTML being paired with stale cached crop and icon CSS."""

    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        html = client.get("/my-learning").text

    for asset in (
        "desktop-base.css",
        "desktop-chrome.css",
        "learning-desktop.css",
        "auth-dialog.js",
    ):
        assert f'/static/{asset}?v=' in html


def test_source_observed_empty_account_copy_and_routes_are_preserved() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        learning = client.get("/my-learning").text
        purchases = client.get("/my-purchases/transactions").text
        settings = unescape(client.get("/account-settings").text)
        updates = client.get("/updates").text
        goals = client.get("/onboarding/learning-goal").text

    assert "Good evening, learner" in learning
    assert "Edit goal" in learning
    assert (
        "Enroll in a course to begin tracking progress in My Learning. "
        "Set a career goal for more personalized recommendations."
    ) in learning

    assert "Need more help? Check out our" in purchases
    assert "Learner Help Center" in purchases
    assert "Terms of Use" in purchases
    assert "No purchases found in your history." in purchases
    assert "Browse courses offering Certificates now." in purchases
    for title in ("Deep Learning", "Neural Networks and Deep Learning", "Google AI"):
        assert title in purchases

    for tab in ("Account", "Communication Preferences", "Notes & Highlights", "Calendar Sync"):
        assert tab in settings
    for heading in (
        "Personal information",
        "Profile photo",
        "Appearance",
        "Name verification",
        "Change password",
        "Two factor authentication",
        "Connected devices",
        "Linked accounts",
        "Learner data report",
        "Delete account",
    ):
        assert heading in settings
    assert "Send report" in settings
    assert "Delete account" in settings

    assert "Please confirm your email" in updates
    assert "You've registered for Coursera using your local learner email." in updates

    for goal in (
        "Start my career",
        "Change my career",
        "Grow in my current role",
        "Explore topics outside of work",
    ):
        assert goal in goals
    assert 'href="/my-learning">Exit</a>' in goals


def test_purchases_renders_all_source_observed_recommendation_sections_and_links() -> None:
    """Removing either lower recommendation rail must break this account surface."""

    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        html = client.get("/my-purchases/transactions").text

    headings = (
        "Recently Viewed Products",
        "Get Started with These Free Courses",
        "Earn Your Degree",
    )
    assert [html.index(heading) for heading in headings] == sorted(
        html.index(heading) for heading in headings
    )

    source_observed_cards = (
        ("Fundamentals of Machine Learning and Artificial Intelligence", "/learn/fundamentals-of-machine-learning-and-artificial-intelligence"),
        ("ChatGPT Prompt Engineering for Developers", "/projects/chatgpt-prompt-engineering-for-developers-project"),
        ("Algorithms, Part I", "/learn/algorithms-part1"),
        ("LangChain for LLM Application Development", "/projects/langchain-for-llm-application-development-project"),
        ("Master of Advanced Study in Engineering", "/degrees/mas-engineering-berkeley"),
        ("Master of Science in Data Analytics Engineering", "/degrees/ms-data-analytics-engineering-northeastern"),
        ("Bachelor of Science in Computer Science", "/degrees/bachelor-of-science-computer-science-london"),
        ("BSc Data Science", "/degrees/bsc-data-science-huddersfield"),
    )
    for title, path in source_observed_cards:
        assert title in html
        assert f'href="{path}"' in html

    assert html.count('class="purchase-show-more"') == 2
    assert html.count(">Show 8 more</button>") == 2
    assert 'src="http' not in html
