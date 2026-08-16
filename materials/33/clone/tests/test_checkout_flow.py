from __future__ import annotations

import importlib
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app


class _InputCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str | None]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "input":
            self.inputs.append(dict(attrs))


@pytest.fixture
def checkout_client(tmp_path: Path, monkeypatch):
    database = tmp_path / "33.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    learning = importlib.import_module("backend.learning_db")
    learning.close_services()
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        yield client
    learning.close_services()


def _login_empty(client: TestClient) -> None:
    client.get("/login")
    response = client.post(
        "/auth/login",
        data={
            "email": "empty@coursera.test",
            "password": "Empty-Learner-33",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _create_browser_draft(client: TestClient) -> str:
    response = client.post(
        "/checkout/deep-learning",
        data={
            "course_id": "deep-learning-specialization",
            "plan_id": "deep-learning-specialization-paid",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert re.fullmatch(r"/checkout/checkout_[^/]+/payment", response.headers["location"])
    return response.headers["location"].split("/")[2]


def test_public_entry_and_authenticated_plan_show_inferred_totals(
    checkout_client: TestClient,
) -> None:
    """Catch a paid entry that bypasses auth or hides inferred pricing."""

    anonymous = checkout_client.get("/specializations/deep-learning")
    assert anonymous.status_code == 200
    assert "Sign in locally to choose the inferred paid plan" in anonymous.text
    assert 'href="/login?next=/checkout/deep-learning"' in anonymous.text
    signed_out_plan = checkout_client.get("/checkout/deep-learning")
    assert signed_out_plan.status_code == 401

    _login_empty(checkout_client)
    specialization = checkout_client.get("/specializations/deep-learning")
    assert 'href="/checkout/deep-learning"' in specialization.text
    plan = checkout_client.get("/checkout/deep-learning")
    assert plan.status_code == 200
    assert "Inferred local price" in plan.text
    assert "Subtotal" in plan.text and "USD 49.00" in plan.text
    assert "Tax" in plan.text and "USD 0.00" in plan.text
    assert "Total" in plan.text and plan.text.count("USD 49.00") >= 2
    assert "No real purchase or payment will occur" in plan.text
    assert 'action="/checkout/deep-learning"' in plan.text


def test_payment_fields_are_memory_only_and_review_submits_two_safe_keys(
    checkout_client: TestClient,
) -> None:
    """Catch payment-looking controls becoming submitted browser fields."""

    _login_empty(checkout_client)
    draft_id = _create_browser_draft(checkout_client)
    payment = checkout_client.get(f"/checkout/{draft_id}/payment")
    assert payment.status_code == 200
    assert "Synthetic payment form" in payment.text
    assert "stays only in this browser page" in payment.text
    collector = _InputCollector()
    collector.feed(payment.text)
    payment_inputs = {
        item["id"]: item
        for item in collector.inputs
        if item.get("id") in {"synthetic-card-number", "synthetic-expiry", "synthetic-cvv"}
    }
    assert set(payment_inputs) == {
        "synthetic-card-number",
        "synthetic-expiry",
        "synthetic-cvv",
    }
    assert all("name" not in item for item in payment_inputs.values())
    assert f'action="/checkout/{draft_id}/review"' in payment.text
    assert 'method="get"' in payment.text

    review = checkout_client.get(f"/checkout/{draft_id}/review")
    assert review.status_code == 200
    assert "Review inferred total" in review.text
    assert "Subtotal" in review.text and "USD 49.00" in review.text
    assert "Tax" in review.text and "USD 0.00" in review.text
    assert "sandbox-approved" in review.text
    assert "sandbox-declined" in review.text
    assert "sandbox-retry" in review.text
    assert 'name="scenario_id"' in review.text
    assert 'name="idempotency_key"' in review.text
    assert "card_number" not in review.text


@pytest.mark.parametrize(
    "body",
    [
        "scenario_id=sandbox-declined",
        "idempotency_key=browser-attempt-001",
        "scenario_id=sandbox-declined&idempotency_key=browser-attempt-001&card_number=4111111111111111",
        "scenario_id=sandbox-declined&scenario_id=sandbox-retry&idempotency_key=browser-attempt-001",
        "scenario_id=sandbox-declined&idempotency_key=browser-attempt-001&idempotency_key=browser-attempt-002",
    ],
)
def test_attempt_endpoint_rejects_any_body_except_exactly_two_safe_keys(
    checkout_client: TestClient,
    body: str,
) -> None:
    """Catch missing, duplicate, extra, or sensitive attempt fields."""

    _login_empty(checkout_client)
    draft_id = _create_browser_draft(checkout_client)
    response = checkout_client.post(
        f"/checkout/{draft_id}/attempt",
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "exactly scenario_id and idempotency_key" in response.text


def test_browser_attempt_maps_decline_retry_and_approval_results(
    checkout_client: TestClient,
) -> None:
    """Catch sandbox outcomes being merged or approval losing its order path."""

    _login_empty(checkout_client)
    for scenario, expected in (
        ("sandbox-declined", "Simulated payment declined"),
        ("sandbox-retry", "Simulated payment needs a retry"),
    ):
        draft_id = _create_browser_draft(checkout_client)
        result = checkout_client.post(
            f"/checkout/{draft_id}/attempt",
            data={
                "scenario_id": scenario,
                "idempotency_key": f"browser-{scenario}-001",
            },
            follow_redirects=False,
        )
        assert result.status_code == 200
        assert expected in result.text
        assert f'href="/checkout/{draft_id}/review"' in result.text
        assert 'href="/specializations/deep-learning"' in result.text

    approved_id = _create_browser_draft(checkout_client)
    approved = checkout_client.post(
        f"/checkout/{approved_id}/attempt",
        data={
            "scenario_id": "sandbox-approved",
            "idempotency_key": "browser-approved-001",
        },
        follow_redirects=False,
    )
    assert approved.status_code == 303
    assert re.fullmatch(r"/orders/order_[^/]+", approved.headers["location"])
