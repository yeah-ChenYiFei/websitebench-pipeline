"""Coursera clone-local checkout and order domain."""

from __future__ import annotations

import sqlite3
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
