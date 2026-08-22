from __future__ import annotations

import app as app_module
import ui


def test_course_detail_route_renders_the_english_playwright_structure(
    monkeypatch,
) -> None:
    """Catch the course page falling back to the old generic detail cards."""

    records = app_module.load_catalog_seed()
    course = next(
        record for record in records if record["id"] == "neural-networks-deep-learning"
    )
    monkeypatch.setattr(
        app_module,
        "_record_by_id",
        lambda record_id: course
        if record_id == "neural-networks-deep-learning"
        else None,
    )
    monkeypatch.setattr(
        app_module,
        "_request_session",
        lambda _request: (None, None, None, {"authenticated": False}),
    )
    monkeypatch.setattr(
        app_module,
        "_page",
        lambda _request, _title, body, **_kwargs: body,
    )

    html = app_module.course_detail(object(), "neural-networks-deep-learning")

    assert 'class="source-course-detail-hero"' in html
    assert "Neural Networks and Deep Learning" in html
    assert "This course is part of" in html
    assert 'class="source-course-detail-stats"' in html
    assert 'class="source-course-detail-tabs"' in html
    assert "Skills you'll gain" in html
    assert "Tools you'll learn" in html
    assert "Details to know" in html
    assert "Build your subject-matter expertise" in html
    assert html.count('class="source-course-module"') == 4
    assert "Introduction to Deep Learning" in html
    assert "Explore more from Machine Learning" in html
    assert html.count('class="source-related-course"') == 4
    assert "Learner reviews" in html
    assert html.count('class="source-course-review"') == 3
    assert "Frequently asked questions" in html
    assert "/static/deep-learning/instructor-andrew-ng.jpg" in html
    assert "/static/deep-learning/course-sequence-models.png" in html
    assert 'style="' not in html


def test_course_footer_renders_the_source_column_groups() -> None:
    """Catch the course page falling back to the compact generic footer."""

    html = ui.page(
        title="Neural Networks and Deep Learning",
        body="<section>Course</section>",
        authenticated=False,
        language="en",
        footer_variant="source-course",
    )

    assert 'class="wb-footer source-course-footer"' in html
    assert "Professional Certificates" in html
    assert "Courses &amp; Specializations" in html
    assert "Career Resources" in html
    assert "App Store" in html
    assert "Google Play" in html
