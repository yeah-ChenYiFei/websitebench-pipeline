"""TripIt offline clone — FastAPI composition root.

Marketing / auth / legal pages are frozen, localized captures served at their
real source routes (Phase 4). This module also carries the dynamic backend
surfaces (Phase 5): server-authoritative auth, the trips list with its
Upcoming / Past / Unfiled tabs, trip itineraries, and the plan writes behind
the anchor "add a hotel to the New York trip" journey. All identity comes from
the server session row addressed by the ``__Host`` session cookie; ownership is
enforced per request and foreign or missing owner-scoped resources return 404
without disclosing existence.

Frozen contracts preserved verbatim from Phase 4:

* ``GET /healthz`` returns *exactly* ``{"ok":true,"site_id":"tripit"}``.
* ``POST /__admin/reset`` is guarded by a constant-time admin-token compare and,
  on success, rebuilds the seeded database through ``reset_fixture_state``.
* Every response carries a same-origin Content-Security-Policy and the
  hardening headers; no shipped file or rendered marketing page references a
  remote origin.
* ``/static`` serves both the manifest-verified ``assets`` tree and the
  out-of-closure ``site`` tree.

CSRF: the frozen auth pages are byte-stable captures, so a per-session hidden
token cannot be injected without breaking their determinism contract. The
session cookie is ``SameSite=Lax``, which stops cross-site form POSTs from
carrying it; that is the CSRF control for every state-changing route here.

Authenticated route shapes (``/trips``, ``/trips/{id}``, ``/trips/{id}/plans``)
were not directly observable during anonymous capture and are recorded as
structural/inferred in the scope claims; they follow a clean, TripIt-plausible
scheme and are refined for visual fidelity in a later phase.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import re
import urllib.parse
import secrets
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.formparsers import MultiPartException

from websitebench.local_clone_auth import (
    AuthConflict,
    AuthError,
    AuthRateLimited,
    AuthRejected,
    AuthValidationError,
    LocalAuthStore,
)
from websitebench.public_clone_auth import (
    VerificationUnavailable,
    load_public_clone_registration_verification,
)
from websitebench.public_clone_auth.fastapi import (
    consume_registration_ticket,
    registration_script_response,
    send_registration_code,
    verify_registration_code,
)
from websitebench.site_backend.stripe_test import (
    StripeTestError,
    StripeTestGateway,
    StripeTestResponseError,
    StripeTestUnavailable,
)

SITE_ID = "tripit"

ROOT = Path(__file__).resolve().parent
PAGES_DIR = ROOT / "frontend" / "pages"
TEMPLATES_DIR = ROOT / "frontend" / "templates"
STATIC_DIR = ROOT / "static"


# ---------------------------------------------------------------------------
# vendored backend data layer (loaded from file, registered under a stable name)
# ---------------------------------------------------------------------------


def _load_backend_db():
    """Import ``backend/db.py`` once under a stable module name.

    The data layer is a sibling file rather than a package, so it is loaded by
    path and cached in ``sys.modules`` so repeated imports (tests reload the app
    module) reuse the same module object and its readiness cache.
    """

    module_name = "tripit_clone_backend_db"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        module_name, ROOT / "backend" / "db.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


db = _load_backend_db()

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))



# ---------------------------------------------------------------------------
# frozen page routes + runtime constants (Phase 4, unchanged)
# ---------------------------------------------------------------------------

# Real source route -> fixture page file (captured anonymously, localized).
PAGE_ROUTES: dict[str, str] = {
    "/": "home",
    "/web/free": "free",
    "/web/pro": "pro",
    "/web/free/how-it-works": "how-it-works",
    "/web/pro/pricing": "pricing",
    "/web/pro/sap-concur": "sap-concur",
    "/web/free/download": "download",
    "/web/security": "security",
    "/web/blog": "blog-index",
    "/web/traveler-resource-center": "traveler-resource-center",
    # /account/login and /account/create are live templates (see the auth
    # section below): a frozen replay cannot render a validation error, and
    # both surfaces have to report why a submission was rejected. Their default
    # render is byte-identical to the frozen capture apart from the documented
    # form changes, which tests/test_auth_surface.py asserts.
    "/account/forgotPassword": "forgot-password",
    "/uhp/userAgreement": "legal-user-agreement",
    "/uhp/privacyPolicy": "legal-privacy",
    "/uhp/doNotShare": "legal-do-not-share",
}

# Admin token for /__admin/reset. A non-secret dev default keeps local runs
# working; deployments inject the real value via the environment. It is never
# logged or echoed.
ADMIN_TOKEN = os.environ.get("WEBSITEBENCH_TRIPIT_ADMIN_TOKEN", "tripit-local-admin")

# Optional build id surfaced as a response header for deploy-time verification.
BUILD_ID = os.environ.get("DEPLOYMENT_BUILD_ID") or os.environ.get(
    "WEBSITEBENCH_BUILD_ID"
)

# Same-origin CSP. 'unsafe-inline'/'unsafe-eval' are required because the
# captured documents carry inline <style>/<script> and vendored animation
# runtimes; the load-bearing property is that NO remote origin is reachable
# (default-src 'self', no external hosts), which enforces zero remote runtime
# requests while the inline first-party content still renders faithfully.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "media-src 'self' data:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

_HEALTH_BODY = json.dumps({"ok": True, "site_id": SITE_ID}, separators=(",", ":"))

_EXTERNAL_PAGE = (
    "<!doctype html>\n"
    '<html lang="en"><head><meta charset="utf-8">\n'
    "<title>Leaving TripIt</title>\n"
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<link rel="icon" href="/static/site/favicon/theme-favicon.ico" '
    'type="image/vnd.microsoft.icon">\n'
    "</head><body>\n"
    '<main style="font-family:sans-serif;max-width:40rem;margin:4rem auto;'
    'padding:0 1rem">\n'
    "<h1>External link</h1>\n"
    "<p>This link points to a destination outside this site.</p>\n"
    '<p><a href="/">Return to TripIt</a></p>\n'
    "</main></body></html>\n"
)

_PAGE_CACHE: dict[str, str] = {}


def _load_page(name: str) -> str:
    cached = _PAGE_CACHE.get(name)
    if cached is None:
        cached = (PAGES_DIR / f"{name}.html").read_text(encoding="utf-8")
        _PAGE_CACHE[name] = cached
    return cached


# ---------------------------------------------------------------------------
# session + auth wiring
# ---------------------------------------------------------------------------

_RUNTIME = db.runtime_config()
SESSION_COOKIE = _RUNTIME.cookie_name  # __Host-websitebench-tripit-session
_COOKIE_OPTS = dict(_RUNTIME.cookie_options)
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 days, matching the store's session TTL

# Source-observed registration policy: the create form's password helper reads
# "At least 15 characters. Cannot be an email." — enforced on top of the store's
# own 8..128 floor.
MIN_REGISTRATION_PASSWORD = 15
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Shared registration-verification runtime. Unconfigured (the local default) it
# is None and registration falls back to the vendored local store's own emailed
# code; configured, the same form drives the external verification boundary.
PUBLIC_REGISTRATION_VERIFICATION = load_public_clone_registration_verification()
templates.env.globals["public_registration_enabled"] = (
    PUBLIC_REGISTRATION_VERIFICATION is not None
)

# Third-party sign-in controls captured on both auth surfaces. Identity
# federation is not modelled here, so each control lands on a same-origin page
# that says so instead of silently doing nothing.
# Evidence: artifacts/parity/auth/{signin,register}/desktop/page.html.
THIRD_PARTY_AUTH: dict[str, dict[str, str]] = {
    "signInGoogle": {
        "provider": "Google",
        "heading": "Sign in with Google",
        "return_path": "/account/login",
        "return_label": "Back to sign in",
    },
    "signUpGoogle": {
        "provider": "Google",
        "heading": "Create an account with Google",
        "return_path": "/account/create",
        "return_label": "Back to sign up",
    },
}

# Home City suggestions for the create form's place picker. The vendored
# components/placepicker.js asks `GET /complete/place?query=&limit=&near=`
# and renders `[{value,label}]`; this is the local answer to that contract.
HOME_CITY_PLACES: tuple[str, ...] = (
    "Amsterdam, Netherlands",
    "Atlanta, GA",
    "Austin, TX",
    "Bangkok, Thailand",
    "Barcelona, Spain",
    "Berlin, Germany",
    "Boston, MA",
    "Buenos Aires, Argentina",
    "Cape Town, South Africa",
    "Chicago, IL",
    "Copenhagen, Denmark",
    "Denver, CO",
    "Dubai, United Arab Emirates",
    "Dublin, Ireland",
    "Edinburgh, United Kingdom",
    "Honolulu, HI",
    "Hong Kong",
    "Istanbul, Turkey",
    "Lisbon, Portugal",
    "London, United Kingdom",
    "Los Angeles, CA",
    "Madrid, Spain",
    "Melbourne, Australia",
    "Mexico City, Mexico",
    "Miami, FL",
    "Milan, Italy",
    "Montreal, QC",
    "Mumbai, India",
    "Munich, Germany",
    "Nashville, TN",
    "New Orleans, LA",
    "New York, NY",
    "Paris, France",
    "Portland, OR",
    "Prague, Czech Republic",
    "Reykjavik, Iceland",
    "Rio de Janeiro, Brazil",
    "Rome, Italy",
    "San Diego, CA",
    "San Francisco, CA",
    "Santiago, Chile",
    "Sao Paulo, Brazil",
    "Seattle, WA",
    "Seoul, South Korea",
    "Singapore",
    "Stockholm, Sweden",
    "Sydney, Australia",
    "Tokyo, Japan",
    "Toronto, ON",
    "Vancouver, BC",
    "Vienna, Austria",
    "Washington, DC",
    "Zurich, Switzerland",
)

# Deterministic lodging typeahead used by the anchor journey. 'Hilton' resolves
# to 'New York Hilton Midtown' exactly as the frozen journey requires.
LODGING_SUGGESTIONS: tuple[dict[str, str], ...] = (
    {
        "name": "New York Hilton Midtown",
        "address": "1335 Avenue of the Americas, New York, NY 10019",
    },
    {
        "name": "Hilton Garden Inn New York/Times Square",
        "address": "790 8th Avenue, New York, NY 10019",
    },
    {
        "name": "The Palmer House Hilton",
        "address": "17 East Monroe Street, Chicago, IL 60603",
    },
    {
        "name": "Hilton Lisbon",
        "address": "Rua Castilho 13, 1250-066 Lisboa, Portugal",
    },
)

# Cookie-preference choice. Not a session control: it records which categories
# the visitor allowed, and nothing here sets any cookie outside that choice.
COOKIE_CHOICE_COOKIE = "tripit-cookie-choice"
COOKIE_CHOICES: tuple[str, ...] = ("all", "necessary")

PLAN_TYPE_LABELS: dict[str, str] = {
    "air": "Flight",
    "lodging": "Lodging",
    "car": "Car rental",
    "rail": "Rail",
    "transport": "Transportation",
    "cruise": "Cruise",
    "restaurant": "Restaurant",
    "meeting": "Meeting",
    "activity": "Activity",
    "map": "Map",
    "directions": "Directions",
    "note": "Note",
}

# Curated primary-location zones for the trip form's timezone picker. The list
# covers every seeded trip zone plus common travel destinations; any IANA name
# is still accepted on submit (validated against the tz database, not this list).
COMMON_TIMEZONES: tuple[tuple[str, str], ...] = (
    ("America/New_York", "New York · Eastern"),
    ("America/Chicago", "Chicago · Central"),
    ("America/Denver", "Denver · Mountain"),
    ("America/Los_Angeles", "Los Angeles · Pacific"),
    ("America/Toronto", "Toronto"),
    ("America/Sao_Paulo", "São Paulo"),
    ("Europe/London", "London"),
    ("Europe/Lisbon", "Lisbon"),
    ("Europe/Paris", "Paris"),
    ("Europe/Berlin", "Berlin"),
    ("Europe/Madrid", "Madrid"),
    ("Asia/Dubai", "Dubai"),
    ("Asia/Singapore", "Singapore"),
    ("Asia/Shanghai", "Shanghai"),
    ("Asia/Tokyo", "Tokyo"),
    ("Australia/Sydney", "Sydney"),
    ("Pacific/Honolulu", "Honolulu"),
    ("UTC", "UTC"),
)

_UTC = timezone.utc

_AUTH_STORES: dict[str, LocalAuthStore] = {}


def auth_store() -> LocalAuthStore:
    """Return the site-bound auth store for the ready database (cached)."""

    path = db.ensure_ready()
    key = str(path)
    store = _AUTH_STORES.get(key)
    if store is None:
        store = LocalAuthStore(path, site_id=SITE_ID)
        store.ensure_schema()
        _AUTH_STORES[key] = store
    return store


def reset_fixture_state() -> None:
    """Restore the pristine seeded baseline (auth + business) in one pass.

    Both the test harness and ``POST /__admin/reset`` call through here. The
    reset clears the six library auth tables and the business tables, then
    reseeds the frozen fixture accounts and manifest rows.
    """

    db.reset(auth_store())


def _set_session_cookie(response: Response, token: str, *, persistent: bool = True) -> None:
    """Issue the session cookie.

    ``persistent`` is the "Keep me signed in." control on the sign-in form. When
    it is set the cookie carries ``Max-Age`` and survives a browser restart;
    when it is not, the cookie is omitted from disk and dies with the browser
    session. That is the whole of the modelled difference — the server-side
    session row's own TTL is fixed by the auth runtime either way — and it is
    the reason the checkbox is shipped at all rather than accepted and ignored.
    """

    options: dict[str, Any] = dict(
        path=_COOKIE_OPTS.get("path", "/"),
        secure=bool(_COOKIE_OPTS.get("secure", True)),
        httponly=bool(_COOKIE_OPTS.get("httponly", True)),
        samesite=str(_COOKIE_OPTS.get("samesite", "Lax")).lower(),
    )
    if persistent:
        options["max_age"] = SESSION_MAX_AGE
    response.set_cookie(SESSION_COOKIE, token, **options)


def _clear_session_cookie(response: Response) -> None:
    # A __Host- cookie is only accepted (and thus only cleared) with Secure and
    # Path=/, so mirror those attributes on the expiring cookie.
    response.delete_cookie(
        SESSION_COOKIE,
        path=_COOKIE_OPTS.get("path", "/"),
        secure=bool(_COOKIE_OPTS.get("secure", True)),
        httponly=bool(_COOKIE_OPTS.get("httponly", True)),
        samesite=str(_COOKIE_OPTS.get("samesite", "Lax")).lower(),
    )


def current_traveler(request: Request) -> dict[str, Any] | None:
    """Resolve the authenticated traveler from the session cookie, or None.

    Identity is taken solely from the server session row; the business owner key
    is the bridged subject. Anonymous or unbridged sessions resolve to None.
    """

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    resolved = auth_store().resolve_session(token)
    if not resolved or not resolved.get("authenticated"):
        return None
    account = resolved["account"]
    subject_id = str(account["subject_id"])
    with closing(db.connect()) as connection:
        owner = db.owner_for_subject(connection, subject_id)
    if not owner:
        return None
    return {
        "token": token,
        "subject_id": subject_id,
        "owner_key": owner,
        "account": account,
    }


def _safe_next(value: str | None, default: str = "/trips") -> str:
    if not value:
        return default
    if not value.startswith("/") or value.startswith("//"):
        return default
    return value


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/account/login", status_code=303)


def _nav_context(request: Request) -> dict[str, Any]:
    """Header state (signed-in name or anonymous) for the shared layout.

    Resolution failures degrade to the anonymous header rather than surfacing an
    error, so a rendering path never fails on nav alone.
    """

    try:
        traveler = current_traveler(request)
    except Exception:  # noqa: BLE001 - nav must never break a render
        traveler = None
    if not traveler:
        return {"authenticated": False, "display_name": None}
    return {
        "authenticated": True,
        "display_name": traveler["account"].get("display_name") or "Traveler",
    }


def _render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    payload: dict[str, Any] = {"request": request, "site_id": SITE_ID}
    if context:
        payload.update(context)
    payload.setdefault("nav", _nav_context(request))
    return templates.TemplateResponse(request, name, payload, status_code=status_code)


def _not_found(request: Request) -> HTMLResponse:
    return _render(request, "not_found.html", status_code=404)


def _display_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    cleaned = re.sub(r"[._-]+", " ", local).strip()
    return cleaned.title() if cleaned else "Traveler"


def _apply_home_city(session_token: str, place: str) -> None:
    """Persist the create form's Home City onto the freshly bridged profile."""

    if not place:
        return
    resolved = auth_store().resolve_session(session_token)
    if not resolved or not resolved.get("authenticated"):
        return
    subject_id = str(resolved["account"]["subject_id"])
    with closing(db.connect()) as connection:
        owner = db.owner_for_subject(connection, subject_id)
    if owner:
        db.update_profile(owner, home_city=place)


def _lodging_natural_key(hotel: str, confirmation: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", hotel.lower()).strip("-")
    conf = re.sub(r"[^a-z0-9]+", "", confirmation.lower())
    return f"lodging:{slug}:{conf}" if conf else f"lodging:{slug}"


def _valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001 - any tz-db lookup failure is "invalid"
        return False


def _valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _local_to_utc_iso(date_str: str, time_str: str, tz_name: str) -> str:
    """Combine a local date + HH:MM in the trip's IANA zone into a UTC stamp."""

    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    aware = naive.replace(tzinfo=ZoneInfo(tz_name))
    return aware.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_ts(ts_utc: str | None, tz_name: str | None) -> str:
    if not ts_utc:
        return ""
    try:
        parsed = datetime.strptime(ts_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_UTC)
    except ValueError:
        return ts_utc
    if tz_name:
        parsed = parsed.astimezone(ZoneInfo(tz_name))
    return parsed.strftime("%a, %b %-d, %Y · %-I:%M %p")


def _timeline(plans: list[dict[str, Any]], tz_name: str | None) -> list[dict[str, Any]]:
    """Expand plans into ordered timeline rows.

    Lodging expands to check-in / check-out rows and car to pick-up / drop-off
    rows; every other type contributes one row. Rows sort by (timestamp,
    sort_key, plan_id, sub-order) so the invariant ordering holds.
    """

    events: list[dict[str, Any]] = []
    for plan in plans:
        sort_key = plan.get("sort_key", 0)
        plan_id = plan["plan_id"]
        if plan["plan_type"] == "lodging":
            pairs = (("Check-in", plan["start_ts_utc"]), ("Check-out", plan["end_ts_utc"]))
        elif plan["plan_type"] == "car":
            pairs = (("Pick-up", plan["start_ts_utc"]), ("Drop-off", plan["end_ts_utc"]))
        else:
            pairs = ((PLAN_TYPE_LABELS.get(plan["plan_type"], "Plan"), plan["start_ts_utc"]),)
        for sub, ts in enumerate(pairs):
            label, stamp = ts
            events.append(
                {
                    "plan": plan,
                    "row_label": label,
                    "when": _fmt_ts(stamp, tz_name),
                    "primary": sub == 0,
                    "_sort": (stamp or "", sort_key, plan_id, sub),
                }
            )
    events.sort(key=lambda event: event["_sort"])
    return events


# ---------------------------------------------------------------------------
# authenticated /app/* surface
#
# The logged-in experience is reproduced from the real captured Bootstrap-Vue
# DOM + CSS bundle, parameterised over the seeded fixtures. Deterministic
# TripIt-shaped object ids give /app the opaque UUID URLs the live SPA uses
# without exposing the slug primary keys or any real identifier.
# ---------------------------------------------------------------------------


def _parse_utc(ts_utc: str | None) -> datetime | None:
    if not ts_utc:
        return None
    try:
        return datetime.strptime(ts_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_UTC)
    except ValueError:
        return None


def _app_local(ts_utc: str | None, tz_name: str | None) -> datetime | None:
    parsed = _parse_utc(ts_utc)
    if parsed is not None and tz_name:
        parsed = parsed.astimezone(ZoneInfo(tz_name))
    return parsed


def _parse_date(value: str | None):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except (ValueError, TypeError):
        return None


def _app_uuid(seed: str, group: int = 1) -> str:
    """Deterministic TripIt-shaped object id from a stable seed (slug).

    Mirrors the live id shape ``<8hex>-<4hex>-9000-000N-<12hex>`` so /app URLs
    are indistinguishable from the source without carrying a real identifier.
    """

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{digest[0:8]}-{digest[8:12]}-9000-000{str(group)[-1]}-{digest[12:24]}"


# Flight objects sit in group 3 on the live app, everything else in group 4;
# reproducing that keeps the opaque ids shaped exactly like the source.
_APP_PLAN_UUID_GROUP: dict[str, int] = {"air": 3}

# URL segment the live app nests each plan type under (/app/trips/{uuid}/<seg>/…).
_APP_PLAN_PATH: dict[str, str] = {
    "air": "flights",
    "lodging": "lodging",
    "car": "car",
    "rail": "rail",
    "transport": "transportation",
    "cruise": "cruise",
    "restaurant": "restaurant",
    "meeting": "meeting",
    "activity": "activity",
    "map": "map",
    "directions": "directions",
    "note": "note",
}

_AIRLINE_CODES: dict[str, str] = {
    "united airlines": "UA",
    "united": "UA",
    "tap air portugal": "TP",
    "tap": "TP",
    "delta": "DL",
    "american airlines": "AA",
    "american": "AA",
    "alaska": "AS",
    "jetblue": "B6",
    "southwest": "WN",
}


def _app_plan_uuid(plan: dict[str, Any]) -> str:
    return _app_uuid(plan["plan_id"], _APP_PLAN_UUID_GROUP.get(plan["plan_type"], 4))


def _app_time(dt: datetime | None) -> str:
    return dt.strftime("%-I:%M %p %Z").strip() if dt is not None else ""


def _flight_number(title: str) -> str:
    match = re.search(r"(\d{1,4})", title or "")
    if not match:
        return ""
    low = (title or "").lower()
    code = next((c for name, c in _AIRLINE_CODES.items() if name in low), "")
    return f"{code} {match.group(1)}".strip()


def _app_content_rows(
    plan: dict[str, Any], plan_type: str, primary: bool, dt_local: datetime | None
) -> list[tuple[str, str, str]]:
    """Type-specific secondary cells shown under a timeline title, mirroring the
    live per-type layout. Each row is ``(data-cy, text, shape)`` where ``shape``
    reproduces the exact wrapper the captured DOM used for that cell:

    * ``lead2`` — ``<div class=""><p class="me-2">…</p><!----><!----></div>``
      (the flight's first row: two trailing slot comments).
    * ``lead1`` — the same wrapper with one trailing comment (lodging
      check-in/out row).
    * ``bare_sp`` — ``<p>…&nbsp;</p><!---->`` (car pick-up / drop-off: a
      trailing space inside the ``<p>`` plus a sibling comment).
    * ``bare`` — a plain ``<p data-cy=…>…</p>``.

    Only the three types whose live timeline markup was directly observed
    (air / lodging / car) emit content rows; every other type renders as a bare
    title, matching the captured activity segment (empty ``.content``). This
    avoids inventing ``data-cy`` markers a blind auditor could compare against.
    """

    details = plan.get("details") or {}
    rows: list[tuple[str, str, str]] = []
    if plan_type == "air":
        number = _flight_number(plan.get("title", ""))
        if number:
            rows.append(("timeline-flight-number", f"Flight Number {number}", "lead2"))
        if details.get("seats"):
            rows.append(("timeline-seats", f"Seat(s) {details['seats']}", "bare"))
        arrival = _app_local(plan.get("end_ts_utc"), plan.get("timezone"))
        if arrival is not None:
            rows.append(
                ("timeline-arrival-time", f"Arrive {arrival.strftime('%-m/%-d/%Y')}", "bare")
            )
    elif plan_type == "lodging":
        cy = "timeline-checkin-time" if primary else "timeline-checkout-time"
        word = "Check in" if primary else "Check out"
        rows.append((cy, f"{word} {_app_time(dt_local)}".strip(), "lead1"))
        address = details.get("address") or details.get("location")
        if address:
            rows.append(("timeline-reservation", address, "bare"))
    elif plan_type == "car":
        rows.append(
            (
                "timeline-pick-up" if primary else "timeline-drop-off",
                "Pick up" if primary else "Drop off",
                "bare_sp",
            )
        )
    return rows


def _flight_route(title: str) -> tuple[str, str] | None:
    """Origin/destination shown in a flight timeline title (``SFO → JFK``)."""

    if "→" in (title or ""):
        tail = title.split("·")[-1]
        parts = [p.strip() for p in tail.split("→")]
        if len(parts) == 2 and all(parts):
            return parts[0], parts[1]
    return None


def _app_timeline(
    plans: list[dict[str, Any]], tz_name: str | None
) -> list[dict[str, Any]]:
    """Group plans into day sections for the /app timeline.

    Reuses the same lodging→check-in/out and car→pick-up/drop-off expansion as
    :func:`_timeline`, then buckets the ordered rows by calendar day (in the
    trip's zone). Dateless plans fall into a trailing ``No Date`` section, as on
    the live app.
    """

    rows: list[dict[str, Any]] = []
    for plan in plans:
        plan_type = plan["plan_type"]
        if plan_type == "lodging":
            subs = (("Check-in", plan.get("start_ts_utc"), True),
                    ("Check-out", plan.get("end_ts_utc"), False))
        elif plan_type == "car":
            subs = (("Pick-up", plan.get("start_ts_utc"), True),
                    ("Drop-off", plan.get("end_ts_utc"), False))
        else:
            subs = ((PLAN_TYPE_LABELS.get(plan_type, "Plan"),
                     plan.get("start_ts_utc"), True),)
        for order, (label, stamp, primary) in enumerate(subs):
            dt_local = _app_local(stamp, tz_name)
            rows.append(
                {
                    "plan_id": plan["plan_id"],
                    "public_id": _app_plan_uuid(plan),
                    "type": plan_type,
                    "title": plan.get("title", ""),
                    "plan_path": _APP_PLAN_PATH.get(plan_type, "plans"),
                    "row_label": label,
                    "time": _app_time(dt_local),
                    "route": _flight_route(plan.get("title", "")) if plan_type == "air" else None,
                    "content": _app_content_rows(plan, plan_type, primary, dt_local),
                    "_day": dt_local,
                    "_sort": (
                        1 if stamp is None else 0,
                        stamp or "",
                        plan.get("sort_key", 0),
                        plan["plan_id"],
                        order,
                    ),
                }
            )
    rows.sort(key=lambda row: row["_sort"])
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        day = row["_day"]
        key = day.strftime("%Y-%m-%d") if day else "no-date"
        header = day.strftime("%a, %b %-d %Y") if day else "No Date"
        if current is None or current["key"] != key:
            current = {"key": key, "header": header, "segments": []}
            sections.append(current)
        current["segments"].append(row)
    return sections


def _app_date_parts(trip: dict[str, Any]) -> tuple[str, str]:
    """Split a trip's header date span into its ``base`` label and the live
    ``N days, in M days`` relative suffix, both computed against the single
    frozen clock so they are deterministic. Returns ``("", "")`` when the trip
    has no usable dates."""

    start = _parse_date(trip.get("start_date"))
    end = _parse_date(trip.get("end_date"))
    if not start or not end:
        return "", ""
    if start.year == end.year and start.month == end.month:
        base = f"{start.strftime('%b %-d')} - {end.strftime('%-d, %Y')}"
    elif start.year == end.year:
        base = f"{start.strftime('%b %-d')} - {end.strftime('%b %-d, %Y')}"
    else:
        base = f"{start.strftime('%b %-d, %Y')} - {end.strftime('%b %-d, %Y')}"
    days = (end - start).days + 1
    parts = [f"{days} day{'s' if days != 1 else ''}"]
    now = _parse_date(db.FROZEN_DATE)
    if now:
        rel = (start - now).days
        if rel > 0:
            parts.append(f"in {rel} days")
        elif rel == 0:
            parts.append("today")
        else:
            parts.append(f"{abs(rel)} days ago")
    return base, ", ".join(parts)


def _app_date_span(trip: dict[str, Any]) -> str:
    """Header-card date span with the live ``(N days, in M days)`` suffix,
    computed against the single frozen clock so it is deterministic."""

    base, rel = _app_date_parts(trip)
    return f"{base} ({rel})" if base else ""


# Trip hero images live in the mirrored /images closure at their real source
# path, so /app renders them exactly as the source did with zero remote fetches.
_APP_PLACE_IMAGES: dict[str, str] = {
    "new york, ny": "/images/places/us/ny/newyorkcity.jpg",
}


def _app_trip_image(trip: dict[str, Any]) -> str:
    key = (trip.get("destination") or "").strip().lower()
    return _APP_PLACE_IMAGES.get(key, "/images/places/themes/generic.jpg")


def _resolve_app_trip(connection: Any, owner: str, public_id: str) -> dict[str, Any] | None:
    """Map an opaque /app trip id back to the owner's trip via the deterministic
    id scheme. Owner-scoped: a foreign or unknown id resolves to ``None`` (404),
    never leaking existence."""

    for tab in ("upcoming", "past"):
        for trip in db.list_trips(connection, owner, tab):
            if _app_uuid(trip["trip_id"], 1) == public_id:
                return trip
    return None


# The four dashboard tabs. Only the owner's own upcoming/past trips carry cards
# in the seed; "others'" (incoming shares) and "unfiled" render their captured
# empty states, so they map to no query.
_APP_TABS: tuple[str, ...] = ("upcoming-your", "upcoming-others", "past", "unfiled")
_APP_TAB_QUERY: dict[str, str] = {"upcoming-your": "upcoming", "past": "past"}

# The source addresses the same four dashboard selections with ?trips_filter=.
# Evidence: source-auth-scratch/*/harvested-app-links.json.
_APP_TAB_ALIASES: dict[str, str] = {
    "your_upcoming": "upcoming-your",
    "others_upcoming": "upcoming-others",
    "past": "past",
    "unassigned": "unfiled",
}

# Path segment each plan type is created under in the source app's URL space,
# harvested from the captured add-plan menu. Several segments narrow onto the
# same stored plan type; ?type= narrows further where the menu offers it.
_APP_CREATE_PLAN_TYPE: dict[str, str] = {
    "flights": "air",
    "lodging": "lodging",
    "car-rental": "car",
    "rail": "rail",
    "transport": "transport",
    "parking": "transport",
    "cruise": "cruise",
    "restaurant": "restaurant",
    "activity": "activity",
    "map": "map",
    "direction": "directions",
    "note": "note",
}

# ?type= refinements the captured menu offers on top of a create segment.
_APP_CREATE_TYPE_REFINEMENT: dict[tuple[str, str], str] = {
    ("activity", "meeting"): "meeting",
    ("activity", "concert"): "activity",
    ("activity", "theater"): "activity",
    ("activity", "tour"): "activity",
    ("transport", "ferry"): "transport",
}


def _app_trip_cards(connection: Any, owner: str, tab: str) -> list[dict[str, Any]]:
    """Build the list-variant trip cards for one dashboard tab, reproduced from
    the captured DOM with the deterministic /app id scheme and frozen-clock date
    spans."""

    query = _APP_TAB_QUERY.get(tab)
    if query is None:
        return []
    cards: list[dict[str, Any]] = []
    for trip in db.list_trips(connection, owner, query):
        base, rel = _app_date_parts(trip)
        cards.append(
            {
                "public_id": _app_uuid(trip["trip_id"], 1),
                "name": trip["name"],
                "destination": trip["destination"],
                "date_span": f"{base} ({rel})" if base else "",
                "date_rel": rel,
                "image": _app_trip_image(trip),
            }
        )
    return cards


# ---------------------------------------------------------------------------
# application
# ---------------------------------------------------------------------------


app = FastAPI(
    title="TripIt offline clone",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

class _MirrorStaticFiles(StaticFiles):
    """StaticFiles that also resolves vendored payloads whose on-disk names
    diverge from the requested name in two ways the mirror introduces:

    1. Percent-encoding: the closure preserves the source URL's percent-encoding
       (e.g. ``Tickets%20%281%29_0.svg``, ``ico-airhelp%402x.svg``). Starlette
       URL-decodes the request path before lookup, so the decoded name misses the
       byte-exact encoded file; we retry with each segment re-encoded.
    2. Content-addressing: the download tool renames query-string assets
       (``fontawesome-webfont.woff2?v=4.6.0`` -> ``fontawesome-webfont.q<hex>.woff2``)
       and rewrites the referencing markup, but a few vendored stylesheets still
       ``url()`` the pre-hash name. Starlette strips the query and misses the
       renamed file; we retry against the content-addressed sibling.

    Both retries resolve only on an exact/unambiguous on-disk match: a re-quote
    that equals the input, or content-addressing with anything other than exactly
    one matching sibling, falls through to a real 404 — so this never masks a
    genuine closure gap."""

    def lookup_path(self, path: str) -> "tuple[str, os.stat_result | None]":
        full_path, stat_result = super().lookup_path(path)
        if stat_result is not None:
            return full_path, stat_result
        requoted = "/".join(urllib.parse.quote(seg) for seg in path.split("/"))
        if requoted != path:
            full_path, stat_result = super().lookup_path(requoted)
            if stat_result is not None:
                return full_path, stat_result
        hashed = self._hashed_sibling(path)
        if hashed is not None:
            return super().lookup_path(hashed)
        return full_path, stat_result

    def _hashed_sibling(self, path: str) -> "str | None":
        """Map a query-stripped request name onto the download tool's
        content-addressed sibling (``foo.ext`` -> ``foo.q<hex>.ext``), returning
        the mount-relative path to retry when exactly one such sibling exists on
        disk, else ``None`` (a genuinely missing asset still 404s)."""
        if path.startswith(("/", "\\")):
            return None
        head, _, tail = path.rpartition("/")
        dot = tail.rfind(".")
        if dot <= 0:
            return None
        prefix, suffix = tail[:dot] + ".q", tail[dot:]
        for directory in self.all_directories:
            parent = os.path.realpath(os.path.join(directory, head))
            base = os.path.realpath(directory)
            if os.path.commonpath([parent, base]) != base:
                continue
            try:
                names = sorted(
                    name
                    for name in os.listdir(parent)
                    if name.startswith(prefix)
                    and name.endswith(suffix)
                    and os.path.isfile(os.path.join(parent, name))
                )
            except (FileNotFoundError, NotADirectoryError):
                continue
            if len(names) == 1:
                return f"{head}/{names[0]}" if head else names[0]
        return None


@app.get("/static/auth-verification.js", include_in_schema=False)
async def public_registration_verification_script() -> Response:
    """Shared verification helper; 404 unless the runtime is configured.

    Registered ahead of the /static mount so the generated asset is not shadowed
    by the mirrored closure when the runtime is live.
    """

    return registration_script_response(PUBLIC_REGISTRATION_VERIFICATION)


app.mount("/static", _MirrorStaticFiles(directory=str(STATIC_DIR)), name="static")

# The mirrored CSS/JS reference theme fonts, icomoon glyphs, and inline images by
# the origin-absolute paths the source served them from (/themes, /images,
# /sites, /core) rather than the /static closure path, and the logged-in app is a
# Bootstrap-Vue design system whose entire visual identity lives in /app/assets/*
# (app CSS + ProximaNova + inline app images). Marketing (2026-08-03) and the
# authenticated bundle (2026-08-05) are separate dated snapshots that share the
# www.tripit.com origin path space, so each origin prefix is mounted from the
# first snapshot that actually provides it. Serving at the real source paths keeps
# both anonymous and logged-in view-source byte-identical to the source with zero
# remote requests. /app/assets is mounted at that specific prefix — never bare
# /app — so it cannot shadow the /app/trips application routes registered later.
_assets_root = STATIC_DIR / "assets"
_snapshots = (
    sorted((p for p in _assets_root.iterdir() if p.is_dir()), reverse=True)
    if _assets_root.is_dir()
    else []
)


def _first_origin(rel: str) -> Path | None:
    """First snapshot mirror that provides the given www.tripit.com/<rel> node."""
    for _snap in _snapshots:
        cand = _snap / "www.tripit.com" / rel
        if cand.exists():
            return cand
    return None


for _prefix in ("themes", "images", "sites", "core", "app/assets"):
    _mirror_dir = _first_origin(_prefix)
    if _mirror_dir is not None and _mirror_dir.is_dir():
        app.mount(
            f"/{_prefix}",
            _MirrorStaticFiles(directory=str(_mirror_dir)),
            name=f"origin-{_prefix.replace('/', '-')}",
        )

# The favicon the live app serves at /app/favicon_v2.ico is byte-for-byte a PNG
# (the ".ico" URL is historical). It is stored on disk as .png so the asset
# verifier reads its intrinsic PNG dimensions, but is still served at the real
# source URL with the source's Content-Type, so the response is indistinguishable.
_APP_FAVICON = _first_origin("app/favicon_v2.png")


@app.get("/app/favicon_v2.ico", include_in_schema=False)
async def app_favicon() -> Response:
    """Serve the logged-in app favicon at its real source path."""
    if _APP_FAVICON is not None and _APP_FAVICON.is_file():
        return FileResponse(str(_APP_FAVICON), media_type="image/vnd.microsoft.icon")
    return Response(status_code=404)


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
        return Response(
            content=json.dumps({"error": "forbidden"}, separators=(",", ":")),
            media_type="application/json",
            status_code=403,
        )
    reset_fixture_state()
    return Response(
        content=json.dumps({"reset": True, "site_id": SITE_ID}, separators=(",", ":")),
        media_type="application/json",
    )


# Unlinked email-ingestion simulator: the deterministic stand-in for TripIt's
# inbound "forward to plans@tripit.com" pipeline. Same management tier as
# /__admin/reset (double-underscore, never linked from any page, so it stays off
# the blind-test surface). Imports are attributed to the signed-in traveler.
IMPORT_FIXTURES_DIR = ROOT / "backend" / "data" / "import_fixtures"


def _import_fixture_library() -> list[dict[str, Any]]:
    try:
        index = json.loads((IMPORT_FIXTURES_DIR / "index.json").read_text("utf-8"))
    except (OSError, ValueError):
        return []
    return list(index.get("fixtures", []))


def _sim_inbox_view(
    request: Request,
    traveler: dict[str, Any],
    *,
    last_result: dict[str, Any] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    with closing(db.connect()) as connection:
        history = db.list_import_messages(connection, traveler["owner_key"])
    return _render(
        request,
        "sim_inbox.html",
        {
            "fixtures": _import_fixture_library(),
            "history": history,
            "last_result": last_result,
            "error": error,
            "viewer_email": _viewer_email(traveler),
        },
        status_code=status_code,
    )


@app.get("/__sim/inbox", include_in_schema=False)
async def sim_inbox(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    return _sim_inbox_view(request, traveler)


@app.post("/__sim/inbox", include_in_schema=False)
async def sim_inbox_submit(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    form = await request.form()
    mode = str(form.get("mode") or "").strip()
    raw = ""
    if mode == "fixture":
        name = os.path.basename(str(form.get("fixture") or ""))
        if name in {entry["file"] for entry in _import_fixture_library()}:
            try:
                raw = (IMPORT_FIXTURES_DIR / name).read_text("utf-8")
            except OSError:
                raw = ""
    elif mode == "paste":
        raw = str(form.get("raw_text") or "")
    elif mode == "upload":
        upload = form.get("eml_file")
        if upload is not None and not isinstance(upload, str):
            data = await upload.read()
            raw = (
                data.decode("utf-8", "replace")
                if isinstance(data, (bytes, bytearray))
                else str(data)
            )
    if not raw.strip():
        return _sim_inbox_view(
            request,
            traveler,
            error="Choose a sample, paste a message, or upload an .eml file.",
            status_code=400,
        )
    result = db.import_email(traveler["owner_key"], raw)
    return _sim_inbox_view(request, traveler, last_result=result)


@app.get("/external/{slug}", include_in_schema=False)
async def external_boundary(slug: str) -> HTMLResponse:
    # Local boundary for third-party navigation targets: the clone never
    # proxies out, so every off-site affordance lands on this same-origin page.
    return HTMLResponse(_EXTERNAL_PAGE)


# ---------------------------------------------------------------------------
# auth — POST handlers wired to the frozen form actions and field names
# ---------------------------------------------------------------------------


def _render_login(
    request: Request,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    payload: dict[str, Any] = {
        "email": "",
        "remember_me": False,
        "form_error": "",
        "email_error": False,
        "password_error": False,
    }
    if context:
        payload.update(context)
    return _render(request, "account_login.html", payload, status_code=status_code)


def _render_create(
    request: Request,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    payload: dict[str, Any] = {
        "email": "",
        "place": "",
        "form_error": "",
        "email_error": False,
        "password_error": False,
    }
    if context:
        payload.update(context)
    return _render(request, "account_create.html", payload, status_code=status_code)


@app.get("/account/login", include_in_schema=False)
async def account_login_form(request: Request) -> Response:
    """Sign-in surface. Live template; the empty render reproduces the frozen
    capture byte for byte, and a rejected submission re-renders through the same
    template with the source's own error classes."""

    return _render_login(request)


@app.get("/account/create", include_in_schema=False)
async def account_create_form(request: Request) -> Response:
    """Registration surface, live for the same reason as the sign-in surface."""

    return _render_create(request)


@app.post("/account/login", include_in_schema=False)
async def account_login(request: Request) -> Response:
    form = await request.form()
    email = str(form.get("login_email_address") or "").strip()
    password = str(form.get("login_password") or "")
    remember = bool(str(form.get("remember_me") or "").strip())
    target = _safe_next(str(form.get("redirect_url") or "") or None, default="/app/trips")

    if not email or not EMAIL_RE.match(email) or not password:
        # Shape errors are answered without touching the store. Only the email
        # field is flagged: revealing its wrapper also reveals the captured
        # "Please use a valid email address." helper, which is exactly the right
        # sentence. The password field's helper reads "At least 15 characters.
        # Cannot be an email." — a registration rule that would be a lie next to
        # a sign-in field, so the password is never flagged here.
        return _render_login(
            request,
            {
                "email": email,
                "remember_me": remember,
                "email_error": bool(email) and not EMAIL_RE.match(email),
                "form_error": "Enter your email address and password to sign in.",
            },
            status_code=400,
        )

    store = auth_store()
    anon_token, _ = store.ensure_session(request.cookies.get(SESSION_COOKIE))
    try:
        signed = store.sign_in(anon_token, email=email, password=password)
    except AuthRateLimited:
        # Generic re-render; no existence disclosure, no session issued.
        return _render_login(
            request,
            {
                "email": email,
                "remember_me": remember,
                "form_error": "Too many sign-in attempts. Please try again shortly.",
            },
            status_code=429,
        )
    except AuthError:
        # One message for "no such account" and "wrong password" alike, so a
        # failed sign-in never discloses whether the address is registered. The
        # status stays 200: a rejected sign-in re-renders the form, and the
        # signal that it was rejected is the absence of a session cookie, which
        # is the contract the backend suite already pins.
        return _render_login(
            request,
            {
                "email": email,
                "remember_me": remember,
                "form_error": "That email address and password do not match an account.",
            },
        )

    response = RedirectResponse(target, status_code=303)
    _set_session_cookie(response, str(signed["session_token"]), persistent=remember)
    return response


@app.get("/account/signInGoogle", include_in_schema=False)
async def third_party_sign_in_boundary(request: Request) -> Response:
    """Same-origin destination for the sign-in surface's Google control.

    Both auth surfaces ship one (``/account/signInGoogle`` and
    ``/account/signUpGoogle``). Federated identity is not modelled here, so the
    control lands on a page that says so and points at the email form instead of
    silently doing nothing or signing anyone in as a side effect.
    """

    return _render(request, "auth_boundary.html", dict(THIRD_PARTY_AUTH["signInGoogle"]))


@app.get("/account/signUpGoogle", include_in_schema=False)
async def third_party_sign_up_boundary(request: Request) -> Response:
    """Same-origin destination for the create surface's Google control."""

    return _render(request, "auth_boundary.html", dict(THIRD_PARTY_AUTH["signUpGoogle"]))


@app.get("/complete/place", include_in_schema=False)
async def complete_place(query: str = "", limit: int = 15, near: str = "") -> Response:
    """Home City suggestions for the create form's vendored place picker.

    Contract taken from ``static/assets/.../components/placepicker.js``: the
    picker requests ``?query=&limit=`` (plus ``near`` for the focus pass) and
    expects a JSON array of ``{value,label}`` for the plain form, or
    ``{"near": [...]}``  when it asked for nearby matches.
    """

    term = query.strip()
    try:
        cap = max(1, min(int(limit), 25))
    except (TypeError, ValueError):
        cap = 15
    if len(term) < 3:
        matches: list[str] = []
    else:
        folded = term.casefold()
        starts = [p for p in HOME_CITY_PLACES if p.casefold().startswith(folded)]
        contains = [
            p
            for p in HOME_CITY_PLACES
            if folded in p.casefold() and p not in starts
        ]
        matches = (starts + contains)[:cap]
    rows = [{"value": place, "label": place} for place in matches]
    if str(near).strip().lower() in ("1", "true", "yes"):
        return JSONResponse({"near": rows})
    return JSONResponse(rows)


@app.post("/api/auth/send-code", include_in_schema=False)
async def public_registration_send_code(request: Request) -> Response:
    return await send_registration_code(
        request,
        verification=PUBLIC_REGISTRATION_VERIFICATION,
        store=auth_store(),
        session_token=request.cookies.get(SESSION_COOKIE, ""),
    )


@app.post("/api/auth/verify-code", include_in_schema=False)
async def public_registration_verify_code(request: Request) -> Response:
    return await verify_registration_code(
        request,
        verification=PUBLIC_REGISTRATION_VERIFICATION,
        store=auth_store(),
        session_token=request.cookies.get(SESSION_COOKIE, ""),
    )


@app.post("/account/logout", include_in_schema=False)
async def account_logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_store().sign_out(token)
    response = RedirectResponse("/", status_code=303)
    _clear_session_cookie(response)
    return response


async def _account_register(request: Request) -> Response:
    """Registration step 1 (the create form posts here): validate + issue code.

    The User Agreement checkbox is the real ``toc`` field: the captured form
    gated it on the client only, behind a hidden ``toc=1`` that made the server
    accept an unticked box. Enforcing it here is the difference between a
    control that means something and one that is decoration.
    """

    form = await request.form()
    email = str(form.get("email_address") or "").strip()
    password = str(form.get("password") or "")
    place = str(form.get("place") or "").strip()
    agreed = bool(str(form.get("toc") or "").strip())

    base = {"email": email, "place": place}

    if not EMAIL_RE.match(email):
        return _render_create(
            request,
            {
                **base,
                "email_error": True,
                "form_error": "Please use a valid email address.",
            },
            status_code=400,
        )
    if len(password) < MIN_REGISTRATION_PASSWORD or EMAIL_RE.match(password):
        return _render_create(
            request,
            {
                **base,
                "password_error": True,
                "form_error": "At least 15 characters. Cannot be an email.",
            },
            status_code=400,
        )
    if not agreed:
        return _render_create(
            request,
            {
                **base,
                "form_error": (
                    "Please accept the TripIt User Agreement to create an account."
                ),
            },
            status_code=400,
        )

    store = auth_store()
    anon_token, _ = store.ensure_session(request.cookies.get(SESSION_COOKIE))
    display_name = _display_name_from_email(email)

    if PUBLIC_REGISTRATION_VERIFICATION is not None:
        # Deployed instances verify the address through the shared runtime
        # before the account exists; the ticket is issued by the send-code /
        # verify-code pair this same form drives.
        try:
            store.validate_registration_details(
                email=email, display_name=display_name, password=password
            )
            ticket = consume_registration_ticket(
                verification=PUBLIC_REGISTRATION_VERIFICATION,
                store=store,
                session_token=anon_token,
                email=email,
            )
            if not ticket:
                response = _render_create(
                    request,
                    {
                        **base,
                        "email_error": True,
                        "form_error": (
                            "Verify this email address before creating the account."
                        ),
                    },
                    status_code=422,
                )
                _set_session_cookie(response, anon_token)
                return response
            completed = store.complete_externally_verified_registration(
                anon_token,
                email=email,
                display_name=display_name,
                password=password,
                subject_factory=db.create_account_subject,
            )
        except VerificationUnavailable:
            response = _render_create(
                request,
                {**base, "form_error": "Email verification is temporarily unavailable."},
                status_code=503,
            )
            _set_session_cookie(response, anon_token)
            return response
        except AuthConflict:
            response = _render_create(
                request,
                {
                    **base,
                    "email_error": True,
                    "form_error": "An account already exists for that email address.",
                },
                status_code=409,
            )
            _set_session_cookie(response, anon_token)
            return response
        except AuthError:
            response = _render_create(
                request,
                {**base, "form_error": "That registration could not be completed."},
                status_code=400,
            )
            _set_session_cookie(response, anon_token)
            return response
        new_token = str(completed.get("session_token") or anon_token)
        _apply_home_city(new_token, place)
        response = RedirectResponse("/app/trips", status_code=303)
        _set_session_cookie(response, new_token)
        return response

    try:
        store.start_registration(
            anon_token,
            email=email,
            display_name=display_name,
            password=password,
            restart_invalid_flow=True,
        )
    except AuthConflict:
        response = _render_create(
            request,
            {
                **base,
                "email_error": True,
                "form_error": "An account already exists for that email address.",
            },
            status_code=409,
        )
        _set_session_cookie(response, anon_token)
        return response
    except (AuthValidationError, AuthRejected) as exc:
        response = _render_create(
            request,
            {
                **base,
                "password_error": True,
                "form_error": str(exc) or "That registration could not be started.",
            },
            status_code=400,
        )
        _set_session_cookie(response, anon_token)
        return response
    except AuthRateLimited:
        response = _render_create(
            request,
            {**base, "form_error": "Too many attempts. Please try again shortly."},
            status_code=429,
        )
        _set_session_cookie(response, anon_token)
        return response

    response = _render(
        request,
        "register_challenge.html",
        {"stage": "verify", "email": email, "place": place, "errors": []},
    )
    _set_session_cookie(response, anon_token)
    return response


@app.post("/account/update", include_in_schema=False)
async def account_register(request: Request) -> Response:
    """The captured create form's own action."""

    return await _account_register(request)


@app.post("/account/create", include_in_schema=False)
async def account_create_submit(request: Request) -> Response:
    """Same handler at the surface's own path, so a submission aimed at
    ``/account/create`` is answered rather than 404ing on method."""

    return await _account_register(request)


@app.post("/account/verify", include_in_schema=False)
async def account_verify(request: Request) -> Response:
    """Registration step 2: verify the emailed code and finish signed in."""

    form = await request.form()
    code = str(form.get("code") or "").strip()
    email = str(form.get("email") or "").strip()
    place = str(form.get("place") or "").strip()

    token = request.cookies.get(SESSION_COOKIE)
    store = auth_store()
    if not token:
        return _login_redirect()
    try:
        store.verify_registration_code(token, code)
        completed = store.complete_registration(
            token, subject_factory=db.create_account_subject
        )
    except AuthError:
        return _render(
            request,
            "register_challenge.html",
            {
                "stage": "verify",
                "email": email,
                "place": place,
                "errors": ["That code is incorrect or expired. Check your email and try again."],
            },
            status_code=400,
        )

    new_token = str(completed.get("session_token") or token)
    _apply_home_city(new_token, place)

    response = RedirectResponse("/trips", status_code=303)
    _set_session_cookie(response, new_token)
    return response


@app.post("/account/forgotPassword", include_in_schema=False)
async def account_forgot_password(request: Request) -> Response:
    """Enumeration-safe reset request: always confirm without disclosure."""

    form = await request.form()
    email = str(form.get("email_address") or "").strip()

    store = auth_store()
    anon_token, _ = store.ensure_session(request.cookies.get(SESSION_COOKIE))
    if EMAIL_RE.match(email):
        try:
            store.start_password_reset(
                anon_token, email=email, restart_invalid_flow=True
            )
        except AuthError:
            # Non-existent address or rate limit: stay silent to avoid
            # disclosing whether the account exists.
            pass

    response = _render(
        request,
        "message.html",
        {
            "heading": "Check your email",
            "body": (
                "If an account exists for that address, we've sent a message "
                "with steps to reset your password."
            ),
        },
    )
    _set_session_cookie(response, anon_token)
    return response


# ---------------------------------------------------------------------------
# trips + plans (authenticated, owner-scoped)
# ---------------------------------------------------------------------------

_TABS = ("upcoming", "past", "unfiled")


@app.get("/trips", include_in_schema=False)
async def trips_list(request: Request, tab: str = "upcoming") -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    tab = tab if tab in _TABS else "upcoming"
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        if tab == "unfiled":
            trips: list[dict[str, Any]] = []
            unfiled = db.list_unfiled_plans(connection, owner)
        else:
            trips = db.list_trips(connection, owner, tab)
            unfiled = []
            for trip in trips:
                plans = db.list_plans_for_trip(connection, owner, trip["trip_id"])
                trip["plan_count"] = len(plans)
                trip["date_range"] = _trip_date_range(trip)
        incoming = db.list_incoming_shares(connection, _viewer_email(traveler), owner)
    for share in incoming:
        share["date_range"] = _trip_date_range(share)
    counts = _tab_counts(owner)
    return _render(
        request,
        "trips_list.html",
        {
            "profile": profile,
            "active_tab": tab,
            "trips": trips,
            "unfiled": unfiled,
            "tab_counts": counts,
            "incoming_shares": incoming,
            "plan_type_labels": PLAN_TYPE_LABELS,
        },
    )


def _validate_trip_form(
    name: str, start_date: str, end_date: str, tz_name: str
) -> list[str]:
    errors: list[str] = []
    if not name:
        errors.append("Enter a name for your trip.")
    if not _valid_date(start_date) or not _valid_date(end_date):
        errors.append("Enter both a start and an end date.")
    elif end_date < start_date:
        errors.append("Your end date must be on or after your start date.")
    if not _valid_timezone(tz_name):
        errors.append("Choose a primary location time zone.")
    return errors


def _trip_form_error(
    request: Request,
    owner: str,
    mode: str,
    trip: dict[str, Any] | None,
    form: Any,
    errors: list[str],
) -> HTMLResponse:
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
    return _render(
        request,
        "trip_form.html",
        {
            "profile": profile,
            "mode": mode,
            "trip": trip,
            "form_token": secrets.token_hex(16),
            "timezones": COMMON_TIMEZONES,
            "values": {key: form.get(key) for key in form.keys()},
            "errors": errors,
        },
        status_code=400,
    )


@app.get("/trips/new", include_in_schema=False)
async def trip_new_form(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, traveler["owner_key"]) or {}
    return _render(
        request,
        "trip_form.html",
        {
            "profile": profile,
            "mode": "create",
            "trip": None,
            "form_token": secrets.token_hex(16),
            "timezones": COMMON_TIMEZONES,
            "values": {"timezone": "America/New_York"},
            "errors": [],
        },
    )


@app.post("/trips", include_in_schema=False)
async def trip_create(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    form = await request.form()
    name = str(form.get("name") or "").strip()
    destination = str(form.get("destination") or "").strip()
    start_date = str(form.get("start_date") or "").strip()
    end_date = str(form.get("end_date") or "").strip()
    tz_name = str(form.get("timezone") or "").strip() or "UTC"
    idempotency_key = str(form.get("idempotency_key") or "").strip() or None
    errors = _validate_trip_form(name, start_date, end_date, tz_name)
    if errors:
        return _trip_form_error(request, owner, "create", None, form, errors)
    result = db.create_trip(
        owner,
        name=name,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        timezone=tz_name,
        idempotency_key=idempotency_key,
    )
    return RedirectResponse(f"/trips/{result['trip_id']}", status_code=303)


@app.get("/trips/{trip_id}/edit", include_in_schema=False)
async def trip_edit_form(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    return _render(
        request,
        "trip_form.html",
        {
            "profile": profile,
            "mode": "edit",
            "trip": trip,
            "form_token": secrets.token_hex(16),
            "timezones": COMMON_TIMEZONES,
            "values": {
                "name": trip["name"],
                "destination": trip.get("destination") or "",
                "start_date": trip["start_date"],
                "end_date": trip["end_date"],
                "timezone": trip["timezone"],
            },
            "errors": [],
        },
    )


@app.post("/trips/{trip_id}/edit", include_in_schema=False)
async def trip_update(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    form = await request.form()
    name = str(form.get("name") or "").strip()
    destination = str(form.get("destination") or "").strip()
    start_date = str(form.get("start_date") or "").strip()
    end_date = str(form.get("end_date") or "").strip()
    tz_name = str(form.get("timezone") or "").strip() or "UTC"
    errors = _validate_trip_form(name, start_date, end_date, tz_name)
    if errors:
        return _trip_form_error(request, owner, "edit", trip, form, errors)
    db.update_trip(
        owner,
        trip_id,
        name=name,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        timezone=tz_name,
    )
    return RedirectResponse(f"/trips/{trip_id}", status_code=303)


@app.post("/trips/{trip_id}/delete", include_in_schema=False)
async def trip_delete(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    try:
        db.delete_trip(traveler["owner_key"], trip_id)
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse("/trips", status_code=303)


@app.get("/app", include_in_schema=False)
async def app_root(request: Request) -> Response:
    """The logged-in app root lands on the trips dashboard, matching the source."""

    if current_traveler(request) is None:
        return _login_redirect()
    return RedirectResponse("/app/trips", status_code=303)


@app.get("/app/trips", include_in_schema=False)
async def app_trips(
    request: Request, tab: str = "upcoming-your", trips_filter: str = ""
) -> Response:
    """High-fidelity logged-in dashboard (the post-login landing) reproduced from
    the captured Bootstrap-Vue DOM. Each tab is a real URL so state survives
    reload and deep links; cards are owner-scoped and rendered from the seed.

    ``trips_filter`` is the source's own query name for the same selection
    (evidence: source-auth-scratch/*/harvested-app-links.json); it is accepted
    as an alias so a link copied from the live app resolves here too.
    """

    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    alias = _APP_TAB_ALIASES.get(trips_filter.strip())
    if alias is not None:
        tab = alias
    active_tab = tab if tab in _APP_TABS else "upcoming-your"
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        cards = _app_trip_cards(connection, owner, active_tab)
    return _render(
        request,
        "app/trips_list.html",
        {"profile": profile, "active_tab": active_tab, "cards": cards},
    )


@app.get("/app/trips/{public_id}", include_in_schema=False)
async def app_trip_detail(request: Request, public_id: str) -> Response:
    """High-fidelity logged-in trip timeline reproduced from the captured
    Bootstrap-Vue DOM. Owner-scoped: an id that resolves to no trip the caller
    owns is a 404, never leaking existence."""

    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        trip = _resolve_app_trip(connection, owner, public_id)
        if trip is None:
            return _not_found(request)
        plans = db.list_plans_for_trip(connection, owner, trip["trip_id"])
    trip["public_id"] = public_id
    trip["date_span"] = _app_date_span(trip)
    trip["image"] = _app_trip_image(trip)
    sections = _app_timeline(plans, trip.get("timezone"))
    return _render(
        request,
        "app/trip_detail.html",
        {"profile": profile, "trip": trip, "sections": sections},
    )


# ---------------------------------------------------------------------------
# /app/* — the source's own logged-in URL space, wired to the same backend
#
# Every path here is one the live app links to (evidence:
# source-auth-scratch/*/harvested-app-links.json plus the captured DOM the
# app/ templates were built from). They were previously unregistered, so the
# whole logged-in surface offered controls that answered 404. Each one now
# resolves the deterministic public id to the owner-scoped row and either
# serves the surface or redirects to the route that already implements it; an
# id that resolves to nothing the caller owns is a 404 that discloses nothing.
# ---------------------------------------------------------------------------


def _resolve_app_plan(
    connection: Any, owner: str, trip: dict[str, Any], plan_public_id: str
) -> dict[str, Any] | None:
    """Map a trip-scoped /app plan uuid back to the owner's stored plan."""

    for plan in db.list_plans_for_trip(connection, owner, trip["trip_id"]):
        if _app_plan_uuid(plan) == plan_public_id:
            return plan
    return None


def _app_trip_or_none(
    request: Request, public_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve (traveler, trip) for an /app trip path, or (traveler, None)."""

    traveler = current_traveler(request)
    if traveler is None:
        return None, None
    with closing(db.connect()) as connection:
        trip = _resolve_app_trip(connection, traveler["owner_key"], public_id)
    if trip is not None:
        trip["public_id"] = public_id
    return traveler, trip


@app.get("/app/account/profile", include_in_schema=False)
async def app_account_profile(request: Request) -> Response:
    if current_traveler(request) is None:
        return _login_redirect()
    return RedirectResponse("/account", status_code=303)


@app.get("/app/settings/notifications", include_in_schema=False)
async def app_settings_notifications(request: Request) -> Response:
    """Notification settings + the traveler's own notification history."""

    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        rows = connection.execute(
            "SELECT kind, title, body, read_at, created_at FROM tripit_notifications "
            "WHERE owner_key=? ORDER BY created_at DESC, notification_id",
            (owner,),
        ).fetchall()
    return _render(
        request,
        "notifications.html",
        {"profile": profile, "notifications": [dict(row) for row in rows]},
    )


@app.get("/app/logout", include_in_schema=False)
async def app_logout_confirm(request: Request) -> Response:
    """Sign-out is a state change, so the link lands on a form rather than
    ending the session on a GET. The form posts to the real sign-out route."""

    if current_traveler(request) is None:
        return RedirectResponse("/", status_code=303)
    return _render(request, "signout.html")


@app.post("/app/logout", include_in_schema=False)
async def app_logout(request: Request) -> Response:
    return await account_logout(request)


@app.get("/app/trip/create", include_in_schema=False)
async def app_trip_create(request: Request) -> Response:
    if current_traveler(request) is None:
        return _login_redirect()
    return RedirectResponse("/trips/new", status_code=303)


@app.get("/app/trips/{public_id}/edit", include_in_schema=False)
async def app_trip_edit(request: Request, public_id: str) -> Response:
    traveler, trip = _app_trip_or_none(request, public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None:
        return _not_found(request)
    return RedirectResponse(f"/trips/{trip['trip_id']}/edit", status_code=303)


@app.get("/app/trips/{public_id}/sharing", include_in_schema=False)
async def app_trip_sharing(request: Request, public_id: str) -> Response:
    traveler, trip = _app_trip_or_none(request, public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None:
        return _not_found(request)
    return RedirectResponse(f"/trips/{trip['trip_id']}/share", status_code=303)


@app.get("/app/trips/{public_id}/print", include_in_schema=False)
async def app_trip_print(request: Request, public_id: str) -> Response:
    """Printable itinerary: the same owner-scoped truth as the timeline, laid
    out as one uninterrupted document with the browser's own print styles."""

    traveler, trip = _app_trip_or_none(request, public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None:
        return _not_found(request)
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        plans = db.list_plans_for_trip(connection, owner, trip["trip_id"])
    trip["date_range"] = _trip_date_range(trip)
    return _render(
        request,
        "trip_print.html",
        {
            "profile": profile,
            "trip": trip,
            "timeline": _timeline(plans, trip.get("timezone")),
            "plan_type_labels": PLAN_TYPE_LABELS,
        },
    )


@app.get("/app/trips/{public_id}/cost", include_in_schema=False)
async def app_trip_cost(request: Request, public_id: str) -> Response:
    """Trip cost.

    Plans in this data set carry no price: ``tripit_plans`` has no cost column
    and none of the captured plan forms collect one, so there is no honest
    number to total. The page therefore reports what it does know -- the plans
    that would make up the total -- and says plainly that no amounts are
    recorded, rather than rendering a fabricated 0.00.
    """

    traveler, trip = _app_trip_or_none(request, public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None:
        return _not_found(request)
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        plans = db.list_plans_for_trip(connection, owner, trip["trip_id"])
    trip["date_range"] = _trip_date_range(trip)
    return _render(
        request,
        "trip_cost.html",
        {
            "profile": profile,
            "trip": trip,
            "plans": plans,
            "plan_type_labels": PLAN_TYPE_LABELS,
        },
    )


@app.get("/app/trips/{public_id}/{plan_path}/create", include_in_schema=False)
async def app_plan_create(
    request: Request, public_id: str, plan_path: str, type: str = ""
) -> Response:
    """Add-plan menu destinations. Registered ahead of the plan-detail route so
    the literal 'create' segment is never read as a plan id."""

    traveler, trip = _app_trip_or_none(request, public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None:
        return _not_found(request)
    plan_type = _APP_CREATE_PLAN_TYPE.get(plan_path)
    if plan_type is None:
        return _not_found(request)
    refined = _APP_CREATE_TYPE_REFINEMENT.get((plan_path, type.strip().lower()))
    if type.strip() and refined is None:
        # An unknown ?type= is not silently widened to the base form.
        return _not_found(request)
    plan_type = refined or plan_type
    return RedirectResponse(
        f"/trips/{trip['trip_id']}/add/{plan_type}", status_code=303
    )


@app.get("/app/trips/{public_id}/{plan_path}/{plan_public_id}", include_in_schema=False)
async def app_plan_detail(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> Response:
    """Read-only plan details, the 'View Plan Details' menu destination."""

    traveler, trip = _app_trip_or_none(request, public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None:
        return _not_found(request)
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        plan = _resolve_app_plan(connection, owner, trip, plan_public_id)
    if plan is None or _APP_PLAN_PATH.get(plan["plan_type"]) != plan_path:
        return _not_found(request)
    trip["date_range"] = _trip_date_range(trip)
    return _render(
        request,
        "plan_detail.html",
        {
            "profile": profile,
            "trip": trip,
            "plan": plan,
            "plan_public_id": plan_public_id,
            "plan_path": plan_path,
            "plan_type_label": PLAN_TYPE_LABELS[plan["plan_type"]],
            "detail_rows": _plan_detail_rows(plan),
        },
    )


def _app_plan_or_404(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    traveler, trip = _app_trip_or_none(request, public_id)
    if traveler is None or trip is None:
        return traveler, trip, None
    with closing(db.connect()) as connection:
        plan = _resolve_app_plan(connection, traveler["owner_key"], trip, plan_public_id)
    if plan is not None and _APP_PLAN_PATH.get(plan["plan_type"]) != plan_path:
        plan = None
    return traveler, trip, plan


@app.get(
    "/app/trips/{public_id}/{plan_path}/{plan_public_id}/edit", include_in_schema=False
)
async def app_plan_edit(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> Response:
    traveler, trip, plan = _app_plan_or_404(request, public_id, plan_path, plan_public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None or plan is None:
        return _not_found(request)
    return RedirectResponse(f"/plans/{plan['plan_id']}/edit", status_code=303)


@app.get(
    "/app/trips/{public_id}/{plan_path}/{plan_public_id}/move", include_in_schema=False
)
async def app_plan_move_form(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> Response:
    """'Move Plan': choose the destination trip, then POST to the move route."""

    return await _app_plan_relocate_form(
        request, public_id, plan_path, plan_public_id, mode="move"
    )


@app.get(
    "/app/trips/{public_id}/{plan_path}/{plan_public_id}/copy", include_in_schema=False
)
async def app_plan_copy_form(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> Response:
    """'Copy Plan': choose the destination trip, then POST to the copy route."""

    return await _app_plan_relocate_form(
        request, public_id, plan_path, plan_public_id, mode="copy"
    )


async def _app_plan_relocate_form(
    request: Request,
    public_id: str,
    plan_path: str,
    plan_public_id: str,
    *,
    mode: str,
) -> Response:
    traveler, trip, plan = _app_plan_or_404(request, public_id, plan_path, plan_public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None or plan is None:
        return _not_found(request)
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        choices = [
            {"trip_id": row["trip_id"], "name": row["name"]}
            for tab in ("upcoming", "past")
            for row in db.list_trips(connection, owner, tab)
        ]
    return _render(
        request,
        "plan_relocate.html",
        {
            "profile": profile,
            "trip": trip,
            "plan": plan,
            "plan_public_id": plan_public_id,
            "plan_path": plan_path,
            "plan_type_label": PLAN_TYPE_LABELS[plan["plan_type"]],
            "mode": mode,
            "choices": choices,
            "form_token": secrets.token_hex(16),
        },
    )


@app.post(
    "/app/trips/{public_id}/{plan_path}/{plan_public_id}/copy", include_in_schema=False
)
async def app_plan_copy(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> Response:
    """Duplicate a plan onto the chosen trip (or Unfiled).

    The copy is a fresh plan with no natural key, so it never collides with the
    original's import/confirmation identity; the form token makes a resubmit
    idempotent through the same owner-scoped command ledger every other write
    uses.
    """

    traveler, trip, plan = _app_plan_or_404(request, public_id, plan_path, plan_public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None or plan is None:
        return _not_found(request)
    form = await request.form()
    raw_trip = str(form.get("trip_id") or "").strip()
    target_trip = raw_trip or None
    owner = traveler["owner_key"]
    if target_trip is not None:
        with closing(db.connect()) as connection:
            try:
                db.get_trip(connection, owner, target_trip)
            except (db.Forbidden, db.NotFound):
                return _not_found(request)
    token = str(form.get("form_token") or "").strip() or None
    try:
        db.add_plan(
            owner,
            trip_id=target_trip,
            plan_type=plan["plan_type"],
            title=plan.get("title", ""),
            start_ts_utc=plan.get("start_ts_utc"),
            end_ts_utc=plan.get("end_ts_utc"),
            timezone=plan.get("timezone"),
            details=dict(plan.get("details") or {}),
            natural_key=None,
            idempotency_key=f"copy:{plan['plan_id']}:{token}" if token else None,
        )
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    except db.ValidationError:
        return _not_found(request)
    destination = f"/trips/{target_trip}" if target_trip else "/trips?tab=unfiled"
    return RedirectResponse(destination, status_code=303)


@app.post(
    "/app/trips/{public_id}/{plan_path}/{plan_public_id}/move", include_in_schema=False
)
async def app_plan_move(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> Response:
    traveler, trip, plan = _app_plan_or_404(request, public_id, plan_path, plan_public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None or plan is None:
        return _not_found(request)
    form = await request.form()
    raw_trip = str(form.get("trip_id") or "").strip()
    target_trip = raw_trip or None
    try:
        db.move_plan(traveler["owner_key"], plan["plan_id"], trip_id=target_trip)
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    destination = f"/trips/{target_trip}" if target_trip else "/trips?tab=unfiled"
    return RedirectResponse(destination, status_code=303)


@app.post(
    "/app/trips/{public_id}/{plan_path}/{plan_public_id}/delete", include_in_schema=False
)
async def app_plan_delete(
    request: Request, public_id: str, plan_path: str, plan_public_id: str
) -> Response:
    traveler, trip, plan = _app_plan_or_404(request, public_id, plan_path, plan_public_id)
    if traveler is None:
        return _login_redirect()
    if trip is None or plan is None:
        return _not_found(request)
    try:
        db.delete_plan(traveler["owner_key"], plan["plan_id"])
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(f"/app/trips/{public_id}", status_code=303)


@app.get("/app/cookie-preferences", include_in_schema=False)
async def app_cookie_preferences(request: Request) -> Response:
    """Cookie preferences, the footer control's real destination.

    The live app opens a consent dialog from a script; that control is a real
    page here so it works with scripting off, and the app shell enhances the
    same URL into an in-place dialog.
    """

    return _render(
        request,
        "cookie_preferences.html",
        {"choice": request.cookies.get(COOKIE_CHOICE_COOKIE, "")},
    )


@app.post("/app/cookie-preferences", include_in_schema=False)
async def app_cookie_preferences_save(request: Request) -> Response:
    form = await request.form()
    choice = str(form.get("cookie_choice") or "").strip()
    if choice not in COOKIE_CHOICES:
        return _render(
            request,
            "cookie_preferences.html",
            {
                "choice": request.cookies.get(COOKIE_CHOICE_COOKIE, ""),
                "error": "Choose which cookies to allow.",
            },
            status_code=400,
        )
    target = _safe_next(str(form.get("return_to") or "") or None, default="/app/trips")
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        COOKIE_CHOICE_COOKIE,
        choice,
        max_age=SESSION_MAX_AGE,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )
    return response


@app.get("/trips/{trip_id}", include_in_schema=False)
async def trip_detail(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
        plans = db.list_plans_for_trip(connection, owner, trip_id)
    trip["date_range"] = _trip_date_range(trip)
    timeline = _timeline(plans, trip.get("timezone"))
    return _render(
        request,
        "trip_detail.html",
        {
            "profile": profile,
            "trip": trip,
            "timeline": timeline,
            "plan_type_labels": PLAN_TYPE_LABELS,
        },
    )


@app.get("/trips/{trip_id}/add/{plan_type}", include_in_schema=False)
async def add_plan_form(request: Request, trip_id: str, plan_type: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    if plan_type not in PLAN_TYPE_LABELS:
        return _not_found(request)
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    return _render(
        request,
        "add_plan.html",
        {
            "profile": profile,
            "trip": trip,
            "plan_type": plan_type,
            "plan_type_label": PLAN_TYPE_LABELS[plan_type],
            "form_token": secrets.token_hex(16),
            "lodging_suggestions": LODGING_SUGGESTIONS,
            "values": {},
            "errors": [],
        },
    )


@app.post("/trips/{trip_id}/plans", include_in_schema=False)
async def add_plan_submit(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]

    form = await request.form()
    plan_type = str(form.get("plan_type") or "").strip()
    if plan_type not in PLAN_TYPE_LABELS:
        return _not_found(request)

    with closing(db.connect()) as connection:
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)

    idempotency_key = str(form.get("idempotency_key") or "").strip() or None
    tz_name = trip.get("timezone") or "UTC"
    errors: list[str] = []

    if plan_type == "lodging":
        hotel = str(form.get("title") or form.get("hotel_name") or "").strip()
        check_in = str(form.get("check_in_date") or "").strip()
        check_out = str(form.get("check_out_date") or "").strip()
        confirmation = str(form.get("confirmation") or "").strip()
        if not hotel:
            errors.append("Choose a hotel to continue.")
        if not check_in or not check_out:
            errors.append("Enter both a check-in and a check-out date.")
        elif check_out < check_in:
            errors.append("Check-out must be on or after check-in.")
        if errors:
            return _add_plan_error(request, traveler, trip, plan_type, form, errors)
        start_ts = _local_to_utc_iso(check_in, "15:00", tz_name)
        end_ts = _local_to_utc_iso(check_out, "11:00", tz_name)
        details = {
            "hotel_name": hotel,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "confirmation_number": confirmation,
        }
        result = db.add_plan(
            owner,
            trip_id=trip_id,
            plan_type="lodging",
            title=hotel,
            start_ts_utc=start_ts,
            end_ts_utc=end_ts,
            timezone=tz_name,
            details=details,
            natural_key=_lodging_natural_key(hotel, confirmation),
            idempotency_key=idempotency_key,
        )
    else:
        title = str(form.get("title") or "").strip()
        start_date = str(form.get("start_date") or "").strip()
        start_time = str(form.get("start_time") or "").strip() or "09:00"
        end_date = str(form.get("end_date") or "").strip()
        end_time = str(form.get("end_time") or "").strip() or start_time
        notes = str(form.get("notes") or "").strip()
        if not title:
            errors.append("Enter a title to continue.")
        start_ts = _local_to_utc_iso(start_date, start_time, tz_name) if start_date else None
        end_ts = _local_to_utc_iso(end_date, end_time, tz_name) if end_date else None
        if start_ts and end_ts and end_ts < start_ts:
            errors.append("The end time must be on or after the start time.")
        if errors:
            return _add_plan_error(request, traveler, trip, plan_type, form, errors)
        details = {"notes": notes} if notes else {}
        result = db.add_plan(
            owner,
            trip_id=trip_id,
            plan_type=plan_type,
            title=title,
            start_ts_utc=start_ts,
            end_ts_utc=end_ts,
            timezone=tz_name if start_ts else None,
            details=details,
            idempotency_key=idempotency_key,
        )

    del result  # PRG: the created/replayed id is not surfaced in the redirect.
    return RedirectResponse(f"/trips/{trip_id}", status_code=303)


def _add_plan_error(
    request: Request,
    traveler: dict[str, Any],
    trip: dict[str, Any],
    plan_type: str,
    form: Any,
    errors: list[str],
) -> HTMLResponse:
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, traveler["owner_key"]) or {}
    return _render(
        request,
        "add_plan.html",
        {
            "profile": profile,
            "trip": trip,
            "plan_type": plan_type,
            "plan_type_label": PLAN_TYPE_LABELS[plan_type],
            "form_token": secrets.token_hex(16),
            "lodging_suggestions": LODGING_SUGGESTIONS,
            "values": {key: form.get(key) for key in form.keys()},
            "errors": errors,
        },
        status_code=400,
    )


@app.post("/plans/{plan_id}/move", include_in_schema=False)
async def plan_move(request: Request, plan_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    form = await request.form()
    raw_trip = str(form.get("trip_id") or "").strip()
    target_trip = raw_trip or None
    try:
        db.move_plan(traveler["owner_key"], plan_id, trip_id=target_trip)
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    destination = f"/trips/{target_trip}" if target_trip else "/trips?tab=unfiled"
    return RedirectResponse(destination, status_code=303)


@app.post("/plans/{plan_id}/delete", include_in_schema=False)
async def plan_delete(request: Request, plan_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    form = await request.form()
    return_to = _safe_next(str(form.get("return_to") or "") or None, default="/trips")
    try:
        db.delete_plan(traveler["owner_key"], plan_id)
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(return_to, status_code=303)


def _split_local(ts_utc: str | None, tz_name: str | None) -> tuple[str, str]:
    """Split a UTC stamp into local (YYYY-MM-DD, HH:MM) for prefilling a form."""

    if not ts_utc:
        return ("", "")
    try:
        parsed = datetime.strptime(ts_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_UTC)
    except ValueError:
        return ("", "")
    if tz_name:
        try:
            parsed = parsed.astimezone(ZoneInfo(tz_name))
        except Exception:  # noqa: BLE001 - unknown tz falls back to UTC display
            pass
    return (parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M"))


def _plan_edit_values(plan: dict[str, Any]) -> dict[str, str]:
    details = plan.get("details") or {}
    if plan["plan_type"] == "lodging":
        return {
            "title": plan.get("title", ""),
            "check_in_date": details.get("check_in_date", ""),
            "check_out_date": details.get("check_out_date", ""),
            "confirmation": details.get("confirmation_number", ""),
        }
    start_date, start_time = _split_local(plan.get("start_ts_utc"), plan.get("timezone"))
    end_date, end_time = _split_local(plan.get("end_ts_utc"), plan.get("timezone"))
    return {
        "title": plan.get("title", ""),
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "notes": details.get("notes", ""),
    }


def _plan_edit_context(
    request: Request,
    owner: str,
    plan: dict[str, Any],
    trip: dict[str, Any] | None,
    values: dict[str, Any],
    errors: list[str],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
    return _render(
        request,
        "edit_plan.html",
        {
            "profile": profile,
            "plan": plan,
            "trip": trip,
            "plan_type": plan["plan_type"],
            "plan_type_label": PLAN_TYPE_LABELS[plan["plan_type"]],
            "lodging_suggestions": LODGING_SUGGESTIONS,
            "values": values,
            "errors": errors,
        },
        status_code=status_code,
    )


@app.get("/plans/{plan_id}/edit", include_in_schema=False)
async def plan_edit_form(request: Request, plan_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        try:
            plan = db.get_plan(connection, owner, plan_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
        trip: dict[str, Any] | None = None
        if plan.get("trip_id"):
            try:
                trip = db.get_trip(connection, owner, plan["trip_id"])
            except (db.Forbidden, db.NotFound):
                trip = None
    return _plan_edit_context(
        request, owner, plan, trip, _plan_edit_values(plan), []
    )


@app.post("/plans/{plan_id}/edit", include_in_schema=False)
async def plan_edit_submit(request: Request, plan_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        try:
            plan = db.get_plan(connection, owner, plan_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
        trip: dict[str, Any] | None = None
        if plan.get("trip_id"):
            try:
                trip = db.get_trip(connection, owner, plan["trip_id"])
            except (db.Forbidden, db.NotFound):
                trip = None

    form = await request.form()
    plan_type = plan["plan_type"]
    tz_name = plan.get("timezone") or (trip.get("timezone") if trip else None) or "UTC"
    errors: list[str] = []

    if plan_type == "lodging":
        hotel = str(form.get("title") or "").strip()
        check_in = str(form.get("check_in_date") or "").strip()
        check_out = str(form.get("check_out_date") or "").strip()
        confirmation = str(form.get("confirmation") or "").strip()
        if not hotel:
            errors.append("Choose a hotel to continue.")
        if not check_in or not check_out:
            errors.append("Enter both a check-in and a check-out date.")
        elif check_out < check_in:
            errors.append("Check-out must be on or after check-in.")
        if errors:
            values = {key: form.get(key) for key in form.keys()}
            return _plan_edit_context(
                request, owner, plan, trip, values, errors, status_code=400
            )
        db.update_plan(
            owner,
            plan_id,
            title=hotel,
            start_ts_utc=_local_to_utc_iso(check_in, "15:00", tz_name),
            end_ts_utc=_local_to_utc_iso(check_out, "11:00", tz_name),
            timezone=tz_name,
            details={
                "hotel_name": hotel,
                "check_in_date": check_in,
                "check_out_date": check_out,
                "confirmation_number": confirmation,
            },
        )
    else:
        title = str(form.get("title") or "").strip()
        start_date = str(form.get("start_date") or "").strip()
        start_time = str(form.get("start_time") or "").strip() or "09:00"
        end_date = str(form.get("end_date") or "").strip()
        end_time = str(form.get("end_time") or "").strip() or start_time
        notes = str(form.get("notes") or "").strip()
        if not title:
            errors.append("Enter a title to continue.")
        start_ts = _local_to_utc_iso(start_date, start_time, tz_name) if start_date else None
        end_ts = _local_to_utc_iso(end_date, end_time, tz_name) if end_date else None
        if start_ts and end_ts and end_ts < start_ts:
            errors.append("The end time must be on or after the start time.")
        if errors:
            values = {key: form.get(key) for key in form.keys()}
            return _plan_edit_context(
                request, owner, plan, trip, values, errors, status_code=400
            )
        db.update_plan(
            owner,
            plan_id,
            title=title,
            start_ts_utc=start_ts,
            end_ts_utc=end_ts,
            timezone=tz_name if start_ts else None,
            details={"notes": notes},
        )

    destination = (
        f"/trips/{plan['trip_id']}" if plan.get("trip_id") else "/trips?tab=unfiled"
    )
    return RedirectResponse(destination, status_code=303)


@app.get("/account", include_in_schema=False)
async def account_home(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        pro = db.pro_status(connection, owner)
    return _render(
        request,
        "account.html",
        {
            "profile": profile,
            "email": traveler["account"].get("email_normalized"),
            "pro": pro,
            "pro_renews_on": _fmt_date_long(pro.get("current_period_end")),
        },
    )


@app.get("/api/lodging/typeahead", include_in_schema=False)
async def lodging_typeahead(request: Request, q: str = "") -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return JSONResponse({"results": []}, status_code=401)
    needle = q.strip().lower()
    if not needle:
        results = list(LODGING_SUGGESTIONS)
    else:
        results = [s for s in LODGING_SUGGESTIONS if needle in s["name"].lower()]
    return JSONResponse({"results": results})


# ---------------------------------------------------------------------------
# trip documents (BLOB attachments)
# ---------------------------------------------------------------------------

# The content type is derived from the file extension, never the client-declared
# type, so a renamed or spoofed upload cannot smuggle an unexpected type through
# preview/download. The allowlist mirrors what the source lets travelers attach:
# a booking PDF or a photo/scan of a confirmation.
DOCUMENT_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".webp": "image/webp",
}

# Read ceiling for a single multipart part. Deliberately well above the 2 MB
# business rule so an oversize upload is read in full and rejected with the
# source's own copy, instead of being masked by Starlette's default 1 MB part
# guard (which would surface as a bare 400 before our size check runs). A part
# beyond this ceiling is a defensive stop, not a path a real traveler hits.
_MAX_UPLOAD_PART_BYTES = 16 * 1024 * 1024


def _document_content_type(filename: str) -> str | None:
    _, ext = os.path.splitext(filename.lower())
    return DOCUMENT_CONTENT_TYPES.get(ext)


def _human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _documents_view(
    request: Request,
    traveler: dict[str, Any],
    trip: dict[str, Any],
    *,
    errors: list[str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        documents = db.list_documents(connection, owner, trip["trip_id"])
    for document in documents:
        document["size_label"] = _human_size(document["byte_size"])
    return _render(
        request,
        "documents.html",
        {
            "profile": profile,
            "trip": trip,
            "documents": documents,
            "errors": errors or [],
            "accept": ",".join(sorted(DOCUMENT_CONTENT_TYPES)),
        },
        status_code=status_code,
    )


@app.get("/trips/{trip_id}/documents", include_in_schema=False)
async def documents_home(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    trip["date_range"] = _trip_date_range(trip)
    return _documents_view(request, traveler, trip)


@app.post("/trips/{trip_id}/documents", include_in_schema=False)
async def documents_upload(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    trip["date_range"] = _trip_date_range(trip)

    try:
        form = await request.form(max_part_size=_MAX_UPLOAD_PART_BYTES)
    except MultiPartException:
        return _documents_view(
            request,
            traveler,
            trip,
            errors=["That file is too large to upload."],
            status_code=400,
        )

    upload = form.get("document")
    filename = ""
    blob = b""
    if upload is not None and not isinstance(upload, str):
        filename = os.path.basename(str(upload.filename or "")).strip()
        blob = await upload.read()

    content_type: str | None = None
    errors: list[str] = []
    if not filename:
        errors.append("Choose a file to upload.")
    else:
        content_type = _document_content_type(filename)
        if content_type is None:
            errors.append(
                "Choose a PDF or image file (PDF, PNG, JPG, GIF, HEIC, or WebP)."
            )
        elif len(blob) == 0:
            errors.append("That file is empty.")
        elif len(blob) > db.MAX_DOCUMENT_BYTES:
            errors.append("Documents must be 2 MB or smaller.")
    if errors:
        return _documents_view(
            request, traveler, trip, errors=errors, status_code=400
        )

    try:
        db.add_document(
            owner,
            trip_id=trip_id,
            filename=filename,
            content_type=content_type,
            blob=blob,
        )
    except db.ValidationError as exc:
        return _documents_view(
            request, traveler, trip, errors=[str(exc)], status_code=400
        )
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(f"/trips/{trip_id}/documents", status_code=303)


def _serve_document(
    request: Request, document_id: str, *, disposition: str
) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    with closing(db.connect()) as connection:
        try:
            document = db.get_document(
                connection, traveler["owner_key"], document_id
            )
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    safe_name = (
        re.sub(r'[\r\n"]+', "", document["filename"])
        .encode("ascii", "replace")
        .decode("ascii")
    )
    return Response(
        content=document["blob"],
        media_type=document["content_type"],
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


@app.get("/documents/{document_id}", include_in_schema=False)
async def document_preview(request: Request, document_id: str) -> Response:
    return _serve_document(request, document_id, disposition="inline")


@app.get("/documents/{document_id}/download", include_in_schema=False)
async def document_download(request: Request, document_id: str) -> Response:
    return _serve_document(request, document_id, disposition="attachment")


@app.post("/documents/{document_id}/delete", include_in_schema=False)
async def document_delete(request: Request, document_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    try:
        result = db.delete_document(traveler["owner_key"], document_id)
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(
        f"/trips/{result['trip_id']}/documents", status_code=303
    )


# ---------------------------------------------------------------------------
# sharing (authenticated) — invite by email, roles, sensitive masking, revoke
# ---------------------------------------------------------------------------

SHARE_ROLE_LABELS: dict[str, str] = {
    "viewer": "Viewer",
    "editor": "Editor",
    "traveler": "Fellow traveler",
}


def _checkbox(value: Any) -> bool:
    return str(value or "").strip().lower() in {"on", "true", "1", "yes"}


def _viewer_email(traveler: dict[str, Any]) -> str:
    account = traveler.get("account") or {}
    return str(account.get("email_normalized") or "")


def _mask_timeline(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of the timeline with sensitive plan fields stripped.

    Defense in depth for the "hide confirmation / ticketing details" share
    option: the shared template already gates these fields, and this makes the
    values unavailable to the template altogether when masking is on, so a
    sensitive identifier can never reach a masked viewer's HTML.
    """

    masked: list[dict[str, Any]] = []
    for event in timeline:
        plan = dict(event.get("plan") or {})
        details = {
            key: value
            for key, value in (plan.get("details") or {}).items()
            if key not in db.SENSITIVE_DETAIL_KEYS
        }
        plan["details"] = details
        row = dict(event)
        row["plan"] = plan
        masked.append(row)
    return masked


def _share_view(
    request: Request,
    traveler: dict[str, Any],
    trip: dict[str, Any],
    *,
    errors: list[str] | None = None,
    values: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        profile = db.profile_for(connection, owner) or {}
        shares = db.list_shares_for_trip(connection, owner, trip["trip_id"])
    for share in shares:
        share["role_label"] = SHARE_ROLE_LABELS.get(share["role"], share["role"])
    return _render(
        request,
        "share.html",
        {
            "profile": profile,
            "trip": trip,
            "shares": shares,
            "roles": db.SHARE_ROLES,
            "role_labels": SHARE_ROLE_LABELS,
            "errors": errors or [],
            "values": values or {"role": "viewer", "show_sensitive": False},
        },
        status_code=status_code,
    )


@app.get("/trips/{trip_id}/share", include_in_schema=False)
async def share_home(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    trip["date_range"] = _trip_date_range(trip)
    return _share_view(request, traveler, trip)


@app.post("/trips/{trip_id}/share", include_in_schema=False)
async def share_create(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    owner = traveler["owner_key"]
    with closing(db.connect()) as connection:
        try:
            trip = db.get_trip(connection, owner, trip_id)
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
    trip["date_range"] = _trip_date_range(trip)
    form = await request.form()
    invitee_email = str(form.get("invitee_email") or "").strip()
    role = str(form.get("role") or "viewer").strip()
    show_sensitive = _checkbox(form.get("show_sensitive"))
    values = {
        "invitee_email": invitee_email,
        "role": role,
        "show_sensitive": show_sensitive,
    }
    try:
        db.create_share(
            owner,
            trip_id=trip_id,
            invitee_email=invitee_email,
            role=role,
            show_sensitive=show_sensitive,
        )
    except db.ValidationError as exc:
        return _share_view(
            request,
            traveler,
            trip,
            errors=[str(exc)],
            values=values,
            status_code=400,
        )
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(f"/trips/{trip_id}/share", status_code=303)


@app.post("/shares/{share_id}/role", include_in_schema=False)
async def share_set_role(request: Request, share_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    form = await request.form()
    role = str(form.get("role") or "").strip()
    try:
        result = db.update_share_role(traveler["owner_key"], share_id, role)
    except (db.ValidationError, db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(f"/trips/{result['trip_id']}/share", status_code=303)


@app.post("/shares/{share_id}/sensitive", include_in_schema=False)
async def share_set_sensitive(request: Request, share_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    form = await request.form()
    show_sensitive = _checkbox(form.get("show_sensitive"))
    try:
        result = db.set_share_sensitive(
            traveler["owner_key"], share_id, show_sensitive
        )
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(f"/trips/{result['trip_id']}/share", status_code=303)


@app.post("/shares/{share_id}/revoke", include_in_schema=False)
async def share_revoke(request: Request, share_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    try:
        result = db.revoke_share(traveler["owner_key"], share_id)
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(f"/trips/{result['trip_id']}/share", status_code=303)


@app.post("/shares/{share_id}/accept", include_in_schema=False)
async def share_accept(request: Request, share_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    try:
        result = db.accept_share(
            traveler["owner_key"], _viewer_email(traveler), share_id
        )
    except (db.Forbidden, db.NotFound):
        return _not_found(request)
    return RedirectResponse(f"/shared/{result['trip_id']}", status_code=303)


@app.get("/shared/{trip_id}", include_in_schema=False)
async def shared_trip_detail(request: Request, trip_id: str) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    viewer_email = _viewer_email(traveler)
    with closing(db.connect()) as connection:
        try:
            shared = db.shared_trip_for(
                connection, traveler["owner_key"], viewer_email, trip_id
            )
        except (db.Forbidden, db.NotFound):
            return _not_found(request)
        trip = shared["trip"]
        owner_profile = db.profile_for(connection, trip["owner_key"]) or {}
        plans = db.list_plans_for_trip(connection, trip["owner_key"], trip_id)
    trip["date_range"] = _trip_date_range(trip)
    show_sensitive = shared["show_sensitive"]
    timeline = _timeline(plans, trip.get("timezone"))
    if not show_sensitive:
        timeline = _mask_timeline(timeline)
    return _render(
        request,
        "shared_trip.html",
        {
            "trip": trip,
            "timeline": timeline,
            "role": shared["role"],
            "role_label": SHARE_ROLE_LABELS.get(shared["role"], shared["role"]),
            "show_sensitive": show_sensitive,
            "owner_name": owner_profile.get("display_name") or "A TripIt traveler",
            "plan_type_labels": PLAN_TYPE_LABELS,
        },
    )


# ---------------------------------------------------------------------------
# small read helpers
# ---------------------------------------------------------------------------


_PLAN_DETAIL_LABELS: dict[str, str] = {
    "confirmation_number": "Confirmation number",
    "check_in_date": "Check-in",
    "check_out_date": "Check-out",
    "address": "Address",
    "notes": "Notes",
    "phone": "Phone",
    "supplier": "Supplier",
    "origin": "From",
    "destination": "To",
    "flight_number": "Flight",
    "carrier": "Airline",
    "seat": "Seat",
}


def _plan_detail_rows(plan: dict[str, Any]) -> list[tuple[str, str]]:
    """Label/value rows for the read-only plan view.

    Only keys with a value are shown, and unknown keys keep their stored name
    turned into a label rather than being dropped, so a plan never renders as
    emptier than it is.
    """

    rows: list[tuple[str, str]] = []
    details = plan.get("details") or {}
    for key, value in details.items():
        if value in (None, "", [], {}):
            continue
        label = _PLAN_DETAIL_LABELS.get(key) or key.replace("_", " ").capitalize()
        rows.append((label, str(value)))
    return rows


def _trip_date_range(trip: dict[str, Any]) -> str:
    start = trip.get("start_date")
    end = trip.get("end_date")
    if not start or not end:
        return ""
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return f"{start} – {end}"
    if start_dt.year == end_dt.year:
        return f"{start_dt.strftime('%b %-d')} – {end_dt.strftime('%b %-d, %Y')}"
    return f"{start_dt.strftime('%b %-d, %Y')} – {end_dt.strftime('%b %-d, %Y')}"


def _tab_counts(owner: str) -> dict[str, int]:
    with closing(db.connect()) as connection:
        upcoming = len(db.list_trips(connection, owner, "upcoming"))
        past = len(db.list_trips(connection, owner, "past"))
        unfiled = len(db.list_unfiled_plans(connection, owner))
    return {"upcoming": upcoming, "past": past, "unfiled": unfiled}


# ---------------------------------------------------------------------------
# TripIt Pro — membership lifecycle (Phase 7)
# ---------------------------------------------------------------------------

# Friendly labels over the opaque, frozen sandbox scenario ids. The runtime
# accepts only these three tokens; the visible label never exposes the raw id,
# and the "add a hotel to the New York trip" anchor journey never reaches here.
PRO_SANDBOX_SCENARIOS: tuple[dict[str, Any], ...] = (
    {"value": "sandbox-pro-approved", "label": "Simulate approval", "checked": True},
    {"value": "sandbox-pro-declined", "label": "Simulate decline", "checked": False},
    {
        "value": "sandbox-pro-retryable",
        "label": "Simulate retryable result",
        "checked": False,
    },
)

# Source-plausible TripIt Pro benefits shown on the upgrade and manage surfaces.
PRO_BENEFITS: tuple[str, ...] = (
    "Real-time flight alerts the moment a gate, delay, or cancellation changes",
    "Alternate flights found for you the instant a flight is cancelled",
    "Seat Tracker watches for a better seat and tells you when one opens",
    "Point Tracker keeps every reward-program balance in one place",
    "Fare and refund monitoring so you never leave money on the table",
    "Interactive airport maps with terminal-to-terminal navigation",
)


def _pro_stripe_enabled() -> bool:
    """True only when a payment-scope approval has wired the stripe-test adapter."""

    try:
        return db.payment_adapter() == "stripe-test"
    except Exception:  # noqa: BLE001 - an undeclared profile is simply "not stripe"
        return False


def _pro_status(owner_key: str) -> dict[str, Any]:
    with closing(db.connect()) as connection:
        return db.pro_status(connection, owner_key)


def _fmt_date_long(ts_utc: str | None) -> str:
    if not ts_utc:
        return ""
    try:
        parsed = datetime.strptime(ts_utc, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ts_utc
    return parsed.strftime("%B %-d, %Y")


def _pro_upgrade_view(
    request: Request,
    *,
    error: str | None = None,
    retry: bool = False,
    selected: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    scenarios = [
        {**scenario, "checked": (scenario["value"] == selected)}
        if selected
        else scenario
        for scenario in PRO_SANDBOX_SCENARIOS
    ]
    return _render(
        request,
        "pro_upgrade.html",
        {
            "price_label": db.PRO_PRICE_LABEL,
            "total_label": db.PRO_TOTAL_LABEL,
            "benefits": PRO_BENEFITS,
            "scenarios": scenarios,
            "error": error,
            "retry": retry,
        },
        status_code=status_code,
    )


def _pro_manage_view(
    request: Request, status: dict[str, Any], *, status_code: int = 200
) -> HTMLResponse:
    return _render(
        request,
        "pro_manage.html",
        {
            "price_label": db.PRO_PRICE_LABEL,
            "total_label": db.PRO_TOTAL_LABEL,
            "benefits": PRO_BENEFITS,
            "plan_label": "TripIt Pro (annual)",
            "renews_on": _fmt_date_long(status.get("current_period_end")),
            "cancel_at_period_end": status["cancel_at_period_end"],
            "receipt_id": status.get("receipt_id"),
        },
        status_code=status_code,
    )


@app.get("/pro/upgrade", include_in_schema=False)
async def pro_upgrade(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    if _pro_status(traveler["owner_key"])["is_pro"]:
        return RedirectResponse("/pro/manage", status_code=303)
    return _pro_upgrade_view(request)


@app.post("/pro/subscribe", include_in_schema=False)
async def pro_subscribe(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    form = await request.form()
    scenario = str(form.get("scenario") or "").strip()
    try:
        result = db.subscribe_pro(traveler["owner_key"], scenario)
    except db.BackendError:
        # An unknown scenario token or an adapter mismatch: re-present the upsell
        # with the generic decline copy. No entitlement and no charge are written.
        return _pro_upgrade_view(
            request,
            error=(
                "Payment was not approved. You can try a permitted test "
                "outcome again."
            ),
            selected=scenario,
            status_code=400,
        )
    outcome = result["result"]
    if outcome in ("approved", "already_active"):
        return RedirectResponse("/pro/manage", status_code=303)
    if outcome == "retryable":
        return _pro_upgrade_view(
            request,
            error=(
                "That test outcome is retryable. Submit again to complete your "
                "upgrade."
            ),
            retry=True,
            selected=scenario,
        )
    return _pro_upgrade_view(
        request,
        error=(
            "Payment was not approved. Your upgrade is still open and you can "
            "try a permitted test outcome again."
        ),
        selected=scenario,
    )


@app.get("/pro/manage", include_in_schema=False)
async def pro_manage(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    status = _pro_status(traveler["owner_key"])
    if not status["is_pro"]:
        # A free traveler is sent to the upsell — the source-plausible upgrade page.
        return RedirectResponse("/pro/upgrade", status_code=303)
    return _pro_manage_view(request, status)


@app.post("/pro/cancel", include_in_schema=False)
async def pro_cancel(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    db.cancel_pro(traveler["owner_key"])
    return RedirectResponse("/pro/manage", status_code=303)


@app.post("/pro/resume", include_in_schema=False)
async def pro_resume(request: Request) -> Response:
    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    db.resume_pro(traveler["owner_key"])
    return RedirectResponse("/pro/manage", status_code=303)


@app.get("/pro/stripe-return", include_in_schema=False)
async def pro_stripe_return(request: Request) -> Response:
    """Finalize a server-retrieved Stripe test Session. Dormant off stripe-test."""

    traveler = current_traveler(request)
    if traveler is None:
        return _login_redirect()
    if not _pro_stripe_enabled():
        return _not_found(request)
    if request.query_params.get("cancelled") == "1":
        return RedirectResponse("/pro/upgrade", status_code=303)
    provider_session_id = request.query_params.get("session_id", "")
    if not provider_session_id:
        return RedirectResponse("/pro/upgrade", status_code=303)
    try:
        provider_snapshot = StripeTestGateway(
            db.runtime_config()
        ).retrieve_checkout_session(provider_session_id)
        connection = db.connect()
        try:
            db.process_verified_stripe_pro_payment(
                connection,
                provider_session_id=provider_session_id,
                provider_snapshot=provider_snapshot,
            )
        finally:
            connection.close()
    except (
        db.BackendError,
        StripeTestError,
        StripeTestResponseError,
        StripeTestUnavailable,
    ):
        return RedirectResponse("/pro/upgrade", status_code=303)
    return RedirectResponse("/pro/manage", status_code=303)


@app.post("/api/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request) -> JSONResponse:
    """Accept only an edge-verified Stripe test event, then re-read the Session.

    Dormant under the local-sandbox profile: an edge-verified event still yields
    400 because ``stripe-test`` is not enabled, so no webhook can ever activate
    Pro outside the hosted-checkout profile. An unsigned or oversize body is
    rejected before any parsing.
    """

    if request.headers.get("x-websitebench-stripe-verified") != "1":
        return JSONResponse({"received": False}, status_code=400)
    raw = await request.body()
    if not raw or len(raw) > 64 * 1024:
        return JSONResponse({"received": False}, status_code=400)
    if not _pro_stripe_enabled():
        return JSONResponse({"received": False}, status_code=400)
    try:
        event = json.loads(raw.decode("utf-8"))
        if not isinstance(event, dict):
            raise ValueError("event is invalid")
        if event.get("type") == "checkout.session.expired":
            return JSONResponse({"received": True})
        data = event.get("data")
        session = data.get("object") if isinstance(data, dict) else None
        provider_session_id = session.get("id") if isinstance(session, dict) else None
        if event.get("type") != "checkout.session.completed" or not isinstance(
            provider_session_id, str
        ):
            raise ValueError("event is invalid")
        provider_snapshot = StripeTestGateway(
            db.runtime_config()
        ).retrieve_checkout_session(provider_session_id)
        connection = db.connect()
        try:
            db.process_verified_stripe_pro_payment(
                connection,
                provider_session_id=provider_session_id,
                provider_snapshot=provider_snapshot,
            )
        finally:
            connection.close()
    except (
        ValueError,
        UnicodeDecodeError,
        db.BackendError,
        StripeTestError,
        StripeTestResponseError,
        StripeTestUnavailable,
    ):
        return JSONResponse({"received": False}, status_code=400)
    return JSONResponse({"received": True})


# ---------------------------------------------------------------------------
# persistent-chrome destinations that the frozen pages link to
#
# The captured marketing chrome links to more of the source than the capture
# covers: legacy nav aliases, the five-locale language menu, and every blog
# article the index lists. Those controls sit in the header and footer, so a
# 404 on any of them is visible from every page. Aliases whose destination *is*
# captured redirect to it; the rest land on a page that says the content was
# not built here, which is the honest answer and is still an answer.
# ---------------------------------------------------------------------------

# Legacy nav paths on the legal pages that name a page this build does have.
_MARKETING_ALIASES: dict[str, str] = {
    "/uhp/features": "/web/free",
    "/pro/features": "/web/pro",
    "/uhp/pricing": "/web/pro/pricing",
    "/web/download": "/web/free/download",
    "/pro": "/pro/upgrade",
}

# Linked from the chrome, never captured.
_UNBUILT_MARKETING: tuple[str, ...] = (
    "/uhp/supportedVendors",
    "/uhp/privacyPolicy/priorversion",
    "/web/save-money-tripit",
    "/web/tripit-20th-anniversary",
)

# The language menu's own list. clone.yaml pins this build to one regional
# baseline, so a locale path is answered by saying which edition this is —
# never by serving en-US copy under a foreign locale.
_FROZEN_LOCALES: frozenset[str] = frozenset({"de", "es", "es-co", "fr", "en-uk"})


def _content_boundary(request: Request, heading: str, explanation: str) -> Response:
    """A real page at a real URL, answering 200.

    These are enumerated destinations the chrome links to, not a catch-all: an
    unrecognised path still reaches ``_not_found``. The page is what this build
    has at that address, so it answers like one — the same shape the shared
    honest-boundary pattern uses for third-party destinations.
    """

    return _render(
        request,
        "content_boundary.html",
        {"heading": heading, "explanation": explanation},
    )


def _make_alias_handler(destination: str):
    async def _handler() -> Response:
        return RedirectResponse(destination, status_code=303)

    _handler.__name__ = "alias_" + re.sub(r"[^a-z0-9]+", "_", destination.lower()).strip("_")
    return _handler


for _alias, _destination in _MARKETING_ALIASES.items():
    app.add_api_route(
        _alias,
        _make_alias_handler(_destination),
        methods=["GET"],
        include_in_schema=False,
    )


def _make_unbuilt_handler(path: str):
    async def _handler(request: Request) -> Response:
        return _content_boundary(
            request,
            "That page is not part of this build",
            "The chrome on this site links to it, but it was not among the pages "
            "built here, so there is nothing to show you.",
        )

    _handler.__name__ = "unbuilt_" + re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    return _handler


for _unbuilt in _UNBUILT_MARKETING:
    app.add_api_route(
        _unbuilt,
        _make_unbuilt_handler(_unbuilt),
        methods=["GET"],
        include_in_schema=False,
    )


@app.get("/account/edit", include_in_schema=False)
async def account_edit(request: Request, section: str = "") -> Response:
    """The Privacy Statement's "unsubscribe" link, and the account-edit path.

    ``?section=email_settings`` is the only section the captured copy names; it
    lands on the notification surface, which states what is and is not sent.
    """

    if current_traveler(request) is None:
        return _login_redirect()
    if section.strip() == "email_settings":
        return RedirectResponse("/app/settings/notifications", status_code=303)
    return RedirectResponse("/account", status_code=303)


@app.get("/web/blog/{article_path:path}", include_in_schema=False)
async def blog_article_boundary(request: Request, article_path: str) -> Response:
    """Blog index entries. The index itself is captured; the articles are not."""

    return _content_boundary(
        request,
        "That blog post is not part of this build",
        "The blog index is here in full, but the posts it links to were not "
        "captured, so there is no article to read.",
    )


@app.get("/{locale}/web", include_in_schema=False)
@app.get("/{locale}/web/{rest:path}", include_in_schema=False)
async def locale_boundary(request: Request, locale: str, rest: str = "") -> Response:
    """The language menu's destinations.

    This build is pinned to one regional baseline. Serving its pages under
    another locale's path would present US copy as if it were the German,
    Spanish, French or UK edition, so the locale is answered honestly instead.
    """

    if locale not in _FROZEN_LOCALES:
        return _not_found(request)
    return _content_boundary(
        request,
        "This edition is English (United States)",
        "The pages here were built from the English (United States) edition of "
        "TripIt. Another locale's pages would read differently — prices, legal "
        "text and availability all vary — so this build does not pretend to "
        "serve them.",
    )


# ---------------------------------------------------------------------------
# frozen page routes (GET) — registered last; distinct methods never collide
# ---------------------------------------------------------------------------


def _make_page_handler(page_name: str):
    async def _handler() -> HTMLResponse:
        return HTMLResponse(_load_page(page_name))

    _handler.__name__ = f"page_{page_name.replace('-', '_')}"
    return _handler


for _route, _name in PAGE_ROUTES.items():
    app.add_api_route(
        _route,
        _make_page_handler(_name),
        methods=["GET"],
        response_class=HTMLResponse,
        include_in_schema=False,
    )
