from __future__ import annotations

from html import unescape
import re
from urllib.parse import urlsplit

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

SOURCE_CATEGORY_LEADS = {
    "arts-and-humanities": "Graphic Design",
    "business": "Google Project Management",
    "computer-science": "Python for Everybody",
    "health": "Introduction to Psychology",
    "information-technology": "Google IT Support",
    "language-learning": "Improve Your English Communication Skills",
    "math-and-logic": "Introduction to Mathematical Thinking",
    "personal-development": "Learning How to Learn",
    "physical-science-and-engineering": "An Introduction to Programming the Internet of Things",
    "social-sciences": "Academic English: Writing",
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
    assert "New and popular" in home.text
    assert 'href="/browse"' in home.text

    browse = client.get("/browse")
    assert browse.status_code == 200
    assert "Explore Categories" in browse.text
    for slug, subject in SUBJECTS.items():
        assert f'href="/browse/{slug}"' in browse.text
        assert subject in browse.text

        category = client.get(f"/browse/{slug}")
        assert category.status_code == 200
        if slug == "data-science":
            assert "<h1 id=\"ds-heading\">Data Science</h1>" in category.text
            assert category.text.count('data-source-result-card="') == 12
        elif slug == "business":
            assert '<html lang="en"' in category.text
            assert 'data-websitebench-snapshot="business-2026-08-19-233413"' in category.text
            assert len(
                re.findall(r'class="[^"]*\bcds-ProductCard-base\b', category.text)
            ) == 34
            assert "Trending now" in category.text
        else:
            assert '<html lang="en">' in category.text
            assert f'<h1 id="category-heading">{subject}</h1>' in category.text
            assert SOURCE_CATEGORY_LEADS[slug] in category.text
            assert category.text.count('class="source-category-card"') == 4
            assert "Coursera Offline Catalog" not in category.text
            assert "Evidence: offline simulation" not in category.text


def test_home_extends_below_the_first_viewport_with_source_observed_sections() -> None:
    """Catch a home page that appears to stop loading after the trend cards."""

    home = client.get("/")

    assert home.status_code == 200
    for marker in (
        "New and popular",
        "Get job-ready for an in-demand career",
        "Learn from 350+ leading universities and companies",
        "Explore categories",
        "Trending searches",
        "What brings you to Coursera today?",
        "Frequently asked questions",
    ):
        assert marker in home.text
    home_card_hrefs = re.findall(
        r'<a\b[^>]*\bdata-home-card="[^"]+"[^>]*\bhref="([^"]+)"', home.text
    )
    assert len(home_card_hrefs) >= 35
    assert all(href.startswith("/") for href in home_card_hrefs)
    assert home.text.count('class="source-list-card"') == 18
    assert home.text.count('class="source-learning-card"') >= 12
    assert home.text.count('class="source-role-card"') == 5
    assert home.text.count('class="source-card-image"') >= 30
    assert 'class="source-skeleton-card"' not in home.text
    assert home.text.count('class="source-logo-pill"') >= 8
    assert 'href="/browse/data-science"' in home.text
    assert 'href="/specializations/deep-learning"' in home.text


def test_home_cookie_banner_accept_and_reject_are_real_local_interactions() -> None:
    """The current observed home has no stale first-version cookie overlay."""

    with TestClient(app) as isolated:
        first = isolated.get("/")
        assert 'class="source-cookie-banner"' not in first.text

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
    assert 'aria-label="Most popular categories"' in browse.text
    for label in (
        "All",
        "Business",
        "Data Science",
        "Information Technology",
        "Computer Science",
    ):
        assert f">{label}<" in browse.text
    assert browse.text.count('class="source-popular-card"') == 4
    assert "Show 8 more" in browse.text
    assert "source-role-explorer" in browse.text


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
    assert "No results for zzzz-no-match-websitebench" in no_match.text
    assert "zzzz-no-match-websitebench" in no_match.text
    assert 'href="/browse"' in no_match.text
    assert 'href="/search?query=Deep%20Learning"' in no_match.text


def test_deep_learning_specialization_matches_the_english_playwright_prototype() -> None:
    """Define the source-grounded structure before replacing the old Chinese page."""

    response = client.get("/specializations/deep-learning")

    assert response.status_code == 200
    assert '<html lang="en">' in response.text
    assert 'class="source-specialization-hero"' in response.text
    assert "Become a Machine Learning expert." in response.text
    assert 'class="source-specialization-stats"' in response.text
    assert 'class="source-specialization-tabs"' in response.text
    assert response.text.count('class="source-specialization-course"') == 5


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


def test_specialization_component_details_and_observed_course_materials_are_complete() -> None:
    component_ids = (
        "neural-networks-deep-learning",
        "improving-deep-neural-networks",
        "structuring-machine-learning-projects",
        "convolutional-neural-networks",
        "sequence-models",
    )
    specialization = client.get("/specializations/deep-learning")
    assert specialization.status_code == 200
    assert "<h1>Deep Learning Specialization</h1>" in specialization.text
    assert "5 course series" in specialization.text
    assert "4.8" in specialization.text
    assert "Intermediate level" in specialization.text
    assert "3 months at 10 hours a week" in specialization.text
    for course_id in component_ids:
        assert f'href="/learn/{course_id}"' in specialization.text

        detail = client.get(f"/learn/{course_id}")
        assert detail.status_code == 200
        assert 'data-course-detail="' in detail.text
        if course_id == "neural-networks-deep-learning":
            for section in (
                "There are 4 modules in this course",
                "Instructors",
                "Learner reviews",
                "Frequently asked questions",
            ):
                assert section in detail.text
            assert f"/learn/{course_id}/preview" not in detail.text
            continue
        for section in (
            "Course modules",
            "Instructors",
            "Prerequisites",
            "Reviews",
            "Pricing",
            "Enrollment options",
        ):
            assert f">{section}<" in detail.text
        assert f"/learn/{course_id}/preview" not in detail.text

    assert client.get("/learn/neural-networks-deep-learning/preview").status_code == 404


def test_non_direct_catalog_facts_are_visibly_disclosed_on_every_public_surface() -> (
    None
):
    business_card = client.get("/browse/business")
    assert "Google Project Management" in business_card.text
    assert "AI For Everyone" in business_card.text
    assert 'data-evidence-classification="truthful-simulation"' not in business_card.text
    assert "Evidence: offline simulation; not source-verified." not in business_card.text

    business_detail = client.get("/learn/business-strategy")
    assert 'href="/specializations/deep-learning"' not in business_detail.text

    specialization = client.get("/specializations/deep-learning")
    assert "Specialization - 5 course series" in specialization.text
    assert specialization.text.count('class="source-specialization-course"') == 5

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
        assert note in detail.text


def test_catalog_cards_visibly_name_each_non_direct_evidence_classification() -> None:
    pages = {
        "improving-deep-neural-networks": client.get(
            "/search?q=improving+deep+neural+networks"
        ).text,
        "sequence-models": client.get("/search?q=sequence+models").text,
    }
    expected_labels = {
        "improving-deep-neural-networks": (
            "Evidence: public structure observed; details simulated."
        ),
        "sequence-models": "Evidence: architecture inferred; details simulated.",
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
        "business-strategy": ("business", "Business"),
        "public-health": ("health", "Health"),
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


def test_public_policy_pages_are_english_only() -> None:
    for path, heading in (
        ("/privacy", "Privacy and cookie preferences"),
        ("/terms", "Local terms of use"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert f"<h1>{heading}</h1>" in response.text
        assert re.search(r"[\u4e00-\u9fff]", response.text) is None


def test_language_filter_does_not_change_the_site_locale() -> None:
    response = client.get("/search", params={"language": "English"})
    assert response.status_code == 200
    assert '<html lang="en">' in response.text
    assert "Log In" in response.text
    assert re.search(r"[\u4e00-\u9fff]", response.text) is None


def test_auth_hashes_standalone_shells_recovery_help_and_contact_are_local() -> None:
    home = client.get("/")
    assert 'data-login-open>Log In</button>' in home.text
    assert 'href="/signup">Join for Free</a>' in home.text

    login = client.get("/login")
    assert login.status_code == 200
    assert '<form class="source-login-form"' in login.text
    assert 'name="email"' in login.text
    assert 'name="password"' not in login.text
    assert "Continue with Google" in login.text
    assert 'href="/help"' in login.text
    assert "reCAPTCHA" in login.text

    signup = client.get("/signup")
    assert signup.status_code == 200
    assert 'data-login-dialog' in signup.text
    assert 'data-open-on-load="true"' in signup.text
    assert 'name="email"' in signup.text
    assert 'name="full_name"' not in signup.text
    assert 'name="password"' not in signup.text
    assert 'data-signup-dialog' not in signup.text
    assert "Terms of Use" in signup.text
    assert "Log in or create account" in signup.text

    recovery = client.get("/account-recovery")
    assert recovery.status_code == 200
    assert 'name="address"' in recovery.text
    assert "No reset message is sent" in recovery.text
    assert 'href="/login"' in recovery.text

    help_page = client.get("/help")
    assert help_page.status_code == 200
    assert "Learner Help Center" in help_page.text
    assert "Account access" in help_page.text
    assert "failed actions" in help_page.text

    contact = client.get("/about/contact")
    assert contact.status_code == 200
    for heading in ("Contact Us", "Learner Support", "Inquiries", "Partnerships"):
        assert heading in contact.text
    assert "mailto:" not in contact.text


def test_branded_404_csp_and_html_asset_references_are_offline_closed() -> None:
    missing = client.get("/websitebench-task3-missing-deep-link")
    assert missing.status_code == 404
    assert "We were not able to find the page you're looking for." in missing.text
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
        assert "script-src 'self'" in policy
        assert response.headers["x-content-type-options"] == "nosniff"
        for attribute, value in re.findall(r'\b(src|href)="([^"]+)"', response.text):
            assert not value.startswith(("http://", "https://", "//", "data:"))
            if attribute == "src" or value.startswith("/static/"):
                static_paths.add(urlsplit(value).path)

    required_static_paths = {
        "/static/auth.css",
        "/static/auth-desktop.css",
        "/static/auth-dialog.js",
        "/static/browse-prototype.css",
        "/static/browse/deep-learning.png",
        "/static/browse/ibm-ai-product-manager.png",
        "/static/browse/foundations-cybersecurity.png",
        "/static/browse/technical-support-fundamentals.png",
        "/static/catalog-desktop.css",
        "/static/checkout.css",
        "/static/checkout-desktop.css",
        "/static/components.css",
        "/static/course-desktop.css",
        "/static/desktop-base.css",
        "/static/desktop-chrome.css",
        "/static/learning-desktop.css",
        "/static/home-prototype.css",
        "/static/site.css",
        "/static/home/current-promo-barriers.png",
        "/static/home/current-promo-teams-small.png",
        "/static/home/logo-google.avif",
        "/static/home/logo-ibm.avif",
        "/static/home/logo-microsoft.avif",
        "/static/home/pathway-career.avif",
        "/static/browse/roles/data-scientist.avif",
        "/static/browse/roles/machine-learning-engineer.avif",
    }
    assert required_static_paths <= static_paths
    for path in static_paths:
        assert client.get(path).status_code == 200
