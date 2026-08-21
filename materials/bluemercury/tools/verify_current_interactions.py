#!/usr/bin/env python3
"""Playwright verification for the current homepage-to-checkout local journey."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    return parser.parse_args()


async def verify(args: argparse.Namespace) -> dict[str, object]:
    args.out.mkdir(parents=True, exist_ok=True)
    external: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[dict[str, str]] = []
    bad_responses: list[dict[str, object]] = []
    steps: list[str] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=str(args.browser))
        context = await browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")

        async def local_only(route) -> None:
            host = urlparse(route.request.url).hostname
            if host not in {"127.0.0.1", "localhost"}:
                external.append(route.request.url)
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", local_only)
        page = await context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("requestfailed", lambda request: failed_requests.append({"url": request.url, "reason": request.failure or "unknown"}))
        page.on("response", lambda response: bad_responses.append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
        await page.goto(args.base_url, wait_until="networkidle")
        steps.append("home_loaded")
        await page.locator('[data-hero-direction="next"]').click()
        await page.get_by_role("heading", name="Perfect for Fall").wait_for()
        steps.append("carousel_next_to_m61")
        await page.locator('[data-hero-index="2"]').click()
        await page.get_by_role("heading", name="Fall in Love").wait_for()
        steps.append("carousel_dot_to_fall")
        await page.locator('[data-hero-index="0"]').click()
        await page.locator("[data-hero-link]").click()
        await page.wait_for_url("**/collections/chantecaille")
        await page.get_by_role("heading", name="Chantecaille (108)").wait_for()
        steps.append("campaign_to_brand_collection")
        bestseller_row = page.locator("[data-brand-carousel] .product-row")
        before_scroll = await bestseller_row.evaluate("el => el.scrollLeft")
        await page.locator('[data-brand-direction="next"]').click()
        await page.wait_for_timeout(500)
        after_scroll = await bestseller_row.evaluate("el => el.scrollLeft")
        if after_scroll <= before_scroll:
            raise AssertionError("Bestsellers carousel did not move")
        steps.append("bestsellers_carousel_scrolled")
        first_product = page.locator(".brand-bestsellers .product-card > a").first
        await first_product.click()
        await page.wait_for_url("**/products/**")
        steps.append("bestseller_to_product")
        variant = page.locator("#variant-select")
        if await variant.count():
            available = variant.locator('option:not([disabled])').first
            await variant.select_option(await available.get_attribute("value"))
            steps.append("available_variant_selected")
        await page.locator("#add-to-bag").click()
        await page.wait_for_url("**/cart")
        await page.get_by_role("heading", name="Your Shopping Cart").wait_for()
        steps.append("product_added_to_bag")
        await page.get_by_role("link", name="CHECKOUT").click()
        await page.wait_for_url("**/checkout")
        await page.get_by_text("LOCAL SYNTHETIC CHECKOUT").wait_for()
        steps.append("local_sandbox_checkout_reached")
        await page.screenshot(path=str(args.out / "checkout-1440x900.png"), full_page=False)
        hard_failures = [failure for failure in failed_requests if "ERR_ABORTED" not in failure["reason"]]
        passed = not external and not console_errors and not hard_failures and not bad_responses
        result = {
            "status": "pass" if passed else "fail",
            "steps": steps,
            "final_url": page.url,
            "external_requests": external,
            "console_errors": console_errors,
            "failed_requests": failed_requests,
            "hard_failed_requests": hard_failures,
            "bad_responses": bad_responses,
            "marker_present": "LOCAL CLONE" in await page.locator("body").inner_text(),
        }
        if not passed or result["marker_present"]:
            result["status"] = "fail"
        (args.out / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        await browser.close()
        return result


def main() -> int:
    args = parse_args()
    result = asyncio.run(verify(args))
    print(json.dumps(result))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
