"""Fenty Beauty source-grounded, zero-remote-runtime offline clone."""

from __future__ import annotations

import hmac
import html
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

from backend import store
from websitebench.local_clone_auth import AuthError


SITE_ID = "fenty-beauty"
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
INDEX = ROOT / "frontend" / "index.html"
ADMIN_TOKEN = os.environ.get("WEBSITEBENCH_FENTY_ADMIN_TOKEN", "fenty-local-reset-token")
KNOWN_PATHS = {
    "/", "/en-ca", "/en-ca/", "/en-ca/collections/makeup-shop-all",
    "/en-ca/search", "/en-ca/cart", "/en-ca/checkout",
    "/en-ca/account/login", "/en-ca/account/register", "/en-ca/account/recover",
    "/en-ca/account", "/en-ca/account/favorites", "/en-ca/account/addresses",
    "/en-ca/account/orders", "/en-ca/pages/help-center", "/en-ca/pages/contact-us",
}

app = FastAPI(title="Fenty Beauty offline clone", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _cookies(request: Request) -> tuple[str, str, dict[str, Any]]:
    actor = request.cookies.get("wb_fenty_actor") or store.new_actor()
    token, session = store.ensure_auth_session(request.cookies.get("wb_fenty_auth"))
    return actor, token, session


def _attach(response: Response, request: Request, actor: str, token: str) -> Response:
    secure = request.url.scheme == "https"
    response.set_cookie("wb_fenty_actor", actor, httponly=True, samesite="lax", secure=secure, max_age=2592000)
    response.set_cookie("wb_fenty_auth", token, httponly=True, samesite="lax", secure=secure, max_age=2592000)
    return response


def _json(payload: Any, request: Request, actor: str, token: str, status: int = 200) -> JSONResponse:
    return _attach(JSONResponse(payload, status_code=status), request, actor, token)


async def _body(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _account_or_error(token: str) -> dict[str, Any]:
    account = store.resolve_account(token)
    if not account or not account.get("account"):
        raise PermissionError("Sign in to continue.")
    return account["account"]


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, Any]:
    return {"ok": True, "site_id": SITE_ID}


@app.post("/__admin/reset", include_in_schema=False)
async def admin_reset(request: Request) -> JSONResponse:
    if not hmac.compare_digest(request.headers.get("X-WebsiteBench-Admin-Token", ""), ADMIN_TOKEN):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    store.reset()
    return JSONResponse({"reset": True, "site_id": SITE_ID})


@app.get("/api/bootstrap", include_in_schema=False)
async def bootstrap(request: Request) -> JSONResponse:
    actor, token, session = _cookies(request)
    account = session.get("account")
    payload = {
        "catalog": store.catalog(),
        "cart": store.cart(actor, include_removed=True),
        "account": account,
        "account_data": store.account_data(account["subject_id"]) if account else None,
        "locale": "en-CA",
        "currency": "CAD",
    }
    return _json(payload, request, actor, token)


@app.get("/api/catalog", include_in_schema=False)
async def catalog(request: Request, q: str = "", category: str = "", sort: str = "featured") -> JSONResponse:
    actor, token, _ = _cookies(request)
    return _json({"products": store.catalog(q, category, sort), "query": q, "category": category, "sort": sort}, request, actor, token)


@app.get("/api/products/{slug}", include_in_schema=False)
async def product(slug: str, request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    item = store.PRODUCT_BY_SLUG.get(slug)
    if item is None:
        return _json({"error": "not-found"}, request, actor, token, 404)
    return _json({"product": store.public_product(item)}, request, actor, token)


@app.get("/api/cart", include_in_schema=False)
async def get_cart(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    return _json(store.cart(actor, include_removed=True), request, actor, token)


@app.post("/api/cart/add", include_in_schema=False)
async def add_cart(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    body = await _body(request)
    try:
        value = store.add_cart(actor, str(body.get("product_id", "")), str(body.get("variant", "")), str(body.get("size", "")), int(body.get("quantity", 1)))
    except (ValueError, TypeError) as exc:
        return _json({"error": str(exc)}, request, actor, token, 422)
    return _json(value, request, actor, token, 201)


@app.post("/api/cart/update", include_in_schema=False)
async def update_cart(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    body = await _body(request)
    try:
        value = store.update_cart(actor, str(body.get("product_id", "")), str(body.get("variant", "")), str(body.get("size", "")), body.get("quantity"), body.get("removed"))
    except (ValueError, TypeError) as exc:
        return _json({"error": str(exc)}, request, actor, token, 422)
    return _json(value, request, actor, token)


@app.post("/api/auth/register", include_in_schema=False)
async def register(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    body = await _body(request)
    try:
        store.register(str(body.get("email", "")), str(body.get("display_name", "")), str(body.get("password", "")))
        signed = store.sign_in(token, str(body.get("email", "")), str(body.get("password", "")))
    except (AuthError, ValueError) as exc:
        return _json({"error": str(exc)}, request, actor, token, 422)
    return _json({"account": signed["account"], "verification": "Local demo account verified without external email."}, request, actor, signed["session_token"], 201)


@app.post("/api/auth/login", include_in_schema=False)
async def login(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    body = await _body(request)
    try:
        signed = store.sign_in(token, str(body.get("email", "")), str(body.get("password", "")))
    except AuthError:
        return _json({"error": "Email or password is incorrect."}, request, actor, token, 401)
    return _json({"account": signed["account"], "account_data": store.account_data(signed["account"]["subject_id"])}, request, actor, signed["session_token"])


@app.post("/api/auth/logout", include_in_schema=False)
async def logout(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    store.sign_out(token)
    new_token, _ = store.ensure_auth_session(None)
    return _json({"signed_out": True}, request, actor, new_token)


@app.post("/api/auth/recovery-preview", include_in_schema=False)
async def recovery_preview(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    body = await _body(request)
    email = str(body.get("email", "")).strip()
    if not email or "@" not in email:
        return _json({"error": "Enter a valid email address."}, request, actor, token, 422)
    return _json({"sent": False, "message": "No message was sent. In the offline clone, recovery uses a local verification code only after explicit confirmation.", "return_path": "/en-ca/account/login"}, request, actor, token)


@app.get("/api/account", include_in_schema=False)
async def account(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    try:
        current = _account_or_error(token)
    except PermissionError as exc:
        return _json({"error": str(exc)}, request, actor, token, 401)
    return _json(store.account_data(current["subject_id"]), request, actor, token)


@app.post("/api/favorites/toggle", include_in_schema=False)
async def favorite(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    try:
        current = _account_or_error(token)
    except PermissionError as exc:
        return _json({"error": str(exc), "signin": "/en-ca/account/login"}, request, actor, token, 401)
    body = await _body(request)
    try:
        active, rows = store.toggle_favorite(current["subject_id"], str(body.get("product_id", "")))
    except ValueError as exc:
        return _json({"error": str(exc)}, request, actor, token, 422)
    return _json({"saved": active, "favorites": rows}, request, actor, token)


@app.post("/api/account/address", include_in_schema=False)
async def address(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    try:
        current = _account_or_error(token)
        value = store.save_address(current["subject_id"], await _body(request))
    except PermissionError as exc:
        return _json({"error": str(exc)}, request, actor, token, 401)
    except ValueError as exc:
        return _json({"error": str(exc)}, request, actor, token, 422)
    return _json(value, request, actor, token)


@app.post("/api/orders/{order_id}/{action}", include_in_schema=False)
async def order_action(order_id: str, action: str, request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    try:
        current = _account_or_error(token)
        value = store.order_action(current["subject_id"], order_id, action, actor)
    except PermissionError as exc:
        return _json({"error": str(exc)}, request, actor, token, 401)
    except ValueError as exc:
        return _json({"error": str(exc)}, request, actor, token, 422)
    return _json(value, request, actor, token)


@app.post("/api/checkout/preview", include_in_schema=False)
async def checkout(request: Request) -> JSONResponse:
    actor, token, _ = _cookies(request)
    body = await _body(request)
    try:
        value = store.checkout_preview(actor, str(body.get("promo", "")))
    except ValueError as exc:
        return _json({"error": str(exc)}, request, actor, token, 422)
    return _json(value, request, actor, token)


@app.get("/{path:path}", include_in_schema=False)
async def page(path: str, request: Request) -> HTMLResponse:
    pathname = "/" + path
    product_path = pathname.startswith("/en-ca/products/") and pathname.removeprefix("/en-ca/products/") in store.PRODUCT_BY_SLUG
    status = 200 if pathname in KNOWN_PATHS or product_path else 404
    body = INDEX.read_text(encoding="utf-8")
    route_marker = html.escape(pathname, quote=True)
    body = body.replace(
        "<body>",
        f'<body data-route="{route_marker}"><p hidden data-route-announcer>Fenty Beauty route {route_marker}</p>',
        1,
    )
    return HTMLResponse(body, status_code=status)
