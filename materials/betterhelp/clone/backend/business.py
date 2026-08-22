"""Site-bound BetterHelp business data for the offline synthetic fixture."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


PROVIDERS = (
    {
        "provider_id": "michelle-wilkinson",
        "name": "Michelle Wilkinson",
        "credentials": "LCSW",
        "specialties": ["anxiety", "stress", "coping-tools"],
        "bio": "A licensed clinical social worker focused on practical coping tools and stress support.",
        "image": "therapist-michelle.jpg",
    },
    {
        "provider_id": "susan-hargett",
        "name": "Susan Hargett",
        "credentials": "LMFT",
        "specialties": ["relationships", "communication", "wellbeing"],
        "bio": "A licensed marriage and family therapist focused on relationships and communication.",
        "image": "therapist-susan.jpg",
    },
    {
        "provider_id": "virginia-truglio",
        "name": "Virginia Truglio",
        "credentials": "LPC",
        "specialties": ["grief", "trauma", "insight"],
        "bio": "A licensed professional counselor focused on grief, trauma, and personal insight.",
        "image": "therapist-virginia.jpg",
    },
)

SLOT_TEMPLATES = (
    ("michelle-wilkinson", 7, 18),
    ("michelle-wilkinson", 9, 20),
    ("michelle-wilkinson", 11, 16),
    ("susan-hargett", 8, 19),
    ("susan-hargett", 10, 17),
    ("virginia-truglio", 7, 21),
    ("virginia-truglio", 12, 15),
)

INTAKE_FIELDS = {
    1: ("therapy_type", {"individual", "couples", "teen"}),
    2: ("state", {"California", "New York", "Texas", "Other"}),
    3: ("support", {"anxiety", "stress", "depression", "relationships", "trauma", "grief", "other"}),
    4: ("therapist_preference", {"no-preference", "woman", "man"}),
    5: ("therapy_experience", {"first-time", "returning"}),
    6: ("communication", {"video", "phone", "live-chat"}),
    7: ("availability", {"weekday-daytime", "weekday-evening", "weekend"}),
    8: ("goal", {"coping-tools", "insight", "relationships", "wellbeing"}),
}

BOOKING_PACKAGES = {"live-session"}
SESSION_TYPES = {"video", "phone", "live-chat"}
SPECIAL_REQUESTS = {"none", "synthetic-scheduling-request", "synthetic-accessibility-request"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fixture_slots(now: datetime | None = None) -> list[tuple[str, str, str]]:
    anchor = (now or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    for provider_id, days_ahead, hour in SLOT_TEMPLATES:
        starts_at = anchor + timedelta(days=days_ahead, hours=hour)
        slot_id = f"{provider_id}-{starts_at.strftime('%Y%m%dT%H%MZ')}"
        result.append((slot_id, provider_id, starts_at.isoformat().replace("+00:00", "Z")))
    return result


def ensure_future_slots(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DELETE FROM betterhelp_availability WHERE starts_at<=? AND NOT EXISTS ("
        "SELECT 1 FROM betterhelp_bookings b WHERE b.slot_id=betterhelp_availability.slot_id)",
        (utc_now(),),
    )
    for slot_id, provider_id, starts_at in fixture_slots():
        connection.execute(
            "INSERT OR IGNORE INTO betterhelp_availability(slot_id,provider_id,starts_at) VALUES (?,?,?)",
            (slot_id, provider_id, starts_at),
        )


def migrate_v4(connection: sqlite3.Connection) -> None:
    schema = """
        CREATE TABLE IF NOT EXISTS betterhelp_schema_versions(
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS betterhelp_intakes(
            owner TEXT PRIMARY KEY,
            current_step INTEGER NOT NULL,
            answers_json TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS betterhelp_providers(
            provider_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            credentials TEXT NOT NULL,
            specialties_json TEXT NOT NULL,
            bio TEXT NOT NULL,
            image TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS betterhelp_availability(
            slot_id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL REFERENCES betterhelp_providers(provider_id),
            starts_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS betterhelp_saved_providers(
            owner TEXT NOT NULL,
            provider_id TEXT NOT NULL REFERENCES betterhelp_providers(provider_id),
            created_at TEXT NOT NULL,
            PRIMARY KEY(owner, provider_id)
        );
        CREATE TABLE IF NOT EXISTS betterhelp_bookings(
            booking_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            provider_id TEXT NOT NULL REFERENCES betterhelp_providers(provider_id),
            slot_id TEXT NOT NULL REFERENCES betterhelp_availability(slot_id),
            status TEXT NOT NULL,
            display_name TEXT,
            consent INTEGER NOT NULL DEFAULT 0,
            amount_minor INTEGER NOT NULL DEFAULT 7000,
            payment_flow_id TEXT,
            mail_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS betterhelp_bookings_owner_idx
            ON betterhelp_bookings(owner, created_at DESC);
        DROP INDEX IF EXISTS betterhelp_active_slot_idx;
        CREATE UNIQUE INDEX IF NOT EXISTS betterhelp_active_slot_idx
            ON betterhelp_bookings(slot_id)
            WHERE status IN ('confirmed');
        CREATE TABLE IF NOT EXISTS betterhelp_reviews(
            review_id TEXT PRIMARY KEY,
            booking_id TEXT NOT NULL UNIQUE REFERENCES betterhelp_bookings(booking_id),
            owner TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS betterhelp_support_requests(
            request_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            topic TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS betterhelp_member_preferences(
            owner TEXT PRIMARY KEY,
            language TEXT NOT NULL,
            keep_active INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS betterhelp_recovery_devices(
            account_id TEXT NOT NULL,
            token_digest TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            PRIMARY KEY(account_id, token_digest)
        );
        CREATE INDEX IF NOT EXISTS betterhelp_recovery_devices_account_idx
            ON betterhelp_recovery_devices(account_id, created_at DESC);
        """
    # ``executescript`` commits implicitly and would break the SiteBackend
    # initialization transaction. Execute each DDL statement on the bound
    # connection so migration remains atomic and site-isolated.
    for statement in schema.split(";"):
        if statement.strip():
            connection.execute(statement)
    booking_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(betterhelp_bookings)").fetchall()
    }
    for column, definition in (
        ("package_id", "TEXT NOT NULL DEFAULT 'live-session'"),
        ("session_type", "TEXT NOT NULL DEFAULT 'video'"),
        ("special_request", "TEXT NOT NULL DEFAULT 'none'"),
        ("intake_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        if column not in booking_columns:
            connection.execute(f"ALTER TABLE betterhelp_bookings ADD COLUMN {column} {definition}")
    connection.execute(
        "INSERT OR IGNORE INTO betterhelp_schema_versions(version,applied_at) VALUES (1,?)",
        (utc_now(),),
    )
    connection.execute(
        "INSERT OR IGNORE INTO betterhelp_schema_versions(version,applied_at) VALUES (2,?)",
        (utc_now(),),
    )
    connection.execute(
        "INSERT OR IGNORE INTO betterhelp_schema_versions(version,applied_at) VALUES (3,?)",
        (utc_now(),),
    )
    connection.execute(
        "INSERT OR IGNORE INTO betterhelp_schema_versions(version,applied_at) VALUES (4,?)",
        (utc_now(),),
    )
    for provider in PROVIDERS:
        connection.execute(
            "INSERT OR IGNORE INTO betterhelp_providers(provider_id,name,credentials,specialties_json,bio,image) VALUES (?,?,?,?,?,?)",
            (
                provider["provider_id"],
                provider["name"],
                provider["credentials"],
                json.dumps(provider["specialties"], sort_keys=True),
                provider["bio"],
                provider["image"],
            ),
        )
    connection.execute(
        "UPDATE betterhelp_bookings SET intake_snapshot_json=("
        "SELECT i.answers_json FROM betterhelp_intakes i WHERE i.owner=betterhelp_bookings.owner "
        "AND i.completed_at IS NOT NULL) WHERE intake_snapshot_json='{}' AND EXISTS ("
        "SELECT 1 FROM betterhelp_intakes i WHERE i.owner=betterhelp_bookings.owner "
        "AND i.completed_at IS NOT NULL)"
    )
    ensure_future_slots(connection)


def reset_mutable(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM betterhelp_recovery_devices")
    connection.execute("DELETE FROM betterhelp_member_preferences")
    connection.execute("DELETE FROM betterhelp_reviews")
    connection.execute("DELETE FROM betterhelp_support_requests")
    connection.execute("DELETE FROM betterhelp_bookings")
    connection.execute("DELETE FROM betterhelp_saved_providers")
    connection.execute("DELETE FROM betterhelp_intakes")
    connection.execute("DELETE FROM betterhelp_availability")
    ensure_future_slots(connection)


def remember_recovery_device(
    connection: sqlite3.Connection, account_id: str, token: str
) -> None:
    if not account_id or len(token) < 32:
        raise ValueError("invalid recovery device")
    digest = hashlib.sha256(f"betterhelp-recovery:{token}".encode()).hexdigest()
    connection.execute(
        "INSERT OR REPLACE INTO betterhelp_recovery_devices(account_id,token_digest,created_at) "
        "VALUES (?,?,?)",
        (account_id, digest, utc_now()),
    )
    connection.execute(
        "DELETE FROM betterhelp_recovery_devices WHERE account_id=? AND token_digest NOT IN ("
        "SELECT token_digest FROM betterhelp_recovery_devices WHERE account_id=? "
        "ORDER BY created_at DESC LIMIT 5)",
        (account_id, account_id),
    )


def recovery_device_authorized(
    connection: sqlite3.Connection, email: str, token: str | None
) -> bool:
    if not token or len(token) < 32:
        return False
    digest = hashlib.sha256(f"betterhelp-recovery:{token}".encode()).hexdigest()
    row = connection.execute(
        "SELECT 1 FROM betterhelp_recovery_devices d "
        "JOIN local_auth_accounts a ON a.account_id=d.account_id "
        "WHERE a.email_normalized=? AND d.token_digest=?",
        (email, digest),
    ).fetchone()
    return row is not None


def save_intake_answer(connection: sqlite3.Connection, owner: str, step: int, value: str) -> dict[str, Any]:
    field = INTAKE_FIELDS.get(step)
    if field is None or value not in field[1]:
        raise ValueError("Choose one answer before continuing.")
    row = connection.execute(
        "SELECT current_step,answers_json,completed_at FROM betterhelp_intakes WHERE owner=?",
        (owner,),
    ).fetchone()
    answers = json.loads(row["answers_json"]) if row else {}
    answers[field[0]] = value
    now = utc_now()
    current_step = min(8, max(step, int(row["current_step"]) if row else 1))
    completed_at = now if step == 8 and all(INTAKE_FIELDS[i][0] in answers for i in range(1, 9)) else (row["completed_at"] if row else None)
    connection.execute(
        "INSERT INTO betterhelp_intakes(owner,current_step,answers_json,completed_at,updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(owner) DO UPDATE SET current_step=excluded.current_step,answers_json=excluded.answers_json,completed_at=excluded.completed_at,updated_at=excluded.updated_at",
        (owner, current_step, json.dumps(answers, sort_keys=True), completed_at, now),
    )
    return {"owner": owner, "current_step": current_step, "answers": answers, "completed_at": completed_at}


def intake(connection: sqlite3.Connection, owner: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM betterhelp_intakes WHERE owner=?", (owner,)).fetchone()
    if row is None:
        return None
    return {"owner": row["owner"], "current_step": int(row["current_step"]), "answers": json.loads(row["answers_json"]), "completed_at": row["completed_at"]}


def count_completed_intakes(backend: Any) -> int:
    with backend.lifecycle.connection() as connection:
        row = connection.execute("SELECT COUNT(*) FROM betterhelp_intakes WHERE completed_at IS NOT NULL").fetchone()
        return int(row[0])


def member_preferences(connection: sqlite3.Connection, owner: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT language,keep_active,updated_at FROM betterhelp_member_preferences WHERE owner=?",
        (owner,),
    ).fetchone()
    if row is None:
        return {"language": "English", "keep_active": True, "updated_at": None}
    return {
        "language": row["language"],
        "keep_active": bool(row["keep_active"]),
        "updated_at": row["updated_at"],
    }


def save_member_preferences(
    connection: sqlite3.Connection,
    owner: str,
    *,
    language: str,
    keep_active: bool,
) -> dict[str, Any]:
    if language != "English":
        raise ValueError("Choose an available language.")
    now = utc_now()
    connection.execute(
        "INSERT INTO betterhelp_member_preferences(owner,language,keep_active,updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(owner) DO UPDATE SET language=excluded.language,keep_active=excluded.keep_active,updated_at=excluded.updated_at",
        (owner, language, int(keep_active), now),
    )
    return {"language": language, "keep_active": keep_active, "updated_at": now}


def providers(
    connection: sqlite3.Connection,
    query: str = "",
    specialty: str = "",
    sort: str = "name-asc",
) -> list[sqlite3.Row]:
    terms = query.strip().casefold()
    specialty = specialty.strip().casefold()
    rows = connection.execute("SELECT * FROM betterhelp_providers ORDER BY name").fetchall()
    result = []
    for row in rows:
        haystack = " ".join((row["name"], row["credentials"], row["bio"], row["specialties_json"])).casefold()
        specialties = json.loads(row["specialties_json"])
        if terms and terms not in haystack:
            continue
        if specialty and specialty not in specialties:
            continue
        result.append(row)
    if sort == "name-desc":
        result.sort(key=lambda row: row["name"].casefold(), reverse=True)
    elif sort == "availability":
        next_slots = {
            row["provider_id"]: row["next_slot"]
            for row in connection.execute(
                "SELECT p.provider_id,MIN(a.starts_at) AS next_slot FROM betterhelp_providers p "
                "LEFT JOIN betterhelp_availability a ON a.provider_id=p.provider_id AND a.starts_at>? "
                "AND NOT EXISTS (SELECT 1 FROM betterhelp_bookings b WHERE b.slot_id=a.slot_id AND b.status='confirmed') "
                "GROUP BY p.provider_id",
                (utc_now(),),
            ).fetchall()
        }
        result.sort(key=lambda row: (next_slots.get(row["provider_id"]) or "9999", row["name"].casefold()))
    else:
        result.sort(key=lambda row: row["name"].casefold())
    return result


def provider(connection: sqlite3.Connection, provider_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM betterhelp_providers WHERE provider_id=?", (provider_id,)).fetchone()


def provider_slots(connection: sqlite3.Connection, provider_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT a.* FROM betterhelp_availability a WHERE a.provider_id=? AND a.starts_at>? AND NOT EXISTS ("
        "SELECT 1 FROM betterhelp_bookings b WHERE b.slot_id=a.slot_id AND b.status IN ('confirmed')) ORDER BY starts_at",
        (provider_id, utc_now()),
    ).fetchall()


def save_provider(connection: sqlite3.Connection, owner: str, provider_id: str) -> None:
    if provider(connection, provider_id) is None:
        raise ValueError("Therapist not found.")
    connection.execute(
        "INSERT OR IGNORE INTO betterhelp_saved_providers(owner,provider_id,created_at) VALUES (?,?,?)",
        (owner, provider_id, utc_now()),
    )


def saved_providers(connection: sqlite3.Connection, owner: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT p.* FROM betterhelp_saved_providers s JOIN betterhelp_providers p ON p.provider_id=s.provider_id WHERE s.owner=? ORDER BY s.created_at DESC",
        (owner,),
    ).fetchall()


def create_booking(connection: sqlite3.Connection, owner: str, provider_id: str, slot_id: str) -> sqlite3.Row:
    slot = connection.execute(
        "SELECT * FROM betterhelp_availability WHERE slot_id=? AND provider_id=?",
        (slot_id, provider_id),
    ).fetchone()
    if slot is None:
        raise ValueError("Choose an available appointment time.")
    starts_at = datetime.fromisoformat(str(slot["starts_at"]).replace("Z", "+00:00"))
    if starts_at <= datetime.now(timezone.utc):
        raise ValueError("Choose a future appointment time.")
    occupied = connection.execute(
        "SELECT 1 FROM betterhelp_bookings WHERE slot_id=? AND status IN ('confirmed')",
        (slot_id,),
    ).fetchone()
    if occupied:
        raise ValueError("That appointment time is no longer available.")
    booking_id = f"BH-{secrets.token_hex(6).upper()}"
    now = utc_now()
    connection.execute(
        "INSERT INTO betterhelp_bookings(booking_id,owner,provider_id,slot_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        (booking_id, owner, provider_id, slot_id, "draft", now, now),
    )
    return owned_booking(connection, owner, booking_id)


def owned_booking(connection: sqlite3.Connection, owner: str, booking_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT b.*,p.name AS provider_name,a.starts_at FROM betterhelp_bookings b "
        "JOIN betterhelp_providers p ON p.provider_id=b.provider_id "
        "JOIN betterhelp_availability a ON a.slot_id=b.slot_id "
        "WHERE b.booking_id=? AND b.owner=?",
        (booking_id, owner),
    ).fetchone()


def save_booking_details(
    connection: sqlite3.Connection,
    owner: str,
    booking_id: str,
    display_name: str,
    consent: bool,
    *,
    package_id: str,
    session_type: str,
    special_request: str,
    expected_display_name: str | None = None,
) -> sqlite3.Row:
    row = owned_booking(connection, owner, booking_id)
    if row is None:
        raise LookupError("Booking not found.")
    if row["status"] != "draft":
        raise ValueError("Booking details cannot be changed in this state.")
    if not display_name.strip() or not consent or (expected_display_name is not None and display_name.strip() != expected_display_name.strip()):
        raise ValueError("Name and consent are required.")
    if package_id not in BOOKING_PACKAGES or session_type not in SESSION_TYPES or special_request not in SPECIAL_REQUESTS:
        raise ValueError("Choose an available package, session format, and request option.")
    current_intake = intake(connection, owner)
    if current_intake is None or not current_intake["completed_at"]:
        raise ValueError("Complete the questionnaire before booking.")
    intake_snapshot_json = json.dumps(current_intake["answers"], sort_keys=True)
    connection.execute(
        "UPDATE betterhelp_bookings SET display_name=?,package_id=?,session_type=?,special_request=?,"
        "intake_snapshot_json=?,consent=1,status='details-ready',updated_at=? WHERE booking_id=? AND owner=?",
        (display_name.strip(), package_id, session_type, special_request, intake_snapshot_json, utc_now(), booking_id, owner),
    )
    return owned_booking(connection, owner, booking_id)


def payment_fingerprint(row: sqlite3.Row, *, include_intake_snapshot: bool = True) -> str:
    payload = {
        "amount_minor": int(row["amount_minor"]),
        "booking_id": row["booking_id"],
        "currency": "USD",
        "owner": row["owner"],
        "provider_id": row["provider_id"],
        "package_id": row["package_id"],
        "session_type": row["session_type"],
        "special_request": row["special_request"],
        "slot_id": row["slot_id"],
    }
    if include_intake_snapshot:
        payload["intake_snapshot_json"] = row["intake_snapshot_json"]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def pay_booking(backend: Any, owner: str, booking_id: str, recipient: str, scenario_id: str) -> tuple[sqlite3.Row, dict[str, Any]]:
    with backend.lifecycle.connection(transaction=True) as connection:
        row = owned_booking(connection, owner, booking_id)
        if row is None:
            raise LookupError("Booking not found.")
        if row["status"] == "confirmed":
            return row, {"status": "APPROVED", "replayed": True}
        if row["status"] != "details-ready":
            raise ValueError("Complete booking details before payment.")
        flow_owner = f"booking:{booking_id}"
        create_idempotency_key = f"betterhelp.create:{booking_id}"
        fingerprint = payment_fingerprint(row)
        existing_flow = connection.execute(
            "SELECT fingerprint FROM websitebench_payment_flows "
            "WHERE site_id=? AND owner=? AND create_idempotency_key=?",
            (backend.config.site_id, flow_owner, create_idempotency_key),
        ).fetchone()
        legacy_fingerprint = payment_fingerprint(row, include_intake_snapshot=False)
        if existing_flow is not None and existing_flow["fingerprint"] == legacy_fingerprint:
            # v3 flows did not include the immutable questionnaire snapshot. Keep
            # their exact fingerprint so a declined/retryable flow can finish
            # after v4 backfills the snapshot, while unrelated fact changes still
            # fail the payment backend's immutable-facts checks.
            fingerprint = legacy_fingerprint
        facts = {
            "owner": flow_owner,
            "amount_minor": int(row["amount_minor"]),
            "currency": "USD",
            "fingerprint": fingerprint,
        }
        flow = backend.payments.create_intent(
            **facts,
            idempotency_key=create_idempotency_key,
            connection=connection,
        )
        attempt = backend.payments.attempt(
            flow_id=flow["flow_id"],
            **facts,
            scenario_id=scenario_id,
            idempotency_key=f"betterhelp.attempt:{booking_id}:{scenario_id}",
            connection=connection,
        )
        if attempt["status"] != "APPROVED":
            return row, attempt
        backend.payments.consume_approval(
            connection,
            flow_id=flow["flow_id"],
            **facts,
        )
        mail = backend.mail.enqueue(
            "booking-confirmation",
            recipient,
            {
                "booking_id": booking_id,
                "provider_name": row["provider_name"],
                "starts_at": row["starts_at"],
            },
            idempotency_key=f"betterhelp.mail:{booking_id}",
            simulation=True,
            connection=connection,
        )
        try:
            updated = connection.execute(
                "UPDATE betterhelp_bookings SET status='confirmed',payment_flow_id=?,mail_id=?,updated_at=? "
                "WHERE booking_id=? AND owner=? AND status='details-ready'",
                (flow["flow_id"], mail["mail_id"], utc_now(), booking_id, owner),
            )
        except sqlite3.IntegrityError as exc:
            # A concurrent confirmation may win the partial unique slot index.
            # Convert the database race into a deterministic local business error;
            # the surrounding transaction rolls back payment/mail side effects.
            if "betterhelp_active_slot_idx" in str(exc) or "UNIQUE constraint failed: betterhelp_bookings.slot_id" in str(exc):
                raise ValueError("That appointment time was just booked by another member.") from exc
            raise
        if updated.rowcount != 1:
            raise ValueError("That appointment time was just booked by another member.")
        return owned_booking(connection, owner, booking_id), {**attempt, "mail": mail}


def bookings(connection: sqlite3.Connection, owner: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT b.*,p.name AS provider_name,a.starts_at FROM betterhelp_bookings b "
        "JOIN betterhelp_providers p ON p.provider_id=b.provider_id "
        "JOIN betterhelp_availability a ON a.slot_id=b.slot_id "
        "WHERE b.owner=? ORDER BY b.created_at DESC",
        (owner,),
    ).fetchall()


def manage_booking(connection: sqlite3.Connection, owner: str, booking_id: str, action: str, slot_id: str = "") -> sqlite3.Row:
    row = owned_booking(connection, owner, booking_id)
    if row is None:
        raise LookupError("Booking not found.")
    if action == "cancel" and row["status"] in {"draft", "details-ready", "confirmed"}:
        connection.execute(
            "UPDATE betterhelp_bookings SET status='cancelled',updated_at=? WHERE booking_id=? AND owner=?",
            (utc_now(), booking_id, owner),
        )
    elif action == "reschedule" and row["status"] == "confirmed":
        slot = connection.execute(
            "SELECT starts_at FROM betterhelp_availability WHERE slot_id=? AND provider_id=?",
            (slot_id, row["provider_id"]),
        ).fetchone()
        occupied = connection.execute(
            "SELECT 1 FROM betterhelp_bookings WHERE slot_id=? AND booking_id<>? AND status IN ('confirmed')",
            (slot_id, booking_id),
        ).fetchone()
        if slot is None or occupied:
            raise ValueError("Choose an available appointment time.")
        starts_at = datetime.fromisoformat(str(slot["starts_at"]).replace("Z", "+00:00"))
        if starts_at <= datetime.now(timezone.utc):
            raise ValueError("Choose a future appointment time.")
        connection.execute(
            "UPDATE betterhelp_bookings SET slot_id=?,updated_at=? WHERE booking_id=? AND owner=?",
            (slot_id, utc_now(), booking_id, owner),
        )
    else:
        raise ValueError("This booking cannot be changed in its current state.")
    return owned_booking(connection, owner, booking_id)


def add_review(connection: sqlite3.Connection, owner: str, booking_id: str, rating: int, comment: str) -> None:
    row = owned_booking(connection, owner, booking_id)
    if row is None:
        raise LookupError("Booking not found.")
    if not reviewable(row) or rating not in range(1, 6) or not comment.strip() or len(comment) > 500 or not _synthetic_text(comment):
        raise ValueError("A completed session, rating, and short review are required.")
    connection.execute(
        "INSERT INTO betterhelp_reviews(review_id,booking_id,owner,rating,comment,created_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(booking_id) DO UPDATE SET rating=excluded.rating,comment=excluded.comment",
        (f"BHR-{secrets.token_hex(6).upper()}", booking_id, owner, rating, comment.strip(), utc_now()),
    )


def reviewable(row: sqlite3.Row) -> bool:
    starts_at = datetime.fromisoformat(str(row["starts_at"]).replace("Z", "+00:00"))
    return row["status"] == "confirmed" and starts_at <= datetime.now(timezone.utc)


def add_support_request(connection: sqlite3.Connection, owner: str, topic: str, message: str) -> str:
    allowed_topics = {
        "registered-client", "current-therapist", "therapist-applicant", "service-question",
        "billing", "press", "business", "organization", "account", "booking", "technical",
    }
    if topic not in allowed_topics or not message.strip() or len(message) > 500 or not _synthetic_text(message):
        raise ValueError("Choose a topic and enter a short message.")
    request_id = f"BHS-{secrets.token_hex(6).upper()}"
    connection.execute(
        "INSERT INTO betterhelp_support_requests(request_id,owner,topic,message,status,created_at) VALUES (?,?,?,?,?,?)",
        (request_id, owner, topic, message.strip(), "received", utc_now()),
    )
    return request_id


def support_request_owned(connection: sqlite3.Connection, owner: str, request_id: str) -> bool:
    if not request_id:
        return False
    return connection.execute(
        "SELECT 1 FROM betterhelp_support_requests WHERE request_id=? AND owner=?",
        (request_id, owner),
    ).fetchone() is not None


def _synthetic_text(value: str) -> bool:
    """Allow only documented fixture text; never persist arbitrary health narratives."""
    normalized = " ".join(value.strip().casefold().split())
    return normalized in {
        "this session was helpful.",
        "i need help with my account.",
        "i need help with a technical issue.",
        "synthetic session review.",
        "synthetic help request",
        "synthetic technical request",
        "local fixture account request",
        "synthetic support request",
        "synthetic account support request",
        "synthetic billing support request",
        "synthetic service question",
        "test fixture booking request",
    }
