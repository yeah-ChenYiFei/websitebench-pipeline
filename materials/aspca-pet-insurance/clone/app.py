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
  runtime (``backend/quotes_db.py``). The source walk stopped before payment;
  a clone-local local-sandbox step accepts only an opaque scenario id and
  rejects credentials plus client-supplied payment facts.
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
from decimal import Decimal, InvalidOperation
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
from websitebench.site_backend import MailError, PaymentError  # noqa: E402
from websitebench.local_clone_auth import (  # noqa: E402
    AuthConflict,
    AuthError,
    AuthRejected,
    AuthValidationError,
)

SITE_ID = "aspca-pet-insurance"
PAGES_DIR = ROOT / "frontend" / "pages"
QUOTE_DIR = ROOT / "frontend" / "quote"
PORTAL_DIR = ROOT / "frontend" / "portal"
STATIC_DIR = ROOT / "static"

_HEALTH_BODY = json.dumps({"ok": True, "site_id": SITE_ID}, separators=(",", ":"))
_MARKETING_RUNTIME_TAG = (
    '<script src="/static/site/marketing-app.js" defer></script>'
)

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
        if _MARKETING_RUNTIME_TAG not in cached:
            if "</body>" in cached:
                cached = cached.replace(
                    "</body>", f"{_MARKETING_RUNTIME_TAG}</body>", 1
                )
            else:
                cached = f"{cached}{_MARKETING_RUNTIME_TAG}"
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
            "email": quote["email"],
            "zip": quote["zip"],
            "state": quote["state"],
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
    return JSONResponse({**quote, "rates": _rates_block(quote)})


@app.get("/api/quotes/{quote_id}", include_in_schema=False)
async def get_quote(quote_id: str) -> JSONResponse:
    quote = db.get_quote(quote_id)
    if quote is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse({**quote, "rates": _rates_block(quote)})


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
    scenario_id = _string(body.get("scenario_id"))
    agree_terms = bool(body.get("agree_terms"))
    paperless = bool(body.get("paperless"))
    contact_source = body.get("contact")
    if not isinstance(contact_source, dict):
        contact_source = {
            k: v
            for k, v in body.items()
            if k not in ("frequency", "agree_terms", "paperless", "scenario_id")
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
    if not scenario_id:
        errors["scenario_id"] = "Choose a local payment simulation."
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    try:
        result = db.enroll(
            quote_id,
            contact,
            frequency,
            agree_terms,
            paperless,
            scenario_id,
        )
    except (PaymentError, MailError, ValueError) as exc:
        return JSONResponse({"errors": {"payment": str(exc)}}, status_code=422)
    if result is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    if not result["enrolled"]:
        status_code = 402 if result["payment"]["status"] == "DECLINED" else 409
        return JSONResponse(result, status_code=status_code)
    enrolled_quote = db.get_quote(quote_id)
    assert enrolled_quote is not None
    pet = enrolled_quote["pets"][0]
    selection = pet["selection"]
    return JSONResponse(
        {
            "policy_number": result["policy_number"],
            "payment": result["payment"],
            "mail": result["mail"],
            "summary": {
                "pet_name": pet["name"],
                "annual_limit": selection["annual_limit"],
                "deductible": selection["deductible"],
                "reimbursement": selection["reimbursement"],
                "frequency": frequency,
                "amount": (
                    f"{Decimal(result['payment']['amount_minor']) / Decimal(100):.2f}"
                ),
                "currency": result["payment"]["currency"],
            },
        },
        status_code=200 if result.get("already") else 201,
    )


@app.get("/api/quotes/{quote_id}/eligibility", include_in_schema=False)
async def quote_eligibility(quote_id: str) -> JSONResponse:
    quote = db.get_quote(quote_id)
    if quote is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(
        {
            "eligible": True,
            "zip": quote["zip"],
            "state": quote["state"],
            "enrollment_fee": "0.00",
            "currency": "USD",
        }
    )


@app.get("/api/quotes/{quote_id}/application", include_in_schema=False)
async def get_quote_application(quote_id: str) -> JSONResponse:
    application = db.get_application(quote_id)
    if application is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(application)


@app.put("/api/quotes/{quote_id}/application", include_in_schema=False)
async def save_quote_application(
    quote_id: str, request: Request
) -> JSONResponse:
    body = await _json_body(request)
    contact = body.get("contact")
    questions = body.get("questions")
    consent = body.get("consent")
    errors: dict[str, str] = {}
    if not isinstance(contact, dict):
        errors["contact"] = "Contact details are required."
        contact = {}
    if not isinstance(questions, dict):
        errors["questions"] = "Application questions are required."
        questions = {}
    if not isinstance(consent, dict):
        errors["consent"] = "Consent choices are required."
        consent = {}
    for field in ("first_name", "last_name"):
        if not _string(contact.get(field)):
            errors[field] = "This field is required."
    for field in ("currently_ill", "seen_vet_last_12_months"):
        if not isinstance(questions.get(field), bool):
            errors[field] = "Choose Yes or No."
    if questions.get("currently_ill") and not _string(
        questions.get("condition_details")
    ):
        errors["condition_details"] = (
            "Describe the condition when Currently ill is Yes."
        )
    if questions.get("seen_vet_last_12_months") and not _string(
        questions.get("vet_name")
    ):
        errors["vet_name"] = "Enter the veterinary provider name."
    for field in ("privacy", "electronic_signature"):
        if not isinstance(consent.get(field), bool):
            errors[field] = "Choose a consent option."
    try:
        db.reject_payment_keys(contact)
    except PaymentFieldRejected as exc:
        errors["payment"] = str(exc)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    saved = db.save_application(
        quote_id,
        contact={str(k)[:64]: v for k, v in contact.items()},
        questions={str(k)[:64]: v for k, v in questions.items()},
        consent={str(k)[:64]: v for k, v in consent.items()},
    )
    if saved is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(saved)


# ---------------------------------------------------------------------------
# portal API — site-isolated local accounts and member workflows
# ---------------------------------------------------------------------------


def _session_token(request: Request) -> str | None:
    backend, _auth = db.services()
    return request.cookies.get(backend.config.cookie_name)


def _set_session_cookie(response: Response, token: str) -> None:
    backend, _auth = db.services()
    options = dict(backend.session_cookie)
    name = options.pop("name")
    options["samesite"] = str(options["samesite"]).lower()
    response.set_cookie(name, token, **options)


def _clear_session_cookie(response: Response) -> None:
    backend, _auth = db.services()
    response.delete_cookie(
        backend.config.cookie_name,
        path="/",
        secure=True,
        httponly=True,
        samesite=str(backend.config.session["same_site"]).lower(),
    )


def _member_account(request: Request) -> dict | None:
    _backend, auth = db.services()
    session = auth.resolve_session(_session_token(request))
    if session is None or not session["authenticated"]:
        return None
    return session["account"]


def _member_required(request: Request) -> tuple[dict | None, JSONResponse | None]:
    account = _member_account(request)
    if account is None:
        return None, JSONResponse(
            {"error": "authentication-required"}, status_code=401
        )
    return account, None


@app.get("/portal/api/session", include_in_schema=False)
async def portal_session(request: Request) -> JSONResponse:
    _backend, auth = db.services()
    token, session = auth.ensure_session(_session_token(request))
    response = JSONResponse(session)
    _set_session_cookie(response, token)
    return response


@app.post("/portal/api/register", include_in_schema=False)
async def portal_register(request: Request) -> JSONResponse:
    body = await _json_body(request)
    errors: dict[str, str] = {}
    email = _string(body.get("email"))
    password = _string(body.get("password"))
    display_name = _string(body.get("display_name"))
    if not email:
        errors["email"] = "This field is required."
    if not password:
        errors["password"] = "This field is required."
    if not display_name:
        errors["display_name"] = "This field is required."
    if body.get("accept_terms") is not True:
        errors["accept_terms"] = "Accept the terms to create an account."
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    _backend, auth = db.services()
    token, _session = auth.ensure_session(_session_token(request))
    try:
        started = auth.start_registration(
            token,
            email=email,
            display_name=display_name,
            password=password,
        )
    except AuthConflict as exc:
        return JSONResponse({"errors": {"email": str(exc)}}, status_code=409)
    except (AuthValidationError, AuthError) as exc:
        return JSONResponse(
            {"errors": {"registration": str(exc)}}, status_code=422
        )
    response = JSONResponse(
        {
            "registered": False,
            "verification_required": True,
            "mail_status": started["mail_status"],
            "expires_at": started["expires_at"],
            "message": (
                "A verification code is available in the local simulation inbox."
            ),
        },
        status_code=202,
    )
    _set_session_cookie(response, token)
    return response


@app.get(
    "/portal/api/local-inbox/{purpose}", include_in_schema=False
)
async def portal_local_inbox(purpose: str, request: Request) -> JSONResponse:
    if purpose not in {"registration", "password-reset"}:
        return JSONResponse({"error": "not-found"}, status_code=404)
    token = _session_token(request)
    if token is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    _backend, auth = db.services()
    mail = auth.local_mail_for_session(token, purpose=purpose)
    if mail is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(
        {
            "purpose": mail["purpose"],
            "status": mail["status"],
            "verification_code": mail["verification_code"],
            "is_simulation": True,
        }
    )


@app.post("/portal/api/register/verify", include_in_schema=False)
async def portal_register_verify(request: Request) -> JSONResponse:
    code = _string((await _json_body(request)).get("code"))
    if not code:
        return JSONResponse(
            {"errors": {"code": "This field is required."}}, status_code=422
        )
    token = _session_token(request)
    if token is None:
        return JSONResponse({"error": "verification-unavailable"}, status_code=409)
    _backend, auth = db.services()
    try:
        auth.verify_registration_code(token, code)
        completed = auth.complete_registration(
            token, subject_factory=db.create_member_subject
        )
    except (AuthRejected, AuthError) as exc:
        return JSONResponse({"errors": {"code": str(exc)}}, status_code=422)
    account = completed["account"]
    db.ensure_member_profile(account)
    response = JSONResponse(
        {"registered": True, "authenticated": True, "account": account},
        status_code=201,
    )
    _set_session_cookie(response, completed["session_token"])
    return response


@app.post("/portal/api/login", include_in_schema=False)
async def portal_login(request: Request) -> JSONResponse:
    body = await _json_body(request)
    email = _string(body.get("email")) or _string(body.get("username"))
    password = _string(body.get("password"))
    errors: dict[str, str] = {}
    if not email:
        errors["email"] = "This field is required."
    if not password:
        errors["password"] = "This field is required."
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    _backend, auth = db.services()
    token, _session = auth.ensure_session(_session_token(request))
    try:
        signed_in = auth.sign_in(token, email=email, password=password)
    except AuthError:
        response = JSONResponse(
            {
                "authenticated": False,
                "message": "The email or password is incorrect.",
            },
            status_code=403,
        )
        _set_session_cookie(response, token)
        return response
    db.ensure_member_profile(signed_in["account"])
    response = JSONResponse(
        {"authenticated": True, "account": signed_in["account"]}
    )
    _set_session_cookie(response, signed_in["session_token"])
    return response


@app.post("/portal/api/logout", include_in_schema=False)
async def portal_logout(request: Request) -> JSONResponse:
    _backend, auth = db.services()
    auth.sign_out(_session_token(request))
    response = JSONResponse({"authenticated": False, "signed_out": True})
    _clear_session_cookie(response)
    return response


@app.post("/portal/api/forgot-password", include_in_schema=False)
async def portal_forgot_password(request: Request) -> JSONResponse:
    email = _string((await _json_body(request)).get("email"))
    if not email:
        return JSONResponse(
            {"errors": {"email": "This field is required."}}, status_code=422
        )
    _backend, auth = db.services()
    token, _session = auth.ensure_session(_session_token(request))
    try:
        result = auth.start_password_reset(token, email=email)
    except AuthError as exc:
        return JSONResponse({"errors": {"reset": str(exc)}}, status_code=422)
    response = JSONResponse(
        {
            "accepted": True,
            "message": result["message"],
            "mail_status": auth.session_mail_status(
                token, purpose="password-reset"
            ),
        },
        status_code=202,
    )
    _set_session_cookie(response, token)
    return response


@app.post("/portal/api/password-reset/verify", include_in_schema=False)
async def portal_password_reset_verify(request: Request) -> JSONResponse:
    body = await _json_body(request)
    code = _string(body.get("code"))
    password = _string(body.get("new_password"))
    if not code or not password:
        return JSONResponse(
            {"errors": {"reset": "Code and new password are required."}},
            status_code=422,
        )
    token = _session_token(request)
    if token is None:
        return JSONResponse({"error": "verification-unavailable"}, status_code=409)
    _backend, auth = db.services()
    try:
        auth.verify_password_reset_code(token, code)
        completed = auth.complete_password_reset(token, new_password=password)
    except AuthError as exc:
        return JSONResponse({"errors": {"reset": str(exc)}}, status_code=422)
    response = JSONResponse({"authenticated": True, "reset": True})
    _set_session_cookie(response, completed["session_token"])
    return response


@app.get("/portal/api/dashboard", include_in_schema=False)
async def portal_dashboard(request: Request) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    return JSONResponse(db.member_dashboard(account))


@app.get("/portal/api/profile", include_in_schema=False)
async def portal_profile(request: Request) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    return JSONResponse(db.ensure_member_profile(account))


@app.get("/portal/api/policies/{policy_number}", include_in_schema=False)
async def portal_policy(policy_number: str, request: Request) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    policy = db.policy_detail(account["email_normalized"], policy_number)
    if policy is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(policy)


@app.patch(
    "/portal/api/policies/{policy_number}/coverage", include_in_schema=False
)
async def portal_policy_coverage(
    policy_number: str, request: Request
) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    body = await _json_body(request)
    try:
        policy = db.update_policy_coverage(
            account["email_normalized"],
            policy_number,
            annual_limit=int(body.get("annual_limit", -1)),
            deductible=int(body.get("deductible", -1)),
            reimbursement=int(body.get("reimbursement", -1)),
            preventive=(
                None if body.get("preventive") in (None, "", "none")
                else str(body["preventive"])
            ),
        )
    except (ValueError, RatingError) as exc:
        return JSONResponse({"errors": {"coverage": str(exc)}}, status_code=422)
    if policy is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(policy)


@app.patch(
    "/portal/api/policies/{policy_number}/billing", include_in_schema=False
)
async def portal_policy_billing(
    policy_number: str, request: Request
) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    body = await _json_body(request)
    if not isinstance(body.get("autopay"), bool):
        return JSONResponse(
            {"errors": {"autopay": "Choose an autopay option."}}, status_code=422
        )
    try:
        billing = db.update_policy_billing(
            account["email_normalized"],
            policy_number,
            autopay=body["autopay"],
            frequency=_string(body.get("frequency")),
        )
    except ValueError as exc:
        return JSONResponse({"errors": {"billing": str(exc)}}, status_code=422)
    if billing is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(billing)


@app.get(
    "/portal/api/policies/{policy_number}/documents", include_in_schema=False
)
async def portal_policy_documents(
    policy_number: str, request: Request
) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    documents = db.policy_documents(account["email_normalized"], policy_number)
    if documents is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse({"documents": documents})


@app.get(
    "/portal/api/documents/{document_id}/download", include_in_schema=False
)
async def portal_document_download(
    document_id: str, request: Request
) -> Response:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    document = db.owned_document(account, document_id)
    if document is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    title = str(document["title"]).replace("(", "[").replace(")", "]")
    pdf = (
        "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
        f"% {title} — {document['policy_number']}\n%%EOF\n"
    ).encode("utf-8")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{document_id}.pdf"'
        },
    )


@app.post("/portal/api/uploads", include_in_schema=False)
async def portal_upload(request: Request) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    body = await _json_body(request)
    filename = Path(_string(body.get("filename"))).name
    content_type = _string(body.get("content_type"))
    try:
        size = int(body.get("size", 0))
    except (TypeError, ValueError):
        size = 0
    allowed = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    expected_type = allowed.get(Path(filename).suffix.lower())
    errors: dict[str, str] = {}
    if not filename or expected_type is None or content_type != expected_type:
        errors["file"] = "Upload a PDF, PNG, or JPEG file."
    if size <= 0 or size > 10 * 1024 * 1024:
        errors["size"] = "File size must be between 1 byte and 10 MB."
    if errors:
        return JSONResponse({"errors": errors, "progress": 0}, status_code=422)
    upload = db.create_upload(
        account["account_id"],
        filename=filename,
        content_type=content_type,
        size_bytes=size,
    )
    return JSONResponse(upload, status_code=201)


@app.get("/portal/api/claims", include_in_schema=False)
async def portal_claims(request: Request) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    return JSONResponse(db.member_claims(account["account_id"]))


@app.post("/portal/api/claims", include_in_schema=False)
async def portal_create_claim(request: Request) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    body = await _json_body(request)
    errors: dict[str, str] = {}
    for field in ("policy_number", "incident_date", "reason", "provider", "amount"):
        if not _string(body.get(field)):
            errors[field] = "This field is required."
    upload_id = _string(body.get("upload_id")) or None
    if body.get("has_invoice") is True and upload_id is None:
        errors["upload_id"] = "Upload the invoice when Has invoice is Yes."
    try:
        amount = Decimal(_string(body.get("amount")))
        amount_minor = int(amount * 100)
        if amount <= 0 or amount * 100 != amount_minor:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        errors["amount"] = "Enter a positive amount with at most two decimals."
        amount_minor = 0
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    try:
        claim = db.create_claim(
            account,
            policy_number=_string(body.get("policy_number")),
            incident_date=_string(body.get("incident_date")),
            reason=_string(body.get("reason")),
            provider=_string(body.get("provider")),
            amount_minor=amount_minor,
            upload_id=upload_id,
        )
    except ValueError as exc:
        return JSONResponse({"errors": {"claim": str(exc)}}, status_code=422)
    if claim is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(claim, status_code=201)


@app.get("/portal/api/claims/{claim_number}", include_in_schema=False)
async def portal_claim_detail(
    claim_number: str, request: Request
) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    claim = db.claim_detail(account["account_id"], claim_number)
    if claim is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(claim)


@app.post(
    "/portal/api/policies/{policy_number}/renew", include_in_schema=False
)
async def portal_policy_renew(
    policy_number: str, request: Request
) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    try:
        result = db.renew_policy(account["email_normalized"], policy_number)
    except ValueError as exc:
        return JSONResponse({"errors": {"renewal": str(exc)}}, status_code=422)
    if result is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(result)


@app.post(
    "/portal/api/policies/{policy_number}/cancel", include_in_schema=False
)
async def portal_policy_cancel(
    policy_number: str, request: Request
) -> JSONResponse:
    account, error = _member_required(request)
    if error is not None:
        return error
    assert account is not None
    body = await _json_body(request)
    if body.get("confirm") is not True:
        return JSONResponse(
            {"errors": {"confirm": "Confirm cancellation to continue."}},
            status_code=422,
        )
    reason = _string(body.get("reason"))
    if not reason:
        return JSONResponse(
            {"errors": {"reason": "Choose a cancellation reason."}},
            status_code=422,
        )
    result = db.cancel_policy(
        account["email_normalized"], policy_number, reason=reason
    )
    if result is None:
        return JSONResponse({"error": "not-found"}, status_code=404)
    return JSONResponse(result)
