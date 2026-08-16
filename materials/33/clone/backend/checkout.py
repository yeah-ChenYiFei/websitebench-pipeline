"""Coursera clone-local checkout and order domain."""

from __future__ import annotations

import sqlite3
import secrets
from typing import Any


COURSE_ID = "deep-learning-specialization"
PLAN_ID = "deep-learning-specialization-paid"
PLAN_LABEL = "Deep Learning Specialization paid plan"
PRICING_EVIDENCE = "inferred-no-authenticated-checkout-evidence"
CURRENCY = "USD"
SUBTOTAL_MINOR = 4900
TAX_MINOR = 0
TOTAL_MINOR = 4900
PLAN_FINGERPRINT = (
    "94b7b58e2a6fc0b45b7aae588169b477"
    "56a0dd1a8cc84a3ca672216a24676b76"
)
FROZEN_TIME = "2026-08-16T00:00:00Z"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS coursera_checkout_drafts (
        draft_id TEXT PRIMARY KEY,
        owner_subject_id TEXT NOT NULL,
        course_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        plan_label TEXT NOT NULL,
        subtotal_minor INTEGER NOT NULL,
        tax_minor INTEGER NOT NULL,
        total_minor INTEGER NOT NULL,
        currency TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        payment_flow_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK(status IN ('OPEN','COMPLETED','CANCELED')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS coursera_orders (
        order_id TEXT PRIMARY KEY,
        owner_subject_id TEXT NOT NULL,
        draft_id TEXT NOT NULL UNIQUE REFERENCES coursera_checkout_drafts(draft_id),
        payment_flow_id TEXT NOT NULL UNIQUE,
        enrollment_id INTEGER NOT NULL REFERENCES coursera_enrollments(enrollment_id),
        course_id TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        plan_label TEXT NOT NULL,
        subtotal_minor INTEGER NOT NULL,
        tax_minor INTEGER NOT NULL,
        total_minor INTEGER NOT NULL,
        currency TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PAID','CANCELED')),
        created_at TEXT NOT NULL,
        canceled_at TEXT
    )""",
)


def migrate(connection: sqlite3.Connection) -> None:
    """Install checkout tables in the caller's site migration transaction."""

    for statement in _SCHEMA:
        connection.execute(statement)


def plan() -> dict[str, Any]:
    """Return a copy of the one current server-owned plan."""

    return {
        "course_id": COURSE_ID,
        "currency": CURRENCY,
        "fingerprint": PLAN_FINGERPRINT,
        "plan_id": PLAN_ID,
        "plan_label": PLAN_LABEL,
        "pricing_evidence": PRICING_EVIDENCE,
        "subtotal_minor": SUBTOTAL_MINOR,
        "tax_minor": TAX_MINOR,
        "total_minor": TOTAL_MINOR,
    }


def _draft_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def create_draft(
    owner: str,
    *,
    course_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Create one owner-bound draft and generated sandbox payment flow."""

    if course_id != COURSE_ID or plan_id != PLAN_ID:
        raise ValueError("plan is unavailable")

    from backend import learning_db

    backend, _auth = learning_db.services()
    draft_id = f"checkout_{secrets.token_urlsafe(18)}"
    with learning_db.connection(transaction=True) as opened:
        owner_exists = opened.execute(
            "SELECT 1 FROM coursera_profiles WHERE subject_id=?", (owner,)
        ).fetchone()
        if owner_exists is None:
            raise LookupError("Learner not found")
        flow = backend.payments.create_intent(
            owner=owner,
            amount_minor=TOTAL_MINOR,
            currency=CURRENCY,
            fingerprint=PLAN_FINGERPRINT,
            idempotency_key=f"draft-create:{draft_id}",
            adapter="local-sandbox",
            connection=opened,
        )
        opened.execute(
            """INSERT INTO coursera_checkout_drafts(
                draft_id,owner_subject_id,course_id,plan_id,plan_label,
                subtotal_minor,tax_minor,total_minor,currency,fingerprint,
                payment_flow_id,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?)""",
            (
                draft_id,
                owner,
                COURSE_ID,
                PLAN_ID,
                PLAN_LABEL,
                SUBTOTAL_MINOR,
                TAX_MINOR,
                TOTAL_MINOR,
                CURRENCY,
                PLAN_FINGERPRINT,
                flow["flow_id"],
                FROZEN_TIME,
                FROZEN_TIME,
            ),
        )
        row = opened.execute(
            "SELECT * FROM coursera_checkout_drafts WHERE draft_id=?",
            (draft_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - insert invariant
            raise RuntimeError("checkout draft insert returned no row")
        return _draft_dict(row)


def get_draft(owner: str, draft_id: str) -> dict[str, Any]:
    """Read one checkout draft without revealing foreign records."""

    from backend import learning_db

    with learning_db.connection() as opened:
        row = opened.execute(
            """SELECT * FROM coursera_checkout_drafts
                WHERE draft_id=? AND owner_subject_id=?""",
            (draft_id, owner),
        ).fetchone()
    if row is None:
        raise LookupError("Checkout not found")
    return _draft_dict(row)
