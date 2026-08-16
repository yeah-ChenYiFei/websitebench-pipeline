"""Coursera-inspired WebsiteBench offline clone."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import learning_db
from catalog import load_catalog_seed
from websitebench.local_clone_auth import AuthError


SITE_ID = "33"
DISPLAY_NAME = "Coursera"
STATIC_DIR = Path(__file__).resolve().parent / "static"

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


def _header() -> str:
    return """
<div class="audience-bar"><strong>For Individuals</strong><span>For Businesses</span><span>For Universities</span><span>For Governments</span></div>
<header class="site-header">
  <a class="wordmark" href="/" aria-label="Coursera home">coursera</a>
  <a class="nav-link" href="/browse">Explore <span aria-hidden="true">⌄</span></a>
  <span class="nav-link">Degrees</span>
  <form class="header-search" action="/search" method="get"><label class="sr-only" for="header-q">Search</label><input id="header-q" name="q" placeholder="What do you want to learn?"><button aria-label="Search">⌕</button></form>
  <a class="auth-placeholder" href="/#login">Log In</a><a class="join-placeholder" href="/#signup">Join for Free</a>
</header>
"""


def _footer() -> str:
    return """
<footer><div><h2>Coursera</h2><a href="/browse">Catalog</a><a href="/about/contact">Contact</a></div><div><h2>Community</h2><span>Learners</span><span>Partners</span></div><div><h2>More</h2><a href="/help">Help</a><span>Terms</span><span>Privacy</span></div><p>© 2026 Coursera offline learning experience.</p></footer>
"""


def _page(title: str, body: str, *, body_class: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | Coursera</title><link rel="stylesheet" href="/static/site.css"><link rel="stylesheet" href="/static/components.css"><link rel="stylesheet" href="/static/auth.css"></head>
<body class="{escape(body_class)}">{_header()}<main>{body}</main>{_footer()}</body></html>"""


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
    response = HTMLResponse(_page(title, body))
    _set_session_cookie(response, backend, token)
    return response


def _auth_failure(message: str, *, status_code: int) -> HTMLResponse:
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local account</p><h1>We couldn't continue</h1><p class="safe-note">{escape(message)}</p><a href="/login">Return to sign in</a></div></section>"""
    return HTMLResponse(_page("Account action", body), status_code=status_code)


def _synthetic_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not normalized.endswith(".test"):
        raise ValueError("Use a synthetic .test address in this offline clone.")
    return normalized


def _authenticated_subject(request: Request):
    backend, auth, token, session = _request_session(request)
    if not session["authenticated"]:
        raise HTTPException(status_code=401, detail="Sign in with a local account to continue")
    return backend, auth, token, str(session["account"]["subject_id"])


def _permission_page(message: str) -> HTMLResponse:
    body = f"""<section class="not-found permission-prompt"><p class="eyebrow">Local account required</p><h1>{escape(message)}</h1><p>Sign in with a site-33 .test account. No source account is contacted.</p><a class="primary-button" href="/login">Sign in locally</a></section>"""
    return HTMLResponse(_page("Sign in required", body), status_code=401)


def _enrollment_required_page(message: str) -> HTMLResponse:
    body = f"""<section class="not-found permission-prompt"><p class="eyebrow">Active enrollment required</p><h1>{escape(message)}</h1><p>Select a local free, audit, or paid track. No checkout or payment occurs.</p><a class="primary-button" href="/specializations/deep-learning">Choose a local enrollment</a></section>"""
    return HTMLResponse(_page("Enrollment required", body), status_code=403)


def _learning_not_found() -> HTMLResponse:
    body = """<section class="not-found"><p class="error-code">404</p><h1>Learning item not found</h1><p>The item is unavailable for this local learner.</p><a class="primary-button" href="/my-learning">Return to My Learning</a></section>"""
    return HTMLResponse(_page("Learning item not found", body), status_code=404)


def _enrollment_rows(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<div class="empty-state"><h2>No local enrollments yet</h2><a href="/specializations/deep-learning">Explore Deep Learning</a></div>'
    return "".join(
        f"""<article class="catalog-card enrollment-card" data-enrollment-id="{record['enrollment_id']}"><p class="eyebrow">{escape(str(record['status']).title())}</p><h2>Deep Learning Specialization</h2><p>{escape(str(record['track']).title())} track</p>{'<p>Previously canceled; the local enrollment was reactivated.</p>' if record['status'] == 'active' and record['canceled_at'] else ''}<p>No checkout or payment was created.</p>{f'<form action="/enrollments/{record["enrollment_id"]}/cancel" method="post"><button type="submit">Cancel enrollment</button></form>' if record['status'] == 'active' else ''}<a href="/learn/neural-networks-deep-learning/lesson/lesson-neural-intro">Open course</a></article>"""
        for record in records
    )


@app.exception_handler(404)
async def branded_not_found(_request: Request, _exception: Exception) -> HTMLResponse:
    body = """<section class="not-found"><p class="error-code">404</p><h1>We couldn't find that page</h1><p>The page may have moved, but your offline learning path is still available.</p><div><a class="primary-button" href="/browse">Browse the catalog</a><a class="secondary-button" href="/search">Search courses</a><a class="secondary-button" href="/">Return home</a></div></section>"""
    return HTMLResponse(_page("Page not found", body), status_code=404)


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
<article class="catalog-card" data-catalog-record="{escape(record['id'])}">
  <div class="card-art" aria-hidden="true"><span>{escape(record['subject'][0])}</span></div>
  <p class="provider">{escape(record['provider'])}</p>
  <h2><a href="{escape(_record_href(record))}">{escape(record['title'])}</a></h2>
  <p class="rating">★ {record['rating']:.1f} · Offline reviews</p>
  <p>{escape(record['level'])} · {escape(record['type'].title())} · {escape(record['duration'])}</p>
  {_card_evidence_note(record)}
</article>"""


def _card_grid(records: list[dict[str, Any]]) -> str:
    return '<div class="card-grid">' + "".join(_card(record) for record in records) + "</div>"


def _category_pills() -> str:
    return '<nav class="category-pills" aria-label="Browse subjects">' + "".join(
        f'<a href="/browse/{slug}"><span aria-hidden="true">{SUBJECT_ICONS[slug]}</span>{escape(subject)}</a>'
        for slug, subject in SUBJECTS.items()
    ) + "</nav>"


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
def home() -> str:
    catalog = load_catalog_seed()
    body = f"""
<section class="home-hero"><div><p class="eyebrow">Professional learning for everyone</p><h1>Learn without limits</h1><p>Build skills with flexible, offline courses and a deterministic local learning experience.</p><a class="primary-button" href="/browse">Explore the catalog</a></div><img src="/static/hero-learning.svg" alt="Learners building new skills"></section>
<section class="section"><p class="eyebrow">New and popular</p><h2>Courses and specializations for your goals</h2>{_card_grid(catalog[:8])}</section>
<section class="subject-band"><h2>Explore by subject</h2>{_category_pills()}</section>
<section class="auth-hash-panel" id="login"><h2>Log in to continue learning</h2><p>This public entry does not accept credentials yet.</p><a class="primary-button" href="/login">Open standalone login</a><a class="close-link" href="#top">Close</a></section>
<section class="auth-hash-panel" id="signup"><h2>Join Coursera locally</h2><p>Review the offline account fields and verification guidance.</p><a class="primary-button" href="/signup">Open standalone signup</a><a class="close-link" href="#top">Close</a></section>"""
    return _page("Online Courses, Certificates, & Degrees", body, body_class="home")


@app.get("/browse", response_class=HTMLResponse)
def browse() -> str:
    catalog = load_catalog_seed()
    body = f"""<section class="page-heading"><h1>Explore Categories</h1>{_category_pills()}</section><section class="section"><h2>Most popular</h2>{_card_grid(catalog[:12])}</section>"""
    return _page("Online Course Catalog by Topic and Skill", body)


@app.get("/browse/{category}", response_class=HTMLResponse)
def browse_category(category: str) -> str:
    subject = SUBJECTS.get(category)
    if subject is None:
        raise HTTPException(status_code=404)
    records = [record for record in load_catalog_seed() if record["subject"] == subject]
    body = f"""<nav class="breadcrumbs"><a href="/browse">Browse</a><span>›</span>{escape(subject)}</nav><section class="page-heading"><h1>{escape(subject)}</h1><p>Explore flexible courses and build practical skills at your own pace.</p></section><section class="section"><h2>Most popular</h2>{_card_grid(records)}</section>"""
    return _page(f"{subject} Online Courses", body)


@app.get("/search", response_class=HTMLResponse)
def search(
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
    return _page("Search", body)


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
        f"""<li><span class="course-number">{index}</span><div><p>Course {index}</p><h3><a href="/learn/{escape(record['id'])}">{escape(record['title'])}</a></h3><p>{escape(record['duration'])} · {escape(record['level'])}</p>{_evidence_note(record, compact=True)}</div></li>"""
        for index, record in enumerate(components, start=1)
    )
    _backend, _auth, _token, session = _request_session(request)
    enrollment_action = (
        """<form class="enrollment-options" action="/enrollments" method="post"><input type="hidden" name="course_id" value="deep-learning-specialization"><label>Enrollment track<select name="track" required><option value="free">Free track</option><option value="audit">Audit track</option><option value="paid">Paid track selection</option></select></label><button class="primary-button" type="submit">Save local enrollment</button><p>No checkout or payment occurs in Task 4. Paid is only a local track selection.</p></form>"""
        if session["authenticated"]
        else '<a class="primary-button" href="/login?next=/specializations/deep-learning">Enroll for free</a>'
    )
    body = f"""
<nav class="breadcrumbs"><a href="/browse">Browse</a><span>›</span><a href="/browse/data-science">Data Science</a><span>›</span>Deep Learning</nav>
<section class="program-hero"><div><p class="provider">DeepLearning.AI</p><h1>Deep Learning Specialization</h1><p class="lead">Become a Machine Learning expert. Master the fundamentals of deep learning and break into AI.</p><p>Instructors: <strong>Andrew Ng +2 more</strong> <span class="badge">Top Instructor</span></p>{enrollment_action}</div><img src="/static/deep-learning-mark.svg" alt="Deep Learning program mark"></section>
<section class="program-facts"><div><strong>5 course series</strong><span>Get in-depth knowledge of a subject</span></div><div><strong>4.8 ★</strong><span>from 147,224 reviews</span></div><div><strong>Intermediate level</strong><span>Recommended experience</span></div><div><strong>Flexible schedule</strong><span>3 months at 10 hours a week</span></div></section>
<section class="detail-section"><h2>What you'll learn</h2><p>Build and train deep neural networks, analyze model performance, and apply convolutional and sequence models to practical tasks.</p><h2>Courses</h2><ol class="course-series">{course_list}</ol></section>"""
    return _page("Deep Learning Specialization", body)


@app.get("/learn/{course_id}/preview", response_class=HTMLResponse)
def course_preview(course_id: str) -> str:
    record = _record_by_id(course_id)
    if record is None or record["type"] != "course":
        raise HTTPException(status_code=404)
    first_lesson = record["syllabus"][0]
    body = f"""<nav class="breadcrumbs"><a href="/learn/{escape(course_id)}">{escape(record['title'])}</a><span>›</span>Preview</nav><section class="preview-shell"><p class="eyebrow">No enrollment required</p><h1>Free preview: {escape(record['title'])}</h1>{_evidence_note(record)}<div class="lesson-player"><span aria-hidden="true">▶</span><div><h2>{escape(first_lesson)}</h2><p>This deterministic offline sample introduces the core ideas and provides a short guided practice activity. Your preview does not create progress or contact any external service.</p></div></div><a class="secondary-button" href="/learn/{escape(course_id)}">Back to course details</a></section>"""
    return _page(f"Free preview: {record['title']}", body)


@app.get("/learn/{course_id}", response_class=HTMLResponse)
def course_detail(course_id: str) -> str:
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
    body = f"""
<nav class="breadcrumbs"><a href="/browse">Browse</a><span>›</span><a href="/browse/{escape(subject_slug)}">{escape(record['subject'])}</a><span>›</span>{escape(record['title'])}</nav>
<section class="course-hero" data-course-detail="{escape(record['id'])}"><div><p class="eyebrow">{escape(record['provider'])}</p><h1>{escape(record['title'])}</h1>{specialization_membership}{_evidence_note(record)}<p><strong>★ {record['rating']:.1f}</strong> · {escape(record['level'])} · {escape(record['duration'])} · {escape(record['schedule'])}</p><a class="primary-button" href="/login?next=/learn/{escape(record['id'])}">Enroll for free</a><a class="secondary-button" href="/learn/{escape(record['id'])}/preview">Preview course</a></div><div class="course-art">{escape(record['title'][0])}</div></section>
<section class="detail-grid"><article><h2>Syllabus</h2><ol>{syllabus}</ol></article><article><h2>Instructors</h2><p>{instructors}</p></article><article><h2>Prerequisites</h2><p>{escape(record['prerequisites'])}</p></article><article><h2>Reviews</h2><p>{escape(record['reviews_summary'])}</p></article><article><h2>Pricing</h2><p>{escape(record['pricing'])}</p></article><article><h2>Enrollment options</h2><ul>{tracks}</ul></article></section>"""
    return _page(record["title"], body)


def _auth_page(kind: str) -> str:
    if kind == "login":
        body = """
<section class="auth-shell"><div class="auth-card"><p class="eyebrow">Welcome back</p><h1>Log in to your Coursera account</h1><p class="safe-note" id="credential-note">This form does not submit credentials to Coursera or any external service. Use only synthetic .test account data.</p><form class="auth-form" action="/auth/login" method="post" aria-describedby="credential-note" autocomplete="off"><label>Email<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>Password<input type="password" name="password" placeholder="Password" required></label><button type="submit">Log in locally</button></form><div class="identity-options"><a href="/auth/provider/google">Continue with Google</a><a href="/auth/provider/facebook">Continue with Facebook</a><a href="/auth/provider/apple">Continue with Apple</a></div><a href="/account-recovery">Forgot password?</a><p>New to Coursera? <a href="/signup">Sign up</a></p></div><aside><h2>Continue learning offline</h2><p>Sessions and learner data stay in the site-33 local database.</p></aside></section>"""
        return _page("Login - Continue Learning", body)
    body = """
<section class="auth-shell"><div class="auth-card"><p class="eyebrow">Join for free</p><h1>Create your Coursera account</h1><p class="safe-note" id="signup-note">Use only synthetic .test data. Registration and its verification code remain in the branded site-33 local inbox.</p><form class="auth-form" action="/auth/registration/start" method="post" aria-describedby="signup-note" autocomplete="off"><label>Full name<input name="full_name" placeholder="Offline learner" required></label><label>Email<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>Password<input type="password" name="password" placeholder="Create a password" required></label><button type="submit">Join locally for free</button></form><div class="identity-options"><a href="/auth/provider/google">Continue with Google</a><a href="/auth/provider/facebook">Continue with Facebook</a><a href="/auth/provider/apple">Continue with Apple</a></div><p>A verification code appears only in the site-bound local outbox; no real email is sent.</p><p>By joining, you agree to the <a href="/help#terms">Terms of Use</a> and Privacy Notice.</p><p>Already have an account? <a href="/login">Log in</a></p></div><aside><h2>Learn without limits</h2><p>Account state remains isolated to this offline clone.</p></aside></section>"""
    return _page("Signup - Start Learning", body)


@app.get("/login", response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    response = HTMLResponse(_auth_page("login"))
    _set_session_cookie(response, backend, token)
    return response


@app.get("/signup", response_class=HTMLResponse)
def signup(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    response = HTMLResponse(_auth_page("signup"))
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
        return _auth_failure(str(exc), status_code=422)
    except AuthError as exc:
        return _auth_failure(str(exc), status_code=409)
    response = RedirectResponse(
        "/local-inbox?purpose=registration", status_code=303
    )
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
        return _auth_failure(str(exc), status_code=400)
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
        return _auth_failure(str(exc), status_code=401)
    response = RedirectResponse("/my-learning", status_code=303)
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
def provider_boundary(provider: str) -> str:
    labels = {"google": "Google", "facebook": "Facebook", "apple": "Apple"}
    label = labels.get(provider)
    if label is None:
        raise HTTPException(status_code=404)
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">{label}</p><h1>Offline identity boundary</h1><p>No external sign-in was opened. {label} identity is unavailable in this deterministic clone.</p><a href="/login">Use a local .test account</a></div></section>"""
    return _page(f"{label} offline boundary", body)


@app.get("/local-inbox", response_class=HTMLResponse)
def local_inbox(request: Request, purpose: str = "registration") -> HTMLResponse:
    if purpose not in {"registration", "password-reset"}:
        raise HTTPException(status_code=404)
    backend, auth, token, _session = _request_session(request)
    mail = auth.local_mail_for_session(token, purpose=purpose)
    if mail is None:
        content = "<p>No local message is available for this browser session.</p>"
    else:
        content = f"""<p>Template: {escape(str(mail['template']))}</p><p class="verification-code" data-verification-code="{escape(str(mail['verification_code']))}">{escape(str(mail['verification_code']))}</p><form class="auth-form" action="{'/auth/registration/verify' if purpose == 'registration' else '/auth/recovery/complete'}" method="post"><label>Verification code<input name="code" required></label>{'<label>New password<input type="password" name="new_password" required></label>' if purpose == 'password-reset' else ''}<button type="submit">Verify locally</button></form>"""
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local outbox delivery</p><h1>Coursera local inbox</h1><p>No real email was sent. This message is visible only to the browser session that requested it.</p>{content}</div></section>"""
    response = HTMLResponse(_page("Local inbox", body))
    _set_session_cookie(response, backend, token)
    return response


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request) -> str:
    _backend, _auth, _token, _subject = _authenticated_subject(request)
    body = """<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local learner profile</p><h1>Tell us about your learning goals</h1><form class="auth-form" action="/onboarding" method="post"><label>Current role<input name="current_role" required></label><label>Learning goal<input name="learning_goal" required></label><button type="submit">Save local profile</button></form></div></section>"""
    return _page("Learner onboarding", body)


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
        return _auth_failure(str(exc), status_code=422)
    return RedirectResponse("/my-learning", status_code=303)


@app.get("/my-learning", response_class=HTMLResponse)
def my_learning(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to view My Learning")
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
        learning_tools = f"""<a data-resume-lesson="{escape(state['resume_lesson_id'])}" href="/learn/neural-networks-deep-learning/lesson/{escape(state['resume_lesson_id'])}">Resume course</a><p>{certificate}</p><section class="auth-shell single"><div class="auth-card"><h2>Course review</h2><p>Your single local review can be updated at any time.</p><form class="auth-form" action="/learning/review" method="post"><label>Rating<select name="rating" required>{rating_options}</select></label><label>Review<textarea name="review_text" required>{escape(current_review)}</textarea></label><button type="submit">Save local review</button></form></div></section>"""
    body = f"""<section class="page-heading"><p class="eyebrow">Site-33 learner</p><h1>My Learning</h1><p>Your enrollments, progress, and bookmarks stay in this offline clone.</p>{learning_tools}</section><section class="section"><div class="card-grid">{_enrollment_rows(enrollments)}</div></section><p><a href="/account/preferences">Learning preferences</a> · <a href="/account/history">Enrollment history</a></p><form action="/auth/logout" method="post"><button type="submit">Log out</button></form>"""
    return HTMLResponse(_page("My Learning", body))


@app.get("/account/history", response_class=HTMLResponse)
def account_history(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to view enrollment history")
    body = f"""<section class="page-heading"><p class="eyebrow">Local account history</p><h1>Enrollment history</h1><p>Canceled items remain visible and private to their owner.</p></section><section class="section"><div class="card-grid">{_enrollment_rows(learning_db.list_enrollments(subject))}</div><a href="/my-learning">Back to My Learning</a></section>"""
    return HTMLResponse(_page("Enrollment history", body))


@app.post("/enrollments")
async def create_enrollment(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in before enrolling")
    values = await _form_values(request)
    try:
        learning_db.enroll(
            subject,
            course_id=values.get("course_id", ""),
            track=values.get("track", ""),
        )
    except ValueError as exc:
        return HTMLResponse(
            _page("Enrollment validation", f'<section class="not-found"><h1>Check enrollment choices</h1><p>{escape(str(exc))}</p></section>'),
            status_code=422,
        )
    return RedirectResponse("/my-learning", status_code=303)


@app.post("/enrollments/{enrollment_id}/cancel")
def cancel_enrollment(request: Request, enrollment_id: int) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in before changing enrollment")
    try:
        learning_db.cancel_enrollment(subject, enrollment_id)
    except LookupError:
        return HTMLResponse(
            _page("Enrollment not found", '<section class="not-found"><h1>Enrollment not found</h1><p>The record is unavailable for this local learner.</p></section>'),
            status_code=404,
        )
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
        return _permission_page("Sign in to open this lesson")
    subject = (
        str(session["account"]["subject_id"])
        if session["authenticated"]
        else None
    )
    active_enrollment = bool(subject and learning_db.has_active_enrollment(subject))
    if not lesson["preview"] and not active_enrollment:
        return _enrollment_required_page("Enroll locally to open this lesson")
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
        learner_controls = f"""<div class="lesson-actions"><form action="/learning/bookmarks/{escape(lesson_id)}" method="post"><input type="hidden" name="bookmarked" value="{'0' if bookmarked else '1'}"><button type="submit">{'Remove bookmark' if bookmarked else 'Bookmark lesson'}</button></form><form action="/learning/progress/{escape(lesson_id)}" method="post"><button type="submit">Mark complete</button></form></div><section><h2>{escape(lesson['quiz']['title'])}</h2><p>{escape(lesson['quiz']['question'])}</p><form class="auth-form" action="/learning/quizzes/{escape(lesson['quiz']['quiz_id'])}" method="post">{choices}<button type="submit">Submit local quiz</button></form></section>"""
    else:
        learner_controls = '<p class="safe-note">Public offline preview. Sign in locally to save progress.</p>'
    body = f"""<nav class="breadcrumbs"><a href="/my-learning">My Learning</a><span>›</span>{escape(lesson['module_title'])}</nav><section class="lesson-layout"><aside><h2>Course outline</h2><ol>{outline}</ol></aside><article><p class="eyebrow">Module {lesson['module_position']} of 3</p><h1>{escape(lesson['title'])}</h1><p>{escape(lesson['body'])}</p><nav>{previous_link} {next_link}</nav>{learner_controls}</article></section>"""
    response = HTMLResponse(_page(lesson["title"], body))
    _set_session_cookie(response, backend, token)
    return response


@app.post("/learning/bookmarks/{lesson_id}")
async def learning_bookmark(request: Request, lesson_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to save bookmarks")
    values = await _form_values(request)
    try:
        learning_db.set_bookmark(
            subject, lesson_id, bookmarked=values.get("bookmarked") == "1"
        )
    except LookupError:
        return _learning_not_found()
    return RedirectResponse(
        f"/learn/neural-networks-deep-learning/lesson/{lesson_id}", status_code=303
    )


@app.post("/learning/progress/{lesson_id}")
def learning_progress(request: Request, lesson_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to save progress")
    try:
        learning_db.complete_lesson(subject, lesson_id)
    except LookupError:
        return _learning_not_found()
    return RedirectResponse("/my-learning", status_code=303)


@app.post("/learning/quizzes/{quiz_id}", response_class=HTMLResponse)
async def learning_quiz(request: Request, quiz_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to submit a quiz")
    values = await _form_values(request)
    try:
        attempt = learning_db.submit_quiz(
            subject, quiz_id, values.get("answer", "")
        )
    except LookupError:
        return _learning_not_found()
    except ValueError as exc:
        return HTMLResponse(_page("Quiz validation", f"<section class='not-found'><h1>Check your answer</h1><p>{escape(str(exc))}</p></section>"), status_code=422)
    body = f"""<section class="page-heading"><p class="eyebrow">Local quiz feedback</p><h1>Quiz score: {attempt['score']}</h1><p>{escape(attempt['feedback'])}</p><a href="/my-learning">Return to My Learning</a></section>"""
    return HTMLResponse(_page("Quiz feedback", body))


@app.post("/learning/review")
async def learning_review(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to save an offline review")
    values = await _form_values(request)
    try:
        learning_db.upsert_review(
            subject,
            rating=int(values.get("rating", "0")),
            review_text=values.get("review_text", ""),
        )
    except LookupError:
        return _learning_not_found()
    except (ValueError, TypeError) as exc:
        return HTMLResponse(_page("Review validation", f"<section class='not-found'><h1>Check your review</h1><p>{escape(str(exc))}</p></section>"), status_code=422)
    return RedirectResponse("/my-learning", status_code=303)


@app.get("/account/preferences", response_class=HTMLResponse)
def account_preferences(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to manage learning preferences")
    preferences = learning_db.get_preferences(subject)
    checked = " checked" if preferences["email_updates"] else ""
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local learning settings</p><h1>Learning preferences</h1><form class="auth-form" action="/account/preferences" method="post"><label>Language<input name="language" value="{escape(preferences['language'])}" required></label><label>Timezone<input name="timezone" value="{escape(preferences['timezone'])}" required></label><label><input type="checkbox" name="email_updates" value="1"{checked}>Local learning reminders</label><button type="submit">Save preferences</button></form></div></section>"""
    return HTMLResponse(_page("Learning preferences", body))


@app.post("/account/preferences")
async def save_preferences(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page("Sign in to manage learning preferences")
    values = await _form_values(request)
    try:
        learning_db.update_preferences(
            subject,
            language=values.get("language", ""),
            timezone=values.get("timezone", ""),
            email_updates=values.get("email_updates") == "1",
        )
    except ValueError as exc:
        return HTMLResponse(_page("Preference validation", f"<section class='not-found'><h1>Check preferences</h1><p>{escape(str(exc))}</p></section>"), status_code=422)
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
        return _auth_failure(str(exc), status_code=422)
    except AuthError as exc:
        return _auth_failure(str(exc), status_code=429)
    response = RedirectResponse(
        "/local-inbox?purpose=password-reset", status_code=303
    )
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
        return _auth_failure(str(exc), status_code=400)
    response = RedirectResponse("/my-learning", status_code=303)
    _set_session_cookie(response, backend, new_token)
    return response


@app.get("/help", response_class=HTMLResponse)
def help_center() -> str:
    body = """<section class="page-heading help-hero"><p class="eyebrow">Public support</p><h1>Learner Help Center</h1><p>Find safe, local guidance without opening an external support origin.</p></section><section class="support-grid"><article><h2>Courses and enrollment</h2><p>Browse categories, search learning opportunities, preview courses, and understand offline enrollment options.</p><a href="/browse">Browse the catalog</a></article><article><h2>Account access</h2><p>Review sign-in, registration, and password-recovery guidance. Never enter real credentials in this offline fixture.</p><a href="/login">Account access help</a></article><article><h2>Failed actions</h2><p>Clear filters, recover from missing pages, and return safely to available public records.</p><a href="/search">Search again</a></article><article id="terms"><h2>Terms of Use</h2><p>This is a deterministic WebsiteBench offline reconstruction with no publication, legal, or source-account effect.</p></article></section>"""
    return _page("Learner Help Center", body)


@app.get("/about/contact", response_class=HTMLResponse)
def contact() -> str:
    body = """<section class="page-heading contact-hero"><p class="eyebrow">Coursera support</p><h1>Contact Us</h1><p>Choose the local guidance area that best fits your question.</p></section><section class="support-grid"><article><h2>Learner Support</h2><p>Get local help with finding courses, previewing materials, and account-entry guidance.</p><a href="/help">Open learner help</a></article><article><h2>Inquiries</h2><p>General questions are represented as offline guidance only; no message is transmitted.</p><a href="/browse">Explore available learning</a></article><article><h2>Partnerships</h2><p>Business, university, and government contact actions are outside this offline scope.</p><a href="/">Return home</a></article></section>"""
    return _page("Contact", body)
