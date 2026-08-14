"""ASPCA Pet Health Insurance offline clone — quote/enrollment persistence.

Owns the site's business schema (quotes, pets, plan selections, enrollments)
on top of the vendored ``websitebench.site_backend`` runtime, which owns the
library tables (accounts / sessions / OTP / mail outbox / payment ledger) in
the same SQLite file. Mirrors the tripit golden-sample layering:

* the runtime contract stays ``backend/runtime.json`` with
  ``migration_hook: null`` / ``seed_hook: null`` — migrations are owned here
  and recorded in ``aspca_schema_migrations``;
* one bound database file (``aspca-pet-insurance.sqlite3``) holds all state;
* deterministic identity: quote numbers and policy numbers derive from the
  row id, timestamps are pinned to the frozen capture clock — no wall clock,
  no randomness — so identical operation sequences yield identical state;
* :func:`reset` clears business rows and the library auth state atomically
  (called by the test harness and ``POST /__admin/reset``).

Payment boundary: the source funnel was never advanced to payment, so the
clone adds a clearly labeled local-sandbox contract of its own. The client may
submit one opaque scenario id; amount, owner, currency and fingerprint are
server-derived. No credential or provider field is accepted.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

from websitebench.local_clone_auth import LocalAuthStore
from websitebench.site_backend import SiteBackend

from backend.site_backend_integration import open_site_services
from backend import rating

SITE_ID = "aspca-pet-insurance"

# Single frozen clock for the whole clone (capture day, UTC).
FROZEN_CLOCK_UTC = "2026-08-13T12:00:00Z"

_MIGRATIONS: dict[str, str] = {
    "0001_quotes_core": """
        CREATE TABLE IF NOT EXISTS aspca_quotes (
            id INTEGER PRIMARY KEY,
            quote_number TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            zip TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'enrolled')),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_aspca_quotes_email_zip
            ON aspca_quotes (email, zip);
        CREATE TABLE IF NOT EXISTS aspca_pets (
            id INTEGER PRIMARY KEY,
            quote_id INTEGER NOT NULL
                REFERENCES aspca_quotes (id) ON DELETE CASCADE,
            species TEXT NOT NULL,
            name TEXT NOT NULL,
            age_label TEXT NOT NULL,
            gender TEXT NOT NULL,
            breed TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_aspca_pets_quote
            ON aspca_pets (quote_id);
    """,
    "0002_selections": """
        CREATE TABLE IF NOT EXISTS aspca_selections (
            pet_id INTEGER PRIMARY KEY
                REFERENCES aspca_pets (id) ON DELETE CASCADE,
            annual_limit INTEGER NOT NULL,
            deductible INTEGER NOT NULL,
            reimbursement INTEGER NOT NULL,
            preventive TEXT
                CHECK (preventive IN ('basic', 'prime') OR preventive IS NULL),
            monthly TEXT NOT NULL,
            preventive_monthly TEXT NOT NULL,
            provenance TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """,
    "0003_enrollments": """
        CREATE TABLE IF NOT EXISTS aspca_enrollments (
            id INTEGER PRIMARY KEY,
            quote_id INTEGER NOT NULL UNIQUE
                REFERENCES aspca_quotes (id) ON DELETE CASCADE,
            policy_number TEXT NOT NULL UNIQUE,
            contact_json TEXT NOT NULL,
            frequency TEXT NOT NULL
                CHECK (frequency IN ('Monthly', 'Annually')),
            agree_terms INTEGER NOT NULL CHECK (agree_terms = 1),
            paperless INTEGER NOT NULL CHECK (paperless IN (0, 1)),
            created_at TEXT NOT NULL
        );
    """,
    "0004_payment_enrollment": """
        ALTER TABLE aspca_enrollments ADD COLUMN payment_flow_id TEXT;
        ALTER TABLE aspca_enrollments ADD COLUMN payment_attempt_id TEXT;
        ALTER TABLE aspca_enrollments ADD COLUMN amount_minor INTEGER;
        ALTER TABLE aspca_enrollments ADD COLUMN currency TEXT;
        ALTER TABLE aspca_enrollments ADD COLUMN fingerprint TEXT;
        ALTER TABLE aspca_enrollments ADD COLUMN mail_id TEXT;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_aspca_enrollments_payment_flow
            ON aspca_enrollments (payment_flow_id)
            WHERE payment_flow_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_aspca_enrollments_payment_attempt
            ON aspca_enrollments (payment_attempt_id)
            WHERE payment_attempt_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_aspca_enrollments_mail
            ON aspca_enrollments (mail_id)
            WHERE mail_id IS NOT NULL;
    """,
}

# Defensive payment-boundary guard: no key that looks like a payment field may
# ever enter the business tables (the source funnel stopped before payment).
_PAYMENT_KEY_RE = re.compile(
    r"(?i)(card|cc[-_]?(num|number|exp)|cvv|cvc|pan\b|iban|routing|account[-_]?number"
    r"|expir|security[-_]?code|payment[-_]?(method|token)|stripe|bank)"
)
_SERVER_PAYMENT_FACT_KEYS = {
    "adapter",
    "amountminor",
    "attemptid",
    "currency",
    "fingerprint",
    "flowid",
    "owner",
    "providerreference",
    "providersessionid",
}


class PaymentFieldRejected(ValueError):
    """A card/payment-like key reached a business insert path."""


def reject_payment_keys(payload: dict[str, Any]) -> None:
    for key in payload:
        normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
        if (
            _PAYMENT_KEY_RE.search(str(key))
            or normalized in _SERVER_PAYMENT_FACT_KEYS
        ):
            raise PaymentFieldRejected(
                f"payment-like field {key!r} is outside this clone's scope"
            )


_SERVICES_LOCK = threading.Lock()
_SERVICES: tuple[SiteBackend, LocalAuthStore] | None = None


def services() -> tuple[SiteBackend, LocalAuthStore]:
    """Process-wide backend + auth pair (bound database, schema ensured)."""

    global _SERVICES
    with _SERVICES_LOCK:
        if _SERVICES is None:
            backend, auth = open_site_services()
            _ensure_business_schema(backend.lifecycle.database_path)
            _SERVICES = (backend, auth)
        return _SERVICES


def close_services() -> None:
    """Drop the cached pair (tests re-open against fresh env paths)."""

    global _SERVICES
    with _SERVICES_LOCK:
        _SERVICES = None


def database_path() -> Path:
    return services()[0].lifecycle.database_path


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def connect() -> sqlite3.Connection:
    return _connect(database_path())


def _ensure_business_schema(path: Path) -> None:
    with closing(_connect(path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS aspca_schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            row["migration_id"]
            for row in connection.execute(
                "SELECT migration_id FROM aspca_schema_migrations"
            )
        }
        for migration_id, ddl in _MIGRATIONS.items():
            if migration_id in applied:
                continue
            connection.executescript(ddl)
            connection.execute(
                "INSERT INTO aspca_schema_migrations (migration_id, applied_at)"
                " VALUES (?, ?)",
                (migration_id, FROZEN_CLOCK_UTC),
            )


def reset() -> None:
    """Delete all site business, payment, mail and auth rows atomically."""

    backend, auth = services()

    def _site_reset(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM aspca_enrollments")
        connection.execute("DELETE FROM aspca_selections")
        connection.execute("DELETE FROM aspca_pets")
        connection.execute("DELETE FROM aspca_quotes")
        backend.lifecycle.reset_embedded(
            connection,
            confirm_site_id=SITE_ID,
        )

    auth.reset_site_state(site_reset=_site_reset, seed_accounts=[])


# ---------------------------------------------------------------------------
# quotes
# ---------------------------------------------------------------------------


def _quote_number(row_id: int) -> str:
    return f"WB{100000 + row_id}"


def _policy_number(quote_row_id: int) -> str:
    return f"APH-{quote_row_id:06d}"


def _pet_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "pet_id": row["id"],
        "species": row["species"],
        "name": row["name"],
        "age_label": row["age_label"],
        "gender": row["gender"],
        "breed": row["breed"],
    }


def _selection_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "annual_limit": row["annual_limit"],
        "deductible": row["deductible"],
        "reimbursement": row["reimbursement"],
        "preventive": row["preventive"],
        "monthly": row["monthly"],
        "preventive_monthly": row["preventive_monthly"],
        "provenance": row["provenance"],
    }


def create_quote(pet: dict[str, str], email: str, zip_code: str) -> dict[str, Any]:
    """Create a quote with its first pet and the default rating selection."""

    reject_payment_keys(pet)
    default = rating.rate(5000, 500, 80, None)
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO aspca_quotes (quote_number, email, zip, created_at)"
            " VALUES ('', ?, ?, ?)",
            (email, zip_code, FROZEN_CLOCK_UTC),
        )
        quote_row_id = cursor.lastrowid
        connection.execute(
            "UPDATE aspca_quotes SET quote_number = ? WHERE id = ?",
            (_quote_number(quote_row_id), quote_row_id),
        )
        pet_row = connection.execute(
            "INSERT INTO aspca_pets"
            " (quote_id, species, name, age_label, gender, breed, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                quote_row_id,
                pet["species"],
                pet["name"],
                pet["age_label"],
                pet["gender"],
                pet["breed"],
                FROZEN_CLOCK_UTC,
            ),
        )
        connection.execute(
            "INSERT INTO aspca_selections"
            " (pet_id, annual_limit, deductible, reimbursement, preventive,"
            "  monthly, preventive_monthly, provenance, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pet_row.lastrowid,
                default["annual_limit"],
                default["deductible"],
                default["reimbursement"],
                None,
                default["monthly"],
                default["preventive_monthly"],
                default["provenance"],
                FROZEN_CLOCK_UTC,
            ),
        )
    return get_quote(_quote_number(quote_row_id))  # type: ignore[return-value]


def _quote_row(
    connection: sqlite3.Connection, quote_number: str
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM aspca_quotes WHERE quote_number = ?", (quote_number,)
    ).fetchone()


def get_quote(quote_number: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        quote = _quote_row(connection, quote_number)
        if quote is None:
            return None
        pets = []
        for pet_row in connection.execute(
            "SELECT * FROM aspca_pets WHERE quote_id = ? ORDER BY id",
            (quote["id"],),
        ):
            selection = connection.execute(
                "SELECT * FROM aspca_selections WHERE pet_id = ?",
                (pet_row["id"],),
            ).fetchone()
            entry = _pet_public(pet_row)
            entry["selection"] = _selection_public(selection)
            pets.append(entry)
        enrollment = connection.execute(
            "SELECT policy_number, frequency, paperless, created_at,"
            " payment_flow_id, payment_attempt_id, amount_minor, currency, mail_id"
            " FROM aspca_enrollments WHERE quote_id = ?",
            (quote["id"],),
        ).fetchone()
        return {
            "quote_id": quote["quote_number"],
            "email": quote["email"],
            "zip": quote["zip"],
            "status": quote["status"],
            "created_at": quote["created_at"],
            "pets": pets,
            "tiers": rating.tiers(),
            "enrollment": (
                {
                    "policy_number": enrollment["policy_number"],
                    "frequency": enrollment["frequency"],
                    "paperless": bool(enrollment["paperless"]),
                    "created_at": enrollment["created_at"],
                    "payment": {
                        "flow_id": enrollment["payment_flow_id"],
                        "attempt_id": enrollment["payment_attempt_id"],
                        "amount_minor": enrollment["amount_minor"],
                        "currency": enrollment["currency"],
                        "is_simulation": True,
                    },
                    "mail_id": enrollment["mail_id"],
                }
                if enrollment is not None
                else None
            ),
        }


def find_quote(email: str, zip_code: str) -> dict[str, Any] | None:
    """Resume lookup: newest open quote for the email + ZIP pair."""

    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT quote_number FROM aspca_quotes"
            " WHERE email = ? AND zip = ? ORDER BY id DESC LIMIT 1",
            (email, zip_code),
        ).fetchone()
    if row is None:
        return None
    return get_quote(row["quote_number"])


def add_pet(quote_number: str, pet: dict[str, str]) -> dict[str, Any] | None:
    reject_payment_keys(pet)
    default = rating.rate(5000, 500, 80, None)
    with closing(connect()) as connection, connection:
        quote = _quote_row(connection, quote_number)
        if quote is None:
            return None
        pet_row = connection.execute(
            "INSERT INTO aspca_pets"
            " (quote_id, species, name, age_label, gender, breed, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                quote["id"],
                pet["species"],
                pet["name"],
                pet["age_label"],
                pet["gender"],
                pet["breed"],
                FROZEN_CLOCK_UTC,
            ),
        )
        connection.execute(
            "INSERT INTO aspca_selections"
            " (pet_id, annual_limit, deductible, reimbursement, preventive,"
            "  monthly, preventive_monthly, provenance, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pet_row.lastrowid,
                default["annual_limit"],
                default["deductible"],
                default["reimbursement"],
                None,
                default["monthly"],
                default["preventive_monthly"],
                default["provenance"],
                FROZEN_CLOCK_UTC,
            ),
        )
    return get_quote(quote_number)


def apply_rate(
    quote_number: str,
    annual_limit: int,
    deductible: int,
    reimbursement: int,
    preventive: str | None,
    pet_id: int | None = None,
) -> dict[str, Any] | None:
    """Re-price one pet's custom selection (defaults to the first pet)."""

    priced = rating.rate(annual_limit, deductible, reimbursement, preventive)
    with closing(connect()) as connection, connection:
        quote = _quote_row(connection, quote_number)
        if quote is None:
            return None
        if pet_id is None:
            pet = connection.execute(
                "SELECT id FROM aspca_pets WHERE quote_id = ? ORDER BY id LIMIT 1",
                (quote["id"],),
            ).fetchone()
        else:
            pet = connection.execute(
                "SELECT id FROM aspca_pets WHERE quote_id = ? AND id = ?",
                (quote["id"], pet_id),
            ).fetchone()
        if pet is None:
            return None
        connection.execute(
            "UPDATE aspca_selections SET annual_limit = ?, deductible = ?,"
            " reimbursement = ?, preventive = ?, monthly = ?,"
            " preventive_monthly = ?, provenance = ?, updated_at = ?"
            " WHERE pet_id = ?",
            (
                priced["annual_limit"],
                priced["deductible"],
                priced["reimbursement"],
                priced["preventive"],
                priced["monthly"],
                priced["preventive_monthly"],
                priced["provenance"],
                FROZEN_CLOCK_UTC,
                pet["id"],
            ),
        )
    return priced


def enroll(
    quote_number: str,
    contact: dict[str, str],
    frequency: str,
    agree_terms: bool,
    paperless: bool,
    scenario_id: str,
) -> dict[str, Any] | None:
    """Attempt local payment and atomically create policy + local mail."""

    reject_payment_keys(contact)
    if frequency not in ("Monthly", "Annually"):
        raise ValueError("frequency must be Monthly or Annually")
    if not agree_terms:
        raise ValueError("agree_terms must be accepted")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("scenario_id is required")

    backend, _auth = services()
    with backend.lifecycle.connection(transaction=True) as connection:
        quote = _quote_row(connection, quote_number)
        if quote is None:
            return None
        existing = connection.execute(
            "SELECT * FROM aspca_enrollments WHERE quote_id = ?",
            (quote["id"],),
        ).fetchone()
        if existing is not None:
            return _enrollment_result(connection, existing, already=True)

        facts = _payment_facts(
            connection,
            quote,
            contact=contact,
            frequency=frequency,
        )
        flow = backend.payments.create_intent(
            owner=facts["owner"],
            amount_minor=facts["amount_minor"],
            currency=facts["currency"],
            fingerprint=facts["fingerprint"],
            idempotency_key=(
                f"aspca.create:{quote_number}:{facts['fingerprint']}"
            ),
            connection=connection,
        )
        attempt = backend.payments.attempt(
            flow_id=flow["flow_id"],
            owner=facts["owner"],
            amount_minor=facts["amount_minor"],
            currency=facts["currency"],
            fingerprint=facts["fingerprint"],
            scenario_id=scenario_id,
            idempotency_key=(
                f"aspca.attempt:{quote_number}:"
                f"{facts['fingerprint'][:32]}:{scenario_id}"
            ),
            connection=connection,
        )
        if attempt["status"] != "APPROVED":
            return {
                "enrolled": False,
                "payment": _payment_result(flow, attempt),
            }

        consumed = backend.payments.consume_approval(
            connection,
            flow_id=flow["flow_id"],
            owner=facts["owner"],
            amount_minor=facts["amount_minor"],
            currency=facts["currency"],
            fingerprint=facts["fingerprint"],
        )
        policy_number = _policy_number(quote["id"])
        connection.execute(
            "INSERT INTO aspca_enrollments"
            " (quote_id, policy_number, contact_json, frequency, agree_terms,"
            "  paperless, created_at, payment_flow_id, payment_attempt_id,"
            "  amount_minor, currency, fingerprint)"
            " VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
            (
                quote["id"],
                policy_number,
                json.dumps(contact, sort_keys=True),
                frequency,
                1 if paperless else 0,
                FROZEN_CLOCK_UTC,
                flow["flow_id"],
                consumed["attempt_id"],
                facts["amount_minor"],
                facts["currency"],
                facts["fingerprint"],
            ),
        )
        connection.execute(
            "UPDATE aspca_quotes SET status = 'enrolled' WHERE id = ?",
            (quote["id"],),
        )
        mail = backend.mail.enqueue(
            "policy-confirmation",
            facts["recipient"],
            {
                "policy_number": policy_number,
                "pet_name": facts["pet_name"],
                "frequency": frequency,
                "amount": f"{Decimal(facts['amount_minor']) / Decimal(100):.2f}",
                "currency": facts["currency"],
            },
            idempotency_key=f"aspca.mail:{policy_number}",
            simulation=True,
            connection=connection,
        )
        connection.execute(
            "UPDATE aspca_enrollments SET mail_id = ? WHERE quote_id = ?",
            (mail["mail_id"], quote["id"]),
        )
        enrollment = connection.execute(
            "SELECT * FROM aspca_enrollments WHERE quote_id = ?",
            (quote["id"],),
        ).fetchone()
        return _enrollment_result(connection, enrollment, already=False)


def _minor_units(value: str) -> int:
    amount = Decimal(value) * 100
    if amount != amount.to_integral_value():
        raise ValueError("quoted amount must have integer minor units")
    return int(amount)


def _payment_facts(
    connection: sqlite3.Connection,
    quote: sqlite3.Row,
    *,
    contact: dict[str, str],
    frequency: str,
) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT p.id, p.species, p.name, p.age_label, p.gender, p.breed,"
        " s.annual_limit, s.deductible, s.reimbursement, s.preventive,"
        " s.monthly, s.preventive_monthly"
        " FROM aspca_pets AS p"
        " JOIN aspca_selections AS s ON s.pet_id = p.id"
        " WHERE p.quote_id = ? ORDER BY p.id",
        (quote["id"],),
    ).fetchall()
    monthly_minor = sum(
        _minor_units(row["monthly"]) + _minor_units(row["preventive_monthly"])
        for row in rows
    )
    amount_minor = monthly_minor if frequency == "Monthly" else monthly_minor * 12
    recipient = str(contact.get("email") or quote["email"]).strip().casefold()
    snapshot = {
        "site_id": SITE_ID,
        "quote_id": quote["quote_number"],
        "frequency": frequency,
        "contact_email": recipient,
        "pets": [
            {
                "pet_id": row["id"],
                "species": row["species"],
                "name": row["name"],
                "age_label": row["age_label"],
                "gender": row["gender"],
                "breed": row["breed"],
                "annual_limit": row["annual_limit"],
                "deductible": row["deductible"],
                "reimbursement": row["reimbursement"],
                "preventive": row["preventive"],
                "monthly": row["monthly"],
                "preventive_monthly": row["preventive_monthly"],
            }
            for row in rows
        ],
        "amount_minor": amount_minor,
        "currency": "USD",
    }
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    names = [str(row["name"]) for row in rows]
    return {
        "owner": f"quote:{quote['quote_number']}",
        "amount_minor": amount_minor,
        "currency": "USD",
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "recipient": recipient,
        "pet_name": names[0] if len(names) == 1 else f"{names[0]} + {len(names) - 1} more",
    }


def _payment_result(flow: sqlite3.Row | dict, attempt: sqlite3.Row | dict) -> dict[str, Any]:
    return {
        "flow_id": flow["flow_id"],
        "attempt_id": attempt["attempt_id"],
        "status": attempt["status"],
        "amount_minor": int(flow["amount_minor"]),
        "currency": flow["currency"],
        "is_simulation": bool(flow["is_simulation"]),
    }


def _enrollment_result(
    connection: sqlite3.Connection,
    enrollment: sqlite3.Row,
    *,
    already: bool,
) -> dict[str, Any]:
    flow = connection.execute(
        "SELECT * FROM websitebench_payment_flows WHERE flow_id = ?",
        (enrollment["payment_flow_id"],),
    ).fetchone()
    attempt = connection.execute(
        "SELECT * FROM websitebench_payment_attempts WHERE attempt_id = ?",
        (enrollment["payment_attempt_id"],),
    ).fetchone()
    mail = connection.execute(
        "SELECT * FROM websitebench_mail_jobs WHERE mail_id = ?",
        (enrollment["mail_id"],),
    ).fetchone()
    return {
        "policy_number": enrollment["policy_number"],
        "already": already,
        "enrolled": True,
        "payment": {
            **_payment_result(flow, attempt),
            "status": flow["status"],
        },
        "mail": {
            "mail_id": mail["mail_id"],
            "purpose": mail["purpose"],
            "status": mail["status"],
            "is_simulation": bool(mail["is_simulation"]),
        },
    }
