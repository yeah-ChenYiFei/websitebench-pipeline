from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from websitebench.local_clone_auth import (
    AuthConflict,
    AuthExpired,
    AuthLocked,
    AuthRateLimited,
    AuthRejected,
    LocalAuthStore,
)
from websitebench.site_backend import (
    PaymentConflict,
    PaymentRejected,
    SiteBackend,
    SiteBindingError,
)


SITE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = SITE_ROOT / "backend" / "runtime.json"
REVIEW_ROOT = Path(
    os.environ.get(
        "WEBSITEBENCH_REVIEW_ARTIFACT_DIR",
        "/home/user/xuehw/.cache/review/blinkist",
    )
)


def case_dir(label: str) -> Path:
    path = REVIEW_ROOT / "pytest-lifecycle" / f"{label}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def runtime(site_id: str = "blinkist") -> dict:
    value = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    value["site"]["id"] = site_id
    value["site"]["label"] = site_id.title()
    value["site"]["public_origin"] = f"https://{site_id}.offline.invalid"
    return value


def services(path: Path, *, site_id: str = "blinkist") -> tuple[SiteBackend, LocalAuthStore]:
    backend = SiteBackend.open(runtime(site_id), data_root=path)
    backend.lifecycle.initialize()
    auth = LocalAuthStore(
        backend.lifecycle.database_path,
        site_id=site_id,
    )
    auth.ensure_schema()
    return backend, auth


def seed_account(auth: LocalAuthStore, suffix: str = "reader") -> str:
    return auth.seed_account(
        subject_id=f"synthetic-{suffix}",
        email=f"{suffix}@example.invalid",
        display_name="Synthetic Reader",
        password="Local-fixture-pass-2026",
    )


def install_business_owner_guard(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS blinkist_favorites (
                owner TEXT NOT NULL,
                slug TEXT NOT NULL,
                PRIMARY KEY(owner, slug)
            );
            CREATE TABLE IF NOT EXISTS blinkist_subscriptions (
                owner TEXT PRIMARY KEY,
                plan TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS blinkist_favorites_owner_insert_guard
            BEFORE INSERT ON blinkist_favorites
            WHEN NOT EXISTS (
                SELECT 1 FROM local_auth_accounts
                WHERE 'account:' || account_id = NEW.owner
            )
            BEGIN
                SELECT RAISE(ABORT, 'business owner is unavailable');
            END;
            """
        )


def normalized_seed_snapshot(auth: LocalAuthStore) -> dict:
    with auth.connect() as connection:
        accounts = [
            tuple(row)
            for row in connection.execute(
                "SELECT subject_id,email_normalized,display_name,email_verified "
                "FROM local_auth_accounts ORDER BY subject_id"
            )
        ]
        markers = [
            tuple(row)
            for row in connection.execute(
                "SELECT marker,value FROM blinkist_seed_markers ORDER BY marker"
            )
        ]
    return {"accounts": accounts, "markers": markers}


def test_deterministic_reset_recreates_the_same_normalized_seed_twice() -> None:
    _, auth = services(case_dir("reset"))
    seed = {
        "subject_id": "synthetic-reset-reader",
        "email": "reset-reader@example.invalid",
        "display_name": "Reset Reader",
        "password": "Local-reset-pass-2026",
    }

    def site_reset(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS blinkist_seed_markers "
            "(marker TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        connection.execute("DELETE FROM blinkist_seed_markers")
        connection.execute(
            "INSERT INTO blinkist_seed_markers(marker,value) VALUES (?,?)",
            ("catalog", "200"),
        )

    snapshots = []
    for _ in range(2):
        auth.reset_site_state(site_reset=site_reset, seed_accounts=[seed])
        snapshots.append(normalized_seed_snapshot(auth))

    assert snapshots[0] == snapshots[1]


def test_restart_persists_account_business_state_and_revocation() -> None:
    path = case_dir("restart")
    backend, auth = services(path)
    account_id = seed_account(auth, "restart-reader")
    install_business_owner_guard(backend.lifecycle.database_path)
    anonymous = auth.create_anonymous_session()
    signed_in = auth.sign_in(
        anonymous,
        email="restart-reader@example.invalid",
        password="Local-fixture-pass-2026",
    )["session_token"]
    owner = f"account:{account_id}"
    with closing(sqlite3.connect(backend.lifecycle.database_path)) as connection:
        connection.execute(
            "INSERT INTO blinkist_favorites(owner,slug) VALUES (?,?)",
            (owner, "atomic-habits"),
        )
        connection.execute(
            "INSERT INTO blinkist_subscriptions(owner,plan,status) VALUES (?,?,?)",
            (owner, "premium-annual", "active"),
        )
        connection.commit()

    restarted_backend, restarted_auth = services(path)
    assert restarted_auth.resolve_session(signed_in)["authenticated"] is True
    with closing(sqlite3.connect(restarted_backend.lifecycle.database_path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM blinkist_favorites WHERE owner=?", (owner,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM blinkist_subscriptions WHERE owner=?", (owner,)
        ).fetchone()[0] == "active"

    restarted_auth.sign_out(signed_in)
    _, second_restart_auth = services(path)
    assert second_restart_auth.resolve_session(signed_in) is None


def test_initialization_and_migration_replay_are_idempotent_and_foreign_db_fails_closed() -> None:
    path = case_dir("migration")
    backend, auth = services(path)
    first = backend.lifecycle.initialize()
    auth.ensure_schema()
    second = backend.lifecycle.initialize()
    replayed_auth = LocalAuthStore(backend.lifecycle.database_path, site_id="blinkist")
    replayed_auth.ensure_schema()

    assert first["status"] == second["status"] == "ok"
    with closing(sqlite3.connect(backend.lifecycle.database_path)) as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM local_auth_schema_migrations ORDER BY version"
            )
        ]
        assert versions == sorted(set(versions))
        assert {"0001", "0002"} <= set(versions)

    with pytest.raises(SiteBindingError):
        SiteBackend.open(runtime("foreign-site"), data_root=path)


def test_backup_restore_round_trip_and_foreign_backup_rejection() -> None:
    path = case_dir("backup")
    backend, auth = services(path / "live")
    account_id = seed_account(auth, "backup-reader")
    install_business_owner_guard(backend.lifecycle.database_path)
    owner = f"account:{account_id}"
    with closing(sqlite3.connect(backend.lifecycle.database_path)) as connection:
        connection.execute(
            "INSERT INTO blinkist_favorites(owner,slug) VALUES (?,?)",
            (owner, "atomic-habits"),
        )
        connection.commit()

    backup_path = path / "backups" / "blinkist.sqlite3"
    backend.lifecycle.backup(backup_path)
    with closing(sqlite3.connect(backend.lifecycle.database_path)) as connection:
        connection.execute("DELETE FROM blinkist_favorites")
        connection.commit()
    backend.lifecycle.restore(backup_path)
    with closing(sqlite3.connect(backend.lifecycle.database_path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM blinkist_favorites WHERE owner=?", (owner,)
        ).fetchone()[0] == 1

    foreign_backend, _ = services(path / "foreign", site_id="foreign-site")
    foreign_backup = path / "foreign-backup" / "blinkist.sqlite3"
    foreign_backend.lifecycle.backup(foreign_backup)
    with pytest.raises(SiteBindingError):
        backend.lifecycle.restore(foreign_backup)


@pytest.mark.parametrize(
    ("scenario", "expected"),
    (
        ("sandbox-approved", "APPROVED"),
        ("sandbox-declined", "DECLINED"),
        ("sandbox-retry", "RETRYABLE"),
    ),
)
def test_payment_sandbox_outcomes_and_duplicate_attempts(
    scenario: str, expected: str
) -> None:
    backend, _ = services(case_dir(f"payment-{scenario}"))
    owner = "account:synthetic-payment-reader"
    fingerprint = hashlib.sha256(b"synthetic-premium-annual").hexdigest()
    flow = backend.payments.create_intent(
        owner=owner,
        amount_minor=9999,
        currency="USD",
        fingerprint=fingerprint,
        idempotency_key=f"create-{scenario}-2026",
    )
    kwargs = {
        "flow_id": flow["flow_id"],
        "owner": owner,
        "amount_minor": 9999,
        "currency": "USD",
        "fingerprint": fingerprint,
        "scenario_id": scenario,
        "idempotency_key": f"attempt-{scenario}-2026",
    }
    first = backend.payments.attempt(**kwargs)
    second = backend.payments.attempt(**kwargs)

    assert first["status"] == expected
    assert second["attempt_id"] == first["attempt_id"]


def test_payment_rejects_forged_stale_foreign_invalid_and_conflicting_facts() -> None:
    backend, _ = services(case_dir("payment-boundaries"))
    owner = "account:synthetic-payment-owner"
    fingerprint = hashlib.sha256(b"premium-annual-owner").hexdigest()
    stale = hashlib.sha256(b"stale-premium-fingerprint").hexdigest()
    flow = backend.payments.create_intent(
        owner=owner,
        amount_minor=9999,
        currency="USD",
        fingerprint=fingerprint,
        idempotency_key="create-boundary-2026",
    )
    base = {
        "flow_id": flow["flow_id"],
        "owner": owner,
        "amount_minor": 9999,
        "currency": "USD",
        "fingerprint": fingerprint,
        "scenario_id": "sandbox-approved",
        "idempotency_key": "attempt-boundary-2026",
    }

    with pytest.raises(PaymentRejected):
        backend.payments.attempt(**{**base, "amount_minor": 1})
    with pytest.raises(PaymentRejected):
        backend.payments.attempt(**{**base, "fingerprint": stale})
    with pytest.raises(PaymentRejected):
        backend.payments.attempt(
            **{**base, "owner": "account:synthetic-foreign-owner"}
        )
    with pytest.raises(PaymentRejected):
        backend.payments.attempt(**{**base, "scenario_id": "not-a-scenario"})

    approved = backend.payments.attempt(**base)
    assert approved["status"] == "APPROVED"
    with pytest.raises(PaymentConflict):
        backend.payments.attempt(
            **{**base, "scenario_id": "sandbox-declined"}
        )
    with backend.lifecycle.connection(transaction=True) as connection:
        with pytest.raises(PaymentRejected):
            backend.payments.consume_approval(
                connection,
                flow_id=flow["flow_id"],
                owner=owner,
                amount_minor=9999,
                currency="USD",
                fingerprint=stale,
            )


def test_duplicate_payment_attempt_is_safe_under_concurrency() -> None:
    backend, _ = services(case_dir("payment-concurrency"))
    owner = "account:synthetic-concurrent-owner"
    fingerprint = hashlib.sha256(b"concurrent-payment").hexdigest()
    flow = backend.payments.create_intent(
        owner=owner,
        amount_minor=9999,
        currency="USD",
        fingerprint=fingerprint,
        idempotency_key="create-concurrent-2026",
    )

    def attempt() -> str:
        return backend.payments.attempt(
            flow_id=flow["flow_id"],
            owner=owner,
            amount_minor=9999,
            currency="USD",
            fingerprint=fingerprint,
            scenario_id="sandbox-declined",
            idempotency_key="attempt-concurrent-2026",
        )["attempt_id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempt_ids = list(executor.map(lambda _: attempt(), range(2)))

    assert len(set(attempt_ids)) == 1


def test_duplicate_registration_is_serialized_under_concurrency() -> None:
    _, auth = services(case_dir("registration-concurrency"))
    sessions = [auth.create_anonymous_session() for _ in range(2)]

    def start(session: str) -> str:
        try:
            auth.start_registration(
                session,
                email="concurrent-reader@example.invalid",
                display_name="Concurrent Reader",
                password="Local-concurrent-pass-2026",
            )
            return "accepted"
        except (AuthConflict, AuthRateLimited):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(start, sessions))

    assert results.count("accepted") == 1
    with auth.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM local_auth_registration_flows "
            "WHERE email_normalized=?",
            ("concurrent-reader@example.invalid",),
        ).fetchone()[0] == 1


def test_favorite_uniqueness_and_account_delete_race_leave_no_orphan() -> None:
    backend, auth = services(case_dir("owner-concurrency"))
    account_id = seed_account(auth, "owner-race-reader")
    install_business_owner_guard(backend.lifecycle.database_path)
    owner = f"account:{account_id}"

    def insert_favorite() -> str:
        try:
            with closing(sqlite3.connect(backend.lifecycle.database_path, timeout=10)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR IGNORE INTO blinkist_favorites(owner,slug) VALUES (?,?)",
                    (owner, "atomic-habits"),
                )
                connection.commit()
            return "inserted"
        except sqlite3.IntegrityError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: insert_favorite(), range(2)))
    with closing(sqlite3.connect(backend.lifecycle.database_path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM blinkist_favorites WHERE owner=?", (owner,)
        ).fetchone()[0] == 1

    def delete_account() -> None:
        with closing(sqlite3.connect(backend.lifecycle.database_path, timeout=10)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM blinkist_favorites WHERE owner=?", (owner,))
            connection.execute(
                "DELETE FROM local_auth_accounts WHERE account_id=?", (account_id,)
            )
            connection.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(delete_account), executor.submit(insert_favorite)]
        for future in futures:
            future.result()

    with closing(sqlite3.connect(backend.lifecycle.database_path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM local_auth_accounts WHERE account_id=?", (account_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM blinkist_favorites WHERE owner=?", (owner,)
        ).fetchone()[0] == 0


def test_verification_rejects_foreign_stale_locked_and_consumed_codes_without_persistence() -> None:
    path = case_dir("verification-boundaries")
    backend = SiteBackend.open(runtime(), data_root=path)
    backend.lifecycle.initialize()
    clock = {"now": 1_000_000}
    auth = LocalAuthStore(
        backend.lifecycle.database_path,
        site_id="blinkist",
        now=lambda: clock["now"],
    )
    auth.ensure_schema()
    session = auth.create_anonymous_session()
    foreign = auth.create_anonymous_session()
    auth.start_registration(
        session,
        email="verification-reader@example.invalid",
        display_name="Verification Reader",
        password="Local-verification-pass-2026",
    )
    mail = auth.local_mail_for_session(session, purpose="registration")
    assert mail is not None
    code = mail["verification_code"]
    assert code.encode() not in backend.lifecycle.database_path.read_bytes()

    with pytest.raises(AuthRejected):
        auth.verify_registration_code(foreign, code)
    clock["now"] += 601
    with pytest.raises(AuthExpired):
        auth.verify_registration_code(session, code)

    locked_path = case_dir("verification-locked")
    locked_backend = SiteBackend.open(runtime(), data_root=locked_path)
    locked_backend.lifecycle.initialize()
    locked_auth = LocalAuthStore(
        locked_backend.lifecycle.database_path,
        site_id="blinkist",
        now=lambda: 2_000_000,
    )
    locked_auth.ensure_schema()
    locked_session = locked_auth.create_anonymous_session()
    locked_auth.start_registration(
        locked_session,
        email="locked-reader@example.invalid",
        display_name="Locked Reader",
        password="Local-locked-pass-2026",
    )
    locked_mail = locked_auth.local_mail_for_session(
        locked_session, purpose="registration"
    )
    assert locked_mail is not None
    locked_code = locked_mail["verification_code"]
    wrong_code = "000000" if locked_code != "000000" else "111111"
    for _ in range(4):
        with pytest.raises(AuthRejected):
            locked_auth.verify_registration_code(locked_session, wrong_code)
    with pytest.raises(AuthLocked):
        locked_auth.verify_registration_code(locked_session, wrong_code)
    with pytest.raises(AuthLocked):
        locked_auth.verify_registration_code(locked_session, locked_code)

    consumed_path = case_dir("verification-consumed")
    _, consumed_auth = services(consumed_path)
    consumed_session = consumed_auth.create_anonymous_session()
    consumed_auth.start_registration(
        consumed_session,
        email="consumed-reader@example.invalid",
        display_name="Consumed Reader",
        password="Local-consumed-pass-2026",
    )
    consumed_mail = consumed_auth.local_mail_for_session(
        consumed_session, purpose="registration"
    )
    assert consumed_mail is not None
    consumed_code = consumed_mail["verification_code"]
    consumed_auth.verify_registration_code(consumed_session, consumed_code)
    consumed_auth.complete_registration(consumed_session)
    with pytest.raises(AuthRejected):
        consumed_auth.verify_registration_code(consumed_session, consumed_code)


def test_known_and_unknown_recovery_have_indistinguishable_public_results() -> None:
    path = case_dir("recovery-enumeration")
    backend = SiteBackend.open(runtime(), data_root=path)
    backend.lifecycle.initialize()
    auth = LocalAuthStore(
        backend.lifecycle.database_path,
        site_id="blinkist",
        now=lambda: 3_000_000,
    )
    auth.ensure_schema()
    seed_account(auth, "known-recovery-reader")
    known_session = auth.create_anonymous_session()
    unknown_session = auth.create_anonymous_session()

    known = auth.start_password_reset(
        known_session, email="known-recovery-reader@example.invalid"
    )
    unknown = auth.start_password_reset(
        unknown_session, email="unknown-recovery-reader@example.invalid"
    )

    assert known == unknown
    assert auth.local_mail_for_session(
        unknown_session, purpose="password-reset"
    ) is None
