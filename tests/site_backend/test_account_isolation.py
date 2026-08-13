from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.local_clone_auth import (
    AuthRejected,
    AuthSiteBindingError,
    LocalAuthStore,
)
from websitebench.site_backend import SiteBackend

EMAIL = "same-person@example.test"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATHS = {
    "amazon": REPO_ROOT / "materials" / "amazon" / "backend" / "runtime.json",
    "edx": REPO_ROOT / "materials" / "edx" / "backend" / "runtime.json",
}


def _runtime(site: str) -> dict[str, object]:
    return json.loads(RUNTIME_PATHS[site].read_text(encoding="utf-8"))


def _bound_backend(tmp_path: Path, site: str) -> SiteBackend:
    config = _runtime(site)
    backend = SiteBackend.open(
        config,
        data_root=tmp_path / site,
    )
    backend.lifecycle.initialize()
    return backend


def _bound_auth(tmp_path: Path, site: str) -> LocalAuthStore:
    backend = _bound_backend(tmp_path, site)
    auth = LocalAuthStore(
        backend.lifecycle.database_path,
        site_id=backend.config.site_id,
    )
    auth.ensure_schema()
    return auth


def _register(auth: LocalAuthStore, password: str) -> None:
    session = auth.create_anonymous_session()
    auth.start_registration(
        session,
        email=EMAIL,
        display_name="Same Person",
        password=password,
    )
    mail = auth.local_mail_for_session(session, purpose="registration")
    assert mail is not None
    auth.verify_registration_code(session, str(mail["verification_code"]))
    auth.complete_registration(session)


def test_same_email_accounts_are_independent_between_sites(tmp_path: Path) -> None:
    amazon = _bound_auth(tmp_path, "amazon")
    edx = _bound_auth(tmp_path, "edx")
    _register(amazon, "amazon-password")

    edx_session = edx.create_anonymous_session()
    with pytest.raises(AuthRejected, match="credentials"):
        edx.sign_in(
            edx_session,
            email=EMAIL,
            password="amazon-password",
        )

    _register(edx, "edx-password")
    with pytest.raises(AuthRejected, match="credentials"):
        amazon.sign_in(
            amazon.create_anonymous_session(),
            email=EMAIL,
            password="edx-password",
        )
    with pytest.raises(AuthRejected, match="credentials"):
        edx.sign_in(
            edx.create_anonymous_session(),
            email=EMAIL,
            password="amazon-password",
        )
    assert amazon.account_exists(EMAIL)
    assert edx.account_exists(EMAIL)

    # A session capability from one site's database is not meaningful in the
    # other site even when both accounts normalize to the same email.
    amazon_session = amazon.create_anonymous_session()
    assert edx.resolve_session(amazon_session) is None


def test_local_auth_rejects_a_foreign_site_database(tmp_path: Path) -> None:
    amazon = _bound_auth(tmp_path, "amazon")
    foreign = LocalAuthStore(amazon.database_path, site_id="edx")
    with pytest.raises(AuthSiteBindingError, match="foreign"):
        foreign.ensure_schema()


def test_amazon_and_edx_share_sender_address_only_not_mail_branding(
    tmp_path: Path,
) -> None:
    amazon = _bound_backend(tmp_path, "amazon")
    edx = _bound_backend(tmp_path, "edx")
    for purpose in ("registration", "password-reset"):
        amazon_message = amazon.mail.issue(
            purpose,
            EMAIL,
            {"code": "123456", "minutes": "10"},
        )
        edx_message = edx.mail.issue(
            purpose,
            EMAIL,
            {"code": "123456", "minutes": "10"},
        )

        assert (
            amazon_message["sender_address_env"]
            == edx_message["sender_address_env"]
        )
        for field in (
            "template_id",
            "sender_display_name",
            "subject",
            "text",
            "html",
        ):
            assert amazon_message[field] != edx_message[field]

    assert set(amazon.config.mail["purposes"]) != set(edx.config.mail["purposes"])
