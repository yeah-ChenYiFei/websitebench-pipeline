from __future__ import annotations

from html import unescape
import re

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)

SUBJECTS = {
    "arts-and-humanities": "Arts and Humanities",
    "business": "Business",
    "computer-science": "Computer Science",
    "data-science": "Data Science",
    "health": "Health",
    "information-technology": "Information Technology",
    "language-learning": "Language Learning",
    "math-and-logic": "Math and Logic",
    "personal-development": "Personal Development",
    "physical-science-and-engineering": "Physical Science and Engineering",
    "social-sciences": "Social Sciences",
}

SUBJECTS_ZH = {
    "arts-and-humanities": "艺术与人文",
    "business": "商业",
    "computer-science": "计算机科学",
    "data-science": "数据科学",
    "health": "健康",
    "information-technology": "信息技术",
    "language-learning": "语言学习",
    "math-and-logic": "数学与逻辑",
    "personal-development": "个人发展",
    "physical-science-and-engineering": "物理科学与工程",
    "social-sciences": "社会科学",
}


def test_home_and_search_use_the_source_observed_document_titles() -> None:
    expected_titles = {
        "/": "Coursera | Online Courses, Certificates, & Degrees",
        "/search?query=deep": (
            "Coursera | Online Courses From Top Universities. Join for Free"
        ),
    }

    for path, expected_title in expected_titles.items():
        response = client.get(path)

        assert response.status_code == 200
        title = re.search(r"<title>(.*?)</title>", response.text)
        assert title is not None
        assert unescape(title.group(1)) == expected_title


def test_public_home_browse_and_all_subject_routes_render_real_catalog() -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "New! Learn vibe coding with Google" in home.text
    assert 'href="/browse"' in home.text

    browse = client.get("/browse")
    assert browse.status_code == 200
    assert "按主题浏览课程" in browse.text
    for slug, subject in SUBJECTS.items():
        assert f'href="/browse/{slug}"' in browse.text
        assert SUBJECTS_ZH[slug] in browse.text

        category = client.get(f"/browse/{slug}")
        assert category.status_code == 200
        assert f"<h1>{SUBJECTS_ZH[slug]}</h1>" in category.text
        assert category.text.count('data-catalog-record="') >= 3


def test_home_extends_below_the_first_viewport_with_source_observed_sections() -> None:
    """Catch a home page that appears to stop loading after the trend cards."""

    home = client.get("/")

    assert home.status_code == 200
    for marker in (
        "订阅即可解锁 10,000 多门课程",
        "学习来自 350 多家领先大学和公司的知识",
        "探索类别",
        "热门新版本",
        "是什么让您今天来到 Coursera？",
        "为什么人们选择 Coursera",
        "Frequently asked questions",
    ):
        assert marker in home.text
    assert home.text.count('class="source-category-chip"') >= 10
    assert home.text.count('class="source-logo-pill"') >= 8
    assert home.text.count('class="source-release-card"') >= 6
    assert 'href="/browse/data-science"' in home.text
    assert 'href="/search?q=Google+%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD%E8%A6%81%E7%82%B9"' in home.text


def test_home_cookie_banner_accept_and_reject_are_real_local_interactions() -> None:
    """Catch inert cookie buttons that make the page feel non-functional."""

    with TestClient(app) as isolated:
        first = isolated.get("/")
        assert 'class="source-cookie-banner"' in first.text
        assert 'action="/privacy-preferences"' in first.text
        assert 'name="choice" value="accept"' in first.text
        assert 'name="choice" value="reject"' in first.text

        accepted = isolated.post(
            "/privacy-preferences",
            data={"choice": "accept"},
            follow_redirects=False,
        )
        assert accepted.status_code == 303
        assert accepted.headers["location"] == "/"

        after_accept = isolated.get("/")
        assert 'class="source-cookie-banner"' not in after_accept.text

    with TestClient(app) as isolated:
        rejected = isolated.post(
            "/privacy-preferences",
            data={"choice": "reject"},
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        after_reject = isolated.get("/")
        assert 'class="source-cookie-banner"' not in after_reject.text


def test_browse_matches_the_retained_oracle_course_collection_composition() -> None:
    """Catch removal of the oracle's popular filters, four-card row, and reveal."""

    browse = client.get("/browse")
    assert browse.status_code == 200
    assert 'aria-label="热门课程分类"' in browse.text
    for label in (
        "全部",
        "商业",
        "数据科学",
        "信息技术",
        "计算机科学",
    ):
        assert f">{label}<" in browse.text
    popular = re.search(
        r'<div class="card-grid popular-grid">(.*?)</div><details',
        browse.text,
        re.S,
    )
    assert popular is not None
    assert popular.group(1).count('data-catalog-record="') == 4
    assert "显示更多课程" in browse.text
    assert "browse-roles" in browse.text


def test_search_combines_every_filter_sorts_server_side_and_recovers_from_no_match() -> (
    None
):
    combined = client.get(
        "/search",
        params={
            "q": "deep",
            "category": "data-science",
            "level": "Intermediate",
            "topic": "Neural",
            "duration": "3 weeks at 10 hours a week",
            "rating": "4.9",
            "language": "English",
            "schedule": "Flexible schedule",
            "sort": "rating-desc",
        },
    )
    assert combined.status_code == 200
    assert 'data-result-count="1"' in combined.text
    assert 'data-catalog-record="neural-networks-deep-learning"' in combined.text
    assert 'data-catalog-record="deep-learning-specialization"' not in combined.text
    for field in (
        "q",
        "category",
        "level",
        "topic",
        "duration",
        "rating",
        "language",
        "schedule",
        "sort",
    ):
        assert f'name="{field}"' in combined.text

    sorted_results = client.get(
        "/search",
        params={
            "category": "data-science",
            "level": "Intermediate",
            "sort": "rating-desc",
        },
    ).text
    ordered_ids = (
        "neural-networks-deep-learning",
        "convolutional-neural-networks",
        "deep-learning-specialization",
        "machine-learning-foundations",
    )
    positions = [
        sorted_results.index(f'data-catalog-record="{record_id}"')
        for record_id in ordered_ids
    ]
    assert positions == sorted(positions)

    no_match = client.get("/search", params={"q": "zzzz-no-match-websitebench"})
    assert no_match.status_code == 200
    assert 'data-result-count="0"' in no_match.text
    assert "没有找到与“zzzz-no-match-websitebench”匹配的课程" in no_match.text
    assert "zzzz-no-match-websitebench" in no_match.text
    assert 'href="/browse"' in no_match.text
    assert 'href="/search"' in no_match.text


def test_language_and_schedule_filters_each_narrow_results_and_combine() -> None:
    spanish = client.get("/search", params={"language": "Spanish"})
    fixed = client.get("/search", params={"schedule": "Fixed schedule"})
    combined = client.get(
        "/search",
        params={"language": "Spanish", "schedule": "Fixed schedule"},
    )

    assert spanish.status_code == fixed.status_code == combined.status_code == 200
    assert re.findall(r'data-catalog-record="([^"]+)"', spanish.text) == [
        "algorithms",
        "business-strategy",
        "nutrition-wellness",
        "spanish-beginners",
    ]
    assert re.findall(r'data-catalog-record="([^"]+)"', fixed.text) == [
        "financial-accounting",
        "medical-neuroscience",
        "web-development",
        "spanish-beginners",
    ]
    assert re.findall(r'data-catalog-record="([^"]+)"', combined.text) == [
        "spanish-beginners"
    ]
    assert 'data-result-count="4"' in spanish.text
    assert 'data-result-count="4"' in fixed.text
    assert 'data-result-count="1"' in combined.text


def test_specialization_component_details_and_free_preview_are_complete() -> None:
    component_ids = (
        "neural-networks-deep-learning",
        "improving-deep-neural-networks",
        "structuring-machine-learning-projects",
        "convolutional-neural-networks",
        "sequence-models",
    )
    specialization = client.get("/specializations/deep-learning")
    assert specialization.status_code == 200
    assert "<h1>深度学习专项课程</h1>" in specialization.text
    assert "5 门课程系列" in specialization.text
    assert "4.8" in specialization.text
    assert "中级水平" in specialization.text
    assert "每周 10 小时，约 3 个月" in specialization.text
    for course_id in component_ids:
        assert f'href="/learn/{course_id}"' in specialization.text

        detail = client.get(f"/learn/{course_id}")
        assert detail.status_code == 200
        assert 'data-course-detail="' in detail.text
        for section in (
            "课程模块",
            "讲师",
            "先修知识",
            "评论",
            "价格",
            "报名选项",
        ):
            assert f">{section}<" in detail.text
        assert f'href="/learn/{course_id}/preview"' in detail.text

    preview = client.get("/learn/neural-networks-deep-learning/preview")
    assert preview.status_code == 200
    assert "<h1>免费预览：" in preview.text
    assert "Neural network foundations" in preview.text
    assert 'href="/learn/neural-networks-deep-learning"' in preview.text


def test_non_direct_catalog_facts_are_visibly_disclosed_on_every_public_surface() -> (
    None
):
    business_card = client.get("/browse/business")
    assert 'data-evidence-classification="truthful-simulation"' in business_card.text
    assert "Evidence: offline simulation; not source-verified." in business_card.text

    business_detail = client.get("/learn/business-strategy")
    assert 'href="/specializations/deep-learning"' not in business_detail.text

    specialization = client.get("/specializations/deep-learning")
    assert "Source-observed course structure; displayed details are simulated." in (
        specialization.text
    )
    assert "Inferred course structure; displayed details are simulated." in (
        specialization.text
    )

    expected_notes = {
        "business-strategy": (
            "Displayed catalog details are a deterministic offline simulation, "
            "not verified source facts."
        ),
        "improving-deep-neural-networks": (
            "Only the public course structure was observed; displayed details are "
            "a deterministic offline simulation."
        ),
        "sequence-models": (
            "Course architecture was inferred; displayed details are a deterministic "
            "offline simulation."
        ),
    }
    for course_id, note in expected_notes.items():
        detail = client.get(f"/learn/{course_id}")
        preview = client.get(f"/learn/{course_id}/preview")
        assert note in detail.text
        assert note in preview.text


def test_catalog_cards_visibly_name_each_non_direct_evidence_classification() -> None:
    pages = {
        "improving-deep-neural-networks": client.get("/browse/data-science").text,
        "sequence-models": client.get("/browse/data-science").text,
        "business-strategy": client.get("/browse/business").text,
    }
    expected_labels = {
        "improving-deep-neural-networks": (
            "Evidence: public structure observed; details simulated."
        ),
        "sequence-models": "Evidence: architecture inferred; details simulated.",
        "business-strategy": "Evidence: offline simulation; not source-verified.",
    }

    for record_id, page in pages.items():
        card = re.search(
            rf'<article class="catalog-card" data-catalog-record="{record_id}">'
            r"(.*?)</article>",
            page,
            re.S,
        )
        assert card is not None
        assert expected_labels[record_id] in card.group(1)


def test_course_breadcrumb_uses_each_records_real_subject_slug() -> None:
    expected = {
        "business-strategy": ("business", "商业"),
        "public-health": ("health", "健康"),
    }
    for course_id, (subject_slug, subject_name) in expected.items():
        detail = client.get(f"/learn/{course_id}")
        assert detail.status_code == 200
        breadcrumb = re.search(
            r'<nav class="course-breadcrumbs">(.*?)</nav>', detail.text, re.S
        )
        assert breadcrumb is not None
        assert f'href="/browse/{subject_slug}">{subject_name}</a>' in breadcrumb.group(
            1
        )
        assert 'href="/browse/data-science"' not in breadcrumb.group(1)


def test_auth_hashes_standalone_shells_recovery_help_and_contact_are_local() -> None:
    home = client.get("/")
    assert 'href="/login">登录</a>' in home.text
    assert 'href="/signup">免费加入</a>' in home.text

    login = client.get("/login")
    assert login.status_code == 200
    assert '<form class="auth-form"' in login.text
    assert 'name="email"' in login.text
    assert 'name="password"' in login.text
    assert "继续使用 Google" in login.text
    assert 'href="/account-recovery"' in login.text
    assert "不会将凭据提交到 Coursera" in login.text

    signup = client.get("/signup")
    assert signup.status_code == 200
    assert 'name="full_name"' in signup.text
    assert 'name="email"' in signup.text
    assert 'name="password"' in signup.text
    assert "使用条款" in signup.text
    assert "验证代码" in signup.text

    recovery = client.get("/account-recovery")
    assert recovery.status_code == 200
    assert 'name="address"' in recovery.text
    assert "不会发送外部重置消息" in recovery.text
    assert 'href="/login"' in recovery.text

    help_page = client.get("/help")
    assert help_page.status_code == 200
    assert "Learner Help Center" in help_page.text
    assert "账户访问" in help_page.text
    assert "失败的操作" in help_page.text

    contact = client.get("/about/contact")
    assert contact.status_code == 200
    for heading in ("Contact Us", "Learner Support", "Inquiries", "Partnerships"):
        assert heading in contact.text
    assert "mailto:" not in contact.text


def test_branded_404_csp_and_html_asset_references_are_offline_closed() -> None:
    missing = client.get("/websitebench-task3-missing-deep-link")
    assert missing.status_code == 404
    assert "我们无法找到您要查找的页面" in missing.text
    assert 'href="/"' in missing.text
    assert 'href="/browse"' in missing.text
    assert 'href="/search"' in missing.text
    assert "coursera" in missing.text.casefold()

    pages = (
        "/",
        "/browse",
        "/browse/data-science",
        "/search?q=deep",
        "/specializations/deep-learning",
        "/learn/neural-networks-deep-learning",
        "/learn/neural-networks-deep-learning/preview",
        "/login",
        "/signup",
        "/account-recovery",
        "/help",
        "/about/contact",
        "/websitebench-task3-missing-deep-link",
    )
    static_paths: set[str] = set()
    for path in pages:
        response = client.get(path)
        policy = response.headers["content-security-policy"]
        assert "default-src 'self'" in policy
        assert "connect-src 'none'" in policy
        assert "frame-src 'none'" in policy
        assert "script-src 'none'" in policy
        assert response.headers["x-content-type-options"] == "nosniff"
        for attribute, value in re.findall(r'\b(src|href)="([^"]+)"', response.text):
            assert not value.startswith(("http://", "https://", "//", "data:"))
            if attribute == "src" or value.startswith("/static/"):
                static_paths.add(value)

    assert static_paths == {
        "/static/auth.css",
        "/static/auth-desktop.css",
        "/static/catalog-desktop.css",
        "/static/checkout.css",
        "/static/checkout-desktop.css",
        "/static/components.css",
        "/static/course-desktop.css",
        "/static/deep-learning-mark.svg",
        "/static/desktop-base.css",
        "/static/desktop-chrome.css",
        "/static/learning-desktop.css",
        "/static/site.css",
        "/static/source-home-career-promo.png",
        "/static/source-home-google-promo.png",
        "/static/source-home-trend-google-ai.png",
        "/static/source-home-trend-google-analytics.png",
        "/static/source-home-trend-microsoft-qa.png",
    }
    for path in static_paths:
        assert client.get(path).status_code == 200
