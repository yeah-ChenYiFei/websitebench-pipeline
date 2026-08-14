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
    "0005_quote_application": """
        CREATE TABLE IF NOT EXISTS aspca_quote_applications (
            quote_id INTEGER PRIMARY KEY
                REFERENCES aspca_quotes (id) ON DELETE CASCADE,
            contact_json TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            consent_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """,
    "0006_member_center": """
        CREATE TABLE IF NOT EXISTS aspca_member_profiles (
            account_id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            display_name TEXT NOT NULL,
            phone TEXT,
            address_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS aspca_policy_state (
            policy_number TEXT PRIMARY KEY
                REFERENCES aspca_enrollments (policy_number) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'canceled')),
            autopay INTEGER NOT NULL DEFAULT 0 CHECK (autopay IN (0, 1)),
            renewal_date TEXT NOT NULL,
            renewal_count INTEGER NOT NULL DEFAULT 0,
            canceled_at TEXT,
            cancel_reason TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS aspca_policy_documents (
            document_id TEXT PRIMARY KEY,
            policy_number TEXT NOT NULL
                REFERENCES aspca_enrollments (policy_number) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (policy_number, kind)
        );
        CREATE TABLE IF NOT EXISTS aspca_uploads (
            id INTEGER PRIMARY KEY,
            upload_id TEXT NOT NULL UNIQUE,
            account_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            parse_status TEXT NOT NULL
                CHECK (parse_status IN ('parsed', 'rejected')),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_aspca_uploads_account
            ON aspca_uploads (account_id);
        CREATE TABLE IF NOT EXISTS aspca_claims (
            id INTEGER PRIMARY KEY,
            claim_number TEXT NOT NULL UNIQUE,
            policy_number TEXT NOT NULL
                REFERENCES aspca_enrollments (policy_number) ON DELETE CASCADE,
            account_id TEXT NOT NULL,
            incident_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            provider TEXT NOT NULL,
            amount_minor INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'submitted'
                CHECK (status IN ('submitted', 'in-review', 'complete')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_aspca_claims_account
            ON aspca_claims (account_id);
        CREATE TABLE IF NOT EXISTS aspca_claim_uploads (
            claim_id INTEGER NOT NULL
                REFERENCES aspca_claims (id) ON DELETE CASCADE,
            upload_id TEXT NOT NULL
                REFERENCES aspca_uploads (upload_id) ON DELETE CASCADE,
            PRIMARY KEY (claim_id, upload_id)
        );
        CREATE TABLE IF NOT EXISTS aspca_policy_events (
            id INTEGER PRIMARY KEY,
            policy_number TEXT NOT NULL
                REFERENCES aspca_enrollments (policy_number) ON DELETE CASCADE,
            action TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_aspca_policy_events_policy
            ON aspca_policy_events (policy_number);
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
        # Backfill member-center baselines for policies enrolled before this
        # migration. Historical enrollment, payment and mail identifiers stay
        # untouched.
        connection.execute(
            "INSERT OR IGNORE INTO aspca_policy_state"
            " (policy_number, status, autopay, renewal_date, renewal_count,"
            "  updated_at)"
            " SELECT policy_number, 'active', 0, '2027-08-13', 0, ?"
            " FROM aspca_enrollments",
            (FROZEN_CLOCK_UTC,),
        )
        for kind, title in (
            ("policy", "Policy document"),
            ("coverage-summary", "Coverage summary"),
        ):
            connection.execute(
                "INSERT OR IGNORE INTO aspca_policy_documents"
                " (document_id, policy_number, kind, title, created_at)"
                " SELECT 'DOC-' || policy_number || '-' || ?, policy_number,"
                " ?, ?, ? FROM aspca_enrollments",
                (kind, kind, title, FROZEN_CLOCK_UTC),
            )


def reset() -> None:
    """Delete all site business, payment, mail and auth rows atomically."""

    backend, auth = services()

    def _site_reset(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM aspca_claim_uploads")
        connection.execute("DELETE FROM aspca_claims")
        connection.execute("DELETE FROM aspca_uploads")
        connection.execute("DELETE FROM aspca_policy_events")
        connection.execute("DELETE FROM aspca_policy_documents")
        connection.execute("DELETE FROM aspca_policy_state")
        connection.execute("DELETE FROM aspca_member_profiles")
        connection.execute("DELETE FROM aspca_quote_applications")
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
            "state": rating.checkout_state(quote["zip"]),
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
        connection.execute(
            "INSERT INTO aspca_policy_state"
            " (policy_number, status, autopay, renewal_date, renewal_count,"
            "  updated_at) VALUES (?, 'active', 0, '2027-08-13', 0, ?)",
            (policy_number, FROZEN_CLOCK_UTC),
        )
        for kind, title in (
            ("policy", "Policy document"),
            ("coverage-summary", "Coverage summary"),
        ):
            connection.execute(
                "INSERT INTO aspca_policy_documents"
                " (document_id, policy_number, kind, title, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    f"DOC-{policy_number}-{kind}",
                    policy_number,
                    kind,
                    title,
                    FROZEN_CLOCK_UTC,
                ),
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


# ---------------------------------------------------------------------------
# application review + member center
# ---------------------------------------------------------------------------


def get_application(quote_number: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        quote = _quote_row(connection, quote_number)
        if quote is None:
            return None
        row = connection.execute(
            "SELECT * FROM aspca_quote_applications WHERE quote_id = ?",
            (quote["id"],),
        ).fetchone()
    if row is None:
        return {
            "quote_id": quote_number,
            "contact": {},
            "questions": {},
            "consent": {},
            "review_ready": False,
            "updated_at": None,
        }
    return {
        "quote_id": quote_number,
        "contact": json.loads(row["contact_json"]),
        "questions": json.loads(row["questions_json"]),
        "consent": json.loads(row["consent_json"]),
        "review_ready": True,
        "updated_at": row["updated_at"],
    }


def save_application(
    quote_number: str,
    *,
    contact: dict[str, Any],
    questions: dict[str, Any],
    consent: dict[str, Any],
) -> dict[str, Any] | None:
    reject_payment_keys(contact)
    with closing(connect()) as connection, connection:
        quote = _quote_row(connection, quote_number)
        if quote is None:
            return None
        connection.execute(
            "INSERT INTO aspca_quote_applications"
            " (quote_id, contact_json, questions_json, consent_json, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(quote_id) DO UPDATE SET contact_json=excluded.contact_json,"
            " questions_json=excluded.questions_json,"
            " consent_json=excluded.consent_json, updated_at=excluded.updated_at",
            (
                quote["id"],
                json.dumps(contact, sort_keys=True),
                json.dumps(questions, sort_keys=True),
                json.dumps(consent, sort_keys=True),
                FROZEN_CLOCK_UTC,
            ),
        )
    return get_application(quote_number)


def create_member_subject(
    connection: sqlite3.Connection, registration: dict[str, Any]
) -> str:
    """Create the ASPCA profile inside LocalAuthStore's registration txn."""

    email = str(registration["email"])
    subject_id = f"aspca-member-{hashlib.sha256(email.encode()).hexdigest()[:20]}"
    connection.execute(
        "INSERT INTO aspca_member_profiles"
        " (account_id, subject_id, email, display_name, address_json, updated_at)"
        " VALUES (?, ?, ?, ?, '{}', ?)",
        (
            registration["account_id"],
            subject_id,
            email,
            registration["display_name"],
            FROZEN_CLOCK_UTC,
        ),
    )
    return subject_id


def ensure_member_profile(account: dict[str, Any]) -> dict[str, Any]:
    with closing(connect()) as connection, connection:
        connection.execute(
            "INSERT OR IGNORE INTO aspca_member_profiles"
            " (account_id, subject_id, email, display_name, address_json, updated_at)"
            " VALUES (?, ?, ?, ?, '{}', ?)",
            (
                account["account_id"],
                account["subject_id"],
                account["email_normalized"],
                account["display_name"],
                FROZEN_CLOCK_UTC,
            ),
        )
        row = connection.execute(
            "SELECT * FROM aspca_member_profiles WHERE account_id = ?",
            (account["account_id"],),
        ).fetchone()
    assert row is not None
    return {
        "account_id": row["account_id"],
        "subject_id": row["subject_id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "phone": row["phone"],
        "address": json.loads(row["address_json"]),
        "updated_at": row["updated_at"],
    }


def _owned_policy_row(
    connection: sqlite3.Connection, email: str, policy_number: str
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT e.*, q.email, q.zip, ps.status AS policy_status,"
        " ps.autopay, ps.renewal_date, ps.renewal_count, ps.canceled_at,"
        " ps.cancel_reason, p.id AS pet_id, p.species, p.name, p.age_label,"
        " p.gender, p.breed, s.annual_limit, s.deductible, s.reimbursement,"
        " s.preventive, s.monthly, s.preventive_monthly, s.provenance"
        " FROM aspca_enrollments AS e"
        " JOIN aspca_quotes AS q ON q.id = e.quote_id"
        " JOIN aspca_policy_state AS ps ON ps.policy_number = e.policy_number"
        " JOIN aspca_pets AS p ON p.quote_id = q.id"
        " JOIN aspca_selections AS s ON s.pet_id = p.id"
        " WHERE e.policy_number = ? AND lower(q.email) = lower(?)"
        " ORDER BY p.id LIMIT 1",
        (policy_number, email),
    ).fetchone()


def _policy_public(row: sqlite3.Row) -> dict[str, Any]:
    holder = json.loads(row["contact_json"])
    coverage = {
        "annual_limit": row["annual_limit"],
        "deductible": row["deductible"],
        "reimbursement": row["reimbursement"],
        "preventive": row["preventive"],
        "monthly": row["monthly"],
        "preventive_monthly": row["preventive_monthly"],
        "provenance": row["provenance"],
    }
    return {
        "policy_number": row["policy_number"],
        "status": row["policy_status"],
        "effective_date": row["created_at"][:10],
        "renewal_date": row["renewal_date"],
        "renewal_eligible": row["policy_status"] == "active",
        "renewal_count": row["renewal_count"],
        "autopay": bool(row["autopay"]),
        "frequency": row["frequency"],
        "paperless": bool(row["paperless"]),
        "holder": holder,
        "insured": {
            "pet_id": row["pet_id"],
            "species": row["species"],
            "name": row["name"],
            "age_label": row["age_label"],
            "gender": row["gender"],
            "breed": row["breed"],
        },
        "pet": {
            "pet_id": row["pet_id"],
            "species": row["species"],
            "name": row["name"],
            "age_label": row["age_label"],
            "gender": row["gender"],
            "breed": row["breed"],
        },
        "coverage": coverage,
        "cancel": {
            "canceled_at": row["canceled_at"],
            "reason": row["cancel_reason"],
        },
        "available_actions": (
            ["update-coverage", "billing", "renew", "cancel", "start-claim"]
            if row["policy_status"] == "active"
            else ["documents", "claim-status", "support"]
        ),
    }


def policy_detail(email: str, policy_number: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = _owned_policy_row(connection, email, policy_number)
        return _policy_public(row) if row is not None else None


def member_dashboard(account: dict[str, Any]) -> dict[str, Any]:
    email = str(account["email_normalized"])
    ensure_member_profile(account)
    with closing(connect()) as connection:
        numbers = connection.execute(
            "SELECT e.policy_number FROM aspca_enrollments AS e"
            " JOIN aspca_quotes AS q ON q.id = e.quote_id"
            " WHERE lower(q.email) = lower(?) ORDER BY e.id DESC",
            (email,),
        ).fetchall()
        policies = []
        for number in numbers:
            row = _owned_policy_row(connection, email, number["policy_number"])
            if row is not None:
                policies.append(_policy_public(row))
        claim_rows = connection.execute(
            "SELECT status, count(*) AS count FROM aspca_claims"
            " WHERE account_id = ? GROUP BY status",
            (account["account_id"],),
        ).fetchall()
    claim_counts = {row["status"]: row["count"] for row in claim_rows}
    return {
        "account": account,
        "policies": policies,
        "metrics": {
            "active_policies": sum(p["status"] == "active" for p in policies),
            "total_policies": len(policies),
            "open_claims": sum(
                claim_counts.get(status, 0) for status in ("submitted", "in-review")
            ),
        },
    }


def _policy_event(
    connection: sqlite3.Connection,
    policy_number: str,
    action: str,
    details: dict[str, Any],
) -> None:
    connection.execute(
        "INSERT INTO aspca_policy_events"
        " (policy_number, action, details_json, created_at) VALUES (?, ?, ?, ?)",
        (policy_number, action, json.dumps(details, sort_keys=True), FROZEN_CLOCK_UTC),
    )


def update_policy_coverage(
    email: str,
    policy_number: str,
    *,
    annual_limit: int,
    deductible: int,
    reimbursement: int,
    preventive: str | None,
) -> dict[str, Any] | None:
    priced = rating.rate(
        annual_limit, deductible, reimbursement, preventive
    )
    with closing(connect()) as connection, connection:
        row = _owned_policy_row(connection, email, policy_number)
        if row is None:
            return None
        if row["policy_status"] != "active":
            raise ValueError("canceled policies cannot be updated")
        connection.execute(
            "UPDATE aspca_selections SET annual_limit=?, deductible=?,"
            " reimbursement=?, preventive=?, monthly=?, preventive_monthly=?,"
            " provenance=?, updated_at=? WHERE pet_id=?",
            (
                priced["annual_limit"],
                priced["deductible"],
                priced["reimbursement"],
                priced["preventive"],
                priced["monthly"],
                priced["preventive_monthly"],
                priced["provenance"],
                FROZEN_CLOCK_UTC,
                row["pet_id"],
            ),
        )
        _policy_event(connection, policy_number, "coverage-updated", priced)
    return policy_detail(email, policy_number)


def update_policy_billing(
    email: str,
    policy_number: str,
    *,
    autopay: bool,
    frequency: str,
) -> dict[str, Any] | None:
    if frequency not in {"Monthly", "Annually"}:
        raise ValueError("frequency must be Monthly or Annually")
    with closing(connect()) as connection, connection:
        row = _owned_policy_row(connection, email, policy_number)
        if row is None:
            return None
        if row["policy_status"] != "active":
            raise ValueError("billing cannot be changed for a canceled policy")
        monthly = Decimal(row["monthly"]) + Decimal(row["preventive_monthly"])
        total = monthly if frequency == "Monthly" else monthly * 12
        connection.execute(
            "UPDATE aspca_enrollments SET frequency=? WHERE policy_number=?",
            (frequency, policy_number),
        )
        connection.execute(
            "UPDATE aspca_policy_state SET autopay=?, updated_at=?"
            " WHERE policy_number=?",
            (1 if autopay else 0, FROZEN_CLOCK_UTC, policy_number),
        )
        _policy_event(
            connection,
            policy_number,
            "billing-updated",
            {"autopay": autopay, "frequency": frequency, "total": f"{total:.2f}"},
        )
    return {
        "policy_number": policy_number,
        "autopay": autopay,
        "frequency": frequency,
        "total": f"{total:.2f}",
        "currency": "USD",
        "payment_profile": "local-sandbox",
    }


def policy_documents(email: str, policy_number: str) -> list[dict[str, Any]] | None:
    with closing(connect()) as connection:
        if _owned_policy_row(connection, email, policy_number) is None:
            return None
        rows = connection.execute(
            "SELECT * FROM aspca_policy_documents WHERE policy_number=?"
            " ORDER BY kind",
            (policy_number,),
        ).fetchall()
    return [
        {
            "document_id": row["document_id"],
            "policy_number": row["policy_number"],
            "kind": row["kind"],
            "title": row["title"],
            "created_at": row["created_at"],
            "download_url": f"/portal/api/documents/{row['document_id']}/download",
        }
        for row in rows
    ]


def owned_document(account: dict[str, Any], document_id: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT d.* FROM aspca_policy_documents AS d"
            " JOIN aspca_enrollments AS e ON e.policy_number=d.policy_number"
            " JOIN aspca_quotes AS q ON q.id=e.quote_id"
            " WHERE d.document_id=? AND lower(q.email)=lower(?)",
            (document_id, account["email_normalized"]),
        ).fetchone()
    return dict(row) if row is not None else None


def create_upload(
    account_id: str, *, filename: str, content_type: str, size_bytes: int
) -> dict[str, Any]:
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO aspca_uploads"
            " (upload_id, account_id, filename, content_type, size_bytes,"
            "  parse_status, created_at) VALUES ('', ?, ?, ?, ?, 'parsed', ?)",
            (account_id, filename, content_type, size_bytes, FROZEN_CLOCK_UTC),
        )
        upload_id = f"UPL-{cursor.lastrowid:06d}"
        connection.execute(
            "UPDATE aspca_uploads SET upload_id=? WHERE id=?",
            (upload_id, cursor.lastrowid),
        )
    return {
        "upload_id": upload_id,
        "filename": filename,
        "content_type": content_type,
        "size": size_bytes,
        "parse_status": "parsed",
        "progress": 100,
    }


def create_claim(
    account: dict[str, Any],
    *,
    policy_number: str,
    incident_date: str,
    reason: str,
    provider: str,
    amount_minor: int,
    upload_id: str | None,
) -> dict[str, Any] | None:
    with closing(connect()) as connection, connection:
        policy = _owned_policy_row(
            connection, account["email_normalized"], policy_number
        )
        if policy is None:
            return None
        if policy["policy_status"] != "active":
            raise ValueError("claims cannot be started for a canceled policy")
        upload = None
        if upload_id:
            upload = connection.execute(
                "SELECT * FROM aspca_uploads WHERE upload_id=? AND account_id=?",
                (upload_id, account["account_id"]),
            ).fetchone()
            if upload is None:
                raise ValueError("upload is missing or belongs to another account")
        cursor = connection.execute(
            "INSERT INTO aspca_claims"
            " (claim_number, policy_number, account_id, incident_date, reason,"
            "  provider, amount_minor, status, created_at, updated_at)"
            " VALUES ('', ?, ?, ?, ?, ?, ?, 'submitted', ?, ?)",
            (
                policy_number,
                account["account_id"],
                incident_date,
                reason,
                provider,
                amount_minor,
                FROZEN_CLOCK_UTC,
                FROZEN_CLOCK_UTC,
            ),
        )
        claim_number = f"CLM-{cursor.lastrowid:06d}"
        connection.execute(
            "UPDATE aspca_claims SET claim_number=? WHERE id=?",
            (claim_number, cursor.lastrowid),
        )
        if upload is not None:
            connection.execute(
                "INSERT INTO aspca_claim_uploads (claim_id, upload_id) VALUES (?, ?)",
                (cursor.lastrowid, upload_id),
            )
    return claim_detail(account["account_id"], claim_number)


def _claim_public(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    evidence = [
        {
            "upload_id": upload["upload_id"],
            "filename": upload["filename"],
            "content_type": upload["content_type"],
            "size": upload["size_bytes"],
            "parse_status": upload["parse_status"],
        }
        for upload in connection.execute(
            "SELECT u.* FROM aspca_uploads AS u"
            " JOIN aspca_claim_uploads AS cu ON cu.upload_id=u.upload_id"
            " WHERE cu.claim_id=? ORDER BY u.id",
            (row["id"],),
        )
    ]
    return {
        "claim_number": row["claim_number"],
        "policy_number": row["policy_number"],
        "incident_date": row["incident_date"],
        "reason": row["reason"],
        "provider": row["provider"],
        "amount": f"{Decimal(row['amount_minor']) / Decimal(100):.2f}",
        "currency": "USD",
        "status": row["status"],
        "evidence": evidence,
        "available_actions": ["view-policy", "upload-evidence", "contact-support"],
    }


def claim_detail(account_id: str, claim_number: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM aspca_claims WHERE claim_number=? AND account_id=?",
            (claim_number, account_id),
        ).fetchone()
        return _claim_public(connection, row) if row is not None else None


def member_claims(account_id: str) -> dict[str, Any]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM aspca_claims WHERE account_id=? ORDER BY id DESC",
            (account_id,),
        ).fetchall()
        claims = [_claim_public(connection, row) for row in rows]
    return {
        "claims": claims,
        "metrics": {
            "submitted": sum(c["status"] == "submitted" for c in claims),
            "in_review": sum(c["status"] == "in-review" for c in claims),
            "complete": sum(c["status"] == "complete" for c in claims),
        },
    }


def renew_policy(email: str, policy_number: str) -> dict[str, Any] | None:
    with closing(connect()) as connection, connection:
        row = _owned_policy_row(connection, email, policy_number)
        if row is None:
            return None
        if row["policy_status"] != "active":
            raise ValueError("canceled policies are not renewal eligible")
        renewal_count = int(row["renewal_count"]) + 1
        renewal_date = f"{2027 + renewal_count:04d}-08-13"
        connection.execute(
            "UPDATE aspca_policy_state SET renewal_count=?, renewal_date=?,"
            " updated_at=? WHERE policy_number=?",
            (renewal_count, renewal_date, FROZEN_CLOCK_UTC, policy_number),
        )
        _policy_event(
            connection,
            policy_number,
            "renewed",
            {"renewal_count": renewal_count, "renewal_date": renewal_date},
        )
    detail = policy_detail(email, policy_number)
    assert detail is not None
    return {**detail, "renewed": True}


def cancel_policy(
    email: str, policy_number: str, *, reason: str
) -> dict[str, Any] | None:
    with closing(connect()) as connection, connection:
        row = _owned_policy_row(connection, email, policy_number)
        if row is None:
            return None
        if row["policy_status"] != "canceled":
            connection.execute(
                "UPDATE aspca_policy_state SET status='canceled',"
                " canceled_at=?, cancel_reason=?, updated_at=?"
                " WHERE policy_number=?",
                (FROZEN_CLOCK_UTC, reason, FROZEN_CLOCK_UTC, policy_number),
            )
            _policy_event(
                connection, policy_number, "canceled", {"reason": reason}
            )
    detail = policy_detail(email, policy_number)
    assert detail is not None
    return detail
