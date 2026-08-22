from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import uuid
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ADMIN_TOKEN, BACKEND, APP, LOCAL_COOKIE, business
from websitebench.site_backend import PaymentConflict


def new_browser() -> TestClient:
    return TestClient(APP, base_url="http://127.0.0.1")


def reset(browser: TestClient) -> None:
    response = browser.post(
        "/__admin/reset",
        headers={"X-WebsiteBench-Admin-Token": ADMIN_TOKEN},
    )
    assert response.status_code == 200


def assert_secret_equal(actual: str, expected: str, message: str) -> None:
    if not secrets.compare_digest(actual, expected):
        pytest.fail(message, pytrace=False)


def latest_mail_code(browser: TestClient, purpose: str) -> str:
    response = browser.get("/mailbox/", params={"purpose": purpose})
    assert response.status_code == 200
    match = re.search(r"data-verification-code='([0-9]{6})'", response.text)
    assert match is not None
    return match.group(1)


def register(browser: TestClient, *, name: str = "Alex Rivera") -> tuple[str, str]:
    email = f"member-{uuid.uuid4().hex[:12]}@example.test"
    password = "synthetic-password-123"
    started = browser.post(
        "/signup/",
        data={"phase": "start", "name": name, "email": email, "password": password},
    )
    assert started.status_code == 200
    code = latest_mail_code(browser, "registration")
    verified = browser.post(
        "/signup/",
        data={"phase": "verify", "code": code},
        follow_redirects=False,
    )
    assert verified.status_code == 303
    return email, password


def complete_intake(browser: TestClient) -> None:
    answers = [
        (1, "therapy_type", "individual"),
        (2, "state", "California"),
        (3, "support", "anxiety"),
        (4, "therapist_preference", "no-preference"),
        (5, "therapy_experience", "first-time"),
        (6, "communication", "video"),
        (7, "availability", "weekday-evening"),
        (8, "goal", "coping-tools"),
    ]
    for step, field, value in answers:
        response = browser.post(
            "/get-started/",
            data={"step": str(step), field: value},
            follow_redirects=False,
        )
        assert response.status_code == 303
    result = browser.get("/matches/")
    assert result.status_code == 200
    assert "Your therapist matches" in result.text


def available_slot_id(provider_id: str = "michelle-wilkinson", index: int = 0) -> str:
    with BACKEND.lifecycle.connection() as connection:
        slots = business.provider_slots(connection, provider_id)
    return str(slots[index]["slot_id"])


def create_booking(browser: TestClient) -> str:
    slot_id = available_slot_id()
    selected = browser.post(
        "/book/michelle-wilkinson/",
        data={"slot_id": slot_id},
        follow_redirects=False,
    )
    assert selected.status_code == 303
    booking_id = selected.headers["location"].split("/")[2]
    details = browser.post(
        f"/booking/{booking_id}/details/",
        data={
            "display_name": "Alex Rivera",
            "package_id": "live-session",
            "session_type": "video",
            "special_request": "synthetic-scheduling-request",
            "consent": "yes",
        },
        follow_redirects=False,
    )
    assert details.status_code == 303
    return booking_id


def test_health_runtime_identity_and_no_remote_markup() -> None:
    browser = new_browser()
    assert browser.get("/__websitebench/health").json() == {"status": "ok"}
    assert browser.get("/healthz").json() == {"status": "ok"}
    assert BACKEND.config.site_id == "betterhelp"
    assert BACKEND.lifecycle.database_path.name == "betterhelp.sqlite3"
    for route in ("/", "/login/", "/signup/", "/get-started/", "/therapists/"):
        response = browser.get(route)
        assert response.status_code == 200
        assert "https://betterhelp.com" not in response.text
        assert "https://www.betterhelp.com" not in response.text
        visible = response.text.casefold()
        for marker in ("synthetic", "local fixture", "local member", "simulated payment", "offline clone"):
            assert marker not in visible


def test_fixture_slots_roll_forward_from_the_runtime_date() -> None:
    anchor = datetime(2032, 1, 1, tzinfo=timezone.utc)
    slots = business.fixture_slots(anchor)
    assert len(slots) == 7
    assert all(datetime.fromisoformat(starts_at.replace("Z", "+00:00")) > anchor for _, _, starts_at in slots)
    assert all("2032" in slot_id for slot_id, _, _ in slots)


def test_app_startup_replaces_expired_fixture_slots(tmp_path) -> None:
    database_path = tmp_path / "betterhelp.sqlite3"
    environment = os.environ.copy()
    environment["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(database_path)
    clone_root = os.path.dirname(os.path.dirname(__file__))
    initialized = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=clone_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("DELETE FROM betterhelp_availability")
    connection.execute(
        "INSERT INTO betterhelp_availability(slot_id,provider_id,starts_at) VALUES (?,?,?)",
        ("expired-slot", "michelle-wilkinson", "2020-01-01T00:00:00Z"),
    )
    connection.commit()
    connection.close()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import app; "
                "cm=app.BACKEND.lifecycle.connection(); c=cm.__enter__(); "
                "print(sum(len(app.business.provider_slots(c,p['provider_id'])) "
                "for p in app.business.PROVIDERS)); cm.__exit__(None,None,None)"
            ),
        ],
        cwd=clone_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == len(business.SLOT_TEMPLATES)


def test_v4_migration_backfills_legacy_booking_intake_snapshot() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    business.migrate_v4(connection)
    owner = "account:legacy-fixture"
    answers = {field: next(iter(values)) for field, values in business.INTAKE_FIELDS.values()}
    connection.execute(
        "INSERT INTO betterhelp_intakes(owner,current_step,answers_json,completed_at,updated_at) VALUES (?,?,?,?,?)",
        (owner, 8, json.dumps(answers, sort_keys=True), business.utc_now(), business.utc_now()),
    )
    slot_id = business.provider_slots(connection, "michelle-wilkinson")[0]["slot_id"]
    connection.execute(
        "INSERT INTO betterhelp_bookings(booking_id,owner,provider_id,slot_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        ("BH-LEGACY", owner, "michelle-wilkinson", slot_id, "confirmed", business.utc_now(), business.utc_now()),
    )
    business.migrate_v4(connection)
    snapshot = connection.execute(
        "SELECT intake_snapshot_json FROM betterhelp_bookings WHERE booking_id='BH-LEGACY'"
    ).fetchone()["intake_snapshot_json"]
    connection.close()
    assert json.loads(snapshot) == answers


def test_advice_faq_reviews_and_contact_match_public_page_contracts() -> None:
    browser = new_browser()
    advice = browser.get("/advice/")
    assert advice.status_code == 200
    assert "A Therapist’s Guide to Insurance Credentialing" in advice.text
    assert advice.text.count("class='advice-card'") == 18
    assert "/static/assets/advice-hero.jpg" in advice.text
    faq = browser.get("/faq/")
    assert faq.status_code == 200
    assert faq.text.count("<details>") == 25
    assert "How are the therapists verified?" in faq.text
    reviews = browser.get("/reviews/")
    assert reviews.status_code == 200
    assert "These quotes represent" not in reviews.text
    contact = browser.get("/contact/")
    assert contact.status_code == 200
    assert "I am a registered client and I need support." in contact.text
    assert "3155 Olsen Dr." in contact.text
    submitted = browser.post(
        "/contact/",
        data={
            "first_name": "Alex", "last_name": "Rivera", "email": "contact@example.test",
            "topic": "service-question", "message": "Synthetic service question",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    assert "support request was received" in browser.get(submitted.headers["location"]).text
    assert "support request was received" not in browser.get("/contact/?submitted=fake").text
    request_id = submitted.headers["location"].split("submitted=", 1)[1]
    raw_token = browser.cookies.get(LOCAL_COOKIE)
    with BACKEND.lifecycle.connection() as connection:
        row = connection.execute(
            "SELECT owner FROM betterhelp_support_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
    assert row is not None and row["owner"].startswith("anonymous:")
    assert raw_token and raw_token not in row["owner"]


def test_authenticated_next_page_and_membership_actions() -> None:
    anonymous = new_browser()
    assert anonymous.get("/next/").status_code == 401
    assert anonymous.get("/financialaid/").status_code == 401
    browser = new_browser()
    reset(browser)
    register(browser)
    not_ready = browser.get("/next/", follow_redirects=False)
    assert not_ready.status_code == 303
    assert not_ready.headers["location"] == "/get-started/"
    not_ready_post = browser.post(
        "/next/", data={"action": "start-therapy"}, follow_redirects=False
    )
    assert not_ready_post.status_code == 303
    assert not_ready_post.headers["location"] == "/get-started/"
    complete_intake(browser)
    page = browser.get("/next/")
    assert page.status_code == 200
    assert "More about the therapy process" in page.text
    assert "BetterHelp vs. traditional in-office therapy" in page.text
    assert page.text.count("<tr>") == 13
    assert "Access therapy from anywhere" in page.text
    assert "$65 per week" in page.text
    assert "Language settings" in page.text
    assert "Keep me active" in page.text
    assert "Logout" in page.text
    assert "href='/login/'" not in page.text
    assert "https://www.betterhelp.com" not in page.text
    invalid = browser.post(
        "/next/", data={"action": "benefit-code", "benefit_code": "NO-SUCH-CODE"}
    )
    assert invalid.status_code == 422
    assert "does not apply" in invalid.text
    unsupported = browser.post(
        "/next/", data={"action": "benefit-code", "benefit_code": "SYNTHETIC25"}
    )
    assert unsupported.status_code == 422
    assert "does not apply" in unsupported.text
    exact_action = browser.post(
        "/api/apply_promo_code", data={"promo-code": "SYNTHETIC25"}
    )
    assert exact_action.status_code == 422
    assert "Benefit code does not apply" in exact_action.text
    saved = browser.post(
        "/next/",
        data={"action": "save-settings", "language": "English"},
    )
    assert saved.status_code == 200
    assert "Settings saved." in saved.text
    assert "name='keep_active' value='yes' checked" not in browser.get("/next/").text
    readiness = browser.post(
        "/next/", data={"action": "start-therapy"}, follow_redirects=False
    )
    assert readiness.status_code == 200
    assert "Why don't you want to try therapy?" in readiness.text
    assert "Still not ready" in readiness.text
    assert "I am ready to start" in readiness.text
    assert "Start my trial now" in readiness.text
    assert browser.post(
        "/next/", data={"action": "readiness-start"}, follow_redirects=False
    ).headers["location"] == "/matches/"
    assert browser.post(
        "/next/", data={"action": "readiness-trial"}
    ).status_code == 422
    assert browser.get("/financialaid/").status_code == 200
    assert browser.post("/next/", data={"action": "unknown"}).status_code == 422
    assert browser.post(
        "/next/", data={"action": "start-therapy"}, headers={"Origin": "https://attacker.example"}
    ).status_code == 403


def test_home_therapy_cards_are_local_functional_routes() -> None:
    browser = new_browser()
    home = browser.get("/")
    assert home.status_code == 200
    assert "href='#'" not in home.text
    for therapy_type in ("couples", "teen"):
        response = browser.get(f"/get-started/?therapy_type={therapy_type}")
        assert response.status_code == 200
        assert f"name='therapy_type' value='{therapy_type}' checked" in response.text


def test_individual_skip_entry_persists_type_and_completes() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    state = browser.get("/get-started/?skip_redirect_question=1")
    assert state.status_code == 200
    assert "Which state are you in?" in state.text
    assert "name='therapy_type' value='individual'" in state.text
    answers = [
        (2, "state", "California"),
        (3, "support", "anxiety"),
        (4, "therapist_preference", "no-preference"),
        (5, "therapy_experience", "first-time"),
        (6, "communication", "video"),
        (7, "availability", "weekday-evening"),
        (8, "goal", "coping-tools"),
    ]
    for step, field, value in answers:
        data = {"step": str(step), field: value}
        if step == 2:
            data["therapy_type"] = "individual"
        response = browser.post("/get-started/", data=data, follow_redirects=False)
        assert response.status_code == 303
    assert browser.get("/matches/").status_code == 200


def test_incomplete_intake_cannot_reach_matches_save_or_booking() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    matches = browser.get("/matches/", follow_redirects=False)
    assert matches.status_code == 303 and matches.headers["location"] == "/get-started/"
    saved = browser.post(
        "/providers/michelle-wilkinson/save/", follow_redirects=False
    )
    assert saved.status_code == 303 and saved.headers["location"] == "/get-started/"
    booked = browser.post(
        "/book/michelle-wilkinson/",
        data={"slot_id": available_slot_id()},
        follow_redirects=False,
    )
    assert booked.status_code == 303 and booked.headers["location"] == "/get-started/"
    browser.post("/get-started/", data={"step": "8", "goal": "coping-tools"})
    member = browser.get("/member/")
    assert "1 of 8 completed" in member.text
    assert "8 of 8 completed" not in member.text


def test_past_slots_are_not_listed_or_bookable() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    complete_intake(browser)
    slot_id = available_slot_id()
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "UPDATE betterhelp_availability SET starts_at=? WHERE slot_id=?",
            ("2020-01-01T18:00:00Z", slot_id),
        )
    detail = browser.get("/therapists/michelle-wilkinson/")
    assert slot_id not in detail.text
    rejected = browser.post(
        "/book/michelle-wilkinson/",
        data={"slot_id": slot_id},
    )
    assert rejected.status_code == 422
    assert "future appointment time" in rejected.text


def _local_mailbox_sidecar_type():
    mailbox_path = Path(__file__).resolve().parents[4] / "src/websitebench/harbor/mailbox.py"
    spec = importlib.util.spec_from_file_location("betterhelp_test_mailbox", mailbox_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.LocalMailboxSidecar


def test_registration_delivers_code_to_harbor_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = new_browser()
    reset(browser)
    email = f"mailbox-{uuid.uuid4().hex[:12]}@example.test"
    namespace = f"betterhelp-test-{uuid.uuid4().hex}"
    capability = secrets.token_urlsafe(32)
    sidecar_type = _local_mailbox_sidecar_type()
    with sidecar_type(smtp_port=0, http_port=0) as mailbox:
        mailbox.register_namespace(namespace, capability)
        monkeypatch.setenv("WEBSITEBENCH_SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("WEBSITEBENCH_SMTP_PORT", str(mailbox.smtp_port))
        monkeypatch.setenv("WEBSITEBENCH_MAILBOX_NAMESPACE", namespace)
        monkeypatch.setenv("WEBSITEBENCH_MAILBOX_CAPABILITY", capability)
        started = browser.post(
            "/signup/",
            data={
                "phase": "start",
                "name": "Alex Rivera",
                "email": email,
                "password": "synthetic-password-123",
            },
        )
        assert started.status_code == 200
        delivered_code = latest_mail_code(browser, "registration")
        query = urllib.parse.urlencode({"recipient": email})
        request = urllib.request.Request(
            f"{mailbox.url}/api/namespaces/{urllib.parse.quote(namespace)}/messages/latest?{query}",
            headers={"Authorization": f"Bearer {capability}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            message = json.load(response)
        assert_secret_equal(
            str(message["otp"]),
            delivered_code,
            "mailbox verification code did not match the registration challenge",
        )
        assert message["recipients"] == [email]
        assert message["subject"] == "Verify your BetterHelp account"


def test_verification_inbox_is_loopback_and_session_isolated() -> None:
    owner = new_browser()
    reset(owner)
    started = owner.post(
        "/signup/",
        data={
            "phase": "start",
            "name": "Alex Rivera",
            "email": f"isolated-{uuid.uuid4().hex[:12]}@example.test",
            "password": "synthetic-password-123",
        },
    )
    assert started.status_code == 200
    assert "Open verification inbox" in started.text
    inbox = owner.get("/mailbox/", params={"purpose": "registration"})
    assert inbox.status_code == 200
    assert re.search(r"data-verification-code='[0-9]{6}'", inbox.text)

    other = new_browser()
    unavailable = other.get("/mailbox/", params={"purpose": "registration"})
    assert unavailable.status_code == 404
    assert "data-verification-code" not in unavailable.text

    remote = owner.get(
        "/mailbox/",
        params={"purpose": "registration"},
        headers={"host": "clone.example.test"},
    )
    assert remote.status_code == 403
    assert "data-verification-code" not in remote.text

    unsupported = owner.get("/mailbox/", params={"purpose": "billing"})
    assert unsupported.status_code == 422
    assert "data-verification-code" not in unsupported.text


def test_admin_mail_code_endpoint_is_not_exposed() -> None:
    browser = new_browser()
    reset(browser)
    response = browser.get(
        "/__admin/mail-code",
        params={"purpose": "registration"},
        headers={"X-WebsiteBench-Admin-Token": ADMIN_TOKEN},
    )
    assert response.status_code == 404

def test_registration_requires_local_verification_and_login_is_persistent() -> None:
    browser = new_browser()
    reset(browser)
    email = f"verify-{uuid.uuid4().hex[:12]}@example.test"
    password = "synthetic-password-123"
    browser.post(
        "/signup/",
        data={"phase": "start", "name": "Alex Rivera", "email": email, "password": password},
    )
    code = latest_mail_code(browser, "registration")
    assert not APP.state.auth.account_exists(email)
    assert browser.post(
        "/signup/", data={"phase": "verify", "code": "000000"}
    ).status_code == 422
    assert browser.post(
        "/signup/", data={"phase": "verify", "code": code}, follow_redirects=False
    ).status_code == 303
    assert APP.state.auth.account_exists(email)
    assert browser.post("/logout/", follow_redirects=False).status_code == 303
    assert browser.post(
        "/login/", data={"email": email, "password": "wrong-password"}
    ).status_code == 401
    assert browser.post(
        "/login/", data={"email": email, "password": password}, follow_redirects=False
    ).status_code == 303
    assert "Alex Rivera" in browser.get("/member/").text


def test_rejects_real_identity_and_duplicate_registration() -> None:
    browser = new_browser()
    reset(browser)
    rejected = browser.post(
        "/signup/",
        data={"phase": "start", "name": "Real Person", "email": "person@example.com", "password": "synthetic-password-123"},
    )
    assert rejected.status_code == 422
    assert "synthetic" not in rejected.text.casefold()
    email, password = register(browser)
    browser.post("/logout/", follow_redirects=False)
    assert browser.post(
        "/signup/",
        data={"phase": "start", "name": "Alex Rivera", "email": email, "password": password},
    ).status_code == 409


def test_password_reset_has_uniform_public_response_and_rotates_password() -> None:
    browser = new_browser()
    reset(browser)
    email, old_password = register(browser)
    browser.post("/logout/", follow_redirects=False)

    attacker = new_browser()
    unauthorized = attacker.post(
        "/password-reset/", data={"phase": "start", "email": email}
    )
    assert unauthorized.status_code == 200
    assert attacker.get(
        "/mailbox/", params={"purpose": "password-reset"}
    ).status_code == 404

    known = browser.post("/password-reset/", data={"phase": "start", "email": email})
    code = latest_mail_code(browser, "password-reset")
    assert known.status_code == 200
    other = new_browser()
    unknown = other.post(
        "/password-reset/",
        data={"phase": "start", "email": f"unknown-{uuid.uuid4().hex[:8]}@example.test"},
    )
    assert unknown.status_code == known.status_code
    assert "If the account exists" in known.text and "If the account exists" in unknown.text
    invalid = browser.post(
        "/password-reset/",
        data={"phase": "complete", "code": "000000", "new_password": "new-synthetic-password-123"},
    )
    assert invalid.status_code == 422
    assert "id='reset-code'" in invalid.text
    assert "name='phase' value='complete'" in invalid.text
    completed = browser.post(
        "/password-reset/",
        data={"phase": "complete", "code": code, "new_password": "new-synthetic-password-123"},
        follow_redirects=False,
    )
    assert completed.status_code == 303
    browser.post("/logout/", follow_redirects=False)
    assert browser.post("/login/", data={"email": email, "password": old_password}).status_code == 401
    assert browser.post(
        "/login/", data={"email": email, "password": "new-synthetic-password-123"}, follow_redirects=False
    ).status_code == 303


def test_mailbox_delivery_failure_is_reported_without_exposing_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = new_browser()
    reset(browser)
    email, _ = register(browser)
    browser.post("/logout/", follow_redirects=False)
    monkeypatch.setenv("WEBSITEBENCH_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBSITEBENCH_SMTP_PORT", "1")
    monkeypatch.setenv("WEBSITEBENCH_MAILBOX_NAMESPACE", "betterhelp-unavailable")
    monkeypatch.setenv("WEBSITEBENCH_MAILBOX_CAPABILITY", secrets.token_urlsafe(32))
    registration = browser.post(
        "/signup/",
        data={
            "phase": "start",
            "name": "Alex Rivera",
            "email": f"unavailable-{uuid.uuid4().hex[:12]}@example.test",
            "password": "synthetic-password-123",
        },
    )
    assert registration.status_code == 503
    assert "data-verification-code" not in registration.text
    recovery = browser.post(
        "/password-reset/",
        data={"phase": "start", "email": email},
    )
    assert recovery.status_code == 503
    assert "data-verification-code" not in recovery.text


def test_intake_is_validated_persisted_and_completed_after_eight_steps() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    invalid = browser.post("/get-started/", data={"step": "1", "therapy_type": ""})
    assert invalid.status_code == 422
    assert "Choose one answer" in invalid.text
    complete_intake(browser)
    assert "8 of 8 completed" in browser.get("/member/").text
    restarted = subprocess.check_output(
        [sys.executable, "-c", "import app; print(app.business.count_completed_intakes(app.BACKEND))"],
        text=True,
    ).strip()
    assert int(restarted) >= 1


def test_provider_search_filter_detail_save_and_no_results() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    complete_intake(browser)
    results = browser.get("/therapists/?q=anxiety&specialty=anxiety")
    assert results.status_code == 200
    assert "Michelle Wilkinson" in results.text
    assert browser.get("/therapists/?q=no-such-specialist").text.count("No therapists found") == 1
    assert browser.get("/therapists/michelle-wilkinson/").status_code == 200
    descending = browser.get("/therapists/?sort=name-desc")
    assert descending.text.index("Virginia Truglio") < descending.text.index("Susan Hargett")
    soonest = browser.get("/therapists/?sort=availability")
    assert soonest.text.index("Michelle Wilkinson") < soonest.text.index("Virginia Truglio") < soonest.text.index("Susan Hargett")
    assert "Soonest availability" in soonest.text
    saved = browser.post("/providers/michelle-wilkinson/save/", follow_redirects=False)
    assert saved.status_code == 303
    assert "Michelle Wilkinson" in browser.get("/member/saved/").text
    booking_id = create_booking(browser)
    assert browser.post(
        f"/booking/{booking_id}/payment/",
        data={"scenario_id": "sandbox-approved"},
        follow_redirects=False,
    ).status_code == 303
    shifted = browser.get("/therapists/?sort=availability")
    assert shifted.text.index("Virginia Truglio") < shifted.text.index("Michelle Wilkinson")
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "UPDATE betterhelp_availability SET starts_at='2020-01-01T00:00:00Z' WHERE provider_id='susan-hargett'"
        )
    no_susan_slots = browser.get("/therapists/?sort=availability")
    assert no_susan_slots.text.index("Susan Hargett") > no_susan_slots.text.index("Michelle Wilkinson")


def test_booking_payment_confirmation_history_modify_cancel_and_mail() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    complete_intake(browser)
    booking_id = create_booking(browser)
    forbidden = browser.post(
        f"/booking/{booking_id}/payment/",
        data={"scenario_id": "sandbox-approved", "card_number": "forbidden"},
    )
    assert forbidden.status_code == 422
    approved = browser.post(
        f"/booking/{booking_id}/payment/",
        data={"scenario_id": "sandbox-approved"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    confirmation = browser.get(approved.headers["location"])
    assert "Session confirmed" in confirmation.text
    assert "Confirmation is available in My sessions" in confirmation.text
    assert "Live counseling session" in confirmation.text
    assert "Video session" in confirmation.text
    assert "Scheduling request" in confirmation.text
    assert "$70.00 USD" in confirmation.text
    assert "Anxiety" in confirmation.text
    assert "Weekday evenings" in confirmation.text
    assert "Secure online session" in confirmation.text
    browser.post("/get-started/", data={"step": "3", "support": "stress"})
    unchanged_confirmation = browser.get(approved.headers["location"])
    assert "Anxiety" in unchanged_confirmation.text
    assert ">Stress<" not in unchanged_confirmation.text
    with BACKEND.lifecycle.connection() as connection:
        booking = connection.execute(
            "SELECT package_id,session_type,special_request FROM betterhelp_bookings WHERE booking_id=?",
            (booking_id,),
        ).fetchone()
    assert tuple(booking) == ("live-session", "video", "synthetic-scheduling-request")
    history = browser.get("/member/bookings/")
    assert booking_id in history.text
    assert f"data-booking-id='{booking_id}'" in history.text
    assert f"data-reschedule-booking='{booking_id}'" in history.text
    assert f"data-cancel-booking='{booking_id}'" in history.text
    assert f"data-review-booking='{booking_id}'" not in history.text
    changed = browser.post(
        f"/booking/{booking_id}/manage/",
        data={"action": "reschedule", "slot_id": available_slot_id()},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    cancelled = browser.post(
        f"/booking/{booking_id}/manage/", data={"action": "cancel"}, follow_redirects=False
    )
    assert cancelled.status_code == 303
    assert "cancelled" in browser.get("/member/bookings/").text.lower()
    cancelled_confirmation = browser.get(f"/booking/{booking_id}/confirmation/")
    assert "Session cancelled" in cancelled_confirmation.text
    assert "This appointment was cancelled" in cancelled_confirmation.text
    assert "LOCAL_SIMULATION" not in cancelled_confirmation.text
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "UPDATE betterhelp_bookings SET intake_snapshot_json='{}' WHERE booking_id=?",
            (booking_id,),
        )
    legacy_confirmation = browser.get(f"/booking/{booking_id}/confirmation/")
    assert "Matching preference summary is unavailable for this earlier appointment." in legacy_confirmation.text


def test_booking_details_require_supported_package_session_and_request() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    complete_intake(browser)
    selected = browser.post(
        "/book/michelle-wilkinson/",
        data={"slot_id": available_slot_id()},
        follow_redirects=False,
    )
    booking_id = selected.headers["location"].split("/")[2]
    page = browser.get(f"/booking/{booking_id}/details/")
    assert "Session format" in page.text
    assert "Special requests" in page.text
    invalid_options = (
        {"package_id": "unsupported", "session_type": "video", "special_request": "none"},
        {"package_id": "live-session", "session_type": "unsupported", "special_request": "none"},
        {"package_id": "live-session", "session_type": "video", "special_request": "unsupported"},
    )
    for options in invalid_options:
        rejected = browser.post(
            f"/booking/{booking_id}/details/",
            data={"display_name": "Alex Rivera", "consent": "yes", **options},
        )
        assert rejected.status_code == 422


def test_payment_declined_retry_and_foreign_owner_fail_closed() -> None:
    first = new_browser()
    reset(first)
    register(first)
    complete_intake(first)
    declined_id = create_booking(first)
    declined = first.post(
        f"/booking/{declined_id}/payment/", data={"scenario_id": "sandbox-declined"}
    )
    assert declined.status_code == 402 and "declined" in declined.text.lower()
    assert "simulated" not in declined.text.casefold()
    retry_id = create_booking(first)
    retry = first.post(
        f"/booking/{retry_id}/payment/", data={"scenario_id": "sandbox-retry"}
    )
    assert retry.status_code == 409 and "try again" in retry.text.lower()
    assert "simulated" not in retry.text.casefold()
    second = new_browser()
    register(second)
    assert second.get(f"/booking/{declined_id}/details/").status_code == 404
    assert second.post(
        f"/booking/{declined_id}/manage/", data={"action": "cancel"}
    ).status_code == 404


def test_v3_retryable_payment_flow_survives_v4_snapshot_backfill() -> None:
    browser = new_browser()
    reset(browser)
    register(browser)
    complete_intake(browser)
    booking_id = create_booking(browser)
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        owner = connection.execute(
            "SELECT owner FROM betterhelp_bookings WHERE booking_id=?", (booking_id,)
        ).fetchone()["owner"]
        connection.execute(
            "UPDATE betterhelp_bookings SET intake_snapshot_json='{}' WHERE booking_id=?",
            (booking_id,),
        )
        row = business.owned_booking(connection, owner, booking_id)
        legacy_fingerprint = business.payment_fingerprint(row, include_intake_snapshot=False)
        facts = {
            "owner": f"booking:{booking_id}",
            "amount_minor": int(row["amount_minor"]),
            "currency": "USD",
            "fingerprint": legacy_fingerprint,
        }
        flow = BACKEND.payments.create_intent(
            **facts,
            idempotency_key=f"betterhelp.create:{booking_id}",
            connection=connection,
        )
        retryable = BACKEND.payments.attempt(
            flow_id=flow["flow_id"],
            **facts,
            scenario_id="sandbox-retry",
            idempotency_key=f"betterhelp.attempt:{booking_id}:sandbox-retry",
            connection=connection,
        )
        assert retryable["status"] == "RETRYABLE"
        business.migrate_v4(connection)
        snapshot = connection.execute(
            "SELECT intake_snapshot_json FROM betterhelp_bookings WHERE booking_id=?",
            (booking_id,),
        ).fetchone()["intake_snapshot_json"]
        assert json.loads(snapshot)["support"] == "anxiety"
    approved = browser.post(
        f"/booking/{booking_id}/payment/",
        data={"scenario_id": "sandbox-approved"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    assert "Session confirmed" in browser.get(approved.headers["location"]).text


@pytest.mark.parametrize(
    ("column", "changed_value"),
    (
        ("amount_minor", 7100),
        ("provider_id", "susan-hargett"),
        ("package_id", "changed-package"),
        ("session_type", "phone"),
        ("special_request", "synthetic-accessibility-request"),
    ),
)
def test_v3_payment_compat_rejects_other_immutable_fact_changes(
    column: str, changed_value: object
) -> None:
    browser = new_browser()
    reset(browser)
    email, _ = register(browser)
    complete_intake(browser)
    booking_id = create_booking(browser)
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        owner = connection.execute(
            "SELECT owner FROM betterhelp_bookings WHERE booking_id=?", (booking_id,)
        ).fetchone()["owner"]
        connection.execute(
            "UPDATE betterhelp_bookings SET intake_snapshot_json='{}' WHERE booking_id=?",
            (booking_id,),
        )
        row = business.owned_booking(connection, owner, booking_id)
        legacy_fingerprint = business.payment_fingerprint(row, include_intake_snapshot=False)
        BACKEND.payments.create_intent(
            owner=f"booking:{booking_id}",
            amount_minor=int(row["amount_minor"]),
            currency="USD",
            fingerprint=legacy_fingerprint,
            idempotency_key=f"betterhelp.create:{booking_id}",
            connection=connection,
        )
        business.migrate_v4(connection)
        connection.execute(
            f"UPDATE betterhelp_bookings SET {column}=? WHERE booking_id=?",
            (changed_value, booking_id),
        )
    with pytest.raises(PaymentConflict, match="immutable facts"):
        business.pay_booking(BACKEND, owner, booking_id, email, "sandbox-approved")


def test_same_slot_confirmation_conflict_is_a_business_error() -> None:
    first = new_browser()
    reset(first)
    register(first)
    complete_intake(first)
    first_booking = create_booking(first)
    second = new_browser()
    register(second)
    complete_intake(second)
    second_booking = create_booking(second)
    assert first.post(
        f"/booking/{first_booking}/payment/", data={"scenario_id": "sandbox-approved"}, follow_redirects=False
    ).status_code == 303
    conflict = second.post(
        f"/booking/{second_booking}/payment/", data={"scenario_id": "sandbox-approved"}
    )
    assert conflict.status_code == 409
    assert "just booked by another member" in conflict.text


def test_review_contact_permissions_help_and_not_found() -> None:
    anonymous = new_browser()
    assert anonymous.get("/member/bookings/").status_code == 401
    assert anonymous.post("/contact/", data={"topic": "account", "message": "I need help with my account."}).status_code == 422
    browser = new_browser()
    reset(browser)
    register(browser)
    complete_intake(browser)
    booking_id = create_booking(browser)
    browser.post(f"/booking/{booking_id}/payment/", data={"scenario_id": "sandbox-approved"})
    assert f"data-review-booking='{booking_id}'" not in browser.get("/member/bookings/").text
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        slot_id = connection.execute(
            "SELECT slot_id FROM betterhelp_bookings WHERE booking_id=?",
            (booking_id,),
        ).fetchone()["slot_id"]
        connection.execute(
            "UPDATE betterhelp_availability SET starts_at=? WHERE slot_id=?",
            ("2020-01-01T18:00:00Z", slot_id),
        )
    assert f"data-review-booking='{booking_id}'" in browser.get("/member/bookings/").text
    review = browser.post(
        f"/booking/{booking_id}/review/",
        data={"rating": "5", "comment": "This session was helpful."},
        follow_redirects=False,
    )
    assert review.status_code == 303
    with BACKEND.lifecycle.connection() as connection:
        saved_review = connection.execute(
            "SELECT rating,comment FROM betterhelp_reviews WHERE booking_id=?",
            (booking_id,),
        ).fetchone()
    assert saved_review["rating"] == 5
    assert saved_review["comment"] == "This session was helpful."
    assert browser.post(
        f"/booking/{booking_id}/review/",
        data={"rating": "5", "comment": "Synthetic note: patient diagnosis depression"},
    ).status_code == 422
    assert browser.post(
        "/contact/", data={"topic": "booking", "first_name": "Alex", "last_name": "Rivera", "email": "contact@example.test", "message": "I need help with my account."}, follow_redirects=False
    ).status_code == 303
    assert browser.post(
        "/contact/", data={"topic": "booking", "message": "Synthetic note: medication list"}
    ).status_code == 422
    assert browser.get("/help/").status_code == 200
    assert browser.get("/definitely-missing").status_code == 404
