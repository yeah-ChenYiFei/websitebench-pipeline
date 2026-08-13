from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from websitebench.site_backend import MailError, SiteBackend

from .helpers import runtime_config


def test_same_sender_domain_can_have_distinct_site_brand_and_copy(tmp_path: Path) -> None:
    alpha = SiteBackend.open(
        runtime_config("alpha", "Alpha Store"), data_root=tmp_path / "alpha"
    )
    beta = SiteBackend.open(
        runtime_config("beta", "Beta Academy"), data_root=tmp_path / "beta"
    )
    alpha.lifecycle.initialize()
    beta.lifecycle.initialize()
    alpha_mail = alpha.mail.issue(
        "registration", "same@example.test", {"code": "123456", "minutes": 10}
    )
    beta_mail = beta.mail.issue(
        "registration", "same@example.test", {"code": "654321", "minutes": 5}
    )
    assert alpha_mail["sender_address_env"] == beta_mail["sender_address_env"]
    assert alpha_mail["sender_display_name"] != beta_mail["sender_display_name"]
    assert alpha_mail["subject"] != beta_mail["subject"]
    assert alpha_mail["text"] != beta_mail["text"]
    assert "<" not in alpha_mail["text"]


def test_structured_mail_escapes_html_and_does_not_persist_body_or_otp(
    tmp_path: Path,
) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    rendered = backend.mail.issue(
        "registration",
        "Owner@Example.test",
        {"code": "<12345>", "minutes": 10},
    )
    assert "&lt;12345&gt;" in rendered["html"]
    assert "<12345>" not in rendered["html"]
    with pytest.raises(MailError, match="cannot be persisted"):
        backend.mail.enqueue(
            "registration",
            "owner@example.test",
            {"code": "123456", "minutes": 10},
            idempotency_key="registration:12345678",
            simulation=False,
        )

    queued = backend.mail.enqueue(
        "order-receipt",
        "owner@example.test",
        {"order_id": "ORDER-1", "total": "USD 10.00"},
        idempotency_key="order:ORDER-1",
        simulation=True,
    )
    assert queued["status"] == "LOCAL_SIMULATION"
    with sqlite3.connect(backend.lifecycle.database_path) as connection:
        raw = connection.execute(
            "SELECT recipient_digest,variables_json FROM websitebench_mail_jobs"
        ).fetchone()
        database_text = backend.lifecycle.database_path.read_bytes()
    assert raw[0] != "owner@example.test"
    assert b"Your simulated order is recorded" not in database_text
    assert b"<html" not in database_text


def test_mail_idempotency_conflict_and_sanitized_failure(tmp_path: Path) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    first = backend.mail.enqueue(
        "order-receipt",
        "owner@example.test",
        {"order_id": "ORDER-1", "total": "USD 10.00"},
        idempotency_key="order:ORDER-1",
        simulation=False,
    )
    replay = backend.mail.enqueue(
        "order-receipt",
        "owner@example.test",
        {"order_id": "ORDER-1", "total": "USD 10.00"},
        idempotency_key="order:ORDER-1",
        simulation=False,
    )
    assert replay == first
    with pytest.raises(MailError, match="conflicts"):
        backend.mail.enqueue(
            "order-receipt",
            "owner@example.test",
            {"order_id": "ORDER-1", "total": "USD 12.00"},
            idempotency_key="order:ORDER-1",
            simulation=False,
        )
    failed = backend.mail.mark_failed(first["mail_id"], category="network")
    assert failed["status"] == "PENDING"
    assert failed["error_category"] == "network"
    with pytest.raises(MailError, match="sanitized"):
        backend.mail.mark_failed(first["mail_id"], category="raw provider says secret")


def test_mail_claim_retry_crash_replay_and_terminal_failure(tmp_path: Path) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    queued = backend.mail.enqueue(
        "order-receipt",
        "owner@example.test",
        {"order_id": "ORDER-2", "total": "USD 12.00"},
        idempotency_key="order:ORDER-2",
        simulation=False,
    )

    first = backend.mail.claim_pending(mail_id=queued["mail_id"], now=100)
    assert first is not None
    assert first["message"]["recipient"] == "owner@example.test"
    assert first["delivery_attempts"] == 1
    retrying = backend.mail.mark_failed(
        queued["mail_id"],
        claim_token=first["claim_token"],
        category="network",
        retry_delay_seconds=10,
        now=100,
    )
    assert retrying["status"] == "PENDING"
    assert backend.mail.claim_pending(mail_id=queued["mail_id"], now=109) is None

    second = backend.mail.claim_pending(mail_id=queued["mail_id"], now=110)
    assert second is not None
    assert backend.mail.release_stale_claims(older_than=110, now=120) == 1
    third = backend.mail.claim_pending(mail_id=queued["mail_id"], now=120)
    assert third is not None
    terminal = backend.mail.mark_failed(
        queued["mail_id"],
        claim_token=third["claim_token"],
        category="provider-rejected",
    )
    assert terminal["status"] == "FAILED"
    assert terminal["delivery_attempts"] == 3
    assert backend.mail.claim_pending(mail_id=queued["mail_id"], now=121) is None


def test_mail_claim_can_be_marked_sent_exactly_once(tmp_path: Path) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    queued = backend.mail.enqueue(
        "order-receipt",
        "owner@example.test",
        {"order_id": "ORDER-3", "total": "USD 13.00"},
        idempotency_key="order:ORDER-3",
        simulation=False,
    )
    claimed = backend.mail.claim_pending(mail_id=queued["mail_id"], now=100)
    assert claimed is not None
    sent = backend.mail.mark_sent(
        queued["mail_id"], claim_token=claimed["claim_token"]
    )
    assert sent["status"] == "SENT"
    with pytest.raises(MailError, match="missing or stale"):
        backend.mail.mark_sent(
            queued["mail_id"], claim_token=claimed["claim_token"]
        )


def test_caller_supplied_mail_connection_requires_active_transaction(
    tmp_path: Path,
) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    with backend.lifecycle.connection() as connection:
        with pytest.raises(MailError, match="active transaction"):
            backend.mail.enqueue(
                "order-receipt",
                "owner@example.test",
                {"order_id": "ORDER-4", "total": "USD 14.00"},
                idempotency_key="order:ORDER-4",
                simulation=False,
                connection=connection,
            )


def test_mail_operations_do_not_log_recipient_body_otp_or_provider_secret(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    recipient = "sensitive-recipient@example.test"
    otp = "907341"
    provider_secret = "re_test_provider_secret_must_not_leak"
    rendered_body = "Your verification code is 907341."

    caplog.set_level(logging.DEBUG)
    rendered = backend.mail.issue(
        "registration",
        recipient,
        {"code": otp, "minutes": 10},
    )
    assert rendered_body in rendered["text"]
    queued = backend.mail.enqueue(
        "order-receipt",
        recipient,
        {"order_id": "ORDER-LOG-1", "total": "USD 9.07"},
        idempotency_key="order:ORDER-LOG-1",
        simulation=False,
    )
    claimed = backend.mail.claim_pending(mail_id=queued["mail_id"], now=100)
    assert claimed is not None
    backend.mail.mark_failed(
        queued["mail_id"],
        claim_token=claimed["claim_token"],
        category="provider-auth",
    )

    captured = capsys.readouterr()
    emitted = "\n".join(
        (
            caplog.text,
            captured.out,
            captured.err,
        )
    )
    for secret in (recipient, otp, rendered_body, provider_secret):
        assert secret not in emitted
