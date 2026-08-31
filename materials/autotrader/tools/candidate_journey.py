#!/usr/bin/env python3
"""Record a reproducible candidate-only Autotrader journey and stability frames."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Locator, Page, expect, sync_playwright


BASE_URL = "http://127.0.0.1:18891"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "trajectory" / "candidate-p0-main"


def proof(locator: Locator) -> dict[str, str | None]:
    return {
        "visible_text": locator.inner_text().strip()[:500],
        "raw_markup": locator.evaluate("element => element.outerHTML")[:2000],
        "form_action": locator.evaluate(
            "element => { const form = element.closest('form'); "
            "return form ? (form.getAttribute('action') || location.pathname + location.search) : null; }"
        ),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger: list[dict[str, object]] = []
    external_requests: list[str] = []

    def record(page: Page, step_id: str, action: str, selector: str, locator: Locator) -> None:
        ledger.append(
            {
                "journey_id": "candidate-p0-public-search-detail-save-compare",
                "role": "anonymous-visitor",
                "state": "candidate-local-only",
                "evidence_id": f"candidate-p0-{len(ledger) + 1:02d}",
                "step_id": step_id,
                "action": action,
                "selector": selector,
                "clone_url": page.url,
                **proof(locator),
            }
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def watch_request(request) -> None:
            if not request.url.startswith(BASE_URL):
                external_requests.append(request.url)

        page.on("request", watch_request)
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        ledger.append(
            {
                "journey_id": "candidate-p0-public-search-detail-save-compare",
                "role": "anonymous-visitor",
                "state": "candidate-local-only",
                "evidence_id": "candidate-p0-00",
                "step_id": "open-home",
                "action": "goto",
                "selector": "main",
                "clone_url": page.url,
                "visible_text": page.locator("main").inner_text().strip()[:500],
                "raw_markup": page.locator("main").evaluate("element => element.outerHTML")[:2000],
                "form_action": None,
            }
        )

        buy = page.get_by_role("button", name="Buy", exact=True)
        record(page, "select-buy", "click", "role=button[name='Buy']", buy)
        buy.click()

        postcode = page.locator("input[name='postcode']")
        record(page, "enter-postcode", "fill", "input[name='postcode']", postcode)
        postcode.fill("SW1A 1AA")

        make = page.locator("select[name='make']")
        record(page, "select-make", "select_option", "select[name='make']", make)
        make.select_option("Ford")

        model = page.locator("select[name='model']")
        record(page, "select-model", "select_option", "select[name='model']", model)
        model.select_option("Fiesta")

        more = page.get_by_role("button", name="More options", exact=True)
        record(page, "show-more-options", "click", "role=button[name='More options']", more)
        more.click()

        cancel_options = page.get_by_role("button", name="Cancel", exact=True)
        record(page, "close-more-options", "click", "role=button[name='Cancel']", cancel_options)
        cancel_options.click()

        search = page.get_by_role("button", name=re.compile(r"^Search "))
        record(page, "submit-home-search", "click", "role=button[name^='Search ']", search)
        search.click()
        page.wait_for_url("**/cars/used?**")
        page.wait_for_selector("article.card")

        sort = page.locator("select[name='sort']")
        record(page, "sort-price-low", "select_option", "select[name='sort']", sort)
        sort.select_option("price-low")

        results_search = page.get_by_role("button", name="Search cars", exact=True)
        record(page, "apply-sort", "click", "role=button[name='Search cars']", results_search)
        results_search.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_selector("article.card")

        first_save = page.locator("article.card").first.locator("button[data-save]")
        record(page, "save-first-result", "click", "article.card:first-of-type button[data-save]", first_save)
        first_save.click()
        expect(first_save).to_have_text("Saved")

        first_compare = page.locator("article.card").first.locator("button[data-compare]")
        record(page, "compare-first-result", "click", "article.card:first-of-type button[data-compare]", first_compare)
        first_compare.click()
        expect(first_compare).to_have_text("Added to compare")

        first_detail = page.locator("article.card").first.locator("h2 a")
        record(page, "open-first-detail", "click", "article.card:first-of-type h2 a", first_detail)
        first_detail.click()
        page.wait_for_selector(".gallery")

        detail_save = page.locator("button[data-save]")
        record(page, "inspect-detail-save-control", "observe", "button[data-save]", detail_save)
        page.screenshot(path=str(OUT / "detail-desktop.png"), full_page=True)

        page.goto(f"{BASE_URL}/cars/used", wait_until="networkidle")
        for frame in range(1, 4):
            page.screenshot(path=str(OUT / f"used-stability-{frame}.png"), full_page=True)
            if frame < 3:
                time.sleep(1.0)

        browser.close()

    report = {
        "schema_version": "autotrader.candidate-trajectory.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_only": True,
        "source_trace_coverage": False,
        "formal_human_trace_present": True,
        "human_trace_text_id": "ht-001",
        "formal_trace_scope_coverage": "partial-candidate-only",
        "journey": "public home -> search -> sort -> save/compare -> vehicle detail",
        "meaningful_action_count": len(ledger) - 1,
        "http_status": 200,
        "external_request_count": len(set(external_requests)),
        "external_requests": sorted(set(external_requests)),
        "ledger": ledger,
    }
    (OUT / "ledger.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("meaningful_action_count", "external_request_count")}))


if __name__ == "__main__":
    main()
