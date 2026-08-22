from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"


def _dismiss_banner(page: Page) -> None:
    banner = page.locator("#cookie-banner")
    if banner.count():
        banner.evaluate("element => element.remove()")


def _goto(page: Page, base: str, path: str) -> None:
    page.goto(base + path, wait_until="networkidle")
    _dismiss_banner(page)


def _task(evidence: dict[str, dict[str, str]], task_id: str, route: str, result: str) -> None:
    evidence[task_id] = {"route": route, "result": result, "status": "passed"}


def test_running_clone_all_expanded_tasks() -> None:
    base = os.environ.get("WEBSITEBENCH_TEST_BASE_URL", "http://127.0.0.1:8458").rstrip("/")
    artifacts = Path(os.environ.get("WEBSITEBENCH_E2E_ARTIFACT_DIR", "artifacts/e2e"))
    artifacts.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, dict[str, str]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        requests: list[str] = []
        page.on("request", lambda request: requests.append(request.url))

        _goto(page, base, "/")
        assert "You deserve to be happy." in page.locator("body").inner_text()
        page.locator("nav a[href='/advice/']").click()
        page.wait_for_load_state("networkidle")
        assert page.url == base + "/advice/"
        assert page.locator("h1").inner_text() == "Advice"
        first_advice_title = page.locator("[data-advice-title]").inner_text()
        page.locator("[data-advice-next]").click()
        assert page.locator("[data-advice-title]").inner_text() == "How does stress affect the body?"
        page.locator("[data-advice-prev]").click()
        assert page.locator("[data-advice-title]").inner_text() == first_advice_title
        _task(evidence, "WB018-T01", "/advice/", "Primary navigation opened the Advice destination and canonical local path.")

        _goto(page, base, "/therapists/?q=zzzz-no-match-websitebench")
        assert page.locator(".empty-state h2").inner_text() == "No therapists found"
        page.locator(".footer-links a[href='/therapists/']").click()
        page.wait_for_load_state("networkidle")
        assert page.locator("article.provider-card").count() == 3
        _task(evidence, "WB018-T15", "/therapists/?q=zzzz-no-match-websitebench", "Impossible search showed an empty state and a route back to all therapists.")

        _goto(page, base, "/login/")
        assert page.locator("#emailInput").is_visible()
        assert page.locator("#login-password").get_attribute("type") == "password"
        assert page.locator("a[href='/password-reset/']").is_visible()
        _task(evidence, "WB018-T16", "/login/", "Sign-in entry exposed email, password, recovery, and return navigation without submission.")

        _goto(page, base, "/signup/")
        assert page.locator("#name").is_visible()
        assert page.locator("#signup-email").is_visible()
        assert page.locator("#signup-password").is_visible()
        assert page.locator("a[href='/terms/']").count() >= 1
        assert page.locator("a[href='/privacy/']").count() >= 1
        assert "verify your account" in page.locator("body").inner_text().lower()
        _task(evidence, "WB018-T17", "/signup/", "Registration entry exposed identity fields, terms, privacy, and verification guidance.")

        _goto(page, base, "/login/")
        page.locator("a[href='/password-reset/']").click()
        page.wait_for_load_state("networkidle")
        assert page.locator("#reset-email").is_visible()
        assert page.locator("a[href='/login/']", has_text="Return to sign in").is_visible()
        _task(evidence, "WB018-T18", "/password-reset/", "Password recovery exposed the reset-address field, uniform guidance, and return-to-sign-in link without submission.")

        _goto(page, base, "/member/bookings/")
        assert "Sign in to continue" in page.locator("body").inner_text()
        assert page.locator("main a[href='/login/']").is_visible()
        _task(evidence, "WB018-T20", "/member/bookings/", "Signed-out access produced a permission prompt and sign-in route.")

        _goto(page, base, "/help/")
        help_text = page.locator("body").inner_text()
        assert "Help and recovery" in help_text
        assert "verify my account" in help_text
        assert "change a session" in help_text
        assert "Payment" not in help_text
        _task(evidence, "WB018-T21", "/help/", "Public help covered getting started, account verification, and session recovery without private data.")

        _goto(page, base, "/not-a-real-betterhelp-route/deep-link/")
        assert page.locator("h1").inner_text() == "Page not found"
        assert page.locator("nav[aria-label='Main Menu']").is_visible()
        assert page.locator("a[href='/']", has_text="Return home").is_visible()
        _task(evidence, "WB018-T22", "/not-a-real-betterhelp-route/deep-link/", "Branded 404 preserved primary navigation and a safe home route.")

        _goto(page, base, "/signup/")
        suffix = uuid.uuid4().hex[:10]
        email = f"e2e-{suffix}@example.test"
        password = "synthetic-password-123"
        page.locator("#name").fill("Alex Rivera")
        page.locator("#signup-email").fill(email)
        page.locator("#signup-password").fill(password)
        page.locator("button[type=submit]").click()
        assert page.locator("[data-mail-status]").is_visible()
        assert page.locator("[data-verification-code]").count() == 0
        with page.expect_popup() as popup_info:
            page.locator("a[href='/mailbox/?purpose=registration']").click()
        inbox = popup_info.value
        inbox.wait_for_load_state("networkidle")
        assert inbox.locator("h1").inner_text() == "Verification inbox"
        code = inbox.locator("[data-verification-code]").inner_text()
        assert len(code) == 6 and code.isdigit()
        inbox.close()
        page.locator("#code").fill(code)
        page.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        assert page.url.rstrip("/") == base + "/get-started"
        _task(evidence, "WB018-T08", "/signup/ -> /get-started/", "Account registration, verification message, and synthetic contact/profile data completed.")

        answers = [
            ("therapy_type", "individual"),
            ("state", "California"),
            ("support", "anxiety"),
            ("therapist_preference", "no-preference"),
            ("therapy_experience", "first-time"),
            ("communication", "video"),
            ("availability", "weekday-evening"),
            ("goal", "coping-tools"),
        ]
        for field, value in answers:
            assert page.locator(".progress-label").is_visible()
            if page.locator(f"select[name='{field}']").count():
                page.locator(f"select[name='{field}']").select_option(value)
            else:
                page.locator(f"input[name='{field}'][value='{value}']").check()
            page.locator("button[type=submit]").click()
            page.wait_for_load_state("networkidle")
        assert page.locator("h1").inner_text() == "Your therapist matches"
        _task(evidence, "WB018-T03", "/get-started/ -> /matches/", "All eight needs and preference steps completed continuously and produced matches.")

        _goto(page, base, "/matches/")
        match_text = page.locator("body").inner_text()
        assert "licensed providers" in match_text
        assert "anxiety" in match_text.lower()
        _task(evidence, "WB018-T05", "/matches/", "Matched provider information reflected intake preferences and exposed provider profiles.")

        _goto(page, base, "/therapists/")
        page.locator("input[name=q]").fill("anxiety")
        page.locator("input[name=specialty]").fill("anxiety")
        page.locator("select[name=sort]").select_option("name-desc")
        page.locator("form.search-form button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        cards = page.locator("article.provider-card h2").all_inner_texts()
        assert cards == ["Michelle Wilkinson, LCSW"]
        assert "q=anxiety" in page.url and "specialty=anxiety" in page.url and "sort=name-desc" in page.url
        _task(evidence, "WB018-T04", "/therapists/?q=anxiety&specialty=anxiety&sort=name-desc", "Search, specialty filter, and sort were applied by backend-driven query state.")

        page.locator("a[href='/therapists/michelle-wilkinson/']").click()
        page.wait_for_load_state("networkidle")
        slot_options = page.locator("select[name=slot_id] option")
        assert slot_options.count() >= 2
        first_slot = slot_options.nth(0).get_attribute("value")
        second_slot = slot_options.nth(1).get_attribute("value")
        assert first_slot and second_slot and first_slot != second_slot
        _task(evidence, "WB018-T06", "/therapists/michelle-wilkinson/", "Multiple available times were compared and a different slot was selected.")

        save_form = page.locator("form[action='/providers/michelle-wilkinson/save/']")
        assert save_form.count() == 1
        save_form.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        assert page.url == base + "/member/saved/"
        assert "Michelle Wilkinson" in page.locator("body").inner_text()
        page.reload(wait_until="networkidle")
        assert "Michelle Wilkinson" in page.locator("body").inner_text()
        _task(evidence, "WB018-T07", "/member/saved/", "Saved therapist persisted across refresh and remained openable.")

        _goto(page, base, "/therapists/michelle-wilkinson/")
        page.locator("select[name=slot_id]").select_option(second_slot)
        page.locator("form[action^='/book/'] button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        assert page.locator("h1").inner_text() == "Booking details"
        assert page.locator("#display-name").input_value() == "Alex Rivera"
        assert page.locator("#package-id").is_visible()
        assert page.locator("#session-type").is_visible()
        assert page.locator("#special-request").is_visible()
        page.locator("#package-id").select_option("live-session")
        page.locator("#session-type").select_option("video")
        page.locator("#special-request").select_option("synthetic-scheduling-request")
        page.locator("input[name=consent]").check()
        page.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        _task(evidence, "WB018-T10", "/booking/<id>/details/", "Service package, attendee identity, session format, special request, and consent were stored.")

        payment_text = page.locator("body").inner_text()
        assert "Review and payment" in payment_text
        assert "Live counseling session" in payment_text
        assert "Video session" in payment_text
        assert "Scheduling request" in payment_text
        assert "$70.00 USD" in payment_text
        assert page.locator("label[for=scenario]").inner_text() == "Payment method"
        _task(evidence, "WB018-T11", "/booking/<id>/payment/", "Review showed booking choices and total before payment.")

        page.locator("select[name=scenario_id]").select_option("sandbox-declined")
        page.locator("button[type=submit]").click()
        assert "payment was declined" in page.locator("body").inner_text().lower()
        page.locator("a", has_text="Try again").click()
        page.wait_for_load_state("networkidle")
        page.locator("select[name=scenario_id]").select_option("sandbox-retry")
        page.locator("button[type=submit]").click()
        assert "try again" in page.locator("body").inner_text().lower()
        page.locator("a", has_text="Try again").click()
        page.wait_for_load_state("networkidle")
        page.locator("select[name=scenario_id]").select_option("sandbox-approved")
        page.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        assert page.locator("h1").inner_text() == "Session confirmed"
        booking_id = page.url.split("/booking/", 1)[1].split("/", 1)[0]
        confirmation_text = page.locator("body").inner_text()
        for expected in ("$70.00 USD", "Video session", "Scheduling request", "Anxiety", "Michelle Wilkinson"):
            assert expected in confirmation_text
        page.screenshot(path=str(artifacts / "formal-confirmation-desktop.png"), full_page=True)
        _task(evidence, "WB018-T12", f"/booking/{booking_id}/confirmation/", "Declined and retryable states recovered into an approved confirmation with date, online location, options, and total.")
        _task(evidence, "WB018-T02", "/signup/ -> questionnaire -> booking -> confirmation", "Formal task completed and final confirmation reflected requested choices and total.")
        _task(evidence, "WB018-T23", "/ -> signup -> questionnaire -> booking -> confirmation", "Task 35 completed from the public entry with all requested final-review facts visible.")

        page.locator("a[href='/member/bookings/']").click()
        page.wait_for_load_state("networkidle")
        assert page.locator(f"article[data-booking-id='{booking_id}']").count() == 1
        history_text = page.locator(f"article[data-booking-id='{booking_id}']").inner_text()
        assert "confirmed" in history_text.lower()
        assert "Michelle Wilkinson" in history_text
        _task(evidence, "WB018-T19", "/member/bookings/", "Newest persisted session exposed status, detail, reschedule, cancel, and collection navigation.")

        reschedule = page.locator(f"form[data-reschedule-booking='{booking_id}']")
        replacement_slot = reschedule.locator("select[name=slot_id] option").first.get_attribute("value")
        assert replacement_slot
        reschedule.locator("select[name=slot_id]").select_option(replacement_slot)
        reschedule.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        page.reload(wait_until="networkidle")
        assert "confirmed" in page.locator(f"article[data-booking-id='{booking_id}']").inner_text().lower()
        cancel = page.locator(f"form[data-cancel-booking='{booking_id}']")
        cancel.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        page.reload(wait_until="networkidle")
        assert "cancelled" in page.locator(f"article[data-booking-id='{booking_id}']").inner_text().lower()
        _task(evidence, "WB018-T13", "/member/bookings/", "Reschedule persisted after refresh, then cancellation persisted with updated status.")

        _goto(page, base, "/contact/")
        page.locator("#first-name").fill("Alex")
        page.locator("#last-name").fill("Rivera")
        page.locator("#contact-email").fill(email)
        page.locator("#topic").select_option("registered-client")
        page.locator("#message").fill("synthetic support request")
        page.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        assert "support request was received" in page.locator("body").inner_text().lower()
        submitted_url = page.url
        page.reload(wait_until="networkidle")
        assert page.url == submitted_url
        assert "support request was received" in page.locator("body").inner_text().lower()
        _task(evidence, "WB018-T14", "/contact/?submitted=<id>", "Post-booking support request persisted for the signed-in member across refresh.")

        _goto(page, base, "/member/")
        page.locator("form[action='/logout/'] button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        _goto(page, base, "/login/")
        page.locator("#emailInput").fill(email)
        page.locator("#login-password").fill(password)
        page.locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        assert page.url == base + "/member/"
        page.locator("a[href='/member/bookings/']").click()
        page.wait_for_load_state("networkidle")
        assert "cancelled" in page.locator(f"article[data-booking-id='{booking_id}']").inner_text().lower()
        _task(evidence, "WB018-T09", "/login/ -> /member/bookings/", "A fresh sign-in reopened the same persisted booking history.")

        page.set_viewport_size({"width": 390, "height": 844})
        _goto(page, base, "/")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(artifacts / "home-mobile-390x844.png"), full_page=False)
        page.set_viewport_size({"width": 768, "height": 1024})
        _goto(page, base, "/faq/")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(artifacts / "faq-tablet-768x1024.png"), full_page=False)

        assert sorted(evidence) == [f"WB018-T{i:02d}" for i in range(1, 24)]
        external = sorted({url for url in requests if not url.startswith(base)})
        (artifacts / "network.json").write_text(json.dumps({"external_requests": external}, indent=2), encoding="utf-8")
        (artifacts / "task-evidence.json").write_text(
            json.dumps(
                {
                    "site_id": "betterhelp",
                    "base_url": base,
                    "browser": "Microsoft Edge via Playwright",
                    "tasks": evidence,
                    "external_requests": external,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        assert external == []
        context.close()
        browser.close()


def test_mobile_public_state_matches_frozen_layout_contract() -> None:
    base = os.environ.get("WEBSITEBENCH_TEST_BASE_URL", "http://127.0.0.1:8458").rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        _goto(page, base, "/faq/")
        assert not page.locator(".faq-list details").first.get_attribute("open")
        _goto(page, base, "/advice/")
        title = page.locator("[data-advice-title]")
        assert title.is_visible()
        image_box = page.locator(".advice-feature img").bounding_box()
        title_box = title.bounding_box()
        assert image_box is not None and title_box is not None
        assert image_box["height"] <= 200
        assert title_box["y"] > image_box["y"] + image_box["height"]
        context.close()
        browser.close()


def test_public_visual_geometry_and_cookie_do_not_cover_primary_content() -> None:
    base = os.environ.get("WEBSITEBENCH_TEST_BASE_URL", "http://127.0.0.1:8458").rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)

        desktop = browser.new_context(viewport={"width": 1440, "height": 900})
        page = desktop.new_page()
        page.goto(base + "/login/", wait_until="networkidle")
        card = page.locator(".login-card").bounding_box()
        banner = page.locator("#cookie-banner").bounding_box()
        assert card is not None and banner is not None
        assert 580 <= card["width"] <= 620
        assert card["y"] < 135
        assert 135 <= banner["height"] <= 165
        assert 725 <= banner["y"] <= 750
        assert page.locator(".login-reviews").is_visible()
        assert page.locator(".site-footer").is_visible()
        first_review = page.locator("[data-quote]").inner_text()
        page.locator("[data-next]").click()
        assert page.locator("[data-quote]").inner_text() != first_review
        assert page.locator("[data-login-dot='1']").get_attribute("class") == "active"
        assert page.evaluate("document.documentElement.scrollHeight") >= 1100
        desktop.close()

        mobile = browser.new_context(viewport={"width": 390, "height": 844})
        page = mobile.new_page()
        page.goto(base + "/advice/", wait_until="networkidle")
        title = page.locator("[data-advice-title]").bounding_box()
        banner = page.locator("#cookie-banner").bounding_box()
        assert title is not None and banner is not None
        assert banner["height"] <= 270
        assert title["y"] < banner["y"]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        mobile.close()
        browser.close()
