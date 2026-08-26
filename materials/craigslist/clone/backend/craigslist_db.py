"""Craigslist offline clone — business database.

Layout mirrors the aspca golden-sample shape:

* The vendored ``websitebench.site_backend`` runtime owns identity, sessions,
  mail outbox and the bound SQLite file (``backend/runtime.json``).
* This module owns the site's business schema: regions, categories,
  postings, posting photos, favorites, saved searches, reply messages,
  flags, wizard drafts and registration rate-limit events. Business
  migrations are versioned and idempotent; the deterministic seed is
  byte-stable so evaluation can always reset to the same initial state.
* All business timestamps use the frozen clock (``FROZEN_CLOCK_UTC``)
  unless ``WEBSITEBENCH_CRAIGSLIST_CLOCK`` overrides it, so 'posted today'
  filters and the five-minute registration rule are testable.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.site_backend_integration import open_site_services
from websitebench.local_clone_auth import LocalAuthStore
from websitebench.site_backend import SiteBackend

SITE_ID = "craigslist"
FROZEN_CLOCK_UTC = "2026-06-20T12:00:00Z"

# The same email may register at most once per this window (requirement:
# "same user can only register once every five minutes"). The window is
# controllable via WEBSITEBENCH_CRAIGSLIST_REGISTRATION_WINDOW_SECONDS so
# tests do not wait five real minutes.
DEFAULT_REGISTRATION_WINDOW_SECONDS = 5 * 60

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _load_real_postings() -> dict[str, list[dict[str, Any]]]:
    """Load the scraped snapshot of real craigslist toronto postings
    (title/price/location per category). Falls back to {} if missing so the
    clone still seeds with the synthetic catalog."""
    path = Path(__file__).resolve().parent / "real_postings.json"
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


REAL_POSTINGS = _load_real_postings()


def _load_real_posting_details() -> dict[str, dict[str, Any]]:
    """Load sanitized, source-observed detail-page fields.

    The search snapshot intentionally stays compact.  Detail observations live
    in a separate file so a known posting can carry its body copy, timestamps,
    and localized media without turning the search catalog into a second copy
    of every detail page.
    """

    path = Path(__file__).resolve().parent / "real_posting_details.json"
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


REAL_POSTING_DETAILS = _load_real_posting_details()


def now_utc() -> str:
    """Frozen business clock; tests override via environment."""
    override = os.environ.get("WEBSITEBENCH_CRAIGSLIST_CLOCK")
    if override:
        return datetime.fromisoformat(override).astimezone(timezone.utc).isoformat()
    return FROZEN_CLOCK_UTC


def now_datetime() -> datetime:
    return datetime.fromisoformat(now_utc())


def registration_window_seconds() -> int:
    raw = os.environ.get("WEBSITEBENCH_CRAIGSLIST_REGISTRATION_WINDOW_SECONDS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_REGISTRATION_WINDOW_SECONDS


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

_MIGRATIONS: dict[str, str] = {
    "0001_regions_categories": """
        CREATE TABLE cl_regions (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            country TEXT NOT NULL
        );
        CREATE TABLE cl_categories (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            section TEXT NOT NULL,
            parent TEXT
        );
    """,
    "0002_postings": """
        CREATE TABLE cl_postings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region_id INTEGER NOT NULL REFERENCES cl_regions(id),
            category_slug TEXT NOT NULL,
            title TEXT NOT NULL,
            price INTEGER,
            description TEXT NOT NULL DEFAULT '',
            postal_code TEXT,
            neighborhood TEXT,
            housing_type TEXT,
            bedrooms TEXT,
            baths TEXT,
            square_feet TEXT,
            available_date TEXT,
            furnished INTEGER NOT NULL DEFAULT 0,
            laundry TEXT,
            parking TEXT,
            ac TEXT,
            posted_by TEXT NOT NULL DEFAULT 'owner',
            contact_email TEXT NOT NULL DEFAULT '',
            contact_phone TEXT,
            contact_method TEXT NOT NULL DEFAULT 'email',
            status TEXT NOT NULL DEFAULT 'published',
            account_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            renewed_at TEXT,
            removed_at TEXT,
            slug TEXT NOT NULL
        );
        CREATE INDEX idx_cl_postings_region_cat ON cl_postings(region_id, category_slug, status);
        CREATE INDEX idx_cl_postings_title ON cl_postings(title);
        CREATE INDEX idx_cl_postings_price ON cl_postings(price);
    """,
    "0003_photos": """
        CREATE TABLE cl_posting_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_cl_photos_posting ON cl_posting_photos(posting_id);
    """,
    "0004_favorites": """
        CREATE TABLE cl_favorites (
            account_id TEXT NOT NULL,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (account_id, posting_id)
        );
    """,
    "0005_saved_searches": """
        CREATE TABLE cl_saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            query_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_cl_saved_account ON cl_saved_searches(account_id);
    """,
    "0006_replies_flags": """
        CREATE TABLE cl_reply_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            mail_id TEXT
        );
        CREATE TABLE cl_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        );
    """,
    "0007_wizard_drafts": """
        CREATE TABLE cl_posting_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_digest TEXT NOT NULL,
            step INTEGER NOT NULL DEFAULT 1,
            region_id INTEGER,
            category_slug TEXT,
            title TEXT,
            price INTEGER,
            description TEXT,
            postal_code TEXT,
            neighborhood TEXT,
            housing_type TEXT,
            bedrooms TEXT,
            baths TEXT,
            square_feet TEXT,
            available_date TEXT,
            furnished INTEGER DEFAULT 0,
            laundry TEXT,
            parking TEXT,
            ac TEXT,
            posted_by TEXT DEFAULT 'owner',
            contact_email TEXT,
            contact_phone TEXT,
            contact_method TEXT DEFAULT 'email',
            updated_at TEXT NOT NULL,
            UNIQUE(session_digest)
        );
        CREATE TABLE cl_draft_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL REFERENCES cl_posting_drafts(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_cl_draft_photos ON cl_draft_photos(draft_id);
    """,
    "0008_registration_events": """
        CREATE TABLE cl_registration_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_normalized TEXT NOT NULL,
            attempted_at TEXT NOT NULL
        );
        CREATE INDEX idx_cl_reg_events_email ON cl_registration_events(email_normalized);
    """,
    "0009_reply_outbox_recipient": """
        ALTER TABLE cl_reply_messages ADD COLUMN recipient TEXT;
    """,
    "0010_neighborhoods": """
        CREATE TABLE cl_neighborhoods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            postal_prefixes TEXT NOT NULL
        );
    """,
    "0011_price_nullable": """
        -- Rebuild cl_postings with a nullable price so postings without a
        -- price on the real site (jobs/community/gigs) are stored as NULL
        -- instead of a fake $0. SQLite rewrites foreign keys pointing at the
        -- renamed table, so the referencing tables are rebuilt afterwards.
        ALTER TABLE cl_postings RENAME TO cl_postings_old;
        CREATE TABLE cl_postings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region_id INTEGER NOT NULL REFERENCES cl_regions(id),
            category_slug TEXT NOT NULL,
            title TEXT NOT NULL,
            price INTEGER,
            description TEXT NOT NULL DEFAULT '',
            postal_code TEXT,
            neighborhood TEXT,
            housing_type TEXT,
            bedrooms TEXT,
            baths TEXT,
            square_feet TEXT,
            available_date TEXT,
            furnished INTEGER NOT NULL DEFAULT 0,
            laundry TEXT,
            parking TEXT,
            ac TEXT,
            posted_by TEXT NOT NULL DEFAULT 'owner',
            contact_email TEXT NOT NULL DEFAULT '',
            contact_phone TEXT,
            contact_method TEXT NOT NULL DEFAULT 'email',
            status TEXT NOT NULL DEFAULT 'published',
            account_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            renewed_at TEXT,
            removed_at TEXT,
            slug TEXT NOT NULL
        );
        INSERT INTO cl_postings (
            id, region_id, category_slug, title, price, description, postal_code,
            neighborhood, housing_type, bedrooms, baths, square_feet, available_date,
            furnished, laundry, parking, ac, posted_by, contact_email, contact_phone,
            contact_method, status, account_id, created_at, updated_at, renewed_at,
            removed_at, slug
        ) SELECT
            id, region_id, category_slug, title, price, description, postal_code,
            neighborhood, housing_type, bedrooms, baths, square_feet, available_date,
            furnished, laundry, parking, ac, posted_by, contact_email, contact_phone,
            contact_method, status, account_id, created_at, updated_at, renewed_at,
            removed_at, slug
        FROM cl_postings_old;
        DROP TABLE cl_postings_old;
        CREATE INDEX idx_cl_postings_region_cat ON cl_postings(region_id, category_slug, status);
        CREATE INDEX idx_cl_postings_title ON cl_postings(title);
        CREATE INDEX idx_cl_postings_price ON cl_postings(price);
        ALTER TABLE cl_posting_photos RENAME TO cl_posting_photos_old;
        CREATE TABLE cl_posting_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO cl_posting_photos (id, posting_id, filename, position)
            SELECT id, posting_id, filename, position FROM cl_posting_photos_old;
        DROP TABLE cl_posting_photos_old;
        CREATE INDEX idx_cl_photos_posting ON cl_posting_photos(posting_id);
        ALTER TABLE cl_favorites RENAME TO cl_favorites_old;
        CREATE TABLE cl_favorites (
            account_id TEXT NOT NULL,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (account_id, posting_id)
        );
        INSERT INTO cl_favorites (account_id, posting_id, created_at)
            SELECT account_id, posting_id, created_at FROM cl_favorites_old;
        DROP TABLE cl_favorites_old;
        ALTER TABLE cl_reply_messages RENAME TO cl_reply_messages_old;
        CREATE TABLE cl_reply_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            mail_id TEXT,
            recipient TEXT
        );
        INSERT INTO cl_reply_messages (
            id, posting_id, name, email, phone, message, created_at, mail_id, recipient
        ) SELECT
            id, posting_id, name, email, phone, message, created_at, mail_id, recipient
        FROM cl_reply_messages_old;
        DROP TABLE cl_reply_messages_old;
        ALTER TABLE cl_flags RENAME TO cl_flags_old;
        CREATE TABLE cl_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posting_id INTEGER NOT NULL REFERENCES cl_postings(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        );
        INSERT INTO cl_flags (id, posting_id, reason, note, created_at)
            SELECT id, posting_id, reason, note, created_at FROM cl_flags_old;
        DROP TABLE cl_flags_old;
    """,
    "0012_forums": """
        CREATE TABLE cl_forum_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            forum_id TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            thread_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE cl_forum_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL REFERENCES cl_forum_boards(id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            posted_at TEXT NOT NULL,
            parent_thread TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX idx_cl_forum_posts_board ON cl_forum_posts(board_id);
    """,
}


def _ensure_business_schema(path: Path) -> None:
    with closing(_connect(path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS craigslist_schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            row["migration_id"]
            for row in connection.execute(
                "SELECT migration_id FROM craigslist_schema_migrations"
            )
        }
        for migration_id, ddl in _MIGRATIONS.items():
            if migration_id in applied:
                continue
            connection.executescript(ddl)
            connection.execute(
                "INSERT INTO craigslist_schema_migrations (migration_id, applied_at)"
                " VALUES (?, ?)",
                (migration_id, FROZEN_CLOCK_UTC),
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


def connect() -> sqlite3.Connection:
    return _connect(database_path())


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


# ---------------------------------------------------------------------------
# seed data
# ---------------------------------------------------------------------------

SEED_REGIONS: list[tuple[str, str, str]] = [
    ("toronto", "toronto", "Canada"),
    ("vancouver", "vancouver", "Canada"),
    ("montreal", "montreal", "Canada"),
    ("newyork", "new york city", "USA"),
    ("losangeles", "los angeles", "USA"),
    ("chicago", "chicago", "USA"),
    ("seattle", "seattle", "USA"),
    ("london", "london", "UK"),
    ("sydney", "sydney", "Australia"),
]

# Category labels and codes follow the live site (captured 2026-08-21).
SEED_CATEGORIES: list[tuple[str, str, str, str | None]] = [
    ("apa", "apts / housing", "housing", None),
    ("swp", "housing swap", "housing", None),
    ("hsw", "housing wanted", "housing", None),
    ("off", "office / commercial", "housing", None),
    ("prk", "parking / storage", "housing", None),
    ("rea", "real estate for sale", "housing", None),
    ("roo", "rooms / shared", "housing", None),
    ("sha", "rooms wanted", "housing", None),
    ("sub", "sublets / temporary", "housing", None),
    ("vac", "vacation rentals", "housing", None),
    ("hhh", "housing", "housing", None),
    ("bia", "bikes", "for-sale", None),
    ("fua", "furniture", "for-sale", None),
    ("ela", "electronics", "for-sale", None),
    ("tia", "tickets", "for-sale", None),
    ("foa", "general", "for-sale", None),
    ("cta", "cars + trucks", "autos", None),
    ("mca", "motorcycles", "autos", None),
    ("sna", "atv/utv/sno", "autos", None),
    ("rva", "rvs + camp", "autos", None),
    ("boo", "boats", "autos", None),
    ("pta", "auto parts", "autos", None),
    ("tra", "trailers", "autos", None),
    ("wta", "wheels + tires", "autos", None),
    ("ava", "aviation", "autos", None),
    ("sof", "software / qa / dba", "jobs", None),
    ("web", "web / info design", "jobs", None),
    ("cpg", "computer gigs", "gigs", None),
    ("crg", "creative gigs", "gigs", None),
    ("lbg", "labor gigs", "gigs", None),
    ("act", "activities", "community", None),
    ("ats", "artists", "community", None),
    ("kid", "childcare", "community", None),
    ("cls", "classes", "community", None),
    ("eve", "events", "community", None),
    ("com", "general", "community", None),
    ("grp", "groups", "community", None),
    ("vnn", "local news", "community", None),
    ("laf", "lost + found", "community", None),
    ("mis", "missed connections", "community", None),
    ("muc", "musicians", "community", None),
    ("pet", "pets", "community", None),
    ("pol", "politics", "community", None),
    ("rnr", "rants & raves", "community", None),
    ("rid", "rideshare", "community", None),
    ("vol", "volunteers", "community", None),
    ("aos", "automotive", "services", None),
    ("bts", "beauty", "services", None),
    ("cms", "cell / mobile", "services", None),
    ("cps", "computer", "services", None),
    ("crs", "creative", "services", None),
    ("cys", "cycle", "services", None),
    ("evs", "event", "services", None),
    ("fgs", "farm + garden", "services", None),
    ("fns", "financial", "services", None),
    ("hws", "health / well", "services", None),
    ("hss", "household", "services", None),
    ("lbs", "labor / move", "services", None),
    ("lgs", "legal", "services", None),
    ("lss", "lessons", "services", None),
    ("mas", "marine", "services", None),
    ("pas", "pet", "services", None),
    ("rts", "real estate", "services", None),
    ("sks", "skilled trade", "services", None),
    ("biz", "sm biz ads", "services", None),
    ("trv", "travel / vac", "services", None),
    ("wet", "write / ed / tran", "services", None),
    ("ata", "antiques", "for-sale", None),
    ("ppa", "appliances", "for-sale", None),
    ("ara", "arts + crafts", "for-sale", None),
    ("baa", "baby + kid", "for-sale", None),
    ("bar", "barter", "for-sale", None),
    ("haa", "beauty + hlth", "for-sale", None),
    ("bip", "bike parts", "for-sale", None),
    ("bka", "books", "for-sale", None),
    ("bfa", "business", "for-sale", None),
    ("ema", "cds / dvd / vhs", "for-sale", None),
    ("moa", "cell phones", "for-sale", None),
    ("cla", "clothes + acc", "for-sale", None),
    ("cba", "collectibles", "for-sale", None),
    ("syp", "computer parts", "for-sale", None),
    ("sya", "computers", "for-sale", None),
    ("gra", "farm + garden", "for-sale", None),
    ("zip", "free", "for-sale", None),
    ("gms", "garage sale", "for-sale", None),
    ("hsa", "household", "for-sale", None),
    ("jwa", "jewelry", "for-sale", None),
    ("maa", "materials", "for-sale", None),
    ("mpa", "motorcycle parts", "for-sale", None),
    ("msa", "music instr", "for-sale", None),
    ("pha", "photo + video", "for-sale", None),
    ("sga", "sporting", "for-sale", None),
    ("tla", "tools", "for-sale", None),
    ("taa", "toys + games", "for-sale", None),
    ("vga", "video gaming", "for-sale", None),
    ("waa", "wanted", "for-sale", None),
    ("acc", "accounting + finance", "jobs", None),
    ("ofc", "admin / office", "jobs", None),
    ("egr", "arch / engineering", "jobs", None),
    ("med", "art / media / design", "jobs", None),
    ("bus", "business / mgmt", "jobs", None),
    ("csr", "customer service", "jobs", None),
    ("edu", "education", "jobs", None),
    ("etc", "etc / misc", "jobs", None),
    ("fbh", "food / bev / hosp", "jobs", None),
    ("lab", "general labor", "jobs", None),
    ("gov", "government", "jobs", None),
    ("hum", "human resources", "jobs", None),
    ("lgl", "legal / paralegal", "jobs", None),
    ("mnu", "manufacturing", "jobs", None),
    ("mar", "marketing / pr / ad", "jobs", None),
    ("hea", "medical / health", "jobs", None),
    ("npo", "nonprofit sector", "jobs", None),
    ("rej", "real estate", "jobs", None),
    ("ret", "retail / wholesale", "jobs", None),
    ("sls", "sales / biz dev", "jobs", None),
    ("spa", "salon / spa / fitness", "jobs", None),
    ("sec", "security", "jobs", None),
    ("trd", "skilled trade / craft", "jobs", None),
    ("sad", "systems / network", "jobs", None),
    ("tch", "technical support", "jobs", None),
    ("trp", "transport", "jobs", None),
    ("tfr", "tv / film / video", "jobs", None),
    ("wri", "writing / editing", "jobs", None),
    ("cwg", "crew", "gigs", None),
    ("dmg", "domestic", "gigs", None),
    ("evg", "event", "gigs", None),
    ("tlg", "talent", "gigs", None),
    ("wrg", "writing", "gigs", None),
    ("rrr", "resumes", "resumes", None),
]

# neighborhood slug -> (name, postal prefixes)
TORONTO_NEIGHBORHOODS: dict[str, tuple[str, list[str]]] = {
    "annex": ("The Annex", ["M6G", "M5R", "M6H"]),
    "kensington": ("Kensington Market", ["M5T", "M5V"]),
    "yorkville": ("Yorkville", ["M4W", "M5R"]),
    "leslieville": ("Leslieville", ["M4L", "M4M"]),
    "corktown": ("Corktown", ["M5A"]),
    "st-lawrence": ("St. Lawrence Market", ["M5E", "M5C"]),
    "liberty": ("Liberty Village", ["M6K"]),
    "parkdale": ("Parkdale", ["M6K", "M6P"]),
    "roncesvalles": ("Roncesvalles", ["M6R"]),
    "beaches": ("The Beaches", ["M4E"]),
    "north-york": ("North York", ["M2N", "M2P"]),
    "etobicoke": ("Etobicoke", ["M9V", "M8V"]),
    "scarborough": ("Scarborough", ["M1P", "M1B"]),
    "east-york": ("East York", ["M4C", "M4B"]),
    "cityplace": ("CityPlace", ["M5V"]),
    "crosstown": ("Davisville", ["M4S", "M4P"]),
}


# Seed photo assets per neighborhood (files shipped under
# static/assets/seed-photos). Housing postings inherit these so search,
# category and detail pages show photos like the real site.
SEED_PHOTO_ASSETS: dict[str, list[str]] = {
    "annex": ["apt-annex-1.svg", "apt-annex-2.svg", "apt-annex-3.svg", "room-annex-1.svg"],
    "beaches": ["apt-beaches-1.svg"],
    "cityplace": ["apt-cityplace-1.svg", "apt-cityplace-2.svg"],
    "corktown": ["apt-corktown-1.svg", "apt-corktown-2.svg"],
    "kensington": ["apt-kensington-1.svg", "room-kensington-1.svg"],
    "leslieville": ["apt-leslieville-1.svg", "apt-leslieville-2.svg", "apt-leslieville-3.svg"],
    "liberty": ["apt-liberty-1.svg", "apt-liberty-2.svg"],
    "north-york": ["apt-northyork-1.svg"],
    "st-lawrence": ["apt-stlawrence-1.svg"],
    "yorkville": ["apt-yorkville-1.svg", "apt-yorkville-2.svg", "condo-ye-1.svg"],
    "east-york": ["house-eastyork-1.svg"],
    "roncesvalles": ["house-roncy-1.svg", "house-roncy-2.svg"],
    "parkdale": ["room-parkdale-1.svg"],
}

# Generic assets for for-sale filler postings (keyword -> assets).
SEED_FOR_SALE_ASSETS: list[tuple[str, list[str]]] = [
    ("bike", ["bike-1.svg"]),
    ("laptop", ["laptop-1.svg"]),
    ("macbook", ["laptop-1.svg"]),
    ("table", ["table-1.svg"]),
    ("condo", ["condo-ye-1.svg"]),
]


def _assign_seed_photos(posting: dict[str, Any]) -> list[str]:
    """Deterministically attach seed photo assets to a seed posting."""
    if posting.get("photos"):
        return posting["photos"]
    housing_type = posting.get("housing_type", "classified")
    if housing_type in {"apartment", "sublet", "room", "house", "condo",
                        "townhouse", "basement", "loft", "duplex", "flat"}:
        nb = posting.get("neighborhood", "") or ""
        if nb not in SEED_PHOTO_ASSETS:
            nb = _neighborhood_from_location(nb)
        assets = SEED_PHOTO_ASSETS.get(nb, [])
        if assets:
            # pick 1-3 photos deterministically from the neighborhood set
            row_id = int(posting.get("id", 0))
            count = 1 + row_id % min(3, len(assets))
            start = row_id % len(assets)
            return [assets[(start + i) % len(assets)] for i in range(count)]
    if housing_type == "for-sale":
        title = posting.get("title", "").lower()
        for keyword, assets in SEED_FOR_SALE_ASSETS:
            if keyword in title:
                return assets[:1]
        # fall back to a generic product photo so every for-sale row has one
        row_id = int(posting.get("id", 0))
        fallback = ["table-1.svg", "bike-1.svg", "laptop-1.svg", "condo-ye-1.svg"]
        return [fallback[row_id % len(fallback)]]
    return []


CATEGORY_FILLER = {
    'acc': [('Junior accountant - downtown', 55000, 'Accounting firm hiring a junior accountant. Full-time with benefits.')],
    'act': [('Toronto hiking meetup - this weekend', 0, 'Group hike on the Don Valley trail this Saturday. All levels welcome, bring water.')],
    'aos': [('Mobile mechanic - brakes and oil', 90, 'Certified mechanic comes to you. Brake jobs and oil changes same day.')],
    'ara': [('Hand-thrown pottery set', 90, 'Six mugs and a serving bowl, stoneware.')],
    'ata': [('Victorian oak sideboard', 650, 'Carved oak sideboard from the 1890s, original finish.')],
    'ats': [("Painter's open studio - The Junction", 0, 'Open studio showing recent acrylic works. Coffee and conversation, free entry.')],
    'ava': [('Private pilot ground school books', 80, 'Complete ground school book set, current edition.')],
    'baa': [('Stokke high chair', 120, 'Wooden high chair, excellent condition.')],
    'bar': [('Swap: bread maker for juicer', 0, 'Barely used bread maker, looking to trade for a juicer.')],
    'bfa': [('POS system with cash drawer', 350, 'Complete point-of-sale system for a small shop.')],
    'bip': [('Crank set - 170mm', 60, 'Aluminum crank set with chainring, 170mm.')],
    'biz': [('Pop-up shop staffing', 20, 'Reliable staff for weekend pop-ups and markets.')],
    'bka': [('Sci-fi book lot - 20 books', 40, 'Mixed sci-fi paperbacks, all readable condition.')],
    'bts': [('Hair stylist - cuts at home', 45, 'Licensed stylist, cuts and colour at your place. $45 and up.')],
    'bus': [('Operations manager - retail', 70000, 'Growing retail chain needs an operations manager.')],
    'cba': [('Baseball card collection', 200, '90s collection in binders, ungraded.')],
    'cla': [('Vintage leather jacket - size M', 80, 'Genuine leather jacket, patina included.')],
    'cms': [('Phone screen replacement', 70, 'Same-day iPhone and Android screen replacement. Walk-in welcome.')],
    'com': [('Free community yoga in the park', 0, 'All-ages yoga every Sunday morning at Trinity Bellwoods. Bring a mat.')],
    'cps': [('Computer tune-up and virus removal', 60, 'Slow computer? Tune-up, cleanup and virus removal for $60.')],
    'crs': [('Logo design - 3 concepts', 150, 'Freelance designer, three concepts with revisions for $150.')],
    'csr': [('Customer service - remote', 19, 'Remote support role, $19/hr, equipment provided.')],
    'cwg': [('Film set crew - weekend', 200, 'PA for a weekend shoot, $200/day.')],
    'cys': [('Bike repair - tune-up special', 55, 'Full tune-up $55. Pickup and delivery within the core.')],
    'dmg': [('Cleaning - one-off', 150, 'Deep clean of a 2BR apartment this week.')],
    'edu': [('After-school tutor - math', 28, 'Tutor grades 6-9 math, afternoons, $28/hr.')],
    'egr': [('Structural engineer - 3+ yrs', 95000, 'Consulting firm seeking a structural engineer for building projects.')],
    'ema': [('Vinyl lot - jazz and soul', 120, '40 records, mostly 60s-70s jazz and soul.')],
    'etc': [('General helper - warehouse', 20, 'Light warehouse work, $20/hr, immediate start.')],
    'eve': [('Neighbourhood film night - outdoor screening', 0, 'Free outdoor movie in the park Friday at dusk. Bring a blanket.')],
    'evg': [('Event setup - Saturday', 18, 'Chairs, tables, signage for a wedding, $18/hr.')],
    'fbh': [('Line cook - brunch spot', 22, 'Experienced line cook for a busy brunch kitchen.')],
    'fgs': [('Garden cleanup - fall special', 120, 'Yard cleanup, hedge trimming and leaf removal.')],
    'fns': [('Small business bookkeeping', 200, 'Monthly bookkeeping for small businesses, $200/mo.')],
    'gms': [('Multi-family garage sale - Saturday', 0, 'Three families, tools, toys, clothes. 9am-2pm.')],
    'gov': [('Summer student - parks', 18, 'City parks summer position for students.')],
    'gra': [('Tomato seedlings - 6 pack', 8, 'Heirloom tomato seedlings, $8 for six.')],
    'grp': [('Board game night - new players welcome', 0, 'Weekly board game meetup at a local cafe. Thursday 7pm.')],
    'haa': [('Unopened skincare bundle', 60, 'New unopened skincare items from a subscription box.')],
    'hea': [('PSW - home care', 21, 'Personal support worker, flexible hours, $21/hr.')],
    'hsa': [('Espresso machine', 150, 'Stainless espresso machine with steamer.')],
    'hss': [('House cleaning - deep clean', 130, 'Two-person team, deep clean starting at $130.')],
    'hsw': [('Wanted: 1BR for Sept 1', 0, 'Quiet professional looking for a 1BR under $2200, moving Sept 1.')],
    'hum': [('HR coordinator', 60000, 'HR generalist supporting a team of 120.')],
    'hws': [('Registered massage - 60 min', 95, 'Registered massage therapist, in-home or clinic.')],
    'jwa': [('Sterling silver hoop earrings', 40, 'Small hoops, sterling, unworn.')],
    'kid': [('Weekend babysitter available', 18, 'Experienced sitter with first aid cert. Saturdays and some weeknights, $18/hr.')],
    'lab': [('Construction labourer', 24, 'Site labourer, $24/hr, tools provided.')],
    'laf': [('Found: grey cat near College St', 0, 'Friendly grey cat found near College and Spadina. Safe but looking for owner.')],
    'lbs': [('Moving help - hourly', 50, 'Two movers, $50/hr each, truck available.')],
    'lgl': [('Paralegal - real estate', 55000, 'Real estate paralegal for a mid-size firm.')],
    'lgs': [('Notary public - evenings', 25, 'Notarization $25 per document. Evenings and weekends.')],
    'lss': [('Guitar lessons - beginner friendly', 40, 'Weekly half-hour lessons, $40. Learn chords and songs fast.')],
    'maa': [('Hardwood offcuts - free to good home', 0, 'Bags of hardwood scraps from a workshop.')],
    'mar': [('Marketing coordinator - non-profit', 50000, 'Coordinate campaigns for a local non-profit.')],
    'mas': [('Boat detailing - lake ready', 150, 'Full detail to get your boat ready for the season.')],
    'med': [('Graphic designer - agency', 60000, 'Mid-level designer for a brand agency. Strong layout skills.')],
    'mis': [('You: red jacket on the streetcar - me: blue umbrella', 0, 'We shared the 505 this morning. You got off at Queen. Coffee sometime?')],
    'mnu': [('Machine operator - days', 22, 'CNC operator, day shift, training provided.')],
    'moa': [('iPhone 13 - 128GB unlocked', 550, 'Great condition, 87% battery, unlocked.')],
    'mpa': [('Chain and sprocket kit', 90, 'New chain and sprockets for a 600cc.')],
    'msa': [('Acoustic guitar - Yamaha', 180, 'Yamaha acoustic, new strings, nice tone.')],
    'muc': [('Acoustic duo looking for a bassist', 0, 'Gigging acoustic duo seeks bass player for weekend shows. Originals + covers.')],
    'npo': [('Fundraising assistant', 45000, 'Support the annual giving program at a charity.')],
    'ofc': [('Administrative assistant - part time', 22, 'Front desk and admin support, 25 hrs/week, $22/hr.')],
    'off': [('Office sublet - Queen West, 6 desks', 1800, 'Bright shared office for six, month to month. $1800/mo.')],
    'pas': [('Pet sitting - insured', 35, 'In-home pet sitting, $35/day. Photos daily.')],
    'pet': [('Adoptable kittens - rescued litter', 0, 'Four healthy kittens ready for adoption. Vet checked, litter trained.')],
    'pha': [('Canon 50mm f/1.8 lens', 120, 'Compact prime lens, clean glass.')],
    'pol': [('City council meeting - public comments', 0, 'Public comment period on the new housing plan. Tuesday 6pm at city hall.')],
    'ppa': [('Stainless range - 30 inch', 400, 'Gas range, clean, works great. Pickup only.')],
    'prk': [('Indoor parking spot - Annex', 250, 'Secure indoor spot near Bathurst station, $250/mo.')],
    'pta': [('Set of winter tires - 16 inch', 300, 'Four winter tires on rims, 205/55R16. Good tread.')],
    'rej': [('Leasing agent - condos', 48000, 'Lease apartments in a downtown tower, base + commission.')],
    'ret': [('Sales associate - footwear', 17, 'Retail associate, weekends required, $17/hr.')],
    'rid': [('Daily ride share to Mississauga', 5, 'Leaving 7:30am weekdays from the Annex. $5 towards gas.')],
    'rnr': [('The elevator in my building is broken again', 0, "Third time this month. 14 floors. On a hot day. That's all.")],
    'rts': [('Property manager for single units', 150, 'Experienced property manager for single family rentals.')],
    'sad': [('Network administrator', 75000, 'Maintain networks and servers for a mid-size org.')],
    'sec': [('Security guard - evenings', 20, 'Licensed security, office building, evenings.')],
    'sga': [('Road bike - 56cm', 500, 'Aluminum road bike, Shimano groupset, rides great.')],
    'sha': [('Roommate wanted - 2BR Leslieville', 1200, 'Looking for a roommate for the second bedroom, $1200/mo.')],
    'sks': [('Drywall and painting', 250, 'Small drywall repairs and painting. Free quotes.')],
    'sls': [('B2B sales rep - SaaS', 65000, 'Inside sales for a software company, base + commission.')],
    'spa': [('Licensed esthetician', 25, 'Esthetician for a spa in Yorkville, $25/hr + tips.')],
    'swp': [('Looking to swap: 1BR Annex for 2BR east end', 0, 'Family growing, hoping to swap our Annex 1BR for a 2BR in Riverdale.')],
    'sya': [('Dell OptiPlex desktop - i5', 250, 'Refurbished i5 desktop with SSD, ready to use.')],
    'syp': [('32GB DDR4 RAM kit', 80, 'Two 16GB sticks, tested.')],
    'taa': [('LEGO city sets - bundle', 110, 'Four city sets, no box, all pieces.')],
    'tch': [('Help desk - level 1', 22, 'First-line IT support, $22/hr.')],
    'tfr': [('Video editor - freelance', 400, 'Edit corporate videos, $400 per project.')],
    'tla': [('Cordless drill + impact driver', 140, 'Two-tool kit with batteries and charger.')],
    'tlg': [('Open mic host - weekly', 60, 'Host a weekly open mic, $60/night.')],
    'tra': [('5x8 utility trailer', 1800, 'Steel utility trailer, new tires, title in hand.')],
    'trd': [('Electrician apprentice', 22, 'Apprentice electrician, commercial projects.')],
    'trp': [('Delivery driver - own car', 20, 'Package delivery, $20/hr + km.')],
    'trv': [('Cottage shuttle service', 40, 'Weekend shuttle to Muskoka cottages from Union Station.')],
    'vga': [('PS5 with two controllers', 480, 'Console, two controllers, two games.')],
    'vnn': [('Local news: new farmers market opens', 0, 'The new weekend farmers market on Dundas West opens this Saturday.')],
    'vol': [('Volunteers needed - food bank sorting', 0, 'Two-hour shifts, flexible days. No experience needed.')],
    'waa': [('Wanted: bicycle trailer', 0, 'Looking for a used bike trailer for a toddler.')],
    'wet': [('Resume and cover letter review', 60, 'Career coach review with edits, $60.')],
    'wrg': [('Blog post - 800 words', 100, 'Write an 800-word post for a travel blog.')],
    'wri': [('Technical writer contract', 60, 'Documentation for a software product, remote.')],
    'wta': [('Set of alloy wheels - 17 inch', 450, 'Four 17-inch alloys with almost-new tires.')],
    'zip': [('Free: moving boxes', 0, 'About 30 boxes of various sizes, pickup in the Annex.')],
    'boo': [('Aluminum fishing boat with trailer', 3200, '16ft aluminum boat, 25hp outboard, trailer included.')],
    'cta': [('2018 Honda Civic LX - clean title', 18500, 'One owner, 78k km, winter tires included.')],
    'mca': [('Honda CBR600 - low km', 5200, '2009 CBR600, 22k km, new chain and sprockets.')],
    'rva': [('Class C motorhome - 2012', 68000, 'Sleeps 6, generator, low km, ready for the season.')],
    'sna': [('ATV utility quad - 4x4', 4500, 'Honda utility ATV, plow attachment included.')],
    'evs': [('Wedding planner - full day', 400, 'Day-of coordination for weddings, $400.')],
    'foa': [('Mixed lot - books, records, small furniture', 60, 'Grab bag lot, everything must go.')],
    'tia': [('Two tickets - Blue Jays vs Yankees', 180, 'Section 120, weekend game, pair for $180.')],
    'rrr': [('Full-stack developer resume', 0, 'Seeking remote or hybrid full-stack roles. 5 years experience with Python and React.')],
    'crg': [("Illustrator for children\'s book", 800, "20 illustrations for a children\'s book, $800 flat.")],
}

# Real-style neutral titles for categories the live site currently has no
# postings in (scraped empty) and that have no CATEGORY_FILLER entry. Avoids
# borrowing another category's entries (which leaked "junior accountant"
# titles into software/web) and stays free of level keywords.
_EMPTY_CATEGORY_FILLER: dict[str, list[tuple[str, int, str]]] = {
    'sof': [
        ('Backend developer - contract', 95000, 'Backend developer for a 6-month contract. Python experience required.'),
        ('QA engineer - product team', 85000, 'Manual and automated testing for a growing product team.'),
        ('Data analyst - reporting', 78000, 'SQL reporting and dashboards. Hybrid work from downtown.'),
    ],
    'web': [
        ('Frontend developer - web apps', 90000, 'React/TypeScript frontend for internal web apps.'),
        ('WordPress site build - freelance', 3000, 'Marketing site build for a local business. Five pages.'),
        ('UI/UX designer - contract', 75000, 'Design system and product UI work, 6-month contract.'),
    ],
}


_SECTION_VARIANTS: dict[str, list[str]] = {
    "community": ["", " - this Saturday", " - weekly", " - free entry", " - all welcome",
                  " - this Friday", " - Sunday morning", " - new members welcome",
                  " - this Sunday", " - monthly"],
    "services": ["", " - same-day", " - evenings & weekends", " - free quotes", " - insured",
                 " - experienced", " - student discount", " - 24h response",
                 " - licensed", " - references available"],
    "for-sale": ["", " - like new", " - great condition", " - needs minor TLC", " - price firm",
                 " - negotiable", " - pickup today", " - reduced",
                 " - barely used", " - delivery available"],
    "autos": ["", " - well maintained", " - one owner", " - recent service", " - winter tires included",
              " - clean title", " - negotiable", " - motivated seller",
              " - no accidents", " - e-test passed"],
    "jobs": ["", " - contract", " - part-time",
             " - hybrid", " - remote", " - urgent start",
             " - full-time", " - benefits included", " - weekdays", " - start soon"],
    "gigs": ["", " - weekend", " - urgent", " - this week", " - flexible", " - recurring",
             " - one-off", " - ASAP",
             " - daytime", " - evenings"],
    "housing": ["", " - available now", " - no fees", " - quiet building", " - utilities included",
                " - short term ok", " - furnished option", " - near transit",
                " - parking included", " - pet friendly"],
}
_SECTION_PRICE_FACTORS: dict[str, list[float]] = {
    "community": [1.0] * 10,
    "services": [1.0, 0.9, 1.1, 0.8, 1.15, 0.95, 1.2, 0.85, 1.05, 0.9],
    "for-sale": [1.0, 0.95, 0.85, 1.1, 0.9, 1.05, 0.8, 0.75, 0.95, 1.12],
    "autos": [1.0, 0.95, 0.9, 1.08, 0.85, 1.02, 0.92, 0.8, 1.1, 0.88],
    "jobs": [1.0, 0.9, 1.15, 1.05, 0.8, 1.1, 1.0, 0.95, 1.2, 1.05],
    "gigs": [1.0, 0.9, 1.1, 0.85, 1.05, 0.95, 1.2, 0.8, 1.15, 0.9],
    "housing": [1.0, 0.95, 1.05, 0.9, 1.08, 0.92, 1.1, 0.88, 0.95, 1.12],
}
_DESC_TAILS = [
    " Please reach out for details.",
    " Message for availability and more photos.",
    " Local pickup; happy to answer questions.",
    " Serious inquiries only, thank you.",
    " Also open to reasonable offers.",
    " Available immediately.",
]


def _expand_filler(
    slug: str, title: str, price: int, desc: str, section: str
) -> list[tuple[str, int, str]]:
    """Expand one anchor posting into 8-10 distinct variants."""
    variants: list[tuple[str, int, str]] = [(title, price, desc)]
    suffixes = _SECTION_VARIANTS.get(section, _SECTION_VARIANTS["for-sale"])
    factors = _SECTION_PRICE_FACTORS.get(section, [1.0] * 8)
    title_lower = title.lower()
    for i in range(1, len(suffixes)):
        suffix = suffixes[i]
        words = set(suffix.strip().lstrip("- ").split())
        if words and words.issubset(title_lower.split()):
            continue
        new_price = int(round(price * factors[i])) if price > 0 else 0
        tail = _DESC_TAILS[i % len(_DESC_TAILS)]
        variants.append((f"{title}{suffix}", new_price, f"{desc}{tail}"))
    return variants


def _neighborhood_from_location(location: str) -> str:
    """Map a real craigslist location string onto the closest known
    neighborhood slug (for filters/labels); falls back to 'annex'."""
    text = location.lower()
    mapping = [
        ("scarborough", "scarborough"),
        ("north york", "north-york"),
        ("east york", "east-york"),
        ("etobicoke", "etobicoke"),
        ("kensington", "kensington"),
        ("leslieville", "leslieville"),
        ("yorkville", "yorkville"),
        ("corktown", "corktown"),
        ("cityplace", "cityplace"),
        ("city place", "cityplace"),
        ("st. lawrence", "st-lawrence"),
        ("st lawrence", "st-lawrence"),
        ("liberty", "liberty"),
        ("roncesvalles", "roncesvalles"),
        ("parkdale", "parkdale"),
        ("beaches", "beaches"),
        ("annex", "annex"),
        ("crosstown", "crosstown"),
        ("davisville", "crosstown"),
        ("toronto", "annex"),
    ]
    for needle, slug in mapping:
        if needle in text:
            return slug
    return "annex"


# housing category -> (housing_type, default beds) used when seeding from the
# real snapshot so the detail page shows the right attribute labels.
_HOUSING_CATEGORY_TYPES: dict[str, tuple[str, str]] = {
    "apa": ("apartment", "1br"),
    "sub": ("sublet", "1br"),
    "roo": ("room", "1br"),
    "hou": ("house", "2br"),
    "swp": ("housing swap", "n/a"),
    "off": ("office / commercial", "n/a"),
    "prk": ("parking / storage", "n/a"),
    "rea": ("real estate for sale", "n/a"),
    "vac": ("vacation rentals", "1br"),
    "cwd": ("room wanted", "1br"),
    "cpx": ("housing wanted", "1br"),
}


def _infer_listing_attributes(
    title: str, category: str, section: str
) -> dict[str, Any]:
    """Infer realistic listing attributes from the real posting title and
    category, so detail pages show concrete values instead of n/a."""
    t = title.lower()
    beds = "n/a"
    if re.search(r"\bstudio\b|\bbachelor\b|\b0 ?br\b|\b0 ?bd\b", t):
        beds = "studio"
    elif re.search(r"\b4 ?bedroom\b|\b4 ?bd\b|\b4 ?br\b|\b4 ?bed\b", t):
        beds = "4br"
    elif re.search(r"\b3 ?bedroom\b|\b3 ?bd\b|\b3 ?br\b|\b3 ?bed\b", t):
        beds = "3br"
    elif re.search(r"\btwo ?bedroom\b|\b2 ?bedroom\b|\b2 ?bd\b|\b2 ?br\b|\b2 ?bed\b", t):
        beds = "2br"
    elif re.search(r"\b1 ?bedroom\b|\bone ?bedroom\b|\b1 ?bd\b|\b1 ?br\b|\b1 ?bed\b", t):
        beds = "1br"
    elif section == "housing":
        beds = "1br"
    baths = "1"
    m = re.search(r"(\d) ?(?:ba(?:th)?|bathroom|washroom)\b", t)
    if m:
        baths = m.group(1)
    sqft = ""
    m = re.search(r"([\d,]{3,5}) ?(?:sq\s*\.?\s*ft|ft2|sf|sqft|sq\.?\s*ft\.?)", t)
    if m:
        sqft = m.group(1).replace(",", "")
    elif re.search(r"([\d,]{3,5}) ?sq", t):
        sqft = re.search(r"([\d,]{3,5}) ?sq", t).group(1).replace(",", "")
    elif section == "housing":
        sqft = str(400 + (hash(title) % 8) * 100) if beds == "studio" else str(500 + (hash(title) % 9) * 100)
    furnished = bool(re.search(r"\bfurnish(?:ed|ing)?\b|\bfurn\b", t))
    available = None
    m = re.search(r"available[: ]+([a-z]{3,9} \d{1,2}|now|immediately|immediate|today)", t)
    if m:
        available = m.group(1)
    elif re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", t):
        month = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", t).group(1)
        available = f"1 {month.title()} 2026"
    elif section == "housing":
        available = "immediately"
    laundry = "in-unit" if re.search(r"laundry", t) else ""
    parking = "available" if re.search(r"parking|garage|driveway", t) else ""
    ac = "yes" if re.search(r"\bac\b|air ?cond", t) else ""
    if section == "housing":
        if not laundry:
            laundry = "in-unit" if (hash(title) % 2) == 0 else "in building"
        if not parking:
            parking = "street" if (hash(title) % 3) == 0 else "none"
        if not ac:
            ac = "window" if (hash(title) % 4) == 0 else "none"
    return {
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "furnished": furnished,
        "available": available,
        "laundry": laundry,
        "parking": parking,
        "ac": ac,
    }


def _rich_seed_description(title: str, location: str, section: str) -> str:
    """Create useful body copy when the search capture had no detail body.

    Search-result evidence gives us the real title, location, category and
    price, but not every result's full body. A section-specific synthetic body
    is more honest and useful than the former title-only value;
    source-observed bodies in ``real_posting_details.json`` always win.
    """

    place = location or "the local area"
    if section == "housing":
        return (
            f"{title}. This housing listing is located in {place}.\n\n"
            "Contact the poster to confirm availability, viewing times, lease "
            "terms, included utilities, and any application requirements."
        )
    if section in {"for-sale", "autos"}:
        return (
            f"{title} is available in {place}. The item is described as used "
            "and in working condition unless the title says otherwise.\n\n"
            "Review the photos for condition and contact the owner to arrange "
            "a local inspection or pickup."
        )
    if section == "jobs":
        return (
            f"{title}. This opportunity is based in {place}.\n\n"
            "Contact the poster for the complete responsibilities, schedule, "
            "compensation range, required experience, and application steps."
        )
    if section == "gigs":
        return (
            f"{title}. This is a short-term opportunity in {place}.\n\n"
            "Ask the poster to confirm the work date, expected deliverables, "
            "duration, and compensation before accepting the gig."
        )
    if section == "services":
        return (
            f"{title}. Service is available in {place}.\n\n"
            "Message the provider with the scope of work to confirm pricing, "
            "availability, service area, and any materials required."
        )
    if section == "community":
        return (
            f"{title}. This community post is for people in and around {place}.\n\n"
            "Reply to the poster for the latest meeting details, participation "
            "information, and accessibility notes."
        )
    if section == "resumes":
        return (
            f"{title}. Candidate based in {place}.\n\n"
            "Contact the candidate to request a current resume, work samples, "
            "availability, and references."
        )
    return (
        f"{title}. This listing is based in {place}.\n\n"
        "Contact the poster for complete details and current availability."
    )


def _real_filler_postings() -> list[dict[str, Any]]:
    """Seed postings from the scraped snapshot of real craigslist toronto
    listings (title/price/location), captured from the JS-rendered search
    pages so every row is a real posting — never invented or duplicated.
    Categories with no real entries fall back to the synthetic
    CATEGORY_FILLER."""
    rows: list[dict[str, Any]] = []
    row_id = 3000100
    section_by_slug = {c[0]: c[2] for c in SEED_CATEGORIES}
    dealer_slugs = {
        "aos", "bts", "cms", "cps", "crs", "cys", "fgs", "fns", "hws", "hss",
        "lbs", "lgs", "lss", "mas", "pas", "rts", "sks", "biz", "trv", "wet",
        "acc", "ofc", "egr", "med", "bus", "csr", "edu", "etc", "fbh", "lab",
        "gov", "hum", "lgl", "mnu", "mar", "hea", "npo", "rej", "ret", "sls",
        "spa", "sec", "trd", "sad", "tch", "trp", "tfr", "wri",
    }
    for slug in sorted(section_by_slug):
        if slug == "hhh":
            continue
        section = section_by_slug[slug]
        real = REAL_POSTINGS.get(slug, [])
        entries: list[dict[str, Any]] = []
        for item in real:
            title = item["title"]
            if not title:
                continue
            source_url = item.get("url", "")
            detail = REAL_POSTING_DETAILS.get(source_url, {})
            entries.append(
                {
                    "title": title,
                    "price": item.get("price"),
                    "location": item.get("location", ""),
                    "desc": detail.get("description", ""),
                    "photos": detail.get("photos", []),
                    "posted": detail.get("posted_at"),
                    "updated": detail.get("updated_at"),
                }
            )
        # synthetic fallback only when the real snapshot has nothing
        if not entries:
            filler_items = CATEGORY_FILLER.get(slug) or _EMPTY_CATEGORY_FILLER.get(slug) or []
            for title, price, desc in filler_items[:10]:
                entries.append({"title": title, "price": price, "location": "", "desc": desc})
        housing_type, beds = _HOUSING_CATEGORY_TYPES.get(
            slug, ("for-sale" if section in {"for-sale", "autos"} else "classified", "n/a")
        )
        for entry in entries:
            # Store the real location text (e.g. "Christie Pits, Toronto") so
            # list rows and the detail page show what the live site shows.
            neighborhood = (entry["location"] or "").strip() or "toronto"
            inferred = _infer_listing_attributes(entry["title"], slug, section)
            description = entry["desc"] or _rich_seed_description(
                entry["title"], neighborhood, section
            )
            posted_at = entry.get("posted") or (
                "2026-06-1%dT10:00:00+00:00" % (1 + row_id % 9)
            )
            rows.append(
                {
                    "id": row_id,
                    "region": "toronto",
                    "category": slug,
                    "title": entry["title"],
                    "price": entry["price"],
                    "neighborhood": neighborhood,
                    "postal": "M6G",
                    "beds": inferred["beds"] if inferred["beds"] != "n/a" else beds,
                    "baths": inferred["baths"],
                    "sqft": inferred["sqft"],
                    "desc": description,
                    "furnished": inferred["furnished"],
                    "posted_by": "dealer" if slug in dealer_slugs else "owner",
                    "available": inferred["available"],
                    "photos": entry.get("photos") or [],
                    "housing_type": housing_type,
                    "posted": posted_at,
                    "updated": entry.get("updated") or posted_at,
                    "account": None,
                    "laundry": inferred["laundry"],
                    "parking": inferred["parking"],
                    "ac": inferred["ac"],
                    "slug": re.sub(r"[^a-z0-9]+", "-", entry["title"].lower()).strip("-"),
                }
            )
            row_id += 1
    return rows


def _filler_postings() -> list[dict[str, Any]]:
    """A believable posting per homepage category so no category is empty."""
    return _real_filler_postings()


def _seed_postings() -> list[dict[str, Any]]:
    """Deterministic Toronto housing catalog (plus a small for-sale set)."""

    def posting(
        row_id: int,
        category: str,
        title: str,
        price: int,
        neighborhood: str,
        postal: str,
        beds: str,
        desc: str,
        *,
        furnished: bool = False,
        posted_by: str = "owner",
        available: str | None = None,
        photos: list[str] | None = None,
        housing_type: str = "apartment",
        posted: str = "2026-06-12T10:00:00+00:00",
        account: str | None = None,
        sqft: str = "",
        baths: str = "1",
        laundry: str = "",
        parking: str = "",
        ac: str = "",
    ) -> dict[str, Any]:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return {
            "id": row_id,
            "region": "toronto",
            "category": category,
            "title": title,
            "price": price,
            "neighborhood": neighborhood,
            "postal": postal,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "desc": desc,
            "furnished": furnished,
            "posted_by": posted_by,
            "available": available,
            "photos": photos or [],
            "housing_type": housing_type,
            "posted": posted,
            "account": account,
            "laundry": laundry,
            "parking": parking,
            "ac": ac,
            "slug": slug,
        }

    # Only the canonical fixture postings that tests and the task contract
    # depend on are hand-written; every other category is populated from the
    # scraped snapshot of real craigslist toronto postings (see
    # _real_filler_postings), so titles/prices/locations match the live site.
    return [
        posting(
            1000001, "sub", "1BR near Annex - furnished sublet Jul-Aug", 2400,
            "annex", "M6G", "1br",
            "Available July 1 through August 31. One-bedroom furnished sublet steps "
            "from the Annex, near subway and shops. Utilities included, high-speed "
            "internet, fully furnished with queen bed, desk, and kitchen essentials. "
            "Quiet building, laundry in unit. $2400/month, July-August.",
            furnished=True, available="2026-07-01", housing_type="sublet",
            posted="2026-06-15T10:00:00+00:00", account="poster-1001",
            photos=[],
            sqft="650", baths="1", laundry="in-unit", parking="none", ac="window",
        ),
        posting(
            1000021, "apa", "2BR apartment near Leslieville", 2850,
            "leslieville", "M4L", "2br",
            "Bright two-bedroom apartment near Queen East. Steps to shops, cafes "
            "and the beach streetcar. Available August 1.",
            furnished=False, available="2026-08-01", housing_type="apartment",
            posted="2026-06-18T10:00:00+00:00", account="poster-1001",
            photos=[], sqft="900", baths="1",
            laundry="in-unit", parking="none", ac="window",
        ),
        posting(
            1000031, "roo", "Room near Kensington Market", 950,
            "kensington", "M5T", "1br",
            "Private room in a shared house steps from Kensington Market. "
            "Utilities and wifi included, shared kitchen and bath.",
            furnished=True, housing_type="room",
            posted="2026-06-17T10:00:00+00:00", account="poster-1001",
            photos=[], sqft="120", baths="shared",
            laundry="shared", parking="street", ac="none",
        ),
    ]


def _seed_neighborhoods() -> list[dict[str, Any]]:
    rows = []
    for index, (slug, (name, prefixes)) in enumerate(
        TORONTO_NEIGHBORHOODS.items(), start=1
    ):
        rows.append(
            {
                "id": index,
                "slug": slug,
                "name": name,
                "postal_prefixes": ",".join(prefixes),
            }
        )
    return rows


def _upgrade_existing_database(connection: sqlite3.Connection) -> None:
    """Bring an older database up to the current seed.

    New categories are inserted, and the seed postings (system-seeded rows
    with no owning account) are rebuilt from the current catalog — including
    the scraped real-postings snapshot — so titles/prices/locations match the
    live site. Postings created by real users (account_id NOT NULL) and all
    user data (favorites, saved searches, replies, drafts) are preserved."""

    existing = {
        row["slug"] for row in connection.execute("SELECT slug FROM cl_categories")
    }
    for slug, name, section, _parent in SEED_CATEGORIES:
        if slug not in existing:
            connection.execute(
                "INSERT INTO cl_categories (slug, name, section, parent)"
                " VALUES (?, ?, ?, NULL)",
                (slug, name, section),
            )
    _rebuild_seed_postings(connection)
    _top_up_empty_categories(connection)
    _backfill_missing_photos(connection)
    _seed_forums(connection)


def _rebuild_seed_postings(connection: sqlite3.Connection) -> None:
    """Replace the system-seeded catalog (seed id ranges) with the current
    seed set so upgraded databases carry the real-data catalog. User-created
    postings (ids outside the seed ranges) keep their rows; dependent photo
    rows are cleaned with the seed rows. The canonical fixtures now belong to
    the poster account, so seed rows are matched by id range, not account."""

    seed_ids = "id <= 1000031 OR id >= 3000000"
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        for table in ("cl_posting_photos", "cl_favorites", "cl_reply_messages", "cl_flags"):
            connection.execute(
                f"DELETE FROM {table} WHERE posting_id IN"
                f" (SELECT id FROM cl_postings WHERE {seed_ids})"
            )
        connection.execute(
            f"DELETE FROM cl_postings WHERE {seed_ids}"
        )
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    region_ids = {
        row["slug"]: row["id"]
        for row in connection.execute("SELECT id, slug FROM cl_regions")
    }
    for posting in _seed_postings() + _filler_postings():
        posting["photos"] = _assign_seed_photos(posting)
        cursor = connection.execute(
            " INSERT INTO cl_postings ("
            " id, region_id, category_slug, title, price, description,"
            " postal_code, neighborhood, housing_type, bedrooms, baths,"
            " square_feet, available_date, furnished, laundry, parking, ac,"
            " posted_by, contact_email, contact_phone, contact_method, status,"
            " account_id, created_at, updated_at, renewed_at, removed_at, slug"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                posting["id"],
                region_ids[posting["region"]],
                posting["category"],
                posting["title"],
                posting["price"],
                posting["desc"],
                posting["postal"],
                posting["neighborhood"],
                posting["housing_type"],
                posting["beds"],
                posting["baths"],
                posting["sqft"],
                posting["available"],
                1 if posting["furnished"] else 0,
                posting["laundry"],
                posting["parking"],
                posting["ac"],
                posting["posted_by"],
                "poster@example.com" if posting["account"] else "poster@example.com",
                "",
                "email",
                "published",
                posting["account"],
                posting["posted"],
                posting.get("updated", posting["posted"]),
                None,
                None,
                posting["slug"],
            ),
        )
        posting_id = cursor.lastrowid
        for position, photo in enumerate(posting["photos"]):
            connection.execute(
                "INSERT INTO cl_posting_photos (posting_id, filename, position)"
                " VALUES (?, ?, ?)",
                (posting_id, photo, position),
            )


def _backfill_missing_photos(connection: sqlite3.Connection) -> None:
    """Attach seed photo assets to existing housing/for-sale postings that
    have none, so upgraded databases show photos like a fresh seed."""

    rows = connection.execute(
        "SELECT p.id, p.neighborhood, p.housing_type, p.title, c.section"
        " FROM cl_postings p LEFT JOIN cl_categories c ON c.slug = p.category_slug"
        " WHERE p.status != 'removed'"
        " AND NOT EXISTS (SELECT 1 FROM cl_posting_photos ph WHERE ph.posting_id = p.id)"
    ).fetchall()
    for row in rows:
        housing_type = row["housing_type"]
        if housing_type == "classified":
            if row["section"] == "housing":
                housing_type = "apartment"
            elif row["section"] in {"for-sale", "autos"}:
                housing_type = "for-sale"
        photos = _assign_seed_photos(
            {
                "id": row["id"],
                "neighborhood": row["neighborhood"],
                "housing_type": housing_type,
                "title": row["title"],
                "photos": [],
            }
        )
        for position, photo in enumerate(photos):
            connection.execute(
                "INSERT INTO cl_posting_photos (posting_id, filename, position)"
                " VALUES (?, ?, ?)",
                (row["id"], photo, position),
            )


def _top_up_empty_categories(connection: sqlite3.Connection) -> None:
    """Ensure every category has at least 10 postings by generating variants
    from existing postings of that category (also repairs old databases that
    predate the expanded catalog)."""

    categories = [
        row["slug"]
        for row in connection.execute("SELECT slug FROM cl_categories")
        if row["slug"] != "hhh"
    ]
    sections = {
        row["slug"]: row["section"]
        for row in connection.execute("SELECT slug, section FROM cl_categories")
    }
    for slug in categories:
        # Categories populated from the real-postings snapshot keep exactly
        # the postings that exist on the live site — never topped up with
        # invented variants.
        if REAL_POSTINGS.get(slug):
            continue
        rows = connection.execute(
            "SELECT * FROM cl_postings WHERE category_slug=? ORDER BY id LIMIT 3",
            (slug,),
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) AS n FROM cl_postings WHERE category_slug=?",
            (slug,),
        ).fetchone()["n"]
        if count >= 10:
            continue
        section = sections.get(slug, "for-sale")
        variants: list[tuple[str, int, str]] = []
        if rows:
            bases = rows
        else:
            # Newly added category with no postings yet: fabricate from the
            # category filler table so old databases still get 8-10 postings.
            filler_items = (
                CATEGORY_FILLER.get(slug)
                or _EMPTY_CATEGORY_FILLER.get(slug)
                or next(iter(CATEGORY_FILLER.values()), [])
            )
            bases = [
                {
                    "title": title,
                    "price": price,
                    "description": desc,
                }
                for title, price, desc in filler_items[:3]
            ]
        for base in bases:
            expanded = _expand_filler(
                slug,
                base["title"],
                int(base["price"]),
                base["description"],
                section,
            )
            for title, price, desc in expanded[1:]:
                variants.append((title, price, desc))
        # pick distinct variants until the category reaches 10 postings
        region_ids = {
            row["slug"]: row["id"]
            for row in connection.execute("SELECT id, slug FROM cl_regions")
        }
        now = now_utc()
        for index, (title, price, desc) in enumerate(variants):
            if count >= 10:
                break
            slug_text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120] or "posting"
            cursor = connection.execute(
                "INSERT INTO cl_postings ("
                " region_id, category_slug, title, price, description, postal_code,"
                " neighborhood, housing_type, bedrooms, baths, square_feet,"
                " available_date, furnished, laundry, parking, ac, posted_by,"
                " contact_email, contact_phone, contact_method, status, account_id,"
                " created_at, updated_at, slug"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    region_ids["toronto"],
                    slug,
                    title,
                    price,
                    desc,
                    "M6G",
                    "annex",
                    "classified",
                    "n/a",
                    "1",
                    "",
                    "",
                    0,
                    "",
                    "",
                    "",
                    "owner",
                    "poster@example.com",
                    "",
                    "email",
                    "published",
                    None,
                    now,
                    now,
                    slug_text,
                ),
            )
            posting_id = int(cursor.lastrowid)
            if section == "housing":
                photos = _assign_seed_photos(
                    {
                        "id": posting_id,
                        "neighborhood": "annex",
                        "housing_type": "apartment",
                        "title": title,
                        "photos": [],
                    }
                )
                for position, photo in enumerate(photos):
                    connection.execute(
                        "INSERT INTO cl_posting_photos (posting_id, filename, position)"
                        " VALUES (?, ?, ?)",
                        (posting_id, photo, position),
                    )
            count += 1


def seed() -> None:
    """Deterministic seed; idempotent under the frozen clock.

    Also upgrades older databases: missing categories are inserted and every
    category is topped up to at least five postings, so an existing data file
    does not need to be deleted after a catalog expansion.
    """

    backend, auth = services()
    with closing(_connect(backend.lifecycle.database_path)) as connection, connection:
        if connection.execute("SELECT COUNT(*) FROM cl_regions").fetchone()[0] > 0:
            _upgrade_existing_database(connection)
        else:
            for slug, name, country in SEED_REGIONS:
                connection.execute(
                    "INSERT INTO cl_regions (slug, name, country) VALUES (?, ?, ?)",
                    (slug, name, country),
                )
            for slug, name, section, parent in SEED_CATEGORIES:
                connection.execute(
                    "INSERT INTO cl_categories (slug, name, section, parent)"
                    " VALUES (?, ?, ?, ?)",
                    (slug, name, section, parent),
                )
            region_ids = {
                row["slug"]: row["id"]
                for row in connection.execute("SELECT id, slug FROM cl_regions")
            }
            for neighborhood in _seed_neighborhoods():
                connection.execute(
                    "INSERT INTO cl_neighborhoods (slug, name, postal_prefixes)"
                    " VALUES (?, ?, ?)",
                    (neighborhood["slug"], neighborhood["name"], neighborhood["postal_prefixes"]),
                )
            for posting in _seed_postings() + _filler_postings():
                posting["photos"] = _assign_seed_photos(posting)
                cursor = connection.execute(
                    "INSERT INTO cl_postings ("
                    " id, region_id, category_slug, title, price, description,"
                    " postal_code, neighborhood, housing_type, bedrooms, baths,"
                    " square_feet, available_date, furnished, laundry, parking, ac,"
                    " posted_by, contact_email, contact_phone, contact_method, status,"
                    " account_id, created_at, updated_at, renewed_at, removed_at, slug"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        posting["id"],
                        region_ids[posting["region"]],
                        posting["category"],
                        posting["title"],
                        posting["price"],
                        posting["desc"],
                        posting["postal"],
                        posting["neighborhood"],
                        posting["housing_type"],
                        posting["beds"],
                        posting["baths"],
                        posting["sqft"],
                        posting["available"],
                        1 if posting["furnished"] else 0,
                        posting["laundry"],
                        posting["parking"],
                        posting["ac"],
                        posting["posted_by"],
                        "poster@example.com" if posting["account"] else "poster@example.com",
                        "",
                        "email",
                        "published",
                        posting["account"],
                        posting["posted"],
                        posting.get("updated", posting["posted"]),
                        None,
                        None,
                        posting["slug"],
                    ),
                )
                posting_id = cursor.lastrowid
                for position, photo in enumerate(posting["photos"]):
                    connection.execute(
                        "INSERT INTO cl_posting_photos (posting_id, filename, position)"
                        " VALUES (?, ?, ?)",
                        (posting_id, photo, position),
                    )
            # ensure every category carries at least five postings
            _top_up_empty_categories(connection)
            _backfill_missing_photos(connection)
            _seed_forums(connection)

    _seed_accounts(auth)
    _attach_fixture_accounts(auth)


def _attach_fixture_accounts(auth: LocalAuthStore) -> None:
    """Give the canonical fixture postings to the poster account. The auth
    account_id is generated at reset, so resolve it by subject_id after the
    accounts are seeded and update the posting rows."""
    try:
        with closing(connect()) as connection, connection:
            row = connection.execute(
                "SELECT account_id FROM local_auth_accounts WHERE subject_id = ?",
                ("poster-1001",),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE cl_postings SET account_id = ? WHERE id IN (1000001, 1000021, 1000031)",
                    (row["account_id"],),
                )
    except Exception:
        # best-effort: account attachment must never block seeding
        pass


def reset() -> None:
    """Delete all site business, auth, mail and payment rows atomically."""

    backend, auth = services()

    def _site_reset(connection: sqlite3.Connection) -> None:
        for table in (
            "cl_registration_events",
            "cl_draft_photos",
            "cl_posting_drafts",
            "cl_flags",
            "cl_reply_messages",
            "cl_saved_searches",
            "cl_favorites",
            "cl_posting_photos",
            "cl_postings",
            "cl_neighborhoods",
            "cl_categories",
            "cl_regions",
            "cl_forum_posts",
            "cl_forum_boards",
            "craigslist_schema_migrations",
        ):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        backend.lifecycle.reset_embedded(
            connection,
            confirm_site_id=SITE_ID,
        )

    auth.reset_site_state(site_reset=_site_reset, seed_accounts=[])
    _ensure_business_schema(backend.lifecycle.database_path)
    seed()
    _seed_accounts(auth)
    _attach_fixture_accounts(auth)


def _seed_accounts(auth: LocalAuthStore) -> None:
    auth.seed_account(
        subject_id="poster-1001",
        email="poster@example.com",
        display_name="Poster",
        password="Websitebench1!",
    )
    auth.seed_account(
        subject_id="seeker-1002",
        email="seeker@example.com",
        display_name="Seeker",
        password="Websitebench1!",
    )


# ---------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------


def region_by_slug(slug: str) -> sqlite3.Row | None:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_regions WHERE slug = ?", (slug,)
        ).fetchone()


def all_regions() -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_regions ORDER BY id"
        ).fetchall()


def categories(section: str | None = None) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        if section:
            return connection.execute(
                "SELECT * FROM cl_categories WHERE section = ? ORDER BY id",
                (section,),
            ).fetchall()
        return connection.execute(
            "SELECT * FROM cl_categories ORDER BY id"
        ).fetchall()


def category_count(region_slug: str, category_slug: str) -> int:
    with closing(connect()) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS n FROM cl_postings p
            JOIN cl_regions r ON r.id = p.region_id
            WHERE r.slug = ? AND p.category_slug = ? AND p.status != 'removed'
            """,
            (region_slug, category_slug),
        ).fetchone()
        return int(row["n"])


def section_postings(
    region_slug: str,
    category_slug: str,
    *,
    limit: int = 200,
) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            """
            SELECT p.*, r.slug AS region_slug FROM cl_postings p
            JOIN cl_regions r ON r.id = p.region_id
            WHERE r.slug = ? AND p.category_slug = ? AND p.status != 'removed'
            ORDER BY p.created_at DESC LIMIT ?
            """,
            (region_slug, category_slug, limit),
        ).fetchall()


def _posting_row(connection: sqlite3.Connection, posting_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT p.*, r.slug AS region_slug FROM cl_postings p"
        " JOIN cl_regions r ON r.id = p.region_id WHERE p.id = ?",
        (posting_id,),
    ).fetchone()


def get_posting(posting_id: int) -> sqlite3.Row | None:
    with closing(connect()) as connection:
        return _posting_row(connection, posting_id)


def posting_photos(posting_id: int) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_posting_photos WHERE posting_id = ?"
            " ORDER BY position, id",
            (posting_id,),
        ).fetchall()


# Section hub codes used on the live site's area pages. A hub code matches
# every category in that section, mirroring craigslist (e.g. ?cat=ccc lists
# all community categories, ?cat=hhh all housing categories).
SECTION_HUB_CODES: dict[str, str] = {
    "ccc": "community",
    "hhh": "housing",
    "sss": "for-sale",
    "jjj": "jobs",
    "ggg": "gigs",
    "bbb": "services",
    "rrr": "resumes",
}


def _section_codes(section: str) -> list[str]:
    return [
        row["slug"]
        for row in categories(section=section)
        if row["slug"] not in SECTION_HUB_CODES
    ]


def search_postings(
    region_slug: str,
    *,
    category: str | None = None,
    query: str = "",
    min_price: int | None = None,
    max_price: int | None = None,
    postal: str = "",
    posted_today: bool = False,
    bedrooms: str = "",
    housing_type: str = "",
    posted_by: str = "",
    has_image: bool = False,
    sort: str = "newest",
    housing_only: bool = False,
    limit: int = 500,
) -> list[sqlite3.Row]:
    """Deterministic search over the seeded catalog.

    ``postal`` matches the neighborhood whose postal prefixes contain the
    given value, mirroring craigslist's 'search nearby areas by postal'
    behaviour. ``posted_today`` compares against the frozen business clock.
    """

    clauses = [
        "r.slug = ?",
        "p.status != 'removed'",
    ]
    params: list[Any] = [region_slug]
    section = SECTION_HUB_CODES.get(category or "")
    if section:
        codes = _section_codes(section)
        if codes:
            in_codes = ",".join(f"'{c}'" for c in codes)
            clauses.append(f"p.category_slug IN ({in_codes})")
        else:
            # Section with a single category that is also its own hub code
            # (e.g. resumes): fall back to exact match so the page is not empty.
            clauses.append("p.category_slug = ?")
            params.append(category)
    elif category:
        clauses.append("p.category_slug = ?")
        params.append(category)
    if housing_only:
        codes = ",".join(f"'{c}'" for c in (
            "apa", "swp", "hsw", "off", "prk", "rea", "roo", "sha", "sub", "vac"))
        clauses.append(f"p.category_slug IN ({codes})")
    if query:
        clauses.append(
            "(p.title LIKE ? OR p.description LIKE ? OR p.neighborhood LIKE ?)"
        )
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])
    if min_price is not None:
        clauses.append("p.price >= ?")
        params.append(min_price)
    if max_price is not None:
        clauses.append("p.price <= ?")
        params.append(max_price)
    if postal:
        prefixes = _postal_prefixes(postal)
        if prefixes:
            clauses.append("p.postal_code IS NOT NULL")
            like_clauses = " OR ".join(
                f"p.postal_code LIKE '{prefix}%'" for prefix in prefixes
            )
            clauses.append(f"({like_clauses})")
    if posted_today:
        today = now_datetime().date().isoformat()
        clauses.append("date(p.created_at) = ?")
        params.append(today)
    if bedrooms:
        clauses.append("p.bedrooms = ?")
        params.append(bedrooms)
    if housing_type:
        clauses.append("p.housing_type = ?")
        params.append(housing_type)
    if posted_by:
        clauses.append("p.posted_by = ?")
        params.append(posted_by)
    if has_image:
        clauses.append(
            "EXISTS (SELECT 1 FROM cl_posting_photos ph WHERE ph.posting_id = p.id)"
        )
    order = {
        "newest": "p.created_at DESC",
        "price-asc": "COALESCE(p.price, 0) ASC, p.created_at DESC",
        "price-desc": "COALESCE(p.price, 0) DESC, p.created_at DESC",
    }.get(sort, "p.created_at DESC")
    sql = (
        "SELECT p.*, r.slug AS region_slug FROM cl_postings p"
        " JOIN cl_regions r ON r.id = p.region_id"
        f" WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?"
    )
    params.append(limit)
    with closing(connect()) as connection:
        return connection.execute(sql, params).fetchall()


def _postal_prefixes(postal: str) -> list[str]:
    prefix = postal.strip().upper()
    if not prefix:
        return []
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT postal_prefixes FROM cl_neighborhoods"
        ).fetchall()
    for row in rows:
        candidates = [p.strip() for p in row["postal_prefixes"].split(",")]
        for candidate in candidates:
            if prefix.startswith(candidate) or candidate.startswith(prefix):
                return [candidate]
    return []


def neighborhood_label(postal: str) -> str | None:
    if not postal:
        return None
    with closing(connect()) as connection:
        for row in connection.execute(
            "SELECT name, postal_prefixes FROM cl_neighborhoods"
        ):
            candidates = [p.strip() for p in row["postal_prefixes"].split(",")]
            for candidate in candidates:
                if postal.upper().startswith(candidate):
                    return row["name"]
    return None


def favorite_ids(account_id: str) -> set[int]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT posting_id FROM cl_favorites WHERE account_id = ?",
            (account_id,),
        ).fetchall()
    return {int(row["posting_id"]) for row in rows}


def is_favorite(account_id: str, posting_id: int) -> bool:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT 1 FROM cl_favorites WHERE account_id = ? AND posting_id = ?",
            (account_id, posting_id),
        ).fetchone()
    return row is not None


def add_favorite(account_id: str, posting_id: int) -> None:
    with closing(connect()) as connection, connection:
        connection.execute(
            "INSERT OR IGNORE INTO cl_favorites (account_id, posting_id, created_at)"
            " VALUES (?, ?, ?)",
            (account_id, posting_id, now_utc()),
        )


def remove_favorite(account_id: str, posting_id: int) -> None:
    with closing(connect()) as connection, connection:
        connection.execute(
            "DELETE FROM cl_favorites WHERE account_id = ? AND posting_id = ?",
            (account_id, posting_id),
        )


def favorite_postings(account_id: str) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            """
            SELECT p.*, r.slug AS region_slug FROM cl_favorites f
            JOIN cl_postings p ON p.id = f.posting_id
            JOIN cl_regions r ON r.id = p.region_id
            WHERE f.account_id = ? AND p.status != 'removed'
            ORDER BY f.created_at DESC
            """,
            (account_id,),
        ).fetchall()


def saved_searches(account_id: str) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_saved_searches WHERE account_id = ? ORDER BY id DESC",
            (account_id,),
        ).fetchall()


def add_saved_search(account_id: str, name: str, query: dict[str, Any]) -> int:
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO cl_saved_searches (account_id, name, query_json, created_at)"
            " VALUES (?, ?, ?, ?)",
            (account_id, name, json.dumps(query, sort_keys=True), now_utc()),
        )
        return int(cursor.lastrowid)


def remove_saved_search(account_id: str, search_id: int) -> bool:
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM cl_saved_searches WHERE id = ? AND account_id = ?",
            (search_id, account_id),
        )
        return cursor.rowcount > 0


def add_reply(
    posting_id: int,
    *,
    name: str,
    email: str,
    phone: str,
    message: str,
    mail_id: str | None = None,
    recipient: str = "",
) -> int:
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO cl_reply_messages"
            " (posting_id, name, email, phone, message, created_at, mail_id, recipient)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (posting_id, name, email, phone, message, now_utc(), mail_id, recipient),
        )
        return int(cursor.lastrowid)


def add_flag(posting_id: int, reason: str, note: str) -> int:
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO cl_flags (posting_id, reason, note, created_at)"
            " VALUES (?, ?, ?, ?)",
            (posting_id, reason, note, now_utc()),
        )
        return int(cursor.lastrowid)


def postings_for_account(account_id: str) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            """
            SELECT p.*, r.slug AS region_slug FROM cl_postings p
            JOIN cl_regions r ON r.id = p.region_id
            WHERE p.account_id = ? ORDER BY p.created_at DESC
            """,
            (account_id,),
        ).fetchall()


def account_for_email(email: str) -> sqlite3.Row | None:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT account_id, display_name, email_normalized FROM local_auth_accounts"
            " WHERE email_normalized = ?",
            (email.strip().lower(),),
        ).fetchone()


def registration_event_check(email: str) -> str | None:
    """Return the rate-limit message if the email was used too recently."""

    normalized = email.strip().lower()
    if not _EMAIL_RE.match(normalized):
        return "Please enter a valid email address."
    window = registration_window_seconds()
    cutoff = now_datetime() - timedelta(seconds=window)
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT attempted_at FROM cl_registration_events"
            " WHERE email_normalized = ? ORDER BY attempted_at DESC LIMIT 1",
            (normalized,),
        ).fetchone()
    if row is not None:
        try:
            attempted = datetime.fromisoformat(row["attempted_at"])
        except ValueError:
            attempted = None
        if attempted is not None and attempted >= cutoff:
            return (
                "Registration is limited to once every five minutes per email "
                "address. Please try again later."
            )
    return None


def record_registration_event(email: str) -> None:
    normalized = email.strip().lower()
    with closing(connect()) as connection, connection:
        connection.execute(
            "INSERT INTO cl_registration_events (email_normalized, attempted_at)"
            " VALUES (?, ?)",
            (normalized, now_utc()),
        )


# ---------------------------------------------------------------------------
# posting CRUD + wizard drafts
# ---------------------------------------------------------------------------


def create_posting(
    account_id: str,
    *,
    region_id: int,
    category_slug: str,
    title: str,
    price: int,
    description: str,
    postal_code: str,
    neighborhood: str,
    housing_type: str,
    bedrooms: str,
    baths: str,
    square_feet: str,
    available_date: str,
    furnished: bool,
    laundry: str,
    parking: str,
    ac: str,
    posted_by: str,
    contact_email: str,
    contact_phone: str,
    contact_method: str,
    photos: list[str] | None = None,
) -> int:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120] or "posting"
    now = now_utc()
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO cl_postings ("
            " region_id, category_slug, title, price, description, postal_code,"
            " neighborhood, housing_type, bedrooms, baths, square_feet,"
            " available_date, furnished, laundry, parking, ac, posted_by,"
            " contact_email, contact_phone, contact_method, status, account_id,"
            " created_at, updated_at, slug"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                region_id,
                category_slug,
                title,
                price,
                description,
                postal_code,
                neighborhood,
                housing_type,
                bedrooms,
                baths,
                square_feet,
                available_date,
                1 if furnished else 0,
                laundry,
                parking,
                ac,
                posted_by,
                contact_email,
                contact_phone,
                contact_method,
                "published",
                account_id,
                now,
                now,
                slug,
            ),
        )
        posting_id = int(cursor.lastrowid)
        for position, filename in enumerate(photos or []):
            connection.execute(
                "INSERT INTO cl_posting_photos (posting_id, filename, position)"
                " VALUES (?, ?, ?)",
                (posting_id, filename, position),
            )
        return posting_id


def update_posting(
    posting_id: int,
    *,
    title: str,
    price: int,
    description: str,
    postal_code: str,
    neighborhood: str,
    housing_type: str,
    bedrooms: str,
    baths: str,
    square_feet: str,
    available_date: str,
    furnished: bool,
    laundry: str,
    parking: str,
    ac: str,
    posted_by: str,
    contact_email: str,
    contact_phone: str,
    contact_method: str,
) -> None:
    with closing(connect()) as connection, connection:
        connection.execute(
            "UPDATE cl_postings SET title=?, price=?, description=?, postal_code=?,"
            " neighborhood=?, housing_type=?, bedrooms=?, baths=?, square_feet=?,"
            " available_date=?, furnished=?, laundry=?, parking=?, ac=?, posted_by=?,"
            " contact_email=?, contact_phone=?, contact_method=?, updated_at=?"
            " WHERE id=?",
            (
                title,
                price,
                description,
                postal_code,
                neighborhood,
                housing_type,
                bedrooms,
                baths,
                square_feet,
                available_date,
                1 if furnished else 0,
                laundry,
                parking,
                ac,
                posted_by,
                contact_email,
                contact_phone,
                contact_method,
                now_utc(),
                posting_id,
            ),
        )


def renew_posting(posting_id: int) -> None:
    with closing(connect()) as connection, connection:
        connection.execute(
            "UPDATE cl_postings SET renewed_at=?, updated_at=? WHERE id=?",
            (now_utc(), now_utc(), posting_id),
        )


def repost_posting(
    posting_id: int,
    *,
    region_id: int,
    category_slug: str,
    account_id: str,
) -> int:
    original = get_posting(posting_id)
    if original is None:
        raise KeyError(posting_id)
    photos = [row["filename"] for row in posting_photos(posting_id)]
    return create_posting(
        account_id,
        region_id=region_id,
        category_slug=category_slug,
        title=original["title"],
        price=int(original["price"]),
        description=original["description"],
        postal_code=original["postal_code"] or "",
        neighborhood=original["neighborhood"] or "",
        housing_type=original["housing_type"] or "",
        bedrooms=original["bedrooms"] or "",
        baths=original["baths"] or "",
        square_feet=original["square_feet"] or "",
        available_date=original["available_date"] or "",
        furnished=bool(original["furnished"]),
        laundry=original["laundry"] or "",
        parking=original["parking"] or "",
        ac=original["ac"] or "",
        posted_by=original["posted_by"] or "owner",
        contact_email=original["contact_email"] or "",
        contact_phone=original["contact_phone"] or "",
        contact_method=original["contact_method"] or "email",
        photos=photos,
    )


def remove_posting(posting_id: int) -> None:
    with closing(connect()) as connection, connection:
        connection.execute(
            "UPDATE cl_postings SET status='removed', removed_at=?, updated_at=?"
            " WHERE id=?",
            (now_utc(), now_utc(), posting_id),
        )


# wizard drafts --------------------------------------------------------------


def get_draft(session_digest: str) -> sqlite3.Row | None:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_posting_drafts WHERE session_digest = ?",
            (session_digest,),
        ).fetchone()


def save_draft(session_digest: str, step: int, fields: dict[str, Any]) -> int:
    allowed = {
        "region_id", "category_slug", "title", "price", "description",
        "postal_code", "neighborhood", "housing_type", "bedrooms", "baths",
        "square_feet", "available_date", "furnished", "laundry", "parking",
        "ac", "posted_by", "contact_email", "contact_phone", "contact_method",
    }
    clean = {key: fields[key] for key in allowed if key in fields}
    current = get_draft(session_digest)
    with closing(connect()) as connection, connection:
        if current is None:
            columns = ", ".join(clean.keys())
            placeholders = ", ".join("?" for _ in clean)
            params = list(clean.values())
            cursor = connection.execute(
                f"INSERT INTO cl_posting_drafts"
                f" (session_digest, step, {columns}, updated_at)"
                f" VALUES (?, ?, {placeholders}, ?)",
                [session_digest, step, *params, now_utc()],
            )
            return int(cursor.lastrowid)
        if clean:
            assignments = ", ".join(f"{key}=?" for key in clean)
            connection.execute(
                f"UPDATE cl_posting_drafts SET step=?, {assignments}, updated_at=?"
                f" WHERE session_digest=?",
                [step, *clean.values(), now_utc(), session_digest],
            )
        else:
            connection.execute(
                "UPDATE cl_posting_drafts SET step=?, updated_at=?"
                " WHERE session_digest=?",
                (step, now_utc(), session_digest),
            )
        return int(current["id"])


def clear_draft(session_digest: str) -> None:
    with closing(connect()) as connection, connection:
        connection.execute(
            "DELETE FROM cl_posting_drafts WHERE session_digest = ?",
            (session_digest,),
        )


def draft_photos(draft_id: int) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_draft_photos WHERE draft_id = ? ORDER BY position, id",
            (draft_id,),
        ).fetchall()


def add_draft_photo(draft_id: int, filename: str) -> None:
    with closing(connect()) as connection, connection:
        connection.execute(
            "INSERT INTO cl_draft_photos (draft_id, filename, position)"
            " VALUES (?, ?, (SELECT COALESCE(MAX(position), -1) + 1 FROM"
            " cl_draft_photos WHERE draft_id = ?))",
            (draft_id, filename, draft_id),
        )


def reorder_draft_photos(draft_id: int, filenames: list[str]) -> None:
    with closing(connect()) as connection, connection:
        for position, filename in enumerate(filenames):
            connection.execute(
                "UPDATE cl_draft_photos SET position = ? WHERE draft_id = ?"
                " AND filename = ?",
                (position, draft_id, filename),
            )


def remove_draft_photo(draft_id: int, filename: str) -> bool:
    with closing(connect()) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM cl_draft_photos WHERE draft_id = ? AND filename = ?",
            (draft_id, filename),
        )
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# discussion forums
# ---------------------------------------------------------------------------


def forum_boards() -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_forum_boards ORDER BY name"
        ).fetchall()


def forum_board(slug: str) -> sqlite3.Row | None:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_forum_boards WHERE slug = ?", (slug,)
        ).fetchone()


def forum_posts(board_id: int, limit: int = 40) -> list[sqlite3.Row]:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_forum_posts WHERE board_id = ?"
            " ORDER BY posted_at DESC, id DESC LIMIT ?",
            (board_id, limit),
        ).fetchall()


def forum_post(post_id: int) -> sqlite3.Row | None:
    with closing(connect()) as connection:
        return connection.execute(
            "SELECT * FROM cl_forum_posts WHERE id = ?", (post_id,)
        ).fetchone()


def _load_forums() -> dict:
    """Load the scraped snapshot of the real craigslist discussion forums."""
    path = Path(__file__).resolve().parent / "forums.json"
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"boards": []}


FORUMS = _load_forums()


def _seed_forums(connection: sqlite3.Connection) -> None:
    """Insert the discussion-forum boards and their scraped threads.
    Idempotent: clears both forum tables first so re-seeding (e.g. the
    lifespan seed on an existing database) never duplicates rows."""
    connection.execute("DELETE FROM cl_forum_posts")
    connection.execute("DELETE FROM cl_forum_boards")
    for board in FORUMS.get("boards", []):
        slug = board.get("slug") or re.sub(r"[^a-z0-9]+", "-", board["name"].lower()).strip("-")
        cursor = connection.execute(
            "INSERT INTO cl_forum_boards"
            " (id, slug, name, forum_id, description, thread_count)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                board.get("board_seq", 0) + 1,
                slug,
                board["name"],
                board.get("forum_id", ""),
                board.get("description", ""),
                len(board.get("threads", [])),
            ),
        )
        board_db_id = int(cursor.lastrowid)
        for index, thread in enumerate(board.get("threads", [])):
            connection.execute(
                "INSERT INTO cl_forum_posts"
                " (board_id, thread_id, title, body, author, posted_at, parent_thread)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    board_db_id,
                    thread.get("thread_id", ""),
                    thread.get("title", ""),
                    thread.get("body", ""),
                    thread.get("author", ""),
                    thread.get("posted_at", FROZEN_CLOCK_UTC),
                    "",
                ),
            )


# Regions linked from the homepage "nearby cl" list that have no seeded
# postings. They render a region shell (real craigslist keeps these as area
# pages even when empty) instead of 404ing.
EXTRA_REGION_NAMES: dict[str, str] = {
    "abbotsford": "fraser valley, BC", "akroncanton": "akron / canton", "altoona": "altoona-johnstown",
    "ashtabula": "ashtabula", "atlanta": "atlanta", "austin": "austin", "barrie": "barrie, ON",
    "belleville": "belleville, ON", "binghamton": "binghamton", "boston": "boston",
    "brantford": "brantford, ON", "buffalo": "buffalo", "calgary": "calgary", "chatham": "chatham-kent, ON",
    "chautauqua": "chautauqua", "cleveland": "cleveland", "dallas": "dallas", "denver": "denver",
    "detroit": "detroit metro", "edmonton": "edmonton", "elmira": "elmira", "erie": "erie, PA",
    "fingerlakes": "finger lakes", "flint": "flint", "guelph": "guelph, ON", "halifax": "halifax",
    "hamilton": "hamilton", "houston": "houston", "ithaca": "ithaca", "kingston": "kingston, ON",
    "kitchener": "kitchener", "lasvegas": "las vegas", "londonon": "london, ON",
    "meadville": "meadville", "miami": "south florida", "minneapolis": "minneapolis",
    "niagara": "niagara region", "orangecounty": "orange co", "ottawa": "ottawa",
    "owensound": "owen sound", "pennstate": "state college", "peterborough": "peterborough",
    "philadelphia": "philadelphia", "phoenix": "phoenix", "pittsburgh": "pittsburgh",
    "porthuron": "port huron", "portland": "portland", "potsdam": "potsdam-massena",
    "raleigh": "raleigh", "rochester": "rochester, NY", "sacramento": "sacramento",
    "saginaw": "saginaw", "sandiego": "san diego", "sandusky": "sandusky", "sarnia": "sarnia",
    "sfbay": "SF bay area", "sudbury": "sudbury", "syracuse": "syracuse", "thumb": "the thumb",
    "twintiers": "twin tiers", "utica": "utica", "victoria": "victoria, BC",
    "washingtondc": "washington, DC", "watertown": "watertown", "williamsport": "williamsport",
    "windsor": "windsor", "winnipeg": "winnipeg", "youngstown": "youngstown",
}


def region_row_for_slug(slug: str) -> sqlite3.Row | None:
    """Region row for a real slug, or a shell row for known-but-empty
    nearby regions (never None for those)."""
    row = region_by_slug(slug)
    if row is not None:
        return row
    name = EXTRA_REGION_NAMES.get(slug)
    if name is None:
        return None
    return dict(id=0, slug=slug, name=name, country="")
