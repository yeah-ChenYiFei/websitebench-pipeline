from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def test_checkout_schema_exposes_the_frozen_inferred_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Catch a missing checkout migration or drifted server-owned plan facts."""

    database = tmp_path / "33.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    learning = importlib.import_module("backend.learning_db")
    learning.close_services()
    learning.services()

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
    learning.close_services()
