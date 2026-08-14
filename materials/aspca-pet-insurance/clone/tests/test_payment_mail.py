"""Atomic local-sandbox payment and local policy-confirmation mail proofs."""

from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend import quotes_db
from websitebench.site_backend import PaymentRejected


PET = {
    "species": "Cat",
    "name": "Willow",
    "age": "2 Years",
    "gender": "Female",
    "breed": "Domestic Shorthair",
}
EMAIL = "willow-payment@example.com"


def _create(client) -> str:
    response = client.post(
        "/api/quotes",
        json={**PET, "email": EMAIL, "zip": "44301"},
    )
    assert response.status_code == 201
    return response.json()["quote_id"]


def _payload(scenario_id: str) -> dict[str, object]:
    return {
        "contact": {
            "firstName": "Willow",
            "lastName": "Example",
            "email": EMAIL,
        },
        "frequency": "Monthly",
        "agree_terms": True,
        "paperless": True,
        "scenario_id": scenario_id,
    }


def _counts() -> dict[str, int]:
    tables = (
        "websitebench_payment_flows",
        "websitebench_payment_attempts",
        "websitebench_payment_events",
        "aspca_enrollments",
        "websitebench_mail_jobs",
    )
    with closing(quotes_db.connect()) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }


def test_approved_payment_enrolls_and_enqueues_one_local_mail(client) -> None:
    quote_id = _create(client)
    response = client.post(
        f"/api/quotes/{quote_id}/enroll",
        json=_payload("sandbox-approved"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["policy_number"] == "APH-000001"
    assert body["payment"]["status"] == "CONSUMED"
    assert body["payment"]["amount_minor"] == 1674
    assert body["payment"]["currency"] == "USD"
    assert body["payment"]["is_simulation"] is True
    assert body["mail"] == {
        "mail_id": body["mail"]["mail_id"],
        "purpose": "policy-confirmation",
        "status": "LOCAL_SIMULATION",
        "is_simulation": True,
    }
    counts = _counts()
    assert counts["websitebench_payment_flows"] == 1
    assert counts["websitebench_payment_attempts"] == 1
    assert counts["aspca_enrollments"] == 1
    assert counts["websitebench_mail_jobs"] == 1


@pytest.mark.parametrize(
    ("scenario_id", "status_code", "outcome"),
    [
        ("sandbox-declined", 402, "DECLINED"),
        ("sandbox-retry", 409, "RETRYABLE"),
    ],
)
def test_nonapproved_attempts_create_no_policy_or_mail(
    client, scenario_id: str, status_code: int, outcome: str
) -> None:
    quote_id = _create(client)
    response = client.post(
        f"/api/quotes/{quote_id}/enroll", json=_payload(scenario_id)
    )
    assert response.status_code == status_code
    assert response.json()["payment"]["status"] == outcome
    assert response.json()["enrolled"] is False
    counts = _counts()
    assert counts["websitebench_payment_flows"] == 1
    assert counts["websitebench_payment_attempts"] == 1
    assert counts["aspca_enrollments"] == 0
    assert counts["websitebench_mail_jobs"] == 0


def test_retry_then_approval_converges_to_one_policy_and_mail(client) -> None:
    quote_id = _create(client)
    retry = client.post(
        f"/api/quotes/{quote_id}/enroll", json=_payload("sandbox-retry")
    )
    approved = client.post(
        f"/api/quotes/{quote_id}/enroll", json=_payload("sandbox-approved")
    )
    duplicate = client.post(
        f"/api/quotes/{quote_id}/enroll", json=_payload("sandbox-approved")
    )
    assert retry.status_code == 409
    assert approved.status_code == 201
    assert duplicate.status_code == 200
    assert approved.json()["policy_number"] == duplicate.json()["policy_number"]
    assert approved.json()["payment"]["flow_id"] == duplicate.json()["payment"]["flow_id"]
    assert approved.json()["mail"]["mail_id"] == duplicate.json()["mail"]["mail_id"]
    counts = _counts()
    assert counts["websitebench_payment_flows"] == 1
    assert counts["websitebench_payment_attempts"] == 2
    assert counts["aspca_enrollments"] == 1
    assert counts["websitebench_mail_jobs"] == 1


def test_mail_failure_rolls_back_payment_consumption_and_policy(client, monkeypatch) -> None:
    quote_id = _create(client)
    backend, _auth = quotes_db.services()

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("injected local outbox failure")

    monkeypatch.setattr(backend.mail, "enqueue", fail_enqueue)
    with pytest.raises(RuntimeError, match="injected local outbox failure"):
        quotes_db.enroll(
            quote_id,
            {"firstName": "Willow", "email": EMAIL},
            "Monthly",
            True,
            True,
            "sandbox-approved",
        )
    assert _counts() == {
        "websitebench_payment_flows": 0,
        "websitebench_payment_attempts": 0,
        "websitebench_payment_events": 0,
        "aspca_enrollments": 0,
        "websitebench_mail_jobs": 0,
    }


def test_unknown_sandbox_scenario_is_rejected(client) -> None:
    quote_id = _create(client)
    response = client.post(
        f"/api/quotes/{quote_id}/enroll", json=_payload("not-configured")
    )
    assert response.status_code == 422
    assert "payment" in response.json()["errors"]
    assert _counts()["aspca_enrollments"] == 0


def test_foreign_owner_and_stale_fingerprint_cannot_consume_approval(client) -> None:
    quote_id = _create(client)
    backend, _auth = quotes_db.services()
    with backend.lifecycle.connection(transaction=True) as connection:
        quote = quotes_db._quote_row(connection, quote_id)
        facts = quotes_db._payment_facts(
            connection,
            quote,
            contact={"email": EMAIL},
            frequency="Monthly",
        )
        flow = backend.payments.create_intent(
            owner=facts["owner"],
            amount_minor=facts["amount_minor"],
            currency=facts["currency"],
            fingerprint=facts["fingerprint"],
            idempotency_key="aspca.foreign-stale.create",
            connection=connection,
        )
        backend.payments.attempt(
            flow_id=flow["flow_id"],
            owner=facts["owner"],
            amount_minor=facts["amount_minor"],
            currency=facts["currency"],
            fingerprint=facts["fingerprint"],
            scenario_id="sandbox-approved",
            idempotency_key="aspca.foreign-stale.attempt",
            connection=connection,
        )

    with pytest.raises(PaymentRejected, match="missing or foreign"):
        with backend.lifecycle.connection(transaction=True) as connection:
            backend.payments.consume_approval(
                connection,
                flow_id=flow["flow_id"],
                owner="quote:WB999999",
                amount_minor=facts["amount_minor"],
                currency=facts["currency"],
                fingerprint=facts["fingerprint"],
            )
    with closing(quotes_db.connect()) as connection:
        assert connection.execute(
            "SELECT status FROM websitebench_payment_flows WHERE flow_id = ?",
            (flow["flow_id"],),
        ).fetchone()[0] == "APPROVED"

    with pytest.raises(PaymentRejected, match="final state"):
        with backend.lifecycle.connection(transaction=True) as connection:
            backend.payments.consume_approval(
                connection,
                flow_id=flow["flow_id"],
                owner=facts["owner"],
                amount_minor=facts["amount_minor"],
                currency=facts["currency"],
                fingerprint="0" * 64,
            )
    with closing(quotes_db.connect()) as connection:
        assert connection.execute(
            "SELECT status FROM websitebench_payment_flows WHERE flow_id = ?",
            (flow["flow_id"],),
        ).fetchone()[0] == "INVALIDATED"
        assert connection.execute(
            "SELECT COUNT(*) FROM aspca_enrollments"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM websitebench_mail_jobs"
        ).fetchone()[0] == 0


def test_concurrent_approved_submissions_converge_to_one_policy_and_mail(client) -> None:
    quote_id = _create(client)

    def submit(_index: int) -> dict[str, object]:
        result = quotes_db.enroll(
            quote_id,
            {"email": EMAIL},
            "Monthly",
            True,
            True,
            "sandbox-approved",
        )
        assert result is not None
        return result

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(submit, range(8)))
    assert sum(not bool(result["already"]) for result in results) == 1
    assert len({result["policy_number"] for result in results}) == 1
    assert len({result["payment"]["flow_id"] for result in results}) == 1
    assert len({result["mail"]["mail_id"] for result in results}) == 1
    counts = _counts()
    assert counts["websitebench_payment_flows"] == 1
    assert counts["websitebench_payment_attempts"] == 1
    assert counts["aspca_enrollments"] == 1
    assert counts["websitebench_mail_jobs"] == 1
