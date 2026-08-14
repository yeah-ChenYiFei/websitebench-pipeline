"""Lifecycle proofs for the site-bound quote database."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from backend import quotes_db


PET = {
    "species": "cat",
    "name": "Willow",
    "age_label": "2 Years",
    "gender": "Female",
    "breed": "Domestic Shorthair",
}


@pytest.fixture(autouse=True)
def _isolated_database():
    quotes_db.reset()
    yield
    quotes_db.reset()


def _create(index: int = 0) -> dict[str, object]:
    return quotes_db.create_quote(
        {**PET, "name": f"Willow {index}"},
        f"willow-{index}@example.com",
        "44301",
    )


def _business_counts() -> tuple[int, int, int, int]:
    with closing(quotes_db.connect()) as connection:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "aspca_quotes",
                "aspca_pets",
                "aspca_selections",
                "aspca_enrollments",
            )
        )


def test_database_path_and_migrations_are_site_bound_and_idempotent() -> None:
    path = quotes_db.database_path()
    assert path.name == "aspca-pet-insurance.sqlite3"
    with closing(quotes_db.connect()) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        migrations = connection.execute(
            "SELECT migration_id, applied_at FROM aspca_schema_migrations"
            " ORDER BY migration_id"
        ).fetchall()
    assert [row[0] for row in migrations] == [
        "0001_quotes_core",
        "0002_selections",
        "0003_enrollments",
        "0004_payment_enrollment",
        "0005_quote_application",
        "0006_member_center",
    ]
    assert {row[1] for row in migrations} == {quotes_db.FROZEN_CLOCK_UTC}

    quotes_db.close_services()
    assert quotes_db.database_path() == path
    with closing(quotes_db.connect()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM aspca_schema_migrations"
        ).fetchone()[0] == 6


def test_reset_is_deterministic_and_preserves_the_schema() -> None:
    quote = _create()
    assert quote["quote_id"] == "WB100001"
    quotes_db.reset()
    first = _business_counts()
    quotes_db.reset()
    second = _business_counts()
    assert first == second == (0, 0, 0, 0)
    assert _create()["quote_id"] == "WB100001"


def test_quote_state_survives_service_restart() -> None:
    quote_id = _create()["quote_id"]
    enrolled = quotes_db.enroll(
        str(quote_id),
        {"email": "willow-0@example.com"},
        "Monthly",
        True,
        True,
        "sandbox-approved",
    )
    assert enrolled is not None
    quotes_db.close_services()
    restored = quotes_db.get_quote(str(quote_id))
    assert restored is not None
    assert restored["pets"][0]["name"] == "Willow 0"
    assert restored["enrollment"]["policy_number"] == "APH-000001"
    assert restored["enrollment"]["payment"]["amount_minor"] == 1674
    with closing(quotes_db.connect()) as connection:
        assert connection.execute(
            "SELECT status FROM websitebench_payment_flows"
        ).fetchone()[0] == "CONSUMED"
        assert connection.execute(
            "SELECT status FROM websitebench_mail_jobs"
        ).fetchone()[0] == "LOCAL_SIMULATION"


def test_site_backend_backup_is_complete_and_readable(tmp_path) -> None:
    quote_id = _create()["quote_id"]
    enrolled = quotes_db.enroll(
        str(quote_id),
        {"email": "willow-0@example.com"},
        "Monthly",
        True,
        False,
        "sandbox-approved",
    )
    assert enrolled is not None
    backend, _auth = quotes_db.services()
    destination = tmp_path / "aspca-backup.sqlite3"
    report = backend.lifecycle.backup(destination)
    assert report["schema_version"] == "websitebench.site-backend-backup.v1"
    with closing(sqlite3.connect(destination)) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute(
            "SELECT quote_number FROM aspca_quotes"
        ).fetchone()[0] == quote_id
        assert restored.execute(
            "SELECT site_id FROM websitebench_site_binding WHERE singleton = 1"
        ).fetchone()[0] == "aspca-pet-insurance"
        assert restored.execute(
            "SELECT site_id FROM websitebench_payment_flows"
        ).fetchone()[0] == "aspca-pet-insurance"
        assert restored.execute(
            "SELECT site_id,status FROM websitebench_mail_jobs"
        ).fetchone() == ("aspca-pet-insurance", "LOCAL_SIMULATION")
        assert restored.execute(
            "SELECT payment_flow_id,mail_id FROM aspca_enrollments"
        ).fetchone() == (
            enrolled["payment"]["flow_id"],
            enrolled["mail"]["mail_id"],
        )


def test_concurrent_quote_creation_is_isolated_and_lossless() -> None:
    with ThreadPoolExecutor(max_workers=4) as executor:
        quotes = list(executor.map(_create, range(8)))
    quote_ids = {str(quote["quote_id"]) for quote in quotes}
    assert len(quote_ids) == 8
    assert _business_counts() == (8, 8, 8, 0)
