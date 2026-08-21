from __future__ import annotations

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def _section(html: str, start_id: str, end_id: str) -> str:
    start = html.index(f'id="{start_id}"')
    end = html.index(f'id="{end_id}"', start)
    return html[start:end]


def _assert_in_order(html: str, values: tuple[str, ...]) -> None:
    positions = [html.index(value) for value in values]
    assert positions == sorted(positions)


def test_data_science_category_uses_the_complete_source_observed_page() -> None:
    """Catch the old translated catalog grid or a truncated source page."""

    response = client.get("/browse/data-science")
    html = response.text

    assert response.status_code == 200
    assert "<title>Data Science Online Courses | Coursera</title>" in html
    assert '<html lang="en">' in html
    assert '<body class="wb-page source-data-science-page">' in html

    section_headings = (
        "Most popular",
        "Explore roles",
        "Trending now",
        "Core skills",
        "Enhance Your Deep Learning Skills with Neural Networks",
        "Online degrees",
        "Explore Categories",
        "All results",
        "New releases",
        "What brings you to Coursera today?",
        "Leading partners",
        "Frequently asked questions",
    )
    positions = [html.index(heading) for heading in section_headings]
    assert positions == sorted(positions)

    for title in (
        "Google Data Analytics",
        "Foundations: Data, Data, Everywhere",
        "IBM Generative AI Engineering",
        "IBM Data Science",
        "Google AI",
        "Google AI Essentials",
        "Introduction to AI",
        "Generative AI for Business Consultants",
        "Discover the Art of Prompting",
        "Generative AI Fundamentals",
        "Data Science Foundations",
        "Master of Science in Data Analytics Engineering",
        "Master of Science in Data Science",
        "Master of Data Science",
        "Master of Science in Data Science (Statistics)",
        "Machine Learning",
        "IBM Data Analyst",
        "Deep Learning",
        "AI in Healthcare",
        "Google Advanced Data Analytics",
        "IBM Data Analytics with Excel and R",
        "Starting a Data Science Career",
        "Applied Data Science and Analytics",
        "Applied Data Science with SQL, R, and Python",
        "Python Data Science Mistakes to Avoid",
    ):
        assert title in html

    assert html.count('data-source-result-card="') == 12
    assert html.count('data-source-release-card="') == 4
    assert 'src="/static/data-science/google-data-analytics.png"' in html
    assert 'src="/static/data-science/degree-northeastern.png"' in html
    assert 'href="/specializations/deep-learning"' in html
    assert "4.8 · 182K reviews" in html
    assert "4.8 · 147K reviews" in html
    assert "Beginner · Professional Certificate · 6 months" in html

    assert html.count('data-source-deep-learning-card="') == 4
    deep_learning = _section(html, "ds-deep-learning-heading", "ds-degrees-heading")
    assert deep_learning.count('class="ds-card-badge"') == 4
    for title, href, image in (
        (
            "Deep Learning",
            "/specializations/deep-learning",
            "/static/browse/deep-learning.png",
        ),
        (
            "Neural Networks and Deep Learning",
            "/learn/neural-networks-deep-learning",
            "/static/deep-learning/course-neural-networks.png",
        ),
        (
            "Convolutional Neural Networks",
            "/learn/convolutional-neural-networks",
            "/static/deep-learning/course-convolutional.png",
        ),
        (
            "Improving Deep Neural Networks: Hyperparameter Tuning, Regularization and Optimization",
            "/learn/deep-neural-network",
            "/static/deep-learning/course-improving-networks.png",
        ),
    ):
        assert title in html
        assert f'href="{href}"' in html
        assert f'src="{image}"' in html
    assert "4.9 · 124K reviews" in html
    assert "4.9 · 43K reviews" in html
    assert "4.9 · 64K reviews" in html
    assert "Google Analytics for Data Insights" not in html
    assert "AI Basics for Everyone" not in html
    assert "IBM Data Science Essentials" not in html

    assert "数据科学" not in html
    assert "热门课程" not in html
    assert 'data-catalog-record="' not in html


def test_data_science_page_uses_only_local_presentation_assets() -> None:
    response = client.get("/browse/data-science")

    assert response.status_code == 200
    assert "d3njjcbhbojbot.cloudfront.net" not in response.text
    assert "coursera-course-photos.s3.amazonaws.com" not in response.text
    assert "https://" not in response.text


def test_data_science_card_collections_match_the_selected_source_state() -> None:
    """Catch cards or covers copied from a different Coursera A/B state."""

    response = client.get("/browse/data-science")
    html = response.text

    assert response.status_code == 200

    trending = _section(html, "ds-trending-heading", "ds-core-heading")
    trending_titles = (
        "Introduction to AI",
        "Generative AI for Business Consultants",
        "Discover the Art of Prompting",
        "Generative AI Fundamentals",
    )
    _assert_in_order(trending, trending_titles)
    trending_cards = trending.split('<article class="ds-card ">')[1:]
    assert len(trending_cards) == 4
    for card, expected in zip(
        trending_cards,
        (
            (
                "Introduction to AI",
                "Google",
                "4.8 · 13K reviews",
                "Beginner · Course · 1 hour",
                "/learn/google-introduction-to-ai",
                "/static/browse/lower/trending-introduction-ai.jpg",
                "/static/browse/lower/logo-google.png",
            ),
            (
                "Generative AI for Business Consultants",
                "Fractal Analytics",
                "4.7 · 427 reviews",
                "Beginner · Specialization",
                "/specializations/generative-ai-for-business-consultants",
                "/static/data-science/trending-business-consultants.png",
                "/static/data-science/logo-fractal.png",
            ),
            (
                "Discover the Art of Prompting",
                "Google",
                "4.8 · 2.5K reviews",
                "Beginner · Course · 1 hour",
                "/learn/google-discover-the-art-of-prompting",
                "/static/data-science/trending-discover-prompting.png",
                "/static/browse/lower/logo-google.png",
            ),
            (
                "Generative AI Fundamentals",
                "IBM",
                "4.7 · 13K reviews",
                "Beginner · Specialization · 1 month",
                "/specializations/generative-ai-for-everyone",
                "/static/data-science/trending-generative-ai-fundamentals.png",
                "/static/browse/lower/logo-ibm.png",
            ),
        ),
        strict=True,
    ):
        for value in expected:
            assert value in card
        assert card.count('class="ds-card-badge"') == 1
    for provider in ("Google", "Fractal Analytics", "Google", "IBM"):
        assert provider in trending
    for rating in (
        "4.8 · 13K reviews",
        "4.7 · 427 reviews",
        "4.8 · 2.5K reviews",
        "4.7 · 13K reviews",
    ):
        assert rating in trending
    for meta in (
        "Beginner · Course · 1 hour",
        "Beginner · Specialization",
        "Beginner · Specialization · 1 month",
    ):
        assert meta in trending
    for href in (
        "/learn/google-introduction-to-ai",
        "/specializations/generative-ai-for-business-consultants",
        "/learn/google-discover-the-art-of-prompting",
        "/specializations/generative-ai-for-everyone",
    ):
        assert f'href="{href}"' in trending
    for image in (
        "/static/browse/lower/trending-introduction-ai.jpg",
        "/static/data-science/trending-business-consultants.png",
        "/static/data-science/trending-discover-prompting.png",
        "/static/data-science/trending-generative-ai-fundamentals.png",
    ):
        assert f'src="{image}"' in trending
    for logo in (
        "/static/browse/lower/logo-google.png",
        "/static/data-science/logo-fractal.png",
        "/static/browse/lower/logo-ibm.png",
    ):
        assert f'src="{logo}"' in trending
    assert trending.count('class="ds-card-badge"') == 4

    degrees = _section(html, "ds-degrees-heading", "ds-categories-heading")
    degree_titles = (
        "Master of Science in Data Analytics Engineering",
        "Master of Science in Data Science",
        "Master of Data Science",
        "Master of Science in Data Science (Statistics)",
    )
    _assert_in_order(degrees, degree_titles)
    _assert_in_order(
        degrees,
        (
            "Northeastern University",
            "University of Colorado Boulder",
            "University of Pittsburgh",
            "University of Leeds",
        ),
    )
    degree_cards = degrees.split('<article class="ds-card ">')[1:]
    assert len(degree_cards) == 4
    for card, expected in zip(
        degree_cards,
        (
            (
                "Master of Science in Data Analytics Engineering",
                "Northeastern University",
                "/degrees/ms-data-analytics-engineering-northeastern",
                "/static/data-science/degree-northeastern.png",
                "/static/browse/lower/logo-northeastern.jpg",
            ),
            (
                "Master of Science in Data Science",
                "University of Colorado Boulder",
                "/degrees/master-of-science-data-science-boulder",
                "/static/data-science/degree-colorado.png",
                "/static/data-science/logo-colorado.png",
            ),
            (
                "Master of Data Science",
                "University of Pittsburgh",
                "/degrees/master-of-data-science-university-of-pittsburgh",
                "/static/data-science/degree-pittsburgh.png",
                "/static/data-science/logo-pittsburgh.png",
            ),
            (
                "Master of Science in Data Science (Statistics)",
                "University of Leeds",
                "/degrees/msc-data-science-ul",
                "/static/data-science/degree-leeds.png",
                "/static/data-science/logo-leeds.png",
            ),
        ),
        strict=True,
    ):
        for value in expected:
            assert value in card
        assert "Earn a degree" in card
    for href in (
        "/degrees/ms-data-analytics-engineering-northeastern",
        "/degrees/master-of-science-data-science-boulder",
        "/degrees/master-of-data-science-university-of-pittsburgh",
        "/degrees/msc-data-science-ul",
    ):
        assert f'href="{href}"' in degrees
    for image in (
        "/static/data-science/degree-northeastern.png",
        "/static/data-science/degree-colorado.png",
        "/static/data-science/degree-pittsburgh.png",
        "/static/data-science/degree-leeds.png",
    ):
        assert f'src="{image}"' in degrees
    for logo in (
        "/static/browse/lower/logo-northeastern.jpg",
        "/static/data-science/logo-colorado.png",
        "/static/data-science/logo-pittsburgh.png",
        "/static/data-science/logo-leeds.png",
    ):
        assert f'src="{logo}"' in degrees
    assert degrees.count("Earn a degree") == 4
