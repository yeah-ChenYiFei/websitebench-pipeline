from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def desktop_client(tmp_path, monkeypatch):
    database = tmp_path / "33.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    learning = importlib.import_module("backend.learning_db")
    learning.close_services()
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        yield client
    learning.close_services()


def _login_seeded_progress_learner(client: TestClient) -> None:
    client.get("/login")
    response = client.post(
        "/auth/login",
        data={
            "email": "progress@coursera.test",
            "password": "Progress-Learner-33",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_desktop_shell_uses_source_observed_language_and_navigation(
    desktop_client: TestClient,
) -> None:
    """Catch the public entry remaining English-first after the source changed."""

    response = desktop_client.get("/")

    assert 'lang="zh-CN"' in response.text
    assert "为个人" in response.text
    assert 'href="/browse"' in response.text
    assert 'action="/search"' in response.text


def test_source_facing_checkout_alias_is_local_and_reachable(
    desktop_client: TestClient,
) -> None:
    """Catch source-shaped checkout navigation falling through to a 404."""

    response = desktop_client.get("/payments/checkout", follow_redirects=False)

    assert response.status_code in {200, 303, 401}
    assert "coursera.org" not in response.headers.get("location", "")


def test_public_shell_has_observed_desktop_chrome(
    desktop_client: TestClient,
) -> None:
    """Catch public pages bypassing the shared Coursera desktop chrome."""

    html = desktop_client.get("/").text

    for marker in (
        'class="wb-audience-bar"',
        'class="wb-header"',
        'class="wb-wordmark"',
        'placeholder="您想学习什么？"',
        'class="wb-footer"',
    ):
        assert marker in html


def test_authenticated_shell_replaces_auth_links_with_my_learning(
    desktop_client: TestClient,
) -> None:
    """Catch a signed-in learner still seeing anonymous account controls."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/my-learning").text

    assert 'href="/my-learning"' in html
    assert "退出登录" in html
