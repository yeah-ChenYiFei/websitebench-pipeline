#!/usr/bin/env python3
"""Candidate-only P0 registration and Mega Fan monthly browser walk.

The unified scenario runner cannot feed a dynamically rendered local verification
code into a later step. This bounded fallback records no password, code, cookie,
or token; it retains only terminal assertions, local-network closure, and screenshots.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8896"
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "materials/crunchyroll/artifacts/offline-clone/frontend/browser-core-672"
REPORT = (
    ROOT
    / "materials/crunchyroll/artifacts/offline-clone/frontend/browser-core-672-report.json"
)
CHROME = "/home/user/.local/bin/chrome-for-testing-codex"


def reset() -> None:
    with urlopen(
        Request(BASE + "/__websitebench/reset", method="POST"), timeout=10
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"reset failed: {response.status}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    reset()
    external: list[str] = []
    checkpoints: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        page.on(
            "request",
            lambda request: (
                external.append(request.url)
                if not request.url.startswith(BASE)
                else None
            ),
        )

        page.goto(BASE + "/premium?term=monthly", wait_until="networkidle")
        page.locator(".plan.featured").screenshot(
            path=str(OUT / "01-mega-fan-monthly.png")
        )
        assert "Mega Fan" in page.locator(".plan.featured").inner_text()
        assert "$13.99" in page.locator(".plan.featured").inner_text()
        checkpoints.append(
            {"id": "mega-fan-monthly", "path": "/premium", "passed": True}
        )

        page.locator('.plan.featured form[action="/select-plan"] button').click()
        page.wait_for_url(re.compile(r".*/register\?next="))
        assert page.locator('form[action="/register"]').evaluate(
            "form => !form.checkValidity()"
        )
        page.screenshot(path=str(OUT / "02-registration-required.png"), full_page=True)
        checkpoints.append(
            {"id": "registration-required-fields", "path": "/register", "passed": True}
        )

        page.locator('input[name="email"]').fill("browser-core-672@example.test")
        page.locator('input[name="password"]').fill("LocalPass123!")
        page.locator('form[action="/register"] button').click()
        page.wait_for_selector('form[action="/register/verify"]')
        code = page.locator(".success strong").inner_text().strip()
        assert re.fullmatch(r"\d{6}", code)
        page.screenshot(path=str(OUT / "03-local-verification.png"), full_page=True)
        checkpoints.append(
            {"id": "local-verification-guidance", "path": "/register", "passed": True}
        )

        page.locator('input[name="code"]').fill(code)
        page.locator('form[action="/register/verify"] button').click()
        page.wait_for_url(re.compile(r".*/checkout\?plan=Mega\+Fan&term=monthly"))
        assert "Mega Fan · Monthly" in page.locator("main").inner_text()
        page.screenshot(path=str(OUT / "04-checkout-review.png"), full_page=True)
        checkpoints.append(
            {"id": "checkout-review", "path": "/checkout", "passed": True}
        )

        page.locator('select[name="scenario"]').select_option("sandbox-approved")
        page.locator('input[name="terms"]').check()
        page.locator('form[action="/checkout"] button').click()
        page.wait_for_url(re.compile(r".*/account/history\?created=1"))
        page.wait_for_load_state("networkidle")
        body = page.locator("main").inner_text()
        expected_values = (
            "Mega Fan Monthly",
            "ACTIVE",
            "DETAILS",
            "EDIT OR CANCEL",
            "BACK TO MY LIST",
        )
        missing = [expected for expected in expected_values if expected not in body]
        assert not missing, f"missing terminal labels: {missing}"
        page.screenshot(path=str(OUT / "05-history-saved.png"), full_page=True)
        checkpoints.append(
            {"id": "history-saved", "path": "/account/history", "passed": True}
        )
        browser.close()

    report = {
        "schema_version": "crunchyroll.browser-core-672.v1",
        "authority": "candidate-browser-evidence",
        "base_url": BASE,
        "viewport": {"width": 1440, "height": 900},
        "checkpoints": checkpoints,
        "terminal_values": {"plan": "Mega Fan", "term": "Monthly", "status": "Active"},
        "external_request_count": len(external),
        "sensitive_values_retained": False,
        "status": "passed" if len(checkpoints) == 5 and not external else "failed",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "report": str(REPORT.relative_to(ROOT)),
                "status": report["status"],
                "checkpoints": len(checkpoints),
                "external_request_count": len(external),
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
