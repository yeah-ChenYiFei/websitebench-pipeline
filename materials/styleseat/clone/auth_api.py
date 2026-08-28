"""Local account API for the StyleSeat offline clone."""

from __future__ import annotations

import os
import secrets
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
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
    MAIL_LOCAL_ONLY,
    MAIL_SMTP_PENDING,
    RESET_PUBLIC_MESSAGE,
)


PREFIX = "/_local/auth"
COOKIE = "wb_session"
router = APIRouter()
_SMTP_KEYS = (
    "WEBSITEBENCH_SMTP_HOST",
    "WEBSITEBENCH_SMTP_PORT",
    "WEBSITEBENCH_SMTP_FROM",
)
_MAIL_WORKER_TOKEN = secrets.token_urlsafe(32)

_auth_provider: Callable[[], Any] | None = None


def smtp_enabled() -> bool:
    return all((os.environ.get(key) or "").strip() for key in _SMTP_KEYS)


def store_mail_options() -> dict[str, str | None]:
    enabled = smtp_enabled()
    return {
        "mail_mode": MAIL_SMTP_PENDING if enabled else MAIL_LOCAL_ONLY,
        "mail_worker_token": _MAIL_WORKER_TOKEN if enabled else None,
    }


def _deliver_smtp(
    auth: Any,
    session_token: str,
    purpose: str,
    *,
    worker_token: str = _MAIL_WORKER_TOKEN,
) -> dict[str, Any] | None:
    if not smtp_enabled():
        return None
    claim = auth.claim_pending_mail_for_session(
        session_token,
        purpose=purpose,
        worker_token=worker_token,
    )
    if claim is None:
        return None

    mail_id = int(claim["mail_id"])
    claim_token = str(claim["claim_token"])
    try:
        port = int(os.environ["WEBSITEBENCH_SMTP_PORT"].strip())
        message = EmailMessage()
        message["From"] = os.environ["WEBSITEBENCH_SMTP_FROM"].strip()
        message["To"] = str(claim["recipient"])
        if purpose == "registration":
            message["Subject"] = "Verify your StyleSeat account"
            lead = "Finish creating your StyleSeat account."
        else:
            message["Subject"] = "Reset your StyleSeat password"
            lead = "A password reset was requested for StyleSeat."
        message.set_content(
            f"{lead}\n\nYour 6-digit verification code is "
            f"{claim['verification_code']}.\n\nThis code expires in 10 minutes."
        )
    except (KeyError, TypeError, ValueError):
        auth.finish_mail_claim(
            mail_id,
            claim_token,
            sent=False,
            target_request_count=0,
            error="configuration",
            worker_token=worker_token,
        )
        return {"mail_id": mail_id, "purpose": purpose, "status": "SMTP_FAILED"}

    auth.reserve_mail_target_request(
        mail_id,
        claim_token,
        worker_token=worker_token,
    )
    try:
        with smtplib.SMTP(
            os.environ["WEBSITEBENCH_SMTP_HOST"].strip(),
            port,
            timeout=10,
        ) as smtp:
            smtp.send_message(message)
    except Exception:
        auth.finish_mail_claim(
            mail_id,
            claim_token,
            sent=False,
            target_request_count=1,
            accepted_request_count=0,
            error="network",
            worker_token=worker_token,
        )
        return {"mail_id": mail_id, "purpose": purpose, "status": "SMTP_FAILED"}
    auth.finish_mail_claim(
        mail_id,
        claim_token,
        sent=True,
        target_request_count=1,
        accepted_request_count=1,
        worker_token=worker_token,
    )
    return {"mail_id": mail_id, "purpose": purpose, "status": "SMTP_SENT"}


def configure(auth_provider: Callable[[], Any]) -> None:
    global _auth_provider
    _auth_provider = auth_provider


def _auth() -> Any:
    if _auth_provider is None:
        raise RuntimeError("local authentication is not configured")
    return _auth_provider()


def _session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE)


def _set_session(response: JSONResponse, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


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
        _deliver_smtp(auth, token, "registration")
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
        _deliver_smtp(auth, token, "password-reset")
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
