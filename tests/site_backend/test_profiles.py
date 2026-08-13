from __future__ import annotations

import sqlite3
from pathlib import Path

from websitebench.local_clone_auth import LocalAuthStore
from websitebench.site_backend import SiteBackend

from .helpers import runtime_config


def _register(
    auth: LocalAuthStore,
    *,
    email: str,
    password: str,
) -> None:
    session = auth.create_anonymous_session()
    auth.start_registration(
        session,
        email=email,
        display_name="Offline User",
        password=password,
    )
    message = auth.local_mail_for_session(session, purpose="registration")
    assert message is not None
    auth.verify_registration_code(
        session,
        str(message["verification_code"]),
    )
    auth.complete_registration(session)


def test_offline_harbor_runtime_restart_preserves_account_and_order(
    tmp_path: Path,
) -> None:
    config = runtime_config("harbor-shop", "Harbor Shop")
    assert (
        config["deployment"]["profiles"]["offline-harbor"]["persistence"]
        == "persistent"
    )
    data_root = tmp_path / "offline-harbor"
    email = "offline-user@example.test"
    password = "offline-password"
    owner = "account:offline-user"
    fingerprint = "a" * 64

    first = SiteBackend.open(config, data_root=data_root)
    first.lifecycle.initialize()
    first_auth = LocalAuthStore(
        first.lifecycle.database_path,
        site_id=first.config.site_id,
    )
    _register(first_auth, email=email, password=password)
    flow = first.payments.create_intent(
        owner=owner,
        amount_minor=2599,
        currency="USD",
        fingerprint=fingerprint,
        idempotency_key="flow:offline-restart",
    )
    first.payments.attempt(
        flow_id=flow["flow_id"],
        owner=owner,
        amount_minor=2599,
        currency="USD",
        fingerprint=fingerprint,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:offline-restart",
    )
    with first.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS site_orders("
            "order_id TEXT PRIMARY KEY,owner TEXT NOT NULL,"
            "amount_minor INTEGER NOT NULL)"
        )
        first.payments.consume_approval(
            connection,
            flow_id=flow["flow_id"],
            owner=owner,
            amount_minor=2599,
            currency="USD",
            fingerprint=fingerprint,
        )
        connection.execute(
            "INSERT INTO site_orders(order_id,owner,amount_minor)"
            " VALUES (?,?,?)",
            ("ORDER-RESTART-1", owner, 2599),
        )

    # Replace every runtime object while retaining only the profile's SQLite
    # path. This models an offline-harbor process restart; Docker replacement
    # persistence is covered separately by the Compose evidence run.
    restarted = SiteBackend.open(config, data_root=data_root)
    assert restarted.lifecycle.initialize()["status"] == "ok"
    restarted_auth = LocalAuthStore(
        restarted.lifecycle.database_path,
        site_id=restarted.config.site_id,
    )
    signed_in = restarted_auth.sign_in(
        restarted_auth.create_anonymous_session(),
        email=email,
        password=password,
    )
    assert signed_in["account"]["email_normalized"] == email
    with sqlite3.connect(restarted.lifecycle.database_path) as connection:
        assert connection.execute(
            "SELECT owner,amount_minor FROM site_orders WHERE order_id=?",
            ("ORDER-RESTART-1",),
        ).fetchone() == (owner, 2599)
