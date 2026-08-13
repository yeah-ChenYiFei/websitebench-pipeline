from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from websitebench.site_backend import (
    LifecycleError,
    PaymentError,
    RuntimeContractError,
    SiteBackend,
    SiteBindingError,
    load_runtime,
)

from .helpers import runtime_config


def _migration_hook(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS site_orders("
        "order_id INTEGER PRIMARY KEY,payload TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO site_orders(order_id,payload) VALUES (1,'seeded')"
    )


def _seed_hook(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS site_seed(marker TEXT PRIMARY KEY)"
    )
    connection.execute("INSERT INTO site_seed(marker) VALUES ('new-database')")


def test_runtime_contract_derives_host_only_site_cookie(tmp_path: Path) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    assert backend.session_cookie == {
        "name": "__Host-websitebench-alpha-session",
        "secure": True,
        "httponly": True,
        "samesite": "Lax",
        "path": "/",
    }
    assert "domain" not in backend.session_cookie


def test_runtime_contract_allows_explicitly_disabled_mail(tmp_path: Path) -> None:
    config = runtime_config()
    config["mail"] = {
        "enabled": False,
        "sender": {
            "display_name": "Alpha Clone",
            "address_env": "RESEND_FROM_EMAIL",
        },
        "purposes": {},
    }

    runtime = load_runtime(config)
    assert runtime.mail["enabled"] is False
    assert runtime.mail["purposes"] == {}

    config["mail"]["purposes"] = runtime_config()["mail"]["purposes"]
    with pytest.raises(RuntimeContractError, match="empty when mail is disabled"):
        load_runtime(config)


def test_runtime_contract_rejects_enabled_mail_without_purposes() -> None:
    config = runtime_config()
    config["mail"]["enabled"] = True
    config["mail"]["purposes"] = {}
    with pytest.raises(RuntimeContractError, match="non-empty object"):
        load_runtime(config)


def test_runtime_contract_can_disable_payments(tmp_path: Path) -> None:
    config = runtime_config()
    config["payments"]["enabled"] = False
    backend = SiteBackend.open(config, data_root=tmp_path)
    backend.lifecycle.initialize()
    with pytest.raises(RuntimeContractError, match="stripe_test must be null"):
        invalid = runtime_config(stripe=True)
        invalid["payments"]["enabled"] = False
        load_runtime(invalid)
    with pytest.raises(PaymentError, match="payments are not enabled"):
        backend.payments.create_intent(
            owner="account_alpha",
            amount_minor=100,
            currency="USD",
            fingerprint="a" * 64,
            idempotency_key="disabled-payment",
        )


def test_runtime_rejects_arbitrary_fields_live_profile_and_parent_domain_cookie() -> None:
    config = runtime_config()
    config["unknown"] = True
    with pytest.raises(RuntimeContractError, match="unknown fields"):
        load_runtime(config)

    config = runtime_config()
    config["session"]["domain"] = ".example.test"
    with pytest.raises(RuntimeContractError, match="unknown fields"):
        load_runtime(config)

    config = runtime_config(stripe=True)
    config["payments"]["default_adapter"] = "stripe-live"
    with pytest.raises(RuntimeContractError, match="default_adapter"):
        load_runtime(config)


def test_initialize_twice_is_idempotent_and_wrong_site_open_fails_closed(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    alpha = SiteBackend.open(runtime_config("alpha"), data_root=shared)
    first = alpha.lifecycle.initialize()
    second = alpha.lifecycle.initialize()
    assert first["status"] == second["status"] == "ok"

    beta_config = runtime_config("beta", "Beta Clone")
    beta_config["database"]["filename"] = "alpha.sqlite3"
    with pytest.raises(SiteBindingError, match="belongs to site"):
        SiteBackend.open(beta_config, data_root=shared)


def test_unbound_legacy_database_requires_contract_and_explicit_authorization(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "legacy"
    data_root.mkdir()
    database = data_root / "alpha.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE legacy_orders(id INTEGER PRIMARY KEY)")

    with pytest.raises(SiteBindingError, match="no site binding"):
        SiteBackend.open(
            runtime_config("alpha"),
            data_root=data_root,
        )
    backend = SiteBackend.open(
        runtime_config("alpha", legacy_unbound_migration=True),
        data_root=data_root,
    )
    assert backend.lifecycle.health()["status"] == "legacy-unbound"
    with pytest.raises(SiteBindingError, match="explicit migration authorization"):
        backend.lifecycle.initialize()
    assert (
        backend.lifecycle.initialize(authorize_legacy_binding=True)["status"] == "ok"
    )


def test_deferred_legacy_migration_must_repair_before_health(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "legacy-repair"
    data_root.mkdir()
    database = data_root / "alpha.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child("
            "id INTEGER PRIMARY KEY,parent_id INTEGER NOT NULL REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO child(id,parent_id) VALUES (1,404)")

    backend = SiteBackend.open(
        runtime_config("alpha", legacy_unbound_migration=True),
        data_root=data_root,
    )
    with pytest.raises(LifecycleError, match="foreign-key"):
        backend.lifecycle.initialize(authorize_legacy_binding=True)

    prepared = backend.lifecycle.prepare_legacy_migration()
    assert prepared["status"] == "legacy-migration-required"
    with pytest.raises(LifecycleError, match="foreign-key"):
        backend.lifecycle.health()
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM child")
    assert backend.lifecycle.health()["status"] == "ok"

    ordinary = SiteBackend.open(
        runtime_config("ordinary"),
        data_root=tmp_path / "ordinary",
    )
    with pytest.raises(LifecycleError, match="does not authorize"):
        ordinary.lifecycle.prepare_legacy_migration()


def test_bound_site_can_repair_before_post_migration_integrity(
    tmp_path: Path,
) -> None:
    value = SiteBackend.open(
        runtime_config("alpha"),
        data_root=tmp_path / "bound-repair",
    )
    value.lifecycle.initialize()
    with sqlite3.connect(value.lifecycle.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child("
            "id INTEGER PRIMARY KEY,parent_id INTEGER NOT NULL REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO child(id,parent_id) VALUES (1,404)")

    with pytest.raises(LifecycleError, match="foreign-key"):
        value.lifecycle.initialize()
    assert (
        value.lifecycle.prepare_bound_site_migration()["status"]
        == "site-migration-required"
    )
    with sqlite3.connect(value.lifecycle.database_path) as connection:
        connection.execute("DELETE FROM child")
    assert value.lifecycle.health()["status"] == "ok"

    unbound_root = tmp_path / "unbound-repair"
    unbound_root.mkdir()
    with sqlite3.connect(unbound_root / "alpha.sqlite3") as connection:
        connection.execute("CREATE TABLE legacy(id INTEGER PRIMARY KEY)")
    unbound = SiteBackend.open(
        runtime_config("alpha", legacy_unbound_migration=True),
        data_root=unbound_root,
    )
    with pytest.raises(SiteBindingError, match="not initialized"):
        unbound.lifecycle.prepare_bound_site_migration()


def test_backup_restore_integrity_and_cross_site_restore_rejection(
    tmp_path: Path,
) -> None:
    alpha = SiteBackend.open(runtime_config("alpha"), data_root=tmp_path / "alpha")
    alpha.lifecycle.initialize()
    backup = alpha.lifecycle.backup(tmp_path / "backups" / "alpha.sqlite3")
    assert backup["integrity_check"] == "ok"
    assert Path(backup["report"]).is_file()

    beta = SiteBackend.open(runtime_config("beta", "Beta"), data_root=tmp_path / "beta")
    beta.lifecycle.initialize()
    with pytest.raises(SiteBindingError, match="belongs to site"):
        beta.lifecycle.restore(Path(backup["path"]))

    alpha.lifecycle.reset(confirm_site_id="alpha")
    assert alpha.lifecycle.restore(Path(backup["path"]))["status"] == "ok"
    with pytest.raises(LifecycleError, match="confirmation"):
        alpha.lifecycle.reset(confirm_site_id="beta")


def test_runtime_file_sets_site_root_and_safe_database_location(tmp_path: Path) -> None:
    runtime_path = tmp_path / "site" / "backend" / "runtime.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(json.dumps(runtime_config()), encoding="utf-8")
    backend = SiteBackend.open(runtime_path)
    backend.lifecycle.initialize()
    assert backend.lifecycle.database_path == (
        tmp_path / "site" / "data" / "alpha.sqlite3"
    ).resolve()
    with pytest.raises(LifecycleError, match="cannot override"):
        SiteBackend.open(runtime_path, data_root=tmp_path / "elsewhere")


def test_database_path_rejects_intermediate_link_or_junction(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory links are unavailable: {exc}")
    with pytest.raises(LifecycleError, match="link/reparse"):
        SiteBackend.open(runtime_config(), data_root=linked / "nested")


def test_declared_hooks_are_exactly_bound_and_run_once(tmp_path: Path) -> None:
    config = runtime_config()
    config["database"]["migration_hook"] = (
        f"{_migration_hook.__module__}:{_migration_hook.__name__}"
    )
    config["database"]["seed_hook"] = (
        f"{_seed_hook.__module__}:{_seed_hook.__name__}"
    )
    with pytest.raises(LifecycleError, match="no callable"):
        SiteBackend.open(config, data_root=tmp_path)

    backend = SiteBackend.open(
        config,
        data_root=tmp_path,
        migration_hook=_migration_hook,
        seed_hook=_seed_hook,
    )
    backend.lifecycle.initialize()
    backend.lifecycle.initialize()
    with backend.lifecycle.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM site_orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM site_seed").fetchone()[0] == 1
        applied = connection.execute(
            "SELECT COUNT(*) FROM websitebench_backend_migrations "
            "WHERE migration_id LIKE 'site-%:%'"
        ).fetchone()[0]
    assert applied == 2


def test_restore_runs_current_migration_but_never_reseeds(tmp_path: Path) -> None:
    original = SiteBackend.open(
        runtime_config(), data_root=tmp_path / "original"
    )
    original.lifecycle.initialize()
    backup = original.lifecycle.backup(tmp_path / "backups" / "alpha.sqlite3")

    upgraded_config = runtime_config()
    upgraded_config["database"]["migration_hook"] = (
        f"{_migration_hook.__module__}:{_migration_hook.__name__}"
    )
    upgraded_config["database"]["seed_hook"] = (
        f"{_seed_hook.__module__}:{_seed_hook.__name__}"
    )
    upgraded = SiteBackend.open(
        upgraded_config,
        data_root=tmp_path / "upgraded",
        migration_hook=_migration_hook,
        seed_hook=_seed_hook,
    )
    upgraded.lifecycle.initialize()
    upgraded.lifecycle.restore(Path(backup["path"]))
    with upgraded.lifecycle.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM site_orders").fetchone()[0] == 1
        seed_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='site_seed'"
        ).fetchone()
    assert seed_table is None


def test_restore_removes_previous_wal_sidecars(tmp_path: Path) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path / "site")
    backend.lifecycle.initialize()
    backup = backend.lifecycle.backup(tmp_path / "backups" / "alpha.sqlite3")
    wal = Path(f"{backend.lifecycle.database_path}-wal")
    shm = Path(f"{backend.lifecycle.database_path}-shm")
    wal.write_bytes(b"stale-wal")
    shm.write_bytes(b"stale-shm")
    assert backend.lifecycle.restore(Path(backup["path"]))["status"] == "ok"
    assert not wal.exists()
    assert not shm.exists()


def test_embedded_reset_clears_common_state_but_preserves_binding(
    tmp_path: Path,
) -> None:
    backend = SiteBackend.open(runtime_config(), data_root=tmp_path)
    backend.lifecycle.initialize()
    fingerprint = "a" * 64
    flow = backend.payments.create_intent(
        owner="account:1",
        amount_minor=100,
        currency="USD",
        fingerprint=fingerprint,
        idempotency_key="flow:embedded-reset",
    )
    backend.payments.attempt(
        flow_id=flow["flow_id"],
        owner="account:1",
        amount_minor=100,
        currency="USD",
        fingerprint=fingerprint,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:embedded-reset",
    )
    with backend.lifecycle.connection(transaction=True) as connection:
        with pytest.raises(LifecycleError, match="confirmation"):
            backend.lifecycle.reset_embedded(
                connection, confirm_site_id="another-site"
            )
        backend.lifecycle.reset_embedded(connection, confirm_site_id="alpha")
    health = backend.lifecycle.health()
    assert health["database_bound"] is True
    assert health["counts"]["websitebench_payment_flows"] == 0
    assert health["counts"]["websitebench_payment_events"] == 0
