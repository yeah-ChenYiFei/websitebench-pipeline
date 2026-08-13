from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from websitebench.site_backend import EffectsMailDelivery, EffectsMailDeliveryError, SiteBackend

from .helpers import runtime_config


class _Response:
    def __init__(self, payload: dict[str, object], *, status: int = 200) -> None:
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status
        self.closed = False

    def read(self, _size: int) -> bytes:
        return self.payload

    def close(self) -> None:
        self.closed = True


def _queued_backend(tmp_path: Path) -> tuple[SiteBackend, dict[str, object]]:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    queued = backend.mail.enqueue(
        "order-receipt",
        "owner@example.test",
        {"order_id": "ORDER-42", "total": "USD 12.99"},
        idempotency_key="order:ORDER-42",
        simulation=False,
    )
    return backend, queued


def test_effects_mail_delivers_only_a_structured_business_envelope(
    tmp_path: Path,
) -> None:
    backend, queued = _queued_backend(tmp_path)
    captured = []

    def opener(request, *, timeout: int):
        assert timeout == 10
        captured.append(request)
        return _Response({"ok": True})

    delivered = EffectsMailDelivery(
        backend,
        environment={
            "WEBSITEBENCH_RESEND_INTERNAL_ORIGIN": "http://resend.internal:8080",
            "PUBLIC_CLONE_AUTH_EFFECTS_TOKEN": "effects-token-not-provider-secret",
            "RESEND_API_KEY": "provider-secret-that-must-not-leave-app",
        },
        opener=opener,
    ).deliver(mail_id=str(queued["mail_id"]), now=100)

    assert delivered is not None
    assert delivered["status"] == "SENT"
    assert len(captured) == 1
    request = captured[0]
    assert request.full_url == "http://resend.internal:8080/business-emails"
    assert request.get_header("X-websitebench-effects-token") == (
        "effects-token-not-provider-secret"
    )
    assert request.get_header("Authorization") is None
    envelope = json.loads(bytes(request.data).decode("utf-8"))
    assert envelope == {
        "purpose": "order-receipt",
        "template_id": "alpha.order-receipt.v1",
        "recipient": "owner@example.test",
        "variables": {"order_id": "ORDER-42", "total": "USD 12.99"},
    }
    assert not {"from", "html", "subject", "text"}.intersection(envelope)


def test_effects_mail_records_a_sanitized_retry_without_rolling_back_outbox(
    tmp_path: Path,
) -> None:
    backend, queued = _queued_backend(tmp_path)

    deferred = EffectsMailDelivery(
        backend,
        opener=lambda _request, **_kwargs: (_ for _ in ()).throw(
            URLError("private upstream detail")
        ),
        retry_delay_seconds=10,
    )
    with pytest.raises(EffectsMailDeliveryError, match="deferred") as exc_info:
        deferred.deliver(mail_id=str(queued["mail_id"]), now=100)
    assert "private upstream detail" not in str(exc_info.value)
    assert backend.mail.claim_pending(mail_id=str(queued["mail_id"]), now=109) is None

    sent = EffectsMailDelivery(
        backend,
        opener=lambda _request, **_kwargs: _Response({"ok": True}),
    ).deliver(mail_id=str(queued["mail_id"]), now=110)
    assert sent is not None
    assert sent["status"] == "SENT"
    assert sent["delivery_attempts"] == 2


def test_effects_mail_rejects_non_isolated_delivery_targets(tmp_path: Path) -> None:
    backend, _queued = _queued_backend(tmp_path)
    with pytest.raises(EffectsMailDeliveryError, match="isolated"):
        EffectsMailDelivery(
            backend,
            environment={
                "WEBSITEBENCH_RESEND_INTERNAL_ORIGIN": "https://api.resend.com"
            },
        )
