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


def test_home_uses_the_observed_two_panel_promotional_rail(
    desktop_client: TestClient,
) -> None:
    """Keep the first desktop viewport card-led rather than a generic hero."""

    html = desktop_client.get("/").text

    assert 'class="promo-rail"' in html
    assert html.count('class="promo-panel') == 2
    assert 'class="promo-panel promo-panel-dark"' in html
    assert 'class="promo-panel promo-panel-blue"' in html


def test_home_matches_observed_trending_course_columns(
    desktop_client: TestClient,
) -> None:
    """Catch the home page drifting back to oversized generic catalog cards."""

    html = desktop_client.get("/").text

    assert 'class="trend-columns"' in html
    for heading in ("最受欢迎", "每周聚焦", "紧缺的 AI 技能"):
        assert heading in html
    assert html.count('class="trend-mini-card"') >= 9
    assert "为热门职业做好就业准备" in html


def test_home_uses_source_observed_visual_assets_and_cookie_banner(
    desktop_client: TestClient,
) -> None:
    """Catch the homepage falling back to placeholder art and a too-short viewport."""

    html = desktop_client.get("/").text

    for asset in (
        "/static/source-home-google-promo.png",
        "/static/source-home-career-promo.png",
        "/static/source-home-trend-google-analytics.png",
        "/static/source-home-trend-microsoft-qa.png",
        "/static/source-home-trend-google-ai.png",
    ):
        assert asset in html
    for observed_title in (
        "Google 数据分析",
        "Microsoft 初级质量保证/软件测试工程师",
        "用于头脑风暴和规划的 AI",
    ):
        assert observed_title in html
    assert 'class="source-cookie-banner"' in html
    assert "Your Privacy Rights" in html
    assert "Reject" in html and "Accept" in html


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


def test_browse_matches_observed_explore_categories_and_role_rows(
    desktop_client: TestClient,
) -> None:
    """Catch Browse losing the compact source category/chip and role layout."""

    html = desktop_client.get("/browse").text

    assert "<h1>Explore Categories</h1>" in html
    assert 'class="browse-category-pills"' in html
    assert 'class="source-popular-row"' in html
    assert 'class="role-explorer-row"' in html
    assert html.count('class="role-explorer-card"') >= 2


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


def test_search_matches_observed_ai_overview_and_filter_chips(
    desktop_client: TestClient,
) -> None:
    """Catch search reverting to a generic sidebar-first result page."""

    html = desktop_client.get("/search?q=Deep+Learning+Specialization").text

    assert 'class="search-ai-overview"' in html
    assert "AI 概览" in html
    assert "You are looking for Deep Learning Specialization" in html
    assert 'class="source-filter-chips"' in html
    for chip in ("筛选和排序", "主题", "课程长度", "了解产品", "语言", "级别"):
        assert chip in html


def test_search_retains_query_in_header_and_related_cards(
    desktop_client: TestClient,
) -> None:
    """Catch search losing the source-observed query context and related row."""

    html = desktop_client.get("/search?q=Deep+Learning+Specialization").text

    assert 'id="wb-header-search" name="q" value="Deep Learning Specialization"' in html
    assert 'class="search-related-cards"' in html
    assert html.count('class="search-related-card"') >= 3


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


def test_course_detail_matches_observed_source_layout_sections(
    desktop_client: TestClient,
) -> None:
    """Catch course detail pages reverting to generic cards above the fold."""

    html = desktop_client.get("/learn/neural-networks-deep-learning").text

    assert "神经网络与深度学习" in html
    assert 'class="course-stats"' in html
    assert 'class="course-tabs"' in html
    assert 'class="skill-chip-row"' in html
    for tab in ("关于", "结果", "单元", "推荐", "评价"):
        assert f">{tab}<" in html


def test_not_found_matches_observed_safe_recovery(
    desktop_client: TestClient,
) -> None:
    """Catch a missing route dropping the catalog recovery links."""

    response = desktop_client.get("/websitebench-not-found-33")

    assert response.status_code == 404
    assert "我们无法找到您要查找的页面" in response.text
    assert 'href="/browse"' in response.text
    assert 'href="/search"' in response.text


def test_help_matches_observed_learner_center_article_layout(
    desktop_client: TestClient,
) -> None:
    """Catch public help reverting to a generic marketing support grid."""

    html = desktop_client.get("/help").text

    assert 'class="help-center-page"' in html
    assert 'placeholder="Search for help"' in html
    assert "Learner Help Center" in html
    assert "Troubleshooting login and account issues" in html
    assert "Skip to:" in html
    assert "Unable to log in" in html


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


def test_unified_auth_entry_uses_an_observed_modal_surface(
    desktop_client: TestClient,
) -> None:
    """The public auth form is a centered entry modal over a local backdrop."""

    html = desktop_client.get("/login").text

    assert 'class="auth-modal-shell"' in html
    assert 'class="auth-modal-backdrop"' in html
    assert 'class="auth-modal-card auth-card"' in html


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


def test_seeded_enrollment_status_is_presented_in_chinese(
    desktop_client: TestClient,
) -> None:
    """The Chinese desktop contract must cover learner records, not just headers."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/account/history").text

    assert 'class="catalog-card enrollment-card"' in html
    assert "进行中" in html


def test_checkout_plan_matches_observed_trial_price_and_total(
    desktop_client: TestClient,
) -> None:
    """Catch the local checkout drifting from the observed trial and price facts."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/checkout/deep-learning").text

    assert "7 天免费试用" in html
    assert "之后为 ¥196/月" in html
    assert "今日合计：¥0" in html
    assert "账单信息" in html
    assert "支付方式" in html
    assert 'href="/static/checkout-desktop.css"' in html


def test_source_checkout_post_alias_creates_an_owner_bound_local_draft(
    desktop_client: TestClient,
) -> None:
    """The source-shaped endpoint must never redirect to Coursera or skip auth."""

    _login_seeded_progress_learner(desktop_client)

    response = desktop_client.post(
        "/payments/checkout",
        data={"plan_id": "deep-learning-specialization-trial"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/checkout/checkout_")
    assert "coursera.org" not in response.headers["location"]
