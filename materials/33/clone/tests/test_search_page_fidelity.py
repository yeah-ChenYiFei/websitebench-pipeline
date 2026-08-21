"""Source-fidelity contracts for Coursera's selected Deep Learning search."""

from __future__ import annotations

from html import unescape
import re

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)

EXPECTED_RESULTS = (
    ("Deep Learning", "DeepLearning.AI", "/specializations/deep-learning"),
    (
        "Neural Networks and Deep Learning",
        "DeepLearning.AI",
        "/learn/neural-networks-deep-learning",
    ),
    (
        "IBM Deep Learning with PyTorch, Keras and Tensorflow",
        "IBM",
        "/professional-certificates/ibm-deep-learning-with-pytorch-keras-tensorflow",
    ),
    (
        "PyTorch for Deep Learning",
        "DeepLearning.AI",
        "/professional-certificates/pytorch-for-deep-learning",
    ),
    (
        "Machine Learning",
        "Multiple educators",
        "/specializations/machine-learning-introduction",
    ),
    (
        "Introduction to Deep Learning & Neural Networks with Keras",
        "IBM",
        "/learn/introduction-to-deep-learning-with-keras",
    ),
    (
        "Deep Learning with PyTorch",
        "IBM",
        "/search?query=Deep%20Learning%20with%20PyTorch",
    ),
    ("IBM AI Engineering", "IBM", "/professional-certificates/ai-engineer"),
    (
        "Deep Learning Engineering",
        "Coursera",
        "/specializations/deep-learning-engineering",
    ),
    (
        "Deep Learning with Python: CNN, ANN & RNN",
        "EDUCBA",
        "/specializations/deep-learning-python-cnn-ann-rnn",
    ),
    (
        "Learning Deep Learning",
        "Pearson",
        "/specializations/pearson-learning-deep-learning-from-perception-to-large-language-models",
    ),
    (
        "Deep Learning",
        "Illinois Tech",
        "/search?query=Illinois%20Tech%20Deep%20Learning",
    ),
)


def _result_identity(tag: str) -> tuple[str, str, str]:
    def attribute(name: str) -> str:
        match = re.search(rf'{name}="([^"]*)"', tag)
        assert match is not None, (name, tag)
        return unescape(match.group(1))

    return (
        attribute("data-result-title"),
        attribute("data-result-provider"),
        attribute("href"),
    )


def _result_identities(html: str) -> tuple[tuple[str, str, str], ...]:
    tags = re.findall(
        r'<a class="search-result-card"[^>]*data-search-result="true"[^>]*>',
        html,
    )
    return tuple(_result_identity(tag) for tag in tags)


def test_deep_learning_search_preserves_source_order_and_selected_ai_state() -> None:
    """Catch a return to the stale loading experiment or substituted results."""

    response = client.get("/search", params={"query": "Deep Learning"})

    assert response.status_code == 200
    assert '<html lang="en">' in response.text
    assert _result_identities(response.text) == EXPECTED_RESULTS
    for copy in (
        "AI Overview",
        "Understanding deep learning and how to get started",
        "Deep learning is a subset of machine learning focused on neural networks",
        "Top courses to get started:",
        "You might follow up with...",
        "deep learning specialization",
        "deep learning with pytorch artificial intelligence and machine learning (ai/ml)",
        "deep learning.ai classification algorithms",
        "deep learning stanford university",
        "All Results",
        "What brings you to Coursera today?",
    ):
        assert copy in response.text
    for invented in (
        "AI 概览",
        "You are looking for",
        "This specialization covers",
        "您的隐私与本次聊天",
        "所有结果",
        "AI summary is loading...",
        "Ask me anything",
    ):
        assert invented not in response.text

    assert response.text.count('data-ai-starter-card="true"') == 4
    assert "IBM Deep Learning with PyTorch, Keras and…" in response.text
    for position, title in enumerate(
        (
            "Deep Learning",
            "Neural Networks and Deep Learning",
            "IBM Deep Learning with PyTorch, Keras and Tensorflow",
            "PyTorch for Deep Learning",
        ),
        start=1,
    ):
        assert (
            f'data-ai-starter-position="{position}" '
            f'data-ai-starter-title="{title}"'
        ) in response.text

    assert 'class="search-assistant-panel"' not in response.text
    assert 'class="search-assistant-composer"' not in response.text


def test_search_query_aliases_render_the_same_selected_state() -> None:
    """Catch the source `query` parameter diverging from the local `q` alias."""

    source_alias = client.get("/search", params={"query": "Deep Learning"}).text
    local_alias = client.get("/search", params={"q": "Deep Learning"}).text

    assert _result_identities(source_alias) == EXPECTED_RESULTS
    assert _result_identities(local_alias) == EXPECTED_RESULTS
    for html in (source_alias, local_alias):
        assert 'id="wb-header-search" name="q" value="deep learning"' in html


def test_impossible_query_has_english_recovery_without_fake_matches() -> None:
    """Catch an impossible query being padded with unrelated result cards."""

    html = client.get(
        "/search", params={"query": "zzzz-no-match-websitebench"}
    ).text

    assert 'data-result-count="0"' in html
    assert "No results for zzzz-no-match-websitebench" in html
    assert 'href="/search?query=Deep%20Learning"' in html
    assert 'href="/browse"' in html
    assert _result_identities(html) == ()


def test_filter_drawer_and_interstitial_match_the_observed_controls() -> None:
    """Catch the observed drawer being replaced by the old inline form."""

    html = client.get("/search", params={"query": "Deep Learning"}).text

    assert 'id="search-filter-open"' in html
    assert 'id="search-filter-drawer"' in html
    for label in (
        "Sort by",
        "Best Match",
        "Newest",
        "Topic",
        "Duration",
        "Learning Product",
        "Skills",
        "Language",
        "Level",
        "Educator",
        "Subtitles",
        "Hands-on Learning",
        "Tools",
        "View",
        "Clear all",
    ):
        assert label in html
    assert 'value="best-match" checked' in html
    assert 'data-search-filter-clear disabled' in html
    sixth = html.index('data-result-position="6"')
    interstitial = html.index("What brings you to Coursera today?")
    seventh = html.index('data-result-position="7"')
    assert sixth < interstitial < seventh


def test_result_cards_use_source_provider_marks_and_metadata_order() -> None:
    """Catch placeholder provider badges or degree metadata moving below facts."""

    html = client.get("/search", params={"query": "Deep Learning"}).text

    assert 'class="search-provider-logo"' in html
    assert 'class="search-ai-starter-provider-logo"' in html
    assert 'src="/static/deep-learning/provider-icon.png"' in html
    assert 'src="/static/browse/lower/logo-ibm.png"' in html

    first_card = html.split('data-result-position="1"', 1)[1].split(
        'data-result-position="2"', 1
    )[0]
    credential = first_card.index("Build toward a degree")
    rating = first_card.index("147K reviews")
    metadata = first_card.index("Intermediate · Specialization · 3 - 6 Months")
    assert credential < rating < metadata


def test_result_cards_use_the_observed_provider_identity_marks() -> None:
    """Catch generic letter tiles replacing the provider marks in source cards."""

    html = client.get("/search", params={"query": "Deep Learning"}).text

    ibm_card = html.split('data-result-position="3"', 1)[1].split(
        'data-result-position="4"', 1
    )[0]
    assert 'src="/static/browse/lower/logo-ibm.png"' in ibm_card

    multiple_educators = html.split('data-result-position="5"', 1)[1].split(
        'data-result-position="6"', 1
    )[0]
    assert multiple_educators.count('class="search-provider-logo"') == 2
    assert 'src="/static/deep-learning/provider-icon.png"' in multiple_educators
    assert 'src="/static/home/logo-stanford.avif"' in multiple_educators

    illinois_card = html.split('data-result-position="12"', 1)[1]
    assert 'src="/static/home/logo-illinois.avif"' in illinois_card
