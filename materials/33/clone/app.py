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
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import assignment_db, checkout, learning_db
from business_category import load_business_snapshot_html
from browse_page import render_browse_body
from catalog import load_catalog_seed
from category_page import render_category_body
from course_page import render_neural_networks_course_body
from data_science_page import render_data_science_body
import enrolled_course
import enrolled_page
from home_page import render_home_body
from home_inventory import load_home_inventory
from search_page import render_public_landing_body, render_search_body
from specialization_page import render_specialization_body
from websitebench.local_clone_auth import AuthError
from websitebench.site_backend import PaymentConflict, PaymentError, PaymentRejected
from ui import footer as desktop_footer
from ui import header as desktop_header
from ui import page as desktop_page


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


app = FastAPI(title=DISPLAY_NAME)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "font-src 'self' data:; script-src 'self'; connect-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
)
BUSINESS_SNAPSHOT_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "script-src 'self'; connect-src 'none'; frame-src 'none'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        BUSINESS_SNAPSHOT_CONTENT_SECURITY_POLICY
        if request.url.path == "/browse/business"
        else CONTENT_SECURITY_POLICY
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def _header(*, authenticated: bool = False) -> str:
    return desktop_header(authenticated=authenticated)


def _footer() -> str:
    return desktop_footer()


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
    search_value: str = "",
    checkout_chrome: bool = False,
    language: str = "en",
    footer_variant: str = "default",
    open_login: bool = False,
    open_signup: bool = False,
    login_next_path: str = "/my-learning",
    real_css: str | None = None,
    minimal_header: bool = False,
) -> str:
    return desktop_page(
        title=title,
        body=body,
        authenticated=_request_authenticated(request),
        body_class=body_class,
        document_title=document_title,
        search_value=search_value,
        checkout_chrome=checkout_chrome,
        language=language,
        footer_variant=footer_variant,
        open_login=open_login,
        open_signup=open_signup,
        login_next_path=login_next_path,
        real_css=real_css,
        minimal_header=minimal_header,
    )


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
    return HTMLResponse(_page(request, "Account action", body, language="en"), status_code=status_code)


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
    intended = request.url.path
    if request.url.query:
        intended += f"?{request.url.query}"
    next_path = quote(_safe_next_path(intended), safe="/")
    body = f"""<section class="not-found permission-prompt"><p class="eyebrow">Local account required</p><h1>{escape(message)}</h1><p>Sign in with a site-33 .test account. No source account is contacted.</p><a class="primary-button" href="/login?next={escape(next_path, quote=True)}">Sign in locally</a></section>"""
    return HTMLResponse(_page(request, "Sign in required", body, language="en"), status_code=401)


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


def _money_amount(minor: int, currency: str) -> str:
    whole, fraction = divmod(minor, 100)
    if currency == "CNY":
        return f"¥{whole}" if fraction == 0 else f"¥{whole}.{fraction:02d}"
    if currency == "USD":
        return f"${whole}.{fraction:02d}"
    return f"{currency} {whole}.{fraction:02d}"


def _trial_terms(pricing: dict[str, Any]) -> tuple[str, str]:
    trial_days = int(pricing["trial_days"])
    if trial_days <= 0:
        return "One-time local checkout", ""
    renewal = _money_amount(
        int(pricing["renewal_minor"]), str(pricing["renewal_currency"])
    )
    interval = "month" if pricing["renewal_interval"] == "month" else str(
        pricing["renewal_interval"]
    )
    return f"{trial_days}-day free trial", f"{renewal}/{interval}"


def _checkout_totals(pricing: dict[str, Any]) -> str:
    trial_label, renewal = _trial_terms(pricing)
    due_today = _money_amount(int(pricing["total_minor"]), str(pricing["currency"]))
    renewal_row = (
        f"<div><dt>Then {renewal}</dt><dd>{renewal}</dd></div>"
        if renewal
        else ""
    )
    return f"""<dl class="checkout-totals"><div><dt>{trial_label}</dt><dd>{trial_label}</dd></div>{renewal_row}<div><dt>Due today</dt><dd>{due_today}</dd></div><div class="checkout-total"><dt>Total due today: {due_today}</dt><dd>{due_today}</dd></div></dl>"""


def _order_rows(records: list[dict[str, Any]]) -> str:
    if not records:
        return """<div class="empty-state"><h2>No local orders yet</h2><p>Approved sandbox checkouts will appear here.</p><a href="/specializations/deep-learning">Back to Deep Learning</a></div>"""
    return "".join(
        f"""<article class="catalog-card order-card" data-order-status="{escape(str(record["status"]))}"><p class="eyebrow">{"Paid" if record["status"] == "PAID" else "Canceled"}</p><h2>Deep Learning Specialization</h2><p>Order {escape(str(record["order_id"]))}</p><p>Due today: {_money_amount(int(record["total_minor"]), str(record["currency"]))}</p><p>{_trial_terms(record)[0]}{f'; then {_trial_terms(record)[1]}' if _trial_terms(record)[1] else ''}</p><a href="/orders/{escape(str(record["order_id"]))}">View order details</a></article>"""
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


def _enrolled_subject(request: Request) -> str | HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to open this course")
    try:
        assignment_db.course_access(subject)
    except LookupError:
        return _enrollment_required_page(request, "Enroll to open this course")
    return subject


def _enrolled_response(
    request: Request,
    title: str,
    body: str,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return HTMLResponse(
        _page(
            request,
            title,
            body,
            language="en",
            body_class="authenticated-learning-page enrolled-course-page",
            real_css="consumer-description-page.css",
        ),
        status_code=status_code,
    )


async def _assignment_form(
    request: Request,
) -> tuple[str, str, dict[int, list[int]]]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type != "application/x-www-form-urlencoded":
        raise ValueError("Submit the assignment form shown on this page")
    try:
        pairs = parse_qsl(
            (await request.body()).decode("utf-8"), keep_blank_values=True
        )
    except UnicodeDecodeError as exc:
        raise ValueError("Submit the assignment form shown on this page") from exc
    attempt_id = ""
    legal_name = ""
    answers: dict[int, list[int]] = {}
    for key, value in pairs:
        if key == "attempt_id":
            if attempt_id:
                raise ValueError("Invalid attempt identifier")
            attempt_id = value
        elif key == "legal_name":
            if legal_name:
                raise ValueError("Invalid legal name confirmation")
            legal_name = value
        elif re.fullmatch(r"q_[0-9]+", key):
            number = int(key[2:])
            try:
                option = int(value)
            except ValueError as exc:
                raise ValueError(f"Invalid option for question {number}") from exc
            answers.setdefault(number, []).append(option)
        else:
            raise ValueError("The assignment form contains an unknown field")
    if not attempt_id:
        raise ValueError("Invalid attempt identifier")
    return attempt_id, legal_name, answers


def _enrollment_rows(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<div class="empty-state"><h2>No local enrollments yet</h2><a href="/specializations/deep-learning">Browse the Deep Learning Specialization</a></div>'
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
            cancellation = f'<a href="/orders/{escape(str(record["order_id"]))}">Manage local paid order</a>'
            origin = "Created by an approved local-sandbox checkout."
        else:
            cancellation = (
                f'<form action="/enrollments/{record["enrollment_id"]}/cancel" method="post"><button type="submit">Cancel enrollment</button></form>'
                if record["status"] == "active"
                else ""
            )
            origin = "No checkout or payment record was created."
        status_label = "In progress" if record["status"] == "active" else "Canceled"
        track_label = {"free": "Free learning", "audit": "Audit", "paid": "Paid"}.get(
            str(record["track"]), str(record["track"])
        )
        reactivated_note = (
            "<p>Previously canceled; this local enrollment is active again.</p>"
            if record["status"] == "active" and record["canceled_at"]
            else ""
        )
        rows.append(
            f"""<article class="catalog-card enrollment-card" data-enrollment-id="{record["enrollment_id"]}"><p class="eyebrow">{status_label}</p><h2>{escape(course_title)}</h2><p>{escape(track_label)} track</p>{reactivated_note}<p>{origin}</p>{cancellation}<a href="/account/history/{record["enrollment_id"]}">View enrollment details</a><a href="{course_href}">Open course</a></article>"""
        )
    return "".join(rows)


@app.exception_handler(404)
async def branded_not_found(request: Request, _exception: Exception) -> HTMLResponse:
    body = """<section class="source-not-found"><img class="source-not-found-art" src="/static/home/source-404-illustration.png" alt="" width="715" height="272"><h1>We were not able to find the page you're looking for.</h1><p>Try <a href="/browse">browsing our course catalog</a> or <a href="/search">searching our course catalog</a> instead.</p><p>You might also find these links helpful:</p><nav aria-label="Helpful links"><a href="/browse">Online Degrees</a><a href="/about/contact">Coursera for Business</a><a href="/help">Coursera Blog</a><a href="/">Coursera home</a></nav></section>"""
    return HTMLResponse(
        _page(
            request,
            "Page not found",
            body,
            body_class="source-not-found-page",
            language="en",
            footer_variant="none",
            real_css="browse.css",
            minimal_header=True,
        ),
        status_code=404,
    )


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


def _source_home_cards(path: str, *, section_ids: tuple[str, ...] = ()) -> list[object]:
    sections = load_home_inventory()
    scoped = [
        card
        for section in sections
        if not section_ids or section.section_id in section_ids
        for card in section.cards
    ]
    normalized_path = urlsplit(path).path.casefold()
    exact = [card for card in scoped if urlsplit(card.href).path.casefold() == normalized_path]
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalized_path)
        if len(token) > 2 and token not in {"online", "courses", "learn"}
    }
    related = [
        card
        for card in scoped
        if tokens
        and tokens
        & set(
            re.split(
                r"[^a-z0-9]+",
                f"{card.title} {card.provider} {card.metadata} {card.href}".casefold(),
            )
        )
    ]
    selected = exact + [card for card in related if card not in exact]
    return (selected or scoped)[:8]


def _source_path_title(path: str) -> str:
    exact = _source_home_cards(path)
    if exact and urlsplit(exact[0].href).path == urlsplit(path).path:
        return str(exact[0].title)
    final_segment = urlsplit(path).path.rstrip("/").rsplit("/", 1)[-1]
    return final_segment.replace("-", " ").title()


def _public_source_landing(
    request: Request,
    *,
    title: str,
    description: str,
    section_ids: tuple[str, ...] = (),
) -> str:
    body = render_public_landing_body(
        title=title,
        description=description,
        cards=_source_home_cards(request.url.path, section_ids=section_ids),
    )
    return _page(
        request,
        title,
        body,
        body_class="source-category-page public-source-landing-page",
        document_title=f"{title} | Coursera",
        language="en",
        footer_variant="source-browse",
    )


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "site_id": SITE_ID}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> str:
    body = render_home_body()
    return _page(
        request,
        "Online Courses, Certificates, & Degrees",
        body,
        body_class="source-home-page catalog-landing",
        document_title="Coursera | Online Courses, Certificates, & Degrees",
        language="en",
        footer_variant="source-browse",
        real_css="front-page.css",
    )


@app.post("/privacy-preferences")
async def privacy_preferences(request: Request) -> Response:
    values = await _form_values(request)
    choice = values.get("choice", "reject")
    if choice not in {"accept", "reject", "settings"}:
        choice = "reject"
    if choice == "settings":
        response = RedirectResponse("/privacy", status_code=303)
    else:
        response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "coursera_privacy_choice",
        "accept" if choice == "accept" else "reject",
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/privacy", response_class=HTMLResponse)
def privacy_notice(request: Request) -> HTMLResponse:
    body = """<section class="page-heading"><p class="eyebrow">Privacy Notice</p><h1>Privacy and cookie preferences</h1><p>This offline clone stores only local demonstration preferences. It does not contact Coursera, send marketing requests, or store real personal information.</p><form class="auth-form" action="/privacy-preferences" method="post"><button type="submit" name="choice" value="accept">Accept</button><button type="submit" name="choice" value="reject">Reject</button></form><a href="/">Back to home</a></section>"""
    return HTMLResponse(_page(request, "Privacy Notice", body, language="en"))


@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request) -> HTMLResponse:
    body = """<section class="page-heading"><p class="eyebrow">Terms</p><h1>Local terms of use</h1><p>This page supports WebsiteBench offline-clone review. Enrollments, payments, learning records, and account actions use local synthetic data and produce no external effect on Coursera.</p><a href="/">Back to home</a></section>"""
    return HTMLResponse(_page(request, "Terms", body, language="en"))


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request) -> str:
    body = render_browse_body()
    return _page(
        request,
        "Online Course Catalog by Topic and Skill",
        body,
        body_class="source-browse-page catalog-landing",
        document_title="Coursera | Degrees, Certificates, & Free Online Courses",
        language="en",
        footer_variant="source-browse",
        real_css="browse.css",
    )


@app.get("/browse/{category}", response_class=HTMLResponse)
def browse_category(request: Request, category: str) -> str:
    subject = SUBJECTS.get(category)
    if subject is None:
        raise HTTPException(status_code=404)
    if category == "data-science":
        return _page(
            request,
            "Data Science Online Courses",
            render_data_science_body(),
            body_class="source-data-science-page",
            document_title="Data Science Online Courses | Coursera",
            language="en",
            footer_variant="source-browse",
            real_css="browse.css",
        )
    if category == "business":
        return HTMLResponse(load_business_snapshot_html())
    return _page(
        request,
        f"{subject} Online Courses",
        render_category_body(category),
        body_class="source-category-page",
        document_title=f"{subject} Online Courses | Coursera",
        language="en",
        footer_variant="source-browse",
        real_css="browse.css",
    )


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    query: str = "",
    category: str = "",
    level: str = "",
    topic: str = "",
    duration: str = "",
    rating: float | None = None,
    language: str = "",
    schedule: str = "",
    sort: str = "title-asc",
    status: str = "",
    product: str = "",
) -> str:
    catalog = load_catalog_seed()
    q = q or query
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
    if status == "free-trial":
        records = [r for r in records if "free" in str(r.get("pricing", "")).casefold()]
    if product == "courses":
        records = [r for r in records if r.get("type") == "course"]
    elif product == "specializations":
        records = [r for r in records if r.get("type") == "specialization"]
    elif product == "professional-certificates":
        records = [r for r in records if r.get("type") in {"professional-certificate", "specialization"} and "certificate" in str(r.get("title", "")).casefold()]
    elif product == "degrees":
        records = [r for r in records if r.get("type") == "degree"]
    filter_values = {
        "category": category,
        "level": level,
        "topic": topic,
        "duration": duration,
        "rating": "" if rating is None else f"{rating:g}",
        "language": language,
        "schedule": schedule,
        "sort": sort,
        "status": status,
        "product": product,
    }
    deep_learning_query = q.strip().casefold() == "deep learning"
    catalog_scope = deep_learning_query and any(
        (category, topic, duration, rating, language, schedule)
    )
    source_selected = deep_learning_query and not catalog_scope and sort in {
        "title-asc",
        "best-match",
    }
    body = render_search_body(
        query=q,
        filtered_records=records,
        filters=filter_values,
        source_selected=source_selected,
        filter_options={
            "category": list(SUBJECTS),
            "level": ["Beginner", "Intermediate", "Advanced", "Mixed"],
            "duration": sorted({str(record["duration"]) for record in catalog}),
            "rating": ["4.8", "4.5", "4.0"],
            "language": sorted({str(record["language"]) for record in catalog}),
            "schedule": sorted({str(record["schedule"]) for record in catalog}),
        },
    )
    return _page(
        request,
        "Search",
        body,
        body_class="source-search-page",
        document_title=(
            "Coursera | Online Courses From Top Universities. Join for Free"
        ),
        search_value="deep learning" if source_selected else q,
        language="en",
        footer_variant="source-browse",
        real_css="search-v2.css",
    )


@app.get("/courses", response_class=HTMLResponse)
def courses_alias(request: Request) -> RedirectResponse:
    suffix = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/search{suffix}", status_code=307)


@app.get("/courseraplus", response_class=HTMLResponse)
@app.get("/courseraplus/{offer:path}", response_class=HTMLResponse)
def coursera_plus_landing(request: Request, offer: str = "") -> str:
    return _public_source_landing(
        request,
        title="Coursera Plus",
        description="Explore source-backed local programs available through the Coursera catalog.",
        section_ids=("most-popular", "google-career", "ai-skills"),
    )


@app.get("/business", response_class=HTMLResponse)
@app.get("/business/{program:path}", response_class=HTMLResponse)
def business_landing(request: Request, program: str = "") -> str:
    return _public_source_landing(
        request,
        title="Coursera for Teams" if program == "teams" else "Coursera for Business",
        description="Build team skills with source-backed local business and career programs.",
        section_ids=("career-data", "trending-project-management", "most-popular"),
    )


@app.get("/career-academy", response_class=HTMLResponse)
@app.get("/career-academy/{role:path}", response_class=HTMLResponse)
def career_landing(request: Request, role: str = "") -> str:
    return _public_source_landing(
        request,
        title=_source_path_title(request.url.path) if role else "Career Academy",
        description="Explore source-backed career roles and the local learning records connected to them.",
        section_ids=("explore-careers", "career-data"),
    )


@app.get("/degrees", response_class=HTMLResponse)
@app.get("/degrees/{degree:path}", response_class=HTMLResponse)
def degrees_landing(request: Request, degree: str = "") -> str:
    return _public_source_landing(
        request,
        title=_source_path_title(request.url.path) if degree else "Degrees",
        description="Explore local learning records and pathways connected to online degree study.",
        section_ids=("most-popular", "career-data", "google-career"),
    )


@app.get("/partners", response_class=HTMLResponse)
@app.get("/partners/{provider:path}", response_class=HTMLResponse)
def partner_landing(request: Request, provider: str = "") -> str:
    title = _source_path_title(request.url.path) if provider else "Partners"
    return _public_source_landing(
        request,
        title=title,
        description=f"Explore source-backed local learning records from {title} and related providers.",
    )


@app.get("/explore/{collection:path}", response_class=HTMLResponse)
def provider_collection_landing(request: Request, collection: str) -> str:
    provider_names = {
        "ibm-online-courses": "IBM",
        "microsoft-certificates": "Microsoft",
        "deep-learning-ai-online-courses": "DeepLearning.AI",
        "stanford-online-courses": "Stanford University",
        "university-of-pennsylvania-online-courses": "University of Pennsylvania",
        "university-of-michigan-online-courses": "University of Michigan",
        "most-popular-courses": "Most Popular Courses",
        "new-on-coursera": "New on Coursera",
        "generative-ai": "Generative AI",
        "learner-outcomes": "Learner Outcomes",
    }
    title = provider_names.get(collection, _source_path_title(request.url.path))
    return _public_source_landing(
        request,
        title=title,
        description=f"Explore source-backed local learning records in {title}.",
    )


@app.get("/google-career-certificates", response_class=HTMLResponse)
@app.get("/professional-certificates", response_class=HTMLResponse)
@app.get("/professional-certificates/{program:path}", response_class=HTMLResponse)
def professional_certificate_landing(
    request: Request, program: str = ""
) -> str:
    title = (
        "Google Career Certificates"
        if request.url.path == "/google-career-certificates"
        else _source_path_title(request.url.path)
        if program
        else "Professional Certificates"
    )
    return _public_source_landing(
        request,
        title=title,
        description="Explore source-backed local professional and career learning records.",
        section_ids=("career-data", "google-career", "hot-new-releases"),
    )


_PROJECT_DETAILS = {
    "chatgpt-prompt-engineering-for-developers-project": {
        "title": "ChatGPT Prompt Engineering for Developers",
        "provider": "DeepLearning.AI",
        "description": "Learn prompt engineering patterns for building reliable applications with large language models.",
    },
    "langchain-for-llm-application-development-project": {
        "title": "LangChain for LLM Application Development",
        "provider": "DeepLearning.AI",
        "description": "Build applications with language models, prompt templates, memory, and document retrieval.",
    },
}


@app.get("/projects/{project_id:path}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: str) -> HTMLResponse:
    """Serve the known local project destinations exposed by Purchases recommendations."""

    project = _PROJECT_DETAILS.get(project_id)
    if project is None:
        raise HTTPException(status_code=404)
    title = str(project["title"])
    body = f"""
<nav class="course-breadcrumbs"><a href="/browse">Browse</a><span aria-hidden="true">›</span><span>Guided Project</span></nav>
<section class="course-hero source-course-hero" data-project-detail="{escape(project_id)}">
  <div><p class="provider">{escape(str(project["provider"]))}</p><h1>{escape(title)}</h1>
  <p>{escape(str(project["description"]))}</p><a class="wb-primary" href="/signup">Join for Free</a></div>
</section>
<section class="course-source-detail"><h2>About this project</h2><p>This local project page is part of the offline Coursera catalog. It creates no external enrollment or payment effect.</p><p><a href="/browse">Browse more courses and projects</a></p></section>
"""
    return HTMLResponse(
        _page(
            request,
            title,
            body,
            body_class="source-course-detail-page",
            document_title=f"{title} | Coursera",
            language="en",
        )
    )


@app.get("/mastertrack", response_class=HTMLResponse)
@app.get("/certificates/learn", response_class=HTMLResponse)
@app.get("/government", response_class=HTMLResponse)
@app.get("/campus", response_class=HTMLResponse)
@app.get("/social-impact", response_class=HTMLResponse)
@app.get("/directory", response_class=HTMLResponse)
@app.get("/articles", response_class=HTMLResponse)
@app.get("/articles/{article:path}", response_class=HTMLResponse)
@app.get("/resources/{resource:path}", response_class=HTMLResponse)
def public_collection_alias(
    request: Request, article: str = "", resource: str = ""
) -> str:
    title = _source_path_title(request.url.path)
    return _public_source_landing(
        request,
        title=title,
        description=f"Explore source-backed local learning records connected to {title}.",
    )


@app.get("/about/privacy", response_class=HTMLResponse)
@app.get("/about/cookies-manage", response_class=HTMLResponse)
def legacy_privacy_alias() -> RedirectResponse:
    return RedirectResponse("/privacy", status_code=307)


@app.get("/about/terms", response_class=HTMLResponse)
def legacy_terms_alias() -> RedirectResponse:
    return RedirectResponse("/terms", status_code=307)


@app.get("/about", response_class=HTMLResponse)
@app.get("/about/affiliates", response_class=HTMLResponse)
@app.get("/about/how-coursera-works/", response_class=HTMLResponse)
@app.get("/about/leadership", response_class=HTMLResponse)
@app.get("/about/press", response_class=HTMLResponse)
def about_landing(request: Request) -> str:
    titles = {
        "/about": "About Coursera",
        "/about/affiliates": "Affiliates",
        "/about/how-coursera-works/": "How Coursera Works",
        "/about/leadership": "Leadership",
        "/about/press": "Press",
    }
    title = titles[request.url.path]
    return _public_source_landing(
        request,
        title=title,
        description=f"Explore local learning records and information connected to {title}.",
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
    _backend, _auth, _token, session = _request_session(request)
    body = render_specialization_body(
        components=components,
        authenticated=bool(session["authenticated"]),
    )
    return _page(
        request,
        "Deep Learning Specialization",
        body,
        body_class="source-specialization-page",
        document_title="Deep Learning Specialization | Coursera",
        language="en",
        login_next_path="/checkout/deep-learning",
        footer_variant="source-browse",
        real_css="consumer-description-page.css",
    )


@app.get("/specializations/{program_id}", response_class=HTMLResponse)
def specialization_landing(request: Request, program_id: str) -> str:
    title = _source_path_title(request.url.path)
    return _public_source_landing(
        request,
        title=title,
        description="Explore this source-backed specialization and related local learning records.",
    )


@app.get("/checkout/deep-learning", response_class=HTMLResponse)
def checkout_plan(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, _subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before choosing a checkout plan")
    pricing = checkout.plan()
    trial_label, renewal = _trial_terms(pricing)
    due_today = _money_amount(int(pricing["total_minor"]), str(pricing["currency"]))
    body = f"""
<nav class="course-breadcrumbs checkout-breadcrumbs"><a href="/specializations/deep-learning">Deep Learning Specialization</a><span>›</span><span>Checkout</span></nav>
<section class="source-checkout-shell">
  <main class="source-checkout-main">
    <h1>Checkout</h1>
    <p class="checkout-required">All fields are required</p>
    <p class="safe-note">This page is reconstructed from observed Coursera checkout information. No real payment data is submitted and Coursera is never contacted.</p>
    <form class="source-checkout-form" action="/checkout/deep-learning" method="post" autocomplete="off">
      <input type="hidden" name="course_id" value="deep-learning-specialization">
      <input type="hidden" name="plan_id" value="{escape(str(pricing["plan_id"]))}">
      <section class="checkout-billing" aria-labelledby="billing-heading">
        <h2 id="billing-heading">Billing information</h2>
        <label>Full name<input id="billing-name" type="text" placeholder="Enter your name" autocomplete="off"></label>
        <label>Country/Region<select id="billing-country" autocomplete="off"><option>China</option><option>United States</option><option>Singapore</option></select></label>
      </section>
      <section class="source-payment-card" aria-labelledby="payment-heading">
        <h2 id="payment-heading">Payment method</h2>
        <div class="payment-choice is-selected"><span>Card</span><span>Visa · Mastercard · American Express</span></div>
        <label>Card number<input id="synthetic-card-number" inputmode="numeric" autocomplete="off" placeholder="Card number"></label>
        <div class="payment-grid">
          <label>Expiry date<input id="synthetic-expiry" autocomplete="off" placeholder="MM / YY"></label>
          <label>Security code<input id="synthetic-cvv" inputmode="numeric" autocomplete="off" placeholder="CVC"></label>
        </div>
        <label class="save-card"><input id="synthetic-save-card" type="checkbox"> Save payment method for future purchases</label>
        <div class="payment-choice paypal-choice"><span>PayPal</span><span>Continue with PayPal</span></div>
      </section>
      <p class="checkout-terms">By clicking “Start free trial,” you agree to Coursera's <a href="/terms">Terms of Use</a> and <a href="/privacy">Privacy Notice</a>. This clone uses local-sandbox and creates only a local draft.</p>
      <button class="wb-primary checkout-start" type="submit">Start free trial</button>
    </form>
    <p class="checkout-safety"><strong>Start your {trial_label}.</strong>Due today: {due_today}; then {renewal}. You can cancel from local Order history.</p>
    <a class="checkout-return" href="/specializations/deep-learning">Back to Specialization</a>
  </main>
  <aside class="source-checkout-summary" aria-label="Order summary">
    <article class="summary-course">
      <a href="/specializations/deep-learning">Deep Learning</a>
      <p>Provided by DeepLearning.AI</p>
      <a class="summary-remove" href="/specializations/deep-learning">Remove</a>
    </article>
    <p class="summary-note">No contracts. Cancel anytime.</p>
    <dl class="summary-prices">
      <div><dt>Monthly subscription</dt><dd>{trial_label}</dd></div>
      <div><dt>Then {renewal}</dt><dd>{renewal}</dd></div>
      <div class="summary-total"><dt>Total due today: {due_today}</dt><dd>{due_today}</dd></div>
    </dl>
    <p class="summary-small">Cancel before the trial ends and you will not be charged. This offline version never submits real payment data.</p>
  </aside>
</section>"""
    return HTMLResponse(
        _page(request, "Deep Learning checkout plan", body, checkout_chrome=True, language="en")
    )


@app.get("/payments/checkout", response_class=HTMLResponse)
def source_checkout_alias(request: Request) -> HTMLResponse:
    """Expose the observed source-shaped checkout entry locally."""

    return checkout_plan(request)


@app.post("/payments/checkout")
async def source_checkout_alias_post(request: Request) -> Response:
    """Create the same owner-bound local draft from the observed source path."""

    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before starting checkout")
    values = await _form_values(request)
    try:
        draft = checkout.create_draft(
            subject,
            course_id=values.get("course_id", "deep-learning-specialization"),
            plan_id=values.get("plan_id", ""),
        )
    except ValueError as exc:
        return _checkout_validation(request, str(exc))
    return RedirectResponse(f"/checkout/{draft['draft_id']}/payment", status_code=303)


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
    body = f"""<nav class="course-breadcrumbs"><a href="/checkout/deep-learning">Checkout</a><span>›</span>Payment method</nav><section class="checkout-shell"><p class="eyebrow">Local safety demonstration</p><h1>Payment method</h1><p class="safe-note"><strong>Do not enter real payment information.</strong> The demonstration inputs below remain only in this browser page and are never submitted or saved as form fields.</p><form class="synthetic-payment" action="/checkout/{escape(draft_id)}/review" method="get" autocomplete="off"><label>Sample card number<input id="synthetic-card-number" inputmode="numeric" autocomplete="off" placeholder="Local demonstration only"></label><label>Sample expiry<input id="synthetic-expiry" autocomplete="off" placeholder="MM / YY"></label><label>Sample security code<input id="synthetic-cvv" inputmode="numeric" autocomplete="off" placeholder="Local demonstration only"></label><button class="wb-primary" type="submit">Continue without submitting these values</button></form><a href="/specializations/deep-learning">Back to Specialization</a></section>"""
    return HTMLResponse(_page(request, "Local Payment Method", body, checkout_chrome=True, language="en"))


@app.get("/checkout/{draft_id}/review", response_class=HTMLResponse)
def checkout_review(request: Request, draft_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to review this checkout")
    try:
        draft = checkout.get_draft(subject, draft_id)
    except LookupError:
        return _checkout_not_found(request)
    idempotency_key = f"browser-attempt:{secrets.token_urlsafe(18)}"
    body = f"""<nav class="course-breadcrumbs"><a href="/checkout/{escape(draft_id)}/payment">Payment method</a><span>›</span>Review</nav><section class="checkout-shell"><p class="eyebrow">Local sandbox only</p><h1>Confirm free trial</h1><p>This is a local demonstration and creates no external or real payment effect.</p>{_checkout_totals(draft)}<p class="checkout-terms">By using the action below, you acknowledge the local demonstration terms and can cancel from Order history.</p><form class="sandbox-scenarios" action="/checkout/{escape(draft_id)}/attempt" method="post"><input type="hidden" name="idempotency_key" value="{escape(idempotency_key)}"><fieldset><legend>Choose a deterministic local sandbox result</legend><label><input type="radio" name="scenario_id" value="sandbox-approved" required>Simulate approval</label><label><input type="radio" name="scenario_id" value="sandbox-declined" required>Simulate decline</label><label><input type="radio" name="scenario_id" value="sandbox-retry" required>Simulate retry</label></fieldset><button class="wb-primary" type="submit">Start free trial</button></form><a href="/specializations/deep-learning">Back to Specialization</a></section>"""
    return HTMLResponse(_page(request, "Review Local Checkout", body, checkout_chrome=True, language="en"))


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
    heading = "Sandbox payment declined" if result["outcome"] == "declined" else "Sandbox payment needs another try"
    body = f"""<section class="checkout-shell"><p class="eyebrow">Local sandbox result</p><h1>{heading}</h1><p>No order or paid enrollment was created, and no external payment was attempted.</p><a class="wb-primary" href="/checkout/{escape(draft_id)}/review">Choose another local result</a><a href="/specializations/deep-learning">Back to the Specialization</a></section>"""
    return HTMLResponse(_page(request, "Local sandbox result", body, language="en"))


@app.get("/learn/{course_id}", response_class=HTMLResponse)
def course_detail(request: Request, course_id: str) -> str:
    record = _record_by_id(course_id)
    if record is None:
        title = _source_path_title(request.url.path)
        return _public_source_landing(
            request,
            title=title,
            description="Explore this source-backed course and related local learning records.",
        )
    if record["type"] != "course":
        raise HTTPException(status_code=404)
    if course_id == "neural-networks-deep-learning":
        _backend, _auth, _token, session = _request_session(request)
        body = render_neural_networks_course_body(
            course=record,
            authenticated=bool(session["authenticated"]),
        )
        return _page(
            request,
            record["title"],
            body,
            body_class="source-course-detail-page",
            document_title="Neural Networks and Deep Learning | Coursera",
            language="en",
            footer_variant="source-browse",
            login_next_path="/learn/neural-networks-deep-learning",
            real_css="consumer-description-page.css",
        )
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
        f"""<form class="enrollment-options" action="/enrollments" method="post"><input type="hidden" name="course_id" value="{escape(enrollment_course_id)}"><label>Enrollment track<select name="track" required><option value="free">Free learning</option><option value="audit">Audit</option></select></label><button class="wb-primary" type="submit">Save local enrollment</button></form>"""
        if session["authenticated"]
        else f'<a class="wb-primary" href="/login?next=/learn/{escape(record["id"])}">Join for Free</a>'
    )
    display_title = record["title"]
    skill_chips = "".join(
        f"<span>{escape(skill)}</span>"
        for skill in (
            "Artificial Intelligence and Machine Learning",
            "Deep Learning",
            "Artificial Intelligence",
            "Model Optimization",
            "Model Training",
            "Convolutional Neural Networks",
            "Applied Machine Learning",
            "Supervised Learning",
            "Machine Learning Methods",
        )
    )
    body = f"""
<nav class="course-breadcrumbs"><a href="/">⌂</a><span>›</span><a href="/browse">Browse</a><span>›</span><a href="/browse/{escape(subject_slug)}">{escape(record["subject"])}</a><span>›</span>Machine Learning</nav>
<section class="course-hero source-course-hero" data-course-detail="{escape(record["id"])}"><div><p class="provider">{escape(record["provider"])}</p><h1>{escape(display_title)}</h1>{specialization_membership}<p>Instructor: <strong>{instructors}</strong> <span class="badge">Top Instructor</span></p>{enrollment_action}</div><div class="course-orbit" aria-hidden="true"></div></section>
<section class="course-stats"><div><strong>4 modules</strong><span>Gain insight into a topic and learn the fundamentals.</span></div><div><strong>{record["rating"]:.1f} ★</strong><span>123,795 reviews</span></div><div><strong>Intermediate level</strong><span>Recommended experience</span></div><div><strong>Flexible schedule</strong><span>3 weeks at 10 hours a week; learn at your own pace</span></div><div><strong>👍 96%</strong><span>Most learners liked this course</span></div></section>
<nav class="course-tabs" aria-label="Course details"><a href="#about">About</a><a href="#outcomes">Outcomes</a><a href="#modules">Modules</a><a href="#recommendations">Recommendations</a><a href="#reviews">Reviews</a><a href="#enroll">Enrollment</a></nav>
<section id="about" class="course-source-detail"><h2>Skills you'll gain</h2><div class="skill-chip-row">{skill_chips}</div>{_evidence_note(record)}<h2>Tools you'll learn</h2><p>{escape(record["prerequisites"])}</p></section>
<section class="detail-grid course-lower-detail"><article id="modules"><h2>Course modules</h2><ol>{syllabus}</ol></article><article><h2>Instructors</h2><p>{instructors}</p></article><article><h2>Prerequisites</h2><p>{escape(record["prerequisites"])}</p></article><article id="reviews"><h2>Reviews</h2><p>{escape(record["reviews_summary"])}</p></article><article><h2>Pricing</h2><p>{escape(record["pricing"])}</p></article><article id="enroll"><h2>Enrollment options</h2><ul>{tracks}</ul></article></section>"""
    return _page(request, record["title"], body, language="en")


def _auth_page(
    request: Request, kind: str, *, next_path: str = "/my-learning"
) -> str:
    if kind == "login":
        body = f"""
<section class="auth-modal-shell"><div class="auth-modal-backdrop" aria-hidden="true"><div class="auth-modal-course"><p>DeepLearning.AI</p><strong>Neural Networks and Deep Learning</strong><span>Start learning after you sign in</span></div></div><div class="auth-modal-card auth-card"><button class="auth-modal-close" type="button" aria-label="Close">×</button><p class="eyebrow">Coursera</p><h1>Log in or create an account</h1><p class="safe-note" id="credential-note">Credentials entered here are local test data and are never sent to Coursera or another external service.</p><form class="auth-form" action="/auth/login" method="post" aria-describedby="credential-note" autocomplete="off"><input type="hidden" name="next" value="{escape(next_path)}"><label>Email<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>Password<input type="password" name="password" placeholder="Enter your password" required></label><button type="submit">Continue</button></form><div class="identity-options"><a href="/auth/provider/google">Continue with Google</a><a href="/auth/provider/facebook">Continue with Facebook</a><a href="/auth/provider/apple">Continue with Apple</a></div><a href="/account-recovery">Having trouble logging in?</a><p>New to Coursera? <a href="/signup">Join for Free</a></p><p>By continuing, you agree to Coursera's <a href="/terms">Terms of Use</a> and acknowledge the <a href="/privacy">Privacy Notice</a>.</p></div></section>"""
        return _page(request, "Login - Continue Learning", body, language="en")
    body = """
<section class="auth-modal-shell"><div class="auth-modal-backdrop" aria-hidden="true"><div class="auth-modal-course"><p>DeepLearning.AI</p><strong>Start a new learning journey</strong><span>Local data stays inside this offline site</span></div></div><div class="auth-modal-card auth-card"><button class="auth-modal-close" type="button" aria-label="Close">×</button><p class="eyebrow">Coursera</p><h1>Log in or create an account</h1><p class="safe-note" id="signup-note">Use synthetic .test data only. Local verification guidance appears only in this browser session.</p><form class="auth-form" action="/auth/registration/start" method="post" aria-describedby="signup-note" autocomplete="off"><label>Full name<input name="full_name" placeholder="Local learner" required></label><label>Email<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>Create a password<input type="password" name="password" placeholder="Create a password" required></label><button type="submit">Join for Free</button></form><div class="identity-options"><a href="/auth/provider/google">Continue with Google</a><a href="/auth/provider/facebook">Continue with Facebook</a><a href="/auth/provider/apple">Continue with Apple</a></div><p>Verification guidance stays in the local inbox; no real email is sent.</p><p>By continuing, you agree to Coursera's <a href="/terms">Terms of Use</a> and acknowledge the <a href="/privacy">Privacy Notice</a>.</p><p>Already have an account? <a href="/login">Log in</a></p></div></section>"""
    return _page(request, "Signup - Start Learning", body, language="en")


@app.get("/login", response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    next_path = _safe_next_path(request.query_params.get("next"))
    body = """<section class="source-auth-page" aria-label="Log in or create account">
  <div class="source-auth-page-card"><p class="eyebrow">Coursera</p><h1>Log in or create account</h1><p>Learn on your own time from top universities and businesses.</p></div>
</section>"""
    response = HTMLResponse(_page(
        request,
        "Log in or create account",
        body,
        body_class="source-auth-standalone",
        document_title="Log in or create account | Coursera",
        language="en",
        footer_variant="source-browse",
        open_login=True,
        login_next_path=next_path,
        real_css="authentication.css",
    ))
    _set_session_cookie(response, backend, token)
    return response


@app.get("/signup", response_class=HTMLResponse)
def signup(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    body = """<section class="source-auth-page" aria-label="Join for free">
  <div class="source-auth-page-card"><p class="eyebrow">Coursera</p><h1>Log in or create an account</h1><p>Learn on your own time from top universities and businesses.</p></div>
</section>"""
    response = HTMLResponse(
        _page(
            request,
            "Signup - Start Learning",
            body,
            body_class="source-auth-standalone",
            document_title="Signup - Start Learning | Coursera",
            language="en",
            footer_variant="source-browse",
            open_login=True,
            real_css="authentication.css",
        )
    )
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


@app.post("/auth/local-learner")
async def auth_local_learner(request: Request) -> Response:
    """Enter the seeded empty learner without collecting real credentials."""

    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    signed_in = auth.sign_in(
        token,
        email="empty@coursera.test",
        password="Empty-Learner-33",
    )
    response = RedirectResponse(_safe_next_path(values.get("next")), status_code=303)
    _set_session_cookie(response, backend, str(signed_in["session_token"]))
    return response


@app.post("/auth/learning-demo")
async def auth_learning_demo(request: Request) -> Response:
    """Enter the seeded enrolled learner for the offline learning journeys."""

    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    signed_in = auth.sign_in(
        token,
        email="progress@coursera.test",
        password="Progress-Learner-33",
    )
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
    profile = learning_db.get_profile(subject)
    if learning_db.has_active_enrollment(subject):
        raw_tab = request.query_params.get("myLearningTab")
        if raw_tab not in {"IN_PROGRESS", "COMPLETED", "CERTIFICATES"}:
            raw_tab = {
                "completed": "COMPLETED",
                "certificates": "CERTIFICATES",
            }.get(request.query_params.get("status", ""), "IN_PROGRESS")
        course_state = assignment_db.course_access(subject)
        source_body = enrolled_page.render_my_learning_enrolled(
            profile, raw_tab, course_state
        )
        legacy_state = learning_db.learning_state(subject)
        review = learning_db.get_review(subject, "deep-learning-specialization")
        rating = int(review["rating"]) if review else 5
        review_text = str(review["review_text"]) if review else ""
        rating_options = "".join(
            f'<option value="{value}"{" selected" if value == rating else ""}>{value} stars</option>'
            for value in range(1, 6)
        )
        legacy_status = {
            "IN_PROGRESS": "in-progress",
            "COMPLETED": "completed",
            "CERTIFICATES": "certificates",
        }[raw_tab]
        legacy_tabs = "".join(
            f'<a class="{"is-active" if legacy_status == key else ""}" href="{href}">{label}</a>'
            for key, href, label in (
                ("in-progress", "/my-learning", "In Progress"),
                ("completed", "/my-learning?status=completed", "Completed"),
                ("certificates", "/my-learning?status=certificates", "Certificates"),
            )
        )
        completed_count = len(legacy_state["completed_lessons"])
        certificate = (
            "Certificate available"
            if legacy_state["certificate_available"]
            else "Certificate available after all lessons and quizzes"
        )
        legacy_empty = (
            '<span class="wb-sr-only">You have no completed courses yet.</span>'
            if raw_tab == "COMPLETED" and not legacy_state["certificate_available"]
            else '<span class="wb-sr-only">You have no certificates yet.</span>'
            if raw_tab == "CERTIFICATES" and not legacy_state["certificate_available"]
            else ""
        )
        legacy_tools = f"""<details class="legacy-learning-tools"><summary>Learning tools</summary><nav class="wb-sr-only">{legacy_tabs}</nav>{legacy_empty}<span class="wb-sr-only">Deep Learning Specialization</span><div class="learning-actions"><a data-resume-lesson="{escape(legacy_state['resume_lesson_id'])}" href="/learn/neural-networks-deep-learning/lesson/{escape(legacy_state['resume_lesson_id'])}" title="Continue learning">Continue learning</a><a href="/learning/progress">{completed_count} of {len(learning_db.LESSONS)} lessons completed</a><a href="/learning/bookmarks">Saved lessons ({len(legacy_state['bookmarks'])})</a><span>{certificate}</span></div><section class="legacy-enrollment-cards"><h2>Enrollment management</h2><div class="card-grid">{_enrollment_rows(enrollments)}</div></section><section class="learning-review"><h2>Course review</h2><form class="auth-form" action="/learning/review" method="post"><label>Rating<select name="rating" required>{rating_options}</select></label><label>Review<textarea name="review_text" required>{escape(review_text)}</textarea></label><button type="submit">Save local review</button></form></section></details>"""
        body = source_body + legacy_tools
        return HTMLResponse(
            _page(
                request,
                "My Learning",
                body,
                language="en",
                body_class="authenticated-learning-page",
            )
        )
    requested_status = request.query_params.get("status", "in-progress")
    selected_status = (
        requested_status
        if requested_status in {"in-progress", "completed", "certificates"}
        else "in-progress"
    )
    learning_tools = ""
    state = None
    if learning_db.has_active_enrollment(subject):
        state = learning_db.learning_state(subject)
        completed_count = len(state["completed_lessons"])
        lesson_count = len(learning_db.LESSONS)
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
        learning_tools = f"""<div class="learning-actions"><a data-resume-lesson="{escape(state["resume_lesson_id"])}" href="/learn/neural-networks-deep-learning/lesson/{escape(state["resume_lesson_id"])}">Continue learning</a><a href="/learning/progress">{completed_count} of {lesson_count} lessons completed</a><a href="/learning/bookmarks">Saved lessons ({len(state["bookmarks"])})</a><span>{certificate}</span></div><section class="learning-review"><h2>Course review</h2><p>Your local review can be updated at any time.</p><form class="auth-form" action="/learning/review" method="post"><label>Rating<select name="rating" required>{rating_options}</select></label><label>Review<textarea name="review_text" required>{escape(current_review)}</textarea></label><button type="submit">Save local review</button></form></section>"""
    visible_enrollments = enrollments
    status_empty = ""
    if selected_status in {"completed", "certificates"}:
        visible_enrollments = enrollments if state and state["certificate_available"] else []
        if not visible_enrollments:
            message = (
                "You have no completed courses yet."
                if selected_status == "completed"
                else "You have no certificates yet."
            )
            status_empty = f'<section class="learning-empty-state"><h2>{message}</h2><p>Continue learning to make progress toward this collection.</p></section>'
        learning_tools = ""
    empty_state = "" if enrollments else """<section class="learning-empty-state" aria-labelledby="learning-empty-heading"><svg class="learning-illustration learning-empty-illustration" viewBox="0 0 160 140" role="img" aria-label=""><defs><linearGradient id="li-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#dbe8ff"/><stop offset="1" stop-color="#eef5ff"/></linearGradient><linearGradient id="li-accent" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4d9cff"/><stop offset="1" stop-color="#227af9"/></linearGradient></defs><circle cx="80" cy="70" r="58" fill="url(#li-bg)"/><path d="M52 30h56c5 0 9 4 9 9v52c0 5-4 9-9 9H52c-5 0-9-4-9-9V39c0-5 4-9 9-9z" fill="#fff" stroke="url(#li-accent)" stroke-width="3"/><path d="M58 44h44v14H58z" fill="url(#li-accent)" opacity="0.85"/><path d="M58 66h30v3H58z" fill="#a9c7f5"/><path d="M58 76h36v3H58z" fill="#a9c7f5"/><path d="M104 96l7 7 15-16" fill="none" stroke="#1e9e4a" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="132" cy="30" r="7" fill="#ffd166"/><circle cx="34" cy="106" r="5" fill="#ff9f9f"/><circle cx="38" cy="38" r="4" fill="#b2d8b2"/></svg><h2 id="learning-empty-heading">Start your learning journey</h2><p>Enroll in a course to begin tracking progress in My Learning. Set a career goal for more personalized recommendations.</p><div class="learning-empty-actions"><a class="wb-primary" href="/browse">Explore courses</a><a class="learning-goal-link" href="/onboarding/learning-goal">Set a career goal</a></div></section>"""
    tabs = '<nav class="learning-tabs" aria-label="My Learning sections">' + "".join(
        f'<a class="{"is-active" if selected_status == key else ""}" href="{href}">{label}</a>'
        for key, href, label in (
            ("in-progress", "/my-learning", "In Progress"),
            ("completed", "/my-learning?status=completed", "Completed"),
            ("certificates", "/my-learning?status=certificates", "Certificates"),
        )
    ) + "</nav>"
    selected_goal = str(profile["learning_goal"]).strip()
    goal_copy = (
        escape(selected_goal)
        if selected_goal
        else "Start a career as a Data Scientist, Machine Learning Engineer, Content Creator, or 5 more"
    )
    greeting = f"""<section class="learning-greeting" data-learning-greeting><span class="learning-avatar">L</span><div><h1>Good evening, learner</h1><p>Your career goal: <strong>{goal_copy}</strong> &nbsp; <a href="/onboarding/learning-goal">Edit goal</a></p></div><svg class="learning-illustration learning-greeting-illustration" viewBox="0 0 210 140" role="img" aria-label=""><defs><linearGradient id="lg-halo" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#cfe2ff"/><stop offset="1" stop-color="#eef5ff"/></linearGradient><linearGradient id="lg-head" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3f8cff"/><stop offset="1" stop-color="#1a62c9"/></linearGradient></defs><circle cx="105" cy="70" r="52" fill="url(#lg-halo)"/><circle cx="105" cy="70" r="52" fill="none" stroke="#b8d3ff" stroke-width="2" stroke-dasharray="4 7"/><circle cx="105" cy="60" r="24" fill="url(#lg-head)"/><path d="M73 132c0-26 15-40 32-40s32 14 32 40" fill="url(#lg-head)"/><path d="M96 52l7 8 14-16" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><circle cx="176" cy="34" r="8" fill="#ffd166"/><circle cx="30" cy="40" r="6" fill="#7ec8b7"/></svg></section>"""
    enrolled_content = f"""{learning_tools}{status_empty}<section class="wb-section"><div class="card-grid">{_enrollment_rows(visible_enrollments)}</div></section><nav class="learning-history-links"><a href="/account/preferences">Learning preferences</a><a href="/account/history">Enrollment history</a><a href="/orders">Order history</a></nav>""" if enrollments else ""
    surface_state = "my-learning-enrolled" if enrollments else "my-learning-empty"
    body = f"""<section class="learning-page" data-authenticated-surface="{surface_state}"><h1>My Learning</h1>{greeting}{tabs}{empty_state}{enrolled_content}</section>"""
    return HTMLResponse(_page(request, "My Learning", body, language="en", body_class="authenticated-learning-page"))


@app.get("/my-purchases", response_class=HTMLResponse)
def my_purchases(request: Request) -> Response:
    """Keep the source account-menu destination and its canonical transactions path."""
    try:
        _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view purchases")
    return RedirectResponse("/my-purchases/transactions", status_code=303)


@app.get("/my-purchases/transactions", response_class=HTMLResponse)
def my_purchase_transactions(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view purchases")
    orders = checkout.list_orders(subject)
    order_state = (
        '<p class="empty-state">No purchases found in your history. <a href="/browse">Browse courses offering Certificates now.</a></p>'
        if not orders
        else _order_rows(orders)
    )
    def purchase_card(
        *, title: str, provider: str, kind: str, href: str, image: str
    ) -> str:
        return f"""<a class="purchase-card" href="{escape(href, quote=True)}"><img src="{escape(image, quote=True)}" alt=""><span>{escape(provider)}</span><strong>{escape(title)}</strong><small>{escape(kind)}</small></a>"""

    recent_cards = (
        ("Deep Learning", "DeepLearning.AI", "Specialization", "/specializations/deep-learning", "/static/home/cards/deep-learning.png"),
        ("Neural Networks and Deep Learning", "DeepLearning.AI", "Course", "/learn/neural-networks-deep-learning", "/static/deep-learning/course-neural-networks.png"),
        ("Google AI", "Google", "Professional Certificate", "/professional-certificates/google-ai", "/static/home/cards/google-ai.png"),
    )
    free_course_cards = (
        ("Fundamentals of Machine Learning and Artificial Intelligence", "Amazon Web Services", "Course", "/learn/fundamentals-of-machine-learning-and-artificial-intelligence", "/static/data-science/machine-learning.png"),
        ("ChatGPT Prompt Engineering for Developers", "DeepLearning.AI", "Guided Project", "/projects/chatgpt-prompt-engineering-for-developers-project", "/static/home/cards/prompt-engineering.png"),
        ("Algorithms, Part I", "Princeton University", "Course", "/learn/algorithms-part1", "/static/home/cards/python-3-programming.png"),
        ("LangChain for LLM Application Development", "DeepLearning.AI", "Guided Project", "/projects/langchain-for-llm-application-development-project", "/static/data-science/genai-everyone.png"),
    )
    degree_cards = (
        ("Master of Advanced Study in Engineering", "University of California, Berkeley", "Degree", "/degrees/mas-engineering-berkeley", "/static/browse/lower/degree-berkeley.jpg"),
        ("Master of Science in Data Analytics Engineering", "Northeastern University", "Degree", "/degrees/ms-data-analytics-engineering-northeastern", "/static/browse/lower/degree-northeastern.jpg"),
        ("Bachelor of Science in Computer Science", "University of London", "Degree", "/degrees/bachelor-of-science-computer-science-london", "/static/browse/lower/degree-london.jpg"),
        ("BSc Data Science", "University of Huddersfield", "Degree", "/degrees/bsc-data-science-huddersfield", "/static/browse/lower/degree-huddersfield.jpg"),
    )

    def recommendation_section(
        heading: str,
        cards: tuple[tuple[str, str, str, str, str], ...],
        *, show_more: bool = False,
        more_href: str = "/search",
    ) -> str:
        rendered_cards = "".join(
            purchase_card(
                title=title, provider=provider, kind=kind, href=href, image=image
            )
            for title, provider, kind, href, image in cards
        )
        more = (
            f'<form class="purchase-show-more-form" action="{escape(more_href, quote=True)}" method="get"><button class="purchase-show-more" type="submit">Show 8 more</button></form>'
            if show_more
            else ""
        )
        return f"""<section class="purchase-recommendations"><h2>{escape(heading)}</h2><div class="purchase-card-grid">{rendered_cards}</div>{more}</section>"""

    recommendations = "".join(
        (
            recommendation_section("Recently Viewed Products", recent_cards),
            recommendation_section(
                "Get Started with These Free Courses",
                free_course_cards,
                show_more=True,
                more_href="/search",
            ),
            recommendation_section(
                "Earn Your Degree", degree_cards, show_more=True, more_href="/degrees"
            ),
        )
    )
    body = f"""<section class="purchases-surface"><div class="purchases-content"><h1>Purchases</h1><p>Need more help? Check out our <a href="/help">Learner Help Center</a> and <a href="/terms">Terms of Use</a>.</p><nav class="surface-tabs" aria-label="Purchase sections"><a class="is-active" href="/my-purchases/transactions">Payment History</a></nav><section class="purchase-history">{order_state}</section>{recommendations}</div></section>"""
    return HTMLResponse(_page(request, "My Purchases", body, language="en"))


@app.get("/account-settings", response_class=HTMLResponse)
def account_settings(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view account settings")
    profile = learning_db.get_profile(subject)
    preferences = learning_db.get_preferences(subject)
    timezone_options = ("UTC", "Asia/Shanghai", "Europe/London", "America/Los_Angeles")
    timezone_select = "".join(
        f'<option value="{zone}"{" selected" if zone == preferences["timezone"] else ""}>{zone}</option>'
        for zone in timezone_options
    )
    body = f"""<section class="settings-surface"><h1>Account settings</h1><nav class="settings-tabs"><a class="is-active" href="/account-settings">Account</a><a href="/account/preferences#communication">Communication Preferences</a><a href="/account/preferences#notes">Notes &amp; Highlights</a><a href="/account/preferences#calendar">Calendar Sync</a></nav><section class="settings-card"><h2>Personal information</h2><p>Update your personal details and how others see you.</p><form class="settings-form" action="/account-settings" method="post"><div class="settings-fields"><label>Full name<input name="display_name" value="{escape(str(profile['display_name']), quote=True)}" maxlength="80" required></label><label>Email address<input value="local.learner@coursera.test" readonly></label><label>Timezone<select name="timezone">{timezone_select}</select></label><label>Language<select disabled><option>Select a language</option></select></label></div><button type="submit">Save Changes</button></form></section><section class="settings-card"><h2>Profile photo</h2><p>Maximum size: 1MB. Supported formats: JPG, GIF, or PNG.</p><button type="button" disabled aria-describedby="photo-disabled">Upload image</button><p id="photo-disabled">Profile uploads are unavailable in this offline clone.</p></section><section class="settings-card settings-row"><div><h2>Appearance</h2><p>Personalize the way Coursera appears through theming controls.</p></div><select disabled aria-describedby="appearance-disabled"><option>Light mode</option></select><span id="appearance-disabled">Appearance changes are unavailable offline.</span></section><section class="settings-card"><h2>Name verification</h2><p>Verify your real name to make sure you're able to receive a certificate when you complete a course or Specialization.</p><button type="button" disabled aria-describedby="verification-disabled">Verify my name</button><p id="verification-disabled">Name verification is unavailable offline.</p></section><section class="settings-card"><h2>Change password</h2><p>Update your password regularly to keep your account secure.</p><a class="settings-button" href="/account-recovery">Change Password</a></section><section class="settings-card settings-row"><div><h2>Two factor authentication</h2><p>Two-factor authentication adds an additional layer of security to your local account.</p></div><span class="settings-toggle" aria-label="Off"></span></section><section class="settings-card"><h2>Connected devices</h2><p>If your account has been logged into on multiple devices, you can log out from here.</p><form action="/auth/logout" method="post"><button type="submit">Log out from all devices</button></form></section><section class="settings-card"><h2>Linked accounts</h2><p>Apple and Google remain unlinked in this offline clone.</p></section><section class="settings-card"><h2>Learner data report</h2><p>Request a report of all learner data stored by this local Coursera account.</p><input value="local.learner@coursera.test" readonly><button type="button" disabled aria-describedby="report-disabled">Send report</button><p id="report-disabled">Reports are unavailable offline.</p></section><section class="settings-card danger"><h2>Delete account</h2><p>This action cannot be undone. Cancel any active subscriptions before you delete your account.</p><button type="button" disabled aria-describedby="delete-disabled">Delete account</button><p id="delete-disabled">Account deletion is unavailable offline.</p></section></section>"""
    return HTMLResponse(_page(request, "Account Settings", body, language="en", real_css="consumer-description-page.css"))


@app.post("/account-settings")
async def save_account_settings(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to update account settings")
    values = await _form_values(request)
    try:
        learning_db.update_account_settings(
            subject,
            display_name=values.get("display_name", ""),
            timezone=values.get("timezone", ""),
        )
    except (LookupError, ValueError) as exc:
        return _auth_failure(request, str(exc), status_code=422)
    return RedirectResponse("/account-settings", status_code=303)


@app.get("/updates", response_class=HTMLResponse)
def updates(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view updates")
    preferences = learning_db.get_update_preferences(subject)
    product_checked = " checked" if preferences["product_updates"] else ""
    course_checked = " checked" if preferences["course_updates"] else ""
    body = f"""<section class="updates-surface"><h1>Updates</h1><section class="update-item"><span class="update-logo">C</span><div><small>4 days ago</small><h2>Please confirm your email</h2><p>You've registered for Coursera using your local learner email. Please check the local account guidance and confirm.</p></div></section><section class="settings-card"><h2>Notification preferences</h2><p>Choose which local updates appear in your account. No external messages are sent.</p><form class="auth-form" action="/updates" method="post"><label><input type="checkbox" name="product_updates" value="on"{product_checked}> Product and platform updates</label><label><input type="checkbox" name="course_updates" value="on"{course_checked}> Course and learning updates</label><button type="submit">Save notification preferences</button></form></section></section>"""
    return HTMLResponse(_page(request, "Updates", body, language="en", real_css="consumer-description-page.css"))


@app.post("/updates")
async def save_updates(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to update notifications")
    values = await _form_values(request)
    try:
        learning_db.update_update_preferences(
            subject,
            product_updates=values.get("product_updates") in {"1", "on", "true"},
            course_updates=values.get("course_updates") in {"1", "on", "true"},
        )
    except LookupError as exc:
        return _auth_failure(request, str(exc), status_code=422)
    return RedirectResponse("/updates", status_code=303)


@app.get("/onboarding/learning-goal", response_class=HTMLResponse)
def learning_goal_onboarding(request: Request) -> HTMLResponse:
    try:
        _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to set learning goals")
    body = """<section class="learning-goal-page"><header><a class="wb-wordmark" href="/">coursera</a><a href="/my-learning">Exit</a></header><main><h1>Hello, learner!</h1><h2>Tell me a little about yourself so I can make the best recommendations. First, what's your goal?</h2><form class="goal-grid" action="/onboarding/learning-goal" method="post"><button type="submit" name="learning_goal" value="Start my career"><span>↗</span>Start my career</button><button type="submit" name="learning_goal" value="Change my career"><span>⇄</span>Change my career</button><button type="submit" name="learning_goal" value="Grow in my current role"><span>↗</span>Grow in my current role</button><button type="submit" name="learning_goal" value="Explore topics outside of work"><span>♧</span>Explore topics outside of work</button></form></main></section>"""
    return HTMLResponse(_page(request, "Learning Goals", body, language="en", body_class="learning-goal-document"))


@app.post("/onboarding/learning-goal")
async def save_learning_goal(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to set learning goals")
    values = await _form_values(request)
    selected = values.get("learning_goal", "")
    available = {
        "Start my career",
        "Change my career",
        "Grow in my current role",
        "Explore topics outside of work",
    }
    if selected not in available:
        return HTMLResponse(
            _page(
                request,
                "Learning goal validation",
                "<section class='not-found'><h1>Choose one available learning goal</h1><a href='/onboarding/learning-goal'>Return to learning goals</a></section>",
                language="en",
            ),
            status_code=422,
        )
    profile = learning_db.get_profile(subject)
    learning_db.update_profile(
        subject,
        current_role=str(profile["current_role"]) or "Learner",
        learning_goal=selected,
    )
    return RedirectResponse("/my-learning", status_code=303)


@app.get("/account/history", response_class=HTMLResponse)
def account_history(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view enrollment history")
    body = f"""<section class="page-heading"><p class="eyebrow">Local account history</p><h1>Enrollment history</h1><p>Canceled items remain visible and are shown only to their owner.</p></section><section class="section"><div class="card-grid">{_enrollment_rows(learning_db.list_enrollments(subject))}</div><a href="/orders">View order history</a> · <a href="/my-learning">Back to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Enrollment History", body, language="en", real_css="consumer-description-page.css"))


@app.get("/account/history/{enrollment_id}", response_class=HTMLResponse)
def enrollment_history_detail(request: Request, enrollment_id: int) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view this enrollment")
    try:
        enrollment = learning_db.get_enrollment(subject, enrollment_id)
    except LookupError:
        return HTMLResponse(
            _page(
                request,
                "Enrollment not found",
                '<section class="not-found"><h1>Enrollment not found</h1><p>The record is unavailable for this local learner.</p><a href="/account/history">Back to enrollment history</a></section>',
                language="en",
            ),
            status_code=404,
        )
    status_label = "In progress" if enrollment["status"] == "active" else "Canceled"
    track_label = {"free": "Free learning", "audit": "Audit", "paid": "Paid"}[str(enrollment["track"])]
    action = ""
    if enrollment["status"] == "active":
        if enrollment["track"] == "paid" and enrollment.get("order_id"):
            action = f'<a class="primary-button" href="/orders/{escape(str(enrollment["order_id"]))}">Manage paid order</a>'
        else:
            action = f'<form action="/enrollments/{enrollment_id}/cancel" method="post"><button type="submit">Cancel enrollment</button></form>'
    body = f'<nav class="course-breadcrumbs"><a href="/account/history">Enrollment history</a><span>›</span>{enrollment_id}</nav><section class="page-heading"><p class="eyebrow">{status_label}</p><h1>Enrollment details</h1><p>Deep Learning Specialization</p><p>{track_label} track</p><p>Created {escape(str(enrollment["created_at"]))}</p>{action}<a href="/account/history">Back to enrollment history</a> · <a href="/my-learning">Back to My Learning</a></section>'
    return HTMLResponse(_page(request, "Enrollment Details", body, language="en"))


@app.get("/orders", response_class=HTMLResponse)
def order_history(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view order history")
    records = checkout.list_orders(subject)
    body = f"""<section class="page-heading"><p class="eyebrow">Owner-only local history</p><h1>Order history</h1><p>Only successful local-sandbox checkouts create persistent orders. Canceled snapshots remain visible.</p></section><section class="section"><div class="card-grid">{_order_rows(records)}</div><a href="/my-learning">Back to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Order History", body, language="en", real_css="consumer-description-page.css"))


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
        f"""<form action="/orders/{escape(order_id)}/cancel" method="post"><button type="submit">Cancel local paid enrollment</button></form>"""
        if order["status"] == "PAID"
        else "<p>This order and paid enrollment were canceled; the immutable snapshot remains in history.</p>"
    )
    status_label = "Paid" if order["status"] == "PAID" else "Canceled"
    body = f"""<nav class="course-breadcrumbs"><a href="/orders">Order history</a><span>›</span>{escape(order_id)}</nav><section class="checkout-shell" data-order-status="{escape(str(order["status"]))}"><p class="eyebrow">Local sandbox order</p><h1>{status_label}</h1><p>Order {escape(order_id)}</p><p>Deep Learning Specialization · {escape(str(order["plan_label"]))}</p><p class="safe-note">This immutable local simulation snapshot did not create a real payment or purchase.</p>{_checkout_totals(order)}{cancellation}<a href="/orders">Back to Order history</a><a href="/specializations/deep-learning">Back to Specialization</a></section>"""
    return HTMLResponse(_page(request, "Order Details", body, language="en", real_css="consumer-description-page.css"))


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
    "/learn/neural-networks-deep-learning/home/welcome",
    response_class=HTMLResponse,
)
def enrolled_course_welcome(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    return RedirectResponse(
        "/learn/neural-networks-deep-learning/home/module/1", status_code=303
    )


@app.get(
    "/learn/neural-networks-deep-learning/home/module/{week}",
    response_class=HTMLResponse,
)
def enrolled_course_module(request: Request, week: int) -> HTMLResponse:
    if week not in {1, 2, 3, 4}:
        return _learning_not_found(request)
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    state = assignment_db.course_access(access)
    return _enrolled_response(
        request,
        str(enrolled_course.MODULES[week - 1]["title"]),
        enrolled_page.render_course_home(
            state,
            week,
            weekly_target=learning_db.get_weekly_target(access),
        ),
    )


@app.post("/learn/neural-networks-deep-learning/weekly-target")
async def enrolled_weekly_target(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    values = await _form_values(request)
    try:
        minutes = int(values.get("minutes", ""))
        learning_db.set_weekly_target(access, minutes)
    except (LookupError, TypeError, ValueError) as exc:
        return _enrolled_response(
            request,
            "Weekly learning target",
            enrolled_page.validation_page(
                "Check your weekly target",
                str(exc),
                "/learn/neural-networks-deep-learning/home/module/1",
            ),
            status_code=422,
        )
    return RedirectResponse(
        "/learn/neural-networks-deep-learning/home/module/1", status_code=303
    )


@app.get(
    "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome",
    response_class=HTMLResponse,
)
def enrolled_welcome_lesson(request: Request) -> HTMLResponse:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    assignment_db.mark_lesson_opened(access)
    state = assignment_db.course_access(access)
    return _enrolled_response(
        request,
        "Welcome",
        enrolled_page.render_lesson(
            state,
            reaction=learning_db.get_lesson_reaction(access, "welcome"),
            issue=learning_db.latest_lesson_issue(access, "welcome"),
        ),
    )


@app.post(
    "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome/reaction"
)
async def enrolled_lesson_reaction(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    values = await _form_values(request)
    reaction = values.get("reaction")
    try:
        learning_db.set_lesson_reaction(access, "welcome", reaction)
    except (LookupError, ValueError) as exc:
        return _enrolled_response(
            request,
            "Welcome",
            enrolled_page.validation_page(
                "Check your lesson reaction", str(exc), f"{enrolled_page.COURSE_ROOT}/lecture/Cuf2f/welcome"
            ),
            status_code=422,
        )
    return RedirectResponse(
        "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome",
        status_code=303,
    )


@app.post("/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome/report")
async def enrolled_lesson_report(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    values = await _form_values(request)
    try:
        learning_db.report_lesson_issue(
            access, "welcome", values.get("reason", "")
        )
    except (LookupError, ValueError) as exc:
        return _enrolled_response(
            request,
            "Welcome",
            enrolled_page.validation_page(
                "Check your issue report", str(exc), f"{enrolled_page.COURSE_ROOT}/lecture/Cuf2f/welcome"
            ),
            status_code=422,
        )
    return RedirectResponse(
        "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome",
        status_code=303,
    )


@app.post("/learn/neural-networks-deep-learning/notes")
async def enrolled_save_note(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    values = await _form_values(request)
    try:
        assignment_db.save_note(access, values.get("note_text", ""))
    except ValueError as exc:
        return _enrolled_response(
            request,
            "Welcome",
            enrolled_page.render_lesson(
                assignment_db.course_access(access), note_error=str(exc)
            ),
            status_code=422,
        )
    return RedirectResponse(
        "/learn/neural-networks-deep-learning/home/notes", status_code=303
    )


@app.post("/learn/neural-networks-deep-learning/notes/{note_id}/delete")
def enrolled_delete_note(request: Request, note_id: int) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    try:
        assignment_db.delete_note(access, note_id)
    except LookupError:
        return _learning_not_found(request)
    return RedirectResponse(
        "/learn/neural-networks-deep-learning/home/notes", status_code=303
    )


@app.get(
    "/learn/neural-networks-deep-learning/home/assignments",
    response_class=HTMLResponse,
)
def enrolled_grades(request: Request) -> HTMLResponse:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    return _enrolled_response(
        request,
        "Grades",
        enrolled_page.render_grades(assignment_db.gradebook(access)),
    )


@app.get(
    "/learn/neural-networks-deep-learning/home/notes",
    response_class=HTMLResponse,
)
def enrolled_notes(request: Request) -> HTMLResponse:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    query = request.query_params.get("q", "")
    return _enrolled_response(
        request,
        "Notes",
        enrolled_page.render_notes(assignment_db.list_notes(access, query), query),
    )


@app.get(
    "/learn/neural-networks-deep-learning/course-inbox",
    response_class=HTMLResponse,
)
def enrolled_messages(request: Request) -> HTMLResponse:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    return _enrolled_response(request, "Messages", enrolled_page.render_messages())


@app.get(
    "/learn/neural-networks-deep-learning/home/info",
    response_class=HTMLResponse,
)
def enrolled_course_info(request: Request) -> HTMLResponse:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    return _enrolled_response(
        request, "Course Info", enrolled_page.render_course_info()
    )


@app.get(
    "/learn/neural-networks-deep-learning/resources/{resource_id}",
    response_class=HTMLResponse,
)
def enrolled_resource(request: Request, resource_id: str) -> HTMLResponse:
    if resource_id not in {str(item["id"]) for item in enrolled_course.RESOURCES}:
        return _learning_not_found(request)
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    return _enrolled_response(
        request, "Resource", enrolled_page.render_resource(resource_id)
    )


ASSIGNMENT_PATH = (
    "/learn/neural-networks-deep-learning/assignment-submission/3KFZW/"
    "introduction-to-deep-learning"
)


@app.get(ASSIGNMENT_PATH, response_class=HTMLResponse)
def enrolled_assignment_entry(request: Request) -> HTMLResponse:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    return _enrolled_response(
        request,
        "Introduction to Deep Learning",
        enrolled_page.render_assignment_entry(),
    )


@app.post(f"{ASSIGNMENT_PATH}/start")
async def enrolled_assignment_start(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    values = await _form_values(request)
    if values.get("honor_code") != "accepted":
        return _enrolled_response(
            request,
            "Introduction to Deep Learning",
            enrolled_page.render_assignment_entry(
                error="Agree to the Coursera Honor Code before starting"
            ),
            status_code=422,
        )
    try:
        assignment_db.start_or_resume_attempt(access)
    except ValueError as exc:
        return _enrolled_response(
            request,
            "Introduction to Deep Learning",
            enrolled_page.render_assignment_entry(error=str(exc)),
            status_code=422,
        )
    return RedirectResponse(f"{ASSIGNMENT_PATH}/attempt", status_code=303)


@app.get(f"{ASSIGNMENT_PATH}/attempt", response_class=HTMLResponse)
def enrolled_assignment_attempt(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    try:
        attempt = assignment_db.current_attempt(access)
    except LookupError:
        return RedirectResponse(ASSIGNMENT_PATH, status_code=303)
    if attempt["status"] == "submitted":
        return RedirectResponse(
            f"{ASSIGNMENT_PATH}/result/{attempt['attempt_id']}", status_code=303
        )
    return _enrolled_response(
        request,
        "Introduction to Deep Learning",
        enrolled_page.render_assignment_attempt(
            attempt, saved=request.query_params.get("saved") == "1"
        ),
    )


@app.post(f"{ASSIGNMENT_PATH}/attempt/draft")
async def enrolled_assignment_draft(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    try:
        attempt_id, _legal_name, answers = await _assignment_form(request)
        saved = assignment_db.save_draft(access, attempt_id, answers)
    except (LookupError, ValueError) as exc:
        try:
            current = assignment_db.current_attempt(access)
        except LookupError:
            return _learning_not_found(request)
        return _enrolled_response(
            request,
            "Check your answers",
            enrolled_page.render_assignment_attempt(current, error=str(exc)),
            status_code=422,
        )
    if saved["status"] == "submitted":
        return RedirectResponse(
            f"{ASSIGNMENT_PATH}/result/{saved['attempt_id']}", status_code=303
        )
    return RedirectResponse(f"{ASSIGNMENT_PATH}/attempt?saved=1", status_code=303)


@app.post(f"{ASSIGNMENT_PATH}/attempt/submit")
async def enrolled_assignment_submit(request: Request) -> Response:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    try:
        attempt_id, legal_name, answers = await _assignment_form(request)
        result = assignment_db.submit_attempt(
            access, attempt_id, answers, legal_name
        )
    except (LookupError, ValueError) as exc:
        try:
            current = assignment_db.current_attempt(access)
        except LookupError:
            return _learning_not_found(request)
        current["answers"] = answers if "answers" in locals() else current["answers"]
        return _enrolled_response(
            request,
            "Check your answers",
            enrolled_page.render_assignment_attempt(current, error=str(exc)),
            status_code=422,
        )
    return RedirectResponse(
        f"{ASSIGNMENT_PATH}/result/{result['attempt_id']}", status_code=303
    )


@app.get(f"{ASSIGNMENT_PATH}/result/{{attempt_id}}", response_class=HTMLResponse)
def enrolled_assignment_result(request: Request, attempt_id: str) -> HTMLResponse:
    access = _enrolled_subject(request)
    if isinstance(access, HTMLResponse):
        return access
    try:
        result = assignment_db.get_attempt(access, attempt_id)
    except LookupError:
        return _learning_not_found(request)
    if result["status"] != "submitted":
        return _learning_not_found(request)
    return _enrolled_response(
        request,
        "Assignment Result",
        enrolled_page.render_assignment_result(result),
    )


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


@app.get("/learning/bookmarks", response_class=HTMLResponse)
def learning_bookmarks(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view saved lessons")
    if not learning_db.has_active_enrollment(subject):
        return _enrollment_required_page(request, "Enroll locally to view saved lessons")
    state = learning_db.learning_state(subject)
    rows = "".join(
        f'<article class="catalog-card"><h2>{escape(str(learning_db.get_lesson(lesson_id)["title"]))}</h2><a href="/learn/neural-networks-deep-learning/lesson/{escape(lesson_id)}">Open saved lesson</a></article>'
        for lesson_id in state["bookmarks"]
    )
    if not rows:
        rows = '<div class="empty-state"><h2>No saved lessons yet</h2><p>Use Bookmark lesson while learning to add one here.</p></div>'
    body = f'<section class="page-heading"><p class="eyebrow">My Learning</p><h1>Saved lessons</h1><p>Bookmarks are private to this local learner.</p></section><section class="section"><div class="card-grid">{rows}</div><a href="/my-learning">Back to My Learning</a></section>'
    return HTMLResponse(_page(request, "Saved Lessons", body, language="en"))


@app.get("/learning/progress", response_class=HTMLResponse)
def learning_progress_collection(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view course progress")
    if not learning_db.has_active_enrollment(subject):
        return _enrollment_required_page(request, "Enroll locally to view course progress")
    state = learning_db.learning_state(subject)
    completed = set(state["completed_lessons"])
    total = len(learning_db.LESSONS)
    count = len(completed)
    percent = round(count * 100 / total)
    resume = learning_db.get_lesson(str(state["resume_lesson_id"]))
    rows = "".join(
        f'<li><span>{"Completed" if lesson_id in completed else "Not completed"}</span> <a href="/learn/neural-networks-deep-learning/lesson/{escape(lesson_id)}">{escape(title)}</a></li>'
        for lesson_id, _module_id, _position, title, _body, _preview in learning_db.LESSONS
    )
    body = f'<section class="page-heading"><p class="eyebrow">My Learning</p><h1>Course progress</h1><p><strong>{count} of {total} lessons completed</strong> · {percent}%</p><p>Resume at <a href="/learn/neural-networks-deep-learning/lesson/{escape(str(state["resume_lesson_id"]))}">{escape(str(resume["title"]))}</a></p></section><section class="section"><ol>{rows}</ol><a href="/my-learning">Back to My Learning</a></section>'
    return HTMLResponse(_page(request, "Course Progress", body, language="en"))


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
            ),
            status_code=422,
        )
    body = f"""<section class="page-heading"><p class="eyebrow">Local quiz feedback</p><h1>Quiz score: {attempt["score"]}</h1><p>{escape(attempt["feedback"])}</p><a href="/my-learning">Back to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Quiz Feedback", body, language="en"))


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
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local learning settings</p><h1>Learning preferences</h1><nav class="settings-tabs preferences-tabs"><a href="/account/preferences#communication">Communication Preferences</a><a href="/account/preferences#notes">Notes &amp; Highlights</a><a href="/account/preferences#calendar">Calendar Sync</a></nav>
<section id="communication" class="settings-card"><h2>Communication Preferences</h2><p>Choose which local reminders and announcements you receive.</p><form class="auth-form" action="/account/preferences" method="post"><label>Language<input name="language" value="{escape(preferences["language"])}" required></label><label>Time zone<input name="timezone" value="{escape(preferences["timezone"])}" required></label><label><input type="checkbox" name="email_updates" value="1"{checked}>Local learning reminders</label><button type="submit">Save preferences</button></form></section>
<section id="notes" class="settings-card"><h2>Notes &amp; Highlights</h2><p>Notes and highlights you create while learning stay in this local clone and are never sent to a server.</p><p class="safe-note">Offline note-taking is available from any lesson page.</p></section>
<section id="calendar" class="settings-card"><h2>Calendar Sync</h2><p>Sync your learning schedule to your local calendar.</p><button type="button" disabled aria-describedby="calendar-disabled">Connect calendar</button><p id="calendar-disabled">Calendar sync is unavailable in this offline clone.</p></section></div></section>"""
    return HTMLResponse(_page(request, "Learning Preferences", body, language="en", real_css="consumer-description-page.css"))


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
            ),
            status_code=422,
        )
    return RedirectResponse("/account/preferences", status_code=303)


@app.get("/account-recovery", response_class=HTMLResponse)
def account_recovery(request: Request) -> HTMLResponse:
    body = """<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Account access</p><h1>Reset your Coursera password</h1><p>No reset message is sent outside this offline site. Use a synthetic .test address; the public response does not reveal whether an account exists.</p><form class="auth-form" action="/auth/recovery/start" method="post" autocomplete="off"><label>Account email<input type="email" name="address" placeholder="learner@coursera.test" required></label><p class="field-guidance">If the local account matches, verification guidance appears only in this browser's local inbox.</p><button type="submit">Open local recovery</button></form><a href="/login">Return to sign in</a></div></section>"""
    backend, _auth, token, _session = _request_session(request)
    response = HTMLResponse(_page(request, "Password Recovery", body, language="en"))
    _set_session_cookie(response, backend, token)
    return response


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
    feedback = None
    if _request_authenticated(request):
        try:
            _backend, _auth, _token, subject = _authenticated_subject(request)
            feedback = learning_db.get_help_feedback(subject)
        except HTTPException:
            feedback = None
    feedback_status = (
        "<p class='help-feedback-status'>Thanks for your feedback.</p>"
        if feedback is not None
        else ""
    )
    account_controls = (
        '<nav class="help-account-nav"><a href="/my-learning">My Learning</a><form action="/auth/logout" method="post"><button type="submit">Log out</button></form></nav>'
        if _request_authenticated(request)
        else '<nav class="help-account-nav"><a href="/login">Log In</a><a class="help-join" href="/signup">Join for Free</a></nav>'
    )
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Learner Help Center | Coursera</title><link rel="stylesheet" href="/static/coursera/cds-variables.css"><link rel="stylesheet" href="/static/coursera/fonts.css"><link rel="stylesheet" href="/static/coursera/front-page.css"><link rel="stylesheet" href="/static/desktop-base.css"><link rel="stylesheet" href="/static/course-desktop.css"></head>
<body class="help-center-page"><div class="help-center-hero"><header class="help-center-header"><a class="help-wordmark" href="/">coursera</a><span class="help-center-title">Learner Help Center</span>{account_controls}</header>
<section class="help-center-search"><h1>Learner Help Center</h1><form action="/help" method="get" role="search"><label class="wb-sr-only" for="help-search">Search for help</label><input id="help-search" name="q" placeholder="Search for help"><button type="submit">Search</button></form><p class="help-hero-tagline">Find answers to common questions about courses, accounts, payments, and more.</p></section></div>
<main class="help-article-shell"><nav class="help-breadcrumbs"><a href="/help">Learner Help Center</a><span>›</span><a href="/help#account">Account &amp; notifications</a><span>›</span><span>Troubleshooting login and account issues</span></nav><article class="help-article"><h1>Troubleshooting login and account issues</h1><p><em>Reading time: 3 minutes</em></p><p>This article can help you troubleshoot:</p><ul><li>Login issues on Coursera.</li><li>Issues with verifying or changing your email.</li></ul><p>If you want to reset your password, see <a href="/account-recovery">Reset your Coursera password</a>.</p><p>If you are part of an organization’s learning program that uses single sign-on, use <a href="/login">single sign-on guidance to log in</a>.</p><aside class="help-skip"><strong>Skip to:</strong><ul><li><a href="#unable">Unable to log in</a><ul><li>Error message: “We couldn't find an account associated with that email address”</li><li>Log in using SSO</li></ul></li><li><a href="#email">Issues selecting images after log in</a></li><li><a href="#verify">I can't verify my email</a></li><li><a href="#change">Changes to your Coursera email</a></li></ul></aside><h2 id="unable">Unable to log in</h2><blockquote><p>If you’re having trouble logging in, follow these steps:</p></blockquote><ol><li>Double check your email address for misspellings. The email address must match exactly what you typed in when you signed up.</li><li>Use the steps in our article on <a href="/account-recovery">resetting your password</a>.</li><li>Return to <a href="/login">Coursera sign in</a> without submitting credentials here.</li></ol><h2 id="account">Account access and failed actions</h2><p>Account access, registration, password recovery, checkout errors and failed actions are represented locally. No private account data is exposed.</p><p><a href="/browse">Browse course catalog</a> · <a href="/search">Search course catalog</a> · <a href="/about/contact">Contact support</a></p><section id="terms"><h2>Terms and privacy</h2><p>Continuing in this clone uses local WebsiteBench data only. No private account data is exposed.</p></section></article><aside class="help-floating"><strong>New! Search with AI</strong><button type="button" disabled aria-describedby="help-ai-disabled">×</button><span id="help-ai-disabled">AI help is unavailable offline.</span><p>Ask a question and get an instant answer.</p></aside><aside class="help-feedback"><strong>Was this article helpful?</strong>{feedback_status}<form action="/help/feedback" method="post"><button type="submit" name="helpful" value="yes">👍 Yes</button><button type="submit" name="helpful" value="no">👎 No</button></form></aside></main></body></html>"""
    return body


@app.post("/help/feedback")
async def help_feedback(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to leave help feedback")
    values = await _form_values(request)
    helpful = values.get("helpful")
    if helpful not in {"yes", "no"}:
        return _auth_failure(request, "Choose yes or no for help feedback", status_code=422)
    learning_db.save_help_feedback(subject, helpful=helpful == "yes")
    return RedirectResponse("/help", status_code=303)


@app.get("/about/contact", response_class=HTMLResponse)
def contact(request: Request) -> str:
    body = """<section class="source-contact-hero"><h1>Contact Us</h1><p>Have questions? The quickest way to get in touch with us is using the contact information below.</p></section><div class="source-contact-shell"><section class="source-contact-learners"><h2>Learner Support</h2><p>If you are a learner and need help, please visit our <a href="/help">Learner Help Center</a> to find troubleshooting and FAQs or contact our Learner Support team. You can search for your issue or check out our most popular articles:</p><ul><li>Check and update your email communication preferences</li><li>Verify your ID</li><li>How to solve problems with peer-graded assignments</li><li>Cancel a subscription</li><li>Refund policies</li><li>Troubleshooting login and account issues</li></ul></section><section class="source-contact-inquiries"><h2>Inquiries</h2><div><article><h3>Coursera for Campus Inquiries</h3><p>For universities interested in enhancing curriculum with world-class content.</p></article><article><h3>Coursera for Business Inquiries</h3><p>For organizations interested in training teams with world-class content.</p></article><article><h3>Coursera for Government Inquiries</h3><p>For government entities interested in upskilling or reskilling citizens or employees.</p></article><article><h3>Privacy Inquiries</h3><p>Read our <a href="/privacy">Privacy Notice</a> for information about local data.</p></article><article><h3>Press Inquiries</h3><p>General press guidance is available without sending a message.</p></article><article><h3>Special Concerns</h3><p>Security and user privacy guidance remains available locally.</p></article></div></section><section class="source-contact-partnerships"><h2>Partnerships</h2><div><article><h3>University Partnership Inquiries</h3><p>For universities interested in creating certificates or degrees.</p><a href="/help">Apply here →</a></article><article><h3>Industry Partnership Inquiries</h3><p>For companies interested in creating Professional Certificates.</p><a href="/help">Contact Us →</a></article></div></section></div>"""
    return _page(
        request,
        "Contact",
        body,
        body_class="source-contact-page",
        language="en",
        footer_variant="source-course",
        real_css="front-page.css",
    )

