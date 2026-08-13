"""Sensitive-value scanning at repository and URL input boundaries."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote

SAFE_REDACTIONS = {
    "***",
    "<redacted>",
    "[redacted]",
    "(redacted)",
    "redacted",
    "omitted",
    "none",
    "null",
}

# JSON quoting places a quote between a field name and ``:``, so the plain
# assignment regular expressions below intentionally are not the only line of
# defence. Boundary inputs are often structured JSON, so scan decoded keys
# recursively before accepting them.
STRUCTURED_SENSITIVE_KEYS = {
    "accesskey": "access_key",
    "accesstoken": "access_token",
    "addressline1": "personal_address",
    "addressline2": "personal_address",
    "apikey": "api_key",
    "authorization": "authorization",
    "billingaddress": "personal_address",
    "cardnumber": "payment_card",
    "clientsecret": "client_secret",
    "cookie": "cookie",
    "cvc": "payment_card",
    "cvv": "payment_card",
    "expiry": "payment_card",
    "formbody": "raw_request_body",
    "onetimecode": "verification_code",
    "otp": "verification_code",
    "pan": "payment_card",
    "passwd": "password",
    "password": "password",
    "postaladdress": "personal_address",
    "postbody": "raw_request_body",
    "privatekey": "private_key",
    "pwd": "password",
    "rawbody": "raw_request_body",
    "rawrequestbody": "raw_request_body",
    "refreshtoken": "refresh_token",
    "requestbody": "raw_request_body",
    "secret": "secret",
    "secretkey": "secret_key",
    "sessionid": "session_id",
    "sessiontoken": "session_token",
    "shippingaddress": "personal_address",
    "smtppassword": "smtp_password",
    "token": "token",
    "verificationcode": "verification_code",
    "verifycode": "verification_code",
}
STRUCTURED_HASH_SUBJECTS = (
    "body",
    "code",
    "otp",
    "password",
    "secret",
    "token",
)

SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|client[_ -]?secret|api[_ -]?key|"
    r"access[_ -]?token|refresh[_ -]?token|authorization|cookie|set-cookie|"
    r"session[_ -]?(?:id|token)|smtp[_ -]?password)\b\s*(?:=|:)\s*"
    r"([^\s,;]+)"
)
SECRET_FLAG = re.compile(
    r"(?i)(?:^|\s)--(?:password|passwd|secret|api-key|access-token|refresh-token|"
    r"authorization|cookie|session-token|smtp-password)(?:=|\s+)([^\s,;]+)"
)
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
PROVIDER_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b")
OTP = re.compile(
    r"(?i)\b(?:otp|one[- ]time code|verification code|verify code)\b\s*(?:=|:|is)?\s*\d{4,8}\b"
)
# A decimal run embedded in a hexadecimal digest or opaque identifier is not a
# card-number field.  Require a non-alphanumeric boundary so safe SHA-256
# evidence cannot nondeterministically trip the Luhn heuristic.
CARD_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d[ -]?){13,19}(?![A-Za-z0-9])"
)
RAW_BODY = re.compile(
    r"(?i)\b(?:raw[_ -]?(?:request[_ -]?)?|request[_ -]?|post[_ -]?|form[_ -]?)body\b"
    r"\s*(?:=|:)\s*([^\r\n]+)"
)
SECRET_HASH = re.compile(
    r"(?i)\b(?:password|otp|verification[_ -]?code|secret|request[_ -]?body|"
    r"raw[_ -]?body|body_sha256)[^\r\n]{0,48}?(?:sha[-_ ]?256|hash|=|:)\s*"
    r"([a-f0-9]{32,128})\b"
)
EMAIL = re.compile(
    r"(?i)(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~-])([A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Z0-9.-]+))"
)
PERSONAL_ADDRESS = re.compile(
    r"(?i)\b(?:street|postal[_ -]?address|shipping[_ -]?address|"
    r"billing[_ -]?address|address[_ -]?line[12])\b\s*(?:=|:)\s*([^\r\n]+)"
)
QUOTED_FIELD_ASSIGNMENT = re.compile(
    r'''(?x)["']([^"']{1,80})["']\s*:\s*'''
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^,\s}\]]+)'''
)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _strict_json_loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_strict_object)


def _luhn(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _structured_sensitive_findings(value: Any) -> list[str]:
    findings: list[str] = []
    if isinstance(value, list):
        for item in value:
            findings.extend(_structured_sensitive_findings(item))
        return findings
    if not isinstance(value, dict):
        return findings
    for raw_key, item in value.items():
        key = re.sub(r"[^a-z0-9]", "", str(raw_key).casefold())
        safe_redaction = isinstance(item, str) and item.strip().casefold() in SAFE_REDACTIONS
        finding = STRUCTURED_SENSITIVE_KEYS.get(key)
        if finding and item is not None and not safe_redaction:
            findings.append(finding)
        if (
            key.endswith(("hash", "sha256"))
            and any(subject in key for subject in STRUCTURED_HASH_SUBJECTS)
            and item is not None
            and not safe_redaction
        ):
            findings.append("low_entropy_secret_hash")
        findings.extend(_structured_sensitive_findings(item))
    return findings


def _json_sensitive_findings(message: str) -> list[str]:
    stripped = message.strip()
    if not stripped.startswith(("{", "[")):
        return []
    try:
        value = _strict_json_loads(stripped)
    except (json.JSONDecodeError, ValueError):
        # Duplicate keys and other ambiguous JSON must not be allowed to hide
        # a first value behind last-key-wins parsing.
        return ["ambiguous_json"]
    if not isinstance(value, (dict, list)):
        return []
    return _structured_sensitive_findings(value)


def _sensitive_findings_one(message: str) -> list[str]:
    findings: list[str] = _json_sensitive_findings(message)
    for match in QUOTED_FIELD_ASSIGNMENT.finditer(message):
        key = re.sub(r"[^a-z0-9]", "", match.group(1).casefold())
        raw_value = match.group(2).strip()
        if raw_value.startswith('"'):
            try:
                decoded_value = json.loads(raw_value)
            except json.JSONDecodeError:
                decoded_value = raw_value.strip('"')
        else:
            decoded_value = raw_value.strip("'")
        safe_redaction = (
            isinstance(decoded_value, str)
            and decoded_value.strip().casefold() in SAFE_REDACTIONS
        )
        finding = STRUCTURED_SENSITIVE_KEYS.get(key)
        if finding and not safe_redaction:
            findings.append(finding)
        if (
            key.endswith(("hash", "sha256"))
            and any(subject in key for subject in STRUCTURED_HASH_SUBJECTS)
            and not safe_redaction
        ):
            findings.append("low_entropy_secret_hash")
    for match in SECRET_ASSIGNMENT.finditer(message):
        value = match.group(2).strip("\"'").casefold()
        if value not in SAFE_REDACTIONS:
            findings.append(match.group(1).casefold().replace(" ", "_"))
    for match in SECRET_FLAG.finditer(message):
        value = match.group(1).strip("\"'").casefold()
        if value not in SAFE_REDACTIONS:
            findings.append("credential_flag")
    if "-----begin " in message.casefold() and "private key-----" in message.casefold():
        findings.append("private_key")
    if BEARER.search(message):
        findings.append("bearer_token")
    if JWT.search(message):
        findings.append("jwt")
    if PROVIDER_KEY.search(message):
        findings.append("provider_key")
    if OTP.search(message):
        findings.append("verification_code")
    for match in RAW_BODY.finditer(message):
        if match.group(1).strip(" \"'").casefold() not in SAFE_REDACTIONS:
            findings.append("raw_request_body")
    if SECRET_HASH.search(message):
        findings.append("low_entropy_secret_hash")
    for match in EMAIL.finditer(message):
        domain = match.group(2).rstrip(".").casefold()
        if not (
            domain == "localhost"
            or domain.endswith((".test", ".invalid"))
            or domain in {"example.com", "example.org", "example.net"}
            or domain.endswith((".example.com", ".example.org", ".example.net"))
        ):
            findings.append("email_address")
    for match in PERSONAL_ADDRESS.finditer(message):
        if match.group(1).strip(" \"'").casefold() not in SAFE_REDACTIONS:
            findings.append("personal_address")
    if any(_luhn(match.group()) for match in CARD_CANDIDATE.finditer(message)):
        findings.append("payment_card")
    return sorted(set(findings))


def sensitive_findings(message: str) -> list[str]:
    """Scan literal and bounded recursively percent-decoded representations."""

    findings: set[str] = set()
    layer = message
    for _ in range(5):
        findings.update(_sensitive_findings_one(layer))
        decoded = unquote(layer)
        if decoded == layer:
            return sorted(findings)
        layer = decoded
    # Scan the representation produced by the final permitted decode. If it
    # still changes, fail closed: otherwise an attacker can always add one more
    # encoding layer than the bounded scanner.
    findings.update(_sensitive_findings_one(layer))
    if unquote(layer) != layer:
        findings.add("excessive_percent_encoding")
    return sorted(findings)
