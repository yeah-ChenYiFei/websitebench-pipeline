"""Server-owned Songkick fan state on the scaffolded site database."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from websitebench.local_clone_auth import AuthRejected, LocalAuthStore


SCHEMA = """
CREATE TABLE IF NOT EXISTS songkick_fans (
    subject_id TEXT PRIMARY KEY,
    location TEXT NOT NULL DEFAULT 'Montreal',
    theme TEXT NOT NULL DEFAULT 'light' CHECK(theme IN ('light','dark')),
    locale TEXT NOT NULL DEFAULT 'en' CHECK(locale IN ('en','fr','es','de','pt')),
    cookie_preferences_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS songkick_artist_tracking (
    subject_id TEXT NOT NULL REFERENCES songkick_fans(subject_id) ON DELETE CASCADE,
    artist_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(subject_id, artist_id)
);
CREATE TABLE IF NOT EXISTS songkick_event_attendance (
    subject_id TEXT NOT NULL REFERENCES songkick_fans(subject_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('interested','attended')),
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(subject_id, event_id)
);
"""
_IDENTIFIER = re.compile(r"^[0-9]{1,24}$")
_LOCALES = {"en", "fr", "es", "de", "pt"}
_THEMES = {"light", "dark"}
_EVENT_STATES = {"none", "interested", "attended"}


def migrate(connection: sqlite3.Connection) -> None:
    """Forward-only idempotent migration hook declared by backend/runtime.json."""

    # The shared lifecycle owns the surrounding transaction.  ``executescript``
    # would implicitly commit it, so execute each fixed DDL statement in place.
    for statement in SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


class SongkickStore:
    def __init__(self, auth: LocalAuthStore, database_path: Path | str) -> None:
        self.auth = auth
        self.database_path = Path(database_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def subject_factory(
        connection: sqlite3.Connection, account: Mapping[str, Any]
    ) -> str:
        subject_id = f"songkick-fan-{account['account_id']}"
        now = int(time.time())
        connection.execute(
            "INSERT INTO songkick_fans(subject_id,created_at,updated_at) VALUES(?,?,?)",
            (subject_id, now, now),
        )
        return subject_id

    def owner(self, token: str | None) -> dict[str, Any]:
        session = self.auth.resolve_session(token)
        account = session.get("account") if session else None
        if not account:
            raise AuthRejected("authentication is required")
        return dict(account)

    def ensure_fixture_profile(self, subject_id: str) -> None:
        """Create only the verifier account's domain row, idempotently."""

        now = int(time.time())
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO songkick_fans(subject_id,created_at,updated_at) "
                "VALUES(?,?,?)",
                (subject_id, now, now),
            )
            connection.commit()

    def _subject(self, token: str | None) -> str:
        return str(self.owner(token)["subject_id"])

    @staticmethod
    def _entity_id(value: str, label: str) -> str:
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"{label} is invalid")
        return value

    def preferences(self, token: str | None) -> dict[str, Any]:
        subject = self._subject(token)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT location,theme,locale,cookie_preferences_json "
                "FROM songkick_fans WHERE subject_id=?",
                (subject,),
            ).fetchone()
        if row is None:
            raise AuthRejected("account profile is unavailable")
        return {
            "location": str(row["location"]),
            "theme": str(row["theme"]),
            "locale": str(row["locale"]),
            "cookie_preferences": json.loads(str(row["cookie_preferences_json"])),
        }

    def update_preferences(
        self,
        token: str | None,
        *,
        location: str,
        theme: str,
        locale: str,
        cookie_preferences: dict[str, bool],
    ) -> dict[str, Any]:
        subject = self._subject(token)
        normalized_location = " ".join(location.split())
        if not 1 <= len(normalized_location) <= 120:
            raise ValueError("location must contain 1 to 120 characters")
        if theme not in _THEMES:
            raise ValueError("theme is invalid")
        if locale not in _LOCALES:
            raise ValueError("locale is invalid")
        if any(not isinstance(key, str) or type(value) is not bool for key, value in cookie_preferences.items()):
            raise ValueError("cookie preferences must be boolean flags")
        if len(cookie_preferences) > 16:
            raise ValueError("too many cookie preferences")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE songkick_fans SET location=?,theme=?,locale=?,"
                "cookie_preferences_json=?,updated_at=? WHERE subject_id=?",
                (
                    normalized_location,
                    theme,
                    locale,
                    json.dumps(cookie_preferences, sort_keys=True, separators=(",", ":")),
                    int(time.time()),
                    subject,
                ),
            )
            if cursor.rowcount != 1:
                raise AuthRejected("account profile is unavailable")
            connection.commit()
        return self.preferences(token)

    def set_artist_tracking(
        self, token: str | None, artist_id: str, tracked: bool
    ) -> dict[str, Any]:
        subject = self._subject(token)
        artist = self._entity_id(artist_id, "artist id")
        with self.connect() as connection:
            if tracked:
                connection.execute(
                    "INSERT OR IGNORE INTO songkick_artist_tracking"
                    "(subject_id,artist_id,created_at) VALUES(?,?,?)",
                    (subject, artist, int(time.time())),
                )
            else:
                connection.execute(
                    "DELETE FROM songkick_artist_tracking WHERE subject_id=? AND artist_id=?",
                    (subject, artist),
                )
            connection.commit()
        return {"artist_id": artist, "tracked": tracked}

    def set_event_status(
        self, token: str | None, event_id: str, status: str
    ) -> dict[str, Any]:
        subject = self._subject(token)
        event = self._entity_id(event_id, "event id")
        if status not in _EVENT_STATES:
            raise ValueError("event status is invalid")
        with self.connect() as connection:
            if status == "none":
                connection.execute(
                    "DELETE FROM songkick_event_attendance WHERE subject_id=? AND event_id=?",
                    (subject, event),
                )
            else:
                connection.execute(
                    "INSERT INTO songkick_event_attendance(subject_id,event_id,status,updated_at) "
                    "VALUES(?,?,?,?) ON CONFLICT(subject_id,event_id) DO UPDATE SET "
                    "status=excluded.status,updated_at=excluded.updated_at",
                    (subject, event, status, int(time.time())),
                )
            connection.commit()
        return {"event_id": event, "status": status}

    def library(self, token: str | None) -> dict[str, Any]:
        subject = self._subject(token)
        with self.connect() as connection:
            artists = connection.execute(
                "SELECT artist_id FROM songkick_artist_tracking "
                "WHERE subject_id=? ORDER BY artist_id",
                (subject,),
            ).fetchall()
            events = connection.execute(
                "SELECT event_id,status FROM songkick_event_attendance "
                "WHERE subject_id=? ORDER BY event_id",
                (subject,),
            ).fetchall()
        return {
            "tracked_artist_ids": [str(row["artist_id"]) for row in artists],
            "events": [dict(row) for row in events],
        }
