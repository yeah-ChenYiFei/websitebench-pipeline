from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from websitebench.local_clone_auth import (
    MAIL_LOCAL_ONLY,
    MAIL_SMTP_FAILED,
    MAIL_SMTP_PENDING,
    AuthBackupError,
    AuthConflict,
    AuthLocked,
    AuthRateLimited,
    AuthRejected,
    AuthSiteBindingError,
    AuthValidationError,
    LocalAuthStore,
)
from websitebench.local_clone_auth.vendor import (
    RUNTIME_FILES,
    vendor_local_clone_auth,
)


class Clock:
    def __init__(self, value: int = 1_800_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "site.sqlite3"


@pytest.fixture
def store(database: Path, clock: Clock) -> LocalAuthStore:
    value = LocalAuthStore(database, now=clock)
    value.ensure_schema()
    return value


def _local_code(
    store: LocalAuthStore, session: str, purpose: str = "registration"
) -> str:
    mail = store.local_mail_for_session(session, purpose=purpose)
    assert mail is not None
    assert mail["status"] == MAIL_LOCAL_ONLY
    return str(mail["verification_code"])


def test_external_registration_details_validate_without_mutation(
    store: LocalAuthStore,
) -> None:
    assert store.validate_registration_details(
        email=" Person@Example.Test ",
        display_name="  Public   Person ",
        password="correct horse",
    ) == {
        "email": "person@example.test",
        "display_name": "Public Person",
        "password": "correct horse",
    }
    with pytest.raises(AuthValidationError):
        store.validate_registration_details(
            email="person@example.test",
            display_name="Public Person",
            password="short",
        )
    assert store.account_exists("person@example.test") is False


def test_schema_wal_migration_and_session_token_digest_only(
    store: LocalAuthStore, database: Path
) -> None:
    session = store.create_anonymous_session()
    assert store.applied_migrations() == ["0001", "0002", "0003", "0004"]
    assert store.resolve_session(session) == {
        "authenticated": False,
        "account": None,
        "created_at": 1_800_000_000,
        "expires_at": 1_802_592_000,
    }

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        stored = connection.execute(
            "SELECT session_digest FROM local_auth_sessions"
        ).fetchone()[0]
        assert stored != session
        assert len(stored) == 64
    assert session.encode("utf-8") not in database.read_bytes()


def test_registration_creates_account_only_after_verified_code_and_rotates_session(
    store: LocalAuthStore, database: Path
) -> None:
    session = store.create_anonymous_session()
    issued = store.start_registration(
        session,
        email=" Owner@Example.Test ",
        display_name="  Owner   Example ",
        password="correct horse battery staple",
    )
    assert issued["accepted"] is True
    assert store.counts()["local_auth_accounts"] == 0
    code = _local_code(store, session)

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT email_normalized,display_name,password_hash,code_hash "
            "FROM local_auth_registration_flows"
        ).fetchone()
        assert row[0:2] == ("owner@example.test", "Owner Example")
        assert row[2] != b"correct horse battery staple"
        assert row[3] != code.encode()
    assert b"correct horse battery staple" not in database.read_bytes()

    store.verify_registration_code(session, code)
    created_subjects: list[str] = []

    def create_subject(
        connection: sqlite3.Connection, registration: dict[str, object]
    ) -> str:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS business_accounts("
            "subject_id TEXT PRIMARY KEY,email TEXT NOT NULL)"
        )
        subject_id = "buyer-001"
        connection.execute(
            "INSERT INTO business_accounts(subject_id,email) VALUES (?,?)",
            (subject_id, registration["email"]),
        )
        created_subjects.append(subject_id)
        return subject_id

    completed = store.complete_registration(session, subject_factory=create_subject)
    assert created_subjects == ["buyer-001"]
    assert store.resolve_session(session) is None
    rotated = completed["session_token"]
    resolved = store.resolve_session(rotated)
    assert resolved is not None
    assert resolved["authenticated"] is True
    assert resolved["account"]["subject_id"] == "buyer-001"
    assert resolved["account"]["email_verified"] == 1
    assert store.counts()["local_auth_registration_flows"] == 0
    assert store.counts()["local_auth_mail_outbox"] == 0


def test_external_registration_creates_verified_account_in_site_transaction(
    store: LocalAuthStore, database: Path
) -> None:
    session = store.create_anonymous_session()
    created_subjects: list[str] = []

    def create_subject(
        connection: sqlite3.Connection, registration: dict[str, object]
    ) -> str:
        connection.execute(
            "CREATE TABLE business_accounts("
            "subject_id TEXT PRIMARY KEY,email TEXT NOT NULL)"
        )
        subject_id = "external-buyer-001"
        connection.execute(
            "INSERT INTO business_accounts(subject_id,email) VALUES (?,?)",
            (subject_id, registration["email"]),
        )
        created_subjects.append(subject_id)
        return subject_id

    completed = store.complete_externally_verified_registration(
        session,
        email=" External.Owner@Example.Test ",
        display_name=" External Owner ",
        password="correct horse battery staple",
        subject_factory=create_subject,
    )

    assert created_subjects == ["external-buyer-001"]
    assert store.resolve_session(session) is None
    assert store.account_exists("external.owner@example.test") is True
    resolved = store.resolve_session(completed["session_token"])
    assert resolved is not None
    assert resolved["authenticated"] is True
    assert resolved["account"]["email_verified"] == 1
    with sqlite3.connect(database) as connection:
        account = connection.execute(
            "SELECT email_normalized,email_verified,password_hash "
            "FROM local_auth_accounts"
        ).fetchone()
        business = connection.execute(
            "SELECT subject_id,email FROM business_accounts"
        ).fetchone()
    assert account[0:2] == ("external.owner@example.test", 1)
    assert account[2] != b"correct horse battery staple"
    assert business == (
        "external-buyer-001",
        "external.owner@example.test",
    )


def test_invalid_codes_consume_persistent_attempt_budget(store: LocalAuthStore) -> None:
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="owner@example.test",
        display_name="Owner",
        password="secure-password",
    )
    for attempt in range(1, 5):
        with pytest.raises(AuthRejected):
            store.verify_registration_code(session, "000000")
        with store.connect() as connection:
            assert (
                connection.execute(
                    "SELECT attempts FROM local_auth_registration_flows"
                ).fetchone()[0]
                == attempt
            )
    with pytest.raises(AuthLocked):
        store.verify_registration_code(session, "000000")
    with store.connect() as connection:
        assert (
            connection.execute(
                "SELECT attempts FROM local_auth_registration_flows"
            ).fetchone()[0]
            == 5
        )
    with pytest.raises(AuthLocked):
        store.verify_registration_code(session, _local_code(store, session))


def test_sign_in_uses_real_credentials_rotates_and_revokes(
    store: LocalAuthStore,
) -> None:
    store.seed_account(
        subject_id="buyer-001",
        email="owner@example.test",
        display_name="Owner",
        password="secure-password",
    )
    anonymous = store.create_anonymous_session()
    with pytest.raises(AuthRejected, match="credentials are invalid"):
        store.sign_in(
            anonymous,
            email="unknown@example.test",
            password="secure-password",
        )
    with pytest.raises(AuthRejected, match="credentials are invalid"):
        store.sign_in(
            anonymous,
            email="owner@example.test",
            password="wrong-password",
        )

    signed_in = store.sign_in(
        anonymous,
        email="owner@example.test",
        password="secure-password",
    )
    assert store.resolve_session(anonymous) is None
    token = signed_in["session_token"]
    assert store.resolve_session(token)["account"]["subject_id"] == "buyer-001"
    store.sign_out(token)
    assert store.resolve_session(token) is None


def test_session_rotation_callback_and_site_reset_are_atomic(
    store: LocalAuthStore,
    database: Path,
) -> None:
    store.seed_account(
        subject_id="buyer-001",
        email="owner@example.test",
        display_name="Owner",
        password="secure-password",
    )
    with store.connect() as connection:
        connection.execute(
            "CREATE TABLE site_state("
            "owner_session_id TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
    anonymous = store.create_anonymous_session()
    old_digest = store.session_owner_digest(anonymous)
    with store.connect() as connection:
        connection.execute(
            "INSERT INTO site_state(owner_session_id,value) VALUES (?,?)",
            (old_digest, "comparison"),
        )

    def transfer(
        connection: sqlite3.Connection,
        old_owner: str,
        new_owner: str,
    ) -> None:
        connection.execute(
            "UPDATE site_state SET owner_session_id=? WHERE owner_session_id=?",
            (new_owner, old_owner),
        )

    signed_in = store.sign_in(
        anonymous,
        email="owner@example.test",
        password="secure-password",
        session_rotation_callback=transfer,
    )
    new_digest = store.session_owner_digest(signed_in["session_token"])
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT owner_session_id,value FROM site_state"
        ).fetchone() == (new_digest, "comparison")

    retry = store.create_anonymous_session()

    def fail_rotation(
        connection: sqlite3.Connection,
        old_owner: str,
        new_owner: str,
    ) -> None:
        del connection, old_owner, new_owner
        raise RuntimeError("site rotation failed")

    with pytest.raises(RuntimeError, match="site rotation failed"):
        store.sign_in(
            retry,
            email="owner@example.test",
            password="secure-password",
            session_rotation_callback=fail_rotation,
        )
    assert store.resolve_session(retry)["authenticated"] is False

    def fail_reset(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM site_state")
        raise RuntimeError("site reset failed")

    with pytest.raises(RuntimeError, match="site reset failed"):
        store.reset_site_state(site_reset=fail_reset, seed_accounts=[])
    assert store.resolve_session(signed_in["session_token"]) is not None
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM site_state").fetchone() == (1,)

    def reset_site(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM site_state")
        connection.execute(
            "INSERT INTO site_state(owner_session_id,value) VALUES (?,?)",
            ("0" * 64, "seed"),
        )

    store.reset_site_state(
        site_reset=reset_site,
        seed_accounts=[
            {
                "subject_id": "buyer-001",
                "email": "owner@example.test",
                "display_name": "Owner",
                "password": "secure-password",
            }
        ],
    )
    assert store.resolve_session(signed_in["session_token"]) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT owner_session_id,value FROM site_state"
        ).fetchone() == ("0" * 64, "seed")
        assert connection.execute(
            "SELECT COUNT(*) FROM local_auth_accounts"
        ).fetchone() == (1,)


def test_password_reset_known_and_unknown_public_responses_are_identical(
    store: LocalAuthStore, clock: Clock
) -> None:
    store.seed_account(
        subject_id="buyer-001",
        email="owner@example.test",
        display_name="Owner",
        password="old-password",
    )
    known_session = store.create_anonymous_session()
    unknown_session = store.create_anonymous_session()
    known = store.start_password_reset(known_session, email="owner@example.test")
    unknown = store.start_password_reset(unknown_session, email="missing@example.test")
    assert known == unknown
    assert _local_code(store, known_session, "password-reset")
    assert (
        store.local_mail_for_session(unknown_session, purpose="password-reset") is None
    )

    code = _local_code(store, known_session, "password-reset")
    store.verify_password_reset_code(known_session, code)
    rotated = store.complete_password_reset(known_session, new_password="new-password")
    assert store.resolve_session(known_session) is None
    assert store.resolve_session(rotated)["authenticated"] is True
    another = store.create_anonymous_session()
    with pytest.raises(AuthRejected):
        store.sign_in(
            another,
            email="owner@example.test",
            password="old-password",
        )
    signed_in = store.sign_in(
        another,
        email="owner@example.test",
        password="new-password",
    )
    assert signed_in["account"]["subject_id"] == "buyer-001"


def test_mail_rate_limit_is_durable_across_store_instances(
    store: LocalAuthStore, database: Path, clock: Clock
) -> None:
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="owner@example.test",
        display_name="Owner",
        password="secure-password",
    )
    restarted = LocalAuthStore(database, now=clock)
    with pytest.raises(AuthRateLimited) as limited:
        restarted.start_registration(
            session,
            email="owner@example.test",
            display_name="Changed Owner",
            password="changed-password",
        )
    assert limited.value.retry_after == 60
    clock.advance(60)
    replacement = restarted.start_registration(
        session,
        email="owner@example.test",
        display_name="Changed Owner",
        password="changed-password",
    )
    assert (
        restarted.start_registration(
            session,
            email="owner@example.test",
            display_name="Changed Owner",
            password="changed-password",
        )
        == replacement
    )


def test_smtp_process_restart_preserves_hash_only_flow_but_not_outbox(
    database: Path, clock: Clock
) -> None:
    worker_token = "shared-mail-worker-token-01"
    store = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    store.ensure_schema()
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="owner@example.test",
        display_name="Owner",
        password="secure-password",
    )

    first = store.claim_pending_mail(worker_token=worker_token)
    assert first is not None
    assert first["delivery_attempts"] == 1
    old_code = str(first["verification_code"])
    # A process restart has no cleartext OTP and therefore cannot replay the
    # outbox, while the hash-only flow remains verifiable with a code already
    # delivered to the user.
    restarted = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    restarted.reconcile_mail(worker_token=worker_token)
    assert restarted.claim_pending_mail(worker_token=worker_token) is None
    assert restarted.session_mail_state(session, purpose="registration") is None
    restarted.verify_registration_code(session, old_code)
    restarted.complete_registration(session)
    with restarted.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(local_auth_mail_outbox)"
            )
        }
    assert "verification_code" not in columns
    assert old_code.encode() not in database.read_bytes()


def test_legacy_plaintext_otp_column_is_dropped_without_copying_secret(
    database: Path, clock: Clock
) -> None:
    worker_token = "legacy-mail-worker-token-01"
    store = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="legacy@example.test",
        display_name="Legacy Owner",
        password="secure-password",
    )
    legacy_code = "654321"
    with store.connect() as connection:
        connection.execute(
            "ALTER TABLE local_auth_mail_outbox "
            "ADD COLUMN verification_code TEXT"
        )
        connection.execute(
            "UPDATE local_auth_mail_outbox SET verification_code=?",
            (legacy_code,),
        )

    migrated = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    migrated.ensure_schema()
    with migrated.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(local_auth_mail_outbox)"
            )
        }
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM local_auth_registration_flows"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM local_auth_mail_outbox"
            ).fetchone()[0]
            == 0
        )
    assert "verification_code" not in columns
    assert legacy_code.encode() not in database.read_bytes()


def test_reserved_smtp_claim_is_invalidated_after_restart(
    database: Path, clock: Clock
) -> None:
    worker_token = "shared-mail-worker-token-reserved-replay"
    store = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="reserved-replay@example.test",
        display_name="Reserved Replay",
        password="secure-password",
    )
    first = store.claim_pending_mail(worker_token=worker_token)
    assert first is not None
    assert (
        store.reserve_mail_target_request(
            int(first["mail_id"]),
            str(first["claim_token"]),
            worker_token=worker_token,
        )
        == 1
    )

    restarted = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    restarted.reconcile_mail(worker_token=worker_token)
    assert restarted.session_mail_state(session, purpose="registration") is None
    assert restarted.claim_pending_mail(worker_token=worker_token) is None


def test_reserved_smtp_claim_at_ceiling_fails_without_replay(
    database: Path, clock: Clock
) -> None:
    worker_token = "shared-mail-worker-token-reserved-ceiling"
    store = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="reserved-ceiling@example.test",
        display_name="Reserved Ceiling",
        password="secure-password",
    )
    for expected_attempt in range(1, 4):
        claim = store.claim_pending_mail(worker_token=worker_token)
        assert claim is not None
        assert claim["delivery_attempts"] == expected_attempt
        store.reserve_mail_target_request(
            int(claim["mail_id"]),
            str(claim["claim_token"]),
            worker_token=worker_token,
        )
        store.reconcile_mail(worker_token=worker_token)

    state = store.session_mail_state(session, purpose="registration")
    assert state is not None
    assert state["status"] == MAIL_SMTP_FAILED
    assert state["delivery_attempts"] == 3
    assert state["target_request_count"] == 1
    assert state["accepted_effect_count"] == 0
    assert state["claim_token"] is None
    assert store.claim_pending_mail(worker_token=worker_token) is None


def test_schema_read_does_not_fabricate_failed_mail_request(
    database: Path, clock: Clock
) -> None:
    worker_token = "shared-mail-worker-token-read-truth"
    store = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="read-truth@example.test",
        display_name="Read Truth",
        password="secure-password",
    )
    claim = store.claim_pending_mail(worker_token=worker_token)
    assert claim is not None
    store.finish_mail_claim(
        int(claim["mail_id"]),
        str(claim["claim_token"]),
        sent=False,
        target_request_count=0,
        accepted_request_count=0,
        error="failed before reserve",
        worker_token=worker_token,
    )
    with store.connect() as connection:
        before = tuple(
            connection.execute(
                "SELECT status,delivery_attempts,target_request_count,"
                "accepted_effect_count,delivery_state_version,last_error "
                "FROM local_auth_mail_outbox"
            ).fetchone()
        )
    state = store.session_mail_state(session, purpose="registration")
    assert state is not None
    with store.connect() as connection:
        after = tuple(
            connection.execute(
                "SELECT status,delivery_attempts,target_request_count,"
                "accepted_effect_count,delivery_state_version,last_error "
                "FROM local_auth_mail_outbox"
            ).fetchone()
        )
    assert (
        before
        == after
        == (
            MAIL_SMTP_FAILED,
            1,
            0,
            0,
            2,
            "unknown",
        )
    )
    assert state["target_request_count"] == 0
    assert state["accepted_effect_count"] == 0


def test_email_delivery_public_actor_cannot_transition_outbox(
    database: Path, clock: Clock
) -> None:
    worker_token = "shared-mail-worker-token-02"
    with pytest.raises(ValueError, match="mail worker token"):
        LocalAuthStore(
            database,
            now=clock,
            mail_mode=MAIL_SMTP_PENDING,
        )
    store = LocalAuthStore(
        database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email="worker-boundary@example.test",
        display_name="Worker Boundary",
        password="secure-password",
    )
    with pytest.raises(AuthRejected, match="worker authority"):
        store.claim_pending_mail()
    with pytest.raises(AuthRejected, match="worker authority"):
        store.claim_pending_mail(worker_token="public-browser-actor")
    claim = store.claim_pending_mail(worker_token=worker_token)
    assert claim is not None
    with pytest.raises(AuthRejected, match="worker authority"):
        store.finish_mail_claim(
            int(claim["mail_id"]),
            str(claim["claim_token"]),
            sent=True,
            accepted_request_count=1,
        )
    with pytest.raises(AuthValidationError, match="accepted loopback request"):
        store.finish_mail_claim(
            int(claim["mail_id"]),
            str(claim["claim_token"]),
            sent=True,
            worker_token=worker_token,
        )
    with store.connect() as connection:
        row = connection.execute(
            "SELECT status,delivery_attempts,claim_token "
            "FROM local_auth_mail_outbox WHERE mail_id=?",
            (claim["mail_id"],),
        ).fetchone()
        assert tuple(row) == (
            MAIL_SMTP_PENDING,
            1,
            claim["claim_token"],
        )


def test_registration_duplicate_is_transactionally_rejected(
    store: LocalAuthStore, clock: Clock
) -> None:
    first = store.create_anonymous_session()
    second = store.create_anonymous_session()
    store.start_registration(
        first,
        email="owner@example.test",
        display_name="Owner",
        password="secure-password",
    )
    clock.advance(60)
    store.start_registration(
        second,
        email="owner@example.test",
        display_name="Other",
        password="other-password",
    )
    store.verify_registration_code(first, _local_code(store, first))
    store.verify_registration_code(second, _local_code(store, second))
    store.complete_registration(first)
    with pytest.raises(AuthConflict):
        store.complete_registration(second)
    assert store.counts()["local_auth_accounts"] == 1


def test_registration_exact_retry_replays_pending_flow_without_new_effects(
    store: LocalAuthStore,
) -> None:
    session = store.create_anonymous_session()
    first = store.start_registration(
        session,
        email=" Owner@Example.Test ",
        display_name="  Owner   Example ",
        password="secure-password",
    )
    with store.connect() as connection:
        before = {
            "flow": tuple(
                connection.execute(
                    "SELECT pending_id,expires_at,attempts,verified_at "
                    "FROM local_auth_registration_flows"
                ).fetchone()
            ),
            "outbox": connection.execute(
                "SELECT COUNT(*) FROM local_auth_mail_outbox"
            ).fetchone()[0],
            "rate_limits": [
                tuple(row)
                for row in connection.execute(
                    "SELECT purpose,scope_type,scope_key,window_started_at,"
                    "send_count,last_sent_at FROM local_auth_mail_rate_limits "
                    "ORDER BY purpose,scope_type,scope_key"
                )
            ],
        }

    second = store.start_registration(
        session,
        email="owner@example.test",
        display_name="Owner Example",
        password="secure-password",
    )

    assert second == first
    with store.connect() as connection:
        after = {
            "flow": tuple(
                connection.execute(
                    "SELECT pending_id,expires_at,attempts,verified_at "
                    "FROM local_auth_registration_flows"
                ).fetchone()
            ),
            "outbox": connection.execute(
                "SELECT COUNT(*) FROM local_auth_mail_outbox"
            ).fetchone()[0],
            "rate_limits": [
                tuple(row)
                for row in connection.execute(
                    "SELECT purpose,scope_type,scope_key,window_started_at,"
                    "send_count,last_sent_at FROM local_auth_mail_rate_limits "
                    "ORDER BY purpose,scope_type,scope_key"
                )
            ],
        }
    assert after == before

    with pytest.raises(AuthRateLimited):
        store.start_registration(
            session,
            email="owner@example.test",
            display_name="Changed Owner",
            password="changed-password",
        )


def test_complete_site_database_backup_restore_and_validation(
    store: LocalAuthStore,
    tmp_path: Path,
) -> None:
    store.seed_account(
        subject_id="buyer-001",
        email="owner@example.test",
        display_name="Owner",
        password="secure-password",
    )
    with store.connect() as connection:
        connection.execute(
            "CREATE TABLE business_cart("
            "owner_id TEXT PRIMARY KEY,quantity INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO business_cart(owner_id,quantity) VALUES (?,?)",
            ("buyer-001", 2),
        )

    backup_path = tmp_path / "backups" / "site.sqlite3"
    metadata = store.backup_to(backup_path)
    assert metadata["quick_check"] == "ok"
    assert metadata["migrations"] == ["0001", "0002", "0003", "0004"]
    assert metadata["bytes"] == backup_path.stat().st_size
    assert len(metadata["sha256"]) == 64
    assert "business_cart" in metadata["tables"]
    with pytest.raises(FileExistsError):
        store.backup_to(backup_path)

    restored_path = tmp_path / "restored" / "site.sqlite3"
    restored = LocalAuthStore(restored_path, now=store._now)
    restored_metadata = restored.restore_from(backup_path)
    assert restored_metadata["quick_check"] == "ok"
    assert restored.counts()["local_auth_accounts"] == 1
    with restored.connect() as connection:
        assert tuple(
            connection.execute("SELECT owner_id,quantity FROM business_cart").fetchone()
        ) == ("buyer-001", 2)
    anonymous = restored.create_anonymous_session()
    signed_in = restored.sign_in(
        anonymous,
        email="owner@example.test",
        password="secure-password",
    )
    assert signed_in["account"]["subject_id"] == "buyer-001"

    invalid = tmp_path / "invalid.sqlite3"
    invalid.write_bytes(b"not a sqlite database")
    with pytest.raises(AuthBackupError):
        LocalAuthStore(tmp_path / "invalid-restore.sqlite3").restore_from(invalid)

    restored.seed_account(
        subject_id="buyer-002",
        email="replacement@example.test",
        display_name="Replacement",
        password="replacement-password",
    )
    overwritten = restored.restore_from(backup_path, overwrite=True)
    assert overwritten["sha256"] == metadata["sha256"]
    assert restored.counts()["local_auth_accounts"] == 1
    replacement_session = restored.create_anonymous_session()
    with pytest.raises(AuthRejected):
        restored.sign_in(
            replacement_session,
            email="replacement@example.test",
            password="replacement-password",
        )


def test_foreign_site_backup_is_rejected_before_live_database_replacement(
    tmp_path: Path,
    clock: Clock,
) -> None:
    def bound_store(site_id: str) -> LocalAuthStore:
        database = tmp_path / site_id / "site.sqlite3"
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE websitebench_site_binding("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                "site_id TEXT NOT NULL UNIQUE,bound_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO websitebench_site_binding"
                "(singleton,site_id,bound_at) VALUES (1,?,?)",
                (site_id, "2026-08-02T00:00:00Z"),
            )
        value = LocalAuthStore(database, now=clock, site_id=site_id)
        value.ensure_schema()
        return value

    alpha = bound_store("alpha")
    beta = bound_store("beta")
    alpha.seed_account(
        subject_id="alpha-owner",
        email="owner@example.test",
        display_name="Alpha Owner",
        password="alpha-password",
    )
    beta.seed_account(
        subject_id="beta-owner",
        email="owner@example.test",
        display_name="Beta Owner",
        password="beta-password",
    )
    beta_backup = tmp_path / "beta-backup.sqlite3"
    beta.backup_to(beta_backup)
    with alpha.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = alpha.database_path.read_bytes()

    with pytest.raises(
        AuthSiteBindingError,
        match="another WebsiteBench site",
    ):
        alpha.restore_from(beta_backup, overwrite=True)

    assert alpha.database_path.read_bytes() == before
    with alpha.connect() as connection:
        assert connection.execute(
            "SELECT site_id FROM websitebench_site_binding"
        ).fetchone()[0] == "alpha"
    session = alpha.create_anonymous_session()
    signed_in = alpha.sign_in(
        session,
        email="owner@example.test",
        password="alpha-password",
    )
    assert signed_in["account"]["subject_id"] == "alpha-owner"


def test_registration_and_mail_claims_are_serialized_under_concurrency(
    database: Path,
    clock: Clock,
) -> None:
    store = LocalAuthStore(database, now=clock)
    store.ensure_schema()
    first = store.create_anonymous_session()
    second = store.create_anonymous_session()
    store.start_registration(
        first,
        email="owner@example.test",
        display_name="First",
        password="secure-password",
    )
    clock.advance(60)
    store.start_registration(
        second,
        email="owner@example.test",
        display_name="Second",
        password="other-password",
    )
    store.verify_registration_code(first, _local_code(store, first))
    store.verify_registration_code(second, _local_code(store, second))

    registration_barrier = threading.Barrier(2)

    def complete(session: str) -> str:
        registration_barrier.wait()
        try:
            store.complete_registration(session)
        except AuthConflict:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(complete, (first, second)))
    assert outcomes == ["conflict", "created"]
    assert store.counts()["local_auth_accounts"] == 1

    mail_database = database.with_name("mail-concurrency.sqlite3")
    worker_token = "shared-concurrent-worker-01"
    mail_store = LocalAuthStore(
        mail_database,
        now=clock,
        mail_mode=MAIL_SMTP_PENDING,
        mail_worker_token=worker_token,
    )
    mail_store.ensure_schema()
    mail_session = mail_store.create_anonymous_session()
    mail_store.start_registration(
        mail_session,
        email="mail@example.test",
        display_name="Mail",
        password="secure-password",
    )
    mail_barrier = threading.Barrier(2)

    def claim() -> dict[str, object] | None:
        mail_barrier.wait()
        return mail_store.claim_pending_mail(worker_token=worker_token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: claim(), range(2)))
    assert sum(item is not None for item in claims) == 1
    assert sum(item is None for item in claims) == 1


def test_vendor_is_self_contained_and_byte_identical() -> None:
    source_root = (
        Path(__file__).resolve().parents[2] / "src" / "websitebench" / "local_clone_auth"
    )
    with tempfile.TemporaryDirectory() as temporary:
        candidate_root = Path(temporary) / "clone"
        candidate_root.mkdir()
        manifest_path = vendor_local_clone_auth(candidate_root)
        target_root = candidate_root / "websitebench" / "local_clone_auth"

        assert manifest_path.is_file()
        for relative_name in RUNTIME_FILES:
            payload = (target_root / relative_name).read_bytes()
            expected = (source_root / relative_name).read_bytes().replace(
                b"\r\n", b"\n"
            )
            assert payload == expected
            assert b"\r\n" not in payload


@pytest.mark.parametrize(
    "site",
    (
        "capterra",
        "change",
        "edx",
        "etsy",
        "imdb",
        "taskrabbit",
        "petfinder",
        "eventbrite",
    ),
)
def test_eight_site_legacy_vendors_match_their_frozen_manifests(site: str) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    target_root = (
        repository_root
        / "materials"
        / site
        / "clone"
        / "clawbench"
        / "local_clone_auth"
    )
    if not target_root.exists():
        pytest.skip(f"materials/{site} is not in this checkout")
    manifest = json.loads(
        (target_root / "VENDOR_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "local-clone-auth.vendor.v1"
    assert manifest["source"] == "src/clawbench/local_clone_auth"
    for entry in manifest["files"]:
        path = target_root / entry["path"]
        payload = path.read_bytes().replace(b"\r\n", b"\n")
        assert len(payload) == entry["bytes"]
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
