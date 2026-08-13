from __future__ import annotations

import json
from urllib.parse import quote

import pytest

from websitebench.offline_clone.secrets import sensitive_findings


def _percent_encode(value: str, layers: int) -> str:
    for _ in range(layers):
        value = quote(value, safe="")
    return value


@pytest.mark.parametrize(
    "message",
    [
        "password=hunter2",
        "access_token%253Dhunter2",
        '{"password":"hunter2","password":"redacted"}',
        '{"event":{"credentials":{"otp":"123456"}}}',
        '{"payment":{"cvv":"123"}}',
        '{"otp_sha256":"' + "a" * 64 + '"}',
        "Authorization: Bearer abcdefghijklmnop",
        "card 4111 1111 1111 1111",
        "api_key=sk-abcdefghijklmnopqrstuvwxyz",
        "raw request body: email=user@example.test&quantity=2",
        "customer email is person@private-mail.example",
        "shipping_address: 123 Main Street, Springfield",
    ],
)
def test_sensitive_values_are_detected(message: str) -> None:
    assert sensitive_findings(message)


def test_percent_decode_depth_scans_last_layer_and_fails_closed_beyond_it() -> None:
    assert "password" in sensitive_findings(_percent_encode("password=secret", 5))
    assert "excessive_percent_encoding" in sensitive_findings(
        _percent_encode("password=secret", 6)
    )


def test_security_hashes_are_not_mistaken_for_payment_cards() -> None:
    digest = "63d20e5898d8725b5609528773891cb39a364bf0e7fbb6c4679ad7518772c571"
    assert "payment_card" not in sensitive_findings(json.dumps({"sha256": digest}))
    assert "payment_card" in sensitive_findings("card 4111 1111 1111 1111")


def test_redacted_security_vocabulary_is_allowed() -> None:
    assert sensitive_findings(
        '{"password":"<redacted>","otp":"omitted","token":"none"}'
    ) == []
