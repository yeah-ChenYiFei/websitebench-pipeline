from __future__ import annotations

import importlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest
from websitebench.site_backend import PaymentConflict, PaymentRejected


@pytest.fixture
def checkout_site(tmp_path: Path, monkeypatch):
    database = tmp_path / "33.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    learning = importlib.import_module("backend.learning_db")
    checkout = importlib.import_module("backend.checkout")
    learning.close_services()
    backend, _auth = learning.services()
    yield checkout, learning, backend
    learning.close_services()


def test_checkout_schema_exposes_the_frozen_inferred_plan(
    checkout_site,
) -> None:
    """Catch a missing checkout migration or drifted server-owned plan facts."""

    _checkout, learning, _backend = checkout_site

    checkout_spec = importlib.util.find_spec("backend.checkout")
    assert checkout_spec is not None, "backend.checkout must own checkout state"
    checkout = importlib.import_module("backend.checkout")

    assert checkout.plan() == {
        "course_id": "deep-learning-specialization",
        "currency": "USD",
        "fingerprint": (
            "94b7b58e2a6fc0b45b7aae588169b477"
            "56a0dd1a8cc84a3ca672216a24676b76"
        ),
        "plan_id": "deep-learning-specialization-paid",
        "plan_label": "Deep Learning Specialization paid plan",
        "pricing_evidence": "inferred-no-authenticated-checkout-evidence",
        "subtotal_minor": 4900,
        "tax_minor": 0,
        "total_minor": 4900,
    }

    with learning.connection() as opened:
        tables = {
            row[0]
            for row in opened.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"coursera_checkout_drafts", "coursera_orders"} <= tables


def test_create_draft_binds_owner_and_frozen_facts_to_generated_payment(
    checkout_site,
) -> None:
    """Catch missing or client-controlled facts in payment intent creation."""

    checkout, learning, _backend = checkout_site
    draft = checkout.create_draft(
        "learner-empty",
        course_id="deep-learning-specialization",
        plan_id="deep-learning-specialization-paid",
    )

    assert draft["owner_subject_id"] == "learner-empty"
    assert draft["status"] == "OPEN"
    assert draft["total_minor"] == 4900
    assert draft["currency"] == "USD"
    assert draft["fingerprint"] == (
        "94b7b58e2a6fc0b45b7aae588169b477"
        "56a0dd1a8cc84a3ca672216a24676b76"
    )
    assert draft["draft_id"].startswith("checkout_")
    assert draft["payment_flow_id"].startswith("payflow_")

    with learning.connection() as opened:
        flow = opened.execute(
            """SELECT owner,amount_minor,currency,fingerprint,adapter,status
                FROM websitebench_payment_flows WHERE flow_id=?""",
            (draft["payment_flow_id"],),
        ).fetchone()
    assert tuple(flow) == (
        "learner-empty",
        4900,
        "USD",
        (
            "94b7b58e2a6fc0b45b7aae588169b477"
            "56a0dd1a8cc84a3ca672216a24676b76"
        ),
        "local-sandbox",
        "OPEN",
    )


@pytest.mark.parametrize(
    ("course_id", "plan_id"),
    [
        ("different-course", "deep-learning-specialization-paid"),
        ("deep-learning-specialization", "different-plan"),
    ],
)
def test_create_draft_rejects_unsupported_plan_without_payment_side_effects(
    checkout_site,
    course_id: str,
    plan_id: str,
) -> None:
    """Catch validation that creates payment state before rejecting the plan."""

    checkout, learning, _backend = checkout_site
    with pytest.raises(ValueError, match="plan is unavailable"):
        checkout.create_draft(
            "learner-empty", course_id=course_id, plan_id=plan_id
        )

    with learning.connection() as opened:
        assert opened.execute(
            "SELECT COUNT(*) FROM coursera_checkout_drafts"
        ).fetchone()[0] == 0
        assert opened.execute(
            "SELECT COUNT(*) FROM websitebench_payment_flows"
        ).fetchone()[0] == 0


def test_get_draft_hides_foreign_owner_records(checkout_site) -> None:
    """Catch a draft lookup that leaks another learner's checkout state."""

    checkout, _learning, _backend = checkout_site
    draft = checkout.create_draft(
        "learner-empty",
        course_id="deep-learning-specialization",
        plan_id="deep-learning-specialization-paid",
    )

    with pytest.raises(LookupError, match="Checkout not found"):
        checkout.get_draft("learner-in-progress", draft["draft_id"])
    assert checkout.get_draft("learner-empty", draft["draft_id"]) == draft


def _new_empty_learner_draft(checkout):
    return checkout.create_draft(
        "learner-empty",
        course_id="deep-learning-specialization",
        plan_id="deep-learning-specialization-paid",
    )


def test_approved_attempt_atomically_creates_paid_order_and_enrollment(
    checkout_site,
) -> None:
    """Catch approval consumption without the matching order/enrollment write."""

    checkout, learning, _backend = checkout_site
    draft = _new_empty_learner_draft(checkout)

    result = checkout.attempt(
        "learner-empty",
        draft["draft_id"],
        scenario_id="sandbox-approved",
        idempotency_key="attempt-approved-001",
    )

    assert result["outcome"] == "approved"
    assert result["attempt"]["status"] == "APPROVED"
    assert result["order"] == checkout.get_order(
        "learner-empty", result["order"]["order_id"]
    )
    assert result["order"]["status"] == "PAID"
    assert result["order"]["subtotal_minor"] == 4900
    assert result["order"]["tax_minor"] == 0
    assert result["order"]["total_minor"] == 4900
    assert checkout.list_orders("learner-empty") == [result["order"]]

    with learning.connection() as opened:
        enrollment = opened.execute(
            """SELECT owner_subject_id,course_id,track,status
                FROM coursera_enrollments WHERE enrollment_id=?""",
            (result["order"]["enrollment_id"],),
        ).fetchone()
        flow_status = opened.execute(
            "SELECT status FROM websitebench_payment_flows WHERE flow_id=?",
            (draft["payment_flow_id"],),
        ).fetchone()[0]
    assert tuple(enrollment) == (
        "learner-empty",
        "deep-learning-specialization",
        "paid",
        "active",
    )
    assert flow_status == "CONSUMED"


@pytest.mark.parametrize(
    ("scenario_id", "expected_outcome", "expected_status"),
    [
        ("sandbox-declined", "declined", "DECLINED"),
        ("sandbox-retry", "retryable", "RETRYABLE"),
    ],
)
def test_nonapproved_attempt_is_idempotent_without_business_state(
    checkout_site,
    scenario_id: str,
    expected_outcome: str,
    expected_status: str,
) -> None:
    """Catch decline/retry paths that create orders or paid enrollments."""

    checkout, learning, _backend = checkout_site
    draft = _new_empty_learner_draft(checkout)

    first = checkout.attempt(
        "learner-empty",
        draft["draft_id"],
        scenario_id=scenario_id,
        idempotency_key="attempt-nonapproved-001",
    )
    repeated = checkout.attempt(
        "learner-empty",
        draft["draft_id"],
        scenario_id=scenario_id,
        idempotency_key="attempt-nonapproved-001",
    )

    assert first == repeated
    assert first["outcome"] == expected_outcome
    assert first["attempt"]["status"] == expected_status
    assert first["order"] is None
    assert checkout.list_orders("learner-empty") == []
    with learning.connection() as opened:
        assert opened.execute(
            """SELECT COUNT(*) FROM coursera_enrollments
                WHERE owner_subject_id='learner-empty'"""
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("column", "stale_value"),
    [
        ("total_minor", 5000),
        ("fingerprint", "0" * 64),
    ],
)
def test_final_submit_rejects_stale_server_stored_draft_facts(
    checkout_site,
    column: str,
    stale_value,
) -> None:
    """Catch final submit that trusts a stale draft over the current plan."""

    checkout, learning, _backend = checkout_site
    draft = _new_empty_learner_draft(checkout)
    with learning.connection(transaction=True) as opened:
        opened.execute(
            f"UPDATE coursera_checkout_drafts SET {column}=? WHERE draft_id=?",
            (stale_value, draft["draft_id"]),
        )

    with pytest.raises(PaymentRejected, match="checkout facts are stale"):
        checkout.attempt(
            "learner-empty",
            draft["draft_id"],
            scenario_id="sandbox-approved",
            idempotency_key="attempt-stale-draft-001",
        )

    with learning.connection() as opened:
        assert opened.execute(
            "SELECT COUNT(*) FROM websitebench_payment_attempts"
        ).fetchone()[0] == 0
        assert opened.execute(
            "SELECT COUNT(*) FROM coursera_orders"
        ).fetchone()[0] == 0
        assert opened.execute(
            """SELECT COUNT(*) FROM coursera_enrollments
                WHERE owner_subject_id='learner-empty'"""
        ).fetchone()[0] == 0


def test_generated_flow_staleness_and_foreign_owner_are_rejected(
    checkout_site,
) -> None:
    """Catch final submit that bypasses generated stale/owner validation."""

    checkout, learning, _backend = checkout_site
    draft = _new_empty_learner_draft(checkout)
    with pytest.raises(LookupError, match="Checkout not found"):
        checkout.attempt(
            "learner-in-progress",
            draft["draft_id"],
            scenario_id="sandbox-approved",
            idempotency_key="attempt-foreign-001",
        )

    with learning.connection(transaction=True) as opened:
        opened.execute(
            """UPDATE websitebench_payment_flows SET fingerprint=?
                WHERE flow_id=?""",
            ("f" * 64, draft["payment_flow_id"]),
        )
    with pytest.raises(PaymentRejected, match="payment facts are stale"):
        checkout.attempt(
            "learner-empty",
            draft["draft_id"],
            scenario_id="sandbox-approved",
            idempotency_key="attempt-stale-flow-001",
        )


def test_attempt_idempotency_conflict_and_duplicate_consumption_are_rejected(
    checkout_site,
) -> None:
    """Catch key reuse across scenarios or a second order from one approval."""

    checkout, _learning, _backend = checkout_site
    declined_draft = _new_empty_learner_draft(checkout)
    checkout.attempt(
        "learner-empty",
        declined_draft["draft_id"],
        scenario_id="sandbox-declined",
        idempotency_key="attempt-conflict-001",
    )
    with pytest.raises(PaymentConflict, match="idempotency key conflicts"):
        checkout.attempt(
            "learner-empty",
            declined_draft["draft_id"],
            scenario_id="sandbox-retry",
            idempotency_key="attempt-conflict-001",
        )

    approved_draft = _new_empty_learner_draft(checkout)
    checkout.attempt(
        "learner-empty",
        approved_draft["draft_id"],
        scenario_id="sandbox-approved",
        idempotency_key="attempt-consume-once-001",
    )
    with pytest.raises(PaymentRejected, match="no longer open"):
        checkout.attempt(
            "learner-empty",
            approved_draft["draft_id"],
            scenario_id="sandbox-approved",
            idempotency_key="attempt-consume-twice-002",
        )


def test_order_insert_failure_rolls_back_approval_and_enrollment(
    checkout_site,
) -> None:
    """Catch a transaction boundary that consumes approval before order commit."""

    checkout, learning, _backend = checkout_site
    draft = _new_empty_learner_draft(checkout)
    with learning.connection(transaction=True) as opened:
        opened.execute(
            """CREATE TRIGGER force_order_failure
                BEFORE INSERT ON coursera_orders
                BEGIN SELECT RAISE(ABORT,'forced order failure'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced order failure"):
        checkout.attempt(
            "learner-empty",
            draft["draft_id"],
            scenario_id="sandbox-approved",
            idempotency_key="attempt-atomic-rollback-001",
        )

    with learning.connection() as opened:
        flow_status = opened.execute(
            "SELECT status FROM websitebench_payment_flows WHERE flow_id=?",
            (draft["payment_flow_id"],),
        ).fetchone()[0]
        assert opened.execute(
            "SELECT COUNT(*) FROM websitebench_payment_attempts"
        ).fetchone()[0] == 0
        assert opened.execute(
            "SELECT COUNT(*) FROM coursera_orders"
        ).fetchone()[0] == 0
        assert opened.execute(
            """SELECT COUNT(*) FROM coursera_enrollments
                WHERE owner_subject_id='learner-empty'"""
        ).fetchone()[0] == 0
    assert flow_status == "OPEN"


def test_paid_enrollment_cannot_bypass_checkout(checkout_site) -> None:
    """Catch the legacy enrollment helper creating paid state without approval."""

    _checkout, learning, _backend = checkout_site
    with pytest.raises(ValueError, match="paid enrollment requires checkout"):
        learning.enroll(
            "learner-empty",
            course_id="deep-learning-specialization",
            track="paid",
        )
    assert learning.list_enrollments("learner-empty") == []


def _approved_empty_learner_order(checkout):
    draft = _new_empty_learner_draft(checkout)
    result = checkout.attempt(
        "learner-empty",
        draft["draft_id"],
        scenario_id="sandbox-approved",
        idempotency_key=f"approved-for-{draft['draft_id']}",
    )
    return result["order"]


def test_cancel_order_retains_snapshot_and_cancels_paid_enrollment(
    checkout_site,
) -> None:
    """Catch cancellation that deletes history or leaves paid access active."""

    checkout, learning, _backend = checkout_site
    order = _approved_empty_learner_order(checkout)

    canceled = checkout.cancel_order("learner-empty", order["order_id"])
    canceled_again = checkout.cancel_order("learner-empty", order["order_id"])

    assert canceled_again == canceled
    assert canceled["status"] == "CANCELED"
    assert canceled["canceled_at"] == "2026-08-16T00:00:00Z"
    assert canceled["subtotal_minor"] == 4900
    assert canceled["tax_minor"] == 0
    assert canceled["total_minor"] == 4900
    assert checkout.list_orders("learner-empty") == [canceled]
    with learning.connection() as opened:
        enrollment = opened.execute(
            """SELECT status,canceled_at FROM coursera_enrollments
                WHERE enrollment_id=?""",
            (order["enrollment_id"],),
        ).fetchone()
    assert tuple(enrollment) == ("canceled", "2026-08-16T00:00:00Z")

    with pytest.raises(LookupError, match="Order not found"):
        checkout.cancel_order("learner-in-progress", order["order_id"])
    with pytest.raises(LookupError, match="Order not found"):
        checkout.get_order("learner-in-progress", order["order_id"])


def test_cancel_order_rolls_back_if_enrollment_update_fails(checkout_site) -> None:
    """Catch order cancellation committing before its enrollment transition."""

    checkout, learning, _backend = checkout_site
    order = _approved_empty_learner_order(checkout)
    with learning.connection(transaction=True) as opened:
        opened.execute(
            """CREATE TRIGGER force_enrollment_cancel_failure
                BEFORE UPDATE OF status ON coursera_enrollments
                BEGIN SELECT RAISE(ABORT,'forced enrollment failure'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced enrollment failure"):
        checkout.cancel_order("learner-empty", order["order_id"])

    assert checkout.get_order("learner-empty", order["order_id"])["status"] == "PAID"
    with learning.connection() as opened:
        assert opened.execute(
            """SELECT status FROM coursera_enrollments
                WHERE enrollment_id=?""",
            (order["enrollment_id"],),
        ).fetchone()[0] == "active"


def test_order_persists_across_restart_and_reset_clears_checkout_state(
    checkout_site,
) -> None:
    """Catch volatile order state or reset that inherits a prior checkout."""

    checkout, learning, _backend = checkout_site
    order = _approved_empty_learner_order(checkout)
    learning.close_services()

    assert checkout.get_order("learner-empty", order["order_id"]) == order
    before_reset = learning.state_snapshot()
    assert len(before_reset["checkout_drafts"]) == 1
    assert len(before_reset["orders"]) == 1

    learning.reset()
    assert checkout.list_orders("learner-empty") == []
    after_reset = learning.state_snapshot()
    assert after_reset["checkout_drafts"] == []
    assert after_reset["orders"] == []
    learning.reset()
    assert learning.state_snapshot() == after_reset
