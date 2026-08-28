"""Asana offline clone — WebsiteBench candidate application.

Route hub only; business logic lives in ``asana_app``. All state is local:
site-bound SQLite through the generated ``websitebench.site_backend`` seam and
LocalAuthStore. No runtime request leaves the local origin.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from asana_app import pages
from asana_app.api import _cookie_name, router as api_router
from asana_app.services import SERVICES

SITE_ID = "asana"
DISPLAY_NAME = "Asana"
CLONE_ROOT = Path(__file__).resolve().parent

app = FastAPI(title=DISPLAY_NAME, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=CLONE_ROOT / "static"), name="static")


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse(
        {"ok": True, "site_id": SITE_ID},
        headers={
            "X-WebsiteBench-Container-Build-ID": os.environ.get(
                "DEPLOYMENT_BUILD_ID", os.environ.get("SOURCE_REF", "")
            )
        },
    )


_MARKETING = {
    "/": pages.home_page,
    "/pricing": pages.pricing_page,
    "/product": pages.product_page,
    "/resources": pages.resources_page,
    "/templates": pages.templates_page,
}


def _register_marketing(path: str, render) -> None:
    @app.get(path, response_class=HTMLResponse)
    def marketing_page() -> str:  # pragma: no cover - thin wrapper
        return render()


for _path, _render in _MARKETING.items():
    _register_marketing(_path, _render)


@app.get("/templates/{category}", response_class=HTMLResponse)
def template_category(category: str) -> str:
    """Keep every observed public template-card destination locally reachable."""

    return pages.templates_page()


@app.get("/resources/category/{category}", response_class=HTMLResponse)
def resource_category(category: str) -> str:
    """Keep every observed resource-card destination locally reachable."""

    return pages.resources_page()


@app.get("/demo/main", response_class=HTMLResponse)
def public_demo() -> str:
    return pages.resources_page()


@app.get("/terms/{document}", response_class=HTMLResponse)
def public_terms(document: str) -> str:
    return pages.templates_page()


@app.get("/solutions", response_class=HTMLResponse)
def unavailable_solutions() -> HTMLResponse:
    """Mirror the directly observed public source status and rescue surface."""

    return HTMLResponse(pages.solutions_page(), status_code=404)


def _authenticated(request: Request) -> bool:
    token = request.cookies.get(_cookie_name(request, SERVICES))
    session = SERVICES.auth.resolve_session(token)
    return bool(session and session.get("authenticated"))


@app.get("/-/login", response_class=HTMLResponse)
def login(request: Request):
    if _authenticated(request):
        return RedirectResponse("/app/home", status_code=302)
    return pages.login_page()


@app.get("/create-account", response_class=HTMLResponse)
def create_account(request: Request, email: str = ""):
    if _authenticated(request):
        return RedirectResponse("/app/home", status_code=302)
    return pages.signup_page(email)


@app.get("/-/forgot_password", response_class=HTMLResponse)
def forgot_password() -> str:
    return pages.forgot_page()


# Dash-free aliases for tooling that cannot pass "-/" routes as arguments
# (OpenCLI adapters treat a leading dash as an option). Same content.
@app.get("/login", response_class=HTMLResponse)
def login_alias(request: Request):
    return login(request)


@app.get("/forgot_password", response_class=HTMLResponse)
def forgot_alias() -> str:
    return pages.forgot_page()


@app.get("/app", response_class=HTMLResponse)
@app.get("/app/{rest:path}", response_class=HTMLResponse)
def app_pages(request: Request, rest: str = ""):
    if not _authenticated(request):
        target = request.url.path
        return RedirectResponse(f"/-/login?u={target}", status_code=302)
    return pages.app_shell()
