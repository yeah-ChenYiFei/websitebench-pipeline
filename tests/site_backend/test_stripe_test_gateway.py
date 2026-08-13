from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import pytest

from websitebench.site_backend import load_runtime
from websitebench.site_backend.stripe_test import (
    StripeTestError,
    StripeTestGateway,
    StripeTestLineItem,
    StripeTestResponseError,
)

from .helpers import runtime_config


FLOW = {
    "flow_id": "payflow_gatewayfactstest123",
    "site_id": "alpha",
    "owner": "owner:account-123",
    "amount_minor": 1299,
    "currency": "USD",
    "fingerprint": "a" * 64,
    "adapter": "stripe-test",
    "is_simulation": True,
}
SESSION_ID = "cs_test_gatewayfactstest123"


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        import json

        self.payload = json.dumps(payload).encode("utf-8")
        self.closed = False

    def read(self, _size: int) -> bytes:
        return self.payload

    def close(self) -> None:
        self.closed = True


def test_gateway_creates_only_frozen_site_bound_test_checkout() -> None:
    runtime = load_runtime(runtime_config("alpha", stripe=True))
    captured: list[Any] = []

    def opener(request, *, timeout: int):
        assert timeout == 10
        captured.append(request)
        return _Response(
            {
                "id": SESSION_ID,
                "object": "checkout.session",
                "livemode": False,
                "url": f"https://checkout.stripe.com/c/pay/{SESSION_ID}#fidkdWxOYHwn",
            }
        )

    gateway = StripeTestGateway(
        runtime,
        environment={"WEBSITEBENCH_EFFECTS_INTERNAL_TOKEN": "token-not-a-provider-key"},
        opener=opener,
        clock=lambda: 1_700_000_000,
    )
    session = gateway.create_checkout_session(
        flow=FLOW,
        customer_email="learner@example.test",
        line_items=(StripeTestLineItem("Verified course", 1299),),
    )

    assert session["id"] == SESSION_ID
    assert len(captured) == 1
    request = captured[0]
    assert request.full_url == "http://stripe.internal/v1/checkout/sessions"
    assert request.get_header("Authorization") is None
    assert request.get_header("Idempotency-key")
    fields = parse_qs(bytes(request.data).decode("utf-8"), strict_parsing=True)
    assert fields["metadata[site_id]"] == ["alpha"]
    assert fields["metadata[flow_id]"] == [FLOW["flow_id"]]
    assert fields["metadata[owner]"] == [FLOW["owner"]]
    assert fields["metadata[amount_minor]"] == ["1299"]
    assert fields["metadata[currency]"] == ["USD"]
    assert fields["metadata[fingerprint]"] == ["a" * 64]
    assert fields["metadata[is_simulation]"] == ["true"]
    assert fields["expires_at"] == [str(1_700_000_000 + 31 * 60)]
    assert fields["success_url"] == [
        "https://alpha.example.test/checkout/stripe-return?session_id=%7BCHECKOUT_SESSION_ID%7D"
    ]
    assert fields["cancel_url"] == [
        "https://alpha.example.test/checkout/stripe-return?cancelled=1&session_id=%7BCHECKOUT_SESSION_ID%7D"
    ]
    assert fields["line_items[0][price_data][unit_amount]"] == ["1299"]


def test_gateway_can_defer_payment_method_selection_to_stripe() -> None:
    config = runtime_config("alpha", stripe=True)
    config["payments"]["stripe_test"]["payment_method_types"] = []
    runtime = load_runtime(config)
    captured: list[Any] = []

    gateway = StripeTestGateway(
        runtime,
        opener=lambda request, **_kwargs: (
            captured.append(request)
            or _Response(
                {
                    "id": SESSION_ID,
                    "object": "checkout.session",
                    "livemode": False,
                    "url": f"https://checkout.stripe.com/c/pay/{SESSION_ID}",
                }
            )
        ),
    )
    gateway.create_checkout_session(
        flow=FLOW,
        customer_email="learner@example.test",
        line_items=(StripeTestLineItem("Verified course", 1299),),
    )

    fields = parse_qs(bytes(captured[0].data).decode("utf-8"))
    assert not any(key.startswith("payment_method_types[") for key in fields)


def test_gateway_uses_only_a_configured_opaque_integration_identifier() -> None:
    config = runtime_config("alpha", stripe=True)
    config["payments"]["stripe_test"]["integration_identifier_prefix"] = (
        "websitebench_alpha_"
    )
    runtime = load_runtime(config)
    captured: list[Any] = []
    gateway = StripeTestGateway(
        runtime,
        opener=lambda request, **_kwargs: (
            captured.append(request)
            or _Response(
                {
                    "id": SESSION_ID,
                    "object": "checkout.session",
                    "livemode": False,
                    "url": f"https://checkout.stripe.com/c/pay/{SESSION_ID}",
                }
            )
        ),
    )
    gateway.create_checkout_session(
        flow=FLOW,
        customer_email="learner@example.test",
        line_items=(StripeTestLineItem("Verified course", 1299),),
    )
    fields = parse_qs(bytes(captured[0].data).decode("utf-8"))
    assert fields["integration_identifier"][0].startswith("websitebench_alpha_")


def test_gateway_rejects_unsafe_internal_origin_and_live_provider_response() -> None:
    runtime = load_runtime(runtime_config("alpha", stripe=True))
    with pytest.raises(StripeTestError, match="isolated"):
        StripeTestGateway(
            runtime,
            environment={"STRIPE_INTERNAL_ORIGIN": "https://api.stripe.com"},
        )

    gateway = StripeTestGateway(
        runtime,
        opener=lambda _request, **_kwargs: _Response(
            {
                "id": SESSION_ID,
                "object": "checkout.session",
                "livemode": True,
                "url": f"https://checkout.stripe.com/c/pay/{SESSION_ID}",
            }
        ),
    )
    with pytest.raises(StripeTestResponseError, match="invalid Checkout Session"):
        gateway.create_checkout_session(
            flow=FLOW,
            customer_email="learner@example.test",
            line_items=(StripeTestLineItem("Verified course", 1299),),
        )


def test_gateway_retrieve_accepts_only_opaque_test_session_ids() -> None:
    runtime = load_runtime(runtime_config("alpha", stripe=True))
    gateway = StripeTestGateway(
        runtime,
        opener=lambda _request, **_kwargs: _Response(
            {"id": SESSION_ID, "object": "checkout.session"}
        ),
    )
    assert gateway.retrieve_checkout_session(SESSION_ID)["id"] == SESSION_ID
    with pytest.raises(StripeTestError, match="provider_session_id"):
        gateway.retrieve_checkout_session("4242424242424242")
