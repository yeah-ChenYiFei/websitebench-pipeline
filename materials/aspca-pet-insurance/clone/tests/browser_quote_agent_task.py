"""Real-browser regression for the anonymous quote-and-enroll agent task.

Run directly from the clone directory.  The script boots an isolated local
runtime and never contacts the source site or an external payment/mail system.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import closing
from pathlib import Path

from playwright.sync_api import ConsoleMessage, Request, sync_playwright


CLONE_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"local clone exited early with {process.returncode}")
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("local clone did not become healthy")


def _ready(page) -> None:
    page.locator("#app-root[data-view-ready='true']").wait_for()


def _run_journey(base_url: str) -> dict[str, object]:
    console_errors: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as playwright:
        browser_name = os.environ.get("WEBSITEBENCH_BROWSER", "chromium")
        browser_type = getattr(playwright, browser_name)
        browser = browser_type.launch(
            executable_path=browser_type.executable_path,
            headless=True,
            args=(
                ["--no-sandbox", "--disable-dev-shm-usage"]
                if browser_name == "chromium"
                else []
            ),
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        page.set_default_timeout(15_000)

        def on_console(message: ConsoleMessage) -> None:
            if message.type == "error":
                console_errors.append(message.text)

        def on_request_failed(request: Request) -> None:
            failed_requests.append(f"{request.url}: {request.failure}")

        page.on("console", on_console)
        page.on("requestfailed", on_request_failed)

        page.goto(base_url, wait_until="networkidle")
        page.locator('a[href="/quote/"]:visible').first.click()
        page.wait_for_url("**/quote/#/start")
        _ready(page)
        page.get_by_role("button", name="See My Rates").click()
        page.locator("#errorSummary").wait_for()
        _ready(page)
        page.locator("#cat").check()
        page.locator("#petsName").fill("Willow")
        page.locator("#zipcode").fill("00000")
        page.locator("#choAge").select_option("2")
        page.locator("#female").check()
        page.locator("#inputBreedList").fill("Domestic Shorthair")
        page.locator("#emailAddress").fill("agent-task@example.com")
        page.get_by_role("button", name="See My Rates").click()
        ineligible = page.locator('p[ng-bind*="valueIsNotAValidZipcode"]')
        ineligible.wait_for()
        assert "00000 is not a valid zip code." in ineligible.inner_text()
        _ready(page)
        page.locator("#zipcode").fill("44301")
        page.get_by_role("button", name="See My Rates").click()

        page.wait_for_url("**/#/plans")
        _ready(page)
        original_quote_id = page.evaluate(
            "sessionStorage.getItem('aspca.quote_id')"
        )
        page.locator("#plan-sort").select_option("price-high")
        assert page.locator(
            '.eb-tier-selector__list[role="radiogroup"]'
        ).get_attribute("data-sort") == "price-high"
        assert page.locator("li[data-tier]").first.get_attribute("data-tier") == "elite"
        page.locator('#plan-compare input[value="essential"]').check()
        page.locator('#plan-compare input[value="elite"]').check()
        page.get_by_text("essential: $8.48/month", exact=False).wait_for()
        page.get_by_role("button", name="Save Quote").click()
        page.get_by_text(f"Quote {original_quote_id} saved.", exact=False).wait_for()
        page.reload(wait_until="networkidle")
        _ready(page)
        assert page.locator("#plan-sort").input_value() == "price-high"
        assert page.locator(
            '#plan-compare input[value="essential"]'
        ).is_checked()
        assert page.locator('#plan-compare input[value="elite"]').is_checked()
        page.get_by_text(f"Saved quote {original_quote_id}.").wait_for()

        page.locator("#accordBtn-coverage-details-faq-0").click()
        assert page.locator(
            "#accordBtn-coverage-details-faq-0"
        ).get_attribute("aria-expanded") == "true"

        page.route(
            "**/api/quotes/*/rate",
            lambda route: route.fulfill(
                status=422,
                content_type="application/json",
                body='{"errors":{"limit":"simulated recalculation rejection"}}',
            ),
            times=1,
        )
        page.get_by_role("button", name="Select High Coverage tier").click()
        page.get_by_text(
            "Your previous selection is preserved; choose another option to retry.",
            exact=False,
        ).wait_for()
        page.locator("#tier-plus[aria-checked='true']").wait_for()
        assert json.loads(
            page.evaluate("sessionStorage.getItem('aspca.selection')")
        )["tier"] == "plus"
        page.get_by_role("button", name="Select High Coverage tier").click()
        page.locator("#tier-elite[aria-checked='true']").wait_for()
        page.locator("#rate-recalculation-error").wait_for(state="detached")
        page.get_by_role("button", name="High Coverage tier selected").wait_for()
        page.locator("#app-root[data-rate-pending='false']").wait_for()
        page.get_by_role("button", name="Select Popular tier").click()
        page.locator("#tier-plus[aria-checked='true']").wait_for()
        page.locator("#app-root[data-rate-pending='false']").wait_for()
        page.get_by_role("button", name="Select High Coverage tier").click()
        page.locator("#tier-elite[aria-checked='true']").wait_for()
        page.locator("#app-root[data-rate-pending='false']").wait_for()

        page.goto(f"{base_url}/quote/#/start", wait_until="networkidle")
        _ready(page)
        page.locator("#cat").check()
        page.locator("#petsName").fill("Willow")
        page.locator("#zipcode").fill("00000")
        page.locator("#choAge").select_option("2")
        page.locator("#female").check()
        page.locator("#inputBreedList").fill("Domestic Shorthair")
        page.locator("#emailAddress").fill("agent-task@example.com")
        page.get_by_role("button", name="See My Rates").click()
        ineligible = page.locator('p[ng-bind*="valueIsNotAValidZipcode"]')
        ineligible.wait_for()
        assert "00000 is not a valid zip code." in ineligible.inner_text()
        _ready(page)
        assert page.evaluate(
            "sessionStorage.getItem('aspca.quote_id')"
        ) == original_quote_id
        page.goto(f"{base_url}/quote/#/quote-search", wait_until="networkidle")
        _ready(page)
        page.locator("#emailAddress").fill("agent-task@example.com")
        page.locator("#zipCode").fill("44301")
        page.get_by_role("button", name="Find My Quote").click()
        page.wait_for_url("**/#/plans")
        _ready(page)
        page.get_by_role("button", name="Select High Coverage tier").click()
        page.locator("#app-root[data-rate-pending='false']").wait_for()
        page.get_by_role("button", name="Continue to next step").click()

        page.wait_for_url("**/#/checkout")
        _ready(page)
        assert page.locator("#stateSelect").input_value() == "OH"
        assert page.locator("#zipcode").input_value() == "44301"
        assert page.locator("#emailAddress").input_value() == "agent-task@example.com"
        assert page.locator(
            'td[aria-labelledby="annualLimit-label-0"]'
        ).inner_text().strip() == "$10,000"
        assert page.locator(
            'td[aria-labelledby="deductible-label-0"]'
        ).inner_text().strip() == "$500"
        assert page.locator(
            'td[aria-labelledby="reimbursement-label-0"]'
        ).inner_text().strip() == "80%"
        assert page.locator(
            'td[aria-labelledby="premiumCost-label-0"]'
        ).inner_text().strip() == "$23.19"
        assert page.locator(
            'td[aria-labelledby="totalCost-label-0"]'
        ).inner_text().strip() == "$23.19"
        assert page.locator("#monthly-price").inner_text().strip() == "$23.19/month"
        assert page.locator("#annually-price").inner_text().strip() == "$278.28/year"
        assert page.locator(
            "#payment-summary-table tfoot td"
        ).inner_text().strip() == "$23.19"
        assert not page.locator(
            "#preventiveEffective-label-0"
        ).is_visible()
        assert not page.get_by_role(
            "button", name="Edit preventive care for Willow"
        ).is_visible()
        page.get_by_text("Eligible in OH (ZIP 44301).", exact=False).wait_for()
        page.get_by_text("Enrollment fee: $0.00 USD.", exact=False).wait_for()

        page.locator("#firstName").fill("Test")
        page.locator("#lastName").fill("User")
        page.locator("#address1").fill("1 Main St")
        page.locator("#city").fill("Akron")
        page.locator("#phone").fill("555-555-5555")
        page.get_by_role("button", name="Review application").click()
        page.get_by_text(
            "Choose whether your pet is currently ill.", exact=False
        ).wait_for()
        page.locator('input[name="currentlyIll"][value="true"]').check()
        page.locator('input[name="seenVet"][value="true"]').check()
        page.get_by_role("button", name="Review application").click()
        page.get_by_text(
            "Condition details are required when Currently ill is Yes.",
            exact=False,
        ).wait_for()
        page.locator('textarea[name="conditionDetails"]').fill(
            "Seasonal allergies"
        )
        page.locator('input[name="vetName"]').fill("Main Street Veterinary")
        page.locator('input[name="privacyConsent"]').check()
        page.locator('input[name="electronicSignature"]').check()
        page.get_by_role("button", name="Review application").click()
        page.get_by_text("Application review saved.", exact=False).wait_for()
        page.get_by_text("Applicant: Test User", exact=False).wait_for()
        page.get_by_role("button", name="Edit prior details").click()
        page.locator("#city").fill("Cuyahoga Falls")
        page.get_by_role("button", name="Review application").click()
        page.get_by_text("Cuyahoga Falls", exact=False).wait_for()
        page.reload(wait_until="networkidle")
        _ready(page)
        page.get_by_text("Application review saved.", exact=False).wait_for()
        assert page.locator("#city").input_value() == "Cuyahoga Falls"
        assert page.locator('input[name="privacyConsent"]').is_checked()
        assert page.locator('input[name="electronicSignature"]').is_checked()
        page.locator("#agreeTerms").check()
        assert page.locator("#agreeTerms").is_checked()
        page.locator(
            'input[name="paymentScenario"][value="sandbox-declined"]'
        ).check()
        page.get_by_role(
            "button",
            name="Click to complete enrollment on your new pet insurance policy",
        ).click()
        page.get_by_text("simulated payment was declined", exact=False).wait_for()
        assert page.locator("#city").input_value() == "Cuyahoga Falls"
        page.locator(
            'input[name="paymentScenario"][value="sandbox-retry"]'
        ).check()
        page.get_by_role(
            "button",
            name="Click to complete enrollment on your new pet insurance policy",
        ).click()
        page.get_by_text("simulated payment can be retried", exact=False).wait_for()
        page.locator(
            'input[name="paymentScenario"][value="sandbox-approved"]'
        ).check()

        page.get_by_role(
            "button",
            name="Click to complete enrollment on your new pet insurance policy",
        ).click()
        page.get_by_text("Enrollment recorded in the offline clone.").wait_for()
        page.get_by_text(
            "Insured pet: Willow. Coverage: $10,000 annual limit, $500 deductible, "
            "80% reimbursement. Monthly simulated total: $23.19 USD."
        ).wait_for()
        page.get_by_text("Payment: local simulation only (no real charge).").wait_for()
        page.get_by_text("Mail: LOCAL_SIMULATION (no email sent).").wait_for()

        quote_id = page.evaluate("sessionStorage.getItem('aspca.quote_id')")
        response = context.request.get(f"{base_url}/api/quotes/{quote_id}")
        assert response.status == 200
        quote = response.json()
        assert quote["status"] == "enrolled"
        assert quote["pets"][0]["species"] == "Cat"
        assert quote["pets"][0]["age_label"] == "2 Years"
        assert quote["pets"][0]["breed"] == "Domestic Shorthair"
        assert quote["pets"][0]["selection"]["annual_limit"] == 10_000
        assert quote["enrollment"]["payment"]["amount_minor"] == 2_319
        assert quote["enrollment"]["payment"]["is_simulation"] is True

        browser.close()

    assert console_errors == [], console_errors
    assert failed_requests == [], failed_requests
    return {
        "quote_id": quote_id,
        "policy_number": quote["enrollment"]["policy_number"],
        "payment_amount_minor": quote["enrollment"]["payment"]["amount_minor"],
        "mail": "LOCAL_SIMULATION",
    }


def main() -> int:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="aspca-agent-task-") as data_dir:
        environment = os.environ.copy()
        environment["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
            Path(data_dir) / "aspca-pet-insurance.sqlite3"
        )
        environment["WEBSITEBENCH_ASPCA_ADMIN_TOKEN"] = "agent-task-local-only"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=CLONE_DIR,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_health(base_url, process)
            result = _run_journey(base_url)
            print(json.dumps(result, indent=2, sort_keys=True))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
