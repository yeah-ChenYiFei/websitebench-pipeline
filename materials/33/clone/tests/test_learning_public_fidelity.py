"""Current public learning-detail contracts at the selected source state."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_specialization_uses_current_source_enrollment_and_review_counts() -> None:
    """Catch stale counters retained from an earlier Coursera observation."""

    html = client.get("/specializations/deep-learning").text

    assert "Starts Aug 19" in html
    assert "997,307 already enrolled" in html
    assert "147,228 reviews of courses in this program" in html
    assert html.count('class="source-specialization-course"') == 5


def test_course_uses_current_source_enrollment_and_review_counts() -> None:
    """Catch the course hero and review summary disagreeing with current evidence."""

    html = client.get("/learn/neural-networks-deep-learning").text

    assert "Starts Aug 19" in html
    assert "1,539,730" in html
    assert "123,798 reviews" in html
    assert "Learner reviews" in html
    assert "Explore more from Machine Learning" in html


def test_public_detail_pages_do_not_advertise_an_unobserved_preview_route() -> None:
    """Catch the historical offline lesson fixture being presented as source fidelity."""

    for path in (
        "/specializations/deep-learning",
        "/learn/neural-networks-deep-learning",
        "/learn/ai-for-everyone",
    ):
        html = client.get(path).text
        assert "/preview" not in html
        assert "Public offline preview" not in html
        assert "Preview lesson" not in html

    assert client.get("/learn/neural-networks-deep-learning/preview").status_code == 404
