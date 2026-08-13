"""Deterministic email-to-plan parser for the TripIt clone.

Travelers forward confirmation emails to ``plans@tripit.com`` and TripIt files
the resulting plan into the matching trip (or leaves it Unfiled). This module is
the offline, side-effect-free heart of that behaviour: :func:`parse_message`
turns a raw RFC822 message into a structured plan intent using a small set of
provider rule packs, and it does so as a pure function of the message text — no
wall clock, no network, no randomness — so the same email always yields the same
plan and the same idempotency fingerprint.

Recognition is intentionally conservative. A message whose sender domain and
subject match a known provider is parsed against that provider's labelled
fields; everything else is a first-class ``unparseable`` outcome that the UI
surfaces exactly as the source does, rather than a guess that files a wrong plan.

The transactional side (dedupe by fingerprint, date-overlap trip routing, plan
upsert for reschedules/cancellations, and the import-receipt mail) lives in
``backend.db.import_email``; this module never touches the database.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from email import message_from_string
from email.utils import parseaddr
from typing import Any

# ---------------------------------------------------------------------------
# fingerprint + field helpers
# ---------------------------------------------------------------------------


def _normalize_body(text: str) -> str:
    """Collapse whitespace and case so trivial re-encodings fingerprint alike."""

    return re.sub(r"\s+", " ", text or "").strip().casefold()


def content_fingerprint(from_address: str, subject: str, body: str) -> str:
    """Stable idempotency fingerprint for a forwarded message.

    ``sha256(from + subject + normalized_body)`` — the same email forwarded twice
    collapses to one import; a reschedule or cancellation (different body) is a
    distinct message that updates the same underlying plan by natural key.
    """

    material = "\x1f".join(
        (from_address.strip().casefold(), subject.strip().casefold(), _normalize_body(body))
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _body_of(raw_text: str) -> str:
    message = message_from_string(raw_text)
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=False)
                if isinstance(payload, str):
                    return payload
    payload = message.get_payload(decode=False)
    return payload if isinstance(payload, str) else ""


def _field(pattern: str, text: str, default: str = "") -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else default


_DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y")


def _parse_date(raw: str) -> str:
    """Normalize a human date to ISO ``YYYY-MM-DD`` (empty string if unreadable)."""

    value = (raw or "").strip().rstrip(".")
    # Drop a leading weekday name ("Monday, May 24, 2027").
    value = re.sub(r"^[A-Za-z]+,\s*", "", value)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _parse_time(raw: str, default: str) -> str:
    value = (raw or "").strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%H:%M", "%I %p"):
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return default


# Location token -> IANA zone, covering every place used by the fixture library.
# A confirmation email never carries an IANA name, so the provider zone is
# inferred from the airport code or city the message does contain.
_TZ_BY_TOKEN: dict[str, str] = {
    "JFK": "America/New_York",
    "LGA": "America/New_York",
    "EWR": "America/New_York",
    "NEW YORK": "America/New_York",
    "SFO": "America/Los_Angeles",
    "SAN FRANCISCO": "America/Los_Angeles",
    "LAX": "America/Los_Angeles",
    "ORD": "America/Chicago",
    "CHICAGO": "America/Chicago",
    "BOS": "America/New_York",
    "BOSTON": "America/New_York",
}


def _zone_for(*tokens: str) -> str:
    """Resolve an IANA zone from any location token found in the message.

    Tokens may be airport codes, cities, or whole address lines. Longer tokens
    win first ("San Francisco" before "SFO"), and matching is whole-word so a
    short code never triggers on a substring of an unrelated word.
    """

    haystack = " ".join(token for token in tokens if token).upper()
    for token, zone in sorted(_TZ_BY_TOKEN.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(token)}\b", haystack):
            return zone
    return "UTC"


def _action_for(subject: str, body: str) -> str:
    """Classify the message as a new plan, a reschedule, or a cancellation."""

    haystack = f"{subject}\n{body}".lower()
    if re.search(r"cancel(l?ed|lation)?\b", haystack):
        return "canceled"
    if re.search(r"schedule change|time change|reschedul|updated itinerary|has changed", haystack):
        return "updated"
    return "parsed"


# ---------------------------------------------------------------------------
# provider rule packs — each returns a plan intent dict or None
# ---------------------------------------------------------------------------


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _lodging_rule(domain: str, subject: str, body: str) -> dict[str, Any] | None:
    if not domain.endswith("hilton.com"):
        return None
    hotel = _field(r"Hotel:\s*(.+)", body) or "Hilton hotel"
    check_in = _parse_date(_field(r"Check-?in:\s*(.+)", body))
    check_out = _parse_date(_field(r"Check-?out:\s*(.+)", body))
    confirmation = _field(r"Confirmation (?:Number|No\.?|#):\s*(\S+)", body)
    zone = _zone_for(_field(r"Address:\s*(.+)", body), hotel)
    return {
        "provider": "Hilton",
        "plan_type": "lodging",
        "title": hotel,
        "confirmation": confirmation,
        "natural_key": f"import:hilton:{confirmation or _slug(hotel)}",
        "start_date": check_in,
        "start_time": "15:00",
        "end_date": check_out,
        "end_time": "11:00",
        "timezone": zone,
        "details": {
            "hotel_name": hotel,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "confirmation_number": confirmation,
        },
    }


def _air_rule(domain: str, subject: str, body: str) -> dict[str, Any] | None:
    if not domain.endswith("united.com"):
        return None
    flight = _field(r"Flight:\s*(.+)", body) or "United flight"
    origin = _field(r"Depart(?:ure|s)?:\s*([A-Z]{3})", body)
    dest = _field(r"Arriv(?:al|es)?:\s*([A-Z]{3})", body)
    date = _parse_date(_field(r"Date:\s*(.+)", body))
    dep_time = _parse_time(_field(r"Depart(?:ure|s)?:\s*[A-Z]{3}\s+at\s+([0-9:APM ]+)", body), "09:00")
    arr_time = _parse_time(_field(r"Arriv(?:al|es)?:\s*[A-Z]{3}\s+at\s+([0-9:APM ]+)", body), dep_time)
    confirmation = _field(r"Confirmation (?:Number|No\.?|#):\s*(\S+)", body)
    title = f"{flight} · {origin} → {dest}" if origin and dest else flight
    return {
        "provider": "United",
        "plan_type": "air",
        "title": title,
        "confirmation": confirmation,
        "natural_key": f"import:united:{confirmation or _slug(flight)}",
        "start_date": date,
        "start_time": dep_time,
        "end_date": date,
        "end_time": arr_time,
        "timezone": _zone_for(origin),
        "details": {
            "airline": "United",
            "flight": flight,
            "origin": origin,
            "destination": dest,
            "confirmation_number": confirmation,
        },
    }


def _car_rule(domain: str, subject: str, body: str) -> dict[str, Any] | None:
    if not domain.endswith("hertz.com"):
        return None
    location = _field(r"Location:\s*(.+)", body) or "Hertz location"
    pickup = _parse_date(_field(r"Pick-?up:\s*(.+?)(?:\s+at\b|$)", body))
    dropoff = _parse_date(_field(r"Drop-?off:\s*(.+?)(?:\s+at\b|$)", body))
    confirmation = _field(r"Confirmation (?:Number|No\.?|#):\s*(\S+)", body)
    return {
        "provider": "Hertz",
        "plan_type": "car",
        "title": f"Hertz rental · {location}",
        "confirmation": confirmation,
        "natural_key": f"import:hertz:{confirmation or _slug(location)}",
        "start_date": pickup,
        "start_time": "12:00",
        "end_date": dropoff,
        "end_time": "12:00",
        "timezone": _zone_for(location),
        "details": {
            "vendor": "Hertz",
            "location": location,
            "confirmation_number": confirmation,
        },
    }


def _restaurant_rule(domain: str, subject: str, body: str) -> dict[str, Any] | None:
    if not domain.endswith("opentable.com"):
        return None
    name = _field(r"Restaurant:\s*(.+)", body) or "Restaurant reservation"
    date = _parse_date(_field(r"Date:\s*(.+)", body))
    time = _parse_time(_field(r"Time:\s*(.+)", body), "19:00")
    party = _field(r"Party(?: size)?:\s*(\d+)", body)
    confirmation = _field(r"Confirmation (?:Number|No\.?|#):\s*(\S+)", body)
    address = _field(r"(?:Address|Location):\s*(.+)", body)
    return {
        "provider": "OpenTable",
        "plan_type": "restaurant",
        "title": name,
        "confirmation": confirmation,
        "natural_key": f"import:opentable:{confirmation or _slug(name)}",
        "start_date": date,
        "start_time": time,
        "end_date": "",
        "end_time": "",
        "timezone": _zone_for(address, name),
        "details": {
            "location": name,
            "party_size": int(party) if party.isdigit() else None,
            "confirmation_number": confirmation,
        },
    }


_RULES = (_lodging_rule, _air_rule, _car_rule, _restaurant_rule)


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def parse_message(raw_text: str) -> dict[str, Any]:
    """Parse a raw forwarded email into a plan intent.

    Always returns a dict carrying ``fingerprint``, ``from_address``,
    ``subject``, ``provider`` and ``status`` (one of ``parsed``/``updated``/
    ``canceled``/``unparseable``). When recognized it also carries the plan
    fields (``plan_type``, ``title``, ``natural_key``, local dates/times,
    ``timezone``, ``details``). ``details`` drops empty values so imported plans
    render like manually entered ones.
    """

    message = message_from_string(raw_text or "")
    _, from_address = parseaddr(message.get("From", ""))
    subject = (message.get("Subject", "") or "").strip()
    body = _body_of(raw_text or "")
    fingerprint = content_fingerprint(from_address, subject, body)
    base = {
        "fingerprint": fingerprint,
        "from_address": from_address,
        "subject": subject,
    }

    domain = from_address.rsplit("@", 1)[-1].lower() if "@" in from_address else ""
    for rule in _RULES:
        intent = rule(domain, subject, body)
        if intent is None:
            continue
        intent["status"] = _action_for(subject, body)
        intent["details"] = {
            key: value for key, value in intent["details"].items() if value not in (None, "")
        }
        return {**base, **intent}

    return {**base, "provider": None, "plan_type": None, "status": "unparseable", "details": {}}
