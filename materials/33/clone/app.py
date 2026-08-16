"""Coursera-inspired WebsiteBench offline clone."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from catalog import load_catalog_seed


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


def _card(record: dict[str, Any]) -> str:
    return f"""
<article class="catalog-card" data-catalog-record="{escape(record['id'])}">
  <div class="card-art" aria-hidden="true"><span>{escape(record['subject'][0])}</span></div>
  <p class="provider">{escape(record['provider'])}</p>
  <h2><a href="{escape(_record_href(record))}">{escape(record['title'])}</a></h2>
  <p class="rating">★ {record['rating']:.1f} · Offline reviews</p>
  <p>{escape(record['level'])} · {escape(record['type'].title())} · {escape(record['duration'])}</p>
  {f'<p class="evidence-note" data-evidence-classification="{escape(record["source_evidence_classification"])}">Offline simulated details — not source-verified.</p>' if record['source_evidence_classification'] != 'directly-observed' else ''}
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
def deep_learning_specialization() -> str:
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
    body = f"""
<nav class="breadcrumbs"><a href="/browse">Browse</a><span>›</span><a href="/browse/data-science">Data Science</a><span>›</span>Deep Learning</nav>
<section class="program-hero"><div><p class="provider">DeepLearning.AI</p><h1>Deep Learning Specialization</h1><p class="lead">Become a Machine Learning expert. Master the fundamentals of deep learning and break into AI.</p><p>Instructors: <strong>Andrew Ng +2 more</strong> <span class="badge">Top Instructor</span></p><a class="primary-button" href="/login?next=/checkout/deep-learning">Enroll for free</a></div><img src="/static/deep-learning-mark.svg" alt="Deep Learning program mark"></section>
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
<section class="auth-shell"><div class="auth-card"><p class="eyebrow">Welcome back</p><h1>Log in to your Coursera account</h1><p class="safe-note" id="credential-note">Public preview only: this form does not submit credentials. Do not enter a real email or password.</p><form class="auth-form" aria-describedby="credential-note" autocomplete="off"><label>Email<input type="email" name="email" placeholder="name@example.invalid"></label><label>Password<input type="password" name="password" placeholder="Password"></label><button type="button" disabled>Log in (available in Task 4)</button></form><div class="identity-options"><button type="button">Continue with Google</button><button type="button">Continue with Apple</button></div><a href="/account-recovery">Forgot password?</a><p>New to Coursera? <a href="/signup">Sign up</a></p></div><aside><h2>Continue learning offline</h2><p>Account creation, sessions, and progress are added separately through the generated WebsiteBench backend.</p></aside></section>"""
        return _page("Login - Continue Learning", body)
    body = """
<section class="auth-shell"><div class="auth-card"><p class="eyebrow">Join for free</p><h1>Create your Coursera account</h1><p class="safe-note" id="signup-note">Field preview only. Do not enter real personal data; account creation is not active in this task.</p><form class="auth-form" aria-describedby="signup-note" autocomplete="off"><label>Full name<input name="full_name" placeholder="Offline learner"></label><label>Email<input type="email" name="email" placeholder="name@example.invalid"></label><label>Password<input type="password" name="password" placeholder="Create a password"></label><button type="button" disabled>Join for free (available in Task 4)</button></form><p>After local submission is enabled, a verification code will appear only in the site-bound local outbox.</p><p>By joining, you agree to the <a href="/help#terms">Terms of Use</a> and Privacy Notice.</p><p>Already have an account? <a href="/login">Log in</a></p></div><aside><h2>Learn without limits</h2><p>Browse now and return when local account support is available.</p></aside></section>"""
    return _page("Signup - Start Learning", body)


@app.get("/login", response_class=HTMLResponse)
def login() -> str:
    return _auth_page("login")


@app.get("/signup", response_class=HTMLResponse)
def signup() -> str:
    return _auth_page("signup")


@app.get("/account-recovery", response_class=HTMLResponse)
def account_recovery() -> str:
    body = """<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Account access</p><h1>Reset your password</h1><p>No reset message is sent from this public preview. Do not enter a real address.</p><form class="auth-form" autocomplete="off"><label>Account email<input type="email" name="address" placeholder="name@example.invalid"></label><p class="field-guidance">Enter the address for a local account. Validation and local-outbox delivery are implemented in Task 4.</p><button type="button" disabled>Send reset link (unavailable)</button></form><a href="/login">Return to sign in</a></div></section>"""
    return _page("Password Recovery", body)


@app.get("/help", response_class=HTMLResponse)
def help_center() -> str:
    body = """<section class="page-heading help-hero"><p class="eyebrow">Public support</p><h1>Learner Help Center</h1><p>Find safe, local guidance without opening an external support origin.</p></section><section class="support-grid"><article><h2>Courses and enrollment</h2><p>Browse categories, search learning opportunities, preview courses, and understand offline enrollment options.</p><a href="/browse">Browse the catalog</a></article><article><h2>Account access</h2><p>Review sign-in, registration, and password-recovery guidance. Never enter real credentials in this offline fixture.</p><a href="/login">Account access help</a></article><article><h2>Failed actions</h2><p>Clear filters, recover from missing pages, and return safely to available public records.</p><a href="/search">Search again</a></article><article id="terms"><h2>Terms of Use</h2><p>This is a deterministic WebsiteBench offline reconstruction with no publication, legal, or source-account effect.</p></article></section>"""
    return _page("Learner Help Center", body)


@app.get("/about/contact", response_class=HTMLResponse)
def contact() -> str:
    body = """<section class="page-heading contact-hero"><p class="eyebrow">Coursera support</p><h1>Contact Us</h1><p>Choose the local guidance area that best fits your question.</p></section><section class="support-grid"><article><h2>Learner Support</h2><p>Get local help with finding courses, previewing materials, and account-entry guidance.</p><a href="/help">Open learner help</a></article><article><h2>Inquiries</h2><p>General questions are represented as offline guidance only; no message is transmitted.</p><a href="/browse">Explore available learning</a></article><article><h2>Partnerships</h2><p>Business, university, and government contact actions are outside this offline scope.</p><a href="/">Return home</a></article></section>"""
    return _page("Contact", body)
