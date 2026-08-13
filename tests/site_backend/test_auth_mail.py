from __future__ import annotations

import json
from pathlib import Path

from websitebench.local_clone_auth import (
    MAIL_SMTP_PENDING,
    LocalAuthStore,
)
from websitebench.site_backend import AuthMailDelivery, SiteBackend

from .helpers import runtime_config


class _Response:
    status = 200

    def read(self, _size: int) -> bytes:
        return b'{"ok":true}'

    def close(self) -> None:
        pass


def test_auth_mail_delivers_ephemeral_reset_code_as_structured_envelope(
    tmp_path: Path,
) -> None:
    runtime = runtime_config()
    runtime["mail"]["purposes"]["password-reset"] = {
        "template_id": "alpha.password-reset.v1",
        "subject": "Recover your Alpha Clone account",
        "lead": "A password recovery was requested.",
        "body": "Enter recovery code ${code} to continue.",
        "expiry": "This code expires in ${minutes} minutes.",
        "footer": "Ignore this message if you did not request recovery.",
        "required_variables": ["code", "minutes"],
        "secret_variables": ["code"],
    }
    backend = SiteBackend.open(runtime, data_root=tmp_path)
    backend.lifecycle.initialize()
    worker_token = "site-auth-mail-worker-token-0123456789"
    store = LocalAuthStore(
        backend.lifecycle.database_path,
        site_id="alpha",
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    store.ensure_schema()
    store.seed_account(
        subject_id="owner-subject",
        email="owner@example.test",
        display_name="Owner",
        password="SecurePassword123!",
    )
    session = store.create_anonymous_session()
    store.start_password_reset(session, email="owner@example.test")

    captured = []

    def opener(request, *, timeout: int):
        assert timeout == 10
        captured.append(request)
        return _Response()

    delivered = AuthMailDelivery(
        backend,
        store,
        worker_token=worker_token,
        environment={
            "WEBSITEBENCH_RESEND_INTERNAL_ORIGIN": "http://resend.internal:8080",
            "PUBLIC_CLONE_AUTH_EFFECTS_TOKEN": "internal-effects-token",
            "RESEND_API_KEY": "must-not-leave-the-gateway",
        },
        opener=opener,
    ).deliver_for_session(session, purpose="password-reset")

    assert delivered is not None
    assert delivered["status"] == "SMTP_SENT"
    assert len(captured) == 1
    request = captured[0]
    assert request.full_url == "http://resend.internal:8080/auth-emails"
    assert request.get_header("Authorization") is None
    envelope = json.loads(bytes(request.data).decode("utf-8"))
    assert envelope["purpose"] == "password-reset"
    assert envelope["template_id"] == "alpha.password-reset.v1"
    assert envelope["recipient"] == "owner@example.test"
    assert envelope["variables"]["minutes"] == 10
    code = envelope["variables"]["code"]
    assert len(code) == 6 and code.isdecimal()
    assert not {"from", "html", "subject", "text"}.intersection(envelope)
    assert code.encode("utf-8") not in backend.lifecycle.database_path.read_bytes()
    store.verify_password_reset_code(session, code)

