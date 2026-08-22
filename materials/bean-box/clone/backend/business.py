"""Deterministic Bean Box catalogue, subscription, cart and order storage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


ROASTS = ("light", "medium", "dark")
ROASTERS = (
    "Broadcast Coffee",
    "Camber Coffee",
    "Fulcrum Coffee",
    "Joe Coffee Company",
    "Kuma Coffee",
    "Olympia Coffee",
    "Partners Coffee",
    "Sightglass Coffee",
    "Temple Coffee",
    "Water Avenue Coffee",
    "Wonderstate Coffee",
    "Zoka Coffee",
)
ORIGINS = (
    "Ethiopia",
    "Colombia",
    "Guatemala",
    "Brazil",
    "Costa Rica",
    "Kenya",
    "Honduras",
    "Peru",
    "Rwanda",
    "Mexico",
)
NOTES = (
    "milk chocolate, caramel, orange",
    "jasmine, bergamot, peach",
    "cocoa, brown sugar, almond",
    "berry, citrus, honey",
    "toffee, cherry, vanilla",
    "plum, cacao, baking spice",
    "lemon, florals, black tea",
    "hazelnut, maple, apple",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(connection: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS bean_box_schema_versions(
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS bean_box_runtime_secrets(
          secret_name TEXT PRIMARY KEY,
          secret_value BLOB NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS bean_box_coffees(
          id INTEGER PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          roaster TEXT NOT NULL,
          origin TEXT NOT NULL,
          roast TEXT NOT NULL CHECK(roast IN ('light','medium','dark')),
          coffee_type TEXT NOT NULL,
          notes TEXT NOT NULL,
          price_minor INTEGER NOT NULL,
          rating REAL NOT NULL,
          reviews INTEGER NOT NULL,
          description TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS bean_box_drafts(
          owner TEXT PRIMARY KEY,
          payload_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS bean_box_cart_items(
          owner TEXT NOT NULL,
          coffee_id INTEGER NOT NULL REFERENCES bean_box_coffees(id),
          quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20),
          PRIMARY KEY(owner, coffee_id)
        )""",
        """CREATE TABLE IF NOT EXISTS bean_box_orders(
          order_id TEXT PRIMARY KEY,
          owner TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          payment_flow_id TEXT NOT NULL,
          status TEXT NOT NULL,
          amount_minor INTEGER NOT NULL,
          snapshot_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(owner, idempotency_key)
        )""",
        """CREATE TABLE IF NOT EXISTS bean_box_subscriptions(
          subscription_id TEXT PRIMARY KEY,
          owner TEXT NOT NULL,
          order_id TEXT NOT NULL UNIQUE REFERENCES bean_box_orders(order_id),
          status TEXT NOT NULL CHECK(status IN ('active','paused','cancelled')),
          draft_json TEXT NOT NULL,
          next_delivery_label TEXT NOT NULL,
          skip_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS bean_box_subscription_events(
          event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          subscription_id TEXT NOT NULL REFERENCES bean_box_subscriptions(subscription_id),
          event_type TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        )""",
    )
    for statement in statements:
        connection.execute(statement)
    connection.execute(
        "INSERT OR IGNORE INTO bean_box_schema_versions(version, applied_at) VALUES (1, ?)",
        (_now(),),
    )
    connection.execute(
        "INSERT OR IGNORE INTO bean_box_schema_versions(version, applied_at) VALUES (2, ?)",
        (_now(),),
    )


def seed(connection: sqlite3.Connection) -> None:
    count = connection.execute("SELECT COUNT(*) FROM bean_box_coffees").fetchone()[0]
    if count >= 240:
        return
    adjectives = ("Morning", "Sunrise", "Meadow", "Summit", "Harbor", "Garden", "Cedar", "Golden", "Velvet", "Wild")
    nouns = ("Bloom", "Trail", "Challa", "Horizon", "Orchard", "Reserve", "Canopy", "Solstice", "Compass", "Mosaic", "Ember", "Current")
    for index in range(1, 241):
        name = f"{adjectives[(index - 1) % len(adjectives)]} {nouns[((index - 1) // len(adjectives)) % len(nouns)]} {index:03d}"
        slug = name.lower().replace(" ", "-")
        roaster = ROASTERS[(index - 1) % len(ROASTERS)]
        origin = ORIGINS[(index * 3) % len(ORIGINS)]
        roast = ROASTS[(index - 1) % len(ROASTS)]
        coffee_type = "single origin" if index % 3 else "blend"
        notes = NOTES[(index - 1) % len(NOTES)]
        price = 1600 + (index % 9) * 100
        rating = round(4.2 + (index % 8) / 10, 1)
        reviews = 18 + (index * 17) % 390
        description = f"A {roast} roast from {origin}, roasted by {roaster}, with notes of {notes}. Curated for a balanced, expressive cup."
        connection.execute(
            "INSERT OR IGNORE INTO bean_box_coffees VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (index, slug, name, roaster, origin, roast, coffee_type, notes, price, rating, reviews, description),
        )


def default_draft() -> dict[str, Any]:
    return {
        "preparation": "whole-bean",
        "taste": "curators-choice",
        "quantity": "solo-sipper",
        "cadence": "4",
        "plan": "pay-per-delivery",
        "step": 1,
    }


def load_draft(connection: sqlite3.Connection, owner: str) -> dict[str, Any]:
    row = connection.execute("SELECT payload_json FROM bean_box_drafts WHERE owner=?", (owner,)).fetchone()
    return default_draft() if row is None else json.loads(row[0])


def save_draft(connection: sqlite3.Connection, owner: str, payload: dict[str, Any]) -> dict[str, Any]:
    clean = default_draft()
    clean.update({key: payload[key] for key in clean if key in payload})
    clean["step"] = max(1, min(3, int(clean["step"])))
    connection.execute(
        "INSERT INTO bean_box_drafts(owner,payload_json,updated_at) VALUES (?,?,?) ON CONFLICT(owner) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
        (owner, json.dumps(clean, sort_keys=True), _now()),
    )
    return clean


def list_coffees(connection: sqlite3.Connection, query: str = "", roast: str = "", page: int = 1, per_page: int = 18) -> tuple[list[sqlite3.Row], int]:
    terms: list[str] = []
    params: list[Any] = []
    if query:
        terms.append("(name LIKE ? OR roaster LIKE ? OR origin LIKE ? OR notes LIKE ?)")
        needle = f"%{query}%"
        params.extend([needle] * 4)
    if roast in ROASTS:
        terms.append("roast=?")
        params.append(roast)
    where = f" WHERE {' AND '.join(terms)}" if terms else ""
    total = connection.execute(f"SELECT COUNT(*) FROM bean_box_coffees{where}", params).fetchone()[0]
    offset = (max(1, page) - 1) * per_page
    rows = connection.execute(
        f"SELECT * FROM bean_box_coffees{where} ORDER BY id LIMIT ? OFFSET ?",
        [*params, per_page, offset],
    ).fetchall()
    return rows, int(total)


def coffee_by_slug(connection: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM bean_box_coffees WHERE slug=?", (slug,)).fetchone()


def add_cart(connection: sqlite3.Connection, owner: str, coffee_id: int, quantity: int = 1) -> None:
    connection.execute(
        "INSERT INTO bean_box_cart_items(owner,coffee_id,quantity) VALUES (?,?,?) ON CONFLICT(owner,coffee_id) DO UPDATE SET quantity=MIN(20,quantity+excluded.quantity)",
        (owner, coffee_id, max(1, min(20, quantity))),
    )


def cart(connection: sqlite3.Connection, owner: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT c.*,i.quantity FROM bean_box_cart_items i JOIN bean_box_coffees c ON c.id=i.coffee_id WHERE i.owner=? ORDER BY c.id",
        (owner,),
    ).fetchall()


def draft_amount_minor(draft: dict[str, Any]) -> int:
    quantity = {"trace-six-cup": 1, "solo-sipper": 1, "duo": 2, "large-solo": 3, "office-duo": 6}.get(str(draft.get("quantity")), 1)
    per_bag = 1500 if draft.get("plan") == "annual" else 1700
    shipping = 0 if draft.get("plan") == "annual" else 545
    return quantity * per_bag + shipping


def payment_fingerprint(owner: str, draft: dict[str, Any], amount_minor: int) -> str:
    canonical = json.dumps({"site_id": "bean-box", "owner": owner, "draft": draft, "amount_minor": amount_minor, "currency": "USD"}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_subscription(
    connection: sqlite3.Connection, owner: str, order_id: str, draft: dict[str, Any]
) -> str:
    subscription_id = "SUB-" + hashlib.sha256(f"{owner}:{order_id}".encode()).hexdigest()[:10].upper()
    now = _now()
    connection.execute(
        "INSERT OR IGNORE INTO bean_box_subscriptions(subscription_id,owner,order_id,status,draft_json,next_delivery_label,skip_count,created_at,updated_at) VALUES (?,?,?,?,?,?,0,?,?)",
        (subscription_id, owner, order_id, "active", json.dumps(draft, sort_keys=True), f"Every {draft['cadence']} weeks", now, now),
    )
    if connection.execute(
        "SELECT COUNT(*) FROM bean_box_subscription_events WHERE subscription_id=?",
        (subscription_id,),
    ).fetchone()[0] == 0:
        connection.execute(
            "INSERT INTO bean_box_subscription_events(subscription_id,event_type,detail_json,created_at) VALUES (?,?,?,?)",
            (subscription_id, "started", json.dumps({"order_id": order_id}), now),
        )
    return subscription_id


def subscriptions(connection: sqlite3.Connection, owner: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM bean_box_subscriptions WHERE owner=? ORDER BY created_at DESC",
        (owner,),
    ).fetchall()


def orders(connection: sqlite3.Connection, owner: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM bean_box_orders WHERE owner=? ORDER BY created_at DESC",
        (owner,),
    ).fetchall()


def update_subscription(
    connection: sqlite3.Connection,
    owner: str,
    subscription_id: str,
    action: str,
    changes: dict[str, str] | None = None,
) -> sqlite3.Row | None:
    row = connection.execute(
        "SELECT * FROM bean_box_subscriptions WHERE subscription_id=? AND owner=?",
        (subscription_id, owner),
    ).fetchone()
    if row is None:
        return None
    status = str(row["status"])
    draft = json.loads(row["draft_json"])
    event_detail: dict[str, Any] = {}
    if action == "modify":
        allowed = {
            "preparation": {"whole-bean", "freshly-ground"},
            "quantity": {"trace-six-cup", "solo-sipper", "duo", "large-solo", "office-duo"},
            "cadence": {"2", "3", "4", "5", "6"},
            "plan": {"pay-per-delivery", "annual"},
        }
        changes = changes or {}
        if not changes or any(key not in allowed or value not in allowed[key] for key, value in changes.items()):
            raise ValueError("invalid subscription change")
        draft.update(changes)
        event_detail = changes
    elif action == "pause" and status == "active":
        status = "paused"
    elif action == "skip" and status == "active":
        connection.execute(
            "UPDATE bean_box_subscriptions SET skip_count=skip_count+1 WHERE subscription_id=?",
            (subscription_id,),
        )
    elif action == "cancel" and status in {"active", "paused"}:
        status = "cancelled"
    elif action == "reactivate" and status in {"paused", "cancelled"}:
        status = "active"
    else:
        raise ValueError("invalid subscription state transition")
    now = _now()
    connection.execute(
        "UPDATE bean_box_subscriptions SET status=?,draft_json=?,next_delivery_label=?,updated_at=? WHERE subscription_id=?",
        (status, json.dumps(draft, sort_keys=True), f"Every {draft['cadence']} weeks", now, subscription_id),
    )
    connection.execute(
        "INSERT INTO bean_box_subscription_events(subscription_id,event_type,detail_json,created_at) VALUES (?,?,?,?)",
        (subscription_id, action, json.dumps(event_detail, sort_keys=True), now),
    )
    return connection.execute(
        "SELECT * FROM bean_box_subscriptions WHERE subscription_id=?", (subscription_id,)
    ).fetchone()


def reset_mutable(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM bean_box_subscription_events")
    connection.execute("DELETE FROM bean_box_subscriptions")
    connection.execute("DELETE FROM bean_box_orders")
    connection.execute("DELETE FROM bean_box_cart_items")
    connection.execute("DELETE FROM bean_box_drafts")
