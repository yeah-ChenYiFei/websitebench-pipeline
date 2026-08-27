from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

from websitebench.site_backend import SiteBackend
from websitebench.site_backend.errors import PaymentRejected

from backend.site_schema import migrate, seed
from app import BACKEND, DEMO_SUBJECT_ID, app


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as active:
        response = active.post("/__websitebench/reset")
        assert response.status_code == 200
        yield active


def sign_in_demo(client: TestClient) -> None:
    response = client.post(
        "/fixture/session", data={"next": "/"}, follow_redirects=False
    )
    assert response.status_code == 303


def register_member(client: TestClient, email: str = "new-member@example.test") -> None:
    response = client.post(
        "/register",
        data={
            "email": email,
            "password": "LocalPass123!",
            "next": "/checkout?plan=Mega+Fan&term=monthly",
        },
    )
    assert response.status_code == 200
    match = re.search(r"verification code: <strong>(\d{6})</strong>", response.text)
    assert match
    verified = client.post(
        "/register/verify",
        data={"code": match.group(1), "next": "/checkout?plan=Mega+Fan&term=monthly"},
        follow_redirects=False,
    )
    assert verified.status_code == 303
    assert verified.headers["location"].startswith("/checkout")


def test_health_contracts(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"ok": True, "site_id": "crunchyroll"}
    assert client.get("/__websitebench/health").json() == {"status": "ok"}


def test_public_entry_navigation_and_catalog(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "crunchyroll" in home.text
    assert "/videos/popular" in home.text
    assert "Most Popular" in home.text
    popular = client.get("/videos/popular")
    assert popular.status_code == 200
    assert "One Piece" in popular.text
    assert "JUJUTSU KAISEN" in popular.text


def test_discovery_and_series_details(client: TestClient) -> None:
    result = client.get("/search?q=One+Piece")
    assert result.status_code == 200
    assert "1 matching title" in result.text
    detail = client.get("/series/GRMG8ZQZR/one-piece")
    for text in (
        "One Piece",
        "Synopsis" if False else "Embark on a voyage",
        "Season 1",
        "Episodes",
        "Cast",
        "Maturity Rating",
        "Audio",
        "Subtitles",
        "More Like This",
    ):
        assert text in detail.text


def test_search_no_results_and_recovery(client: TestClient) -> None:
    response = client.get("/search?q=no-such-anime-672")
    assert response.status_code == 200
    assert "No results found" in response.text
    assert "/videos/popular" in response.text
    assert "Clear Search" in response.text


def test_auth_entries_and_empty_validation(client: TestClient) -> None:
    login = client.get("/login")
    assert 'name="email"' in login.text
    assert 'name="password"' in login.text
    assert "Forgot Password?" in login.text
    register = client.get("/register")
    assert "Use at least 6 characters" in register.text
    assert "Terms of Use" in register.text
    invalid = client.post("/register", data={"email": "", "password": ""})
    assert invalid.status_code == 200
    assert "Enter an email address and password" in invalid.text


def test_password_recovery_does_not_send_remote_message(client: TestClient) -> None:
    page = client.get("/reset-password")
    assert "Email Address" in page.text
    assert "Return to Log In" in page.text
    invalid = client.post("/reset-password", data={"email": ""})
    assert "Enter the email address" in invalid.text
    result = client.post("/reset-password", data={"email": "unknown@example.test"})
    assert "No reset message was sent" in result.text


def test_signed_out_watchlist_prompts(client: TestClient) -> None:
    response = client.post(
        "/watchlist/toggle", data={"series_id": "GRMG8ZQZR", "return_to": "/watchlist"}
    )
    assert response.status_code == 401
    assert "Log In Required" in response.text
    assert "Log in or create an account" in response.text


def test_seeded_member_journey(client: TestClient) -> None:
    sign_in_demo(client)
    home = client.get("/")
    assert "Continue Watching" in home.text
    watchlist = client.get("/watchlist")
    assert watchlist.status_code == 200
    assert "One Piece" in watchlist.text
    player = client.get("/watch/GN7UD8ARD/one-piece-episode-1")
    for text in (
        "Local controls and progress simulation",
        "Play",
        "Volume",
        "Subtitles",
        "Audio",
        "Fullscreen",
        "Next Episode",
    ):
        assert text in player.text
    progress = client.post(
        "/api/progress",
        json={"episode_id": "GN7UD8ARD", "position": 640, "duration": 1440},
    )
    assert progress.json()["position"] == 640


def test_watchlist_add_remove(client: TestClient) -> None:
    sign_in_demo(client)
    removed = client.post(
        "/watchlist/toggle",
        data={"series_id": "GRMG8ZQZR", "return_to": "/watchlist"},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    assert "Your Watchlist is empty" in client.get("/watchlist").text
    client.post(
        "/watchlist/toggle", data={"series_id": "G6NQ5DWZ6", "return_to": "/watchlist"}
    )
    assert "JUJUTSU KAISEN" in client.get("/watchlist").text


def test_profiles_and_settings(client: TestClient) -> None:
    sign_in_demo(client)
    profiles = client.get("/profiles")
    assert "Anime Fan" in profiles.text and "Kids" in profiles.text
    created = client.post(
        "/profiles",
        data={"name": "Night Viewer", "maturity": "Mature", "language": "English (US)"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert "Night Viewer" in client.get("/profiles").text
    saved = client.post(
        "/account/settings",
        data={
            "audio_language": "English",
            "subtitle_language": "English (US)",
            "autoplay": "on",
            "privacy_mode": "Limited personalization",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    settings = client.get("/account/settings?saved=1")
    assert "Preferences saved" in settings.text
    assert "Notifications" in settings.text
    devices = client.get("/account/settings?tab=devices")
    assert "Web Browser" in devices.text


def test_subscription_checkout_states(client: TestClient) -> None:
    register_member(client, "checkout-states@example.test")
    empty = client.post(
        "/checkout",
        data={"plan": "Mega Fan", "term": "monthly", "scenario": "", "terms": ""},
    )
    assert "Choose a valid plan" in empty.text
    declined = client.post(
        "/checkout",
        data={
            "plan": "Mega Fan",
            "term": "monthly",
            "scenario": "sandbox-declined",
            "terms": "on",
        },
    )
    assert "declined this attempt" in declined.text
    retry = client.post(
        "/checkout",
        data={
            "plan": "Mega Fan",
            "term": "monthly",
            "scenario": "sandbox-retry",
            "terms": "on",
        },
    )
    assert "temporarily unavailable" in retry.text


def test_registration_mega_fan_checkout_and_history(client: TestClient) -> None:
    register_member(client, "core-672@example.test")
    result = client.post(
        "/checkout",
        data={
            "plan": "Mega Fan",
            "term": "monthly",
            "scenario": "sandbox-approved",
            "terms": "on",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert result.headers["location"] == "/account/history?created=1"
    history = client.get(result.headers["location"])
    for text in (
        "Mega Fan Monthly",
        "Active",
        "Details",
        "Edit or Cancel",
        "Back to My List",
    ):
        assert text in history.text


def test_checkout_requires_account_and_fields(client: TestClient) -> None:
    response = client.get("/checkout?plan=Mega+Fan&term=monthly")
    assert response.status_code == 401
    assert "Log In Required" in response.text


def test_reset_is_deterministic_and_clears_payment_rows(client: TestClient) -> None:
    sign_in_demo(client)
    first = client.post("/__websitebench/reset").json()
    second = client.post("/__websitebench/reset").json()
    assert (
        first
        == second
        == {"ok": True, "site_id": "crunchyroll", "seed": "crunchyroll-seed-v1"}
    )
    with BACKEND.lifecycle.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM websitebench_payment_flows"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM crunchyroll_profiles WHERE owner=?",
                (f"subject:{DEMO_SUBJECT_ID}",),
            ).fetchone()[0]
            == 2
        )


def test_checkout_rejects_payment_credentials(client: TestClient) -> None:
    register_member(client, "credential-reject@example.test")
    response = client.post(
        "/checkout",
        data={
            "plan": "Mega Fan",
            "term": "monthly",
            "scenario": "sandbox-approved",
            "terms": "on",
            "card_number": "4242424242424242",
            "cvv": "123",
        },
    )
    assert "Payment credentials are forbidden" in response.text
    with BACKEND.lifecycle.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM websitebench_payment_flows"
            ).fetchone()[0]
            == 0
        )


def test_duplicate_approved_checkout_is_idempotent(client: TestClient) -> None:
    register_member(client, "duplicate-672@example.test")
    payload = {
        "plan": "Mega Fan",
        "term": "monthly",
        "scenario": "sandbox-approved",
        "terms": "on",
    }
    first = client.post("/checkout", data=payload, follow_redirects=False)
    second = client.post("/checkout", data=payload, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    with BACKEND.lifecycle.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM websitebench_payment_flows"
            ).fetchone()[0]
            == 1
        )
        row = connection.execute(
            "SELECT owner FROM crunchyroll_subscriptions WHERE payment_scenario='sandbox-approved'"
        ).fetchone()
        assert row is not None
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM crunchyroll_subscriptions WHERE owner=?",
                (row[0],),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM crunchyroll_history WHERE owner=? AND item_type='subscription'",
                (row[0],),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT status FROM websitebench_payment_attempts"
            ).fetchone()[0]
            == "CONSUMED"
        )


def test_actor_business_state_is_isolated(client: TestClient) -> None:
    register_member(client, "actor-a@example.test")
    client.post(
        "/profiles",
        data={"name": "Actor A Only", "maturity": "Mature", "language": "English (US)"},
    )
    client.post(
        "/watchlist/toggle", data={"series_id": "G6NQ5DWZ6", "return_to": "/watchlist"}
    )
    with TestClient(app) as other:
        register_member(other, "actor-b@example.test")
        assert "Actor A Only" not in other.get("/profiles").text
        assert "JUJUTSU KAISEN" not in other.get("/watchlist").text
    assert "Actor A Only" in client.get("/profiles").text
    assert "JUJUTSU KAISEN" in client.get("/watchlist").text


def test_restart_preserves_authenticated_business_state(client: TestClient) -> None:
    register_member(client, "restart@example.test")
    client.post(
        "/profiles",
        data={"name": "Restart Viewer", "maturity": "Teen", "language": "Español"},
    )
    token = client.cookies.get("websitebench-crunchyroll-session")
    assert token
    with TestClient(app) as restarted:
        restarted.cookies.set("websitebench-crunchyroll-session", token)
        assert "Restart Viewer" in restarted.get("/profiles").text


def test_payment_flow_rejects_foreign_owner_and_stale_fingerprint(
    client: TestClient,
) -> None:
    owner_a = "subject:payment-owner-a"
    facts = {"amount_minor": 1399, "currency": "USD", "fingerprint": "a" * 64}
    flow = BACKEND.payments.create_intent(
        owner=owner_a, idempotency_key="foreign-owner-create", **facts
    )
    with pytest.raises(PaymentRejected):
        BACKEND.payments.attempt(
            flow_id=flow["flow_id"],
            owner="subject:payment-owner-b",
            scenario_id="sandbox-approved",
            idempotency_key="foreign-owner-attempt",
            **facts,
        )
    BACKEND.payments.attempt(
        flow_id=flow["flow_id"],
        owner=owner_a,
        scenario_id="sandbox-approved",
        idempotency_key="owner-a-approved",
        **facts,
    )
    with pytest.raises(PaymentRejected):
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            BACKEND.payments.consume_approval(
                connection,
                flow_id=flow["flow_id"],
                owner=owner_a,
                amount_minor=1399,
                currency="USD",
                fingerprint="b" * 64,
            )
    with BACKEND.lifecycle.connection() as connection:
        status = connection.execute(
            "SELECT status FROM websitebench_payment_flows WHERE flow_id=?",
            (flow["flow_id"],),
        ).fetchone()[0]
    assert status == "INVALIDATED"


def test_backup_restore_preserves_business_rows(tmp_path) -> None:
    runtime_path = Path(__file__).resolve().parents[1] / "backend" / "runtime.json"
    backend = SiteBackend.open(
        json.loads(runtime_path.read_text(encoding="utf-8")),
        data_root=tmp_path / "runtime",
        migration_hook=migrate,
        seed_hook=seed,
    )
    backend.lifecycle.initialize()
    backup_owner = "subject:backup-proof"
    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "INSERT INTO crunchyroll_profiles"
            "(owner,profile_id,name,maturity,language,is_active) "
            "VALUES (?,?,?,?,?,0)",
            (
                backup_owner,
                "backup-viewer",
                "Backup Viewer",
                "Teen",
                "English (US)",
            ),
        )
    backup = backend.lifecycle.backup(tmp_path / "backups" / "crunchyroll.sqlite3")
    assert backup["integrity_check"] == "ok"

    with backend.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "DELETE FROM crunchyroll_profiles WHERE owner=?", (backup_owner,)
        )
    with backend.lifecycle.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM crunchyroll_profiles WHERE owner=?",
                (backup_owner,),
            ).fetchone()[0]
            == 0
        )

    restored = backend.lifecycle.restore(Path(backup["path"]))
    assert restored["status"] == "ok"
    with backend.lifecycle.connection() as connection:
        assert (
            connection.execute(
                "SELECT name FROM crunchyroll_profiles WHERE owner=?",
                (backup_owner,),
            ).fetchone()[0]
            == "Backup Viewer"
        )


def test_concurrent_profile_transactions_do_not_lose_writes(client: TestClient) -> None:
    concurrent_owner = "subject:concurrency-proof"

    def create_profile(index: int) -> int:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            connection.execute(
                "INSERT INTO crunchyroll_profiles"
                "(owner,profile_id,name,maturity,language,is_active) "
                "VALUES (?,?,?,?,?,0)",
                (
                    concurrent_owner,
                    f"profile-{index}",
                    f"Concurrent Viewer {index}",
                    "Teen",
                    "English (US)",
                ),
            )
        return index

    with ThreadPoolExecutor(max_workers=4) as pool:
        completed = sorted(pool.map(create_profile, range(12)))
    assert completed == list(range(12))
    with BACKEND.lifecycle.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM crunchyroll_profiles WHERE owner=?",
            (concurrent_owner,),
        ).fetchone()[0]
    assert count == 12


def test_recovery_routes(client: TestClient) -> None:
    help_page = client.get("/help")
    assert "Account Access" in help_page.text
    assert "Fix a Problem" in help_page.text
    contact = client.get("/help/contact")
    assert "does not send a ticket" in contact.text
    missing = client.get("/missing/anime/record/672")
    assert missing.status_code == 404
    assert "Page Not Found" in missing.text
    assert "Browse Popular Anime" in missing.text


def test_pages_have_no_remote_urls(client: TestClient) -> None:
    for path in (
        "/",
        "/videos/popular",
        "/search?q=One+Piece",
        "/series/GRMG8ZQZR/one-piece",
        "/premium",
        "/login",
        "/register",
        "/reset-password",
        "/help",
    ):
        text = client.get(path).text
        assert "https://" not in text
        assert "http://" not in text


def test_runtime_contract_is_local_sandbox() -> None:
    assert BACKEND.config.site_id == "crunchyroll"
    assert BACKEND.config.payments["default_adapter"] == "local-sandbox"
    assert BACKEND.config.payments["stripe_test"] is None
    assert BACKEND.session_cookie["name"].startswith("__Host-")
