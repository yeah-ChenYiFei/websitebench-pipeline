from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from websitebench.site_backend import (
    PaymentConflict,
    PaymentError,
    PaymentRejected,
    SiteBackend,
    SiteBindingError,
)

from .helpers import runtime_config


OWNER = "owner:account-123"
OTHER_OWNER = "owner:account-999"
FINGERPRINT = "a" * 64


def backend(tmp_path: Path, site_id: str = "alpha") -> SiteBackend:
    value = SiteBackend.open(
        runtime_config(site_id, f"{site_id.title()} Clone"),
        data_root=tmp_path / site_id,
    )
    value.lifecycle.initialize()
    return value


def create_flow(value: SiteBackend, key: str = "create:order-1") -> dict[str, object]:
    return value.payments.create_intent(
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        idempotency_key=key,
    )


def test_local_sandbox_approve_decline_retry_and_idempotency(tmp_path: Path) -> None:
    value = backend(tmp_path)
    flow = create_flow(value)
    declined = value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-declined",
        idempotency_key="attempt:decline-1",
    )
    assert declined["status"] == "DECLINED"
    retryable = value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-retry",
        idempotency_key="attempt:retry-1",
    )
    assert retryable["status"] == "RETRYABLE"
    approved = value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:approve-1",
    )
    replay = value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:approve-1",
    )
    assert approved == replay
    assert approved["status"] == "APPROVED"


def test_new_attempt_supersedes_approval_and_foreign_owner_is_rejected(
    tmp_path: Path,
) -> None:
    value = backend(tmp_path)
    flow = create_flow(value)
    value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:approve-1",
    )
    value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-declined",
        idempotency_key="attempt:decline-2",
    )
    with value.lifecycle.connection(transaction=True) as connection:
        with pytest.raises(PaymentRejected, match="active approval"):
            value.payments.consume_approval(
                connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=1299,
                currency="USD",
                fingerprint=FINGERPRINT,
            )
    with pytest.raises(PaymentRejected, match="foreign"):
        value.payments.attempt(
            flow_id=str(flow["flow_id"]),
            owner=OTHER_OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
            scenario_id="sandbox-approved",
            idempotency_key="attempt:foreign-1",
        )


def test_consume_approval_uses_caller_transaction_and_rolls_back_with_order(
    tmp_path: Path,
) -> None:
    value = backend(tmp_path)
    flow = create_flow(value)
    value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:approve-1",
    )
    with value.lifecycle.connection(transaction=True) as connection:
        connection.execute("CREATE TABLE site_orders(id TEXT PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="order failed"):
        with value.lifecycle.connection(transaction=True) as connection:
            connection.execute("INSERT INTO site_orders(id) VALUES ('order-1')")
            value.payments.consume_approval(
                connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=1299,
                currency="USD",
                fingerprint=FINGERPRINT,
            )
            raise RuntimeError("order failed")

    with value.lifecycle.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM site_orders").fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM websitebench_payment_attempts"
        ).fetchone()[0] == "APPROVED"

    with value.lifecycle.connection(transaction=True) as connection:
        snapshot = value.payments.consume_approval(
            connection,
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
        )
        connection.execute("INSERT INTO site_orders(id) VALUES ('order-1')")
    assert snapshot["is_simulation"] is True


def test_stale_amount_invalidates_approval_and_replay_conflicts(tmp_path: Path) -> None:
    value = backend(tmp_path)
    flow = create_flow(value)
    value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:approve-1",
    )
    with pytest.raises(PaymentRejected, match="stale"):
        value.payments.attempt(
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1300,
            currency="USD",
            fingerprint=FINGERPRINT,
            scenario_id="sandbox-approved",
            idempotency_key="attempt:changed-1",
        )
    with value.lifecycle.connection() as connection:
        assert connection.execute(
            "SELECT status FROM websitebench_payment_flows"
        ).fetchone()[0] == "INVALIDATED"
        assert connection.execute(
            "SELECT status FROM websitebench_payment_attempts"
        ).fetchone()[0] == "SUPERSEDED"

    with pytest.raises(PaymentConflict, match="conflicts"):
        value.payments.create_intent(
            owner=OWNER,
            amount_minor=1400,
            currency="USD",
            fingerprint=FINGERPRINT,
            idempotency_key="create:order-1",
        )


def test_unknown_scenario_secret_fields_and_cross_site_transaction_are_rejected(
    tmp_path: Path,
) -> None:
    alpha = backend(tmp_path, "alpha")
    beta = backend(tmp_path, "beta")
    flow = create_flow(alpha)
    with pytest.raises(PaymentRejected, match="unknown"):
        alpha.payments.attempt(
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
            scenario_id="4242424242424242",
            idempotency_key="attempt:secret-1",
        )
    alpha.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:approve-1",
    )
    with beta.lifecycle.connection(transaction=True) as foreign_connection:
        with pytest.raises(SiteBindingError):
            alpha.payments.consume_approval(
                foreign_connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=1299,
                currency="USD",
                fingerprint=FINGERPRINT,
            )
    with pytest.raises(PaymentError, match="active SQLite transaction"):
        with alpha.lifecycle.connection() as connection:
            alpha.payments.consume_approval(
                connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=1299,
                currency="USD",
                fingerprint=FINGERPRINT,
            )


def test_stripe_test_requires_server_verifier_and_exact_provider_snapshot(
    tmp_path: Path,
) -> None:
    value = SiteBackend.open(
        runtime_config("alpha", stripe=True),
        data_root=tmp_path / "alpha",
    )
    value.lifecycle.initialize()
    flow = value.payments.create_intent(
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        idempotency_key="create:stripe-order-1",
        adapter="stripe-test",
    )
    with pytest.raises(PaymentRejected, match="opaque test Session"):
        value.payments.attempt(
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
            scenario_id="4242424242424242",
            idempotency_key="attempt:stripe-secret",
        )
    with pytest.raises(PaymentRejected, match="provider-verified"):
        value.payments.attempt(
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
            scenario_id="cs_test_verified_12345678",
            idempotency_key="attempt:stripe-unverified",
        )

    session_id = "cs_test_verified_12345678"

    def provider_snapshot(requested_id: str) -> dict[str, object]:
        assert requested_id == session_id
        return {
            "id": session_id,
            "object": "checkout.session",
            "livemode": False,
            "status": "complete",
            "payment_status": "paid",
            "client_reference_id": flow["flow_id"],
            "amount_total": 1299,
            "currency": "usd",
            "metadata": {
                "site_id": "alpha",
                "flow_id": flow["flow_id"],
                "owner": OWNER,
                "amount_minor": "1299",
                "currency": "USD",
                "fingerprint": FINGERPRINT,
                "is_simulation": "true",
            },
        }

    forged = provider_snapshot(session_id)
    forged["amount_total"] = 1
    with pytest.raises(PaymentRejected, match="immutable payment facts"):
        value.payments.attempt_verified_stripe(
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
            provider_session_id=session_id,
            idempotency_key="attempt:stripe-forged",
            provider_verifier=lambda _: forged,
        )

    missing_owner = provider_snapshot(session_id)
    del missing_owner["metadata"]["owner"]
    with pytest.raises(PaymentRejected, match="immutable payment facts"):
        value.payments.attempt_verified_stripe(
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
            provider_session_id=session_id,
            idempotency_key="attempt:stripe-missing-owner",
            provider_verifier=lambda _: missing_owner,
        )

    approved = value.payments.attempt_verified_stripe(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        provider_session_id=session_id,
        idempotency_key="attempt:stripe-approved",
        provider_verifier=provider_snapshot,
    )
    assert approved["status"] == "APPROVED"
    with value.lifecycle.connection(transaction=True) as connection:
        consumed = value.payments.consume_approval(
            connection,
            flow_id=str(flow["flow_id"]),
            owner=OWNER,
            amount_minor=1299,
            currency="USD",
            fingerprint=FINGERPRINT,
        )
    assert consumed["attempt_id"] == approved["attempt_id"]


def test_final_state_mismatch_durably_invalidates_and_restores_transaction(
    tmp_path: Path,
) -> None:
    value = backend(tmp_path)
    flow = create_flow(value)
    value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:approve-final-state",
    )
    with value.lifecycle.connection(transaction=True) as connection:
        connection.execute("CREATE TABLE site_orders(id TEXT PRIMARY KEY)")

    with value.lifecycle.connection(transaction=True) as connection:
        with pytest.raises(PaymentRejected, match="final state"):
            value.payments.consume_approval(
                connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=1299,
                currency="USD",
                fingerprint="b" * 64,
            )
        assert connection.in_transaction

    with value.lifecycle.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM site_orders"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM websitebench_payment_flows"
        ).fetchone()[0] == "INVALIDATED"
        assert connection.execute(
            "SELECT status FROM websitebench_payment_attempts"
        ).fetchone()[0] == "SUPERSEDED"
        assert connection.execute(
            "SELECT event_type FROM websitebench_payment_events "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0] == "APPROVAL_INVALIDATED_FINAL_STATE"

    with value.lifecycle.connection(transaction=True) as connection:
        with pytest.raises(PaymentRejected, match="active approval"):
            value.payments.consume_approval(
                connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=1299,
                currency="USD",
                fingerprint=FINGERPRINT,
            )


def test_consumed_approval_and_order_roll_back_together(tmp_path: Path) -> None:
    value = backend(tmp_path)
    flow = create_flow(value)
    value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:atomic-order",
    )
    with value.lifecycle.connection(transaction=True) as connection:
        connection.execute("CREATE TABLE site_orders(id TEXT PRIMARY KEY)")

    with pytest.raises(RuntimeError, match="order write failed"):
        with value.lifecycle.connection(transaction=True) as connection:
            value.payments.consume_approval(
                connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=1299,
                currency="USD",
                fingerprint=FINGERPRINT,
            )
            connection.execute(
                "INSERT INTO site_orders(id) VALUES ('must-rollback')"
            )
            raise RuntimeError("order write failed")

    with value.lifecycle.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM site_orders"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM websitebench_payment_flows"
        ).fetchone()[0] == "APPROVED"
        assert connection.execute(
            "SELECT status FROM websitebench_payment_attempts"
        ).fetchone()[0] == "APPROVED"
        assert connection.execute(
            "SELECT COUNT(*) FROM websitebench_payment_events "
            "WHERE event_type='APPROVAL_CONSUMED'"
        ).fetchone()[0] == 0


def test_stale_invalidation_has_no_concurrent_consume_window(
    tmp_path: Path,
) -> None:
    value = backend(tmp_path)
    flow = create_flow(value)
    value.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=1299,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:concurrent-final-state",
    )
    invalidation_committed = threading.Event()
    release_stale_connection = threading.Event()
    stale_errors: list[BaseException] = []

    class PauseAfterCommitConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            result = super().execute(sql, parameters)
            if sql == "COMMIT":
                invalidation_committed.set()
                if not release_stale_connection.wait(timeout=5):
                    raise AssertionError("concurrent consumer did not finish")
            return result

    def reject_stale_state() -> None:
        connection = sqlite3.connect(
            value.lifecycle.database_path,
            timeout=5,
            check_same_thread=False,
            factory=PauseAfterCommitConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(PaymentRejected, match="final state"):
                value.payments.consume_approval(
                    connection,
                    flow_id=str(flow["flow_id"]),
                    owner=OWNER,
                    amount_minor=1299,
                    currency="USD",
                    fingerprint="b" * 64,
                )
            assert connection.in_transaction
        except BaseException as exc:
            stale_errors.append(exc)
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    stale_thread = threading.Thread(target=reject_stale_state)
    stale_thread.start()
    assert invalidation_committed.wait(timeout=5)
    try:
        with value.lifecycle.connection(transaction=True) as connection:
            with pytest.raises(PaymentRejected, match="active approval"):
                value.payments.consume_approval(
                    connection,
                    flow_id=str(flow["flow_id"]),
                    owner=OWNER,
                    amount_minor=1299,
                    currency="USD",
                    fingerprint=FINGERPRINT,
                )
    finally:
        release_stale_connection.set()
        stale_thread.join(timeout=5)

    assert not stale_thread.is_alive()
    assert stale_errors == []
    with value.lifecycle.connection() as connection:
        assert connection.execute(
            "SELECT status FROM websitebench_payment_flows"
        ).fetchone()[0] == "INVALIDATED"
        assert connection.execute(
            "SELECT COUNT(*) FROM websitebench_payment_events "
            "WHERE event_type='APPROVAL_CONSUMED'"
        ).fetchone()[0] == 0
