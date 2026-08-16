from __future__ import annotations

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_desktop_shell_uses_source_observed_language_and_navigation() -> None:
    """Catch the public entry remaining English-first after the source changed."""

    response = client.get("/")

    assert 'lang="zh-CN"' in response.text
    assert "为个人" in response.text
    assert 'href="/browse"' in response.text
    assert 'action="/search"' in response.text


def test_source_facing_checkout_alias_is_local_and_reachable() -> None:
    """Catch source-shaped checkout navigation falling through to a 404."""

    response = client.get("/payments/checkout", follow_redirects=False)

    assert response.status_code in {200, 303, 401}
    assert "coursera.org" not in response.headers.get("location", "")
