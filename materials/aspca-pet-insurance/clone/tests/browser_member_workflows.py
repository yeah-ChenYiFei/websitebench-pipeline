"""Real-browser member-center lifecycle against an isolated HTTPS runtime."""

from __future__ import annotations

import json
import os
import socket
import ssl
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
    deadline = time.monotonic() + 20
    context = ssl._create_unverified_context()  # noqa: SLF001 - throwaway cert
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"local clone exited early with {process.returncode}")
        try:
            with urllib.request.urlopen(
                f"{base_url}/healthz", timeout=1, context=context
            ) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("local HTTPS clone did not become healthy")


def _ready(page) -> None:
    page.locator("#app-root[data-view-ready='true']").wait_for(state="attached")


def _seed_policy(context, base_url: str) -> str:
    quote = context.request.post(
        f"{base_url}/api/quotes",
        data={
            "species": "Cat",
            "name": "Willow",
            "age_label": "2 Years",
            "gender": "Female",
            "breed": "Domestic Shorthair",
            "email": "member-browser@example.com",
            "zip": "44301",
        },
    )
    assert quote.status == 201
    quote_id = quote.json()["quote_id"]
    enrolled = context.request.post(
        f"{base_url}/api/quotes/{quote_id}/enroll",
        data={
            "contact": {
                "firstName": "Taylor",
                "lastName": "Morgan",
                "address1": "1 Main St",
                "city": "Akron",
                "state": "OH",
                "zip": "44301",
                "phone": "555-555-5555",
                "email": "member-browser@example.com",
            },
            "frequency": "Monthly",
            "paperless": True,
            "agree_terms": True,
            "scenario_id": "sandbox-approved",
        },
    )
    assert enrolled.status == 201
    return enrolled.json()["policy_number"]


def _run_journey(
    base_url: str, upload_path: Path, invalid_upload_path: Path
) -> dict[str, object]:
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
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(20_000)

        def on_console(message: ConsoleMessage) -> None:
            if message.type == "error":
                console_errors.append(message.text)

        def on_request_failed(request: Request) -> None:
            failed_requests.append(f"{request.url}: {request.failure}")

        page.on("console", on_console)
        page.on("requestfailed", on_request_failed)
        policy_number = _seed_policy(context, base_url)

        page.goto(f"{base_url}/portal/#/register", wait_until="networkidle")
        _ready(page)
        form = page.locator("#registerForm")
        form.locator('input[name="email"]').fill("member-browser@example.com")
        form.locator('input[name="confirmEmail"]').fill(
            "member-browser@example.com"
        )
        form.locator('input[name="password"]').fill(
            "correct-horse-battery-staple"
        )
        form.locator('input[name="confirmPassword"]').fill(
            "correct-horse-battery-staple"
        )
        form.locator('input[name="accountNumber"]').fill(policy_number)
        form.locator('input[name="zipCode"]').fill("44301")
        form.get_by_role("button", name="Register Account").click()

        code = page.locator("#local-registration-code")
        code.wait_for()
        page.locator("#verify-registration input[name='code']").fill(
            code.inner_text()
        )
        page.get_by_role("button", name="Verify and create account").click()
        page.wait_for_url("**/#/home")
        page.get_by_text(policy_number, exact=True).last.wait_for()
        page.get_by_text("Willow").wait_for()

        page.get_by_role("link", name="My Account").click()
        page.get_by_text("Personal / Contact Details").wait_for()
        assert page.get_by_role("link", name="Contact support").get_attribute(
            "href"
        ) == "/about-us/contact-us/"
        page.get_by_role("link", name="Help Center").click()
        page.get_by_role("heading", name="Help Center").wait_for()
        assert page.get_by_role("link", name="Contact Us").get_attribute(
            "href"
        ) == "/about-us/contact-us/"
        page.get_by_role("link", name="My Pets").click()
        page.wait_for_url("**/#/my-pets")
        page.get_by_text("Domestic Shorthair").wait_for()
        page.get_by_role("link", name="View coverage").click()
        page.wait_for_url(f"**/#/policies/{policy_number}")
        page.get_by_text("Policy holder / insured details").wait_for()

        page.get_by_role("link", name="Policy documents").click()
        page.get_by_role("heading", name="Policy Documents").wait_for()
        page.get_by_role(
            "heading", name="Policy document", exact=True
        ).wait_for()
        page.get_by_role(
            "heading", name="Coverage summary", exact=True
        ).wait_for()
        assert page.get_by_role("link", name="Download PDF").count() == 2
        page.get_by_role("link", name="My Pets").click()
        page.get_by_role("link", name="View coverage").click()
        page.get_by_role("link", name="Update coverage").click()
        page.locator("#coverage-form select[name='annual_limit']").select_option(
            "7000"
        )
        page.locator("#coverage-form select[name='deductible']").select_option(
            "250"
        )
        page.locator(
            "#coverage-form select[name='reimbursement']"
        ).select_option("90")
        page.locator("#coverage-form select[name='preventive']").select_option(
            "basic"
        )
        page.get_by_role("button", name="Save coverage changes").click()
        page.get_by_text("Coverage and pricing saved.").wait_for()
        page.reload(wait_until="networkidle")
        _ready(page)
        assert page.locator("#coverage-price").inner_text() == "$35.58/month"

        page.get_by_role("link", name="Billing").click()
        billing = page.locator(".billing-form")
        billing.locator("select[name='frequency']").select_option("Annually")
        billing.locator("input[name='autopay']").check()
        billing.get_by_role("button", name="Save billing settings").click()
        page.get_by_text("$546.36 Annually").wait_for()
        page.reload(wait_until="networkidle")
        _ready(page)
        assert billing.locator("input[name='autopay']").is_checked()
        assert billing.locator("select[name='frequency']").input_value() == "Annually"

        page.get_by_role("link", name="Submit a Claim").click()
        page.locator("#claim-form select[name='policy_number']").select_option(
            policy_number
        )
        page.locator("#claim-form input[name='incident_date']").fill("2026-07-20")
        page.locator("#claim-form select[name='reason']").select_option("Illness")
        page.locator("#claim-form input[name='provider']").fill(
            "Main Street Veterinary Clinic"
        )
        page.locator("#claim-form input[name='amount']").fill("125.00")
        page.locator("#claim-form input[name='has_invoice']").check()
        page.get_by_role("button", name="Submit claim").click()
        page.get_by_text(
            "Upload the invoice when Has invoice is Yes."
        ).wait_for()
        page.locator("#claim-file").set_input_files(str(invalid_upload_path))
        page.get_by_text("Upload a PDF, PNG, or JPEG file.").wait_for()
        assert page.locator("#upload-progress").get_attribute("style") == "width: 0px;"
        page.locator("#claim-file").set_input_files(str(upload_path))
        page.get_by_text("Parsed successfully: invoice.pdf").wait_for()
        assert page.locator("#upload-progress").get_attribute("style") == "width: 100%;"
        page.get_by_role("button", name="Submit claim").click()
        page.wait_for_url("**/#/claims/CLM-000001")
        page.get_by_text("Main Street Veterinary Clinic").wait_for()
        page.get_by_text("invoice.pdf").wait_for()

        page.get_by_role("link", name="Track a Claim").click()
        page.get_by_text("CLM-000001").wait_for()
        page.get_by_role("link", name="Home").click()
        page.get_by_role("link", name="View policy").click()
        page.get_by_role("button", name="Renew policy").click()
        page.get_by_text("Renewal saved.").wait_for()
        cancel = page.locator("#cancel-form")
        cancel.locator("select[name='reason']").select_option("No longer needed")
        cancel.locator("input[name='confirm']").check()
        cancel.get_by_role("button", name="Cancel policy").click()
        page.get_by_text("Cancellation confirmed").wait_for()
        page.reload(wait_until="networkidle")
        _ready(page)
        page.get_by_text("not renewal eligible").wait_for()

        page.get_by_role("button", name="Log Out").click()
        page.wait_for_url("**/#/login")
        _ready(page)
        page.locator("#emailAddress").fill("member-browser@example.com")
        page.locator("#password").fill("correct-horse-battery-staple")
        page.get_by_role("button", name="Log In").click()
        page.wait_for_url("**/#/home")
        page.get_by_text(policy_number, exact=True).last.wait_for()
        page.get_by_text("canceled").wait_for()

        session = context.request.get(f"{base_url}/portal/api/session")
        assert session.status == 200
        assert session.json()["authenticated"] is True
        browser.close()

    assert console_errors == [], console_errors
    assert failed_requests == [], failed_requests
    return {
        "policy_number": policy_number,
        "claim_number": "CLM-000001",
        "coverage_monthly": "35.58",
        "billing_total": "546.36",
        "final_status": "canceled",
        "authenticated_after_signin": True,
    }


def main() -> int:
    port = _free_port()
    base_url = f"https://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="aspca-member-browser-") as temp_dir:
        temp_path = Path(temp_dir)
        cert = temp_path / "cert.pem"
        key = temp_path / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        upload = temp_path / "invoice.pdf"
        upload.write_bytes(b"%PDF-1.4\n% synthetic local claim invoice\n%%EOF\n")
        invalid_upload = temp_path / "invoice.txt"
        invalid_upload.write_text("unsupported local fixture", encoding="utf-8")
        environment = os.environ.copy()
        environment["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
            temp_path / "aspca-pet-insurance.sqlite3"
        )
        environment["WEBSITEBENCH_ASPCA_ADMIN_TOKEN"] = "member-browser-local-only"
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
                "--ssl-keyfile",
                str(key),
                "--ssl-certfile",
                str(cert),
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
            result = _run_journey(base_url, upload, invalid_upload)
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
