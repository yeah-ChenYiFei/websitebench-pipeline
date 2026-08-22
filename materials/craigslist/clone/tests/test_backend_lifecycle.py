"""Lifecycle proofs for the site-bound database and deterministic reset."""

from __future__ import annotations

from contextlib import closing

import pytest

from backend import craigslist_db


@pytest.fixture(autouse=True)
def _isolated_database():
    craigslist_db.reset()
    yield
    craigslist_db.reset()


def test_database_path_and_migrations_are_site_bound_and_idempotent() -> None:
    path = craigslist_db.database_path()
    assert path.name == "craigslist.sqlite3"
    with closing(craigslist_db.connect()) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        migrations = connection.execute(
            "SELECT migration_id, applied_at FROM craigslist_schema_migrations"
            " ORDER BY migration_id"
        ).fetchall()
    assert [row[0] for row in migrations] == sorted(
        (row[0] for row in migrations), key=lambda value: value
    )
    assert migrations  # at least the business migrations ran
    # re-running the schema builder is a no-op
    craigslist_db._ensure_business_schema(path)
    with closing(craigslist_db.connect()) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_seed_is_deterministic() -> None:
    def snapshot() -> list[tuple]:
        with closing(craigslist_db.connect()) as connection:
            return [
                tuple(row)
                for row in connection.execute(
                    "SELECT id, title, price, neighborhood, status FROM cl_postings"
                    " ORDER BY id"
                )
            ]

    first = snapshot()
    craigslist_db.reset()
    second = snapshot()
    assert first == second
    assert len(first) >= 20  # housing catalog plus a small for-sale set


def test_canonical_sublet_fixture_exists() -> None:
    posting = craigslist_db.get_posting(1000001)
    assert posting is not None
    assert posting["title"] == "1BR near Annex - furnished sublet Jul-Aug"
    assert int(posting["price"]) == 2400
    assert posting["neighborhood"] == "annex"
    assert posting["furnished"] == 1
    assert posting["available_date"] == "2026-07-01"
    # seeded postings carry neighborhood photo assets like the real site
    photos = craigslist_db.posting_photos(1000001)
    assert len(photos) >= 1
    assert photos[0]["filename"].endswith(".svg")


def test_reset_is_idempotent_and_restores_seed() -> None:
    craigslist_db.reset()
    craigslist_db.reset()
    with closing(craigslist_db.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cl_regions").fetchone()[0] == 9
        assert connection.execute("SELECT COUNT(*) FROM cl_categories").fetchone()[0] >= 16


def test_posting_crud_restart_persistence() -> None:
    # Create a posting, then simulate a "restart" by re-opening services (the
    # same SQLite file) and confirm the row survives.
    posting_id = craigslist_db.create_posting(
        "account_x",
        region_id=1,
        category_slug="sub",
        title="Restart-proof sublet",
        price=1999,
        description="Persists across restarts.",
        postal_code="M6G",
        neighborhood="annex",
        housing_type="sublet",
        bedrooms="1br",
        baths="1",
        square_feet="600",
        available_date="2026-08-01",
        furnished=True,
        laundry="in-unit",
        parking="none",
        ac="none",
        posted_by="owner",
        contact_email="poster@example.com",
        contact_phone="",
        contact_method="email",
    )
    craigslist_db.close_services()
    reloaded = craigslist_db.get_posting(posting_id)
    assert reloaded is not None
    assert reloaded["title"] == "Restart-proof sublet"
    craigslist_db.renew_posting(posting_id)
    assert craigslist_db.get_posting(posting_id)["renewed_at"] is not None
