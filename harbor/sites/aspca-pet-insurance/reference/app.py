"""ASPCA Pet Health Insurance offline clone — FastAPI composition root.

Layout (tripit golden-sample shape):

* Frozen localized marketing pages (``frontend/pages/*.html``) served at their
  real source routes; every unmatched path renders the captured not-found page.
* The quote funnel (``/quote/`` + hash routes) and portal (``/portal/``) are
  SPA shells whose view fragments were mechanically extracted from the capture
  (``frontend/quote/views``, ``frontend/portal/views``); behavior is
  re-implemented locally in ``static/site/{quote-app.js,portal-app.js}``
  against the JSON API below.
* The JSON API prices plans with the frozen rating table
  (``backend/model.json`` via ``backend/rating.py``) and persists quotes /
  pets / enrollments through the vendored ``websitebench.site_backend``
  runtime (``backend/quotes_db.py``). ZERO payment fields anywhere — the
  source walk stopped before payment and the insert paths reject card-like
  keys defensively.
* ``GET /healthz`` returns exactly ``{"ok":true,"site_id":"aspca-pet-insurance"}``.
* ``POST /__admin/reset`` is guarded by a constant-time admin-token compare.
* Every response carries a same-origin Content-Security-Policy; no remote
  origin is reachable at runtime.
"""

from __future__ import annotations

import hmac
import html
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:  # vendored websitebench + backend imports
    sys.path.insert(0, str(ROOT))

from backend import quotes_db as db  # noqa: E402
from backend import rating  # noqa: E402
from backend.quotes_db import PaymentFieldRejected  # noqa: E402
from backend.rating import RatingError  # noqa: E402

SITE_ID = "aspca-pet-insurance"
PAGES_DIR = ROOT / "frontend" / "pages"
QUOTE_DIR = ROOT / "frontend" / "quote"
PORTAL_DIR = ROOT / "frontend" / "portal"
STATIC_DIR = ROOT / "static"

_HEALTH_BODY = json.dumps({"ok": True, "site_id": SITE_ID}, separators=(",", ":"))

# Real source route -> frozen fixture page (captured anonymously, localized).
PAGE_ROUTES: dict[str, str] = {
    "/": "home",
    "/pet-insurance-plan/": "pet-insurance-plan",
    "/cat-insurance/": "cat-insurance",
    "/dog-insurance/": "dog-insurance",
    "/why-us/": "why-us",
    "/research-and-compare/": "research-and-compare",
    "/about-us/": "about-us",
    "/about-us/contact-us/": "support",
}

# Admin token for /__admin/reset. Non-secret dev default for local runs;
# deployments inject the real value via the environment. Never logged.
ADMIN_TOKEN = os.environ.get(
    "WEBSITEBENCH_ASPCA_ADMIN_TOKEN", "aspca-local-admin"
)

BUILD_ID = os.environ.get("DEPLOYMENT_BUILD_ID") or os.environ.get(
    "WEBSITEBENCH_BUILD_ID"
)

# Same-origin CSP: the captured documents carry inline styles, so
# 'unsafe-inline' stays; the load-bearing property is that no remote origin is
# reachable (default-src 'self') — zero remote runtime requests.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

_VIEW_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
# Exact ng-pattern from the captured quote-start form (views-report.json);
# Angular tests with JS RegExp.test, i.e. unanchored-start search semantics.
EMAIL_RE = re.compile(r"[a-z0-9A-Z._%+-]+@[a-z0-9A-Z.-]+\.[a-zA-Z]{2,4}$")
REQUIRED_PET_FIELDS = ("species", "name", "age_label", "gender", "breed")

_PAGE_CACHE: dict[str, str] = {}


def _load_page(name: str) -> str:
    cached = _PAGE_CACHE.get(name)
    if cached is None:
        cached = (PAGES_DIR / f"{name}.html").read_text(encoding="utf-8")
        _PAGE_CACHE[name] = cached
    return cached


def _fragment(directory: Path, name: str) -> Response:
    if not _VIEW_NAME_RE.match(name):
        return _not_found_response()
    path = directory / "views" / f"{name}.html"
    if not path.is_file():
        return _not_found_response()
    return HTMLResponse(path.read_text(encoding="utf-8"))


def _not_found_response() -> HTMLResponse:
    try:
        body = _load_page("not-found")
    except FileNotFoundError:  # pre-build fallback, never expected in release
        body = "<!doctype html><title>Not found</title><h1>Not found</h1>"
    return HTMLResponse(body, status_code=404)


_EXTERNAL_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>External link boundary</title></head>
<body style="font-family: sans-serif; max-width: 40rem; margin: 4rem auto;">
<h1>External link</h1>
<p>This offline clone does not open third-party destinations. The original
page linked to an external site ({slug}). No remote request was made.</p>
<p><a href="/">Return to the home page</a></p>
</body>
</html>
"""

app = FastAPI(
    title="ASPCA Pet Health Insurance offline clone",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class _MirrorStaticFiles(StaticFiles):
    """StaticFiles that retries percent-encoded on-disk names.

    The asset closure preserves the source URL's percent-encoding; Starlette
    URL-decodes the request path before lookup, so the decoded name can miss
    the byte-exact encoded file. Retry with each segment re-encoded; anything
    else still 404s (never masks a genuine closure gap).
    """

    def lookup_path(self, path: str) -> "tuple[str, os.stat_result | None]":
        full_path, stat_result = super().lookup_path(path)
        if stat_result is not None:
            return full_path, stat_result
        requoted = "/".join(urllib.parse.quote(seg) for seg in path.split("/"))
        if requoted != path:
            retry_path, retry_stat = super().lookup_path(requoted)
            if retry_stat is not None:
                return retry_path, retry_stat
        return full_path, stat_result


app.mount("/static", _MirrorStaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def runtime_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if BUILD_ID:
        response.headers["X-WebsiteBench-Build-Id"] = BUILD_ID
    return response


@app.get("/healthz", include_in_schema=False)
async def healthz() -> Response:
    return Response(content=_HEALTH_BODY, media_type="application/json")


@app.post("/__admin/reset", include_in_schema=False)
async def admin_reset(request: Request) -> Response:
    token = request.headers.get("X-WebsiteBench-Admin-Token", "")
    if not hmac.compare_digest(token, ADMIN_TOKEN):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    db.reset()
    return JSONResponse({"reset": True, "site_id": SITE_ID})


@app.get("/external/{slug}", include_in_schema=False)
async def external_boundary(slug: str) -> HTMLResponse:
    # Local boundary for third-party navigation targets: the clone never
    # proxies out, so every off-site affordance lands on this same-origin page.
    safe = html.escape(slug[:80])
    return HTMLResponse(_EXTERNAL_PAGE_TEMPLATE.format(slug=safe))


# ---------------------------------------------------------------------------
# frozen marketing pages
# ---------------------------------------------------------------------------


def _register_page(route: str, name: str) -> None:
    @app.get(route, include_in_schema=False)
    async def frozen_page(_name: str = name) -> HTMLResponse:
        return HTMLResponse(_load_page(_name))


for _route, _name in PAGE_ROUTES.items():
    _register_page(_route, _name)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> Response:
    if request.url.path.startswith(("/api/", "/portal/api/")):
        return JSONResponse({"error": "not-found"}, status_code=404)
    return _not_found_response()


# ---------------------------------------------------------------------------
# SPA shells + captured view fragments
# ---------------------------------------------------------------------------


@app.get("/quote/", include_in_schema=False)
@app.get("/quote", include_in_schema=False)
async def quote_shell() -> HTMLResponse:
    return HTMLResponse((QUOTE_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/quote/views/{name}", include_in_schema=False)
async def quote_view(name: str) -> Response:
    return _fragment(QUOTE_DIR, name)


@app.get("/portal/", include_in_schema=False)
@app.get("/portal", include_in_schema=False)
async def portal_shell() -> HTMLResponse:
    return HTMLResponse((PORTAL_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/portal/views/{name}", include_in_schema=False)
async def portal_view(name: str) -> Response:
    return _fragment(PORTAL_DIR, name)


# ---------------------------------------------------------------------------
# quote-funnel JSON API
# ---------------------------------------------------------------------------


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _pet_payload(body: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Validate pet fields; returns (pet, errors)."""

    pet: dict[str, str] = {}
    errors: dict[str, str] = {}
    aliases = {"age_label": ("age_label", "age")}
    for field in REQUIRED_PET_FIELDS:
        value = ""
        for key in aliases.get(field, (field,)):
            value = _string(body.get(key))
            if value:
                break
        if not value:
            errors[field] = "This field is required."
        else:
            pet[field] = value[:120]
    return pet, errors


def _rates_block(quote: dict) -> dict:
    first = quote["pets"][0]["selection"] if quote["pets"] else None
    return {"tiers": quote["tiers"], "selection": first}


@app.post("/api/quotes", include_in_schema=False)
async def create_quote(request: Request) -> JSONResponse:
    body = await _json_body(request)
    try:
        db.reject_payment_keys(body)
    except PaymentFieldRejected as exc:
        return JSONResponse({"errors": {"payment": str(exc)}}, status_code=422)
    pet, errors = _pet_payload(body)
    email = _string(body.get("email"))
    zip_code = _string(body.get("zip"))
    if not email:
        errors["email"] = "This field is required."
    elif not EMAIL_RE.search(email):
        errors["email"] = "Please enter a valid email address."
    if not zip_code:
        errors["zip"] = "This field is required."
    elif not rating.valid_zip(zip_code):
        return JSONResponse(
            {
                "eligible": False,
                "errors": {"zip": rating.zip_error_message(zip_code)},
            },
            status_code=422,
        )
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    quote = db.create_quote(pet, email, zip_code)
    return JSONResponse(
        {
            "quote_id": quote["quote_id"],
            "eligible": True,
            "pet": quote["pets"][0],
            "rates": _rates_block(quote),
        },
        status_code=201,
    )


@app.get("/api/quotes/search", include_in_schema=False)
async def search_quotes(request: Request) -> JSONResponse:
    email = _string(request.query_params.get("email"))
    zip_code = _string(request.query_params.get("zip"))
    if not email or not zip_code:
        return JSONResponse(
            {"errors": {"query": "email and zip are required"}}, status_code=422
        )
    quote = db.find_quote(email, zip_code)
    if quote is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(quote)


@app.get("/api/quotes/{quote_id}", include_in_schema=False)
async def get_quote(quote_id: str) -> JSONResponse:
    quote = db.get_quote(quote_id)
    if quote is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(quote)


@app.post("/api/quotes/{quote_id}/rate", include_in_schema=False)
async def rate_quote(quote_id: str, request: Request) -> JSONResponse:
    body = await _json_body(request)

    def _intval(key: str, fallback: int) -> int:
        raw = body.get(key, fallback)
        try:
            return int(str(raw).replace(",", "").replace("$", ""))
        except ValueError:
            return -1

    preventive = body.get("preventive")
    if preventive in ("", "none"):
        preventive = None
    pet_id = body.get("pet_id")
    try:
        priced = db.apply_rate(
            quote_id,
            _intval("limit", _intval("annual_limit", 5000)),
            _intval("deductible", 500),
            _intval("reimbursement", 80),
            preventive,
            pet_id=int(pet_id) if pet_id is not None else None,
        )
    except (RatingError, ValueError) as exc:
        return JSONResponse({"errors": {"rate": str(exc)}}, status_code=422)
    if priced is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(priced)


@app.post("/api/quotes/{quote_id}/pets", include_in_schema=False)
async def add_pet(quote_id: str, request: Request) -> JSONResponse:
    body = await _json_body(request)
    try:
        db.reject_payment_keys(body)
    except PaymentFieldRejected as exc:
        return JSONResponse({"errors": {"payment": str(exc)}}, status_code=422)
    pet, errors = _pet_payload(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    quote = db.add_pet(quote_id, pet)
    if quote is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(quote, status_code=201)


@app.post("/api/quotes/{quote_id}/enroll", include_in_schema=False)
async def enroll(quote_id: str, request: Request) -> JSONResponse:
    body = await _json_body(request)
    try:
        db.reject_payment_keys(body)
    except PaymentFieldRejected as exc:
        return JSONResponse({"errors": {"payment": str(exc)}}, status_code=422)
    frequency = _string(body.get("frequency")) or "Monthly"
    agree_terms = bool(body.get("agree_terms"))
    paperless = bool(body.get("paperless"))
    contact_source = body.get("contact")
    if not isinstance(contact_source, dict):
        contact_source = {
            k: v
            for k, v in body.items()
            if k not in ("frequency", "agree_terms", "paperless")
        }
    try:
        db.reject_payment_keys(contact_source)
    except PaymentFieldRejected as exc:
        return JSONResponse({"errors": {"payment": str(exc)}}, status_code=422)
    contact = {
        str(k)[:64]: _string(v)[:200]
        for k, v in contact_source.items()
        if isinstance(v, (str, int, float, bool))
    }
    errors: dict[str, str] = {}
    if not agree_terms:
        errors["agreeTerms"] = "You must agree to the terms to continue."
    if frequency not in ("Monthly", "Annually"):
        errors["frequency"] = "Choose Monthly or Annually."
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    result = db.enroll(quote_id, contact, frequency, agree_terms, paperless)
    if result is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(
        {"policy_number": result["policy_number"]},
        status_code=200 if result.get("already") else 201,
    )


# ---------------------------------------------------------------------------
# portal API — anonymous-only clone; member area is not reproduced
# ---------------------------------------------------------------------------

_PORTAL_UNAVAILABLE = (
    "Member account access is not available in this offline clone."
)


@app.post("/portal/api/login", include_in_schema=False)
async def portal_login(request: Request) -> JSONResponse:
    body = await _json_body(request)
    errors: dict[str, str] = {}
    if not _string(body.get("email")) and not _string(body.get("username")):
        errors["email"] = "This field is required."
    if not _string(body.get("password")):
        errors["password"] = "This field is required."
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    return JSONResponse(
        {"authenticated": False, "message": _PORTAL_UNAVAILABLE}, status_code=403
    )


@app.post("/portal/api/forgot-password", include_in_schema=False)
async def portal_forgot_password(request: Request) -> JSONResponse:
    body = await _json_body(request)
    email = _string(body.get("email"))
    if not email:
        return JSONResponse(
            {"errors": {"email": "This field is required."}}, status_code=422
        )
    return JSONResponse(
        {"sent": False, "message": _PORTAL_UNAVAILABLE}, status_code=403
    )


@app.post("/portal/api/register", include_in_schema=False)
async def portal_register(request: Request) -> JSONResponse:
    body = await _json_body(request)
    errors: dict[str, str] = {}
    for field in ("email", "password"):
        if not _string(body.get(field)):
            errors[field] = "This field is required."
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    return JSONResponse(
        {"registered": False, "message": _PORTAL_UNAVAILABLE}, status_code=403
    )
