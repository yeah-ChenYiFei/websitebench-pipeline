"""Source-grounded rendering for Coursera's selected search experience."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape


_TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)


SEARCH_RESULTS: tuple[dict[str, Any], ...] = (
    {
        "title": "Deep Learning",
        "provider": "DeepLearning.AI",
        "provider_mark": "D",
        "provider_icon": "/static/deep-learning/provider-icon.png",
        "href": "/specializations/deep-learning",
        "image": "/static/search/deep-learning.png",
        "badges": ("Free Trial",),
        "skills": "Convolutional Neural Networks, Recurrent Neural Networks (RNNs),…",
        "rating": "4.8",
        "reviews": "147K reviews",
        "meta": "Intermediate · Specialization · 3 - 6 Months",
        "credential": True,
    },
    {
        "title": "Neural Networks and Deep Learning",
        "provider": "DeepLearning.AI",
        "provider_mark": "D",
        "provider_icon": "/static/deep-learning/provider-icon.png",
        "href": "/learn/neural-networks-deep-learning",
        "image": "/static/search/neural-networks.png",
        "badges": ("Free Trial",),
        "skills": "Deep Learning, Artificial Intelligence and Machine Learning (AI/ML),…",
        "rating": "4.9",
        "reviews": "124K reviews",
        "meta": "Intermediate · Course · 1 - 4 Weeks",
        "credential": False,
    },
    {
        "title": "IBM Deep Learning with PyTorch, Keras and Tensorflow",
        "starter_title": "IBM Deep Learning with PyTorch, Keras and…",
        "provider": "IBM",
        "provider_mark": "IBM",
        "provider_icons": ("/static/browse/lower/logo-ibm.png",),
        "href": "/professional-certificates/ibm-deep-learning-with-pytorch-keras-tensorflow",
        "image": "/static/search/ibm-deep-learning.jpg",
        "badges": ("Free Trial", "AI skills"),
        "skills": "PyTorch (Machine Learning Library), Model Optimization, Keras,…",
        "rating": "4.5",
        "reviews": "4.3K reviews",
        "meta": "Intermediate · Professional Certificate · 3 - 6 Months",
        "credential": False,
    },
    {
        "title": "PyTorch for Deep Learning",
        "provider": "DeepLearning.AI",
        "provider_mark": "D",
        "provider_icon": "/static/deep-learning/provider-icon.png",
        "href": "/professional-certificates/pytorch-for-deep-learning",
        "image": "/static/search/pytorch-cert.png",
        "badges": ("Free Trial", "AI skills"),
        "skills": "PyTorch (Machine Learning Library), Model Deployment, Hugging…",
        "rating": "4.8",
        "reviews": "122 reviews",
        "meta": "Intermediate · Professional Certificate · 1 - 3 Months",
        "credential": False,
    },
    {
        "title": "Machine Learning",
        "provider": "Multiple educators",
        "provider_mark": "D S",
        "provider_icons": (
            "/static/deep-learning/provider-icon.png",
            "/static/home/logo-stanford.avif",
        ),
        "href": "/specializations/machine-learning-introduction",
        "image": "/static/search/machine-learning.png",
        "badges": ("Free Trial",),
        "skills": "Unsupervised Learning, Supervised Learning, Model Training, Applied Machi…",
        "rating": "4.9",
        "reviews": "39K reviews",
        "meta": "Beginner · Specialization · 1 - 3 Months",
        "credential": False,
    },
    {
        "title": "Introduction to Deep Learning & Neural Networks with Keras",
        "provider": "IBM",
        "provider_mark": "IBM",
        "provider_icons": ("/static/browse/lower/logo-ibm.png",),
        "href": "/learn/introduction-to-deep-learning-with-keras",
        "image": "/static/search/keras.jpg",
        "badges": ("Free Trial",),
        "skills": "Keras (Neural Network Library), Deep Learning, Transfer Learning, Artificial…",
        "rating": "4.7",
        "reviews": "2.1K reviews",
        "meta": "Intermediate · Course · 1 - 3 Months",
        "credential": False,
    },
    {
        "title": "Deep Learning with PyTorch",
        "provider": "IBM",
        "provider_mark": "IBM",
        "provider_icons": ("/static/browse/lower/logo-ibm.png",),
        "href": "/search?query=Deep%20Learning%20with%20PyTorch",
        "image": "/static/search/ibm-pytorch.jpg",
        "badges": ("Free Trial",),
        "skills": "PyTorch (Machine Learning Library), Model Optimization, Transfer…",
        "rating": "4.6",
        "reviews": "104 reviews",
        "meta": "Intermediate · Course · 1 - 3 Months",
        "credential": False,
    },
    {
        "title": "IBM AI Engineering",
        "provider": "IBM",
        "provider_mark": "IBM",
        "provider_icons": ("/static/browse/lower/logo-ibm.png",),
        "href": "/professional-certificates/ai-engineer",
        "image": "/static/search/ibm-ai-engineering.png",
        "badges": ("Free Trial",),
        "skills": "Prompt Engineering, Apache Spark, Large Language Modeling,…",
        "rating": "4.6",
        "reviews": "22K reviews",
        "meta": "Intermediate · Professional Certificate · 3 - 6 Months",
        "credential": True,
    },
    {
        "title": "Deep Learning Engineering",
        "provider": "Coursera",
        "provider_mark": "C",
        "href": "/specializations/deep-learning-engineering",
        "image": "/static/search/deep-learning-engineering.jpg",
        "badges": ("Free Trial",),
        "skills": "Model Deployment, Fine-tuning, PyTorch (Machine Learning…",
        "rating": "",
        "reviews": "",
        "meta": "Advanced · Specialization · 1 - 3 Months",
        "credential": False,
    },
    {
        "title": "Deep Learning with Python: CNN, ANN & RNN",
        "provider": "EDUCBA",
        "provider_mark": "E",
        "href": "/specializations/deep-learning-python-cnn-ann-rnn",
        "image": "/static/search/educba-deep-learning.png",
        "badges": ("Free Trial",),
        "skills": "Model Evaluation, Convolutional Neural Networks, Model Training, Dat…",
        "rating": "4.6",
        "reviews": "49 reviews",
        "meta": "Beginner · Specialization · 1 - 3 Months",
        "credential": False,
    },
    {
        "title": "Learning Deep Learning",
        "provider": "Pearson",
        "provider_mark": "P",
        "href": "/specializations/pearson-learning-deep-learning-from-perception-to-large-language-models",
        "image": "/static/search/pearson-learning.jpg",
        "badges": ("Free Trial",),
        "skills": "Large Language Modeling, Deep Learning, Prompt Engineering,…",
        "rating": "",
        "reviews": "",
        "meta": "Intermediate · Specialization · 1 - 4 Weeks",
        "credential": False,
    },
    {
        "title": "Deep Learning",
        "provider": "Illinois Tech",
        "provider_mark": "I",
        "provider_icons": ("/static/home/logo-illinois.avif",),
        "href": "/search?query=Illinois%20Tech%20Deep%20Learning",
        "image": "/static/search/illinois-tech.jpg",
        "badges": ("Free Trial",),
        "skills": "Recurrent Neural Networks (RNNs), Deep Learning, Generative AI,…",
        "rating": "4.5",
        "reviews": "35 reviews",
        "meta": "Beginner · Course · 1 - 3 Months",
        "credential": True,
    },
)

_AI_STARTER_BEST_FOR: tuple[str, ...] = (
    "learners with 3-6 months availability, intermediate skill level, and those "
    "seeking specialization credentials eager to master deep learning",
    "learners with 1-4 weeks availability, intermediate experience, and those "
    "preferring focused courses ready to learn neural networks basics",
    "learners with 3-6 months availability, intermediate skill level, and those "
    "pursuing professional certificates looking to apply deep learning with "
    "popular libraries",
    "learners with 1-3 months availability, intermediate experience, and those "
    "seeking professional certificates eager to specialize in PyTorch for deep "
    "learning",
)

_CARD_EVIDENCE_NOTES = {
    "structural-only": "Evidence: public structure observed; details simulated.",
    "inferred-architecture": "Evidence: architecture inferred; details simulated.",
    "truthful-simulation": "Evidence: offline simulation; not source-verified.",
}


def _generic_result(record: dict[str, Any]) -> dict[str, Any]:
    record_id = str(record["id"])
    kind = str(record.get("type", "course"))
    classification = str(record["source_evidence_classification"])
    href = (
        f"/specializations/{record_id}"
        if kind == "specialization"
        else f"/learn/{record_id}"
    )
    return {
        "title": str(record["title"]),
        "provider": str(record["provider"]),
        "provider_mark": str(record["provider"])[0].upper(),
        "href": href,
        "image": "/static/search/deep-learning.png",
        "badges": ("Free Trial",),
        "skills": str(record.get("topic", "")),
        "rating": f"{float(record['rating']):g}",
        "reviews": str(record.get("reviews_summary", "")),
        "meta": f"{record['level']} · {kind.replace('-', ' ').title()} · {record['duration']}",
        "credential": False,
        "catalog_id": record_id,
        "evidence_classification": classification,
        "evidence_note": _CARD_EVIDENCE_NOTES.get(classification, ""),
    }


def render_search_body(
    *,
    query: str,
    filtered_records: list[dict[str, Any]],
    filters: dict[str, str],
    source_selected: bool,
    filter_options: dict[str, list[str]],
) -> str:
    """Render search without remote content or unsupported AI output."""

    results = (
        [dict(record, source_result=True) for record in SEARCH_RESULTS]
        if source_selected
        else [dict(_generic_result(record), source_result=False) for record in filtered_records]
    )
    template = _TEMPLATES.get_template("pages/search.html")
    ai_starter_cards = [
        dict(SEARCH_RESULTS[position], best_for=best_for)
        for position, best_for in enumerate(_AI_STARTER_BEST_FOR)
    ]
    return template.render(
        query=query,
        results=results,
        ai_starter_cards=ai_starter_cards,
        result_count=len(results),
        filters=filters,
        filters_active=any(
            value
            for key, value in filters.items()
            if key != "sort"
        )
        or filters.get("sort") not in {"", "best-match", "title-asc"},
        clear_filters_href=f"/search?query={quote(query)}",
        filter_options=filter_options,
        no_results=not results,
    )


def render_public_landing_body(
    *, title: str, description: str, cards: Iterable[object]
) -> str:
    """Render a source-path landing from existing source-backed card records."""

    rendered_cards: list[str] = []
    seen_hrefs: set[str] = set()
    for position, card in enumerate(cards):
        href = str(getattr(card, "href"))
        if not href.startswith("/") or href.startswith("//") or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        card_title = str(getattr(card, "title"))
        provider = str(getattr(card, "provider", ""))
        metadata = str(getattr(card, "metadata", ""))
        image = str(getattr(card, "image"))
        rendered_cards.append(
            f"""<article data-public-landing-record="{position}"><a class="source-learning-card" href="{escape(href, quote=True)}"><img class="source-card-image" src="{escape(image, quote=True)}" alt=""><span><small>{escape(provider)}</small><strong>{escape(card_title)}</strong><em>{escape(metadata)}</em></span></a></article>"""
        )
    if not rendered_cards:
        raise ValueError("public landing requires at least one source-backed record")
    return f"""
<section class="source-category-shell public-source-landing">
  <nav class="source-category-breadcrumb" aria-label="Breadcrumb"><a href="/browse">Browse</a><span aria-hidden="true">›</span><span>{escape(title)}</span></nav>
  <header class="source-category-hero"><div><h1>{escape(title)}</h1><p>{escape(description)}</p></div></header>
  <section aria-labelledby="public-landing-results"><h2 id="public-landing-results">Explore local learning records</h2><div class="source-mini-grid">{''.join(rendered_cards)}</div></section>
  <p><a href="/browse">Back to Browse</a></p>
</section>"""
