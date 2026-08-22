from __future__ import annotations

import importlib
import re

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
    """Catch the public entry reverting to the obsolete Chinese prototype."""

    response = desktop_client.get("/")

    assert 'lang="en"' in response.text
    assert "For Individuals" in response.text
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
        'placeholder="What do you want to learn?"',
        '<footer class="wb-footer',
    ):
        assert marker in html


def test_home_uses_the_observed_two_panel_promotional_rail(
    desktop_client: TestClient,
) -> None:
    """Keep the first desktop viewport card-led rather than a generic hero."""

    html = desktop_client.get("/").text

    assert 'class="promo-rail"' in html
    assert html.count('class="promo-panel') == 4
    assert html.count('class="home-promo-choice"') == 4
    assert "Learn without limits" in html
    assert "Save 40% on 3 months of Coursera Plus" in html
    assert "Close team skill gaps" in html
    assert "Start, switch, or advance your career" in html


def test_home_exposes_requested_complete_discovery_sections(
    desktop_client: TestClient,
) -> None:
    """Catch requested homepage collections being reduced to headings or omitted."""

    html = desktop_client.get("/").text

    for heading in (
        "New and popular",
        "Get job-ready for an in-demand career",
        "Learn from 350+ leading universities and companies",
        "Explore categories",
        "Trending searches",
        "What brings you to Coursera today?",
        "91% of learners achieved a positive career outcome",
        "Why people choose Coursera",
        "Frequently asked questions",
    ):
        assert heading in html
    assert html.count('class="home-promo-choice"') == 4
    assert html.count('class="source-list-card"') == 18
    assert html.count('class="source-learning-card"') >= 12
    assert len(
        re.findall(r'<div class="source-learning-card"[^>]*data-card-href="/[^"]+"', html)
    ) == html.count('class="source-learning-card"')
    assert html.count('class="source-role-card"') == 5
    assert html.count('class="source-card-image"') >= 30
    assert 'class="source-skeleton-card"' not in html
    assert html.count('class="source-logo-pill"') >= 8
    assert 'href="/search?q=Python"' in html


def test_home_uses_source_observed_visual_assets_and_cookie_banner(
    desktop_client: TestClient,
) -> None:
    """Catch the homepage falling back to placeholder art and a too-short viewport."""

    html = desktop_client.get("/").text

    for asset in (
        "/static/home/logo-google.avif",
        "/static/home/logo-ibm.avif",
        "/static/home/logo-microsoft.avif",
    ):
        assert asset in html
    for observed_title in (
        "Save 40% on 3 months of Coursera Plus",
        "Close team skill gaps",
        "Start, switch, or advance your career",
    ):
        assert observed_title in html
    for observed_title in (
        "Google Career Collection",
        "Python for Everybody",
        "Google Data Analytics",
    ):
        assert observed_title in html
    assert 'class="source-cookie-banner"' not in html


def test_authenticated_shell_replaces_auth_links_with_my_learning(
    desktop_client: TestClient,
) -> None:
    """Catch a signed-in learner still seeing anonymous account controls."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/my-learning").text

    assert 'href="/my-learning"' in html
    assert "Log out" in html


def test_browse_has_source_style_subject_grid_and_canonical_heading(
    desktop_client: TestClient,
) -> None:
    """Catch Browse losing its visible subject discovery entry points."""

    response = desktop_client.get("/browse")

    assert "Explore Categories" in response.text
    assert 'href="/browse/data-science"' in response.text
    assert 'class="source-category-chips"' in response.text
    expected_order = (
        "Arts and Humanities",
        "Business",
        "Computer Science",
        "Data Science",
        "Health",
        "Information Technology",
        "Language Learning",
        "Math and Logic",
        "Personal Development",
        "Physical Science and Engineering",
        "Social Sciences",
    )
    category_html = response.text.split(
        '<nav class="source-category-chips"', 1
    )[1].split("</nav>", 1)[0]
    positions = [category_html.index(label) for label in expected_order]
    assert positions == sorted(positions)
    assert 'class="wb-ai-sparkle"' in response.text


def test_browse_matches_observed_explore_categories_and_role_rows(
    desktop_client: TestClient,
) -> None:
    """Catch Browse replacing archived role cards with a failed-query empty state."""

    html = desktop_client.get("/browse").text

    assert ">Explore Categories</h1>" in html
    assert 'class="source-category-chips"' in html
    assert 'class="source-popular-grid"' in html
    assert "Grow in your career and get new skills with these premium courses on a 7-day free trial" in html
    for label in (
        "Level: Beginner",
        "Popular",
        "Software Engineering &amp; IT",
        "Business",
        "Sales &amp; Marketing",
        "Data Science &amp; Analytics",
        "Healthcare",
    ):
        assert label in html
    assert 'class="source-role-grid"' in html
    expected_roles = (
        (
            "Data Scientist",
            "/static/browse/roles/data-scientist.avif",
            "$145,280",
            "55,655 jobs available",
        ),
        (
            "Machine Learning Engineer",
            "/static/browse/roles/machine-learning-engineer.avif",
            "$169,700",
            "6,963 jobs available",
        ),
        (
            "Data Analyst",
            "/static/browse/roles/data-analyst.avif",
            "$97,664",
            "70,687 jobs available",
        ),
        (
            "IT Project Manager",
            "/static/browse/roles/it-project-manager.avif",
            "$151,424",
            "97,488 jobs available",
        ),
    )
    for title, image, salary, openings in expected_roles:
        assert f">{title}</h3>" in html
        assert f'src="{image}"' in html
        assert salary in html
        assert openings in html
    assert html.count('class="source-role-card"') == 4
    assert "No results found" not in html
    assert "source-role-skeleton" not in html


def test_browse_lower_collections_match_the_supplied_and_playwright_evidence(
    desktop_client: TestClient,
) -> None:
    """Catch invented lower-page cards replacing the observed Browse collections."""

    html = desktop_client.get("/browse").text
    role_position = html.index('class="source-role-explorer"')
    faq_position = html.index('class="source-browse-faq"')
    lower = html[role_position:faq_position]

    headings = (
        "Google Analytics for Data Insights",
        "Your Path to Project Management: Google Project Management Essentials",
        "AI Basics for Everyone",
        "Trending now",
        "In-demand skills",
        "New releases",
        "Leading partners",
    )
    positions = [lower.index(f">{heading}</h2>") for heading in headings]
    assert positions == sorted(positions)
    assert "home-learning-card" not in lower
    assert "home-degree-card" not in lower

    observed_cards = (
        ("Google Analytics Insights", "/search?q=Google+Analytics+Insights", "/static/browse/google-data-analytics.png"),
        ("Google Analytics: Data-Driven Marketing Mastery with AI", "/search?q=Google+Analytics+Data-Driven+Marketing+Mastery+with+AI", "/static/browse/google-data-analytics.png"),
        ("Project Planning: Putting It All Together", "/search?q=Project+Planning+Putting+It+All+Together", "/static/browse/google-project-management.png"),
        ("Foundations of Project Management", "/learn/foundations-of-project-management", "/static/browse/google-project-management.png"),
        ("AI For Everyone", "/search?q=AI+For+Everyone", "/static/browse/lower/trending-introduction-ai.jpg"),
        ("AI For All", "/search?q=AI+For+All", "/static/browse/lower/trending-ai-fundamentals.jpg"),
        ("Introduction to AI", "/learn/google-introduction-to-ai", "/static/browse/lower/trending-introduction-ai.jpg"),
        ("Generative AI Fundamentals", "/search?q=Generative+AI+Fundamentals", "/static/browse/lower/trending-google-ai-essentials.jpg"),
        ("AI Fundamentals", "/learn/google-ai-fundamentals", "/static/browse/lower/trending-ai-fundamentals.jpg"),
        ("AI for App Deployment", "/learn/google-ai-for-app-deployment", "/static/browse/lower/release-ai-app-deployment.jpg"),
        ("Anti Money Laundering and Transaction Compliance", "/specializations/anti-money-laundering-and-transaction-compliance", "/static/browse/lower/release-anti-money-laundering.jpg"),
        ("Emotional Intelligence, Creativity, and Mental Strength - 2026", "/specializations/emotional-intelligence", "/static/browse/lower/release-emotional-intelligence.jpg"),
        ("Customer Service, Customer Support, Customer Experience", "/search?q=Customer+Service+Customer+Support+Customer+Experience", "/static/browse/lower/release-financial-modeling.jpg"),
    )
    for title, href, image in observed_cards:
        assert title in lower
        assert f'href="{href}"' in lower
        assert f'src="{image}"' in lower

    for fact in (
        "4.8 · 12K reviews",
        "4.8 · 33K reviews",
        "4.8 · 143K reviews",
        "4.8 · 92K reviews",
        "4.8 · 8K reviews",
        "4.8 · 13K reviews",
        "4.8 · 25K reviews",
        "4.8 · 4.7K reviews",
        "4.8 · 51 reviews",
        "4.6 · 15 reviews",
        "4.3 · 40 reviews",
        "4.7 · 67 reviews",
    ):
        assert fact in lower

    for skill, href in (
        ("Responsible AI", "/courses?query=responsible%20ai"),
        ("AI literacy", "/courses?query=ai%20literacy"),
        ("Google Gemini", "/courses?query=google%20gemini"),
        ("AI Enablement", "/courses?query=ai%20enablement"),
        ("Machine Learning", "/courses?query=machine%20learning"),
        ("Generative AI", "/courses?query=generative%20ai"),
    ):
        assert skill in lower
        assert f'href="{href}"' in lower

    for partner, href in (
        ("University of Illinois at Urbana-Champaign", "/partners/illinois"),
        ("Duke University", "/partners/duke"),
        ("Google", "/partners/google"),
        ("University of Michigan", "/partners/umich"),
        ("IBM", "/partners/ibm-skills-network"),
        ("Imperial College of London", "/partners/imperial"),
        ("Stanford University", "/partners/stanford"),
        ("University of Pennsylvania", "/partners/penn"),
    ):
        assert f'alt="{partner}"' in lower
        assert f'href="{href}"' in lower

    assert lower.count('class="source-lower-course-card"') == 20
    assert lower.count('class="source-lower-degree-card"') == 0
    assert lower.count('class="source-lower-skill-link"') == 6
    assert lower.count('class="source-lower-partner"') == 8
    assert lower.count("Show 8 more") == 2


def test_browse_uses_the_source_observed_english_card_surface(
    desktop_client: TestClient,
) -> None:
    """Catch Browse showing recommendations from a different source response."""

    html = desktop_client.get("/browse").text

    assert '<html lang="en">' in html
    assert ">Most popular</h2>" in html
    assert "Explore roles" in html
    for subject in (
        "Personal Development",
        "Information Technology",
        "Data Science",
        "Arts and Humanities",
    ):
        assert subject in html
    expected_cards = (
        (
            "Deep Learning",
            "DeepLearning.AI",
            "/specializations/deep-learning",
            "/static/browse/deep-learning.png",
            "4.8 · 147K reviews",
            "Intermediate · Specialization",
        ),
        (
            "IBM AI Product Manager",
            "IBM",
            "/professional-certificates/ibm-ai-product-manager",
            "/static/browse/ibm-ai-product-manager.png",
            "4.7 · 36K reviews",
            "Beginner · Professional Certificate · 3 months",
        ),
        (
            "Foundations of Cybersecurity",
            "Google",
            "/learn/foundations-of-cybersecurity",
            "/static/browse/foundations-cybersecurity.png",
            "4.8 · 42K reviews",
            "Beginner · Course",
        ),
        (
            "Technical Support Fundamentals",
            "Google",
            "/learn/technical-support-fundamentals",
            "/static/browse/technical-support-fundamentals.png",
            "4.8 · 165K reviews",
            "Beginner · Course · 8 - 10 hours per module",
        ),
    )
    for title, provider, href, asset, rating, meta in expected_cards:
        assert title in html
        assert provider in html
        assert f'href="{href}"' in html
        assert f'src="{asset}"' in html
        assert rating in html
        assert meta in html

    popular = html.split('class="source-browse-popular"', 1)[1].split(
        'class="source-role-explorer"', 1
    )[0]
    assert popular.count(">Free Trial<") == 4
    assert ">AI skills<" in popular
    assert "Build toward a degree" in popular


def test_browse_includes_the_observed_faq_footnote_and_full_footer(
    desktop_client: TestClient,
) -> None:
    """Catch the source Browse page being truncated below its role section."""

    html = desktop_client.get("/browse").text

    for text in (
        "Frequently asked questions",
        "What types of courses does Coursera offer?",
        "What are the benefits of taking courses on Coursera?",
        "Can I earn an accredited degree through Coursera?",
        "Show all 7 frequently asked questions",
        "More questions",
        "Visit the learner help center",
        "Median salary and job opening data are sourced from Lightcast™ Job Postings Report.",
        "Skills",
        "Professional Certificates",
        "Courses &amp; Specializations",
        "Career Resources",
        "Accounting",
        "Google AI Certificate",
        "Deep Learning Specialization",
        "Career Aptitude Test",
        "What We Offer",
        "The Coursera Podcast",
        "Cookies Preference Center",
    ):
        assert text in html
    assert 'class="source-browse-faq"' in html
    assert 'class="wb-footer source-browse-footer"' in html


def test_browse_includes_the_settled_personalized_signup_section(
    desktop_client: TestClient,
) -> None:
    """Catch the page jumping directly from its footnote to the footer."""

    html = desktop_client.get("/browse").text

    assert 'class="source-browse-signup"' in html
    assert "Join for free and get personalized recommendations, updates and offers." in html
    assert 'class="source-browse-signup-button" href="/signup">Join for free</a>' in html


def test_impossible_query_shows_no_match_and_recovery(
    desktop_client: TestClient,
) -> None:
    """Catch an impossible public query looking like a blank catalog."""

    html = desktop_client.get("/search?q=zzzz-no-match-websitebench").text

    assert "No results for zzzz-no-match-websitebench" in html
    assert "Try another search or explore the catalog." in html
    assert 'href="/browse"' in html


def test_catalog_filters_preserve_selected_values_and_real_result_ids(
    desktop_client: TestClient,
) -> None:
    """Catch the English filter drawer disconnecting from server-side results."""

    html = desktop_client.get("/search?q=Deep&level=Intermediate").text

    assert "Filter & Sort" in html
    assert 'value="Intermediate" selected' in html
    assert 'data-catalog-record=' in html


def test_search_matches_observed_ai_overview_and_filter_chips(
    desktop_client: TestClient,
) -> None:
    """Catch search reverting to a generic sidebar-first result page."""

    html = desktop_client.get("/search?q=Deep+Learning+Specialization").text

    assert 'class="search-ai-overview"' in html
    assert "AI Overview" in html
    assert "Top courses to get started:" in html
    assert 'class="source-filter-chips"' in html
    for chip in (
        "Filter & Sort",
        "Topic",
        "Duration",
        "Learning Product",
        "Language",
        "Level",
    ):
        assert chip in html


def test_search_retains_query_in_header_and_related_cards(
    desktop_client: TestClient,
) -> None:
    """Catch search losing the source-observed query context and related row."""

    html = desktop_client.get("/search?q=Deep+Learning+Specialization").text

    assert 'id="wb-header-search" name="query" value="Deep Learning Specialization"' in html
    assert 'class="search-ai-summary-cards"' in html
    assert html.count('class="search-ai-starter-card"') == 4


def test_specialization_shows_observed_trial_and_course_series(
    desktop_client: TestClient,
) -> None:
    """Keep the prototype specialization grounded in the English Playwright page."""

    html = desktop_client.get("/specializations/deep-learning").text

    assert '<html lang="en">' in html
    assert 'class="source-specialization-hero"' in html
    assert "Deep Learning Specialization" in html
    assert "Become a Machine Learning expert." in html
    assert "Master the fundamentals of deep learning and break into AI." in html
    assert "Enroll for free" in html
    assert 'class="source-specialization-stats"' in html
    assert "5 course series" in html
    assert "4.8" in html
    assert "Intermediate level" in html
    assert "Flexible schedule" in html
    assert 'class="source-specialization-tabs"' in html
    for label in ("About", "Outcomes", "Courses", "Testimonials"):
        assert f">{label}<" in html


def test_specialization_exposes_the_observed_english_content_and_local_art(
    desktop_client: TestClient,
) -> None:
    """Catch the first prototype replacing direct source content with placeholders."""

    html = desktop_client.get("/specializations/deep-learning").text

    assert "What you'll learn" in html
    assert "Skills you'll gain" in html
    assert "Details to know" in html
    assert "Specialization - 5 course series" in html
    assert html.count('class="source-specialization-course"') == 5
    for asset in (
        "/static/deep-learning/provider-icon.png",
        "/static/deep-learning/instructor-andrew-ng.jpg",
        "/static/deep-learning/course-neural-networks.png",
        "/static/deep-learning/course-sequence-models.png",
    ):
        assert asset in html


def test_course_exposes_observed_materials_without_invented_preview(
    desktop_client: TestClient,
) -> None:
    """Keep the course page on observed modules instead of a simulated route."""

    html = desktop_client.get("/learn/neural-networks-deep-learning").text

    assert "There are 4 modules in this course" in html
    assert "Instructors" in html
    assert "Learner reviews" in html
    assert "/learn/neural-networks-deep-learning/preview" not in html


def test_course_detail_matches_observed_source_layout_sections(
    desktop_client: TestClient,
) -> None:
    """Catch course detail pages reverting to generic cards above the fold."""

    html = desktop_client.get("/learn/neural-networks-deep-learning").text

    assert "Neural Networks and Deep Learning" in html
    assert 'class="source-course-detail-stats"' in html
    assert 'class="source-course-detail-tabs"' in html
    assert 'class="source-course-skill-chips"' in html
    for tab in ("About", "Outcomes", "Modules", "Testimonials", "Reviews"):
        assert f">{tab}<" in html


def test_not_found_matches_observed_safe_recovery(
    desktop_client: TestClient,
) -> None:
    """Catch a missing route dropping the catalog recovery links."""

    response = desktop_client.get("/websitebench-not-found-33")

    assert response.status_code == 404
    assert "We were not able to find the page you're looking for." in response.text
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

    assert "Log in or create account" in html
    assert 'type="email"' in html
    assert "Continue with Google" in html
    assert "Terms of Use" in html
    assert "Privacy Notice" in html


def test_unified_auth_entry_uses_an_observed_modal_surface(
    desktop_client: TestClient,
) -> None:
    """The public auth form is a centered entry modal over a local backdrop."""

    html = desktop_client.get("/login").text

    assert 'class="source-login-dialog"' in html
    assert 'data-login-dialog' in html
    assert 'data-open-on-load="true"' in html


def test_recovery_requires_local_address_and_returns_to_login(
    desktop_client: TestClient,
) -> None:
    """Catch password recovery losing validation context or a safe return route."""

    html = desktop_client.get("/account-recovery").text

    assert "Reset your Coursera password" in html
    assert 'type="email"' in html
    assert 'href="/login"' in html


def test_seeded_dashboard_has_resume_progress_and_history_links(
    desktop_client: TestClient,
) -> None:
    """Catch the seeded learner dashboard omitting its usable continuation path."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/my-learning").text

    assert "My Learning" in html
    assert "Continue learning" in html
    assert 'href="/account/history"' in html


def test_seeded_enrollment_status_is_presented_in_english(
    desktop_client: TestClient,
) -> None:
    """The English desktop contract must cover learner records, not just headers."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/account/history").text

    assert 'class="catalog-card enrollment-card"' in html
    assert "In progress" in html


def test_checkout_plan_matches_observed_trial_price_and_total(
    desktop_client: TestClient,
) -> None:
    """Catch the local checkout drifting from the observed trial and price facts."""

    _login_seeded_progress_learner(desktop_client)

    html = desktop_client.get("/checkout/deep-learning").text

    assert "7-day free trial" in html
    assert "Then ¥196/month" in html
    assert "Total due today: ¥0" in html
    assert "Billing information" in html
    assert "Payment method" in html
    assert 'href="/static/checkout-desktop.css?v=' in html


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
