from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parent
mimetypes.add_type("image/avif", ".avif")

app = FastAPI(
    title="Coursera WACZ homepage",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def add_browser_safety_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/healthz", include_in_schema=False)
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(ROOT / "index.html", media_type="text/html")


@app.exception_handler(404)
def not_found(request: Request, error: Exception) -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Page not in archive</title><link rel="stylesheet" href="/static/styles.css"></head>
<body class="boundary-page"><main><a class="wordmark" href="/">coursera</a>
<p class="eyebrow">Homepage-only archive</p><h1>This page was not included in the supplied archive.</h1>
<p>The reconstruction contains the captured Coursera homepage only.</p><a class="primary-button" href="/">Return to homepage</a></main></body></html>""",
        status_code=404,
    )
