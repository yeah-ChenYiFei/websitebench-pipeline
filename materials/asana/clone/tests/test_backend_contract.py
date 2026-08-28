from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from websitebench.site_backend import SiteBackend


RUNTIME_PATH = Path(__file__).resolve().parents[2] / "backend" / "runtime.json"


def _open_isolated(root: Path) -> SiteBackend:
    runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    backend = SiteBackend.open(runtime, data_root=root)
    backend.lifecycle.initialize()
    with backend.lifecycle.connection() as connection:
        mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0])
    assert mode.casefold() == "wal"
    return backend


def test_backend_data_location_binding_and_migration(tmp_path: Path) -> None:
    backend = _open_isolated(tmp_path / "site-data")
    assert backend.config.site_id == "asana"
    assert backend.lifecycle.database_path == (
        tmp_path / "site-data" / "asana.sqlite3"
    )
    with backend.lifecycle.connection() as connection:
        binding = connection.execute(
            "SELECT site_id FROM websitebench_site_binding WHERE singleton=1"
        ).fetchone()[0]
        migrations = {
            row[0]
            for row in connection.execute(
                "SELECT migration_id FROM websitebench_backend_migrations"
            )
        }
    assert binding == "asana"
    assert "site-backend-v1" in migrations


def test_backend_reset_is_deterministic_and_site_bound(tmp_path: Path) -> None:
    backend = _open_isolated(tmp_path / "site-data")
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute("CREATE TABLE proof_rows(value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof_rows(value) VALUES ('mutable')")

    report = backend.lifecycle.reset(confirm_site_id="asana")
    assert report["status"] == "ok"
    with backend.lifecycle.connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='proof_rows'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT site_id FROM websitebench_site_binding WHERE singleton=1"
        ).fetchone()[0] == "asana"


def test_backend_restart_persistence_and_backup_restore(tmp_path: Path) -> None:
    data_root = tmp_path / "site-data"
    backend = _open_isolated(data_root)
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute("CREATE TABLE proof_rows(value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof_rows(value) VALUES ('before')")

    restarted = _open_isolated(data_root)
    with restarted.lifecycle.connection() as connection:
        assert connection.execute("SELECT value FROM proof_rows").fetchone()[0] == "before"

    backup_path = tmp_path / "backup" / "asana.sqlite3"
    report = restarted.lifecycle.backup(backup_path)
    assert report["site_id"] == "asana"
    assert report["integrity_check"] == "ok"
    with restarted.lifecycle.connection(transaction=True) as connection:
        connection.execute("UPDATE proof_rows SET value='after'")
    restarted.lifecycle.restore(backup_path)
    with restarted.lifecycle.connection() as connection:
        assert connection.execute("SELECT value FROM proof_rows").fetchone()[0] == "before"


def test_backend_wal_concurrency_serializes_writers(tmp_path: Path) -> None:
    backend = _open_isolated(tmp_path / "site-data")
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "CREATE TABLE proof_rows(writer INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )

    def write_row(writer: int) -> None:
        with backend.lifecycle.connection(transaction=True) as connection:
            connection.execute(
                "INSERT INTO proof_rows(writer,value) VALUES (?,?)",
                (writer, f"writer-{writer}"),
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write_row, range(12)))
    with backend.lifecycle.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM proof_rows").fetchone()[0] == 12
