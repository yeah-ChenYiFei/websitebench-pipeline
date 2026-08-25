import sys
from pathlib import Path

import pytest


SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT / "tools"))

from privacy_scan import scan_tree  # noqa: E402


def test_candidate_tree_has_no_high_confidence_sensitive_values() -> None:
    findings = scan_tree(SITE_ROOT)

    assert not findings, "\n" + "\n".join(
        finding.render(SITE_ROOT) for finding in findings
    )


@pytest.mark.parametrize(
    "category_payload",
    (
        ("non-reserved-email", "synthetic-user" + "@not-allowed.test"),
        ("cookie-value", "Set-" + "Coo" + "kie: session=abcdefghijklmnop"),
        ("cookie-value", "Cook" + "ie: session=abcdefghijklmnop"),
        ("authorization-value", "Authori" + "zation: Bear" + "er abcdefghijklmnop"),
        ("assigned-secret", "api_" + 'key = "abcdefghijklmnop1234"'),
        ("assigned-secret", "sec" + 'ret = "abcdefghijklmnop1234"'),
        ("assigned-secret", "tok" + 'en = "abcdefghijklmnop1234"'),
        ("private-key", "-----BEGIN " + "PRIVATE " + "KEY" + "-----"),
        ("live-provider-key", "sk_" + "live_abcdefghijklmnop"),
        ("live-provider-key", "sk-" + "abcdefghijklmnopqrstuvwx"),
        ("live-provider-key", "re_" + "abcdefghijklmnopqrstuvwx"),
        ("plaintext-otp", "verification_" + "code = 481516"),
        (
            "payment-card-data",
            "card_" + 'number = "4111111111111111"',
        ),
        ("international-phone", "+" + "442079460958"),
        ("password-value", "pass" + 'word = "RiverStoneTwelve"'),
        (
            "cloudflare-api-token",
            "cloudflare_" + 'api_token = "zyxwvutsrqponmlkjihgfedcba"',
        ),
        (
            "postal-" + "address",
            "postal_" + "add" + 'ress = "4827 Cedar Road"',
        ),
        (
            "url-query-identifier",
            "https://pixels.example.invalid/collect?" + "mscl" + "kid=opaque123456",
        ),
    ),
)
def test_scanner_detects_required_categories_without_echoing_values(
    tmp_path: Path, category_payload: tuple[str, str]
) -> None:
    category, payload = category_payload
    artifact = tmp_path / "runtime.log"
    artifact.write_text(payload + "\n", encoding="utf-8")

    findings = scan_tree(tmp_path)

    assert category in {finding.category for finding in findings}
    rendered = "\n".join(finding.render(tmp_path) for finding in findings)
    assert payload not in rendered
    assert "REDACTED" in rendered
