"""Coursera-inspired WebsiteBench offline clone."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import checkout, learning_db
from catalog import load_catalog_seed
from websitebench.local_clone_auth import AuthError
from websitebench.site_backend import PaymentConflict, PaymentError, PaymentRejected


SITE_ID = "33"
DISPLAY_NAME = "Coursera"
STATIC_DIR = Path(__file__).resolve().parent / "static"
VERIFY_SESSION_TOKEN_ENV = "WEBSITEBENCH_VERIFY_SESSION_TOKEN"
VERIFY_SESSION_TOKEN_HEADER = "X-WebsiteBench-Verify-Token"

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
SUBJECT_SLUGS = {subject: slug for slug, subject in SUBJECTS.items()}

SUBJECT_ICONS = {
    "arts-and-humanities": "✎",
    "business": "▣",
    "computer-science": "‹›",
    "data-science": "↗",
    "health": "✚",
    "information-technology": "▰",
    "language-learning": "◎",
    "math-and-logic": "▦",
    "personal-development": "◇",
    "physical-science-and-engineering": "△",
    "social-sciences": "♧",
}

app = FastAPI(title=DISPLAY_NAME)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "font-src 'self'; script-src 'none'; connect-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def _header(*, authenticated: bool = False) -> str:
    account_controls = (
        '<div class="learner-nav"><a href="/my-learning">My Learning</a>'
        '<form class="header-logout" action="/auth/logout" method="post">'
        '<button type="submit">Log out</button></form></div>'
        if authenticated
        else '<a class="auth-placeholder" href="/login">Log In</a>'
        '<a class="join-placeholder" href="/signup">Join for Free</a>'
    )
    return f"""
<div class="audience-bar"><strong>For Individuals</strong><span>For Businesses</span><span>For Universities</span><span>For Governments</span></div>
<header class="site-header">
  <a class="wordmark" href="/" aria-label="Coursera home">coursera</a>
  <a class="nav-link" href="/browse">Explore <span aria-hidden="true">⌄</span></a>
  <span class="nav-link">Degrees</span>
  <form class="header-search" action="/search" method="get"><label class="sr-only" for="header-q">Search</label><input id="header-q" name="q" placeholder="What do you want to learn?"><button aria-label="Search">⌕</button></form>
  {account_controls}
</header>
"""


def _footer() -> str:
    return """
<footer><div><h2>Coursera</h2><a href="/browse">Catalog</a><a href="/about/contact">Contact</a></div><div><h2>Community</h2><span>Learners</span><span>Partners</span></div><div><h2>More</h2><a href="/help">Help</a><span>Terms</span><span>Privacy</span></div><p>© 2026 Coursera offline learning experience.</p></footer>
"""


def _request_authenticated(request: Request) -> bool:
    """Resolve only this request's existing site-bound session."""

    backend, auth = learning_db.services()
    cookie = backend.session_cookie
    session = auth.resolve_session(request.cookies.get(cookie["name"]))
    return bool(session and session["authenticated"])


def _page(
    request: Request,
    title: str,
    body: str,
    *,
    body_class: str = "",
    document_title: str | None = None,
) -> str:
    rendered_title = document_title or f"{title} | Coursera"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(rendered_title)}</title><link rel="stylesheet" href="/static/site.css"><link rel="stylesheet" href="/static/components.css"><link rel="stylesheet" href="/static/auth.css"><link rel="stylesheet" href="/static/checkout.css"></head>
<body class="{escape(body_class)}">{_header(authenticated=_request_authenticated(request))}<main>{body}</main>{_footer()}</body></html>"""


async def _form_values(request: Request) -> dict[str, str]:
    parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _request_session(request: Request):
    backend, auth = learning_db.services()
    cookie = backend.session_cookie
    token, session = auth.ensure_session(request.cookies.get(cookie["name"]))
    return backend, auth, token, session


def _set_session_cookie(response: Response, backend, token: str) -> None:
    cookie = dict(backend.session_cookie)
    name = cookie.pop("name")
    response.set_cookie(name, token, **cookie)


def _session_html(request: Request, title: str, body: str) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    response = HTMLResponse(_page(request, title, body))
    _set_session_cookie(response, backend, token)
    return response


def _auth_failure(request: Request, message: str, *, status_code: int) -> HTMLResponse:
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local account</p><h1>We couldn't continue</h1><p class="safe-note">{escape(message)}</p><a href="/login">Return to sign in</a></div></section>"""
    return HTMLResponse(_page(request, "Account action", body), status_code=status_code)


def _synthetic_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not normalized.endswith(".test"):
        raise ValueError("Use a synthetic .test address in this offline clone.")
    return normalized


def _safe_next_path(value: str | None) -> str:
    """Return one strictly local continuation or the learner dashboard."""

    fallback = "/my-learning"
    candidate = (value or "").strip()
    if not candidate or re.search(r"%(?![0-9A-Fa-f]{2})", candidate):
        return fallback
    try:
        parsed = urlsplit(candidate)
        decoded_path = unquote(parsed.path)
    except ValueError:
        return fallback
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(
            ord(character) < 32 or ord(character) == 127 for character in decoded_path
        )
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        return fallback
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))


def _authenticated_subject(request: Request):
    backend, auth, token, session = _request_session(request)
    if not session["authenticated"]:
        raise HTTPException(
            status_code=401, detail="Sign in with a local account to continue"
        )
    return backend, auth, token, str(session["account"]["subject_id"])


def _permission_page(request: Request, message: str) -> HTMLResponse:
    body = f"""<section class="not-found permission-prompt"><p class="eyebrow">Local account required</p><h1>{escape(message)}</h1><p>Sign in with a site-33 .test account. No source account is contacted.</p><a class="primary-button" href="/login">Sign in locally</a></section>"""
    return HTMLResponse(_page(request, "Sign in required", body), status_code=401)


def _enrollment_required_page(request: Request, message: str) -> HTMLResponse:
    body = f"""<section class="not-found permission-prompt"><p class="eyebrow">Active enrollment required</p><h1>{escape(message)}</h1><p>Select a local free or audit track, or complete the inferred sandbox checkout for paid access.</p><a class="primary-button" href="/specializations/deep-learning">Choose a local enrollment</a></section>"""
    return HTMLResponse(_page(request, "Enrollment required", body), status_code=403)


def _checkout_not_found(request: Request) -> HTMLResponse:
    body = """<section class="not-found"><h1>Checkout not found</h1><p>The checkout record is unavailable for this local learner.</p><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Checkout not found", body), status_code=404)


@app.post("/__websitebench/session", include_in_schema=False)
async def websitebench_session(request: Request) -> Response:
    """Open a verifier-owned fixture session using only its ephemeral token."""

    expected = os.environ.get(VERIFY_SESSION_TOKEN_ENV, "")
    if not expected:
        return Response(status_code=404)
    supplied = request.headers.get(VERIFY_SESSION_TOKEN_HEADER, "")
    if not hmac.compare_digest(supplied, expected):
        return Response(status_code=403)
    values = await _form_values(request)
    aliases = {
        "empty-learner": "learner-empty",
        "progress-learner": "learner-in-progress",
    }
    subject_id = aliases.get(values.get("account", ""))
    if set(values) != {"account"} or subject_id is None:
        return Response(status_code=400)
    account = next(
        record
        for record in learning_db.SEED_ACCOUNTS
        if record["subject_id"] == subject_id
    )
    backend, auth, token, _session = _request_session(request)
    signed_in = auth.sign_in(
        token,
        email=str(account["email"]),
        password=str(account["password"]),
    )
    response = Response(status_code=204)
    _set_session_cookie(response, backend, str(signed_in["session_token"]))
    return response


def _order_not_found(request: Request) -> HTMLResponse:
    body = """<section class="not-found"><h1>Order not found</h1><p>The order record is unavailable for this local learner.</p><a href="/orders">Back to order history</a></section>"""
    return HTMLResponse(_page(request, "Order not found", body), status_code=404)


def _checkout_validation(
    request: Request, message: str, *, status_code: int = 422
) -> HTMLResponse:
    body = f"""<section class="not-found"><p class="eyebrow">Safe local checkout</p><h1>Checkout could not continue</h1><p>{escape(message)}</p><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Checkout validation", body), status_code=status_code)


def _checkout_totals() -> str:
    return """<dl class="checkout-totals"><div><dt>Subtotal</dt><dd>USD 49.00</dd></div><div><dt>Tax</dt><dd>USD 0.00</dd></div><div class="checkout-total"><dt>Total</dt><dd>USD 49.00</dd></div></dl>"""


def _order_rows(records: list[dict[str, Any]]) -> str:
    if not records:
        return """<div class="empty-state"><h2>No local orders yet</h2><p>Approved sandbox checkouts will appear here.</p><a href="/specializations/deep-learning">Back to Deep Learning</a></div>"""
    return "".join(
        f"""<article class="catalog-card order-card" data-order-status="{escape(str(record["status"]))}"><p class="eyebrow">{escape(str(record["status"]).title())}</p><h2>Deep Learning Specialization</h2><p>Order {escape(str(record["order_id"]))}</p><p>Inferred total: USD 49.00</p><a href="/orders/{escape(str(record["order_id"]))}">View order detail</a></article>"""
        for record in records
    )


async def _exact_checkout_attempt_values(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type != "application/x-www-form-urlencoded":
        raise ValueError("Submit exactly scenario_id and idempotency_key.")
    try:
        pairs = parse_qsl(
            (await request.body()).decode("utf-8"), keep_blank_values=True
        )
    except UnicodeDecodeError as exc:
        raise ValueError("Submit exactly scenario_id and idempotency_key.") from exc
    if len(pairs) != 2 or {key for key, _value in pairs} != {
        "scenario_id",
        "idempotency_key",
    }:
        raise ValueError("Submit exactly scenario_id and idempotency_key.")
    return dict(pairs)


def _learning_not_found(request: Request) -> HTMLResponse:
    body = """<section class="not-found"><p class="error-code">404</p><h1>Learning item not found</h1><p>The item is unavailable for this local learner.</p><a class="primary-button" href="/my-learning">Return to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Learning item not found", body), status_code=404)


def _enrollment_rows(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<div class="empty-state"><h2>No local enrollments yet</h2><a href="/specializations/deep-learning">Explore Deep Learning</a></div>'
    rows = []
    for record in records:
        course_id = str(record["course_id"])
        catalog_record = _record_by_id(course_id)
        course_title = (
            str(catalog_record["title"])
            if catalog_record is not None
            else "Unavailable course"
        )
        course_href = (
            "/learn/neural-networks-deep-learning/lesson/lesson-neural-intro"
            if course_id == learning_db.COURSE_ID
            else f"/learn/{escape(course_id)}"
        )
        paid = record["track"] == "paid"
        if paid and record.get("order_id"):
            cancellation = f'<a href="/orders/{escape(str(record["order_id"]))}">Manage paid order</a>'
            origin = "Created by an approved local-sandbox checkout."
        else:
            cancellation = (
                f'<form action="/enrollments/{record["enrollment_id"]}/cancel" method="post"><button type="submit">Cancel enrollment</button></form>'
                if record["status"] == "active"
                else ""
            )
            origin = "No checkout or payment was created."
        rows.append(
            f"""<article class="catalog-card enrollment-card" data-enrollment-id="{record["enrollment_id"]}"><p class="eyebrow">{escape(str(record["status"]).title())}</p><h2>{escape(course_title)}</h2><p>{escape(str(record["track"]).title())} track</p>{"<p>Previously canceled; the local enrollment was reactivated.</p>" if record["status"] == "active" and record["canceled_at"] else ""}<p>{origin}</p>{cancellation}<a href="{course_href}">Open course</a></article>"""
        )
    return "".join(rows)


@app.exception_handler(404)
async def branded_not_found(request: Request, _exception: Exception) -> HTMLResponse:
    body = """<section class="not-found"><p class="error-code">404</p><h1>We couldn't find that page</h1><p>The page may have moved, but your offline learning path is still available.</p><div><a class="primary-button" href="/browse">Browse the catalog</a><a class="secondary-button" href="/search">Search courses</a><a class="secondary-button" href="/">Return home</a></div></section>"""
    return HTMLResponse(_page(request, "Page not found", body), status_code=404)


def _record_href(record: dict[str, Any]) -> str:
    if record["type"] == "specialization":
        return "/specializations/deep-learning"
    return f"/learn/{record['id']}"


_EVIDENCE_NOTES = {
    "structural-only": (
        "Only the public course structure was observed; displayed details are "
        "a deterministic offline simulation."
    ),
    "inferred-architecture": (
        "Course architecture was inferred; displayed details are a deterministic "
        "offline simulation."
    ),
    "truthful-simulation": (
        "Displayed catalog details are a deterministic offline simulation, "
        "not verified source facts."
    ),
}

_SERIES_EVIDENCE_NOTES = {
    "structural-only": "Source-observed course structure; displayed details are simulated.",
    "inferred-architecture": "Inferred course structure; displayed details are simulated.",
    "truthful-simulation": "Course and displayed details are an offline simulation.",
}

_CARD_EVIDENCE_NOTES = {
    "structural-only": "Evidence: public structure observed; details simulated.",
    "inferred-architecture": "Evidence: architecture inferred; details simulated.",
    "truthful-simulation": "Evidence: offline simulation; not source-verified.",
}


def _evidence_note(record: dict[str, Any], *, compact: bool = False) -> str:
    classification = record["source_evidence_classification"]
    if classification == "directly-observed":
        return ""
    if compact:
        message = _SERIES_EVIDENCE_NOTES[classification]
    else:
        message = _EVIDENCE_NOTES[classification]
    return (
        f'<p class="evidence-note" data-evidence-classification="{escape(classification)}">'
        f"{escape(message)}</p>"
    )


def _card_evidence_note(record: dict[str, Any]) -> str:
    classification = record["source_evidence_classification"]
    if classification == "directly-observed":
        return ""
    return (
        f'<p class="evidence-note" data-evidence-classification="{escape(classification)}">'
        f"{escape(_CARD_EVIDENCE_NOTES[classification])}</p>"
    )


def _card(record: dict[str, Any]) -> str:
    return f"""
<article class="catalog-card" data-catalog-record="{escape(record["id"])}">
  <div class="card-art" aria-hidden="true"><span>{escape(record["subject"][0])}</span></div>
  <p class="provider">{escape(record["provider"])}</p>
  <h2><a href="{escape(_record_href(record))}">{escape(record["title"])}</a></h2>
  <p class="rating">★ {record["rating"]:.1f} · Offline reviews</p>
  <p>{escape(record["level"])} · {escape(record["type"].title())} · {escape(record["duration"])}</p>
  {_card_evidence_note(record)}
</article>"""


def _card_grid(records: list[dict[str, Any]]) -> str:
    return (
        '<div class="card-grid">'
        + "".join(_card(record) for record in records)
        + "</div>"
    )


def _category_pills() -> str:
    return (
        '<nav class="category-pills" aria-label="Browse subjects">'
        + "".join(
            f'<a href="/browse/{slug}"><span aria-hidden="true">{SUBJECT_ICONS[slug]}</span>{escape(subject)}</a>'
            for slug, subject in SUBJECTS.items()
        )
        + "</nav>"
    )


def _option(value: str, label: str, selected: str) -> str:
    chosen = " selected" if value == selected else ""
    return f'<option value="{escape(value)}"{chosen}>{escape(label)}</option>'


def _select(name: str, label: str, values: list[str], selected: str) -> str:
    options = [_option("", f"All {label.casefold()}", selected)]
    options.extend(_option(value, value, selected) for value in values)
    return f'<label>{escape(label)}<select name="{name}">{"".join(options)}</select></label>'


def _filter_catalog(
    *,
    q: str,
    category: str,
    level: str,
    topic: str,
    duration: str,
    rating: float | None,
    language: str,
    schedule: str,
    sort: str,
) -> list[dict[str, Any]]:
    records = load_catalog_seed()
    query = q.strip().casefold()
    topic_query = topic.strip().casefold()
    subject = SUBJECTS.get(category)

    def matches(record: dict[str, Any]) -> bool:
        searchable = " ".join(
            [
                record["title"],
                record["topic"],
                record["subject"],
                record["provider"],
                *record["instructors"],
            ]
        ).casefold()
        return (
            (not query or query in searchable)
            and (not category or subject == record["subject"])
            and (not level or level.casefold() == record["level"].casefold())
            and (not topic_query or topic_query in record["topic"].casefold())
            and (not duration or duration.casefold() == record["duration"].casefold())
            and (rating is None or record["rating"] >= rating)
            and (not language or language.casefold() == record["language"].casefold())
            and (not schedule or schedule.casefold() == record["schedule"].casefold())
        )

    filtered = [record for record in records if matches(record)]
    if sort == "rating-desc":
        filtered.sort(key=lambda record: -record["rating"])
    elif sort == "title-desc":
        filtered.sort(key=lambda record: record["title"].casefold(), reverse=True)
    else:
        filtered.sort(key=lambda record: record["title"].casefold())
    return filtered


def _record_by_id(record_id: str) -> dict[str, Any] | None:
    return next(
        (record for record in load_catalog_seed() if record["id"] == record_id),
        None,
    )


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "site_id": SITE_ID}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> str:
    catalog = load_catalog_seed()
    body = f"""
<section class="home-hero"><div><p class="eyebrow">Professional learning for everyone</p><h1>Learn without limits</h1><p>Build skills with flexible, offline courses and a deterministic local learning experience.</p><a class="primary-button" href="/browse">Explore the catalog</a></div><img src="/static/hero-learning.svg" alt="Learners building new skills"></section>
<section class="section"><p class="eyebrow">New and popular</p><h2>Courses and specializations for your goals</h2>{_card_grid(catalog[:8])}</section>
<section class="subject-band"><h2>Explore by subject</h2>{_category_pills()}</section>
<section class="auth-hash-panel" id="login"><h2>Log in to continue learning</h2><p>This public entry does not accept credentials yet.</p><a class="primary-button" href="/login">Open standalone login</a><a class="close-link" href="#top">Close</a></section>
<section class="auth-hash-panel" id="signup"><h2>Join Coursera locally</h2><p>Review the offline account fields and verification guidance.</p><a class="primary-button" href="/signup">Open standalone signup</a><a class="close-link" href="#top">Close</a></section>"""
    return _page(
        request,
        "Online Courses, Certificates, & Degrees",
        body,
        body_class="home",
        document_title="Coursera | Online Courses, Certificates, & Degrees",
    )


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request) -> str:
    catalog = load_catalog_seed()
    popular_ids = (
        "business-strategy",
        "deep-learning-specialization",
        "cybersecurity",
        "tech-support",
    )
    popular_records = [
        record
        for record_id in popular_ids
        if (record := _record_by_id(record_id)) is not None
    ]
    remaining_records = [
        record for record in catalog if record["id"] not in popular_ids
    ]
    popular_filters = """<nav class="popular-filters" aria-label="Most popular categories"><strong>All</strong><a href="/browse/business">Business</a><a href="/browse/data-science">Data Science</a><a href="/browse/information-technology">Information Technology</a><a href="/browse/computer-science">Computer Science</a></nav>"""
    popular = (
        '<div class="card-grid popular-grid">'
        + "".join(_card(record) for record in popular_records)
        + '</div><details class="more-popular"><summary>Show 8 more</summary><div class="card-grid expanded-popular-grid">'
        + "".join(_card(record) for record in remaining_records[:8])
        + "</div></details>"
    )
    roles = """<section class="browse-roles"><div class="role-filters"><strong>Level: Beginner</strong><span>Popular</span><span>Software Engineering &amp; IT</span><span>Business</span><span>Sales &amp; Marketing</span></div><h2>Explore roles</h2><p>Find deterministic offline learning paths by role and skill.</p></section>"""
    body = f"""<section class="page-heading browse-heading"><h1>Explore Categories</h1>{_category_pills()}</section><section class="section popular-section"><h2>Most popular</h2>{popular_filters}{popular}</section>{roles}"""
    return _page(
        request,
        "Online Course Catalog by Topic and Skill",
        body,
        body_class="browse-page",
    )


@app.get("/browse/{category}", response_class=HTMLResponse)
def browse_category(request: Request, category: str) -> str:
    subject = SUBJECTS.get(category)
    if subject is None:
        raise HTTPException(status_code=404)
    records = [record for record in load_catalog_seed() if record["subject"] == subject]
    body = f"""<nav class="breadcrumbs"><a href="/browse">Browse</a><span>›</span>{escape(subject)}</nav><section class="page-heading"><h1>{escape(subject)}</h1><p>Explore flexible courses and build practical skills at your own pace.</p></section><section class="section"><h2>Most popular</h2>{_card_grid(records)}</section>"""
    return _page(request, f"{subject} Online Courses", body)


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    category: str = "",
    level: str = "",
    topic: str = "",
    duration: str = "",
    rating: float | None = None,
    language: str = "",
    schedule: str = "",
    sort: str = "title-asc",
) -> str:
    catalog = load_catalog_seed()
    records = _filter_catalog(
        q=q,
        category=category,
        level=level,
        topic=topic,
        duration=duration,
        rating=rating,
        language=language,
        schedule=schedule,
        sort=sort,
    )
    rating_value = "" if rating is None else f"{rating:g}"
    form = f"""
<form class="filters" action="/search" method="get">
  <label class="search-wide">Search<input name="q" value="{escape(q)}" placeholder="Course, topic, or skill"></label>
  {_select("category", "Category", list(SUBJECTS), category)}
  {_select("level", "Level", ["Beginner", "Intermediate", "Advanced", "Mixed"], level)}
  <label>Topic<input name="topic" value="{escape(topic)}" placeholder="e.g. Neural"></label>
  {_select("duration", "Duration", sorted({record["duration"] for record in catalog}), duration)}
  {_select("rating", "Rating", ["4.5", "4.7", "4.8", "4.9"], rating_value)}
  {_select("language", "Language", sorted({record["language"] for record in catalog}), language)}
  {_select("schedule", "Schedule", sorted({record["schedule"] for record in catalog}), schedule)}
  <label>Sort<select name="sort">{_option("title-asc", "Title A–Z", sort)}{_option("title-desc", "Title Z–A", sort)}{_option("rating-desc", "Highest rated", sort)}</select></label>
  <button class="primary-button" type="submit">Show results</button>
</form>"""
    if records:
        result_body = _card_grid(records)
    else:
        clear_query = urlencode({"q": ""})
        result_body = f"""<div class="empty-state"><h2>No results for “{escape(q)}”</h2><p>Try a broader term or remove a filter.</p><a href="/search?{clear_query}">Clear search</a><a href="/search">Reset all filters</a><a href="/browse">Browse available categories</a></div>"""
    body = f"""<section class="page-heading search-heading"><p class="eyebrow">Coursera catalog</p><h1>Search learning opportunities</h1></section><section class="search-layout">{form}<div class="results" data-result-count="{len(records)}"><h2>{len(records)} results</h2>{result_body}</div></section>"""
    return _page(
        request,
        "Search",
        body,
        document_title=(
            "Coursera | Online Courses From Top Universities. Join for Free"
        ),
    )


@app.get("/specializations/deep-learning", response_class=HTMLResponse)
def deep_learning_specialization(request: Request) -> str:
    specialization = _record_by_id("deep-learning-specialization")
    if specialization is None:
        raise HTTPException(status_code=404)
    components = [
        record
        for record in load_catalog_seed()
        if record.get("parent_specialization_id") == specialization["id"]
    ]
    course_list = "".join(
        f"""<li><span class="course-number">{index}</span><div><p>Course {index}</p><h3><a href="/learn/{escape(record["id"])}">{escape(record["title"])}</a></h3><p>{escape(record["duration"])} · {escape(record["level"])}</p>{_evidence_note(record, compact=True)}</div></li>"""
        for index, record in enumerate(components, start=1)
    )
    _backend, _auth, _token, session = _request_session(request)
    enrollment_action = (
        """<div class="enrollment-actions"><form class="enrollment-options" action="/enrollments" method="post"><input type="hidden" name="course_id" value="deep-learning-specialization"><label>Enrollment track<select name="track" required><option value="free">Free track</option><option value="audit">Audit track</option></select></label><button class="secondary-button" type="submit">Save free or audit enrollment</button></form><a class="primary-button" href="/checkout/deep-learning">Choose inferred paid plan</a><p>The paid plan opens a deterministic local-sandbox checkout. No real payment occurs.</p></div>"""
        if session["authenticated"]
        else '<div class="enrollment-actions"><a class="primary-button" href="/login?next=/checkout/deep-learning">Sign in locally to choose the inferred paid plan</a><a class="secondary-button" href="/login?next=/specializations/deep-learning">Sign in for free or audit enrollment</a></div>'
    )
    body = f"""
<nav class="breadcrumbs"><a href="/browse">Browse</a><span>›</span><a href="/browse/data-science">Data Science</a><span>›</span>Deep Learning</nav>
<section class="program-hero"><div><p class="provider">DeepLearning.AI</p><h1>Deep Learning Specialization</h1><p class="lead">Become a Machine Learning expert. Master the fundamentals of deep learning and break into AI.</p><p>Instructors: <strong>Andrew Ng +2 more</strong> <span class="badge">Top Instructor</span></p>{enrollment_action}</div><img src="/static/deep-learning-mark.svg" alt="Deep Learning program mark"></section>
<section class="program-facts"><div><strong>5 course series</strong><span>Get in-depth knowledge of a subject</span></div><div><strong>4.8 ★</strong><span>from 147,224 reviews</span></div><div><strong>Intermediate level</strong><span>Recommended experience</span></div><div><strong>Flexible schedule</strong><span>3 months at 10 hours a week</span></div></section>
<section class="detail-section"><h2>What you'll learn</h2><p>Build and train deep neural networks, analyze model performance, and apply convolutional and sequence models to practical tasks.</p><h2>Courses</h2><ol class="course-series">{course_list}</ol></section>"""
    return _page(
        request,
        "Deep Learning Specialization",
        body,
    )


@app.get("/checkout/deep-learning", response_class=HTMLResponse)
def checkout_plan(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, _subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before choosing a checkout plan")
    body = f"""<nav class="breadcrumbs"><a href="/specializations/deep-learning">Deep Learning Specialization</a><span>›</span>Plan</nav><section class="checkout-shell"><p class="eyebrow">Inferred local price</p><h1>Choose the Deep Learning paid plan</h1><p class="safe-note">Authenticated source checkout evidence is unavailable. This USD 49.00 price is explicitly inferred for the deterministic offline clone.</p>{_checkout_totals()}<p><strong>No real purchase or payment will occur.</strong> The generated site backend uses only the local-sandbox adapter.</p><form action="/checkout/deep-learning" method="post"><input type="hidden" name="course_id" value="deep-learning-specialization"><input type="hidden" name="plan_id" value="deep-learning-specialization-paid"><button class="primary-button" type="submit">Continue to synthetic payment</button></form><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Deep Learning checkout plan", body))


@app.post("/checkout/deep-learning")
async def create_checkout(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before starting checkout")
    values = await _form_values(request)
    try:
        draft = checkout.create_draft(
            subject,
            course_id=values.get("course_id", ""),
            plan_id=values.get("plan_id", ""),
        )
    except ValueError as exc:
        return _checkout_validation(request, str(exc))
    return RedirectResponse(f"/checkout/{draft['draft_id']}/payment", status_code=303)


@app.get("/checkout/{draft_id}/payment", response_class=HTMLResponse)
def checkout_payment(request: Request, draft_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to open this synthetic payment page")
    try:
        checkout.get_draft(subject, draft_id)
    except LookupError:
        return _checkout_not_found(request)
    body = f"""<nav class="breadcrumbs"><a href="/checkout/deep-learning">Plan</a><span>›</span>Synthetic payment</nav><section class="checkout-shell"><p class="eyebrow">Memory-only demonstration</p><h1>Synthetic payment form</h1><p class="safe-note"><strong>Do not enter real payment data.</strong> Anything typed below stays only in this browser page and has no submitted field name.</p><form class="synthetic-payment" action="/checkout/{escape(draft_id)}/review" method="get" autocomplete="off"><label>Example card number<input id="synthetic-card-number" inputmode="numeric" autocomplete="off" placeholder="Synthetic digits only"></label><label>Example expiry<input id="synthetic-expiry" autocomplete="off" placeholder="MM / YY"></label><label>Example security code<input id="synthetic-cvv" inputmode="numeric" autocomplete="off" placeholder="Synthetic code"></label><button class="primary-button" type="submit">Continue without submitting these fields</button></form><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Synthetic payment", body))


@app.get("/checkout/{draft_id}/review", response_class=HTMLResponse)
def checkout_review(request: Request, draft_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to review this checkout")
    try:
        checkout.get_draft(subject, draft_id)
    except LookupError:
        return _checkout_not_found(request)
    idempotency_key = f"browser-attempt:{secrets.token_urlsafe(18)}"
    body = f"""<nav class="breadcrumbs"><a href="/checkout/{escape(draft_id)}/payment">Synthetic payment</a><span>›</span>Review</nav><section class="checkout-shell"><p class="eyebrow">Local sandbox only</p><h1>Review inferred total</h1><p>This price is inferred and this action has no external or real payment effect.</p>{_checkout_totals()}<form class="sandbox-scenarios" action="/checkout/{escape(draft_id)}/attempt" method="post"><input type="hidden" name="idempotency_key" value="{escape(idempotency_key)}"><fieldset><legend>Choose a deterministic sandbox result</legend><label><input type="radio" name="scenario_id" value="sandbox-approved" required>Simulated approval</label><label><input type="radio" name="scenario_id" value="sandbox-declined" required>Simulated decline</label><label><input type="radio" name="scenario_id" value="sandbox-retry" required>Simulated retry</label></fieldset><button class="primary-button" type="submit">Run local sandbox attempt</button></form><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Review local checkout", body))


@app.post("/checkout/{draft_id}/attempt")
async def checkout_attempt(request: Request, draft_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to submit this local checkout")
    try:
        values = await _exact_checkout_attempt_values(request)
    except ValueError as exc:
        return _checkout_validation(request, str(exc))
    if values["scenario_id"] not in {
        "sandbox-approved",
        "sandbox-declined",
        "sandbox-retry",
    }:
        return _checkout_validation(request, "Choose one available sandbox scenario.")
    try:
        result = checkout.attempt(
            subject,
            draft_id,
            scenario_id=values["scenario_id"],
            idempotency_key=values["idempotency_key"],
        )
    except LookupError:
        return _checkout_not_found(request)
    except PaymentConflict as exc:
        return _checkout_validation(request, str(exc), status_code=409)
    except PaymentRejected as exc:
        return _checkout_validation(request, str(exc), status_code=409)
    except PaymentError as exc:
        return _checkout_validation(request, str(exc))
    if result["outcome"] == "approved":
        return RedirectResponse(
            f"/orders/{result['order']['order_id']}", status_code=303
        )
    heading = (
        "Simulated payment declined"
        if result["outcome"] == "declined"
        else "Simulated payment needs a retry"
    )
    body = f"""<section class="checkout-shell"><p class="eyebrow">Local sandbox result</p><h1>{heading}</h1><p>No order or paid enrollment was created. No external payment was attempted.</p><a class="primary-button" href="/checkout/{escape(draft_id)}/review">Try another sandbox result</a><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Local sandbox result", body))


@app.get("/learn/{course_id}/preview", response_class=HTMLResponse)
def course_preview(request: Request, course_id: str) -> str:
    record = _record_by_id(course_id)
    if record is None or record["type"] != "course":
        raise HTTPException(status_code=404)
    first_lesson = record["syllabus"][0]
    body = f"""<nav class="breadcrumbs"><a href="/learn/{escape(course_id)}">{escape(record["title"])}</a><span>›</span>Preview</nav><section class="preview-shell"><p class="eyebrow">No enrollment required</p><h1>Free preview: {escape(record["title"])}</h1>{_evidence_note(record)}<div class="lesson-player"><span aria-hidden="true">▶</span><div><h2>{escape(first_lesson)}</h2><p>This deterministic offline sample introduces the core ideas and provides a short guided practice activity. Your preview does not create progress or contact any external service.</p></div></div><a class="secondary-button" href="/learn/{escape(course_id)}">Back to course details</a></section>"""
    return _page(request, f"Free preview: {record['title']}", body)


@app.get("/learn/{course_id}", response_class=HTMLResponse)
def course_detail(request: Request, course_id: str) -> str:
    record = _record_by_id(course_id)
    if record is None or record["type"] != "course":
        raise HTTPException(status_code=404)
    syllabus = "".join(f"<li>{escape(item)}</li>" for item in record["syllabus"])
    instructors = ", ".join(escape(item) for item in record["instructors"])
    tracks = "".join(f"<li>{escape(item)}</li>" for item in record["enrollment_tracks"])
    subject_slug = SUBJECT_SLUGS[record["subject"]]
    specialization_membership = (
        '<p>This course is part of the <a href="/specializations/deep-learning">'
        "Deep Learning Specialization</a></p>"
        if record.get("parent_specialization_id") == "deep-learning-specialization"
        else ""
    )
    enrollment_course_id = str(
        record.get("parent_specialization_id") or record["id"]
    )
    _backend, _auth, _token, session = _request_session(request)
    enrollment_action = (
        f"""<form class="enrollment-options" action="/enrollments" method="post"><input type="hidden" name="course_id" value="{escape(enrollment_course_id)}"><label>Enrollment track<select name="track" required><option value="free">Free track</option><option value="audit">Audit track</option></select></label><button class="primary-button" type="submit">Enroll locally</button></form>"""
        if session["authenticated"]
        else f'<a class="primary-button" href="/login?next=/learn/{escape(record["id"])}">Enroll for free</a>'
    )
    body = f"""
<nav class="breadcrumbs"><a href="/browse">Browse</a><span>›</span><a href="/browse/{escape(subject_slug)}">{escape(record["subject"])}</a><span>›</span>{escape(record["title"])}</nav>
<section class="course-hero" data-course-detail="{escape(record["id"])}"><div><p class="eyebrow">{escape(record["provider"])}</p><h1>{escape(record["title"])}</h1>{specialization_membership}{_evidence_note(record)}<p><strong>★ {record["rating"]:.1f}</strong> · {escape(record["level"])} · {escape(record["duration"])} · {escape(record["schedule"])}</p>{enrollment_action}<a class="secondary-button" href="/learn/{escape(record["id"])}/preview">Preview course</a></div><div class="course-art">{escape(record["title"][0])}</div></section>
<section class="detail-grid"><article><h2>Syllabus</h2><ol>{syllabus}</ol></article><article><h2>Instructors</h2><p>{instructors}</p></article><article><h2>Prerequisites</h2><p>{escape(record["prerequisites"])}</p></article><article><h2>Reviews</h2><p>{escape(record["reviews_summary"])}</p></article><article><h2>Pricing</h2><p>{escape(record["pricing"])}</p></article><article><h2>Enrollment options</h2><ul>{tracks}</ul></article></section>"""
    return _page(request, record["title"], body)


def _auth_page(
    request: Request, kind: str, *, next_path: str = "/my-learning"
) -> str:
    if kind == "login":
        body = f"""
<section class="auth-shell"><div class="auth-card"><p class="eyebrow">Welcome back</p><h1>Log in to your Coursera account</h1><p class="safe-note" id="credential-note">This form does not submit credentials to Coursera or any external service. Use only synthetic .test account data.</p><form class="auth-form" action="/auth/login" method="post" aria-describedby="credential-note" autocomplete="off"><input type="hidden" name="next" value="{escape(next_path)}"><label>Email<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>Password<input type="password" name="password" placeholder="Password" required></label><button type="submit">Log in locally</button></form><div class="identity-options"><a href="/auth/provider/google">Continue with Google</a><a href="/auth/provider/facebook">Continue with Facebook</a><a href="/auth/provider/apple">Continue with Apple</a></div><a href="/account-recovery">Forgot password?</a><p>New to Coursera? <a href="/signup">Sign up</a></p></div><aside><h2>Continue learning offline</h2><p>Sessions and learner data stay in the site-33 local database.</p></aside></section>"""
        return _page(request, "Login - Continue Learning", body)
    body = """
<section class="auth-shell"><div class="auth-card"><p class="eyebrow">Join for free</p><h1>Create your Coursera account</h1><p class="safe-note" id="signup-note">Use only synthetic .test data. Registration and its verification code remain in the branded site-33 local inbox.</p><form class="auth-form" action="/auth/registration/start" method="post" aria-describedby="signup-note" autocomplete="off"><label>Full name<input name="full_name" placeholder="Offline learner" required></label><label>Email<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>Password<input type="password" name="password" placeholder="Create a password" required></label><button type="submit">Join locally for free</button></form><div class="identity-options"><a href="/auth/provider/google">Continue with Google</a><a href="/auth/provider/facebook">Continue with Facebook</a><a href="/auth/provider/apple">Continue with Apple</a></div><p>A verification code appears only in the site-bound local outbox; no real email is sent.</p><p>By joining, you agree to the <a href="/help#terms">Terms of Use</a> and Privacy Notice.</p><p>Already have an account? <a href="/login">Log in</a></p></div><aside><h2>Learn without limits</h2><p>Account state remains isolated to this offline clone.</p></aside></section>"""
    return _page(request, "Signup - Start Learning", body)


@app.get("/login", response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    next_path = _safe_next_path(request.query_params.get("next"))
    response = HTMLResponse(
        _auth_page(
            request,
            "login",
            next_path=next_path,
        )
    )
    _set_session_cookie(response, backend, token)
    return response


@app.get("/signup", response_class=HTMLResponse)
def signup(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    response = HTMLResponse(_auth_page(request, "signup"))
    _set_session_cookie(response, backend, token)
    return response


@app.post("/auth/registration/start")
async def registration_start(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        email = _synthetic_email(values.get("email", ""))
        auth.start_registration(
            token,
            email=email,
            display_name=values.get("display_name", values.get("full_name", "")),
            password=values.get("password", ""),
        )
    except ValueError as exc:
        return _auth_failure(request, str(exc), status_code=422)
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=409)
    response = RedirectResponse("/local-inbox?purpose=registration", status_code=303)
    _set_session_cookie(response, backend, token)
    return response


@app.post("/auth/registration/verify")
async def registration_verify(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        auth.verify_registration_code(token, values.get("code", ""))
        completed = auth.complete_registration(
            token,
            subject_factory=learning_db.create_profile,
        )
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=400)
    response = RedirectResponse("/onboarding", status_code=303)
    _set_session_cookie(response, backend, str(completed["session_token"]))
    return response


@app.post("/auth/login")
async def auth_login(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        email = _synthetic_email(values.get("email", ""))
        signed_in = auth.sign_in(
            token,
            email=email,
            password=values.get("password", ""),
        )
    except (AuthError, ValueError) as exc:
        return _auth_failure(request, str(exc), status_code=401)
    response = RedirectResponse(_safe_next_path(values.get("next")), status_code=303)
    _set_session_cookie(response, backend, str(signed_in["session_token"]))
    return response


@app.post("/auth/logout")
def auth_logout(request: Request) -> Response:
    backend, auth = learning_db.services()
    cookie = backend.session_cookie
    auth.sign_out(request.cookies.get(cookie["name"]))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(
        cookie["name"],
        path="/",
        secure=True,
        httponly=True,
        samesite="Lax",
    )
    return response


@app.get("/auth/provider/{provider}", response_class=HTMLResponse)
def provider_boundary(request: Request, provider: str) -> str:
    labels = {"google": "Google", "facebook": "Facebook", "apple": "Apple"}
    label = labels.get(provider)
    if label is None:
        raise HTTPException(status_code=404)
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">{label}</p><h1>Offline identity boundary</h1><p>No external sign-in was opened. {label} identity is unavailable in this deterministic clone.</p><a href="/login">Use a local .test account</a></div></section>"""
    return _page(request, f"{label} offline boundary", body)


@app.get("/local-inbox", response_class=HTMLResponse)
def local_inbox(request: Request, purpose: str = "registration") -> HTMLResponse:
    if purpose not in {"registration", "password-reset"}:
        raise HTTPException(status_code=404)
    backend, auth, token, _session = _request_session(request)
    mail = auth.local_mail_for_session(token, purpose=purpose)
    if mail is None:
        content = "<p>No local message is available for this browser session.</p>"
    else:
        content = f"""<p>Template: {escape(str(mail["template"]))}</p><p class="verification-code" data-verification-code="{escape(str(mail["verification_code"]))}">{escape(str(mail["verification_code"]))}</p><form class="auth-form" action="{"/auth/registration/verify" if purpose == "registration" else "/auth/recovery/complete"}" method="post"><label>Verification code<input name="code" required></label>{'<label>New password<input type="password" name="new_password" required></label>' if purpose == "password-reset" else ""}<button type="submit">Verify locally</button></form>"""
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local outbox delivery</p><h1>Coursera local inbox</h1><p>No real email was sent. This message is visible only to the browser session that requested it.</p>{content}</div></section>"""
    response = HTMLResponse(_page(request, "Local inbox", body))
    if mail is not None:
        response.headers["X-Local-Inbox-Purpose"] = purpose
    _set_session_cookie(response, backend, token)
    return response


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request) -> str:
    _backend, _auth, _token, _subject = _authenticated_subject(request)
    body = """<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local learner profile</p><h1>Tell us about your learning goals</h1><form class="auth-form" action="/onboarding" method="post"><label>Current role<input name="current_role" required></label><label>Learning goal<input name="learning_goal" required></label><button type="submit">Save local profile</button></form></div></section>"""
    return _page(request, "Learner onboarding", body)


@app.post("/onboarding")
async def save_onboarding(request: Request) -> Response:
    _backend, _auth, _token, subject = _authenticated_subject(request)
    values = await _form_values(request)
    try:
        learning_db.update_profile(
            subject,
            current_role=values.get("current_role", ""),
            learning_goal=values.get("learning_goal", ""),
        )
    except ValueError as exc:
        return _auth_failure(request, str(exc), status_code=422)
    return RedirectResponse("/my-learning", status_code=303)


@app.get("/my-learning", response_class=HTMLResponse)
def my_learning(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view My Learning")
    enrollments = learning_db.list_enrollments(subject)
    learning_tools = ""
    if learning_db.has_active_enrollment(subject):
        state = learning_db.learning_state(subject)
        certificate = (
            "Certificate available"
            if state["certificate_available"]
            else "Certificate available after all lessons and quizzes"
        )
        review = learning_db.get_review(subject, "deep-learning-specialization")
        current_rating = int(review["rating"]) if review else 5
        current_review = str(review["review_text"]) if review else ""
        rating_options = "".join(
            f'<option value="{rating}"{" selected" if rating == current_rating else ""}>{rating} stars</option>'
            for rating in range(1, 6)
        )
        learning_tools = f"""<a data-resume-lesson="{escape(state["resume_lesson_id"])}" href="/learn/neural-networks-deep-learning/lesson/{escape(state["resume_lesson_id"])}">Resume course</a><p>{certificate}</p><section class="auth-shell single"><div class="auth-card"><h2>Course review</h2><p>Your single local review can be updated at any time.</p><form class="auth-form" action="/learning/review" method="post"><label>Rating<select name="rating" required>{rating_options}</select></label><label>Review<textarea name="review_text" required>{escape(current_review)}</textarea></label><button type="submit">Save local review</button></form></div></section>"""
    body = f"""<section class="page-heading"><p class="eyebrow">Site-33 learner</p><h1>My Learning</h1><p>Your enrollments, progress, and bookmarks stay in this offline clone.</p>{learning_tools}</section><section class="section"><div class="card-grid">{_enrollment_rows(enrollments)}</div></section><p><a href="/account/preferences">Learning preferences</a> · <a href="/account/history">Enrollment history</a> · <a href="/orders">Order history</a></p><form action="/auth/logout" method="post"><button type="submit">Log out</button></form>"""
    return HTMLResponse(_page(request, "My Learning", body))


@app.get("/account/history", response_class=HTMLResponse)
def account_history(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view enrollment history")
    body = f"""<section class="page-heading"><p class="eyebrow">Local account history</p><h1>Enrollment history</h1><p>Canceled items remain visible and private to their owner.</p></section><section class="section"><div class="card-grid">{_enrollment_rows(learning_db.list_enrollments(subject))}</div><a href="/orders">View order history</a> · <a href="/my-learning">Back to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Enrollment history", body))


@app.get("/orders", response_class=HTMLResponse)
def order_history(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view order history")
    records = checkout.list_orders(subject)
    body = f"""<section class="page-heading"><p class="eyebrow">Owner-private local history</p><h1>Order history</h1><p>Only approved local-sandbox checkouts create durable orders. Canceled snapshots remain visible.</p></section><section class="section"><div class="card-grid">{_order_rows(records)}</div><a href="/my-learning">Back to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Order history", body))


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view this order")
    try:
        order = checkout.get_order(subject, order_id)
    except LookupError:
        return _order_not_found(request)
    cancellation = (
        f"""<form action="/orders/{escape(order_id)}/cancel" method="post"><button type="submit">Cancel paid enrollment</button></form>"""
        if order["status"] == "PAID"
        else "<p>This order and its paid enrollment were canceled; the immutable snapshot remains in history.</p>"
    )
    body = f"""<nav class="breadcrumbs"><a href="/orders">Order history</a><span>›</span>{escape(order_id)}</nav><section class="checkout-shell" data-order-status="{escape(str(order["status"]))}"><p class="eyebrow">Local sandbox order</p><h1>{escape(str(order["status"]).title())}</h1><p>Order {escape(order_id)}</p><p>Deep Learning Specialization · {escape(str(order["plan_label"]))}</p><p class="safe-note">This is an immutable simulation snapshot. No real payment or external purchase occurred.</p>{_checkout_totals()}{cancellation}<a href="/orders">Back to order history</a><a href="/specializations/deep-learning">Back to Deep Learning collection</a></section>"""
    return HTMLResponse(_page(request, "Order detail", body))


@app.post("/orders/{order_id}/cancel")
def cancel_order(request: Request, order_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before canceling this order")
    try:
        checkout.cancel_order(subject, order_id)
    except LookupError:
        return _order_not_found(request)
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@app.post("/enrollments")
async def create_enrollment(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before enrolling")
    values = await _form_values(request)
    try:
        learning_db.enroll(
            subject,
            course_id=values.get("course_id", ""),
            track=values.get("track", ""),
        )
    except ValueError as exc:
        return HTMLResponse(
            _page(
                request,
                "Enrollment validation",
                f'<section class="not-found"><h1>Check enrollment choices</h1><p>{escape(str(exc))}</p></section>',
            ),
            status_code=422,
        )
    return RedirectResponse("/my-learning", status_code=303)


@app.post("/enrollments/{enrollment_id}/cancel")
def cancel_enrollment(request: Request, enrollment_id: int) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before changing enrollment")
    try:
        learning_db.cancel_enrollment(subject, enrollment_id)
    except LookupError:
        return HTMLResponse(
            _page(
                request,
                "Enrollment not found",
                '<section class="not-found"><h1>Enrollment not found</h1><p>The record is unavailable for this local learner.</p></section>',
            ),
            status_code=404,
        )
    except ValueError:
        try:
            order = checkout.get_order_for_enrollment(subject, enrollment_id)
        except LookupError:
            return RedirectResponse("/orders", status_code=303)
        return RedirectResponse(f"/orders/{order['order_id']}", status_code=303)
    return RedirectResponse("/account/history", status_code=303)


@app.get(
    "/learn/neural-networks-deep-learning/lesson/{lesson_id}",
    response_class=HTMLResponse,
)
def learning_lesson(request: Request, lesson_id: str) -> HTMLResponse:
    try:
        lesson = learning_db.get_lesson(lesson_id)
    except LookupError:
        raise HTTPException(status_code=404) from None
    backend, auth, token, session = _request_session(request)
    if not session["authenticated"] and not lesson["preview"]:
        return _permission_page(request, "Sign in to open this lesson")
    subject = (
        str(session["account"]["subject_id"]) if session["authenticated"] else None
    )
    active_enrollment = bool(subject and learning_db.has_active_enrollment(subject))
    if not lesson["preview"] and not active_enrollment:
        return _enrollment_required_page(request, "Enroll locally to open this lesson")
    state = learning_db.learning_state(subject) if active_enrollment else None
    previous_link = (
        f'<a href="/learn/neural-networks-deep-learning/lesson/{escape(lesson["previous_lesson_id"])}">Previous lesson</a>'
        if lesson["previous_lesson_id"]
        else ""
    )
    next_link = (
        f'<a href="/learn/neural-networks-deep-learning/lesson/{escape(lesson["next_lesson_id"])}">Next lesson</a>'
        if lesson["next_lesson_id"]
        else ""
    )
    outline = "".join(
        f"<li><strong>{escape(module['title'])}</strong><ul>"
        + "".join(
            f'<li><a href="/learn/neural-networks-deep-learning/lesson/{escape(item["lesson_id"])}">{escape(item["title"])}</a></li>'
            for item in module["lessons"]
        )
        + "</ul></li>"
        for module in lesson["outline"]
    )
    learner_controls = ""
    if active_enrollment:
        bookmarked = lesson_id in state["bookmarks"]
        choices = "".join(
            f'<label><input type="radio" name="answer" value="{escape(choice)}" required>{escape(choice)}</label>'
            for choice in json.loads(str(lesson["quiz"]["choices_json"]))
        )
        learner_controls = f"""<div class="lesson-actions"><form action="/learning/bookmarks/{escape(lesson_id)}" method="post"><input type="hidden" name="bookmarked" value="{"0" if bookmarked else "1"}"><button type="submit">{"Remove bookmark" if bookmarked else "Bookmark lesson"}</button></form><form action="/learning/progress/{escape(lesson_id)}" method="post"><button type="submit">Mark complete</button></form></div><section><h2>{escape(lesson["quiz"]["title"])}</h2><p>{escape(lesson["quiz"]["question"])}</p><form class="auth-form" action="/learning/quizzes/{escape(lesson["quiz"]["quiz_id"])}" method="post">{choices}<button type="submit">Submit local quiz</button></form></section>"""
    else:
        learner_controls = '<p class="safe-note">Public offline preview. Sign in locally to save progress.</p>'
    body = f"""<nav class="breadcrumbs"><a href="/my-learning">My Learning</a><span>›</span>{escape(lesson["module_title"])}</nav><section class="lesson-layout"><aside><h2>Course outline</h2><ol>{outline}</ol></aside><article><p class="eyebrow">Module {lesson["module_position"]} of 3</p><h1>{escape(lesson["title"])}</h1><p>{escape(lesson["body"])}</p><nav>{previous_link} {next_link}</nav>{learner_controls}</article></section>"""
    response = HTMLResponse(_page(request, lesson["title"], body))
    _set_session_cookie(response, backend, token)
    return response


@app.post("/learning/bookmarks/{lesson_id}")
async def learning_bookmark(request: Request, lesson_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to save bookmarks")
    values = await _form_values(request)
    try:
        learning_db.set_bookmark(
            subject, lesson_id, bookmarked=values.get("bookmarked") == "1"
        )
    except LookupError:
        return _learning_not_found(request)
    return RedirectResponse(
        f"/learn/neural-networks-deep-learning/lesson/{lesson_id}", status_code=303
    )


@app.post("/learning/progress/{lesson_id}")
def learning_progress(request: Request, lesson_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to save progress")
    try:
        learning_db.complete_lesson(subject, lesson_id)
    except LookupError:
        return _learning_not_found(request)
    return RedirectResponse("/my-learning", status_code=303)


@app.post("/learning/quizzes/{quiz_id}", response_class=HTMLResponse)
async def learning_quiz(request: Request, quiz_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to submit a quiz")
    values = await _form_values(request)
    try:
        attempt = learning_db.submit_quiz(subject, quiz_id, values.get("answer", ""))
    except LookupError:
        return _learning_not_found(request)
    except ValueError as exc:
        return HTMLResponse(
            _page(
                request,
                "Quiz validation",
                f"<section class='not-found'><h1>Check your answer</h1><p>{escape(str(exc))}</p></section>",
                authenticated=True,
            ),
            status_code=422,
        )
    body = f"""<section class="page-heading"><p class="eyebrow">Local quiz feedback</p><h1>Quiz score: {attempt["score"]}</h1><p>{escape(attempt["feedback"])}</p><a href="/my-learning">Return to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Quiz feedback", body))


@app.post("/learning/review")
async def learning_review(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to save an offline review")
    values = await _form_values(request)
    try:
        learning_db.upsert_review(
            subject,
            rating=int(values.get("rating", "0")),
            review_text=values.get("review_text", ""),
        )
    except LookupError:
        return _learning_not_found(request)
    except (ValueError, TypeError) as exc:
        return HTMLResponse(
            _page(
                request,
                "Review validation",
                f"<section class='not-found'><h1>Check your review</h1><p>{escape(str(exc))}</p></section>",
                authenticated=True,
            ),
            status_code=422,
        )
    return RedirectResponse("/my-learning", status_code=303)


@app.get("/account/preferences", response_class=HTMLResponse)
def account_preferences(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to manage learning preferences")
    preferences = learning_db.get_preferences(subject)
    checked = " checked" if preferences["email_updates"] else ""
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local learning settings</p><h1>Learning preferences</h1><form class="auth-form" action="/account/preferences" method="post"><label>Language<input name="language" value="{escape(preferences["language"])}" required></label><label>Timezone<input name="timezone" value="{escape(preferences["timezone"])}" required></label><label><input type="checkbox" name="email_updates" value="1"{checked}>Local learning reminders</label><button type="submit">Save preferences</button></form></div></section>"""
    return HTMLResponse(_page(request, "Learning preferences", body))


@app.post("/account/preferences")
async def save_preferences(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to manage learning preferences")
    values = await _form_values(request)
    try:
        learning_db.update_preferences(
            subject,
            language=values.get("language", ""),
            timezone=values.get("timezone", ""),
            email_updates=values.get("email_updates") == "1",
        )
    except ValueError as exc:
        return HTMLResponse(
            _page(
                request,
                "Preference validation",
                f"<section class='not-found'><h1>Check preferences</h1><p>{escape(str(exc))}</p></section>",
                authenticated=True,
            ),
            status_code=422,
        )
    return RedirectResponse("/account/preferences", status_code=303)


@app.get("/account-recovery", response_class=HTMLResponse)
def account_recovery(request: Request) -> HTMLResponse:
    body = """<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Account access</p><h1>Reset your password</h1><p>No reset message is sent externally. Use only a synthetic .test address; the public response does not reveal whether it exists.</p><form class="auth-form" action="/auth/recovery/start" method="post" autocomplete="off"><label>Account email<input type="email" name="address" placeholder="learner@coursera.test" required></label><p class="field-guidance">A matching site-33 account receives a code only in this browser's local inbox.</p><button type="submit">Open local recovery</button></form><a href="/login">Return to sign in</a></div></section>"""
    return _session_html(request, "Password Recovery", body)


@app.post("/auth/recovery/start")
async def recovery_start(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        email = _synthetic_email(values.get("email", values.get("address", "")))
        auth.start_password_reset(token, email=email)
    except ValueError as exc:
        return _auth_failure(request, str(exc), status_code=422)
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=429)
    response = RedirectResponse("/local-inbox?purpose=password-reset", status_code=303)
    response.headers["X-Auth-Message"] = (
        "If a matching local account exists, a local verification message is available."
    )
    _set_session_cookie(response, backend, token)
    return response


@app.post("/auth/recovery/complete")
async def recovery_complete(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        auth.verify_password_reset_code(token, values.get("code", ""))
        new_token = auth.complete_password_reset(
            token,
            new_password=values.get("new_password", ""),
        )
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=400)
    response = RedirectResponse("/my-learning", status_code=303)
    _set_session_cookie(response, backend, new_token)
    return response


@app.get("/help", response_class=HTMLResponse)
def help_center(request: Request) -> str:
    body = """<section class="page-heading help-hero"><p class="eyebrow">Public support</p><h1>Learner Help Center</h1><p>Find safe, local guidance without opening an external support origin.</p></section><section class="support-grid"><article><h2>Courses and enrollment</h2><p>Browse categories, search learning opportunities, preview courses, and understand offline enrollment options.</p><a href="/browse">Browse the catalog</a></article><article><h2>Account access</h2><p>Review sign-in, registration, and password-recovery guidance. Never enter real credentials in this offline fixture.</p><a href="/login">Account access help</a></article><article><h2>Failed actions</h2><p>Clear filters, recover from missing pages, and return safely to available public records.</p><a href="/search">Search again</a></article><article id="terms"><h2>Terms of Use</h2><p>This is a deterministic WebsiteBench offline reconstruction with no publication, legal, or source-account effect.</p></article></section>"""
    return _page(request, "Learner Help Center", body)


@app.get("/about/contact", response_class=HTMLResponse)
def contact(request: Request) -> str:
    body = """<section class="page-heading contact-hero"><p class="eyebrow">Coursera support</p><h1>Contact Us</h1><p>Choose the local guidance area that best fits your question.</p></section><section class="support-grid"><article><h2>Learner Support</h2><p>Get local help with finding courses, previewing materials, and account-entry guidance.</p><a href="/help">Open learner help</a></article><article><h2>Inquiries</h2><p>General questions are represented as offline guidance only; no message is transmitted.</p><a href="/browse">Explore available learning</a></article><article><h2>Partnerships</h2><p>Business, university, and government contact actions are outside this offline scope.</p><a href="/">Return home</a></article></section>"""
    return _page(request, "Contact", body)
