from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest


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
