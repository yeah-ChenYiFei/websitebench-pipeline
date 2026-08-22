"""Craigslist offline clone — FastAPI composition root.

The clone reproduces the craigslist classifieds experience as a single
same-origin application:

* Server-rendered pages (Jinja2) for the public entry, region pages, the
  housing section and subcategories, search with price/neighborhood/date/
  category filters, listing detail, reply and flag flows, help/contact/about,
  account (login/register/password recovery), the posting wizard
  (category -> location -> details -> contact -> photos -> preview ->
  publish), posting management (edit/renew/repost/delete), favorites and
  saved searches, and the branded not-found view.
* Identity, sessions, verification codes, password recovery and the local
  mail outbox come from the vendored ``websitebench.site_backend`` runtime
  (``backend/runtime.json``); business data lives in the same bound SQLite
  file (``backend/craigslist_db.py``).
* ``GET /healthz`` returns ``{"ok":true,"site_id":"craigslist"}`` and
  ``GET /__websitebench/health`` returns ``{"status":"ok"}``; the token-gated
  ``POST /__admin/reset`` performs the deterministic reset.
* Every response carries a same-origin CSP; no remote origin is reachable.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
from pathlib import Path

from contextlib import asynccontextmanager, closing
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:  # vendored websitebench + backend imports
    sys.path.insert(0, str(ROOT))

from backend import craigslist_db as db  # noqa: E402
from websitebench.local_clone_auth import AuthConflict, AuthError, AuthRateLimited  # noqa: E402
from websitebench.site_backend import MailError  # noqa: E402

SITE_ID = "craigslist"
FRONTEND_DIR = ROOT / "frontend"
STATIC_DIR = ROOT / "static"
TEMPLATES = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))
TEMPLATES.env.filters["from_json"] = json.loads


def _db_now_ms() -> int:
    return int(db.now_datetime().timestamp() * 1000)

HEALTH_BODY = json.dumps({"ok": True, "site_id": SITE_ID}, separators=(",", ":"))
HARBOR_HEALTH_BODY = json.dumps({"status": "ok"}, separators=(",", ":"))

ADMIN_TOKEN = os.environ.get("WEBSITEBENCH_CRAIGSLIST_ADMIN_TOKEN", "craigslist-local-admin")
BUILD_ID = os.environ.get("DEPLOYMENT_BUILD_ID") or os.environ.get("WEBSITEBENCH_BUILD_ID")

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

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
HOUSING_CATEGORIES = {"apa", "sub", "roo", "wnt", "off", "prk", "rea", "vac"}
FOR_SALE_CATEGORIES = {"bia", "fua", "ela", "tia", "foa", "cta", "mca", "sna", "rva", "boo"}
KNOWN_SECTIONS = {"housing", "for-sale", "jobs", "gigs"}
CATEGORY_SLUG_RE = re.compile(r"^[a-z]{3}$")

@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Deterministic seed on every boot: the same initial data state for
    # evaluation and verification runs. Idempotent, and upgrades existing
    # databases (new categories, per-category posting minimums).
    db.services()
    db.seed()
    yield


app = FastAPI(
    title="Craigslist offline clone",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)


def _uploads_dir() -> Path:
    """Uploaded photo files live beside the site database (runtime data)."""
    data_dir = Path(os.environ.get("WEBSITEBENCH_CRAIGSLIST_UPLOADS", str(ROOT / "data" / "uploads")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir())), name="uploads")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return RedirectResponse("/static/assets/favicon.svg", status_code=301)


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


# ---------------------------------------------------------------------------
# session helpers
# ---------------------------------------------------------------------------


def _backend():
    return db.services()[0]


def _auth():
    return db.services()[1]


def _pending_registration_code(email: str) -> str:
    """Offline clone: the verification code is delivered to the local outbox
    which has no viewer, so surface it on the verify page. This is the only
    delivery channel in an offline environment and never leaves the process."""
    try:
        auth = _auth()
        with closing(db.connect()) as connection:
            row = connection.execute(
                "SELECT pending_id FROM local_auth_registration_flows"
                " WHERE email_normalized = ? AND verified_at IS NULL"
                " ORDER BY created_at DESC LIMIT 1",
                (email.strip().lower(),),
            ).fetchone()
        if row is None:
            return ""
        return auth._mail_code("registration", row["pending_id"]) or ""
    except Exception:
        return ""


def _pending_reset_code(email: str) -> str:
    """Offline clone: surface the password-reset code on the sent page."""
    try:
        auth = _auth()
        with closing(db.connect()) as connection:
            account = connection.execute(
                "SELECT account_id FROM local_auth_accounts WHERE email_normalized = ?",
                (email.strip().lower(),),
            ).fetchone()
            if account is None:
                return ""
            row = connection.execute(
                "SELECT reset_id FROM local_auth_password_reset_flows"
                " WHERE account_id = ? AND verified_at IS NULL"
                " ORDER BY created_at DESC LIMIT 1",
                (account["account_id"],),
            ).fetchone()
        if row is None:
            return ""
        return auth._mail_code("password-reset", row["reset_id"]) or ""
    except Exception:
        return ""


def _cookie_facts(request: Request) -> dict[str, Any]:
    """Session-cookie facts adjusted for the request scheme.

    The runtime config declares a Secure ``__Host-`` cookie for HTTPS
    deployments; over plain HTTP (local demo) browsers refuse to send Secure
    cookies, so the clone falls back to a non-Secure cookie with a plain
    name. Both schemes keep HttpOnly/SameSite and stay host-only."""
    facts = dict(_backend().session_cookie)
    if request.url.scheme != "https":
        facts["secure"] = False
        if facts["name"].startswith("__Host-"):
            facts["name"] = facts["name"][len("__Host-"):]
    return facts


def _session_token(request: Request) -> str | None:
    name = _cookie_facts(request)["name"]
    return request.cookies.get(name)


def _session_digest(request: Request) -> str | None:
    token = _session_token(request)
    if not token:
        return None
    try:
        return _auth().session_owner_digest(token)
    except AuthError:
        return None


def _account(request: Request) -> dict | None:
    token = _session_token(request)
    if not token:
        return None
    session = _auth().resolve_session(token)
    if not session:
        return None
    return session.get("account")


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    facts = _cookie_facts(request)
    response.set_cookie(
        key=facts["name"],
        value=token,
        httponly=facts.get("httponly", True),
        secure=facts.get("secure", True),
        samesite=facts.get("samesite", "lax"),
        path=facts.get("path", "/"),
    )


def _clear_session_cookie(request: Request, response: Response) -> None:
    facts = _cookie_facts(request)
    response.delete_cookie(facts["name"], path=facts.get("path", "/"))


# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------


def _render(request: Request, template: str, context: dict | None = None, status_code: int = 200) -> Response:
    token = _session_token(request)
    session = _auth().resolve_session(token) if token else None
    account = session.get("account") if session else None
    favorite_ids: set[int] = set()
    if account:
        favorite_ids = db.favorite_ids(account["account_id"])
    base = {
        "site_id": SITE_ID,
        "account": account,
        "favorite_ids": favorite_ids,
        "regions": db.all_regions(),
        "housing_categories": db.categories("housing"),
        "for_sale_categories": db.categories("for-sale"),
        "current_path": request.url.path,
        "query_string": request.url.query,
    }
    if context:
        base.update(context)
    return TEMPLATES.TemplateResponse(request, template, base, status_code=status_code)


def _redirect(path: str) -> Response:
    return RedirectResponse(path, status_code=303)


def _string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: object) -> int | None:
    raw = _string(value).replace("$", "").replace(",", "")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _price_label(price) -> str:
    if price is None:
        return ""
    return f"${int(price):,}"


def _detail_url(posting) -> str:
    return f"/view/d/{posting['slug']}/{_posting_code(int(posting['id']))}"


def _photo_url(filename: str) -> str:
    # wizard-uploaded photos live under /uploads; seed photos ship in static
    if filename.startswith("draft-"):
        return f"/uploads/{filename}"
    return f"/static/assets/seed-photos/{filename}"


def _posting_context(posting, photos) -> dict:
    enriched = []
    for row in photos:
        item = dict(row)
        item["url"] = _photo_url(item["filename"])
        enriched.append(item)
    housing_types = {
        "apartment", "sublet", "room", "house", "condo", "townhouse",
        "basement", "loft", "duplex", "flat", "housing swap",
        "office / commercial", "parking / storage", "real estate for sale",
        "vacation rentals",
    }
    return {
        "posting": posting,
        "photos": enriched,
        "price_label": _price_label(posting["price"]),
        "detail_url": _detail_url(posting),
        "is_housing": posting["housing_type"] in housing_types,
    }


def _not_found(request: Request | None) -> Response:
    if request is None:
        return HTMLResponse("not found", status_code=404)
    return _render(request, "not-found.html", status_code=404)


# ---------------------------------------------------------------------------
# health + admin
# ---------------------------------------------------------------------------


@app.get("/healthz", include_in_schema=False)
async def healthz() -> Response:
    return Response(content=HEALTH_BODY, media_type="application/json")


@app.get("/__websitebench/health", include_in_schema=False)
async def harbor_health() -> Response:
    return Response(content=HARBOR_HEALTH_BODY, media_type="application/json")


@app.post("/__admin/reset", include_in_schema=False)
async def admin_reset(request: Request) -> Response:
    token = request.headers.get("X-WebsiteBench-Admin-Token", "")
    if not hmac.compare_digest(token, ADMIN_TOKEN):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    db.reset()
    return JSONResponse({"reset": True, "site_id": SITE_ID})


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> Response:
    if request.url.path.startswith(("/api/", "/__websitebench/")):
        return JSONResponse({"error": "not-found"}, status_code=404)
    return _not_found(request)


# ---------------------------------------------------------------------------
# posting wizard
# ---------------------------------------------------------------------------


def _wizard_guard(request: Request) -> tuple[dict | None, Response | None]:
    account = _account(request)
    if account is None:
        return None, _render(request, "signin-prompt.html", {"next": "/post/"}, status_code=401)
    return account, None


def _require_digest(request: Request) -> str | None:
    digest = _session_digest(request)
    if digest is None:
        return None
    return digest


@app.get("/post/", include_in_schema=False)
async def post_wizard_start(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    return _render(request, "wizard-category.html", {"regions": db.all_regions()})


@app.post("/post/category", include_in_schema=False)
async def post_wizard_category(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    form = await request.form()
    category = _string(form.get("category"))
    if category not in HOUSING_CATEGORIES | FOR_SALE_CATEGORIES:
        return _render(request, "wizard-category.html", {"regions": db.all_regions(), "errors": {"category": "Please choose a category."}}, status_code=422)
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    db.save_draft(session_digest, 2, {"category_slug": category})
    return _redirect("/post/location")


@app.get("/post/location", include_in_schema=False)
async def post_wizard_location_page(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    return _render(request, "wizard-location.html", {"regions": db.all_regions()})


@app.post("/post/location", include_in_schema=False)
async def post_wizard_location(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    form = await request.form()
    region = _string(form.get("region"))
    neighborhood = _string(form.get("neighborhood"))
    errors: dict[str, str] = {}
    if db.region_by_slug(region) is None:
        errors["region"] = "Please choose a location."
    if not neighborhood:
        errors["neighborhood"] = "Please choose a neighborhood."
    if errors:
        return _render(request, "wizard-location.html", {"regions": db.all_regions(), "errors": errors, "values": dict(form)}, status_code=422)
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    region_id = db.region_by_slug(region)["id"]
    db.save_draft(session_digest, 3, {"region_id": region_id, "neighborhood": neighborhood})
    return _redirect("/post/details")


@app.get("/post/details", include_in_schema=False)
async def post_wizard_details_page(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    return _render(request, "wizard-details.html")


@app.post("/post/details", include_in_schema=False)
async def post_wizard_details(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    form = await request.form()
    title = _string(form.get("title"))
    price = _int(form.get("price"))
    description = _string(form.get("description"))
    postal = _string(form.get("postal_code"))
    housing_type = _string(form.get("housing_type"))
    bedrooms = _string(form.get("bedrooms"))
    baths = _string(form.get("baths"))
    sqft = _string(form.get("square_feet"))
    available = _string(form.get("available_date"))
    furnished = _string(form.get("furnished")) == "on"
    laundry = _string(form.get("laundry"))
    parking = _string(form.get("parking"))
    ac = _string(form.get("ac"))
    posted_by = _string(form.get("posted_by")) or "owner"
    errors: dict[str, str] = {}
    if not title:
        errors["title"] = "Please enter a title."
    elif len(title) > 120:
        errors["title"] = "Title must be 120 characters or fewer."
    if price is None or price < 0:
        errors["price"] = "Please enter a valid price (numbers only)."
    if not description:
        errors["description"] = "Please enter a description."
    if not postal:
        errors["postal_code"] = "Please enter a postal code."
    if errors:
        return _render(request, "wizard-details.html", {"errors": errors, "values": dict(form)}, status_code=422)
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    db.save_draft(
        session_digest,
        4,
        {
            "title": title,
            "price": price,
            "description": description,
            "postal_code": postal,
            "housing_type": housing_type,
            "bedrooms": bedrooms,
            "baths": baths,
            "square_feet": sqft,
            "available_date": available,
            "furnished": 1 if furnished else 0,
            "laundry": laundry,
            "parking": parking,
            "ac": ac,
            "posted_by": posted_by,
        },
    )
    return _redirect("/post/contact")


@app.get("/post/contact", include_in_schema=False)
async def post_wizard_contact_page(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    return _render(request, "wizard-contact.html")


@app.post("/post/contact", include_in_schema=False)
async def post_wizard_contact(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    form = await request.form()
    contact_method = _string(form.get("contact_method")) or "email"
    email = _string(form.get("contact_email"))
    phone = _string(form.get("contact_phone"))
    errors: dict[str, str] = {}
    if contact_method not in ("email", "phone", "both"):
        errors["contact_method"] = "Please choose a contact method."
    if contact_method in ("email", "both") and not EMAIL_RE.match(email):
        errors["contact_email"] = "Please enter a valid email address."
    if contact_method in ("phone", "both") and not phone:
        errors["contact_phone"] = "Please enter a phone number."
    if errors:
        return _render(request, "wizard-contact.html", {"errors": errors, "values": dict(form)}, status_code=422)
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    db.save_draft(
        session_digest,
        5,
        {"contact_method": contact_method, "contact_email": email, "contact_phone": phone},
    )
    return _redirect("/post/photos")


@app.get("/post/photos", include_in_schema=False)
async def post_wizard_photos_page(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    draft = db.get_draft(session_digest)
    photos = db.draft_photos(draft["id"]) if draft else []
    return _render(request, "wizard-photos.html", {"photos": photos})


@app.post("/post/photos", include_in_schema=False)
async def post_wizard_photos_upload(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    draft = db.get_draft(session_digest)
    if draft is None:
        return _redirect("/post/")
    uploads = await request.form()
    for field in ("photo1", "photo2", "photo3", "photo4", "photo5", "photo6"):
        upload = uploads.get(field)
        if upload is None:
            continue
        filename = getattr(upload, "filename", "")
        content = getattr(upload, "file", None)
        if not filename or content is None:
            continue
        safe = _safe_upload_name(filename)
        destination = _uploads_dir() / f"draft-{draft['id']}-{safe}"
        with open(destination, "wb") as handle:
            handle.write(content.read(8 * 1024 * 1024))
        db.add_draft_photo(draft["id"], destination.name)
    return _render(request, "wizard-photos.html", {"photos": db.draft_photos(draft["id"])})


@app.post("/post/photos/reorder", include_in_schema=False)
async def post_wizard_photos_reorder(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    draft = db.get_draft(session_digest)
    if draft is None:
        return _redirect("/post/")
    form = await request.form()
    order = [item for item in _string(form.get("order")).split(",") if item]
    if order:
        db.reorder_draft_photos(draft["id"], order)
    return _redirect("/post/photos")


@app.post("/post/photos/remove", include_in_schema=False)
async def post_wizard_photos_remove(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    draft = db.get_draft(session_digest)
    if draft is None:
        return _redirect("/post/")
    form = await request.form()
    filename = _string(form.get("filename"))
    if filename:
        db.remove_draft_photo(draft["id"], filename)
    return _redirect("/post/photos")


def _safe_upload_name(filename: str) -> str:
    base = Path(filename).name
    base = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return base[:80] or "photo.jpg"


@app.get("/post/preview", include_in_schema=False)
async def post_wizard_preview_page(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    draft = db.get_draft(session_digest)
    if draft is None:
        return _redirect("/post/")
    preview = _draft_preview(draft, db.draft_photos(draft["id"]))
    return _render(request, "wizard-preview.html", preview)


def _draft_preview(draft, photos) -> dict:
    region_row = None
    if draft["region_id"] is not None:
        with closing(db.connect()) as connection:
            region_row = connection.execute(
                "SELECT * FROM cl_regions WHERE id = ?", (draft["region_id"],)
            ).fetchone()
    category = next(
        (c for c in db.categories() if c["slug"] == draft["category_slug"]), None
    )
    title = draft["title"] or "Untitled posting"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120] or "posting"
    price = int(draft["price"] or 0)
    return {
        "draft": draft,
        "photos": photos,
        "preview_title": title,
        "preview_slug": slug,
        "preview_price": _price_label(price),
        "preview_region": region_row["name"] if region_row is not None else "",
        "preview_category": category["name"] if category is not None else "",
        "preview_neighborhood": draft["neighborhood"] or "",
    }


@app.post("/post/publish", include_in_schema=False)
async def post_wizard_publish(request: Request) -> Response:
    account, guard = _wizard_guard(request)
    if guard:
        return guard
    session_digest = _require_digest(request)
    if session_digest is None:
        return _redirect("/post/")
    draft = db.get_draft(session_digest)
    if draft is None:
        return _redirect("/post/")
    if not draft["title"] or draft["price"] is None:
        return _redirect("/post/details")
    photos = [row["filename"] for row in db.draft_photos(draft["id"])]
    posting_id = db.create_posting(
        account["account_id"],
        region_id=int(draft["region_id"]),
        category_slug=draft["category_slug"] or "sub",
        title=draft["title"],
        price=int(draft["price"]),
        description=draft["description"] or "",
        postal_code=draft["postal_code"] or "",
        neighborhood=draft["neighborhood"] or "",
        housing_type=draft["housing_type"] or "",
        bedrooms=draft["bedrooms"] or "",
        baths=draft["baths"] or "",
        square_feet=draft["square_feet"] or "",
        available_date=draft["available_date"] or "",
        furnished=bool(draft["furnished"]),
        laundry=draft["laundry"] or "",
        parking=draft["parking"] or "",
        ac=draft["ac"] or "",
        posted_by=draft["posted_by"] or "owner",
        contact_email=draft["contact_email"] or "",
        contact_phone=draft["contact_phone"] or "",
        contact_method=draft["contact_method"] or "email",
        photos=photos,
    )
    db.clear_draft(session_digest)
    posting = db.get_posting(posting_id)
    return _render(request, "wizard-publish.html", {"posting": posting, "detail_url": _detail_url(posting)})


# ---------------------------------------------------------------------------
# posting management
# ---------------------------------------------------------------------------
# public pages
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def home(request: Request) -> Response:
    # The public entry is the geo-default area page (toronto for this clone).
    row = db.region_by_slug("toronto")
    counts = {c["slug"]: db.category_count("toronto", c["slug"]) for c in db.categories()}
    return _render(request, "area-real.html", {"region_row": row, "counts": counts, "calendar_rows": _calendar_rows()})


@app.get("/about", include_in_schema=False)
async def about(request: Request) -> Response:
    return _render(request, "about.html")


@app.get("/about/help", include_in_schema=False)
async def help_index(request: Request) -> Response:
    return _render(request, "help.html")


@app.get("/about/help/{topic}", include_in_schema=False)
async def help_topic(request: Request, topic: str) -> Response:
    if topic in {"posting", "account", "housing"}:
        return _render(request, f"help-{topic}.html", {"topic": topic})
    if topic == "system-status":
        title, body = _ABOUT_PAGES["help/system-status"]
        return _render(request, "about-generic.html", {"title": title, "body": body})
    return _not_found(request)


@app.get("/about/terms", include_in_schema=False)
async def terms(request: Request) -> Response:
    return _render(request, "terms.html")


@app.get("/about/privacy", include_in_schema=False)
async def privacy(request: Request) -> Response:
    return _render(request, "privacy.html")


_ABOUT_PAGES = {
    "best/all": ("best-of-craigslist", "best-of-craigslist — memorable posts from the community, curated for the offline demo."),
    "best": ("best-of-craigslist", "best-of-craigslist — memorable posts from the community, curated for the offline demo."),
    "whats-new": ("what's new", "Recent changes and improvements to this offline craigslist demo."),
    "craigslist_is_hiring": ("craigslist is hiring", "Join the team building the offline craigslist experience."),
    "craigslist_app": ("craigslist app", "The craigslist offline clone runs entirely in your browser and on the local server — no app install needed."),
    "help/system-status": ("system status", "All systems operational. This offline clone runs entirely on your local machine."),
}


@app.get("/about/{page}", include_in_schema=False)
async def about_page(request: Request, page: str) -> Response:
    info = _ABOUT_PAGES.get(page)
    if info is None:
        return _not_found(request)
    title, body = info
    return _render(request, "about-generic.html", {"title": title, "body": body})


@app.get("/about/best/all", include_in_schema=False)
async def best_of_all(request: Request) -> Response:
    title, body = _ABOUT_PAGES["best/all"]
    return _render(request, "about-generic.html", {"title": title, "body": body})


# ---------------------------------------------------------------------------
# discussion forums
# ---------------------------------------------------------------------------


@app.get("/forums", include_in_schema=False)
@app.get("/forums/", include_in_schema=False)
async def forums_index(request: Request) -> Response:
    boards = db.forum_boards()
    return _render(request, "forums.html", {"boards": boards})


@app.get("/sitemap", include_in_schema=False)
@app.get("/sitemap/", include_in_schema=False)
@app.get("/sitemap/area/{region}", include_in_schema=False)
async def sitemap_page(request: Request, region: str | None = None) -> Response:
    region_row = db.region_by_slug(region) if region else None
    if region and region_row is None:
        return _not_found(request)
    return _render(request, "sitemap.html", {"region_row": region_row, "categories": db.categories()})


@app.get("/forums/{slug}", include_in_schema=False)
async def forum_board_page(request: Request, slug: str) -> Response:
    board = db.forum_board(slug)
    if board is None:
        return _not_found(request)
    posts = db.forum_posts(board["id"])
    return _render(
        request,
        "forum-board.html",
        {"board": board, "posts": posts},
    )


@app.get("/forums/{slug}/{post_id}", include_in_schema=False)
async def forum_thread_page(request: Request, slug: str, post_id: int) -> Response:
    board = db.forum_board(slug)
    if board is None:
        return _not_found(request)
    post = db.forum_post(post_id)
    if post is None or post["board_id"] != board["id"]:
        return _not_found(request)
    return _render(
        request,
        "forum-thread.html",
        {"board": board, "post": post},
    )


@app.get("/contact", include_in_schema=False)
async def contact_page(request: Request) -> Response:
    return _render(request, "contact.html")


@app.post("/contact", include_in_schema=False)
async def contact_submit(request: Request) -> Response:
    form = await request.form()
    category = _string(form.get("category"))
    _subject = _string(form.get("subject"))
    message = _string(form.get("message"))
    errors: dict[str, str] = {}
    if not category:
        errors["category"] = "Please choose a contact category."
    if not message:
        errors["message"] = "Please enter a message."
    if errors:
        return _render(request, "contact.html", {"errors": errors, "values": dict(form)}, status_code=422)
    return _render(request, "contact.html", {"sent": True})




def _calendar_rows(year: int = 2026, month: int = 6) -> list[list[dict]]:
    """Deterministic 4-row calendar grid for the frozen month (June 2026)."""
    import calendar as _calendar

    first = _calendar.weekday(year, month, 1)  # Monday=0
    days = _calendar.monthrange(year, month)[1]
    rows: list[list[dict]] = []
    cells: list[dict] = []
    for _ in range(first):
        cells.append({"label": "", "class": ""})
    for day in range(1, days + 1):
        cells.append({"label": str(day), "class": "clickable"})
    while cells:
        row, cells = cells[:7], cells[7:]
        while len(row) < 7:
            row.append({"label": "", "class": ""})
        rows.append(row)
    return rows



def _listing_extra(posting) -> dict:
    """Derived listing context: category name, attribute chips, posted-ago label."""
    category = next(
        (c for c in db.categories() if c["slug"] == posting["category_slug"]), None
    )
    chips: list[str] = []
    if posting["housing_type"]:
        chips.append(posting["housing_type"])
    if posting["furnished"]:
        chips.append("furnished")
    if posting["laundry"]:
        chips.append(posting["laundry"])
    if posting["parking"]:
        chips.append(posting["parking"])
    if posting["baths"]:
        chips.append(f"{posting['baths']} bath")
    posted_ago = "about 8 hours ago"
    try:
        from datetime import datetime

        posted = datetime.fromisoformat(posting["created_at"])
        now = datetime.fromisoformat(db.now_utc())
        hours = max(0, int((now - posted).total_seconds() // 3600))
        if hours < 24:
            posted_ago = f"about {max(1, hours)} hour{'s' if hours != 1 else ''} ago"
        else:
            posted_ago = f"about {hours // 24} day{'s' if hours // 24 != 1 else ''} ago"
    except ValueError:
        pass
    return {
        "category_name": category["name"] if category is not None else posting["category_slug"],
        "attribute_chips": chips,
        "posted_ago": posted_ago,
    }

# ---------------------------------------------------------------------------
# current craigslist URL model: /area/{region}, /search/area/{region}, /view/d/{slug}/{code}
# ---------------------------------------------------------------------------

# deterministic opaque posting code (base62 of the numeric id)
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _posting_code(posting_id: int) -> str:
    value = posting_id
    chars: list[str] = []
    while value:
        value, remainder = divmod(value, 62)
        chars.append(_ALPHABET[remainder])
    return "".join(reversed(chars)) or "0"


def _posting_id_from_code(code: str) -> int | None:
    value = 0
    for char in code:
        index = _ALPHABET.find(char)
        if index < 0:
            return None
        value = value * 62 + index
    return value


@app.get("/area/{region}", include_in_schema=False)
async def area_page(request: Request, region: str) -> Response:
    row = db.region_row_for_slug(region)
    if row is None:
        return _not_found(request)
    counts = {c["slug"]: db.category_count(region, c["slug"]) for c in db.categories()}
    return _render(request, "area-real.html", {"region_row": row, "counts": counts, "calendar_rows": _calendar_rows()})


@app.get("/search/area/{region}", include_in_schema=False)
async def area_search(request: Request, region: str) -> Response:
    if db.region_row_for_slug(region) is None:
        return _not_found(request)
    params = _search_params(request)
    category = params["category"] or None
    housing_only = category == "hhh"
    section = db.SECTION_HUB_CODES.get(category or "")
    postings = db.search_postings(
        region,
        category=category,
        query=params["query"],
        min_price=params["min_price"],
        max_price=params["max_price"],
        postal=params["postal"],
        posted_today=params["posted_today"],
        bedrooms=params["bedrooms"],
        housing_type=params["housing_type"],
        posted_by=params["posted_by"],
        has_image=params["has_image"],
        sort=params["sort"],
        housing_only=housing_only,
    )
    rows = [_posting_context(p, db.posting_photos(p["id"])) for p in postings]
    counts = {c["slug"]: db.category_count(region, c["slug"]) for c in db.categories()}
    neighborhood = db.neighborhood_label(params["postal"]) if params["postal"] else None
    return _render(
        request,
        "search.html",
        {
            "region_row": db.region_by_slug(region),
            "section": section or "housing",
            "category": category,
            "category_row": next((c for c in db.categories() if c["slug"] == category), None),
            "params": params,
            "rows": rows,
            "counts": counts,
            "neighborhood": neighborhood,
            "no_results": not rows,
            "now_label": db.now_utc()[:16].replace("T", " "),
        },
    )


@app.get("/view/d/{slug}/{code}", include_in_schema=False)
async def view_detail(request: Request, slug: str, code: str) -> Response:
    posting_id = _posting_id_from_code(code)
    if posting_id is None:
        return _not_found(request)
    posting = db.get_posting(posting_id)
    if posting is None:
        return _not_found(request)
    if posting["status"] == "removed":
        return _render(request, "removed.html", status_code=410)
    photos = db.posting_photos(posting_id)
    context = _posting_context(posting, photos)
    account = _account(request)
    is_favorite = bool(account and posting_id in db.favorite_ids(account["account_id"]))
    context.update(_listing_extra(posting))
    context.update(
        {
            "region_row": db.region_by_slug(posting["region_slug"]),
            "furnished_label": "yes" if posting["furnished"] else "no",
            "available_label": posting["available_date"] or "n/a",
            "is_favorite": is_favorite,
        }
    )
    return _render(request, "listing.html", context)


@app.get("/{region}/{section}/{cat}/d/{posting_id}/{slug}", include_in_schema=False)
@app.get("/{region}/{section}/d/{posting_id}/{slug}", include_in_schema=False)
async def legacy_detail_redirect(
    request: Request, region: str, section: str, posting_id: int, slug: str, cat: str | None = None
) -> Response:
    posting = db.get_posting(posting_id)
    if posting is None:
        return _not_found(request)
    return RedirectResponse(f"/view/d/{posting['slug']}/{_posting_code(posting_id)}", status_code=301)


@app.get("/{region}/housing/{cat}/", include_in_schema=False)
async def legacy_category_redirect(request: Request, region: str, cat: str) -> Response:
    if db.region_by_slug(region) is None or not CATEGORY_SLUG_RE.match(cat):
        return _not_found(request)
    return RedirectResponse(f"/search/area/{region}?cat={cat}", status_code=301)


@app.get("/{region}/housing/", include_in_schema=False)
async def legacy_housing_redirect(request: Request, region: str) -> Response:
    if db.region_by_slug(region) is None:
        return _not_found(request)
    return RedirectResponse(f"/search/area/{region}?cat=hhh", status_code=301)


@app.get("/{region}/", include_in_schema=False)
async def legacy_region_redirect(request: Request, region: str) -> Response:
    if db.region_by_slug(region) is None:
        return _not_found(request)
    return RedirectResponse(f"/area/{region}", status_code=301)


# ---------------------------------------------------------------------------
# region + section pages
# ---------------------------------------------------------------------------


@app.get("/{region}/", include_in_schema=False)
async def region_page(request: Request, region: str) -> Response:
    row = db.region_by_slug(region)
    if row is None:
        return _not_found(request)
    counts = {c["slug"]: db.category_count(region, c["slug"]) for c in db.categories()}
    return _render(request, "region.html", {"region_row": row, "counts": counts})


@app.get("/{region}/housing/", include_in_schema=False)
async def housing_section(request: Request, region: str) -> Response:
    row = db.region_by_slug(region)
    if row is None:
        return _not_found(request)
    counts = {c["slug"]: db.category_count(region, c["slug"]) for c in db.categories("housing")}
    return _render(request, "housing.html", {"region_row": row, "counts": counts})


@app.get("/{region}/housing/{cat}/", include_in_schema=False)
async def category_listing(request: Request, region: str, cat: str) -> Response:
    if db.region_by_slug(region) is None or not CATEGORY_SLUG_RE.match(cat):
        return _not_found(request)
    category = next((c for c in db.categories("housing") if c["slug"] == cat), None)
    if category is None:
        return _not_found(request)
    postings = db.section_postings(region, cat)
    rows = [_posting_context(p, db.posting_photos(p["id"])) for p in postings]
    counts = {c["slug"]: db.category_count(region, c["slug"]) for c in db.categories("housing")}
    return _render(
        request,
        "category.html",
        {"region_row": db.region_by_slug(region), "category": category, "counts": counts, "rows": rows},
    )


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def _search_params(request: Request) -> dict:
    q = request.query_params
    return {
        "query": _string(q.get("query")),
        "min_price": _int(q.get("min_price")),
        "max_price": _int(q.get("max_price")),
        "postal": _string(q.get("postal")),
        "posted_today": q.get("postedToday") in ("1", "true", "on"),
        "bedrooms": _string(q.get("bedrooms")),
        "housing_type": _string(q.get("housingType")),
        "posted_by": _string(q.get("posted_by")),
        "has_image": q.get("hasImage") in ("1", "true", "on"),
        "sort": _string(q.get("sort")) or "newest",
        "view": _string(q.get("view")) or "list",
        # the live site uses ?cat= ; also accept ?category= for compatibility
        "category": _string(q.get("cat")) or _string(q.get("category")),
    }


@app.get("/{region}/search/{section}", include_in_schema=False)
@app.get("/{region}/search/{section}/{cat}", include_in_schema=False)
async def search_page(request: Request, region: str, section: str, cat: str | None = None) -> Response:
    if db.region_by_slug(region) is None or section not in KNOWN_SECTIONS:
        return _not_found(request)
    if cat is not None and not CATEGORY_SLUG_RE.match(cat):
        return _not_found(request)
    params = _search_params(request)
    category = cat or params["category"] or None
    housing_only = category == "hhh"
    if category == "hhh":
        category = None  # housing hub: all housing categories
    postings = db.search_postings(
        region,
        category=category,
        query=params["query"],
        min_price=params["min_price"],
        max_price=params["max_price"],
        postal=params["postal"],
        posted_today=params["posted_today"],
        bedrooms=params["bedrooms"],
        housing_type=params["housing_type"],
        posted_by=params["posted_by"],
        has_image=params["has_image"],
        sort=params["sort"],
        housing_only=housing_only,
    )
    rows = [_posting_context(p, db.posting_photos(p["id"])) for p in postings]
    counts = {c["slug"]: db.category_count(region, c["slug"]) for c in db.categories()}
    neighborhood = db.neighborhood_label(params["postal"]) if params["postal"] else None
    return _render(
        request,
        "search.html",
        {
            "region_row": db.region_by_slug(region),
            "section": section,
            "category": category,
            "params": params,
            "rows": rows,
            "counts": counts,
            "neighborhood": neighborhood,
            "no_results": not rows,
            "now_label": db.now_utc()[:16].replace("T", " "),
        },
    )


@app.post("/{region}/search/{section}/save", include_in_schema=False)
async def save_search(request: Request, region: str, section: str) -> Response:
    account = _account(request)
    if account is None:
        return _render(request, "signin-prompt.html", {"next": request.url.path}, status_code=401)
    form = await request.form()
    name = _string(form.get("name")) or "housing search"
    params = _search_params(request)
    query = {k: v for k, v in params.items() if v not in ("", None)}
    query["section"] = section
    query["region"] = region
    db.add_saved_search(account["account_id"], name, query)
    return _redirect("/account/searches")


# ---------------------------------------------------------------------------
# listing detail
# ---------------------------------------------------------------------------


@app.get("/{region}/{section}/{cat}/d/{posting_id}/{slug}", include_in_schema=False)
@app.get("/{region}/{section}/d/{posting_id}/{slug}", include_in_schema=False)
async def listing_detail(
    request: Request, region: str, section: str, posting_id: int, slug: str, cat: str | None = None
) -> Response:
    posting = db.get_posting(posting_id)
    if posting is None:
        return _not_found(request)
    if posting["status"] == "removed":
        return _render(request, "removed.html", status_code=410)
    photos = db.posting_photos(posting_id)
    context = _posting_context(posting, photos)
    account = _account(request)
    is_favorite = bool(account and posting_id in db.favorite_ids(account["account_id"]))
    context.update(_listing_extra(posting))
    context.update(
        {
            "region_row": db.region_by_slug(posting["region_slug"]),
            "furnished_label": "yes" if posting["furnished"] else "no",
            "available_label": posting["available_date"] or "n/a",
            "is_favorite": is_favorite,
        }
    )
    return _render(request, "listing.html", context)


@app.get("/{region}/housing/reply/{posting_id}", include_in_schema=False)
async def reply_page(request: Request, region: str, posting_id: int) -> Response:
    posting = db.get_posting(posting_id)
    if posting is None or posting["status"] == "removed":
        return _not_found(request)
    return _render(request, "reply.html", {"posting": posting, "region_row": db.region_by_slug(region)})


@app.post("/{region}/housing/reply/{posting_id}", include_in_schema=False)
async def reply_submit(request: Request, region: str, posting_id: int) -> Response:
    posting = db.get_posting(posting_id)
    if posting is None or posting["status"] == "removed":
        return _not_found(request)
    form = await request.form()
    name = _string(form.get("name"))
    email = _string(form.get("email"))
    phone = _string(form.get("phone"))
    message = _string(form.get("message"))
    errors: dict[str, str] = {}
    if not name:
        errors["name"] = "Please enter your name."
    if not email:
        errors["email"] = "Please enter your email address."
    elif not EMAIL_RE.match(email):
        errors["email"] = "Please enter a valid email address."
    if not message:
        errors["message"] = "Please enter a message."
    if errors:
        return _render(request, "reply.html", {"posting": posting, "region_row": db.region_by_slug(region), "errors": errors, "values": dict(form)}, status_code=422)
    mail_id = None
    recipient = posting["contact_email"] or ""
    try:
        mail = _backend().mail.enqueue(
            purpose="posting-reply",
            recipient=recipient,
            variables={
                "posting_title": posting["title"],
                "posting_id": str(posting["id"]),
                "sender_name": name,
                "sender_email": email,
            },
            idempotency_key=f"reply-{posting_id}-{name[:40]}-{int(_db_now_ms())}",
            simulation=True,
        )
        if isinstance(mail, dict):
            mail_id = mail.get("mail_id")
    except (MailError, ValueError):
        mail_id = None
    db.add_reply(posting_id, name=name, email=email, phone=phone, message=message, mail_id=mail_id, recipient=recipient)
    return _render(request, "reply.html", {"posting": posting, "region_row": db.region_by_slug(region), "sent": True})


@app.post("/{region}/housing/favorite/{posting_id}", include_in_schema=False)
async def favorite_toggle(request: Request, region: str, posting_id: int) -> Response:
    account = _account(request)
    if account is None:
        return _render(request, "signin-prompt.html", {"next": f"/{region}/housing/favorite/{posting_id}"}, status_code=401)
    posting = db.get_posting(posting_id)
    if posting is None:
        return _not_found(request)
    if db.is_favorite(account["account_id"], posting_id):
        db.remove_favorite(account["account_id"], posting_id)
    else:
        db.add_favorite(account["account_id"], posting_id)
    # return to the canonical detail page (the legacy /{region}/... fallback
    # 404s because the clone's URL model is /view/d/{slug}/{code})
    return _redirect(_detail_url(posting))


# ---------------------------------------------------------------------------
# flag
# ---------------------------------------------------------------------------


@app.get("/flag/{posting_id}", include_in_schema=False)
async def flag_page(request: Request, posting_id: int) -> Response:
    posting = db.get_posting(posting_id)
    if posting is None:
        return _not_found(request)
    return _render(request, "flag.html", {"posting": posting})


@app.post("/flag/{posting_id}", include_in_schema=False)
async def flag_submit(request: Request, posting_id: int) -> Response:
    posting = db.get_posting(posting_id)
    if posting is None:
        return _not_found(request)
    form = await request.form()
    reason = _string(form.get("reason"))
    note = _string(form.get("note"))
    errors: dict[str, str] = {}
    if not reason:
        errors["reason"] = "Please choose a reason."
    if errors:
        return _render(request, "flag.html", {"posting": posting, "errors": errors}, status_code=422)
    db.add_flag(posting_id, reason, note)
    return _render(request, "flag.html", {"posting": posting, "sent": True})
# ---------------------------------------------------------------------------
# account
# ---------------------------------------------------------------------------


@app.get("/account/login", include_in_schema=False)
async def login_page(request: Request) -> Response:
    return _render(request, "login.html")


@app.post("/account/login", include_in_schema=False)
async def login_submit(request: Request) -> Response:
    form = await request.form()
    email = _string(form.get("email"))
    password = _string(form.get("password"))
    errors: dict[str, str] = {}
    if not email:
        errors["email"] = "This field is required."
    if not password:
        errors["password"] = "This field is required."
    if errors:
        return _render(request, "login.html", {"errors": errors, "values": dict(form)}, status_code=422)
    token = _session_token(request)
    if not token:
        token = _auth().create_anonymous_session()
    try:
        result = _auth().sign_in(token, email=email, password=password)
    except AuthError:
        errors["password"] = "The email address and password you entered don't match."
        return _render(request, "login.html", {"errors": errors, "values": dict(form)}, status_code=401)
    response = _redirect("/account/home")
    _set_session_cookie(request, response, result["session_token"])
    return response


@app.get("/account/register", include_in_schema=False)
async def register_page(request: Request) -> Response:
    return _render(request, "register.html")


@app.post("/account/register", include_in_schema=False)
async def register_submit(request: Request) -> Response:
    form = await request.form()
    email = _string(form.get("email"))
    password = _string(form.get("password"))
    confirm = _string(form.get("confirm_password"))
    agree = _string(form.get("agree_terms"))
    errors: dict[str, str] = {}
    if not email:
        errors["email"] = "This field is required."
    elif not EMAIL_RE.match(email):
        errors["email"] = "Please enter a valid email address."
    if not password:
        errors["password"] = "This field is required."
    elif len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    if confirm != password:
        errors["confirm_password"] = "Passwords do not match."
    if agree != "on":
        errors["agree_terms"] = "You must agree to the terms of use."
    if errors:
        return _render(request, "register.html", {"errors": errors, "values": dict(form)}, status_code=422)
    rate_message = db.registration_event_check(email)
    if rate_message:
        errors["email"] = rate_message
        return _render(request, "register.html", {"errors": errors, "values": dict(form)}, status_code=429)
    db.record_registration_event(email)
    token = _session_token(request)
    if not token:
        token = _auth().create_anonymous_session()
    try:
        _auth().start_registration(
            token,
            email=email,
            display_name=email.split("@")[0],
            password=password,
        )
    except AuthConflict:
        errors["email"] = "An account with this email address already exists."
        return _render(request, "register.html", {"errors": errors, "values": dict(form)}, status_code=409)
    except AuthRateLimited:
        errors["email"] = "Too many registration attempts. Please try again later."
        return _render(request, "register.html", {"errors": errors, "values": dict(form)}, status_code=429)
    except AuthError as exc:
        errors["email"] = str(exc)
        return _render(request, "register.html", {"errors": errors, "values": dict(form)}, status_code=422)
    response = _render(request, "register-verify.html", {"email": email, "debug_code": _pending_registration_code(email)})
    _set_session_cookie(request, response, token)
    return response


@app.post("/account/register/verify", include_in_schema=False)
async def register_verify(request: Request) -> Response:
    token = _session_token(request)
    if not token:
        return _redirect("/account/register")
    form = await request.form()
    code = _string(form.get("code"))
    errors: dict[str, str] = {}
    if not code:
        errors["code"] = "Please enter the verification code."
        return _render(request, "register-verify.html", {"errors": errors}, status_code=422)
    try:
        _auth().verify_registration_code(token, code)
        result = _auth().complete_registration(token)
    except AuthError as exc:
        errors["code"] = str(exc)
        return _render(request, "register-verify.html", {"errors": errors}, status_code=422)
    response = _redirect("/account/home")
    _set_session_cookie(request, response, result["session_token"])
    return response


@app.get("/account/forgot", include_in_schema=False)
async def forgot_page(request: Request) -> Response:
    return _render(request, "forgot.html")


@app.post("/account/forgot", include_in_schema=False)
async def forgot_submit(request: Request) -> Response:
    form = await request.form()
    email = _string(form.get("email"))
    errors: dict[str, str] = {}
    if not email:
        errors["email"] = "Please enter the email address for your account."
        return _render(request, "forgot.html", {"errors": errors, "values": dict(form)}, status_code=422)
    elif not EMAIL_RE.match(email):
        errors["email"] = "Please enter a valid email address."
        return _render(request, "forgot.html", {"errors": errors, "values": dict(form)}, status_code=422)
    token = _session_token(request)
    if not token:
        token = _auth().create_anonymous_session()
    try:
        _auth().start_password_reset(token, email=email)
    except AuthError:
        pass  # neutral sent state; never reveal whether the email exists
    response = _render(request, "forgot.html", {"sent": True, "email": email, "debug_code": _pending_reset_code(email)})
    _set_session_cookie(request, response, token)
    return response


@app.get("/account/reset", include_in_schema=False)
async def reset_code_page(request: Request) -> Response:
    return _render(request, "reset.html")


@app.post("/account/reset", include_in_schema=False)
async def reset_code_submit(request: Request) -> Response:
    token = _session_token(request)
    if not token:
        return _redirect("/account/forgot")
    form = await request.form()
    code = _string(form.get("code"))
    password = _string(form.get("password"))
    confirm = _string(form.get("confirm_password"))
    errors: dict[str, str] = {}
    if not code:
        errors["code"] = "Please enter the reset code."
    if not password:
        errors["password"] = "This field is required."
    elif len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    if confirm != password:
        errors["confirm_password"] = "Passwords do not match."
    if errors:
        return _render(request, "reset.html", {"errors": errors}, status_code=422)
    try:
        _auth().verify_password_reset_code(token, code)
        new_token = _auth().complete_password_reset(token, new_password=password)
    except AuthError as exc:
        errors["code"] = str(exc)
        return _render(request, "reset.html", {"errors": errors}, status_code=422)
    response = _redirect("/account/home")
    _set_session_cookie(request, response, new_token)
    return response


@app.get("/account/home", include_in_schema=False)
async def account_home(request: Request) -> Response:
    account = _account(request)
    if account is None:
        return _render(request, "signin-prompt.html", {"next": "/account/home"}, status_code=401)
    postings = db.postings_for_account(account["account_id"])
    rows = [_posting_context(p, db.posting_photos(p["id"])) for p in postings]
    return _render(request, "account-home.html", {"rows": rows, "email": account["email_normalized"]})


@app.get("/account/saved", include_in_schema=False)
async def account_saved(request: Request) -> Response:
    account = _account(request)
    if account is None:
        return _render(request, "signin-prompt.html", {"next": "/account/saved"}, status_code=401)
    rows = [_posting_context(p, db.posting_photos(p["id"])) for p in db.favorite_postings(account["account_id"])]
    return _render(request, "account-saved.html", {"rows": rows})


@app.get("/account/searches", include_in_schema=False)
async def account_searches(request: Request) -> Response:
    account = _account(request)
    if account is None:
        return _render(request, "signin-prompt.html", {"next": "/account/searches"}, status_code=401)
    searches = db.saved_searches(account["account_id"])
    return _render(request, "account-searches.html", {"searches": searches})


@app.post("/account/searches/{search_id}/delete", include_in_schema=False)
async def account_search_delete(request: Request, search_id: int) -> Response:
    account = _account(request)
    if account is None:
        return _render(request, "signin-prompt.html", {"next": "/account/searches"}, status_code=401)
    db.remove_saved_search(account["account_id"], search_id)
    return _redirect("/account/searches")


@app.get("/account/settings", include_in_schema=False)
async def account_settings(request: Request) -> Response:
    account = _account(request)
    if account is None:
        return _render(request, "signin-prompt.html", {"next": "/account/settings"}, status_code=401)
    return _render(request, "account-settings.html", {"email": account["email_normalized"]})


@app.post("/account/logout", include_in_schema=False)
async def logout(request: Request) -> Response:
    token = _session_token(request)
    if token:
        try:
            _auth().sign_out(token)
        except AuthError:
            pass
    response = _redirect("/")
    _clear_session_cookie(request, response)
    return response



# ---------------------------------------------------------------------------


def _owner_or_prompt(request: Request, posting_id: int):
    account = _account(request)
    if account is None:
        return None, _render(request, "signin-prompt.html", {"next": request.url.path}, status_code=401)
    posting = db.get_posting(posting_id)
    if posting is None:
        return None, _not_found(request)
    if posting["account_id"] != account["account_id"]:
        return None, _render(request, "permission-denied.html", {"posting": posting}, status_code=403)
    return account, None


@app.get("/post/edit/{posting_id}", include_in_schema=False)
async def post_edit_page(request: Request, posting_id: int) -> Response:
    account, guard = _owner_or_prompt(request, posting_id)
    if guard:
        return guard
    posting = db.get_posting(posting_id)
    return _render(request, "edit.html", {"posting": posting, "values": dict(posting)})


@app.post("/post/edit/{posting_id}", include_in_schema=False)
async def post_edit_submit(request: Request, posting_id: int) -> Response:
    account, guard = _owner_or_prompt(request, posting_id)
    if guard:
        return guard
    form = await request.form()
    title = _string(form.get("title"))
    price = _int(form.get("price"))
    description = _string(form.get("description"))
    postal = _string(form.get("postal_code"))
    errors: dict[str, str] = {}
    if not title:
        errors["title"] = "Please enter a title."
    if price is None or price < 0:
        errors["price"] = "Please enter a valid price."
    if not description:
        errors["description"] = "Please enter a description."
    if errors:
        posting = db.get_posting(posting_id)
        return _render(request, "edit.html", {"posting": posting, "errors": errors, "values": dict(form)}, status_code=422)
    db.update_posting(
        posting_id,
        title=title,
        price=price,
        description=description,
        postal_code=postal,
        neighborhood=_string(form.get("neighborhood")),
        housing_type=_string(form.get("housing_type")),
        bedrooms=_string(form.get("bedrooms")),
        baths=_string(form.get("baths")),
        square_feet=_string(form.get("square_feet")),
        available_date=_string(form.get("available_date")),
        furnished=_string(form.get("furnished")) == "on",
        laundry=_string(form.get("laundry")),
        parking=_string(form.get("parking")),
        ac=_string(form.get("ac")),
        posted_by=_string(form.get("posted_by")) or "owner",
        contact_email=_string(form.get("contact_email")),
        contact_phone=_string(form.get("contact_phone")),
        contact_method=_string(form.get("contact_method")) or "email",
    )
    return _redirect(_detail_url(db.get_posting(posting_id)))


@app.post("/post/renew/{posting_id}", include_in_schema=False)
async def post_renew(request: Request, posting_id: int) -> Response:
    account, guard = _owner_or_prompt(request, posting_id)
    if guard:
        return guard
    db.renew_posting(posting_id)
    return _redirect("/account/home")


@app.post("/post/repost/{posting_id}", include_in_schema=False)
async def post_repost(request: Request, posting_id: int) -> Response:
    account, guard = _owner_or_prompt(request, posting_id)
    if guard:
        return guard
    posting = db.get_posting(posting_id)
    new_id = db.repost_posting(
        posting_id,
        region_id=int(posting["region_id"]),
        category_slug=posting["category_slug"],
        account_id=account["account_id"],
    )
    return _redirect(f"/account/home?reposted={new_id}")


@app.get("/post/delete/{posting_id}", include_in_schema=False)
async def post_delete_confirm(request: Request, posting_id: int) -> Response:
    account, guard = _owner_or_prompt(request, posting_id)
    if guard:
        return guard
    posting = db.get_posting(posting_id)
    return _render(request, "delete.html", {"posting": posting})


@app.post("/post/delete/{posting_id}", include_in_schema=False)
async def post_delete_submit(request: Request, posting_id: int) -> Response:
    account, guard = _owner_or_prompt(request, posting_id)
    if guard:
        return guard
    db.remove_posting(posting_id)
    return _redirect("/account/home")


@app.get("/__admin/mail/query", include_in_schema=False)
async def admin_mail_query(request: Request) -> Response:
    """Admin mail outbox query: returns locally queued mail (registration /
    password-reset / posting-reply) with any verification codes, so the
    benchmark runner can read codes the way a real inbox would."""
    token = request.headers.get("X-WebsiteBench-Admin-Token", "")
    if not hmac.compare_digest(token, ADMIN_TOKEN):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    purpose = _string(request.query_params.get("purpose") or "")
    mails: list[dict[str, Any]] = []
    with closing(db.connect()) as connection:
        # business mail jobs (posting-reply)
        rows = connection.execute(
            "SELECT mail_id, purpose, template_id, recipient, status, variables_json, created_at"
            " FROM websitebench_mail_jobs"
        ).fetchall()
        for row in rows:
            if purpose and row["purpose"] != purpose:
                continue
            item = dict(row)
            try:
                item["variables"] = json.loads(row["variables_json"] or "{}")
            except Exception:
                item["variables"] = {}
            mails.append(item)
        # auth outbox mail (registration / password-reset) with codes
        for table, id_col, purpose_name, email_col in (
            ("local_auth_mail_outbox", "mail_id", None, "recipient"),
        ):
            cols = [c[1] for c in connection.execute(f"PRAGMA table_info({table})").fetchall()]
            if not cols:
                continue
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                item = dict(zip(cols, row))
                if purpose and item.get("purpose") != purpose:
                    continue
                flow_id = item.get("flow_id") or ""
                code = _auth()._mail_code(item.get("purpose", ""), flow_id) or ""
                item["verification_code"] = code
                mails.append(item)
    return JSONResponse({"mails": mails, "count": len(mails)})
