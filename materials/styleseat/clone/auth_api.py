"""Local account API for the StyleSeat offline clone."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from websitebench.local_clone_auth import (
    AuthConflict,
    AuthExpired,
    AuthLocked,
    AuthRateLimited,
    AuthRejected,
    AuthValidationError,
    RESET_PUBLIC_MESSAGE,
)


PREFIX = "/_local/auth"
router = APIRouter()
_auth_provider: Callable[[], Any] | None = None
_cookie_name = ""
_cookie_options: dict[str, Any] = {}


def configure(
    auth_provider: Callable[[], Any], *, cookie_name: str, cookie_options: dict[str, Any]
) -> None:
    global _auth_provider, _cookie_name, _cookie_options
    _auth_provider = auth_provider
    _cookie_name = cookie_name
    _cookie_options = dict(cookie_options)


def _auth() -> Any:
    if _auth_provider is None:
        raise RuntimeError("local authentication is not configured")
    return _auth_provider()


def _session_token(request: Request) -> str | None:
    return request.cookies.get(_cookie_name)


def _set_session(response: JSONResponse, request: Request, token: str) -> None:
    del request
    response.set_cookie(_cookie_name, token, **_cookie_options)


def _response(
    payload: dict[str, Any],
    request: Request,
    *,
    token: str | None = None,
    status: int = 200,
) -> JSONResponse:
    response = JSONResponse(payload, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    if token:
        _set_session(response, request, token)
    return response


def _status_for(error: Exception) -> int:
    for kind, status in (
        (AuthRateLimited, 429),
        (AuthLocked, 423),
        (AuthExpired, 410),
        (AuthConflict, 409),
        (AuthValidationError, 400),
        (AuthRejected, 401),
    ):
        if isinstance(error, kind):
            return status
    return 500


def _error(error: Exception, request: Request) -> JSONResponse:
    status = _status_for(error)
    if status == 500:
        raise error
    return _response(
        {"error": type(error).__name__, "detail": str(error)},
        request,
        status=status,
    )


async def _body(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception:
        try:
            value = dict(await request.form())
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def _ensure(request: Request) -> tuple[Any, str]:
    auth = _auth()
    token, _ = auth.ensure_session(_session_token(request))
    return auth, token


def _public(auth: Any, token: str) -> dict[str, Any]:
    record = auth.resolve_session(token)
    account = (
        record.get("account")
        if isinstance(record, dict) and record.get("authenticated")
        else None
    )
    account = account if isinstance(account, dict) else {}
    return {
        "authenticated": bool(account),
        "email": account.get("email_normalized"),
        "displayName": account.get("display_name"),
    }


@router.get(PREFIX + "/session")
def session_state(request: Request) -> JSONResponse:
    try:
        auth, token = _ensure(request)
    except Exception as error:
        return _error(error, request)
    return _response(_public(auth, token), request, token=token)


@router.post(PREFIX + "/register/start")
async def register_start(request: Request) -> JSONResponse:
    body = await _body(request)
    try:
        auth, token = _ensure(request)
        auth.start_registration(
            token,
            email=str(body.get("email", "")),
            display_name=str(body.get("displayName") or body.get("display_name") or ""),
            password=str(body.get("password", "")),
            restart_invalid_flow=True,
        )
        flow = auth.session_flow_status(token, purpose="registration")
    except Exception as error:
        return _error(error, request)
    return _response(
        {"stage": "pending-verification", "flow": flow},
        request,
        token=token,
    )


@router.post(PREFIX + "/register/verify")
async def register_verify(request: Request) -> JSONResponse:
    body = await _body(request)
    try:
        auth, token = _ensure(request)
        auth.verify_registration_code(token, str(body.get("code", "")))
    except Exception as error:
        return _error(error, request)
    return _response({"stage": "verified"}, request, token=token)


@router.post(PREFIX + "/register/complete")
def register_complete(request: Request) -> JSONResponse:
    try:
        auth, token = _ensure(request)
        result = auth.complete_registration(token)
        fresh = result.get("session_token") if isinstance(result, dict) else None
        token = fresh or token
    except Exception as error:
        return _error(error, request)
    return _response(
        {"stage": "account-created", **_public(auth, token)},
        request,
        token=token,
    )


@router.post(PREFIX + "/signin")
async def signin(request: Request) -> JSONResponse:
    body = await _body(request)
    try:
        auth, token = _ensure(request)
        result = auth.sign_in(
            token,
            email=str(body.get("email", "")),
            password=str(body.get("password", "")),
        )
        fresh = result.get("session_token") if isinstance(result, dict) else None
        token = fresh or token
    except Exception as error:
        return _error(error, request)
    return _response(_public(auth, token), request, token=token)


@router.post(PREFIX + "/signout")
def signout(request: Request) -> JSONResponse:
    try:
        auth, token = _ensure(request)
        auth.sign_out(token)
        token = auth.create_anonymous_session()
    except Exception as error:
        return _error(error, request)
    return _response(
        {"authenticated": False, "email": None, "displayName": None},
        request,
        token=token,
    )


@router.post(PREFIX + "/reset/start")
async def reset_start(request: Request) -> JSONResponse:
    body = await _body(request)
    try:
        auth, token = _ensure(request)
        auth.start_password_reset(
            token,
            email=str(body.get("email", "")),
            restart_invalid_flow=True,
        )
    except Exception as error:
        return _error(error, request)
    return _response({"message": RESET_PUBLIC_MESSAGE}, request, token=token)


@router.post(PREFIX + "/reset/verify")
async def reset_verify(request: Request) -> JSONResponse:
    body = await _body(request)
    try:
        auth, token = _ensure(request)
        auth.verify_password_reset_code(token, str(body.get("code", "")))
    except Exception as error:
        return _error(error, request)
    return _response({"stage": "verified"}, request, token=token)


@router.post(PREFIX + "/reset/complete")
async def reset_complete(request: Request) -> JSONResponse:
    body = await _body(request)
    try:
        auth, token = _ensure(request)
        rotated = auth.complete_password_reset(
            token,
            new_password=str(body.get("password") or body.get("new_password") or ""),
        )
        # Reset completion creates an authenticated rotation inside the Store.
        # The StyleSeat recovery UI promises a return to sign-in, so revoke
        # that internal token and give the browser a fresh anonymous session.
        auth.sign_out(rotated)
        token = auth.create_anonymous_session()
    except Exception as error:
        return _error(error, request)
    return _response(
        {"stage": "consumed", "authenticated": False},
        request,
        token=token,
    )


@router.get(PREFIX + "/outbox")
def local_outbox(request: Request, purpose: str = "registration") -> JSONResponse:
    if purpose not in {"registration", "password-reset"}:
        return _response(
            {"error": "invalid-purpose", "detail": "mail purpose is invalid"},
            request,
            status=400,
        )
    try:
        auth, token = _ensure(request)
        mail = auth.local_mail_for_session(token, purpose=purpose)
    except Exception as error:
        return _error(error, request)
    return _response(
        {"purpose": purpose, "mail": mail},
        request,
        token=token,
    )
