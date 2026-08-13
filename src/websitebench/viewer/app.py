"""Authenticated FastAPI application for WebsiteBench corpus QA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import (
    LOGIN_CSRF_COOKIE,
    SESSION_COOKIE,
    AuthManager,
    AuthSettings,
    LoginLimiter,
)
from .discovery import CorpusIndex, discover_corpus
from .evidence import EvidenceStore
from .review_mode import (
    ReviewModeConflict,
    ReviewModeError,
    ReviewSessionStore,
)
from .reviews import ReviewConflict, ReviewError, ReviewStore, empty_review


PACKAGE_ROOT = Path(__file__).resolve().parent
SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "script-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def _safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else "/"


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _template_context(
    request: Request,
    *,
    index: CorpusIndex,
    auth: AuthManager,
    **values: Any,
) -> dict[str, Any]:
    session = auth.session(request.cookies.get(SESSION_COOKIE))
    return {
        "request": request,
        "profile": index.profile,
        "session": session,
        "csrf_token": session.get("csrf") if session else "",
        **values,
    }


def create_app(
    repo_root: Path | None = None,
    *,
    profile: str = "internal",
    settings: AuthSettings | None = None,
    review_root: Path | None = None,
    review_session_root: Path | None = None,
    evidence_root: Path | None = None,
    public_allowlist: Path | None = None,
) -> FastAPI:
    root = (repo_root or Path.cwd()).resolve()
    settings = settings or AuthSettings.from_env()
    auth = AuthManager(settings)
    limiter = LoginLimiter(settings.login_attempts, settings.login_window_seconds)
    index = discover_corpus(root, profile=profile, public_allowlist=public_allowlist)
    reviews = ReviewStore(
        review_root or root / "artifacts" / "websitebench-viewer" / "reviews", root
    )
    review_sessions = ReviewSessionStore(
        review_session_root
        or root / "artifacts" / "websitebench-viewer" / "review-sessions",
        root,
    )
    evidence = EvidenceStore(
        evidence_root or root / "artifacts" / "websitebench-viewer" / "visual", root
    )
    templates = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))

    app = FastAPI(
        title="WebsiteBench Clone Atlas",
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))
    app.mount("/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static")
    app.state.corpus_index = index
    app.state.review_store = reviews
    app.state.review_session_store = review_sessions
    app.state.evidence_store = evidence

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = SECURITY_POLICY
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        return response

    def session_or_none(request: Request) -> dict[str, Any] | None:
        return auth.session(request.cookies.get(SESSION_COOKIE))

    def require_page(request: Request) -> dict[str, Any] | RedirectResponse:
        session = session_or_none(request)
        if session is None:
            return RedirectResponse(
                f"/login?next={request.url.path}", status_code=303
            )
        return session

    def require_api(request: Request, *, csrf: bool = False) -> dict[str, Any]:
        session = session_or_none(request)
        if session is None:
            raise HTTPException(401, "authentication required")
        if csrf and not auth.csrf_matches(session, request.headers.get("x-csrf-token")):
            raise HTTPException(403, "invalid CSRF token")
        return session

    def current_review(item: dict[str, Any]) -> dict[str, Any]:
        review = reviews.load(item["key"])
        if profile == "public" and review and not (
            review["decision"] == "approve" and review["visibility"] == "public"
        ):
            review = None
        return review or empty_review(item["key"])

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "profile": profile}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, next: str | None = None) -> Response:
        if session_or_none(request):
            return RedirectResponse(_safe_next(next), status_code=303)
        token = auth.login_csrf()
        response = templates.TemplateResponse(
            request,
            "login.html",
            _template_context(
                request,
                index=index,
                auth=auth,
                login_csrf=token,
                next_path=_safe_next(next),
                error=None,
            ),
        )
        response.set_cookie(
            LOGIN_CSRF_COOKIE,
            token,
            secure=settings.cookie_secure,
            httponly=True,
            samesite="strict",
            max_age=15 * 60,
            path="/login",
        )
        return response

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        csrf_token: str = Form(""),
        next_path: str = Form("/"),
    ) -> Response:
        client = _client_key(request)
        if not limiter.allowed(client):
            raise HTTPException(429, "too many login attempts; try again later")
        csrf_ok = auth.verify_login_csrf(
            csrf_token, request.cookies.get(LOGIN_CSRF_COOKIE)
        )
        credentials_ok = csrf_ok and auth.verify_password(username, password)
        if not credentials_ok:
            limiter.failure(client)
            token = auth.login_csrf()
            response = templates.TemplateResponse(
                request,
                "login.html",
                _template_context(
                    request,
                    index=index,
                    auth=auth,
                    login_csrf=token,
                    next_path=_safe_next(next_path),
                    error="Login failed. Check the credentials and try again.",
                ),
                status_code=401,
            )
            response.set_cookie(
                LOGIN_CSRF_COOKIE,
                token,
                secure=settings.cookie_secure,
                httponly=True,
                samesite="strict",
                max_age=15 * 60,
                path="/login",
            )
            return response
        limiter.success(client)
        response = RedirectResponse(_safe_next(next_path), status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            auth.session_token(),
            secure=settings.cookie_secure,
            httponly=True,
            samesite="strict",
            max_age=settings.session_seconds,
            path="/",
        )
        response.delete_cookie(LOGIN_CSRF_COOKIE, path="/login")
        return response

    @app.post("/logout")
    async def logout(request: Request, csrf_token: str = Form("")) -> Response:
        session = session_or_none(request)
        if session is None or not auth.csrf_matches(session, csrf_token):
            raise HTTPException(403, "invalid CSRF token")
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        data = index.as_dict()
        item_reviews = {item["key"]: current_review(item) for item in index.items}
        return templates.TemplateResponse(
            request,
            "home.html",
            _template_context(
                request, index=index, auth=auth, summary=data["summary"], items=index.items,
                reviews=item_reviews, categories=index.categories, models=index.models,
                evaluation_matrix=index.evaluation_matrix,
            ),
        )

    @app.get("/tasks", response_class=HTMLResponse)
    async def tasks_page(request: Request) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        return templates.TemplateResponse(
            request,
            "tasks.html",
            _template_context(
                request, index=index, auth=auth, items=index.items,
                reviews={item["key"]: current_review(item) for item in index.items},
            ),
        )

    @app.get("/tasks/{item_key}", response_class=HTMLResponse)
    async def task_detail(request: Request, item_key: str) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        item = index.by_key(item_key)
        if item is None:
            raise HTTPException(404, "corpus item not found")
        visual = evidence.load(item_key) or item.get("visual_evidence")
        return templates.TemplateResponse(
            request,
            "task_detail.html",
            _template_context(
                request, index=index, auth=auth, item=item, review=current_review(item),
                visual=visual,
            ),
        )

    @app.get("/models", response_class=HTMLResponse)
    async def models_page(request: Request) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        return templates.TemplateResponse(
            request,
            "models.html",
            _template_context(
                request,
                index=index,
                auth=auth,
                models=index.models,
                site_count=len(index.evaluation_matrix),
            ),
        )

    @app.get("/models/{model_key}", response_class=HTMLResponse)
    async def model_detail(request: Request, model_key: str) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        model = index.model_by_key(model_key)
        if model is None:
            raise HTTPException(404, "model result group not found")
        runs = []
        for run in model["runs"]:
            item = next(item for item in index.items if item["site_id"] == run["site_id"])
            runs.append({"run": run, "item": item})
        return templates.TemplateResponse(
            request,
            "model_detail.html",
            _template_context(request, index=index, auth=auth, model=model, runs=runs),
        )

    @app.get("/results", response_class=HTMLResponse)
    async def results_page(request: Request) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        return templates.TemplateResponse(
            request,
            "results.html",
            _template_context(
                request,
                index=index,
                auth=auth,
                models=index.models,
                matrix=index.evaluation_matrix,
            ),
        )

    @app.get("/compare", response_class=HTMLResponse)
    async def compare_page(
        request: Request,
        items: list[str] = Query(default=[]),
        keys: str | None = None,
    ) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        selected_keys = items or ([part for part in (keys or "").split(",") if part])
        if not selected_keys:
            selected_keys = [item["key"] for item in index.items[:2]]
        known_keys = {item["key"] for item in index.items}
        selected_keys = [
            key for key in dict.fromkeys(selected_keys) if key in known_keys
        ]
        if len(selected_keys) > 4:
            raise HTTPException(400, "compare accepts at most four corpus items")
        selected = [index.by_key(key) for key in selected_keys]
        selected = [item for item in selected if item is not None]
        return templates.TemplateResponse(
            request,
            "compare.html",
            _template_context(
                request, index=index, auth=auth, items=index.items, selected=selected,
                selected_keys=selected_keys,
                reviews={item["key"]: current_review(item) for item in selected},
                selection_error="Choose 2–4 tasks to compare." if len(selected) < 2 else None,
            ),
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        run = index.run_by_id(run_id)
        if run is None:
            raise HTTPException(404, "valid websitebench.result.v1 run not found")
        item = next(item for item in index.items if run in item["official_runs"])
        run_visual = evidence.load(item["key"], run_id) if profile == "internal" else None
        visual = (
            run_visual or evidence.load(item["key"]) or item.get("visual_evidence")
            if profile == "internal"
            else item.get("visual_evidence")
        )
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            _template_context(
                request, index=index, auth=auth, run=run, item=item, visual=visual,
                visual_run_specific=run_visual is not None,
            ),
        )

    @app.get("/methodology", response_class=HTMLResponse)
    async def methodology(request: Request) -> Response:
        session = require_page(request)
        if isinstance(session, RedirectResponse):
            return session
        return templates.TemplateResponse(
            request, "methodology.html", _template_context(request, index=index, auth=auth)
        )

    @app.get("/api/reviews/export")
    async def reviews_export(request: Request) -> Response:
        require_api(request)
        bundle = reviews.export(public_only=profile == "public")
        return Response(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=websitebench-reviews.json"},
        )

    @app.get("/api/reviews/{item_key}")
    async def review_get(request: Request, item_key: str) -> dict[str, Any]:
        require_api(request)
        item = index.by_key(item_key)
        if item is None:
            raise HTTPException(404, "corpus item not found")
        return current_review(item)

    @app.put("/api/reviews/{item_key}")
    async def review_put(request: Request, item_key: str) -> Response:
        session = require_api(request, csrf=True)
        if profile == "public":
            raise HTTPException(403, "review writes are disabled in the public profile")
        item = index.by_key(item_key)
        if item is None:
            raise HTTPException(404, "corpus item not found")
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "request body must be JSON") from exc
        try:
            review = reviews.save(
                item_key,
                body.get("review", body),
                expected_revision=int(body.get("expected_revision", -1)),
                default_reviewer=session["username"],
            )
        except ReviewConflict as exc:
            return JSONResponse(
                {"error": str(exc), "current_revision": exc.current}, status_code=409
            )
        except (ReviewError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse(review)

    @app.post("/api/reviews/import")
    async def reviews_import(request: Request) -> Response:
        require_api(request, csrf=True)
        if profile == "public":
            raise HTTPException(403, "review imports are disabled in the public profile")
        try:
            bundle = await request.json()
            imported = reviews.import_batch(
                bundle,
                known_item_keys={item["key"] for item in index.items},
            )
        except ReviewConflict as exc:
            return JSONResponse(
                {"error": str(exc), "current_revision": exc.current}, status_code=409
            )
        except (ReviewError, AttributeError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse({"imported": len(imported)})

    @app.get("/api/review-mode/export")
    async def review_mode_export(
        request: Request, item_key: str | None = None
    ) -> Response:
        require_api(request)
        if profile == "public":
            raise HTTPException(403, "Review Mode is unavailable in the public profile")
        if item_key is not None and index.by_key(item_key) is None:
            raise HTTPException(404, "corpus item not found")
        try:
            bundle = review_sessions.export(item_key=item_key)
        except ReviewModeError as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    "attachment; filename=websitebench-review-sessions.json"
                )
            },
        )

    @app.get("/api/review-mode/{item_key}")
    async def review_mode_get(request: Request, item_key: str) -> Response:
        require_api(request)
        if profile == "public":
            raise HTTPException(403, "Review Mode is unavailable in the public profile")
        item = index.by_key(item_key)
        if item is None:
            raise HTTPException(404, "corpus item not found")
        try:
            review_session = review_sessions.current(item_key)
        except ReviewModeError as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse(review_session)

    @app.post("/api/review-mode/{item_key}/findings")
    async def review_mode_add(request: Request, item_key: str) -> Response:
        session = require_api(request, csrf=True)
        if profile == "public":
            raise HTTPException(403, "Review Mode writes are disabled in the public profile")
        item = index.by_key(item_key)
        if item is None:
            raise HTTPException(404, "corpus item not found")
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "request body must be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(422, "request body must be an object")
        try:
            review_session = review_sessions.add_finding(
                item_key,
                body.get("finding", {}),
                expected_revision=int(body.get("expected_revision", -1)),
                reviewer=session["username"],
            )
        except ReviewModeConflict as exc:
            return JSONResponse(
                {"error": str(exc), "current_revision": exc.current}, status_code=409
            )
        except (ReviewModeError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse(review_session)

    @app.patch("/api/review-mode/{item_key}/findings/{finding_id}")
    async def review_mode_update(
        request: Request, item_key: str, finding_id: str
    ) -> Response:
        require_api(request, csrf=True)
        if profile == "public":
            raise HTTPException(403, "Review Mode writes are disabled in the public profile")
        item = index.by_key(item_key)
        if item is None:
            raise HTTPException(404, "corpus item not found")
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "request body must be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(422, "request body must be an object")
        try:
            review_session = review_sessions.update_finding(
                item_key,
                finding_id,
                body.get("finding", {}),
                expected_revision=int(body.get("expected_revision", -1)),
            )
        except ReviewModeConflict as exc:
            return JSONResponse(
                {"error": str(exc), "current_revision": exc.current}, status_code=409
            )
        except (ReviewModeError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse(review_session)

    @app.get("/artifacts/{item_key}/runs/{run_id}/{artifact_path:path}")
    async def run_artifact(
        request: Request, item_key: str, run_id: str, artifact_path: str
    ) -> Response:
        require_api(request)
        item = index.by_key(item_key)
        run = index.run_by_id(run_id)
        if item is None or run is None or run not in item["official_runs"]:
            raise HTTPException(404, "run artifact not found")
        if profile == "public":
            raise HTTPException(404, "artifact not published")
        try:
            path = evidence.resolve(item_key, artifact_path, run_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "run artifact not found") from None
        return FileResponse(path)

    @app.get("/artifacts/{item_key}/{artifact_path:path}")
    async def artifact(request: Request, item_key: str, artifact_path: str) -> Response:
        require_api(request)
        item = index.by_key(item_key)
        if item is None:
            raise HTTPException(404, "corpus item not found")
        if profile == "public":
            raise HTTPException(404, "artifact not published")
        try:
            path = evidence.resolve(item_key, artifact_path)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "artifact not found") from None
        return FileResponse(path)

    return app
