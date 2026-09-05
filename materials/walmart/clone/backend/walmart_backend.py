"""Site-specific Walmart catalog and anonymous-cart migrations and seeds."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


PRODUCTS = (
    {
        "id": "dawn-18",
        "slug": "dawn-ultra-original-18oz",
        "name": "Dawn Ultra Liquid Dish Soap, Original Scent, 18 fl oz",
        "brand": "Dawn",
        "category": "Household Essentials",
        "price_cents": 318,
        "was_cents": None,
        "rating": 4.7,
        "reviews": 12846,
        "image": "dawn-original-18oz.jpg",
        "fulfillment": "Pickup today|Shipping tomorrow",
        "badges": "Best seller",
        "description": "Tough on grease and gentle enough for everyday dishes. The concentrated formula helps clean more dishes with less liquid.",
        "options": (("original-18", "Original, 18 fl oz", 0), ("fresh-rain-18", "Fresh Rain, 18 fl oz", 20), ("apple-18", "Apple Blossom, 18 fl oz", 20)),
    },
    {
        "id": "gain-24",
        "slug": "gain-honeyberry-hula-24oz",
        "name": "Gain EZ-Squeeze Dish Soap, Honeyberry Hula, 24.3 fl oz",
        "brand": "Gain",
        "category": "Household Essentials",
        "price_cents": 318,
        "was_cents": 398,
        "rating": 4.8,
        "reviews": 3221,
        "image": "gain-honeyberry-24oz.jpg",
        "fulfillment": "Pickup today|Shipping tomorrow",
        "badges": "Rollback",
        "description": "A bright fruity scent in an easy-squeeze bottle with dependable grease-cutting cleaning power.",
        "options": (("honeyberry-24", "Honeyberry Hula, 24.3 fl oz", 0), ("original-24", "Original, 24.3 fl oz", 0), ("waterfall-24", "Waterfall Delight, 24.3 fl oz", 0)),
    },
    {
        "id": "dawn-5",
        "slug": "dawn-ultra-original-5oz",
        "name": "Dawn Ultra Liquid Dish Soap, Original Scent, 5.8 fl oz",
        "brand": "Dawn",
        "category": "Household Essentials",
        "price_cents": 106,
        "was_cents": None,
        "rating": 4.6,
        "reviews": 912,
        "image": "dawn-original-5oz.jpg",
        "fulfillment": "Pickup today|Shipping tomorrow",
        "badges": "Popular pick",
        "description": "A compact bottle of concentrated Dawn dishwashing liquid for small kitchens, travel, and everyday cleanup.",
        "options": (("original-5", "Original, 5.8 fl oz", 0),),
    },
    {
        "id": "ajax-orange",
        "slug": "ajax-ultra-orange-28oz",
        "name": "Ajax Ultra Triple Action Dish Soap, Orange, 28 fl oz",
        "brand": "Ajax",
        "category": "Household Essentials",
        "price_cents": 274,
        "was_cents": None,
        "rating": 4.5,
        "reviews": 1478,
        "image": "ajax-orange-28oz.jpg",
        "fulfillment": "Pickup today",
        "badges": "",
        "description": "Triple-action dish soap with an orange scent for washing away stuck-on food and grease.",
        "options": (("orange-28", "Orange, 28 fl oz", 0), ("lemon-28", "Lemon, 28 fl oz", 0)),
    },
    {
        "id": "ajax-lemon",
        "slug": "ajax-ultra-lemon-28oz",
        "name": "Ajax Ultra Super Degreaser Dish Soap, Lemon, 28 fl oz",
        "brand": "Ajax",
        "category": "Household Essentials",
        "price_cents": 274,
        "was_cents": None,
        "rating": 4.5,
        "reviews": 1033,
        "image": "ajax-lemon-28oz.jpg",
        "fulfillment": "Shipping tomorrow",
        "badges": "",
        "description": "A lemon-scented liquid dish soap designed to cut through everyday grease.",
        "options": (("lemon-28", "Lemon, 28 fl oz", 0), ("orange-28", "Orange, 28 fl oz", 0)),
    },
    {
        "id": "degree-cool",
        "slug": "degree-men-cool-rush-2oz",
        "name": "Degree Advanced Men Antiperspirant, Cool Rush, 2.7 oz",
        "brand": "Degree",
        "category": "Personal Care",
        "price_cents": 497,
        "was_cents": 548,
        "rating": 4.6,
        "reviews": 2840,
        "image": "degree-cool-rush.jpg",
        "fulfillment": "Pickup tomorrow|Shipping tomorrow",
        "badges": "Rollback",
        "description": "Motion-activated antiperspirant protection with a fresh Cool Rush scent.",
        "options": (("single", "Single, 2.7 oz", 0), ("two-pack", "2 pack", 452)),
    },
)


# Keep the original product IDs so existing anonymous carts remain valid.
PRODUCTS += tuple(json.loads((Path(__file__).parents[1] / 'data/catalog.json').read_text(encoding='utf-8')))


DETAIL_DATA = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'product-details.json').read_text(encoding='utf-8'))
for product in PRODUCTS:
    extra = DETAIL_DATA.get(product['id'], {})
    if extra.get('brand'):
        product['brand'] = extra['brand']
    options = list(product['options'])
    for variant_id, variant in extra.get('variants', {}).items():
        if variant['available']:
            options.append((variant_id, variant['label'], variant['price'] - product['price_cents']))
    product['options'] = tuple(options)


def migrate(connection: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS wb_walmart_products (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            brand TEXT NOT NULL,
            category TEXT NOT NULL,
            price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
            was_cents INTEGER,
            rating REAL NOT NULL,
            review_count INTEGER NOT NULL,
            image TEXT NOT NULL,
            fulfillment TEXT NOT NULL,
            badges TEXT NOT NULL,
            description TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS wb_walmart_product_options (
            product_id TEXT NOT NULL REFERENCES wb_walmart_products(id),
            option_id TEXT NOT NULL,
            label TEXT NOT NULL,
            price_delta_cents INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (product_id, option_id)
        )""",
        """CREATE TABLE IF NOT EXISTS wb_walmart_carts (
            cart_id TEXT NOT NULL,
            product_id TEXT NOT NULL REFERENCES wb_walmart_products(id),
            option_id TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (cart_id, product_id, option_id)
        )""",
        """CREATE INDEX IF NOT EXISTS wb_walmart_cart_owner
          ON wb_walmart_carts(cart_id, updated_at)""",
        """CREATE TABLE IF NOT EXISTS wb_walmart_orders (
            order_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            zip_code TEXT NOT NULL,
            subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
            tax_cents INTEGER NOT NULL CHECK(tax_cents >= 0),
            total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
            status TEXT NOT NULL DEFAULT 'Placed',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE INDEX IF NOT EXISTS wb_walmart_order_account
          ON wb_walmart_orders(account_id, created_at DESC)""",
        """CREATE TABLE IF NOT EXISTS wb_walmart_order_items (
            order_id TEXT NOT NULL REFERENCES wb_walmart_orders(order_id) ON DELETE CASCADE,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            option_label TEXT NOT NULL,
            image TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20),
            unit_cents INTEGER NOT NULL CHECK(unit_cents >= 0),
            PRIMARY KEY (order_id, product_id, option_label)
        )""",
    )
    for statement in statements:
        connection.execute(statement)


def seed(connection: sqlite3.Connection) -> None:
    for product in PRODUCTS:
        connection.execute(
            """
            INSERT INTO wb_walmart_products
              (id, slug, name, brand, category, price_cents, was_cents,
               rating, review_count, image, fulfillment, badges, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              slug=excluded.slug, name=excluded.name, brand=excluded.brand,
              category=excluded.category, price_cents=excluded.price_cents,
              was_cents=excluded.was_cents, rating=excluded.rating,
              review_count=excluded.review_count, image=excluded.image,
              fulfillment=excluded.fulfillment, badges=excluded.badges,
              description=excluded.description
            """,
            (
                product["id"], product["slug"], product["name"], product["brand"],
                product["category"], product["price_cents"], product["was_cents"],
                product["rating"], product["reviews"], product["image"],
                product["fulfillment"], product["badges"], product["description"],
            ),
        )
        for option_id, label, delta in product["options"]:
            connection.execute(
                """
                INSERT INTO wb_walmart_product_options
                  (product_id, option_id, label, price_delta_cents)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(product_id, option_id) DO UPDATE SET
                  label=excluded.label, price_delta_cents=excluded.price_delta_cents
                """,
                (product["id"], option_id, label, delta),
            )


def catalog_json() -> str:
    """Stable catalog projection used by deterministic reset tests."""

    return json.dumps(PRODUCTS, sort_keys=True, separators=(",", ":"))


def migrate_storefront_v2(connection: sqlite3.Connection) -> None:
    """Upgrade an existing six-item database without clearing anonymous carts."""
    migrate(connection)
    seed(connection)


def migrate_details_v4(connection: sqlite3.Connection) -> None:
    """Add captured variants while preserving existing carts and option IDs."""
    migrate(connection)
    seed(connection)


def migrate_accounts_v5(connection: sqlite3.Connection) -> None:
    """Add local order storage while preserving the catalog and carts."""
    migrate(connection)
    seed(connection)
