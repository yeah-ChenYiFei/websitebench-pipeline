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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
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


def _login_progress(client: TestClient) -> None:
    client.get("/login")
    response = client.post(
        "/auth/login",
        data={
            "email": "progress@coursera.test",
            "password": "Progress-Learner-33",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _create_browser_draft(client: TestClient) -> str:
    response = client.post(
        "/checkout/deep-learning",
        data={
            "course_id": "deep-learning-specialization",
            "plan_id": "deep-learning-specialization-trial",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert re.fullmatch(
        r"/checkout/checkout_[^/]+/payment", response.headers["location"]
    )
    return response.headers["location"].split("/")[2]


def test_diagnostic_session_requires_ephemeral_token_and_authenticates_alias(
    checkout_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch the verifier fixture accepting requests without its minted token."""

    token = "round2-ephemeral-verifier-token-0001"
    monkeypatch.setenv("WEBSITEBENCH_VERIFY_SESSION_TOKEN", token)
    endpoint = "/__websitebench/session"
    form = {"account": "empty-learner"}

    missing = checkout_client.post(endpoint, data=form)
    wrong = checkout_client.post(
        endpoint,
        data=form,
        headers={"X-WebsiteBench-Verify-Token": "wrong-token"},
    )
    unknown = checkout_client.post(
        endpoint,
        data={"account": "unknown"},
        headers={"X-WebsiteBench-Verify-Token": token},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert unknown.status_code == 400

    opened = checkout_client.post(
        endpoint,
        data=form,
        headers={"X-WebsiteBench-Verify-Token": token},
    )
    assert opened.status_code == 204
    checkout = checkout_client.get("/checkout/deep-learning")
    assert checkout.status_code == 200
    assert "Start your 7-day free trial" in checkout.text


def test_compatibility_session_still_reaches_historical_learning_states(
    checkout_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch current scope cleanup deleting historical clone compatibility behavior."""

    token = "final-wave-ephemeral-verifier-token"
    monkeypatch.setenv("WEBSITEBENCH_VERIFY_SESSION_TOKEN", token)
    opened = checkout_client.post(
        "/__websitebench/session",
        data={"account": "progress-learner"},
        headers={"X-WebsiteBench-Verify-Token": token},
    )
    assert opened.status_code == 204

    expected = {
        "/my-learning": (200, "<h1>My Learning</h1>"),
        "/learn/neural-networks-deep-learning/lesson/lesson-optimization": (
            200,
            "<h1>Optimization methods</h1>",
        ),
        "/account/history": (200, "<h1>Enrollment history</h1>"),
        "/account/preferences": (200, "<h1>Learning preferences</h1>"),
    }
    for route, (status, marker) in expected.items():
        response = checkout_client.get(route)
        assert response.status_code == status, route
        assert marker in response.text, route

    lesson = checkout_client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-optimization"
    )
    assert 'action="/learning/quizzes/quiz-improving-networks"' in lesson.text
    feedback = checkout_client.post(
        "/learning/quizzes/quiz-improving-networks",
        data={"answer": "Regularization"},
    )
    assert feedback.status_code == 200
    assert "<h1>Quiz score: 100</h1>" in feedback.text


def test_public_entry_and_authenticated_plan_show_observed_trial_totals(
    checkout_client: TestClient,
) -> None:
    """Catch a paid entry that bypasses auth or hides inferred pricing."""

    anonymous = checkout_client.get("/specializations/deep-learning")
    assert anonymous.status_code == 200
    assert "Enroll for free" in anonymous.text
    assert 'data-enrollment-login-open' in anonymous.text
    assert 'name="next" value="/checkout/deep-learning"' in anonymous.text
    signed_out_plan = checkout_client.get("/checkout/deep-learning")
    assert signed_out_plan.status_code == 401

    _login_empty(checkout_client)
    specialization = checkout_client.get("/specializations/deep-learning")
    assert 'href="/checkout/deep-learning"' in specialization.text
    plan = checkout_client.get("/checkout/deep-learning")
    assert plan.status_code == 200
    assert "Start your 7-day free trial" in plan.text
    assert "Then ¥196/month" in plan.text
    assert "Due today" in plan.text and "¥0" in plan.text
    assert "Total due today: ¥0" in plan.text
    assert "No real payment data is submitted" in plan.text
    assert 'action="/checkout/deep-learning"' in plan.text


def test_checkout_entry_matches_observed_source_payment_layout_in_english(
    checkout_client: TestClient,
) -> None:
    """Catch the checkout entry drifting away from the captured Coursera layout."""

    _login_empty(checkout_client)

    html = checkout_client.get("/checkout/deep-learning").text

    assert 'class="source-checkout-shell"' in html
    assert "<h1>Checkout</h1>" in html
    assert "All fields are required" in html
    assert "Billing information" in html
    assert "Payment method" in html
    assert "Card" in html
    assert "PayPal" in html
    assert 'placeholder="Card number"' in html
    assert "1234 1234 1234 1234" not in html
    assert "Deep Learning" in html
    assert "Provided by DeepLearning.AI" in html
    assert "No contracts. Cancel anytime." in html
    assert "7-day free trial" in html
    assert "Then ¥196/month" in html
    assert "Total due today: ¥0" in html

    collector = _InputCollector()
    collector.feed(html)
    payment_inputs = {
        item["id"]: item
        for item in collector.inputs
        if item.get("id")
        in {"synthetic-card-number", "synthetic-expiry", "synthetic-cvv"}
    }
    assert set(payment_inputs) == {
        "synthetic-card-number",
        "synthetic-expiry",
        "synthetic-cvv",
    }
    assert all("name" not in item for item in payment_inputs.values())


def test_checkout_entry_uses_observed_minimal_checkout_chrome(
    checkout_client: TestClient,
) -> None:
    """Catch the checkout page using the catalog header instead of checkout chrome."""

    _login_empty(checkout_client)

    html = checkout_client.get("/checkout/deep-learning").text

    assert "checkout-page" in html
    assert 'class="source-checkout-header"' in html
    assert 'class="source-checkout-avatar"' in html
    assert 'class="wb-audience-bar"' not in html
    assert 'class="wb-search"' not in html
    assert 'class="wb-footer"' not in html


def test_payment_fields_are_memory_only_and_review_submits_two_safe_keys(
    checkout_client: TestClient,
) -> None:
    """Catch payment-looking controls becoming submitted browser fields."""

    _login_empty(checkout_client)
    draft_id = _create_browser_draft(checkout_client)
    payment = checkout_client.get(f"/checkout/{draft_id}/payment")
    assert payment.status_code == 200
    assert "Payment method" in payment.text
    assert "remain only in this browser page" in payment.text
    collector = _InputCollector()
    collector.feed(payment.text)
    payment_inputs = {
        item["id"]: item
        for item in collector.inputs
        if item.get("id")
        in {"synthetic-card-number", "synthetic-expiry", "synthetic-cvv"}
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
    assert "Confirm free trial" in review.text
    assert "Then ¥196/month" in review.text and "Total due today: ¥0" in review.text
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
        "scenario_id=sandbox-declined&idempotency_key=browser-attempt-001&card_number=synthetic-card-value",
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
        ("sandbox-declined", "Sandbox payment declined"),
        ("sandbox-retry", "Sandbox payment needs another try"),
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

    replay = checkout_client.post(
        f"/checkout/{approved_id}/attempt",
        data={
            "scenario_id": "sandbox-approved",
            "idempotency_key": "browser-approved-001",
        },
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert replay.headers["location"] == approved.headers["location"]


def test_order_history_detail_cancel_and_foreign_owner_boundaries(
    checkout_client: TestClient,
) -> None:
    """Catch order pages that hide history or expose it to another learner."""

    _login_empty(checkout_client)
    draft_id = _create_browser_draft(checkout_client)
    approved = checkout_client.post(
        f"/checkout/{draft_id}/attempt",
        data={
            "scenario_id": "sandbox-approved",
            "idempotency_key": "browser-history-approved-001",
        },
        follow_redirects=False,
    )
    order_path = approved.headers["location"]
    order_id = order_path.rsplit("/", 1)[1]

    history = checkout_client.get("/orders")
    detail = checkout_client.get(order_path)
    assert history.status_code == detail.status_code == 200
    assert order_id in history.text
    assert 'data-order-status="PAID"' in history.text
    assert order_id in detail.text
    assert "Paid" in detail.text
    assert "Then ¥196/month" in detail.text and "Total due today: ¥0" in detail.text
    assert 'href="/specializations/deep-learning"' in detail.text
    assert 'href="/orders"' in detail.text

    with TestClient(app, base_url="https://33.offline.invalid") as foreign:
        _login_progress(foreign)
        foreign_detail = foreign.get(order_path)
        foreign_history = foreign.get("/orders")
        assert foreign_detail.status_code == 404
        assert order_id not in foreign_history.text

    canceled = checkout_client.post(
        f"/orders/{order_id}/cancel", follow_redirects=False
    )
    canceled_again = checkout_client.post(
        f"/orders/{order_id}/cancel", follow_redirects=False
    )
    assert canceled.status_code == canceled_again.status_code == 303
    assert canceled.headers["location"] == order_path
    canceled_detail = checkout_client.get(order_path)
    assert 'data-order-status="CANCELED"' in canceled_detail.text
    assert "Canceled" in canceled_detail.text
    assert "Total due today: ¥0" in canceled_detail.text

    learning = importlib.import_module("backend.learning_db")
    enrollment = learning.list_enrollments("learner-empty")[0]
    assert enrollment["track"] == "paid"
    assert enrollment["status"] == "canceled"


def test_checkout_styles_do_not_render_a_chinese_order_summary_label() -> None:
    stylesheet = (
        Path(__file__).resolve().parents[1] / "static" / "checkout-desktop.css"
    ).read_text(encoding="utf-8")
    assert 'content: "Order summary"' in stylesheet
    assert re.search(r"[\u4e00-\u9fff]", stylesheet) is None


def test_paid_enrollment_card_and_legacy_cancel_route_preserve_paid_order(
    checkout_client: TestClient,
) -> None:
    """Catch paid cards exposing the enrollment-only cancellation path."""

    _login_empty(checkout_client)
    draft_id = _create_browser_draft(checkout_client)
    approved = checkout_client.post(
        f"/checkout/{draft_id}/attempt",
        data={
            "scenario_id": "sandbox-approved",
            "idempotency_key": "browser-paid-card-approved-001",
        },
        follow_redirects=False,
    )
    order_path = approved.headers["location"]
    learning = importlib.import_module("backend.learning_db")
    enrollment_id = learning.list_enrollments("learner-empty")[0]["enrollment_id"]

    dashboard = checkout_client.get("/my-learning")
    assert f'action="/enrollments/{enrollment_id}/cancel"' not in dashboard.text
    assert f'href="{order_path}"' in dashboard.text
    assert "Manage local paid order" in dashboard.text

    legacy = checkout_client.post(
        f"/enrollments/{enrollment_id}/cancel", follow_redirects=False
    )
    assert legacy.status_code == 303
    assert legacy.headers["location"] == order_path

    checkout = importlib.import_module("backend.checkout")
    order_id = order_path.rsplit("/", 1)[1]
    assert checkout.get_order("learner-empty", order_id)["status"] == "PAID"
    enrollment = learning.list_enrollments("learner-empty")[0]
    assert enrollment["status"] == "active"
    assert enrollment["track"] == "paid"
