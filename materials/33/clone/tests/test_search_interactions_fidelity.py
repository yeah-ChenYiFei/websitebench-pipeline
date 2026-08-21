"""Query-driven interaction contracts for the public search filter surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_combined_filters_remain_selected_and_can_be_cleared_to_the_query() -> None:
    """Catch filtering that loses active state or strands users without recovery."""

    html = client.get(
        "/search",
        params={
            "q": "Deep Learning",
            "category": "data-science",
            "level": "Intermediate",
            "topic": "deep learning",
            "duration": "3 months at 10 hours a week",
            "language": "English",
            "schedule": "Flexible schedule",
            "sort": "newest",
        },
    ).text

    for selected in (
        '<option value="data-science" selected>',
        '<option value="Intermediate" selected>',
        '<option value="3 months at 10 hours a week" selected>',
        '<option value="English" selected>',
        '<option value="Flexible schedule" selected>',
    ):
        assert selected in html
    assert 'name="topic" value="deep learning"' in html
    assert 'name="sort" value="newest" checked' in html
    assert 'name="sort" value="best-match" checked' not in html
    assert 'data-search-filter-clear href="/search?query=Deep%20Learning"' in html


def test_default_filter_view_keeps_clear_disabled() -> None:
    """Catch the source-observed default drawer exposing a false active state."""

    html = client.get("/search", params={"query": "Deep Learning"}).text

    assert 'name="sort" value="best-match" checked' in html
    assert 'data-search-filter-clear disabled' in html


def test_rating_filter_is_user_selectable_persistent_and_applied() -> None:
    response = client.get(
        "/search",
        params={"q": "Deep Learning", "rating": "4.8"},
    )

    assert response.status_code == 200
    assert '<select name="rating">' in response.text
    assert '<option value="4.8" selected>4.8 and above</option>' in response.text
    assert 'data-search-filter-clear href="/search?query=Deep%20Learning"' in response.text
    assert 'data-result-count="2"' in response.text
    assert 'data-catalog-record="deep-learning-specialization"' in response.text
    assert 'data-catalog-record="neural-networks-deep-learning"' in response.text
