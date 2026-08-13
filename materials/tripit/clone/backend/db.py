"""TripIt offline clone — persistent, site-isolated backend database layer.

This module owns the site's business schema, deterministic seed, and reset.
It sits on top of the vendored ``websitebench.site_backend`` runtime (which owns
accounts / sessions / OTP / mail outbox / payment ledger) and never duplicates
those library-owned tables.

Design contracts (frozen in ``scope/deterministic-seed.json``):

* One SQLite file under the runtime data dir holds *all* state (including
  document BLOBs), so migration-copy / reset / ephemeral semantics stay
  consistent.
* Migrations are db.py-owned and run outside the vendored hook mechanism
  (runtime declares ``migration_hook: null`` / ``seed_hook: null``). The ledger
  ``tripit_schema_migrations`` carries the five frozen ids
  ``0001_core_travel`` … ``0005_pro_payment_overlay``.
* The deterministic seed reproduces the exact entity counts and stable-row
  identities from the frozen manifest. Seeding happens once at first init
  (guarded by a meta marker) so user mutations survive restart; ``reset()``
  deletes business rows and reseeds atomically together with the library auth
  reset via ``LocalAuthStore.reset_site_state``.
* All timestamps are pinned to the frozen clock — no wall clock, no randomness —
  so identical operation sequences yield identical visible state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Mapping

from websitebench.site_backend import (
    PaymentConflict,
    PaymentError,
    PaymentRejected,
    SiteBackend,
    load_runtime,
)

# ---------------------------------------------------------------------------
# module constants
# ---------------------------------------------------------------------------

# materials/tripit  (this file is clone/backend/db.py -> parents[2] == site dir)
SITE_DIR = Path(__file__).resolve().parents[2]
SITE_ID = "tripit"
DB_FILENAME = "tripit.sqlite3"

# The single frozen clock for the whole clone (America/New_York, -04:00).
FROZEN_CLOCK = "2026-08-04T09:00:00-04:00"
FROZEN_CLOCK_UTC = "2026-08-04T13:00:00Z"
FROZEN_DATE = "2026-08-04"

# Attached documents are stored inline as BLOBs; the 2 MiB ceiling mirrors the
# ``byte_size`` CHECK on tripit_documents so the app-level guard and the schema
# agree on the same limit.
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

# Runtime data-dir selection, most specific first (mirrors the edx clone).
SITE_DATA_DIR_ENV = "WEBSITEBENCH_TRIPIT_DATA_DIR"
SHARED_DATA_DIR_ENV = "WEBSITEBENCH_DATA_DIR"
LEGACY_DATA_DIR_ENV = "CLAWBENCH_DATA_DIR"
DEFAULT_DATA_DIR_NAME = "runtime-data"

RUNTIME_ENV = "WEBSITEBENCH_SITE_BACKEND_RUNTIME"
DEPLOYED_DB_ENV = "WEBSITEBENCH_SITE_BACKEND_DATABASE"

# Mail-adapter selection, mirroring the payment-adapter contract: a direct
# override, then the deployment-supplied name, else the offline-harbor default.
MAIL_ADAPTER_ENV = "WEBSITEBENCH_MAIL_ADAPTER"
DEPLOYMENT_MAIL_ADAPTER_ENV = "MAIL_ADAPTER"
PAYMENT_ADAPTER_ENV = "WEBSITEBENCH_PAYMENT_ADAPTER"
DEPLOYMENT_PAYMENT_ADAPTER_ENV = "PAYMENT_ADAPTER"

# The twelve TripIt plan types (frozen feature floor).
PLAN_TYPES: tuple[str, ...] = (
    "air",
    "lodging",
    "car",
    "rail",
    "transport",
    "cruise",
    "restaurant",
    "meeting",
    "activity",
    "map",
    "directions",
    "note",
)

# Deterministic fixture accounts. These credentials are non-secret benchmark
# fixtures (documented in the backend gate / tests); they are never real users.
AUTH_FIXTURES: tuple[Mapping[str, Any], ...] = (
    {
        "subject_id": "traveler",
        "email": "traveler@example.com",
        "display_name": "Avery Chen",
        "password": "traveler-fixture-2027",
        "email_verified": True,
    },
    {
        "subject_id": "other",
        "email": "other@example.com",
        "display_name": "Jordan Lee",
        "password": "other-fixture-2027",
        "email_verified": True,
    },
)


# ---------------------------------------------------------------------------
# domain exceptions
# ---------------------------------------------------------------------------


class BackendError(Exception):
    """Base class for backend domain failures."""


class NotFound(BackendError):
    """Requested resource does not exist for this owner."""


class Forbidden(BackendError):
    """Resource exists but belongs to another owner."""


class ValidationError(BackendError):
    """Caller-supplied data violates a domain rule."""


class IdempotencyConflict(BackendError):
    """Same idempotency key was reused with a different payload."""


# ---------------------------------------------------------------------------
# runtime wiring
# ---------------------------------------------------------------------------


def _selected_data_dir() -> Path:
    """Resolve the runtime data directory, honoring the deployment contract."""

    deployed = os.environ.get(DEPLOYED_DB_ENV)
    if deployed:
        database_path = Path(deployed).resolve()
        if database_path.name != DB_FILENAME:
            raise BackendError(
                "deployed database filename does not match runtime contract"
            )
        directory = database_path.parent
    else:
        for env_name in (SITE_DATA_DIR_ENV, SHARED_DATA_DIR_ENV, LEGACY_DATA_DIR_ENV):
            value = os.environ.get(env_name)
            if value:
                directory = Path(value).resolve()
                break
        else:
            directory = (SITE_DIR / DEFAULT_DATA_DIR_NAME).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def data_dir() -> Path:
    return _selected_data_dir()


def database_path() -> Path:
    return _selected_data_dir() / DB_FILENAME


def runtime_path() -> Path:
    override = os.environ.get(RUNTIME_ENV)
    if override:
        return Path(override).resolve()
    return (SITE_DIR / "backend" / "runtime.json").resolve()


def runtime_config():
    config = load_runtime(runtime_path())
    if config.site_id != SITE_ID:
        raise BackendError(
            f"runtime site_id {config.site_id!r} does not match {SITE_ID!r}"
        )
    if config.database_filename != DB_FILENAME:
        raise BackendError(
            f"runtime database filename {config.database_filename!r} "
            f"does not match {DB_FILENAME!r}"
        )
    return config


_SITE_BACKENDS: dict[tuple[str, str], SiteBackend] = {}


def site_backend() -> SiteBackend:
    """Open (once per runtime+data-dir) the site-bound vendored backend."""

    config = runtime_config()
    selected = _selected_data_dir()
    key = (str(runtime_path()), str(selected))
    backend = _SITE_BACKENDS.get(key)
    if backend is None:
        # Passing the raw mapping (not the file path) leaves site_root unset so
        # the data_root override is honored (the edx / scaffold pattern).
        backend = SiteBackend.open(config.raw, data_root=selected)
        backend.lifecycle.initialize()
        _SITE_BACKENDS[key] = backend
    return backend


def mail_adapter() -> str:
    """Resolve the active mail adapter declared by the frozen runtime contract.

    Mirrors the payment-adapter resolution: honor an explicit override, then the
    deployment-injected name, else the offline-harbor default. Business mail is
    simulated (never delivered) under ``local-outbox``; ``redis-resend`` and
    ``effects-gateway`` are real delivery paths.
    """

    config = runtime_config()
    profiles = config.deployment["profiles"]
    allowed = {str(profile["mail_adapter"]) for profile in profiles.values()}
    default = str(profiles["offline-harbor"]["mail_adapter"])
    selected = os.environ.get(
        MAIL_ADAPTER_ENV,
        os.environ.get(DEPLOYMENT_MAIL_ADAPTER_ENV, default),
    ).strip()
    if selected not in allowed:
        raise BackendError("mail adapter is not declared by the runtime")
    return selected


def _mail_is_simulation() -> bool:
    """True when the active mail adapter records jobs without delivering them."""

    return mail_adapter() == "local-outbox"


def payment_adapter() -> str:
    """Resolve the active payment adapter declared by the frozen runtime.

    Mirrors :func:`mail_adapter`: honor an explicit override, then the
    deployment-injected name, else the offline-harbor default. Every declared
    profile currently pins ``local-sandbox``; ``stripe-test`` stays dormant
    until a payment-scope approval wires the ``stripe_test`` runtime block.
    """

    config = runtime_config()
    profiles = config.deployment["profiles"]
    allowed = {str(profile["payment_adapter"]) for profile in profiles.values()}
    default = str(profiles["offline-harbor"]["payment_adapter"])
    selected = os.environ.get(
        PAYMENT_ADAPTER_ENV,
        os.environ.get(DEPLOYMENT_PAYMENT_ADAPTER_ENV, default),
    ).strip()
    if selected not in allowed:
        raise BackendError("payment adapter is not declared by the runtime")
    return selected


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a business connection with the site's pragmas."""

    connection = sqlite3.connect(str(path or database_path()))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


# ---------------------------------------------------------------------------
# migrations
# ---------------------------------------------------------------------------


def _migration_0001_core_travel(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tripit_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- Auth-subject -> business-owner bridge. Independent of the vendored
        -- local_auth_accounts table (logical match on subject_id).
        CREATE TABLE IF NOT EXISTS business_subjects (
            subject_id   TEXT PRIMARY KEY,
            traveler_key TEXT NOT NULL UNIQUE,
            role         TEXT NOT NULL DEFAULT 'traveler',
            created_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tripit_traveler_profiles (
            traveler_key TEXT PRIMARY KEY
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            display_name TEXT NOT NULL,
            home_city    TEXT NOT NULL,
            home_airport TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tripit_trips (
            trip_id     TEXT PRIMARY KEY,
            owner_key   TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            slug        TEXT NOT NULL,
            name        TEXT NOT NULL,
            destination TEXT,
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            timezone    TEXT NOT NULL,
            image_key   TEXT,
            is_concur   INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            CHECK (end_date >= start_date),
            UNIQUE (owner_key, slug)
        );
        CREATE INDEX IF NOT EXISTS idx_tripit_trips_owner_start
            ON tripit_trips(owner_key, start_date);

        CREATE TABLE IF NOT EXISTS tripit_trip_travelers (
            trip_id      TEXT NOT NULL
                REFERENCES tripit_trips(trip_id) ON DELETE CASCADE,
            traveler_key TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            role         TEXT NOT NULL DEFAULT 'owner',
            created_at   TEXT NOT NULL,
            PRIMARY KEY (trip_id, traveler_key)
        );

        CREATE TABLE IF NOT EXISTS tripit_plans (
            plan_id      TEXT PRIMARY KEY,
            owner_key    TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            trip_id      TEXT
                REFERENCES tripit_trips(trip_id) ON DELETE CASCADE,
            plan_type    TEXT NOT NULL CHECK (plan_type IN (
                'air','lodging','car','rail','transport','cruise',
                'restaurant','meeting','activity','map','directions','note')),
            title        TEXT NOT NULL,
            start_ts_utc TEXT,
            end_ts_utc   TEXT,
            timezone     TEXT,
            sort_key     INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','canceled')),
            source       TEXT NOT NULL DEFAULT 'manual'
                CHECK (source IN ('manual','import')),
            natural_key  TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            UNIQUE (owner_key, natural_key)
        );
        CREATE INDEX IF NOT EXISTS idx_tripit_plans_trip_time
            ON tripit_plans(trip_id, start_ts_utc, sort_key);
        CREATE INDEX IF NOT EXISTS idx_tripit_plans_owner_trip
            ON tripit_plans(owner_key, trip_id);

        CREATE TABLE IF NOT EXISTS tripit_plan_segments (
            segment_id   TEXT PRIMARY KEY,
            plan_id      TEXT NOT NULL
                REFERENCES tripit_plans(plan_id) ON DELETE CASCADE,
            seq          INTEGER NOT NULL,
            start_ts_utc TEXT,
            end_ts_utc   TEXT,
            origin_code  TEXT,
            dest_code    TEXT,
            origin_tz    TEXT,
            dest_tz      TEXT,
            marker       TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE (plan_id, seq)
        );

        -- Owner-scoped idempotency ledger for state-changing form submissions.
        CREATE TABLE IF NOT EXISTS tripit_write_commands (
            owner_key       TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            payload_digest  TEXT NOT NULL,
            result_json     TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            PRIMARY KEY (owner_key, idempotency_key)
        );
        """
    )


def _migration_0002_sharing_documents(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tripit_trip_shares (
            share_id            TEXT PRIMARY KEY,
            trip_id             TEXT NOT NULL
                REFERENCES tripit_trips(trip_id) ON DELETE CASCADE,
            owner_key           TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            invitee_email       TEXT NOT NULL,
            invitee_key         TEXT
                REFERENCES business_subjects(traveler_key) ON DELETE SET NULL,
            role                TEXT NOT NULL
                CHECK (role IN ('viewer','editor','traveler')),
            show_sensitive      INTEGER NOT NULL DEFAULT 0,
            status              TEXT NOT NULL
                CHECK (status IN ('invited','active','revoked')),
            invite_token_digest TEXT UNIQUE,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            UNIQUE (trip_id, invitee_email)
        );

        -- Documents are stored as BLOBs so the single SQLite file is the whole
        -- state; oversized uploads are rejected (see the >2MB CHECK).
        CREATE TABLE IF NOT EXISTS tripit_documents (
            document_id  TEXT PRIMARY KEY,
            owner_key    TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            trip_id      TEXT
                REFERENCES tripit_trips(trip_id) ON DELETE CASCADE,
            plan_id      TEXT
                REFERENCES tripit_plans(plan_id) ON DELETE SET NULL,
            filename     TEXT NOT NULL,
            content_type TEXT NOT NULL,
            byte_size    INTEGER NOT NULL
                CHECK (byte_size >= 0 AND byte_size <= 2097152),
            sha256       TEXT NOT NULL,
            blob         BLOB NOT NULL,
            created_at   TEXT NOT NULL,
            UNIQUE (trip_id, filename)
        );
        """
    )


def _migration_0003_import_messages(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tripit_import_messages (
            message_id         TEXT PRIMARY KEY,
            owner_key          TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            fingerprint_sha256 TEXT NOT NULL,
            from_address       TEXT,
            subject            TEXT,
            provider           TEXT,
            parse_status       TEXT NOT NULL CHECK (parse_status IN (
                'parsed','updated','canceled','duplicate','unparseable')),
            trip_id            TEXT
                REFERENCES tripit_trips(trip_id) ON DELETE SET NULL,
            plan_id            TEXT
                REFERENCES tripit_plans(plan_id) ON DELETE SET NULL,
            received_at        TEXT NOT NULL,
            details_json       TEXT NOT NULL DEFAULT '{}',
            UNIQUE (owner_key, fingerprint_sha256)
        );
        """
    )


def _migration_0004_notifications_loyalty(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tripit_notifications (
            notification_id TEXT PRIMARY KEY,
            owner_key       TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            kind            TEXT NOT NULL,
            subject_key     TEXT,
            title           TEXT NOT NULL,
            body            TEXT,
            dedupe_key      TEXT NOT NULL,
            read_at         TEXT,
            created_at      TEXT NOT NULL,
            UNIQUE (owner_key, dedupe_key)
        );

        CREATE TABLE IF NOT EXISTS tripit_loyalty_programs (
            program_id    TEXT PRIMARY KEY,
            owner_key     TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            category      TEXT NOT NULL,
            provider      TEXT NOT NULL,
            program_name  TEXT NOT NULL,
            membership_id TEXT,
            created_at    TEXT NOT NULL,
            UNIQUE (owner_key, provider, program_name)
        );

        CREATE TABLE IF NOT EXISTS tripit_fare_watches (
            watch_id    TEXT PRIMARY KEY,
            owner_key   TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            origin_code TEXT NOT NULL,
            dest_code   TEXT NOT NULL,
            depart_date TEXT,
            return_date TEXT,
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tripit_ics_feed_tokens (
            token_id     TEXT PRIMARY KEY,
            owner_key    TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            token_digest TEXT NOT NULL UNIQUE,
            created_at   TEXT NOT NULL,
            revoked_at   TEXT
        );
        """
    )


def _migration_0005_pro_payment_overlay(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tripit_pro_subscriptions (
            subscription_id      TEXT PRIMARY KEY,
            owner_key            TEXT NOT NULL
                REFERENCES business_subjects(traveler_key) ON DELETE CASCADE,
            plan_code            TEXT NOT NULL DEFAULT 'pro-annual',
            status               TEXT NOT NULL
                CHECK (status IN ('active','canceled','expired')),
            current_period_start TEXT,
            current_period_end   TEXT,
            cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
            payment_flow_id      TEXT,
            receipt_id           TEXT,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        );
        -- At most one active subscription per owner (repeat webhooks cannot
        -- double-activate).
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tripit_pro_one_active
            ON tripit_pro_subscriptions(owner_key)
            WHERE status = 'active';
        """
    )


MIGRATIONS: tuple[tuple[str, Callable[[sqlite3.Connection], None]], ...] = (
    ("0001_core_travel", _migration_0001_core_travel),
    ("0002_sharing_documents", _migration_0002_sharing_documents),
    ("0003_import_messages", _migration_0003_import_messages),
    ("0004_notifications_loyalty", _migration_0004_notifications_loyalty),
    ("0005_pro_payment_overlay", _migration_0005_pro_payment_overlay),
)

SCHEMA_HEAD = MIGRATIONS[-1][0]


def _ensure_ledger(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tripit_schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at   TEXT NOT NULL
        )
        """
    )


def applied_migrations(connection: sqlite3.Connection) -> list[str]:
    _ensure_ledger(connection)
    return [
        str(row["migration_id"])
        for row in connection.execute(
            "SELECT migration_id FROM tripit_schema_migrations ORDER BY migration_id"
        )
    ]


def migrate(connection: sqlite3.Connection, *, upto: str | None = None) -> list[str]:
    """Apply pending migrations in order; idempotent. Returns applied ids."""

    _ensure_ledger(connection)
    already = set(applied_migrations(connection))
    applied_now: list[str] = []
    for migration_id, migration in MIGRATIONS:
        if migration_id not in already:
            migration(connection)
            connection.execute(
                "INSERT INTO tripit_schema_migrations(migration_id, applied_at) "
                "VALUES (?, ?)",
                (migration_id, FROZEN_CLOCK_UTC),
            )
            applied_now.append(migration_id)
        if upto is not None and migration_id == upto:
            break
    connection.commit()
    return applied_now


# ---------------------------------------------------------------------------
# deterministic seed
# ---------------------------------------------------------------------------

# Business tables in child-before-parent delete order.
_BUSINESS_TABLES_CHILD_FIRST: tuple[str, ...] = (
    "tripit_plan_segments",
    "tripit_documents",
    "tripit_import_messages",
    "tripit_notifications",
    "tripit_fare_watches",
    "tripit_ics_feed_tokens",
    "tripit_loyalty_programs",
    "tripit_pro_subscriptions",
    "tripit_write_commands",
    "tripit_trip_shares",
    "tripit_plans",
    "tripit_trip_travelers",
    "tripit_trips",
    "tripit_traveler_profiles",
    "business_subjects",
)

# Tables whose post-reset row counts are frozen in the manifest.
SEED_COUNT_TABLES: tuple[str, ...] = (
    "business_subjects",
    "tripit_traveler_profiles",
    "tripit_trips",
    "tripit_trip_travelers",
    "tripit_plans",
    "tripit_plan_segments",
    "tripit_documents",
    "tripit_import_messages",
    "tripit_notifications",
    "tripit_trip_shares",
    "tripit_pro_subscriptions",
    "tripit_loyalty_programs",
    "tripit_fare_watches",
    "tripit_ics_feed_tokens",
)

# Frozen expected counts (from scope/deterministic-seed.json).
EXPECTED_SEED_COUNTS: Mapping[str, int] = {
    "business_subjects": 2,
    "tripit_traveler_profiles": 2,
    "tripit_trips": 5,
    "tripit_trip_travelers": 5,
    "tripit_plans": 16,
    "tripit_plan_segments": 5,
    "tripit_documents": 1,
    "tripit_import_messages": 0,
    "tripit_notifications": 2,
    "tripit_trip_shares": 0,
    "tripit_pro_subscriptions": 0,
    "tripit_loyalty_programs": 1,
    "tripit_fare_watches": 0,
    "tripit_ics_feed_tokens": 0,
}

_SUBJECTS: tuple[tuple[str, str, str], ...] = (
    # (subject_id, traveler_key, role)
    ("traveler", "traveler", "traveler"),
    ("other", "other", "traveler"),
)

_PROFILES: tuple[tuple[str, str, str, str], ...] = (
    # (traveler_key, display_name, home_city, home_airport)
    ("traveler", "Avery Chen", "San Francisco, CA", "SFO"),
    ("other", "Jordan Lee", "Austin, TX", "AUS"),
)

_TRIPS: tuple[dict[str, Any], ...] = (
    {
        "trip_id": "trip-traveler-new-york",
        "owner_key": "traveler",
        "slug": "new-york",
        "name": "New York",
        "destination": "New York, NY",
        "start_date": "2027-05-22",
        "end_date": "2027-05-27",
        "timezone": "America/New_York",
    },
    {
        "trip_id": "trip-traveler-lisbon-getaway",
        "owner_key": "traveler",
        "slug": "lisbon-getaway",
        "name": "Lisbon Getaway",
        "destination": "Lisbon, Portugal",
        "start_date": "2027-09-03",
        "end_date": "2027-09-10",
        "timezone": "Europe/Lisbon",
    },
    {
        "trip_id": "trip-traveler-kyoto-autumn",
        "owner_key": "traveler",
        "slug": "kyoto-autumn",
        "name": "Kyoto Autumn",
        "destination": "Kyoto, Japan",
        "start_date": "2026-11-02",
        "end_date": "2026-11-09",
        "timezone": "Asia/Tokyo",
    },
    {
        "trip_id": "trip-traveler-chicago-sprint",
        "owner_key": "traveler",
        "slug": "chicago-sprint",
        "name": "Chicago Sprint",
        "destination": "Chicago, IL",
        "start_date": "2026-03-10",
        "end_date": "2026-03-12",
        "timezone": "America/Chicago",
    },
    {
        "trip_id": "trip-other-denver-offsite",
        "owner_key": "other",
        "slug": "denver-offsite",
        "name": "Denver Offsite",
        "destination": "Denver, CO",
        "start_date": "2027-06-14",
        "end_date": "2027-06-16",
        "timezone": "America/Denver",
    },
)

# Plans: 16 rows across the five trips + one Unfiled. plan_id == slug.
# The New York trip intentionally carries NO lodging plan (anchor precondition:
# the Hilton becomes the first lodging row deterministically).
_PLANS: tuple[dict[str, Any], ...] = (
    # --- New York (air / restaurant / activity / note) ---
    {
        "plan_id": "ny-round-trip-flight",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-new-york",
        "plan_type": "air",
        "title": "United 512 · SFO → JFK",
        "start_ts_utc": "2027-05-22T15:00:00Z",
        "end_ts_utc": "2027-05-27T05:30:00Z",
        "timezone": "America/New_York",
        "sort_key": 10,
        "natural_key": "united:UA512-2027-05-22",
        "details": {
            "airline": "United Airlines",
            "confirmation_number": "UA512NYC",
            "record_locator": "H7QK2P",
        },
    },
    {
        "plan_id": "ny-dinner-gramercy",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-new-york",
        "plan_type": "restaurant",
        "title": "Dinner at Gramercy Tavern",
        "start_ts_utc": "2027-05-23T23:30:00Z",
        "end_ts_utc": None,
        "timezone": "America/New_York",
        "sort_key": 20,
        "details": {"party_size": 2, "confirmation_number": "OT-88213"},
    },
    {
        "plan_id": "ny-high-line-walk",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-new-york",
        "plan_type": "activity",
        "title": "High Line walk",
        "start_ts_utc": "2027-05-24T14:00:00Z",
        "end_ts_utc": "2027-05-24T15:30:00Z",
        "timezone": "America/New_York",
        "sort_key": 30,
        "details": {"location": "The High Line, Manhattan"},
    },
    {
        "plan_id": "ny-packing-note",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-new-york",
        "plan_type": "note",
        "title": "Packing list",
        "start_ts_utc": None,
        "end_ts_utc": None,
        "timezone": "America/New_York",
        "sort_key": 0,
        "details": {"text": "Passport, chargers, umbrella, running shoes."},
    },
    # --- Lisbon (air / rail / cruise / map / directions) ---
    {
        "plan_id": "lisbon-round-trip-flight",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-lisbon-getaway",
        "plan_type": "air",
        "title": "TAP 202 · SFO → LIS",
        "start_ts_utc": "2027-09-03T22:30:00Z",
        "end_ts_utc": "2027-09-10T18:45:00Z",
        "timezone": "Europe/Lisbon",
        "sort_key": 10,
        "natural_key": "tap:TP202-2027-09-03",
        "details": {"airline": "TAP Air Portugal", "confirmation_number": "TP202LIS"},
    },
    {
        "plan_id": "lisbon-sintra-rail",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-lisbon-getaway",
        "plan_type": "rail",
        "title": "Train to Sintra",
        "start_ts_utc": "2027-09-05T08:15:00Z",
        "end_ts_utc": "2027-09-05T09:00:00Z",
        "timezone": "Europe/Lisbon",
        "sort_key": 20,
        "details": {"operator": "CP", "from": "Rossio", "to": "Sintra"},
    },
    {
        "plan_id": "lisbon-tagus-cruise",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-lisbon-getaway",
        "plan_type": "cruise",
        "title": "Tagus River sunset cruise",
        "start_ts_utc": "2027-09-06T16:00:00Z",
        "end_ts_utc": "2027-09-06T18:00:00Z",
        "timezone": "Europe/Lisbon",
        "sort_key": 30,
        "details": {"operator": "Lisbon by Boat", "dock": "Cais do Sodré"},
    },
    {
        "plan_id": "lisbon-alfama-map",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-lisbon-getaway",
        "plan_type": "map",
        "title": "Alfama walking map",
        "start_ts_utc": None,
        "end_ts_utc": None,
        "timezone": "Europe/Lisbon",
        "sort_key": 40,
        "details": {"center": "Alfama, Lisbon"},
    },
    {
        "plan_id": "lisbon-airport-directions",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-lisbon-getaway",
        "plan_type": "directions",
        "title": "Directions: Airport → Hotel",
        "start_ts_utc": None,
        "end_ts_utc": None,
        "timezone": "Europe/Lisbon",
        "sort_key": 50,
        "details": {"from": "LIS Airport", "to": "Hotel Alfama"},
    },
    # --- Chicago (lodging / car / meeting / transport) ---
    {
        "plan_id": "chicago-palmer-house",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-chicago-sprint",
        "plan_type": "lodging",
        "title": "Palmer House Hilton",
        "start_ts_utc": "2026-03-10T20:00:00Z",
        "end_ts_utc": "2026-03-12T16:00:00Z",
        "timezone": "America/Chicago",
        "sort_key": 20,
        "natural_key": "hilton:PH-3391category",
        "details": {"confirmation_number": "PH3391", "room": "King"},
    },
    {
        "plan_id": "chicago-avis-rental",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-chicago-sprint",
        "plan_type": "car",
        "title": "Avis rental car",
        "start_ts_utc": "2026-03-10T18:00:00Z",
        "end_ts_utc": "2026-03-12T17:00:00Z",
        "timezone": "America/Chicago",
        "sort_key": 10,
        "details": {"vendor": "Avis", "confirmation_number": "AV77120"},
    },
    {
        "plan_id": "chicago-client-review",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-chicago-sprint",
        "plan_type": "meeting",
        "title": "Client review meeting",
        "start_ts_utc": "2026-03-11T14:00:00Z",
        "end_ts_utc": "2026-03-11T16:00:00Z",
        "timezone": "America/Chicago",
        "sort_key": 30,
        "details": {"location": "200 S Wacker Dr, Chicago"},
    },
    {
        "plan_id": "chicago-airport-shuttle",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-chicago-sprint",
        "plan_type": "transport",
        "title": "Airport shuttle",
        "start_ts_utc": "2026-03-10T16:30:00Z",
        "end_ts_utc": "2026-03-10T17:15:00Z",
        "timezone": "America/Chicago",
        "sort_key": 5,
        "details": {"provider": "GO Airport Express"},
    },
    # --- Kyoto (lodging) ---
    {
        "plan_id": "kyoto-ryokan-stay",
        "owner_key": "traveler",
        "trip_id": "trip-traveler-kyoto-autumn",
        "plan_type": "lodging",
        "title": "Tawaraya Ryokan",
        "start_ts_utc": "2026-11-03T06:00:00Z",
        "end_ts_utc": "2026-11-07T01:00:00Z",
        "timezone": "Asia/Tokyo",
        "sort_key": 10,
        "details": {"confirmation_number": "TWR-2026-11", "room": "Garden suite"},
    },
    # --- Denver (owner=other, air) ---
    {
        "plan_id": "denver-oneway-flight",
        "owner_key": "other",
        "trip_id": "trip-other-denver-offsite",
        "plan_type": "air",
        "title": "Southwest 1841 · AUS → DEN",
        "start_ts_utc": "2027-06-14T12:00:00Z",
        "end_ts_utc": "2027-06-14T14:05:00Z",
        "timezone": "America/Denver",
        "sort_key": 10,
        "natural_key": "southwest:WN1841-2027-06-14",
        "details": {"airline": "Southwest", "confirmation_number": "WN1841DEN"},
    },
    # --- Unfiled (owner=traveler, trip_id NULL) ---
    {
        "plan_id": "unfiled-bluebottle-tasting",
        "owner_key": "traveler",
        "trip_id": None,
        "plan_type": "restaurant",
        "title": "Blue Bottle coffee tasting",
        "start_ts_utc": "2026-08-20T16:00:00Z",
        "end_ts_utc": None,
        "timezone": "America/Los_Angeles",
        "sort_key": 10,
        "details": {"location": "Blue Bottle, Ferry Building", "party_size": 1},
    },
)

# Flight segments: 5 rows for the three air plans.
_SEGMENTS: tuple[dict[str, Any], ...] = (
    {
        "segment_id": "seg-ny-1",
        "plan_id": "ny-round-trip-flight",
        "seq": 1,
        "start_ts_utc": "2027-05-22T15:00:00Z",
        "end_ts_utc": "2027-05-22T23:20:00Z",
        "origin_code": "SFO",
        "dest_code": "JFK",
        "origin_tz": "America/Los_Angeles",
        "dest_tz": "America/New_York",
        "marker": "UA 512",
    },
    {
        "segment_id": "seg-ny-2",
        "plan_id": "ny-round-trip-flight",
        "seq": 2,
        "start_ts_utc": "2027-05-27T13:00:00Z",
        "end_ts_utc": "2027-05-27T16:30:00Z",
        "origin_code": "JFK",
        "dest_code": "SFO",
        "origin_tz": "America/New_York",
        "dest_tz": "America/Los_Angeles",
        "marker": "UA 517",
    },
    {
        "segment_id": "seg-lis-1",
        "plan_id": "lisbon-round-trip-flight",
        "seq": 1,
        "start_ts_utc": "2027-09-03T22:30:00Z",
        "end_ts_utc": "2027-09-04T09:55:00Z",
        "origin_code": "SFO",
        "dest_code": "LIS",
        "origin_tz": "America/Los_Angeles",
        "dest_tz": "Europe/Lisbon",
        "marker": "TP 202",
    },
    {
        "segment_id": "seg-lis-2",
        "plan_id": "lisbon-round-trip-flight",
        "seq": 2,
        "start_ts_utc": "2027-09-10T11:15:00Z",
        "end_ts_utc": "2027-09-10T18:45:00Z",
        "origin_code": "LIS",
        "dest_code": "SFO",
        "origin_tz": "Europe/Lisbon",
        "dest_tz": "America/Los_Angeles",
        "marker": "TP 205",
    },
    {
        "segment_id": "seg-den-1",
        "plan_id": "denver-oneway-flight",
        "seq": 1,
        "start_ts_utc": "2027-06-14T12:00:00Z",
        "end_ts_utc": "2027-06-14T14:05:00Z",
        "origin_code": "AUS",
        "dest_code": "DEN",
        "origin_tz": "America/Chicago",
        "dest_tz": "America/Denver",
        "marker": "WN 1841",
    },
)

_NOTIFICATIONS: tuple[dict[str, Any], ...] = (
    {
        "notification_id": "notif-traveler-trip-reminder-new-york",
        "owner_key": "traveler",
        "kind": "trip-reminder",
        "subject_key": "new-york",
        "title": "Your New York trip is coming up",
        "body": "Your trip to New York begins May 22, 2027.",
        "dedupe_key": "trip-reminder::new-york",
    },
    {
        "notification_id": "notif-traveler-welcome-account",
        "owner_key": "traveler",
        "kind": "welcome",
        "subject_key": "account",
        "title": "Welcome to TripIt",
        "body": "Forward your travel confirmations to plans@tripit.com to get started.",
        "dedupe_key": "welcome::account",
    },
)

_LOYALTY: tuple[dict[str, Any], ...] = (
    {
        "program_id": "loyalty-traveler-united-mileageplus",
        "owner_key": "traveler",
        "category": "air",
        "provider": "United Airlines",
        "program_name": "MileagePlus",
        "membership_id": "MP-2481357",
    },
)


def _build_pdf(title: str) -> bytes:
    """Build a small, valid, deterministic single-page PDF."""

    safe = title.encode("latin-1", "replace").replace(b"(", b"[").replace(b")", b"]")
    stream = b"BT /F1 18 Tf 72 720 Td (" + safe + b") Tj ET"
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_pos = len(body)
    count = len(objects) + 1
    body += b"xref\n0 " + str(count).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        body += ("%010d 00000 n \n" % offset).encode()
    body += (
        b"trailer\n<< /Size " + str(count).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    )
    return bytes(body)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _is_seeded(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT value FROM tripit_meta WHERE key='seeded'"
    ).fetchone()
    return row is not None


def _seed_business(connection: sqlite3.Connection) -> None:
    """Insert the frozen deterministic seed (idempotent) and mark seeded."""

    for subject_id, traveler_key, role in _SUBJECTS:
        connection.execute(
            "INSERT OR IGNORE INTO business_subjects"
            "(subject_id, traveler_key, role, created_at) VALUES (?,?,?,?)",
            (subject_id, traveler_key, role, FROZEN_CLOCK_UTC),
        )
    for traveler_key, display_name, home_city, home_airport in _PROFILES:
        connection.execute(
            "INSERT OR IGNORE INTO tripit_traveler_profiles"
            "(traveler_key, display_name, home_city, home_airport,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (
                traveler_key,
                display_name,
                home_city,
                home_airport,
                FROZEN_CLOCK_UTC,
                FROZEN_CLOCK_UTC,
            ),
        )
    for trip in _TRIPS:
        connection.execute(
            "INSERT OR IGNORE INTO tripit_trips"
            "(trip_id, owner_key, slug, name, destination, start_date, end_date,"
            " timezone, image_key, is_concur, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trip["trip_id"],
                trip["owner_key"],
                trip["slug"],
                trip["name"],
                trip.get("destination"),
                trip["start_date"],
                trip["end_date"],
                trip["timezone"],
                trip.get("image_key"),
                int(trip.get("is_concur", 0)),
                FROZEN_CLOCK_UTC,
                FROZEN_CLOCK_UTC,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO tripit_trip_travelers"
            "(trip_id, traveler_key, role, created_at) VALUES (?,?,?,?)",
            (trip["trip_id"], trip["owner_key"], "owner", FROZEN_CLOCK_UTC),
        )
    for plan in _PLANS:
        connection.execute(
            "INSERT OR IGNORE INTO tripit_plans"
            "(plan_id, owner_key, trip_id, plan_type, title, start_ts_utc,"
            " end_ts_utc, timezone, sort_key, status, source, natural_key,"
            " details_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                plan["plan_id"],
                plan["owner_key"],
                plan.get("trip_id"),
                plan["plan_type"],
                plan["title"],
                plan.get("start_ts_utc"),
                plan.get("end_ts_utc"),
                plan.get("timezone"),
                int(plan.get("sort_key", 0)),
                plan.get("status", "active"),
                plan.get("source", "manual"),
                plan.get("natural_key"),
                _canonical_json(plan.get("details", {})),
                FROZEN_CLOCK_UTC,
                FROZEN_CLOCK_UTC,
            ),
        )
    for segment in _SEGMENTS:
        connection.execute(
            "INSERT OR IGNORE INTO tripit_plan_segments"
            "(segment_id, plan_id, seq, start_ts_utc, end_ts_utc, origin_code,"
            " dest_code, origin_tz, dest_tz, marker, details_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                segment["segment_id"],
                segment["plan_id"],
                segment["seq"],
                segment.get("start_ts_utc"),
                segment.get("end_ts_utc"),
                segment.get("origin_code"),
                segment.get("dest_code"),
                segment.get("origin_tz"),
                segment.get("dest_tz"),
                segment.get("marker"),
                _canonical_json(segment.get("details", {})),
            ),
        )
    document_bytes = _build_pdf("New York Hilton — quote")
    connection.execute(
        "INSERT OR IGNORE INTO tripit_documents"
        "(document_id, owner_key, trip_id, plan_id, filename, content_type,"
        " byte_size, sha256, blob, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "document-new-york-ny-hotel-quote",
            "traveler",
            "trip-traveler-new-york",
            None,
            "ny-hotel-quote.pdf",
            "application/pdf",
            len(document_bytes),
            hashlib.sha256(document_bytes).hexdigest(),
            document_bytes,
            FROZEN_CLOCK_UTC,
        ),
    )
    for notification in _NOTIFICATIONS:
        connection.execute(
            "INSERT OR IGNORE INTO tripit_notifications"
            "(notification_id, owner_key, kind, subject_key, title, body,"
            " dedupe_key, read_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                notification["notification_id"],
                notification["owner_key"],
                notification["kind"],
                notification.get("subject_key"),
                notification["title"],
                notification.get("body"),
                notification["dedupe_key"],
                None,
                FROZEN_CLOCK_UTC,
            ),
        )
    for program in _LOYALTY:
        connection.execute(
            "INSERT OR IGNORE INTO tripit_loyalty_programs"
            "(program_id, owner_key, category, provider, program_name,"
            " membership_id, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                program["program_id"],
                program["owner_key"],
                program["category"],
                program["provider"],
                program["program_name"],
                program.get("membership_id"),
                FROZEN_CLOCK_UTC,
            ),
        )
    connection.execute(
        "INSERT OR REPLACE INTO tripit_meta(key, value) VALUES ('seeded', ?)",
        (FROZEN_CLOCK_UTC,),
    )


def seed(connection: sqlite3.Connection | None = None) -> dict[str, int]:
    """Public seed entry (opens its own connection when none is given)."""

    if connection is not None:
        _seed_business(connection)
        return counts(connection)
    with closing(connect()) as own:
        migrate(own)
        _seed_business(own)
        own.commit()
        return counts(own)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def _reset_business(connection: sqlite3.Connection) -> None:
    """Delete business rows (child-first) and reseed inside a caller txn."""

    site_backend().lifecycle.reset_embedded(connection, confirm_site_id=SITE_ID)
    for table in _BUSINESS_TABLES_CHILD_FIRST:
        connection.execute(f"DELETE FROM {table}")
    connection.execute("DELETE FROM tripit_meta WHERE key='seeded'")
    _seed_business(connection)


def reset(auth_store: Any) -> dict[str, int]:
    """Deterministically reset auth + business state in one transaction.

    ``auth_store`` is a ``LocalAuthStore``; ``reset_site_state`` clears the six
    library auth tables and reseeds the fixture accounts, invoking our business
    reset inside the same SQLite transaction.
    """

    ensure_ready()
    auth_store.reset_site_state(
        site_reset=_reset_business,
        seed_accounts=[dict(fixture) for fixture in AUTH_FIXTURES],
    )
    with closing(connect()) as connection:
        return counts(connection)


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------

_READY_PATHS: set[str] = set()


def ensure_ready() -> Path:
    """Open the backend, apply migrations, seed once. Returns the db path."""

    backend = site_backend()
    path = backend.lifecycle.database_path
    key = str(path)
    if key in _READY_PATHS:
        return path
    with closing(connect(path)) as connection:
        migrate(connection)
        if not _is_seeded(connection):
            _seed_business(connection)
        connection.commit()
    backend.lifecycle.health()
    _READY_PATHS.add(key)
    return path


# ---------------------------------------------------------------------------
# subject bridge
# ---------------------------------------------------------------------------


def owner_for_subject(connection: sqlite3.Connection, subject_id: str) -> str | None:
    row = connection.execute(
        "SELECT traveler_key FROM business_subjects WHERE subject_id=?",
        (subject_id,),
    ).fetchone()
    return str(row["traveler_key"]) if row is not None else None


def create_account_subject(
    connection: sqlite3.Connection, account: Mapping[str, Any]
) -> str:
    """subject_factory for registration: create the business subject + profile.

    Called by the vendored auth store inside its registration transaction. The
    returned string becomes ``local_auth_accounts.subject_id``.
    """

    # The auth store passes {account_id, email, display_name} and expects the
    # factory to mint and return the subject id. Mirror the seed's invariant
    # that subject_id == traveler_key (a stable, unique owner scope).
    subject_id = str(account["account_id"])
    traveler_key = subject_id
    display_name = str(account.get("display_name") or "Traveler")
    connection.execute(
        "INSERT OR IGNORE INTO business_subjects"
        "(subject_id, traveler_key, role, created_at) VALUES (?,?,?,?)",
        (subject_id, traveler_key, "traveler", FROZEN_CLOCK_UTC),
    )
    connection.execute(
        "INSERT OR IGNORE INTO tripit_traveler_profiles"
        "(traveler_key, display_name, home_city, home_airport,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (traveler_key, display_name, "", None, FROZEN_CLOCK_UTC, FROZEN_CLOCK_UTC),
    )
    # A welcome notification is part of the registration contract; the seeded
    # account carries the same dedupe key, so INSERT OR IGNORE is idempotent.
    connection.execute(
        "INSERT OR IGNORE INTO tripit_notifications"
        "(notification_id, owner_key, kind, subject_key, title, body,"
        " dedupe_key, read_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            f"notif-{subject_id}-welcome-account",
            traveler_key,
            "welcome",
            "account",
            "Welcome to TripIt",
            "Forward your travel confirmations to plans@tripit.com to get started.",
            "welcome::account",
            None,
            FROZEN_CLOCK_UTC,
        ),
    )
    return subject_id


def update_profile(
    owner_key: str,
    *,
    display_name: str | None = None,
    home_city: str | None = None,
    home_airport: str | None = None,
) -> dict[str, Any]:
    """Persist editable traveler-profile fields (registration + settings)."""

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM tripit_traveler_profiles WHERE traveler_key=?",
            (owner_key,),
        ).fetchone()
        if row is None:
            raise NotFound("profile not found")
        new_display = (
            row["display_name"] if display_name is None else display_name.strip()
        )
        if not new_display:
            raise ValidationError("display name is required")
        new_city = row["home_city"] if home_city is None else home_city.strip()
        new_airport = (
            row["home_airport"]
            if home_airport is None
            else (home_airport.strip() or None)
        )
        connection.execute(
            "UPDATE tripit_traveler_profiles SET display_name=?, home_city=?,"
            " home_airport=?, updated_at=? WHERE traveler_key=?",
            (new_display, new_city, new_airport, FROZEN_CLOCK_UTC, owner_key),
        )
        connection.commit()
        return {"owner_key": owner_key, "updated": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in SEED_COUNT_TABLES:
        result[table] = int(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
    return result


def profile_for(connection: sqlite3.Connection, owner_key: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM tripit_traveler_profiles WHERE traveler_key=?",
        (owner_key,),
    ).fetchone()
    return dict(row) if row is not None else None


def list_trips(
    connection: sqlite3.Connection, owner_key: str, tab: str = "upcoming"
) -> list[dict[str, Any]]:
    """Trips for an owner partitioned by the frozen clock.

    ``upcoming`` = end_date >= today; ``past`` = end_date < today.
    """

    if tab == "past":
        clause = "AND end_date < ?"
        order = "ORDER BY start_date DESC"
    else:
        clause = "AND end_date >= ?"
        order = "ORDER BY start_date ASC"
    rows = connection.execute(
        f"SELECT * FROM tripit_trips WHERE owner_key=? {clause} {order}",
        (owner_key, FROZEN_DATE),
    ).fetchall()
    return [dict(row) for row in rows]


def get_trip(
    connection: sqlite3.Connection, owner_key: str, trip_id: str
) -> dict[str, Any]:
    """Owner-scoped trip fetch. Raises Forbidden if owned by another, else
    NotFound if it does not exist at all."""

    row = connection.execute(
        "SELECT * FROM tripit_trips WHERE trip_id=? AND owner_key=?",
        (trip_id, owner_key),
    ).fetchone()
    if row is not None:
        return dict(row)
    foreign = connection.execute(
        "SELECT 1 FROM tripit_trips WHERE trip_id=?",
        (trip_id,),
    ).fetchone()
    if foreign is not None:
        raise Forbidden("trip belongs to another traveler")
    raise NotFound("trip not found")


def list_plans_for_trip(
    connection: sqlite3.Connection, owner_key: str, trip_id: str
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM tripit_plans WHERE owner_key=? AND trip_id=? "
        "AND status='active' "
        "ORDER BY (start_ts_utc IS NULL), start_ts_utc, sort_key, plan_id",
        (owner_key, trip_id),
    ).fetchall()
    return [_plan_row(connection, row) for row in rows]


def list_unfiled_plans(
    connection: sqlite3.Connection, owner_key: str
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM tripit_plans WHERE owner_key=? AND trip_id IS NULL "
        "AND status='active' "
        "ORDER BY (start_ts_utc IS NULL), start_ts_utc, sort_key, plan_id",
        (owner_key,),
    ).fetchall()
    return [_plan_row(connection, row) for row in rows]


def get_plan(
    connection: sqlite3.Connection, owner_key: str, plan_id: str
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM tripit_plans WHERE plan_id=? AND owner_key=?",
        (plan_id, owner_key),
    ).fetchone()
    if row is not None:
        return _plan_row(connection, row)
    foreign = connection.execute(
        "SELECT 1 FROM tripit_plans WHERE plan_id=?",
        (plan_id,),
    ).fetchone()
    if foreign is not None:
        raise Forbidden("plan belongs to another traveler")
    raise NotFound("plan not found")


def _plan_row(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    plan = dict(row)
    plan["details"] = json.loads(plan.pop("details_json") or "{}")
    segments = connection.execute(
        "SELECT * FROM tripit_plan_segments WHERE plan_id=? ORDER BY seq",
        (plan["plan_id"],),
    ).fetchall()
    plan["segments"] = [dict(segment) for segment in segments]
    return plan


def list_documents(
    connection: sqlite3.Connection, owner_key: str, trip_id: str
) -> list[dict[str, Any]]:
    """Owner + trip scoped document metadata (never the BLOB), newest first.

    The frozen clock makes every ``created_at`` identical for seeded rows, so the
    filename is the deterministic tie-breaker.
    """

    rows = connection.execute(
        "SELECT document_id, owner_key, trip_id, plan_id, filename, content_type,"
        " byte_size, sha256, created_at FROM tripit_documents "
        "WHERE owner_key=? AND trip_id=? ORDER BY created_at DESC, filename",
        (owner_key, trip_id),
    ).fetchall()
    return [dict(row) for row in rows]


def get_document(
    connection: sqlite3.Connection, owner_key: str, document_id: str
) -> dict[str, Any]:
    """Owner-scoped document fetch including the BLOB, for preview / download.

    Raises Forbidden if it belongs to another traveler, else NotFound, so a
    caller can never distinguish "not yours" from "does not exist".
    """

    row = connection.execute(
        "SELECT * FROM tripit_documents WHERE document_id=? AND owner_key=?",
        (document_id, owner_key),
    ).fetchone()
    if row is not None:
        return dict(row)
    foreign = connection.execute(
        "SELECT 1 FROM tripit_documents WHERE document_id=?",
        (document_id,),
    ).fetchone()
    if foreign is not None:
        raise Forbidden("document belongs to another traveler")
    raise NotFound("document not found")


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def _next_sort_key(
    connection: sqlite3.Connection, owner_key: str, trip_id: str | None
) -> int:
    if trip_id is None:
        row = connection.execute(
            "SELECT COALESCE(MAX(sort_key), 0) FROM tripit_plans "
            "WHERE owner_key=? AND trip_id IS NULL",
            (owner_key,),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT COALESCE(MAX(sort_key), 0) FROM tripit_plans "
            "WHERE owner_key=? AND trip_id=?",
            (owner_key, trip_id),
        ).fetchone()
    return int(row[0]) + 10


def _plan_id_for(
    owner_key: str,
    trip_id: str | None,
    plan_type: str,
    title: str,
    natural_key: str | None,
    ordinal: int,
) -> str:
    if natural_key:
        material = f"{owner_key}\x1f{natural_key}"
    else:
        material = f"{owner_key}\x1f{trip_id}\x1f{plan_type}\x1f{title}\x1f{ordinal}"
    return "plan-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def add_plan(
    owner_key: str,
    *,
    trip_id: str | None,
    plan_type: str,
    title: str,
    start_ts_utc: str | None = None,
    end_ts_utc: str | None = None,
    timezone: str | None = None,
    details: Mapping[str, Any] | None = None,
    natural_key: str | None = None,
    source: str = "manual",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Add a plan to a trip (or Unfiled when trip_id is None).

    Idempotent on three levels: the owner-scoped command ledger (form resubmit),
    the (owner, natural_key) unique constraint (repeat confirmation/import), and
    a deterministic plan id. Returns ``{"plan_id", "trip_id", "created"}``.
    """

    if plan_type not in PLAN_TYPES:
        raise ValidationError(f"unknown plan type: {plan_type!r}")
    if not title or not title.strip():
        raise ValidationError("plan title is required")
    payload = {
        "trip_id": trip_id,
        "plan_type": plan_type,
        "title": title,
        "start_ts_utc": start_ts_utc,
        "end_ts_utc": end_ts_utc,
        "timezone": timezone,
        "details": dict(details or {}),
        "natural_key": natural_key,
        "source": source,
    }
    payload_digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        # 1) command-ledger idempotency (same form submission token).
        if idempotency_key:
            existing = connection.execute(
                "SELECT payload_digest, result_json FROM tripit_write_commands "
                "WHERE owner_key=? AND idempotency_key=?",
                (owner_key, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["payload_digest"] != payload_digest:
                    raise IdempotencyConflict(
                        "idempotency key reused with a different payload"
                    )
                connection.rollback()
                return json.loads(existing["result_json"])

        # 2) ownership of the target trip (403 vs 404 semantics).
        if trip_id is not None:
            owned = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE trip_id=? AND owner_key=?",
                (trip_id, owner_key),
            ).fetchone()
            if owned is None:
                foreign = connection.execute(
                    "SELECT 1 FROM tripit_trips WHERE trip_id=?",
                    (trip_id,),
                ).fetchone()
                raise (Forbidden if foreign is not None else NotFound)(
                    "trip not available for this traveler"
                )

        # 3) natural-key idempotency (repeat confirmation entry / import).
        created = True
        plan_id: str | None = None
        if natural_key:
            prior = connection.execute(
                "SELECT plan_id FROM tripit_plans WHERE owner_key=? AND natural_key=?",
                (owner_key, natural_key),
            ).fetchone()
            if prior is not None:
                plan_id = str(prior["plan_id"])
                created = False

        if plan_id is None:
            ordinal = int(
                connection.execute(
                    "SELECT COUNT(*) FROM tripit_plans WHERE owner_key=?",
                    (owner_key,),
                ).fetchone()[0]
            )
            plan_id = _plan_id_for(
                owner_key, trip_id, plan_type, title, natural_key, ordinal
            )
            connection.execute(
                "INSERT INTO tripit_plans"
                "(plan_id, owner_key, trip_id, plan_type, title, start_ts_utc,"
                " end_ts_utc, timezone, sort_key, status, source, natural_key,"
                " details_json, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_id,
                    owner_key,
                    trip_id,
                    plan_type,
                    title.strip(),
                    start_ts_utc,
                    end_ts_utc,
                    timezone,
                    _next_sort_key(connection, owner_key, trip_id),
                    "active",
                    source,
                    natural_key,
                    _canonical_json(dict(details or {})),
                    FROZEN_CLOCK_UTC,
                    FROZEN_CLOCK_UTC,
                ),
            )

        result = {"plan_id": plan_id, "trip_id": trip_id, "created": created}
        if idempotency_key:
            connection.execute(
                "INSERT INTO tripit_write_commands"
                "(owner_key, idempotency_key, payload_digest, result_json,"
                " created_at) VALUES (?,?,?,?,?)",
                (
                    owner_key,
                    idempotency_key,
                    payload_digest,
                    _canonical_json(result),
                    FROZEN_CLOCK_UTC,
                ),
            )
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_plan(
    owner_key: str,
    plan_id: str,
    *,
    title: str | None = None,
    start_ts_utc: str | None = None,
    end_ts_utc: str | None = None,
    timezone: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM tripit_plans WHERE plan_id=? AND owner_key=?",
            (plan_id, owner_key),
        ).fetchone()
        if row is None:
            foreign = connection.execute(
                "SELECT 1 FROM tripit_plans WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
            raise (Forbidden if foreign is not None else NotFound)("plan not found")
        new_title = row["title"] if title is None else title.strip()
        if not new_title:
            raise ValidationError("plan title is required")
        merged = json.loads(row["details_json"] or "{}")
        if details is not None:
            merged.update(dict(details))
        connection.execute(
            "UPDATE tripit_plans SET title=?, start_ts_utc=?, end_ts_utc=?,"
            " timezone=?, details_json=?, updated_at=? WHERE plan_id=?",
            (
                new_title,
                row["start_ts_utc"] if start_ts_utc is None else start_ts_utc,
                row["end_ts_utc"] if end_ts_utc is None else end_ts_utc,
                row["timezone"] if timezone is None else timezone,
                _canonical_json(merged),
                FROZEN_CLOCK_UTC,
                plan_id,
            ),
        )
        connection.commit()
        return {"plan_id": plan_id, "updated": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def delete_plan(owner_key: str, plan_id: str) -> dict[str, Any]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT 1 FROM tripit_plans WHERE plan_id=? AND owner_key=?",
            (plan_id, owner_key),
        ).fetchone()
        if row is None:
            foreign = connection.execute(
                "SELECT 1 FROM tripit_plans WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
            raise (Forbidden if foreign is not None else NotFound)("plan not found")
        connection.execute("DELETE FROM tripit_plans WHERE plan_id=?", (plan_id,))
        connection.commit()
        return {"plan_id": plan_id, "deleted": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def move_plan(
    owner_key: str, plan_id: str, *, trip_id: str | None
) -> dict[str, Any]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        plan = connection.execute(
            "SELECT 1 FROM tripit_plans WHERE plan_id=? AND owner_key=?",
            (plan_id, owner_key),
        ).fetchone()
        if plan is None:
            raise NotFound("plan not found")
        if trip_id is not None:
            owned = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE trip_id=? AND owner_key=?",
                (trip_id, owner_key),
            ).fetchone()
            if owned is None:
                raise NotFound("target trip not found")
        connection.execute(
            "UPDATE tripit_plans SET trip_id=?, sort_key=?, updated_at=? "
            "WHERE plan_id=?",
            (trip_id, _next_sort_key(connection, owner_key, trip_id),
             FROZEN_CLOCK_UTC, plan_id),
        )
        connection.commit()
        return {"plan_id": plan_id, "trip_id": trip_id, "moved": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# document writes
# ---------------------------------------------------------------------------


def _document_id_for(owner_key: str, trip_id: str, filename: str) -> str:
    material = f"{owner_key}\x1f{trip_id}\x1f{filename}"
    return "document-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _split_filename(filename: str) -> tuple[str, str]:
    """Split into (stem, extension-with-dot); a leading-dot dotfile has no ext."""

    dot = filename.rfind(".")
    if dot <= 0:
        return filename, ""
    return filename[:dot], filename[dot:]


def _unique_document_filename(
    connection: sqlite3.Connection, trip_id: str, filename: str
) -> str:
    """Disambiguate a colliding filename within a trip (quote.pdf -> quote-2.pdf).

    Mirrors ``_unique_trip_slug``: re-uploading a same-named file never destroys
    the existing attachment, and never trips the UNIQUE(trip_id, filename)
    constraint.
    """

    existing = {
        row[0]
        for row in connection.execute(
            "SELECT filename FROM tripit_documents WHERE trip_id=?", (trip_id,)
        ).fetchall()
    }
    if filename not in existing:
        return filename
    stem, ext = _split_filename(filename)
    ordinal = 2
    while f"{stem}-{ordinal}{ext}" in existing:
        ordinal += 1
    return f"{stem}-{ordinal}{ext}"


def add_document(
    owner_key: str,
    *,
    trip_id: str,
    filename: str,
    content_type: str,
    blob: bytes,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Attach a document BLOB to a trip the caller owns.

    The single SQLite file is the whole state, so the bytes live inline. Enforces
    the 2 MiB ceiling (ValidationError) and requires the trip — and the optional
    plan — to belong to the caller (Forbidden/NotFound, no existence disclosure).
    A colliding filename is disambiguated rather than overwritten.
    """

    filename = (filename or "").strip()
    if not filename:
        raise ValidationError("a document file name is required")
    size = len(blob)
    if size == 0:
        raise ValidationError("the document is empty")
    if size > MAX_DOCUMENT_BYTES:
        raise ValidationError("the document is larger than the 2 MB limit")
    digest = hashlib.sha256(blob).hexdigest()
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        owned = connection.execute(
            "SELECT 1 FROM tripit_trips WHERE trip_id=? AND owner_key=?",
            (trip_id, owner_key),
        ).fetchone()
        if owned is None:
            foreign = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE trip_id=?", (trip_id,)
            ).fetchone()
            raise (Forbidden if foreign is not None else NotFound)("trip not found")
        if plan_id is not None:
            plan_owned = connection.execute(
                "SELECT 1 FROM tripit_plans WHERE plan_id=? AND owner_key=?",
                (plan_id, owner_key),
            ).fetchone()
            if plan_owned is None:
                raise NotFound("plan not found")
        stored_name = _unique_document_filename(connection, trip_id, filename)
        document_id = _document_id_for(owner_key, trip_id, stored_name)
        connection.execute(
            "INSERT INTO tripit_documents"
            "(document_id, owner_key, trip_id, plan_id, filename, content_type,"
            " byte_size, sha256, blob, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                owner_key,
                trip_id,
                plan_id,
                stored_name,
                content_type,
                size,
                digest,
                blob,
                FROZEN_CLOCK_UTC,
            ),
        )
        connection.commit()
        return {
            "document_id": document_id,
            "trip_id": trip_id,
            "filename": stored_name,
            "content_type": content_type,
            "byte_size": size,
            "sha256": digest,
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def delete_document(owner_key: str, document_id: str) -> dict[str, Any]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT trip_id FROM tripit_documents WHERE document_id=? AND owner_key=?",
            (document_id, owner_key),
        ).fetchone()
        if row is None:
            foreign = connection.execute(
                "SELECT 1 FROM tripit_documents WHERE document_id=?",
                (document_id,),
            ).fetchone()
            raise (Forbidden if foreign is not None else NotFound)(
                "document not found"
            )
        connection.execute(
            "DELETE FROM tripit_documents WHERE document_id=?", (document_id,)
        )
        connection.commit()
        return {"document_id": document_id, "trip_id": row[0], "deleted": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# sharing
# ---------------------------------------------------------------------------

# The three roles a trip can be shared under (schema CHECK order).
SHARE_ROLES: tuple[str, ...] = ("viewer", "editor", "traveler")

# Plan detail keys hidden from a shared viewer while "show sensitive info" is
# off. Confirmation and ticketing identifiers are the sensitive fields the
# clone stores; the shared timeline masks them per-share.
SENSITIVE_DETAIL_KEYS: frozenset[str] = frozenset(
    {"confirmation_number", "ticket_number", "record_locator", "frequent_flyer"}
)


def _normalize_share_email(value: str) -> str:
    return (value or "").strip().casefold()


def _share_id_for(trip_id: str, invitee_email: str) -> str:
    material = f"{trip_id}\x1f{_normalize_share_email(invitee_email)}"
    return "share-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _invite_token_digest(share_id: str, owner_key: str) -> str:
    """Deterministic digest for the UNIQUE invite-token column.

    Invites are delivered by email match — the invitee accepts from their own
    signed-in session — so no bearer token is ever minted, mailed, or logged.
    The digest only keeps the column populated and unique; it never authorizes
    an accept.
    """

    material = f"{share_id}\x1f{owner_key}\x1finvite"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _owned_share(
    connection: sqlite3.Connection, owner_key: str, share_id: str
) -> sqlite3.Row:
    """Owner-scoped share fetch with the standard non-disclosure fallback."""

    row = connection.execute(
        "SELECT * FROM tripit_trip_shares WHERE share_id=? AND owner_key=?",
        (share_id, owner_key),
    ).fetchone()
    if row is not None:
        return row
    foreign = connection.execute(
        "SELECT 1 FROM tripit_trip_shares WHERE share_id=?",
        (share_id,),
    ).fetchone()
    raise (Forbidden if foreign is not None else NotFound)("share not found")


def list_shares_for_trip(
    connection: sqlite3.Connection, owner_key: str, trip_id: str
) -> list[dict[str, Any]]:
    """Every share the owner created for a trip (never the invite digest)."""

    rows = connection.execute(
        "SELECT share_id, trip_id, owner_key, invitee_email, invitee_key, role,"
        " show_sensitive, status, created_at, updated_at "
        "FROM tripit_trip_shares WHERE owner_key=? AND trip_id=? "
        "ORDER BY created_at, invitee_email",
        (owner_key, trip_id),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        share = dict(row)
        share["show_sensitive"] = bool(share["show_sensitive"])
        result.append(share)
    return result


def list_incoming_shares(
    connection: sqlite3.Connection, invitee_email: str, invitee_key: str
) -> list[dict[str, Any]]:
    """Trips shared *to* the signed-in traveler (invited + active), with the
    owner's display name and trip dates for the "Shared with you" surface."""

    email = _normalize_share_email(invitee_email)
    rows = connection.execute(
        "SELECT s.share_id, s.trip_id, s.role, s.show_sensitive, s.status,"
        " t.name AS trip_name, t.destination, t.start_date, t.end_date,"
        " COALESCE(p.display_name, 'A TripIt traveler') AS owner_name "
        "FROM tripit_trip_shares s "
        "JOIN tripit_trips t ON t.trip_id = s.trip_id "
        "LEFT JOIN tripit_traveler_profiles p ON p.traveler_key = s.owner_key "
        "WHERE (s.invitee_email=? OR s.invitee_key=?) "
        "AND s.status IN ('invited','active') "
        "ORDER BY t.start_date, t.name",
        (email, invitee_key),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        share = dict(row)
        share["show_sensitive"] = bool(share["show_sensitive"])
        result.append(share)
    return result


def shared_trip_for(
    connection: sqlite3.Connection,
    viewer_key: str,
    viewer_email: str,
    trip_id: str,
) -> dict[str, Any]:
    """Resolve a trip the viewer may read through an *active* share.

    Returns the trip plus the granting share's role / sensitivity. A trip that
    is not actively shared with the viewer raises NotFound — a viewer can never
    tell "not shared with me" from "does not exist".
    """

    email = _normalize_share_email(viewer_email)
    share = connection.execute(
        "SELECT role, show_sensitive FROM tripit_trip_shares "
        "WHERE trip_id=? AND status='active' "
        "AND (invitee_key=? OR invitee_email=?)",
        (trip_id, viewer_key, email),
    ).fetchone()
    if share is None:
        raise NotFound("shared trip not found")
    trip = connection.execute(
        "SELECT * FROM tripit_trips WHERE trip_id=?",
        (trip_id,),
    ).fetchone()
    if trip is None:  # pragma: no cover - CASCADE keeps these consistent
        raise NotFound("shared trip not found")
    return {
        "trip": dict(trip),
        "role": str(share["role"]),
        "show_sensitive": bool(share["show_sensitive"]),
    }


def create_share(
    owner_key: str,
    *,
    trip_id: str,
    invitee_email: str,
    role: str,
    show_sensitive: bool,
) -> dict[str, Any]:
    """Invite an email address to a trip the caller owns (idempotent).

    Keyed by UNIQUE(trip_id, invitee_email): re-inviting the same address
    refreshes the role / sensitivity and, if it had been revoked, returns it to
    'invited'. Enqueues the ``share-invite`` business mail (no secret variables)
    within the same transaction. Delivery is by email match, so nothing secret
    is mailed.
    """

    email = _normalize_share_email(invitee_email)
    if not email or "@" not in email:
        raise ValidationError("a valid invitee email is required")
    if role not in SHARE_ROLES:
        raise ValidationError("unknown share role")
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        trip_row = connection.execute(
            "SELECT name FROM tripit_trips WHERE trip_id=? AND owner_key=?",
            (trip_id, owner_key),
        ).fetchone()
        if trip_row is None:
            foreign = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE trip_id=?", (trip_id,)
            ).fetchone()
            raise (Forbidden if foreign is not None else NotFound)("trip not found")
        owner_account = connection.execute(
            "SELECT email_normalized FROM local_auth_accounts WHERE subject_id=?",
            (owner_key,),
        ).fetchone()
        if (
            owner_account is not None
            and _normalize_share_email(owner_account["email_normalized"]) == email
        ):
            raise ValidationError("you already own this trip")
        trip_name = str(trip_row["name"])
        existing = connection.execute(
            "SELECT * FROM tripit_trip_shares WHERE trip_id=? AND invitee_email=?",
            (trip_id, email),
        ).fetchone()
        if existing is None:
            share_id = _share_id_for(trip_id, email)
            status = "invited"
            connection.execute(
                "INSERT INTO tripit_trip_shares"
                "(share_id, trip_id, owner_key, invitee_email, invitee_key, role,"
                " show_sensitive, status, invite_token_digest, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    share_id,
                    trip_id,
                    owner_key,
                    email,
                    None,
                    role,
                    int(bool(show_sensitive)),
                    status,
                    _invite_token_digest(share_id, owner_key),
                    FROZEN_CLOCK_UTC,
                    FROZEN_CLOCK_UTC,
                ),
            )
        else:
            share_id = str(existing["share_id"])
            status = "invited" if existing["status"] == "revoked" else str(
                existing["status"]
            )
            connection.execute(
                "UPDATE tripit_trip_shares SET role=?, show_sensitive=?, status=?,"
                " updated_at=? WHERE share_id=?",
                (
                    role,
                    int(bool(show_sensitive)),
                    status,
                    FROZEN_CLOCK_UTC,
                    share_id,
                ),
            )
            if existing["status"] == "active" and existing["invitee_key"] is not None:
                connection.execute(
                    "UPDATE tripit_trip_travelers SET role=? "
                    "WHERE trip_id=? AND traveler_key=?",
                    (role, trip_id, existing["invitee_key"]),
                )
        inviter_row = connection.execute(
            "SELECT display_name FROM tripit_traveler_profiles WHERE traveler_key=?",
            (owner_key,),
        ).fetchone()
        inviter_name = (
            str(inviter_row["display_name"])
            if inviter_row and inviter_row["display_name"]
            else "A TripIt traveler"
        )
        # One share-invite mail per (share, role); a later role change re-notifies
        # without conflicting with the immutable earlier job.
        site_backend().mail.enqueue(
            "share-invite",
            email,
            {"inviter_name": inviter_name, "trip_name": trip_name, "role": role},
            idempotency_key=f"tripit-share-invite:{share_id}:{role}",
            simulation=_mail_is_simulation(),
            connection=connection,
        )
        connection.commit()
        return {
            "share_id": share_id,
            "trip_id": trip_id,
            "invitee_email": email,
            "role": role,
            "show_sensitive": bool(show_sensitive),
            "status": status,
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def accept_share(
    invitee_key: str, invitee_email: str, share_id: str
) -> dict[str, Any]:
    """Accept an invite addressed to the signed-in traveler's own email.

    The accepting account's email must match the invite's target (otherwise the
    share is indistinguishable from one that does not exist). Flips it to
    'active', records the invitee_key, and adds the trip_travelers membership.
    Idempotent for an already-accepted share.
    """

    email = _normalize_share_email(invitee_email)
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM tripit_trip_shares WHERE share_id=?",
            (share_id,),
        ).fetchone()
        if row is None or _normalize_share_email(row["invitee_email"]) != email:
            raise NotFound("share not found")
        if row["status"] == "revoked":
            raise Forbidden("this invitation is no longer available")
        connection.execute(
            "UPDATE tripit_trip_shares SET status='active', invitee_key=?,"
            " updated_at=? WHERE share_id=?",
            (invitee_key, FROZEN_CLOCK_UTC, share_id),
        )
        connection.execute(
            "INSERT INTO tripit_trip_travelers(trip_id, traveler_key, role,"
            " created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(trip_id, traveler_key) DO UPDATE SET role=excluded.role",
            (row["trip_id"], invitee_key, row["role"], FROZEN_CLOCK_UTC),
        )
        connection.commit()
        return {
            "share_id": share_id,
            "trip_id": str(row["trip_id"]),
            "role": str(row["role"]),
            "status": "active",
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_share_role(owner_key: str, share_id: str, role: str) -> dict[str, Any]:
    """Change a share's role; keep an active membership row in sync."""

    if role not in SHARE_ROLES:
        raise ValidationError("unknown share role")
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _owned_share(connection, owner_key, share_id)
        connection.execute(
            "UPDATE tripit_trip_shares SET role=?, updated_at=? WHERE share_id=?",
            (role, FROZEN_CLOCK_UTC, share_id),
        )
        if row["status"] == "active" and row["invitee_key"] is not None:
            connection.execute(
                "UPDATE tripit_trip_travelers SET role=? "
                "WHERE trip_id=? AND traveler_key=?",
                (role, row["trip_id"], row["invitee_key"]),
            )
        connection.commit()
        return {"share_id": share_id, "trip_id": str(row["trip_id"]), "role": role}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_share_sensitive(
    owner_key: str, share_id: str, show_sensitive: bool
) -> dict[str, Any]:
    """Toggle whether a shared viewer sees confirmation / ticketing fields."""

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _owned_share(connection, owner_key, share_id)
        connection.execute(
            "UPDATE tripit_trip_shares SET show_sensitive=?, updated_at=? "
            "WHERE share_id=?",
            (int(bool(show_sensitive)), FROZEN_CLOCK_UTC, share_id),
        )
        connection.commit()
        return {
            "share_id": share_id,
            "trip_id": str(row["trip_id"]),
            "show_sensitive": bool(show_sensitive),
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def revoke_share(owner_key: str, share_id: str) -> dict[str, Any]:
    """Revoke a share and drop the invitee's membership so access ends."""

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _owned_share(connection, owner_key, share_id)
        connection.execute(
            "UPDATE tripit_trip_shares SET status='revoked', updated_at=? "
            "WHERE share_id=?",
            (FROZEN_CLOCK_UTC, share_id),
        )
        if row["invitee_key"] is not None:
            connection.execute(
                "DELETE FROM tripit_trip_travelers "
                "WHERE trip_id=? AND traveler_key=?",
                (row["trip_id"], row["invitee_key"]),
            )
        connection.commit()
        return {
            "share_id": share_id,
            "trip_id": str(row["trip_id"]),
            "status": "revoked",
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# email import (forward-to-plans@tripit.com)
# ---------------------------------------------------------------------------


def _load_importer():
    """Load the sibling ``importer`` module by path, cached in ``sys.modules``.

    ``importer`` is a pure stdlib module with no dependency on this one, so it is
    safe to execute standalone; loading it by path (rather than as a package)
    mirrors how the app itself loads this data layer.
    """

    import importlib.util
    import sys

    module_name = "tripit_clone_backend_importer"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).resolve().parent / "importer.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _message_id_for(owner_key: str, fingerprint: str) -> str:
    material = f"{owner_key}\x1f{fingerprint}"
    return "imp-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _local_to_utc(date_str: str, time_str: str, tz_name: str) -> str | None:
    """Convert a local ``YYYY-MM-DD`` / ``HH:MM`` in ``tz_name`` to a UTC stamp.

    Deterministic (no wall clock): the offset for a fixed calendar instant is a
    pure function of the zone's rules. Returns ``None`` when there is no date.
    """

    if not date_str:
        return None
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    try:
        naive = datetime.strptime(f"{date_str} {time_str or '00:00'}", "%Y-%m-%d %H:%M")
        zone = ZoneInfo(tz_name) if tz_name else timezone.utc
    except Exception:  # noqa: BLE001 - unreadable date/tz => no stamp
        return None
    return (
        naive.replace(tzinfo=zone)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _route_trip_for_date(
    connection: sqlite3.Connection, owner_key: str, start_date: str
) -> str | None:
    """The owner's trip whose date span covers ``start_date`` (else None → Unfiled)."""

    if not start_date:
        return None
    row = connection.execute(
        "SELECT trip_id FROM tripit_trips WHERE owner_key=? "
        "AND start_date<=? AND end_date>=? ORDER BY start_date, trip_id LIMIT 1",
        (owner_key, start_date, start_date),
    ).fetchone()
    return str(row["trip_id"]) if row is not None else None


def _trip_name(connection: sqlite3.Connection, trip_id: str | None) -> str | None:
    if not trip_id:
        return None
    row = connection.execute(
        "SELECT name FROM tripit_trips WHERE trip_id=?", (trip_id,)
    ).fetchone()
    return str(row["name"]) if row is not None else None


def _insert_import_plan(
    connection: sqlite3.Connection,
    owner_key: str,
    trip_id: str | None,
    intent: Mapping[str, Any],
    start_ts: str | None,
    end_ts: str | None,
) -> str:
    """Insert a new plan from an import intent (mirrors add_plan's INSERT)."""

    natural_key = str(intent["natural_key"])
    ordinal = int(
        connection.execute(
            "SELECT COUNT(*) FROM tripit_plans WHERE owner_key=?", (owner_key,)
        ).fetchone()[0]
    )
    plan_id = _plan_id_for(
        owner_key, trip_id, str(intent["plan_type"]), str(intent["title"]),
        natural_key, ordinal,
    )
    connection.execute(
        "INSERT INTO tripit_plans"
        "(plan_id, owner_key, trip_id, plan_type, title, start_ts_utc,"
        " end_ts_utc, timezone, sort_key, status, source, natural_key,"
        " details_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            plan_id,
            owner_key,
            trip_id,
            str(intent["plan_type"]),
            str(intent["title"]).strip(),
            start_ts,
            end_ts,
            intent.get("timezone"),
            _next_sort_key(connection, owner_key, trip_id),
            "active",
            "import",
            natural_key,
            _canonical_json(dict(intent.get("details") or {})),
            FROZEN_CLOCK_UTC,
            FROZEN_CLOCK_UTC,
        ),
    )
    return plan_id


def _import_summary(
    message_id: str,
    intent: Mapping[str, Any],
    *,
    parse_status: str,
    trip_id: str | None,
    plan_id: str | None,
    trip_name: str | None,
    duplicate: bool = False,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "provider": intent.get("provider"),
        "subject": intent.get("subject"),
        "from_address": intent.get("from_address"),
        "plan_type": intent.get("plan_type"),
        "title": intent.get("title"),
        "confirmation": intent.get("confirmation"),
        "parse_status": parse_status,
        "trip_id": trip_id,
        "plan_id": plan_id,
        "trip_name": trip_name,
        "routing": "trip" if trip_id else ("unfiled" if plan_id else None),
        "duplicate": duplicate,
    }


def import_email(owner_key: str, raw_text: str) -> dict[str, Any]:
    """Ingest a forwarded confirmation email on behalf of a traveler.

    Deterministic and idempotent, keyed by ``(owner, content fingerprint)``:

    * a repeat of the same message is a ``duplicate`` — no new plan, no new mail;
    * a reschedule or cancellation (new body, same confirmation number) updates
      the plan the original import created, matched by natural key;
    * a new plan routes into a trip by date overlap, else to Unfiled;
    * an unrecognized message is a first-class ``unparseable`` outcome recorded
      with no plan (mirroring the source failure UX), never an exception.

    On ``parsed`` / ``updated`` an ``import-receipt`` business mail is enqueued in
    the same transaction. Returns a summary dict describing the outcome.
    """

    importer = _load_importer()
    intent = importer.parse_message(raw_text or "")
    fingerprint = str(intent["fingerprint"])
    message_id = _message_id_for(owner_key, fingerprint)

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")

        # (1) fingerprint idempotency — the same email forwarded twice.
        prior_msg = connection.execute(
            "SELECT * FROM tripit_import_messages "
            "WHERE owner_key=? AND fingerprint_sha256=?",
            (owner_key, fingerprint),
        ).fetchone()
        if prior_msg is not None:
            trip_name = _trip_name(connection, prior_msg["trip_id"])
            connection.rollback()
            return _import_summary(
                str(prior_msg["message_id"]),
                intent,
                parse_status="duplicate",
                trip_id=prior_msg["trip_id"],
                plan_id=prior_msg["plan_id"],
                trip_name=trip_name,
                duplicate=True,
            )

        status = str(intent["status"])
        plan_id: str | None = None
        trip_id: str | None = None

        if status != "unparseable":
            natural_key = str(intent["natural_key"])
            start_ts = _local_to_utc(
                str(intent.get("start_date") or ""),
                str(intent.get("start_time") or ""),
                str(intent.get("timezone") or ""),
            )
            end_ts = _local_to_utc(
                str(intent.get("end_date") or ""),
                str(intent.get("end_time") or ""),
                str(intent.get("timezone") or ""),
            )
            prior_plan = connection.execute(
                "SELECT plan_id, trip_id, details_json FROM tripit_plans "
                "WHERE owner_key=? AND natural_key=?",
                (owner_key, natural_key),
            ).fetchone()

            if status == "canceled":
                # Flip the existing plan to canceled (drops it from the
                # timeline); preserve its richer itinerary details. Nothing to
                # do if the cancellation arrives with no prior plan.
                if prior_plan is not None:
                    plan_id = str(prior_plan["plan_id"])
                    trip_id = prior_plan["trip_id"]
                    connection.execute(
                        "UPDATE tripit_plans SET status='canceled', updated_at=? "
                        "WHERE plan_id=?",
                        (FROZEN_CLOCK_UTC, plan_id),
                    )
            elif prior_plan is not None:
                # parsed/updated with a known confirmation: refresh in place,
                # keeping the plan's existing trip placement.
                plan_id = str(prior_plan["plan_id"])
                trip_id = prior_plan["trip_id"]
                merged = json.loads(prior_plan["details_json"] or "{}")
                merged.update(dict(intent.get("details") or {}))
                connection.execute(
                    "UPDATE tripit_plans SET title=?, start_ts_utc=?, end_ts_utc=?,"
                    " timezone=?, status='active', details_json=?, updated_at=? "
                    "WHERE plan_id=?",
                    (
                        str(intent["title"]).strip(),
                        start_ts,
                        end_ts,
                        intent.get("timezone"),
                        _canonical_json(merged),
                        FROZEN_CLOCK_UTC,
                        plan_id,
                    ),
                )
            else:
                # A brand-new plan: route by date overlap, else Unfiled.
                trip_id = _route_trip_for_date(
                    connection, owner_key, str(intent.get("start_date") or "")
                )
                plan_id = _insert_import_plan(
                    connection, owner_key, trip_id, intent, start_ts, end_ts
                )

        # (2) record the import message (parse_status carries the outcome).
        connection.execute(
            "INSERT INTO tripit_import_messages"
            "(message_id, owner_key, fingerprint_sha256, from_address, subject,"
            " provider, parse_status, trip_id, plan_id, received_at, details_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                message_id,
                owner_key,
                fingerprint,
                intent.get("from_address"),
                intent.get("subject"),
                intent.get("provider"),
                status,
                trip_id,
                plan_id,
                FROZEN_CLOCK_UTC,
                _canonical_json(
                    {
                        "title": intent.get("title"),
                        "plan_type": intent.get("plan_type"),
                        "confirmation": intent.get("confirmation"),
                    }
                ),
            ),
        )

        # (3) import-receipt mail on a plan-affecting parse (not cancel/unparse).
        trip_name = _trip_name(connection, trip_id)
        if status in ("parsed", "updated") and plan_id is not None:
            account = connection.execute(
                "SELECT email_normalized FROM local_auth_accounts WHERE subject_id=?",
                (owner_key,),
            ).fetchone()
            recipient = str(account["email_normalized"]) if account else ""
            if recipient:
                site_backend().mail.enqueue(
                    "import-receipt",
                    recipient,
                    {
                        "trip_name": trip_name or "Unfiled Items",
                        "plan_count": "1",
                        "provider": str(intent.get("provider") or "Email"),
                    },
                    idempotency_key=f"tripit-import-receipt:{message_id}",
                    simulation=_mail_is_simulation(),
                    connection=connection,
                )

        connection.commit()
        return _import_summary(
            message_id,
            intent,
            parse_status=status,
            trip_id=trip_id,
            plan_id=plan_id,
            trip_name=trip_name,
        )
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_import_messages(
    connection: sqlite3.Connection, owner_key: str
) -> list[dict[str, Any]]:
    """Import history for an owner, newest first (insertion order via rowid)."""

    rows = connection.execute(
        "SELECT * FROM tripit_import_messages WHERE owner_key=? "
        "ORDER BY rowid DESC",
        (owner_key,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        item["trip_name"] = _trip_name(connection, item.get("trip_id"))
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# trip writes
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "trip"


def _unique_trip_slug(
    connection: sqlite3.Connection,
    owner_key: str,
    base_slug: str,
    *,
    exclude_trip_id: str | None = None,
) -> str:
    """First free ``owner_key`` slug: ``base``, ``base-2``, ``base-3`` …"""

    slug = base_slug
    ordinal = 1
    while True:
        if exclude_trip_id is None:
            clash = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE owner_key=? AND slug=?",
                (owner_key, slug),
            ).fetchone()
        else:
            clash = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE owner_key=? AND slug=? "
                "AND trip_id<>?",
                (owner_key, slug, exclude_trip_id),
            ).fetchone()
        if clash is None:
            return slug
        ordinal += 1
        slug = f"{base_slug}-{ordinal}"


def create_trip(
    owner_key: str,
    *,
    name: str,
    destination: str | None = None,
    start_date: str,
    end_date: str,
    timezone: str = "UTC",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create a trip owned by ``owner_key``.

    The caller is responsible for validating ``timezone`` against the IANA
    database; the column is stored verbatim. Idempotent on the owner-scoped
    command ledger so a double-submitted form yields a single trip. Returns
    ``{"trip_id", "slug", "created"}``.
    """

    name = (name or "").strip()
    destination = (destination or "").strip() or None
    if not name:
        raise ValidationError("a trip name is required")
    if not start_date or not end_date:
        raise ValidationError("both a start and an end date are required")
    if end_date < start_date:
        raise ValidationError("the end date must be on or after the start date")
    tz = (timezone or "").strip() or "UTC"
    payload = {
        "name": name,
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": tz,
    }
    payload_digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            existing = connection.execute(
                "SELECT payload_digest, result_json FROM tripit_write_commands "
                "WHERE owner_key=? AND idempotency_key=?",
                (owner_key, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["payload_digest"] != payload_digest:
                    raise IdempotencyConflict(
                        "idempotency key reused with a different payload"
                    )
                connection.rollback()
                return json.loads(existing["result_json"])

        slug = _unique_trip_slug(connection, owner_key, _slugify(name))
        trip_id = "trip-" + hashlib.sha256(
            f"{owner_key}\x1f{slug}".encode("utf-8")
        ).hexdigest()[:24]
        connection.execute(
            "INSERT INTO tripit_trips"
            "(trip_id, owner_key, slug, name, destination, start_date, end_date,"
            " timezone, image_key, is_concur, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trip_id,
                owner_key,
                slug,
                name,
                destination,
                start_date,
                end_date,
                tz,
                None,
                0,
                FROZEN_CLOCK_UTC,
                FROZEN_CLOCK_UTC,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO tripit_trip_travelers"
            "(trip_id, traveler_key, role, created_at) VALUES (?,?,?,?)",
            (trip_id, owner_key, "owner", FROZEN_CLOCK_UTC),
        )
        result = {"trip_id": trip_id, "slug": slug, "created": True}
        if idempotency_key:
            connection.execute(
                "INSERT INTO tripit_write_commands"
                "(owner_key, idempotency_key, payload_digest, result_json,"
                " created_at) VALUES (?,?,?,?,?)",
                (
                    owner_key,
                    idempotency_key,
                    payload_digest,
                    _canonical_json(result),
                    FROZEN_CLOCK_UTC,
                ),
            )
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_trip(
    owner_key: str,
    trip_id: str,
    *,
    name: str | None = None,
    destination: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Edit a trip's core fields. Slug is kept stable across renames so shared
    links do not break. ``None`` means "leave unchanged"; an empty
    ``destination`` string clears it. Cross-owner access is Forbidden, missing is
    NotFound (no existence disclosure)."""

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM tripit_trips WHERE trip_id=? AND owner_key=?",
            (trip_id, owner_key),
        ).fetchone()
        if row is None:
            foreign = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE trip_id=?",
                (trip_id,),
            ).fetchone()
            raise (Forbidden if foreign is not None else NotFound)("trip not found")

        new_name = row["name"] if name is None else name.strip()
        if not new_name:
            raise ValidationError("a trip name is required")
        new_start = row["start_date"] if start_date is None else start_date
        new_end = row["end_date"] if end_date is None else end_date
        if not new_start or not new_end:
            raise ValidationError("both a start and an end date are required")
        if new_end < new_start:
            raise ValidationError("the end date must be on or after the start date")
        if destination is None:
            new_dest = row["destination"]
        else:
            new_dest = destination.strip() or None
        if timezone is None:
            new_tz = row["timezone"]
        else:
            new_tz = (timezone or "").strip() or row["timezone"]

        connection.execute(
            "UPDATE tripit_trips SET name=?, destination=?, start_date=?,"
            " end_date=?, timezone=?, updated_at=? WHERE trip_id=?",
            (
                new_name,
                new_dest,
                new_start,
                new_end,
                new_tz,
                FROZEN_CLOCK_UTC,
                trip_id,
            ),
        )
        connection.commit()
        return {"trip_id": trip_id, "updated": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def delete_trip(owner_key: str, trip_id: str) -> dict[str, Any]:
    """Delete a trip and everything filed inside it.

    The plans / shares / documents / travelers rows cascade via their foreign
    keys (``PRAGMA foreign_keys=ON`` is set by :func:`connect`). Cross-owner is
    Forbidden, missing is NotFound."""

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT 1 FROM tripit_trips WHERE trip_id=? AND owner_key=?",
            (trip_id, owner_key),
        ).fetchone()
        if row is None:
            foreign = connection.execute(
                "SELECT 1 FROM tripit_trips WHERE trip_id=?",
                (trip_id,),
            ).fetchone()
            raise (Forbidden if foreign is not None else NotFound)("trip not found")
        connection.execute("DELETE FROM tripit_trips WHERE trip_id=?", (trip_id,))
        connection.commit()
        return {"trip_id": trip_id, "deleted": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def resolve_trip_for_month_day(
    owner_key: str, month_day_start: str, month_day_end: str
) -> dict[str, Any] | None:
    """Resolve a year-less date range (MM-DD) to an existing trip by overlap.

    Each candidate trip supplies the year: if the plan's [start, end], placed in
    the trip's year, overlaps the trip's own [start_date, end_date], that trip
    wins. This is how the anchor journey resolves "May 23–26" to the seeded 2027
    New York trip without the year being given.
    """

    with closing(connect()) as connection:
        trips = connection.execute(
            "SELECT * FROM tripit_trips WHERE owner_key=? ORDER BY start_date",
            (owner_key,),
        ).fetchall()
    for trip in trips:
        year = trip["start_date"][:4]
        plan_start = f"{year}-{month_day_start}"
        plan_end = f"{year}-{month_day_end}"
        # Overlap test on inclusive local date ranges.
        if plan_start <= trip["end_date"] and plan_end >= trip["start_date"]:
            resolved = dict(trip)
            resolved["resolved_start_date"] = plan_start
            resolved["resolved_end_date"] = plan_end
            return resolved
    return None


def health() -> dict[str, Any]:
    return site_backend().lifecycle.health()


# ---------------------------------------------------------------------------
# TripIt Pro subscription domain
#
# TripIt Pro is a single annual product ($49 / year). The subscription row *is*
# the order, so no per-item checkout table is required: the vendored generic
# ledger (websitebench_payment_flows / _attempts) carries the money facts, and
# the tripit_pro_subscriptions overlay (migration 0005) carries entitlement.
# The default deployment adapter is local-sandbox; the stripe-test path is
# written but dormant until a payment-scope approval wires the ``stripe_test``
# runtime block. The anchor hotel-reservation journey never touches this code.
# ---------------------------------------------------------------------------

PRO_PLAN_CODE = "pro-annual"
PRO_AMOUNT_MINOR = 4900
PRO_CURRENCY = "USD"
PRO_PRICE_LABEL = "$49"
PRO_TOTAL_LABEL = "$49.00"


def _pro_period() -> tuple[str, str]:
    """The frozen annual billing term ``[now, now + 1 year]`` as UTC ``…Z``."""

    from datetime import datetime, timezone

    start = datetime.fromisoformat(FROZEN_CLOCK_UTC.replace("Z", "+00:00"))
    try:
        end = start.replace(year=start.year + 1)
    except ValueError:  # Feb 29 -> Feb 28 the following year
        end = start.replace(year=start.year + 1, day=28)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (
        start.astimezone(timezone.utc).strftime(fmt),
        end.astimezone(timezone.utc).strftime(fmt),
    )


def _pro_fingerprint(owner_key: str, period_start: str) -> str:
    """Stable money fingerprint for a Pro term; equal inputs, equal approval."""

    material = f"tripit|{PRO_PLAN_CODE}|{owner_key}|{period_start}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _pro_row(
    connection: sqlite3.Connection, owner_key: str, *, active_only: bool = True
) -> sqlite3.Row | None:
    if active_only:
        return connection.execute(
            "SELECT * FROM tripit_pro_subscriptions "
            "WHERE owner_key=? AND status='active'",
            (owner_key,),
        ).fetchone()
    return connection.execute(
        "SELECT * FROM tripit_pro_subscriptions WHERE owner_key=? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (owner_key,),
    ).fetchone()


def pro_status(connection: sqlite3.Connection, owner_key: str) -> dict[str, Any]:
    """Entitlement snapshot for an owner: membership + renewal facts."""

    row = _pro_row(connection, owner_key, active_only=True)
    if row is None:
        return {
            "is_pro": False,
            "plan_code": PRO_PLAN_CODE,
            "price_label": PRO_PRICE_LABEL,
            "subscription": None,
            "cancel_at_period_end": False,
            "current_period_end": None,
            "receipt_id": None,
        }
    sub = dict(row)
    return {
        "is_pro": True,
        "plan_code": sub["plan_code"],
        "price_label": PRO_PRICE_LABEL,
        "subscription": sub,
        "cancel_at_period_end": bool(sub["cancel_at_period_end"]),
        "current_period_end": sub["current_period_end"],
        "receipt_id": sub["receipt_id"],
    }


def is_pro(connection: sqlite3.Connection, owner_key: str) -> bool:
    """True when the owner holds an active Pro entitlement."""

    return _pro_row(connection, owner_key, active_only=True) is not None


def _resolve_pro_scenario(
    connection: sqlite3.Connection,
    flow_id: str,
    token: str,
    configured: set[str],
) -> str:
    """Map an opaque client scenario token to a frozen runtime scenario id.

    Only the opaque ids frozen in ``runtime.json`` are accepted (the payment
    scope permits opaque-scenario-id input only). The retry scenario promotes
    to approval once a prior declined/retryable attempt exists on this flow, so
    the "retry then succeed" journey converges exactly like the edX reference.
    """

    token = (token or "").strip()
    if token not in configured:
        raise BackendError("unsupported payment scenario")
    if token == "sandbox-pro-retryable" and "sandbox-pro-approved" in configured:
        prior = connection.execute(
            "SELECT 1 FROM websitebench_payment_attempts "
            "WHERE site_id=? AND flow_id=? "
            "AND status IN ('DECLINED','RETRYABLE') LIMIT 1",
            (SITE_ID, flow_id),
        ).fetchone()
        if prior is not None:
            return "sandbox-pro-approved"
    return token


def _activate_pro_subscription(
    connection: sqlite3.Connection,
    *,
    owner_key: str,
    flow_id: str,
    fingerprint: str,
    amount_minor: int,
    currency: str,
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    """Consume the approval and write entitlement + receipt in one transaction.

    The caller must already hold an active transaction. Consuming the approval
    binds the money to this activation; the one-active partial unique index
    makes a repeat webhook or a concurrent submit unable to double-activate.
    """

    site_backend().payments.consume_approval(
        connection,
        flow_id=flow_id,
        owner=owner_key,
        amount_minor=amount_minor,
        currency=currency,
        fingerprint=fingerprint,
    )
    subscription_id = f"prosub-{secrets.token_hex(10)}"
    receipt_id = f"TPRO-{fingerprint[:12].upper()}"
    connection.execute(
        "INSERT INTO tripit_pro_subscriptions "
        "(subscription_id, owner_key, plan_code, status, current_period_start, "
        "current_period_end, cancel_at_period_end, payment_flow_id, receipt_id, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', ?, ?, 0, ?, ?, ?, ?)",
        (
            subscription_id,
            owner_key,
            PRO_PLAN_CODE,
            period_start,
            period_end,
            flow_id,
            receipt_id,
            FROZEN_CLOCK_UTC,
            FROZEN_CLOCK_UTC,
        ),
    )
    account = connection.execute(
        "SELECT email_normalized FROM local_auth_accounts WHERE subject_id=?",
        (owner_key,),
    ).fetchone()
    recipient = str(account["email_normalized"]) if account else ""
    if recipient:
        # One receipt per activation, tied to the immutable subscription id so a
        # Stripe return/webhook replay can retry a deferred receipt without a
        # second mail job.
        site_backend().mail.enqueue(
            "pro-receipt",
            recipient,
            {"receipt_id": receipt_id, "total": PRO_TOTAL_LABEL},
            idempotency_key=f"tripit-pro-receipt:{subscription_id}",
            simulation=_mail_is_simulation(),
            connection=connection,
        )
    return dict(
        connection.execute(
            "SELECT * FROM tripit_pro_subscriptions WHERE subscription_id=?",
            (subscription_id,),
        ).fetchone()
    )


def subscribe_pro(
    owner_key: str, scenario_token: str, *, idempotency_key: str | None = None
) -> dict[str, Any]:
    """Attempt a Pro subscription through the active local-sandbox adapter.

    Runs create-intent -> attempt -> (on approval) consume-approval + insert the
    subscription + enqueue the pro-receipt, all inside one ``BEGIN IMMEDIATE``
    transaction. Returns ``{result, subscription, receipt_id}`` where result is
    one of ``approved``/``declined``/``retryable``/``already_active``. Idempotent:
    a second call while already active is a no-op that reports ``already_active``,
    and the one-active partial unique index is the concurrency backstop.
    """

    adapter = payment_adapter()
    if adapter == "stripe-test":
        # Stripe-test uses the hosted-checkout redirect + verified webhook path,
        # never this synchronous sandbox call.
        raise BackendError("stripe-test uses the hosted checkout flow")
    if adapter != "local-sandbox":
        raise BackendError("payment adapter is not declared by the runtime")
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = _pro_row(connection, owner_key, active_only=True)
        if active is not None:
            connection.commit()
            return {
                "result": "already_active",
                "subscription": dict(active),
                "receipt_id": active["receipt_id"],
            }
        period_start, period_end = _pro_period()
        fingerprint = _pro_fingerprint(owner_key, period_start)
        flow = site_backend().payments.create_intent(
            owner=owner_key,
            amount_minor=PRO_AMOUNT_MINOR,
            currency=PRO_CURRENCY,
            fingerprint=fingerprint,
            idempotency_key=f"tripit-pro-flow:{owner_key}:{period_start}",
            adapter=adapter,
            connection=connection,
        )
        configured = {
            str(item["id"])
            for item in runtime_config().payments["local_sandbox"]["scenarios"]
        }
        scenario_id = _resolve_pro_scenario(
            connection, str(flow["flow_id"]), scenario_token, configured
        )
        attempt = site_backend().payments.attempt(
            flow_id=str(flow["flow_id"]),
            owner=owner_key,
            amount_minor=PRO_AMOUNT_MINOR,
            currency=PRO_CURRENCY,
            fingerprint=fingerprint,
            scenario_id=scenario_id,
            idempotency_key=(
                f"tripit-pro-attempt:{owner_key}:{period_start}:{scenario_id}"
            ),
            connection=connection,
        )
        if attempt["status"] != "APPROVED":
            connection.commit()
            return {
                "result": (
                    "retryable" if attempt["status"] == "RETRYABLE" else "declined"
                ),
                "subscription": None,
                "receipt_id": None,
            }
        subscription = _activate_pro_subscription(
            connection,
            owner_key=owner_key,
            flow_id=str(flow["flow_id"]),
            fingerprint=fingerprint,
            amount_minor=PRO_AMOUNT_MINOR,
            currency=PRO_CURRENCY,
            period_start=period_start,
            period_end=period_end,
        )
        connection.commit()
        return {
            "result": "approved",
            "subscription": subscription,
            "receipt_id": subscription["receipt_id"],
        }
    except (PaymentConflict, PaymentError, PaymentRejected) as exc:
        if connection.in_transaction:
            connection.rollback()
        raise BackendError("payment authorization was rejected") from exc
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def cancel_pro(owner_key: str) -> dict[str, Any]:
    """Schedule cancellation at period end; Pro benefits persist until then.

    TripIt keeps you Pro through the paid term, so cancellation flips
    ``cancel_at_period_end`` rather than revoking entitlement. Status stays
    ``active`` (the one-active index still guards re-subscription).
    """

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _pro_row(connection, owner_key, active_only=True)
        if row is None:
            connection.commit()
            return {"result": "not_subscribed", "current_period_end": None}
        connection.execute(
            "UPDATE tripit_pro_subscriptions SET cancel_at_period_end=1, "
            "updated_at=? WHERE subscription_id=?",
            (FROZEN_CLOCK_UTC, row["subscription_id"]),
        )
        connection.commit()
        return {
            "result": "canceled",
            "current_period_end": row["current_period_end"],
        }
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def resume_pro(owner_key: str) -> dict[str, Any]:
    """Undo a scheduled cancellation while the term is still active."""

    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _pro_row(connection, owner_key, active_only=True)
        if row is None:
            connection.commit()
            return {"result": "not_subscribed", "current_period_end": None}
        connection.execute(
            "UPDATE tripit_pro_subscriptions SET cancel_at_period_end=0, "
            "updated_at=? WHERE subscription_id=?",
            (FROZEN_CLOCK_UTC, row["subscription_id"]),
        )
        connection.commit()
        return {
            "result": "resumed",
            "current_period_end": row["current_period_end"],
        }
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _provider_pro_flow_id(provider_snapshot: Mapping[str, Any]) -> str:
    """Extract and validate the flow id from a re-read Stripe test Session."""

    metadata = provider_snapshot.get("metadata")
    if not isinstance(metadata, Mapping):
        raise BackendError("Stripe test Session metadata is invalid")
    flow_id = metadata.get("flow_id")
    if not isinstance(flow_id, str) or re.fullmatch(
        r"payflow_[A-Za-z0-9_-]{12,120}", flow_id
    ) is None:
        raise BackendError("Stripe test Session metadata is invalid")
    return flow_id


def prepare_pro_stripe_checkout(owner_key: str) -> dict[str, Any]:
    """Persist/recover one Stripe-test flow before contacting the provider.

    Dormant until a payment-scope approval wires ``stripe_test``: raises unless
    the active adapter is ``stripe-test``. Written to mirror the edX reference so
    enabling the adapter needs no new domain code.
    """

    if payment_adapter() != "stripe-test":
        raise BackendError("stripe-test is not enabled by this profile")
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = _pro_row(connection, owner_key, active_only=True)
        if active is not None:
            connection.commit()
            return {"completed": True, "subscription": dict(active)}
        period_start, _period_end = _pro_period()
        fingerprint = _pro_fingerprint(owner_key, period_start)
        flow = site_backend().payments.create_intent(
            owner=owner_key,
            amount_minor=PRO_AMOUNT_MINOR,
            currency=PRO_CURRENCY,
            fingerprint=fingerprint,
            idempotency_key=f"tripit-pro-flow:{owner_key}:{period_start}",
            adapter="stripe-test",
            connection=connection,
        )
        account = connection.execute(
            "SELECT email_normalized FROM local_auth_accounts WHERE subject_id=?",
            (owner_key,),
        ).fetchone()
        connection.commit()
        return {
            "completed": False,
            "flow": flow,
            "customer_email": str(account["email_normalized"]) if account else "",
            "amount_minor": PRO_AMOUNT_MINOR,
        }
    except (PaymentConflict, PaymentError, PaymentRejected) as exc:
        if connection.in_transaction:
            connection.rollback()
        raise BackendError("payment authorization was rejected") from exc
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def process_verified_stripe_pro_payment(
    connection: sqlite3.Connection,
    *,
    provider_session_id: str,
    provider_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Consume a re-read Stripe test Session and activate Pro in one txn.

    The return/webhook boundary obtains ``provider_snapshot`` only through the
    isolated server gateway; the browser/webhook body supplies at most the
    opaque Session id. Dormant until ``stripe_test`` is wired (raises otherwise).
    """

    if payment_adapter() != "stripe-test":
        raise BackendError("stripe-test is not enabled by this profile")
    flow_id = _provider_pro_flow_id(provider_snapshot)
    connection.execute("BEGIN IMMEDIATE")
    try:
        flow = connection.execute(
            "SELECT owner FROM websitebench_payment_flows "
            "WHERE site_id=? AND flow_id=?",
            (SITE_ID, flow_id),
        ).fetchone()
        if flow is None:
            raise BackendError("payment flow not found")
        owner = str(flow["owner"])
        existing = _pro_row(connection, owner, active_only=True)
        if existing is not None:
            connection.commit()
            return {
                "result": "approved",
                "replayed": True,
                "subscription": dict(existing),
            }
        period_start, period_end = _pro_period()
        fingerprint = _pro_fingerprint(owner, period_start)
        site_backend().payments.attempt_verified_stripe(
            flow_id=flow_id,
            owner=owner,
            amount_minor=PRO_AMOUNT_MINOR,
            currency=PRO_CURRENCY,
            fingerprint=fingerprint,
            provider_session_id=provider_session_id,
            idempotency_key=f"tripit-pro-stripe:{flow_id}:{provider_session_id}",
            provider_verifier=lambda _session_id: provider_snapshot,
            connection=connection,
        )
        subscription = _activate_pro_subscription(
            connection,
            owner_key=owner,
            flow_id=flow_id,
            fingerprint=fingerprint,
            amount_minor=PRO_AMOUNT_MINOR,
            currency=PRO_CURRENCY,
            period_start=period_start,
            period_end=period_end,
        )
        connection.commit()
        return {
            "result": "approved",
            "replayed": False,
            "subscription": subscription,
        }
    except (PaymentConflict, PaymentError, PaymentRejected) as exc:
        if connection.in_transaction:
            connection.rollback()
        raise BackendError("payment authorization was rejected") from exc
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
