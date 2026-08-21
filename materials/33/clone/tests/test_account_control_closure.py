from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT / "clone"))

from app import app  # noqa: E402


def _login(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_account_settings_update_persists_for_owner_and_renders_saved_values() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client, "empty@coursera.test", "Empty-Learner-33")
        response = client.post(
            "/account-settings",
            data={"display_name": "Empty Owner", "timezone": "Asia/Shanghai"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/account-settings"
        settings = client.get("/account-settings")

    assert 'name="display_name"' in settings.text
    assert 'value="Empty Owner"' in settings.text
    assert 'name="timezone"' in settings.text
    assert 'option value="Asia/Shanghai" selected' in settings.text


def test_account_settings_are_owner_isolated() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client, "empty@coursera.test", "Empty-Learner-33")
        changed = client.post(
            "/account-settings",
            data={"display_name": "Only Empty", "timezone": "Europe/London"},
            follow_redirects=False,
        )
        assert changed.status_code == 303
        client.post("/auth/logout", follow_redirects=False)
        _login(client, "progress@coursera.test", "Progress-Learner-33")
        settings = client.get("/account-settings")

    assert 'value="Progress Learner"' in settings.text
    assert 'value="Only Empty"' not in settings.text
    assert 'option value="UTC" selected' in settings.text


def test_updates_preferences_post_persists_and_is_owner_scoped() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client, "empty@coursera.test", "Empty-Learner-33")
        response = client.post(
            "/updates",
            data={"product_updates": "on", "course_updates": "on"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        updates = client.get("/updates")
        assert 'name="product_updates"' in updates.text
        assert 'name="course_updates"' in updates.text
        assert 'name="product_updates" value="on" checked' in updates.text
        assert 'name="course_updates" value="on" checked' in updates.text
        client.post("/auth/logout", follow_redirects=False)
        _login(client, "progress@coursera.test", "Progress-Learner-33")
        other = client.get("/updates")

    assert 'name="product_updates" value="on" checked' not in other.text
    assert 'name="course_updates" value="on" checked' not in other.text


def test_help_feedback_is_a_local_owner_scoped_state_transition() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client, "empty@coursera.test", "Empty-Learner-33")
        response = client.post(
            "/help/feedback",
            data={"helpful": "yes"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        help_page = client.get("/help")

    assert "Thanks for your feedback" in help_page.text
    assert 'name="helpful" value="yes"' in help_page.text


def test_purchase_show_more_controls_have_real_local_destinations() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client, "empty@coursera.test", "Empty-Learner-33")
        purchases = client.get("/my-purchases/transactions")

    assert '<form class="purchase-show-more-form" action="/search" method="get">' in purchases.text
    assert '<form class="purchase-show-more-form" action="/degrees" method="get">' in purchases.text
    assert purchases.text.count('class="purchase-show-more" type="submit"') == 2
