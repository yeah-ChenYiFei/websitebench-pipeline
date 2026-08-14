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

Payment boundary: the source funnel was never advanced past plan selection /
contact checkout, so this schema carries ZERO payment fields and the insert
paths reject any card-like key defensively.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import closing
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
}

# Defensive payment-boundary guard: no key that looks like a payment field may
# ever enter the business tables (the source funnel stopped before payment).
_PAYMENT_KEY_RE = re.compile(
    r"(?i)(card|cc[-_]?(num|number|exp)|cvv|cvc|pan\b|iban|routing|account[-_]?number"
    r"|expir|security[-_]?code|payment[-_]?(method|token)|stripe|bank)"
)


class PaymentFieldRejected(ValueError):
    """A card/payment-like key reached a business insert path."""


def reject_payment_keys(payload: dict[str, Any]) -> None:
    for key in payload:
        if _PAYMENT_KEY_RE.search(str(key)):
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
    """Delete business rows and library auth state atomically; keep schema."""

    _backend, auth = services()

    def _site_reset(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM aspca_enrollments")
        connection.execute("DELETE FROM aspca_selections")
        connection.execute("DELETE FROM aspca_pets")
        connection.execute("DELETE FROM aspca_quotes")

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
            "SELECT policy_number, frequency, paperless, created_at"
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
) -> dict[str, Any] | None:
    """Record an enrollment (contact + billing frequency; NO payment data)."""

    reject_payment_keys(contact)
    if frequency not in ("Monthly", "Annually"):
        raise ValueError("frequency must be Monthly or Annually")
    if not agree_terms:
        raise ValueError("agree_terms must be accepted")
    import json as _json

    with closing(connect()) as connection, connection:
        quote = _quote_row(connection, quote_number)
        if quote is None:
            return None
        existing = connection.execute(
            "SELECT policy_number FROM aspca_enrollments WHERE quote_id = ?",
            (quote["id"],),
        ).fetchone()
        if existing is not None:
            return {"policy_number": existing["policy_number"], "already": True}
        policy_number = _policy_number(quote["id"])
        connection.execute(
            "INSERT INTO aspca_enrollments"
            " (quote_id, policy_number, contact_json, frequency, agree_terms,"
            "  paperless, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?, ?)",
            (
                quote["id"],
                policy_number,
                _json.dumps(contact, sort_keys=True),
                frequency,
                1 if paperless else 0,
                FROZEN_CLOCK_UTC,
            ),
        )
        connection.execute(
            "UPDATE aspca_quotes SET status = 'enrolled' WHERE id = ?",
            (quote["id"],),
        )
    return {"policy_number": policy_number, "already": False}
