"""Crunchyroll-specific business schema and deterministic seed hooks."""

from __future__ import annotations

import sqlite3


STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS crunchyroll_profiles (
        owner TEXT NOT NULL, profile_id TEXT NOT NULL, name TEXT NOT NULL,
        maturity TEXT NOT NULL DEFAULT 'Mature',
        language TEXT NOT NULL DEFAULT 'English (US)',
        is_active INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (owner, profile_id)
    )""",
    """CREATE TABLE IF NOT EXISTS crunchyroll_watchlist (
        owner TEXT NOT NULL, series_id TEXT NOT NULL,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        PRIMARY KEY (owner, series_id)
    )""",
    """CREATE TABLE IF NOT EXISTS crunchyroll_progress (
        owner TEXT NOT NULL, episode_id TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0, duration INTEGER NOT NULL DEFAULT 1440,
        updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        PRIMARY KEY (owner, episode_id)
    )""",
    """CREATE TABLE IF NOT EXISTS crunchyroll_subscriptions (
        owner TEXT PRIMARY KEY, plan TEXT NOT NULL, term TEXT NOT NULL,
        status TEXT NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL,
        payment_scenario TEXT NOT NULL, flow_id TEXT NOT NULL,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    )""",
    """CREATE TABLE IF NOT EXISTS crunchyroll_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
        item_type TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
        detail TEXT NOT NULL,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    )""",
    """CREATE TABLE IF NOT EXISTS crunchyroll_preferences (
        owner TEXT PRIMARY KEY, audio_language TEXT NOT NULL DEFAULT 'Japanese',
        subtitle_language TEXT NOT NULL DEFAULT 'English (US)',
        autoplay INTEGER NOT NULL DEFAULT 1, notifications INTEGER NOT NULL DEFAULT 1,
        privacy_mode TEXT NOT NULL DEFAULT 'Standard'
    )""",
    """CREATE TABLE IF NOT EXISTS crunchyroll_devices (
        owner TEXT NOT NULL, device_id TEXT NOT NULL, label TEXT NOT NULL,
        last_used TEXT NOT NULL, PRIMARY KEY (owner, device_id)
    )""",
    """CREATE TABLE IF NOT EXISTS crunchyroll_seed_marker (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        seed_version TEXT NOT NULL
    )""",
)


def migrate(connection: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        connection.execute(statement)


def seed(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO crunchyroll_seed_marker(singleton,seed_version) VALUES (1,'crunchyroll-seed-v1')"
    )


def reset_business(connection: sqlite3.Connection) -> None:
    for table in (
        "crunchyroll_profiles",
        "crunchyroll_watchlist",
        "crunchyroll_progress",
        "crunchyroll_subscriptions",
        "crunchyroll_history",
        "crunchyroll_preferences",
        "crunchyroll_devices",
    ):
        connection.execute(f"DELETE FROM {table}")
