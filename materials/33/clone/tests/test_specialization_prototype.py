from __future__ import annotations

import app as app_module


def test_specialization_route_renders_the_english_playwright_structure(
    monkeypatch,
) -> None:
    """Exercise the real route renderer without opening the slow site backend."""

    records = app_module.load_catalog_seed()
    specialization = next(
        record for record in records if record["id"] == "deep-learning-specialization"
    )
    monkeypatch.setattr(
        app_module,
        "_record_by_id",
        lambda record_id: specialization
        if record_id == "deep-learning-specialization"
        else None,
    )
    monkeypatch.setattr(app_module, "load_catalog_seed", lambda: records)
    monkeypatch.setattr(
        app_module.checkout,
        "plan",
        lambda: {
            "trial_days": 7,
            "renewal_minor": 19600,
            "renewal_currency": "CNY",
            "renewal_interval": "month",
        },
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

    html = app_module.deep_learning_specialization(object())

    assert 'class="source-specialization-hero"' in html
    assert "Become a Machine Learning expert." in html
    assert 'class="source-specialization-stats"' in html
    assert 'class="source-specialization-tabs"' in html
    assert html.count('class="source-specialization-course"') == 5
    assert "What you'll learn" in html
    assert "Skills you'll gain" in html
    assert "Details to know" in html
