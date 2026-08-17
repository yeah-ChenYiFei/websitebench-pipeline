from __future__ import annotations

import importlib
import json
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
    assert "开始 7 天免费试用" in checkout.text


def test_progress_verifier_alias_reaches_declared_learning_states(
    checkout_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch stale diagnostic aliases or progress recipes that remain anonymous."""

    token = "final-wave-ephemeral-verifier-token"
    monkeypatch.setenv("WEBSITEBENCH_VERIFY_SESSION_TOKEN", token)
    opened = checkout_client.post(
        "/__websitebench/session",
        data={"account": "progress-learner"},
        headers={"X-WebsiteBench-Verify-Token": token},
    )
    assert opened.status_code == 204

    driver = json.loads(
        (Path(__file__).resolve().parents[2] / "scope" / "verify.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "my-learning": (200, "<h1>我的学习</h1>"),
        "lesson": (200, "<h1>Optimization methods</h1>"),
        "account-history": (200, "<h1>报名历史</h1>"),
        "preferences": (200, "<h1>学习偏好</h1>"),
    }
    for alias, (status, marker) in expected.items():
        response = checkout_client.get(driver["routes"][alias])
        assert response.status_code == status, alias
        assert marker in response.text, alias

    lesson = checkout_client.get(driver["routes"]["quiz"])
    assert 'action="/learning/quizzes/quiz-improving-networks"' in lesson.text
    feedback = checkout_client.post(
        "/learning/quizzes/quiz-improving-networks",
        data={"answer": "Regularization"},
    )
    assert feedback.status_code == 200
    assert "<h1>测验得分：100</h1>" in feedback.text


def test_public_entry_and_authenticated_plan_show_observed_trial_totals(
    checkout_client: TestClient,
) -> None:
    """Catch a paid entry that bypasses auth or hides inferred pricing."""

    anonymous = checkout_client.get("/specializations/deep-learning")
    assert anonymous.status_code == 200
    assert "免费注册" in anonymous.text
    assert 'href="/login?next=/checkout/deep-learning"' in anonymous.text
    signed_out_plan = checkout_client.get("/checkout/deep-learning")
    assert signed_out_plan.status_code == 401

    _login_empty(checkout_client)
    specialization = checkout_client.get("/specializations/deep-learning")
    assert 'href="/checkout/deep-learning"' in specialization.text
    plan = checkout_client.get("/checkout/deep-learning")
    assert plan.status_code == 200
    assert "开始 7 天免费试用" in plan.text
    assert "之后为 ¥196/月" in plan.text
    assert "今天应付" in plan.text and "¥0" in plan.text
    assert "今日合计：¥0" in plan.text
    assert "不会提交真实付款数据" in plan.text
    assert 'action="/checkout/deep-learning"' in plan.text


def test_checkout_entry_matches_observed_chinese_source_payment_layout(
    checkout_client: TestClient,
) -> None:
    """Catch the checkout entry drifting away from the captured Coursera layout."""

    _login_empty(checkout_client)

    html = checkout_client.get("/checkout/deep-learning").text

    assert 'class="source-checkout-shell"' in html
    assert "<h1>结帐</h1>" in html
    assert "所有字段均为必填字段" in html
    assert "账单信息" in html
    assert "支付方式" in html
    assert "银行卡" in html
    assert "Paypal" in html
    assert "1234 1234 1234 1234" in html
    assert "Deep Learning" in html
    assert "由 DeepLearning.AI 提供" in html
    assert "无绑定合同。可随时取消。" in html
    assert "7 天免费试用" in html
    assert "之后为 ¥196/月" in html
    assert "今日合计：¥0" in html

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
    assert "付款方式" in payment.text
    assert "只保留在当前浏览器页面" in payment.text
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
    assert "确认免费试用" in review.text
    assert "之后为 ¥196/月" in review.text and "今日合计：¥0" in review.text
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
        ("sandbox-declined", "模拟付款被拒绝"),
        ("sandbox-retry", "模拟付款需要重试"),
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
    assert "已付款" in detail.text
    assert "之后为 ¥196/月" in detail.text and "今日合计：¥0" in detail.text
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
    assert "已取消" in canceled_detail.text
    assert "今日合计：¥0" in canceled_detail.text

    learning = importlib.import_module("backend.learning_db")
    enrollment = learning.list_enrollments("learner-empty")[0]
    assert enrollment["track"] == "paid"
    assert enrollment["status"] == "canceled"


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
    assert "管理本地付费订单" in dashboard.text

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
