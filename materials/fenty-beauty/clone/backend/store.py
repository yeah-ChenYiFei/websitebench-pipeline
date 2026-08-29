"""Site-bound product, cart, account, and order persistence for the clone."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

from backend.site_backend_integration import open_site_services


SITE_ID = "fenty-beauty"
backend, auth = open_site_services()

PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "foundation",
        "slug": "pro-filtr-soft-matte-longwear-foundation-420",
        "name": "Pro Filt'r Soft Matte Longwear Foundation",
        "short_name": "Pro Filt'r Soft Matte Foundation",
        "category": "Face Makeup",
        "price": 54.00,
        "rating": 4.4,
        "reviews": 9787,
        "image": "/static/assets/foundation.webp",
        "badge": "BESTSELLER · SOFT MATTE",
        "description": "Buildable, medium to full coverage foundation with climate-adaptive technology to fight heat, sweat + shine.",
        "details": "Longwear, shine-free, soft matte finish. Light as air, noncomedogenic, and available in 50 shades.",
        "variant_label": "Shade",
        "variants": ["100", "110", "120", "130", "140", "150", "160", "170", "175", "185N", "190", "200", "210", "220", "230", "240", "250", "260", "280", "300", "310", "330", "345", "360", "370", "385", "400", "420", "430", "440", "450", "470", "480", "490", "495", "498"],
        "sizes": ["Standard 32 mL", "Mini 12 mL"],
        "availability": "In stock while supplies last",
    },
    {
        "id": "powder",
        "slug": "invisimatte-instant-setting-blotting-powder",
        "name": "Invisimatte Instant Setting + Blotting Powder",
        "short_name": "Invisible Setting Powder",
        "category": "Prime + Set",
        "price": 53.00,
        "rating": 4.5,
        "reviews": 448,
        "image": "/static/assets/powder.webp",
        "badge": "BESTSELLER",
        "description": "A universally sheer powder to set, blur + mattify on the go.",
        "details": "Absorbs shine, extends makeup wear, has no flashback, and is refillable, talc-free, and vegan.",
        "variant_label": "Finish",
        "variants": ["Universal"],
        "sizes": ["Standard 8.5 g", "Refill 8.5 g", "Mini 4 g"],
        "availability": "In stock",
    },
    {
        "id": "gloss",
        "slug": "gloss-bomb-stix-high-shine-gloss-stick-caviar-crystalz",
        "name": "Gloss Bomb Stix High-Shine Gloss Stick",
        "short_name": "Gloss Bomb Stix",
        "category": "Lip Makeup",
        "price": 36.50,
        "rating": 4.5,
        "reviews": 1241,
        "image": "/static/assets/gloss.webp",
        "badge": "NEW",
        "description": "High-shine color and lip-loving moisture in one swipe.",
        "details": "Creamy, non-sticky gloss stick with buildable color.",
        "variant_label": "Shade",
        "variants": ["Caviar Crystalz", "Rose Amber", "Lu$t Bunny"],
        "sizes": ["Full Size"],
        "availability": "In stock",
    },
    {
        "id": "match-stix",
        "slug": "match-stix-contour-skinstick-amber",
        "name": "Match Stix Contour Skinstick",
        "short_name": "Match Stix",
        "category": "Face Makeup",
        "price": 45.00,
        "rating": 4.3,
        "reviews": 3108,
        "image": "/static/assets/match-stix.webp",
        "badge": "BESTSELLER",
        "description": "A longwear cream-to-powder contour stick with a soft matte finish.",
        "details": "Blendable, buildable, and made for precise sculpting.",
        "variant_label": "Shade",
        "variants": ["Amber", "Mocha", "Espresso"],
        "sizes": ["Full Size"],
        "availability": "In stock",
    },
    {
        "id": "starter",
        "slug": "fenty-skin-startrs-build-your-own-3-piece-skincare-bundle",
        "name": "Fenty Skin Start’rs Build Your Own 3-Piece Bundle",
        "short_name": "Fenty Skin Start’rs",
        "category": "Skincare",
        "price": 140.00,
        "rating": 4.8,
        "reviews": 202,
        "image": "/static/assets/starter.webp",
        "badge": "EXCLUSIVE",
        "description": "Build a three-piece routine for cleanse, treat, and hydrate.",
        "details": "A customizable starter set with full-size skincare essentials.",
        "variant_label": "Routine",
        "variants": ["Balanced", "Hydrating"],
        "sizes": ["3 Piece Bundle"],
        "availability": "In stock",
    },
]

PRODUCT_BY_ID = {item["id"]: item for item in PRODUCTS}
PRODUCT_BY_SLUG = {item["slug"]: item for item in PRODUCTS}

# Kept in sync with FREE_SHIPPING_OVER in static/app.js.
FREE_SHIPPING_OVER = 75.0
STANDARD_SHIPPING = 8.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS fenty_profiles (
  subject_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fenty_addresses (
  address_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  label TEXT NOT NULL,
  full_name TEXT NOT NULL,
  line1 TEXT NOT NULL,
  city TEXT NOT NULL,
  province TEXT NOT NULL,
  postal_code TEXT NOT NULL,
  country TEXT NOT NULL,
  is_default INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fenty_cart (
  actor_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  variant TEXT NOT NULL,
  size TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 5),
  removed INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(actor_id, product_id, variant, size)
);
CREATE TABLE IF NOT EXISTS fenty_favorites (
  subject_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY(subject_id, product_id)
);
CREATE TABLE IF NOT EXISTS fenty_orders (
  order_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  status TEXT NOT NULL,
  total REAL NOT NULL,
  fulfillment TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  cancelled_at INTEGER
);
CREATE TABLE IF NOT EXISTS fenty_order_lines (
  order_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  variant TEXT NOT NULL,
  size TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  price REAL NOT NULL,
  PRIMARY KEY(order_id, product_id, variant, size)
);
"""


def initialize() -> None:
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.executescript(SCHEMA)


initialize()


def new_actor() -> str:
    return f"actor_{secrets.token_urlsafe(18)}"


def ensure_auth_session(token: str | None) -> tuple[str, dict[str, Any]]:
    return auth.ensure_session(token)


def resolve_account(token: str | None) -> dict[str, Any] | None:
    return auth.resolve_session(token)


def register(email: str, display_name: str, password: str) -> dict[str, Any]:
    details = auth.validate_registration_details(email=email, display_name=display_name, password=password)
    if auth.account_exists(details["email"]):
        raise ValueError("An account already exists for this email.")
    subject = "customer_" + hashlib.sha256(details["email"].encode()).hexdigest()[:20]
    auth.seed_account(subject_id=subject, email=details["email"], display_name=details["display_name"], password=details["password"], email_verified=True)
    ensure_profile(subject, details["display_name"], details["email"])
    return {"subject_id": subject, "email": details["email"], "display_name": details["display_name"]}


def sign_in(session_token: str, email: str, password: str) -> dict[str, Any]:
    result = auth.sign_in(session_token, email=email, password=password)
    account = result["account"]
    ensure_profile(account["subject_id"], account["display_name"], account["email_normalized"])
    return result


def sign_out(session_token: str | None) -> None:
    auth.sign_out(session_token)


def ensure_profile(subject_id: str, display_name: str, email: str) -> None:
    now = int(time.time())
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO fenty_profiles(subject_id,display_name,email,created_at) VALUES(?,?,?,?)",
            (subject_id, display_name, email, now),
        )
        existing = connection.execute("SELECT 1 FROM fenty_orders WHERE subject_id=?", (subject_id,)).fetchone()
        if existing is None:
            order_id = "WB-1001"
            if connection.execute("SELECT 1 FROM fenty_orders WHERE order_id=?", (order_id,)).fetchone():
                order_id = "WB-" + hashlib.sha256(subject_id.encode()).hexdigest()[:8].upper()
            connection.execute(
                "INSERT INTO fenty_orders(order_id,subject_id,status,total,fulfillment,created_at) VALUES(?,?,?,?,?,?)",
                (order_id, subject_id, "Processing", 113.56, "Standard Shipping · 3–6 business days", now - 86400),
            )
            connection.execute(
                "INSERT INTO fenty_order_lines(order_id,product_id,variant,size,quantity,price) VALUES(?,?,?,?,?,?)",
                (order_id, "foundation", "185N", "Standard 32 mL", 1, 54.00),
            )
            connection.execute(
                "INSERT INTO fenty_order_lines(order_id,product_id,variant,size,quantity,price) VALUES(?,?,?,?,?,?)",
                (order_id, "powder", "Universal", "Standard 8.5 g", 1, 53.00),
            )


def catalog(query: str = "", category: str = "", sort: str = "featured") -> list[dict[str, Any]]:
    q = query.strip().casefold()
    rows = [p for p in PRODUCTS if (not q or q in (p["name"] + " " + p["short_name"] + " " + p["category"] + " " + p["description"]).casefold())]
    if category:
        rows = [p for p in rows if p["category"].casefold() == category.casefold()]
    if sort == "price-low":
        rows.sort(key=lambda p: p["price"])
    elif sort == "price-high":
        rows.sort(key=lambda p: -p["price"])
    elif sort == "rating":
        rows.sort(key=lambda p: (-p["rating"], -p["reviews"]))
    return rows


def cart(actor_id: str, include_removed: bool = False) -> dict[str, Any]:
    condition = "" if include_removed else " AND removed=0"
    with backend.lifecycle.connection() as connection:
        rows = connection.execute("SELECT * FROM fenty_cart WHERE actor_id=?" + condition + " ORDER BY updated_at", (actor_id,)).fetchall()
    items = []
    for row in rows:
        product = PRODUCT_BY_ID.get(str(row["product_id"]))
        if product:
            items.append({"product": product, "variant": row["variant"], "size": row["size"], "quantity": int(row["quantity"]), "removed": bool(row["removed"]), "line_total": round(product["price"] * int(row["quantity"]), 2)})
    subtotal = round(sum(item["line_total"] for item in items if not item["removed"]), 2)
    return {
        "items": items,
        "count": sum(item["quantity"] for item in items if not item["removed"]),
        "subtotal": subtotal,
        "shipping": 0.0 if subtotal >= FREE_SHIPPING_OVER else (STANDARD_SHIPPING if subtotal else 0.0),
        "free_shipping_over": FREE_SHIPPING_OVER,
        "currency": "CAD",
    }


def add_cart(actor_id: str, product_id: str, variant: str, size: str, quantity: int = 1) -> dict[str, Any]:
    product = PRODUCT_BY_ID.get(product_id)
    if product is None:
        raise ValueError("Product was not found.")
    if variant not in product["variants"]:
        raise ValueError(f"Choose an available {product['variant_label'].lower()}.")
    if size not in product["sizes"]:
        raise ValueError("Choose an available size.")
    quantity = max(1, min(5, int(quantity)))
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "INSERT INTO fenty_cart(actor_id,product_id,variant,size,quantity,removed,updated_at) VALUES(?,?,?,?,?,0,?) ON CONFLICT(actor_id,product_id,variant,size) DO UPDATE SET quantity=MIN(5,fenty_cart.quantity+excluded.quantity),removed=0,updated_at=excluded.updated_at",
            (actor_id, product_id, variant, size, quantity, int(time.time())),
        )
    return cart(actor_id)


def update_cart(actor_id: str, product_id: str, variant: str, size: str, quantity: int | None = None, removed: bool | None = None) -> dict[str, Any]:
    with backend.lifecycle.connection(transaction=True) as connection:
        if quantity is not None:
            connection.execute("UPDATE fenty_cart SET quantity=?,removed=0,updated_at=? WHERE actor_id=? AND product_id=? AND variant=? AND size=?", (max(1, min(5, int(quantity))), int(time.time()), actor_id, product_id, variant, size))
        if removed is not None:
            connection.execute("UPDATE fenty_cart SET removed=?,updated_at=? WHERE actor_id=? AND product_id=? AND variant=? AND size=?", (1 if removed else 0, int(time.time()), actor_id, product_id, variant, size))
    return cart(actor_id, include_removed=True)


def favorites(subject_id: str) -> list[dict[str, Any]]:
    with backend.lifecycle.connection() as connection:
        ids = [str(row[0]) for row in connection.execute("SELECT product_id FROM fenty_favorites WHERE subject_id=? ORDER BY created_at DESC", (subject_id,))]
    return [PRODUCT_BY_ID[item] for item in ids if item in PRODUCT_BY_ID]


def toggle_favorite(subject_id: str, product_id: str) -> tuple[bool, list[dict[str, Any]]]:
    if product_id not in PRODUCT_BY_ID:
        raise ValueError("Product was not found.")
    with backend.lifecycle.connection(transaction=True) as connection:
        row = connection.execute("SELECT 1 FROM fenty_favorites WHERE subject_id=? AND product_id=?", (subject_id, product_id)).fetchone()
        if row:
            connection.execute("DELETE FROM fenty_favorites WHERE subject_id=? AND product_id=?", (subject_id, product_id))
            active = False
        else:
            connection.execute("INSERT INTO fenty_favorites(subject_id,product_id,created_at) VALUES(?,?,?)", (subject_id, product_id, int(time.time())))
            active = True
    return active, favorites(subject_id)


def save_address(subject_id: str, value: dict[str, str]) -> dict[str, Any]:
    required = ("full_name", "line1", "city", "province", "postal_code", "country")
    missing = [field for field in required if not str(value.get(field, "")).strip()]
    if missing:
        raise ValueError("Complete all required address fields: " + ", ".join(missing))
    address_id = str(value.get("address_id") or f"addr_{secrets.token_urlsafe(10)}")
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute("UPDATE fenty_addresses SET is_default=0 WHERE subject_id=?", (subject_id,))
        connection.execute(
            "INSERT INTO fenty_addresses(address_id,subject_id,label,full_name,line1,city,province,postal_code,country,is_default) VALUES(?,?,?,?,?,?,?,?,?,1) ON CONFLICT(address_id) DO UPDATE SET label=excluded.label,full_name=excluded.full_name,line1=excluded.line1,city=excluded.city,province=excluded.province,postal_code=excluded.postal_code,country=excluded.country,is_default=1",
            (address_id, subject_id, str(value.get("label") or "Home")[:40], str(value["full_name"])[:120], str(value["line1"])[:180], str(value["city"])[:80], str(value["province"])[:80], str(value["postal_code"])[:20], str(value["country"])[:80]),
        )
    return account_data(subject_id)


def account_data(subject_id: str) -> dict[str, Any]:
    with backend.lifecycle.connection() as connection:
        profile = connection.execute("SELECT * FROM fenty_profiles WHERE subject_id=?", (subject_id,)).fetchone()
        addresses = [dict(row) for row in connection.execute("SELECT * FROM fenty_addresses WHERE subject_id=? ORDER BY is_default DESC", (subject_id,))]
    return {"profile": dict(profile) if profile else None, "addresses": addresses, "favorites": favorites(subject_id), "orders": orders(subject_id)}


def orders(subject_id: str) -> list[dict[str, Any]]:
    with backend.lifecycle.connection() as connection:
        rows = connection.execute("SELECT * FROM fenty_orders WHERE subject_id=? ORDER BY created_at DESC", (subject_id,)).fetchall()
        result = []
        for row in rows:
            lines = []
            for line in connection.execute("SELECT * FROM fenty_order_lines WHERE order_id=?", (row["order_id"],)):
                item = dict(line)
                item["product"] = PRODUCT_BY_ID.get(str(line["product_id"]))
                lines.append(item)
            item = dict(row)
            item["lines"] = lines
            result.append(item)
    return result


def order_action(subject_id: str, order_id: str, action: str, actor_id: str) -> dict[str, Any]:
    with backend.lifecycle.connection(transaction=True) as connection:
        order = connection.execute("SELECT * FROM fenty_orders WHERE order_id=? AND subject_id=?", (order_id, subject_id)).fetchone()
        if order is None:
            raise ValueError("Order was not found.")
        if action == "cancel":
            if order["status"] not in {"Processing", "Confirmed"}:
                raise ValueError("This order can no longer be cancelled.")
            connection.execute("UPDATE fenty_orders SET status='Cancelled',cancelled_at=? WHERE order_id=?", (int(time.time()), order_id))
        elif action == "return":
            connection.execute("UPDATE fenty_orders SET status='Return requested' WHERE order_id=?", (order_id,))
        elif action == "reorder":
            for line in connection.execute("SELECT * FROM fenty_order_lines WHERE order_id=?", (order_id,)).fetchall():
                connection.execute("INSERT INTO fenty_cart(actor_id,product_id,variant,size,quantity,removed,updated_at) VALUES(?,?,?,?,?,0,?) ON CONFLICT(actor_id,product_id,variant,size) DO UPDATE SET quantity=MIN(5,fenty_cart.quantity+excluded.quantity),removed=0,updated_at=excluded.updated_at", (actor_id, line["product_id"], line["variant"], line["size"], line["quantity"], int(time.time())))
        else:
            raise ValueError("Unknown order action.")
    return {"orders": orders(subject_id), "cart": cart(actor_id)}


def checkout_preview(actor_id: str, promo: str = "") -> dict[str, Any]:
    value = cart(actor_id)
    if not value["items"]:
        raise ValueError("Your bag is empty.")
    discount = round(value["subtotal"] * 0.10, 2) if promo.strip().upper() == "FENTY10" else 0.0
    tax = round((value["subtotal"] - discount + value["shipping"]) * 0.13, 2)
    total = round(value["subtotal"] - discount + value["shipping"] + tax, 2)
    return {**value, "promo": promo.strip().upper(), "discount": discount, "tax": tax, "total": total, "fulfillment_options": ["Standard Shipping · 3–6 business days", "Express Shipping · 1–2 business days"], "payment_adapter": "local-sandbox", "is_simulation": True}


def reset() -> None:
    def site_reset(connection):
        for table in ("fenty_order_lines", "fenty_orders", "fenty_addresses", "fenty_favorites", "fenty_cart", "fenty_profiles"):
            connection.execute(f"DELETE FROM {table}")
    auth.reset_site_state(site_reset=site_reset, seed_accounts=[])


def public_product(product: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(product))
