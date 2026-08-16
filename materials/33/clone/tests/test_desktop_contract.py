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


def test_browse_has_source_style_subject_grid_and_canonical_heading(
    desktop_client: TestClient,
) -> None:
    """Catch Browse losing its visible subject discovery entry points."""

    response = desktop_client.get("/browse")

    assert "按主题浏览课程" in response.text
    assert 'href="/browse/data-science"' in response.text
    assert 'class="subject-tile-grid"' in response.text


def test_impossible_query_shows_no_match_and_recovery(
    desktop_client: TestClient,
) -> None:
    """Catch an impossible public query looking like a blank catalog."""

    html = desktop_client.get("/search?q=zzzz-no-match-websitebench").text

    assert "没有找到与“zzzz-no-match-websitebench”匹配的课程" in html
    assert "推荐课程" in html
    assert 'href="/browse"' in html


def test_catalog_filters_preserve_selected_values_and_real_result_ids(
    desktop_client: TestClient,
) -> None:
    """Catch the Chinese filter surface disconnecting from server-side results."""

    html = desktop_client.get("/search?q=Deep+Learning&level=Beginner").text

    assert "筛选和排序" in html
    assert 'value="Beginner" selected' in html
    assert 'data-catalog-record=' in html


def test_specialization_shows_observed_trial_and_course_series(
    desktop_client: TestClient,
) -> None:
    """Catch the Deep Learning landing page losing source-observed trial facts."""

    html = desktop_client.get("/specializations/deep-learning").text

    assert "深度学习专项课程" in html
    assert "5 门课程系列" in html
    assert "7 天免费试用" in html
    assert "¥196/月" in html


def test_course_exposes_modules_instructors_reviews_and_preview(
    desktop_client: TestClient,
) -> None:
    """Catch the local course detail omitting a route the learner can inspect."""

    html = desktop_client.get("/learn/neural-networks-deep-learning").text

    assert "课程模块" in html
    assert "讲师" in html
    assert "评论" in html
    assert 'href="/learn/neural-networks-deep-learning/preview"' in html


def test_not_found_matches_observed_safe_recovery(
    desktop_client: TestClient,
) -> None:
    """Catch a missing route dropping the catalog recovery links."""

    response = desktop_client.get("/websitebench-not-found-33")

    assert response.status_code == 404
    assert "我们无法找到您要查找的页面" in response.text
    assert 'href="/browse"' in response.text
    assert 'href="/search"' in response.text


def test_unified_auth_entry_has_email_identity_choices_and_terms(
    desktop_client: TestClient,
) -> None:
    """Catch the account entry regressing to a separate English-only form."""

    html = desktop_client.get("/login").text

    assert "登录或创建账户" in html
    assert 'type="email"' in html
    assert "继续使用 Google" in html
    assert "使用条款" in html
    assert "隐私声明" in html


def test_recovery_requires_local_address_and_returns_to_login(
    desktop_client: TestClient,
) -> None:
    """Catch password recovery losing validation context or a safe return route."""

    html = desktop_client.get("/account-recovery").text

    assert "重置您的 Coursera 密码" in html
    assert 'type="email"' in html
    assert 'href="/login"' in html


def test_seeded_dashboard_has_resume_progress_and_history_links(
    desktop_client: TestClient,
) -> None:
    """Catch the seeded learner dashboard omitting its usable continuation path."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/my-learning").text

    assert "我的学习" in html
    assert "继续学习" in html
    assert 'href="/account/history"' in html
