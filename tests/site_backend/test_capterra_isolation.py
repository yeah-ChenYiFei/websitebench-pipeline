from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.local_clone_auth import AuthRejected, AuthSiteBindingError, LocalAuthStore
from websitebench.site_backend import PaymentRejected, SiteBackend, SiteBindingError


REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTERRA_RUNTIME = REPO_ROOT / "materials/capterra/backend/runtime.json"
EDX_RUNTIME = REPO_ROOT / "materials/edx/backend/runtime.json"
DEPLOYMENT = (
    REPO_ROOT
    / "deploy/generic-offline-clone/deployment.capterra.v2.json"
)
EMAIL = "same-person@capterra-isolation.example"
OWNER = "owner:capterra-account"
FINGERPRINT = "c" * 64


def _runtime(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _generic_backend(tmp_path: Path, runtime_path: Path) -> SiteBackend:
    config = _runtime(runtime_path)
    database = dict(config["database"])
    # These cross-site tests exercise the canonical runtime's own binding,
    # auth, mail, and payment tables. Site business hooks are independently
    # covered by each clone's migration gate.
    database["migration_hook"] = None
    database["seed_hook"] = None
    database["legacy_unbound_migration"] = False
    config["database"] = database
    backend = SiteBackend.open(
        config,
        data_root=tmp_path / str(config["site"]["id"]),
    )
    backend.lifecycle.initialize()
    return backend


def _auth(backend: SiteBackend) -> LocalAuthStore:
    store = LocalAuthStore(
        backend.lifecycle.database_path,
        site_id=backend.config.site_id,
    )
    store.ensure_schema()
    return store


def _register(store: LocalAuthStore, password: str) -> None:
    session = store.create_anonymous_session()
    store.start_registration(
        session,
        email=EMAIL,
        display_name="Independent Site User",
        password=password,
    )
    mail = store.local_mail_for_session(session, purpose="registration")
    assert mail is not None
    store.verify_registration_code(session, str(mail["verification_code"]))
    store.complete_registration(session)


def test_capterra_runtime_has_unique_database_cookie_volume_and_safe_profiles() -> None:
    capterra = _runtime(CAPTERRA_RUNTIME)
    edx = _runtime(EDX_RUNTIME)
    deployment = json.loads(DEPLOYMENT.read_text(encoding="utf-8"))

    assert capterra["site"]["id"] == "capterra"
    assert capterra["database"]["filename"] == "capterra.sqlite3"
    assert capterra["database"]["filename"] != edx["database"]["filename"]
    assert deployment["deployment_profile"] == "docker-volume"
    assert deployment["backend_runtime"] == (
        "materials/capterra/backend/runtime.json"
    )
    assert capterra["deployment"]["profiles"]["docker-volume"] == {
        "persistence": "persistent-volume",
        "mail_adapter": "effects-gateway",
        "payment_adapter": "local-sandbox",
    }
    backend = SiteBackend.open(
        {**capterra, "database": {**capterra["database"], "migration_hook": None, "seed_hook": None, "legacy_unbound_migration": False}},
        data_root=Path("/tmp/websitebench-capterra-contract-probe"),
    )
    assert backend.session_cookie == {
        "name": "__Host-websitebench-capterra-session",
        "path": "/",
        "secure": True,
        "httponly": True,
        "samesite": "Lax",
    }
    assert "domain" not in backend.session_cookie
    assert capterra["payments"]["default_adapter"] == "local-sandbox"
    assert capterra["payments"]["stripe_test"] is None


def test_capterra_accounts_passwords_sessions_and_mail_are_cross_site_isolated(
    tmp_path: Path,
) -> None:
    capterra_backend = _generic_backend(tmp_path, CAPTERRA_RUNTIME)
    edx_backend = _generic_backend(tmp_path, EDX_RUNTIME)
    capterra = _auth(capterra_backend)
    edx = _auth(edx_backend)
    _register(capterra, "Capterra-Only-Password-1!")

    with pytest.raises(AuthRejected, match="credentials"):
        edx.sign_in(
            edx.create_anonymous_session(),
            email=EMAIL,
            password="Capterra-Only-Password-1!",
        )
    _register(edx, "Edx-Only-Password-2!")
    with pytest.raises(AuthRejected, match="credentials"):
        capterra.sign_in(
            capterra.create_anonymous_session(),
            email=EMAIL,
            password="Edx-Only-Password-2!",
        )
    capterra_token = capterra.create_anonymous_session()
    assert edx.resolve_session(capterra_token) is None

    capterra_mail = capterra_backend.mail.issue(
        "registration", EMAIL, {"code": "123456", "minutes": "10"}
    )
    edx_mail = edx_backend.mail.issue(
        "registration", EMAIL, {"code": "123456", "minutes": "10"}
    )
    for field in ("template_id", "sender_display_name", "subject", "text", "html"):
        assert capterra_mail[field] != edx_mail[field]


def test_capterra_rejects_foreign_database_and_payment_transaction(
    tmp_path: Path,
) -> None:
    capterra = _generic_backend(tmp_path, CAPTERRA_RUNTIME)
    edx = _generic_backend(tmp_path, EDX_RUNTIME)

    foreign_auth = LocalAuthStore(
        capterra.lifecycle.database_path,
        site_id="edx",
    )
    with pytest.raises(AuthSiteBindingError, match="foreign"):
        foreign_auth.ensure_schema()

    flow = capterra.payments.create_intent(
        owner=OWNER,
        amount_minor=0,
        currency="USD",
        fingerprint=FINGERPRINT,
        idempotency_key="create:capterra-isolation",
    )
    capterra.payments.attempt(
        flow_id=str(flow["flow_id"]),
        owner=OWNER,
        amount_minor=0,
        currency="USD",
        fingerprint=FINGERPRINT,
        scenario_id="sandbox-approved",
        idempotency_key="attempt:capterra-isolation",
    )
    with edx.lifecycle.connection(transaction=True) as connection:
        with pytest.raises(SiteBindingError):
            capterra.payments.consume_approval(
                connection,
                flow_id=str(flow["flow_id"]),
                owner=OWNER,
                amount_minor=0,
                currency="USD",
                fingerprint=FINGERPRINT,
            )
    with pytest.raises(PaymentRejected, match="foreign"):
        capterra.payments.attempt(
            flow_id=str(flow["flow_id"]),
            owner="owner:foreign-account",
            amount_minor=0,
            currency="USD",
            fingerprint=FINGERPRINT,
            scenario_id="sandbox-approved",
            idempotency_key="attempt:foreign-isolation",
        )


def test_capterra_runtime_and_deployment_contain_no_payment_credentials() -> None:
    combined = CAPTERRA_RUNTIME.read_text(encoding="utf-8") + DEPLOYMENT.read_text(
        encoding="utf-8"
    )
    forbidden = (
        "sk_live_",
        "sk_test_",
        "whsec_",
        "4242424242424242",
        "cvv",
        "card_number",
    )
    assert all(value not in combined.casefold() for value in forbidden)
