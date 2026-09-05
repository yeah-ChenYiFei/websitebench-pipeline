#!/usr/bin/env python3
"""Visible Playwright walk for the frozen Walmart P0/P1 matrix."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright


CLONE_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = CLONE_ROOT.parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ManagedClone:
    def __init__(self, data_dir: Path):
        self.port = free_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.data_dir = data_dir
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        env = os.environ.copy()
        env.update({"HOST": "127.0.0.1", "PORT": str(self.port), "DATA_DIR": str(self.data_dir), "SEED": "wb201", "TZ": "Etc/UTC"})
        self.process = subprocess.Popen(
            [sys.executable, "app.py"], cwd=CLONE_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.process.poll() is not None:
                out, err = self.process.communicate()
                raise RuntimeError(f"clone failed to start\n{out}\n{err}")
            try:
                import urllib.request
                with urllib.request.urlopen(f"{self.origin}/__websitebench/health", timeout=.8) as response:
                    if response.read() == b'{"status":"ok"}':
                        return
            except OSError:
                time.sleep(.08)
        raise RuntimeError("clone health timeout")

    def stop(self) -> None:
        if not self.process:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=4)
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.stderr:
            self.process.stderr.close()
        self.process = None

    def restart(self) -> None:
        self.stop()
        self.start()


class Walk:
    def __init__(self, origin: str, output: Path):
        self.origin = origin
        self.output = output
        self.ledger: list[dict] = []
        self.console_errors: list[dict] = []
        self.page_errors: list[dict] = []
        self.requests: list[str] = []
        self.responses: list[dict] = []
        self.matrix: list[dict] = []
        self._evidence_counter = 0

    def attach(self, page: Page, viewport: str) -> None:
        page.on("console", lambda message: self.console_errors.append({"viewport": viewport, "url": page.url, "type": message.type, "text": message.text}) if message.type == "error" else None)
        page.on("pageerror", lambda error: self.page_errors.append({"viewport": viewport, "url": page.url, "text": str(error)}))
        page.on("request", lambda request: self.requests.append(request.url))
        page.on("response", lambda response: self.responses.append({"url": response.url, "status": response.status}) if response.status >= 400 else None)

    def record(self, page: Page, selector: str, *, journey: str, state: str, viewport: str) -> None:
        locator = page.locator(selector).first
        locator.wait_for(state="attached")
        proof = locator.evaluate("""el => ({
          text: (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim(),
          markup: el.outerHTML,
          formAction: el.form ? el.form.action : null,
          tag: el.tagName.toLowerCase(),
          id: el.id || null,
          name: el.getAttribute('name'),
          type: el.getAttribute('type'),
          role: el.getAttribute('role')
        })""")
        self._evidence_counter += 1
        self.ledger.append({
            "schema_version": "websitebench.interaction-ledger-entry.v1",
            "evidence_id": f"wb201-candidate-{self._evidence_counter:03d}",
            "journey_id": journey,
            "role": "anonymous-shopper",
            "state": state,
            "viewport": viewport,
            "clone_url": page.url,
            "selector": selector,
            "visible_text_proof": proof["text"][:500],
            "raw_markup_proof": proof["markup"][:2000],
            "form_action": proof["formAction"],
            "element": {key: proof[key] for key in ("tag", "id", "name", "type", "role")},
        })

    def activate(self, page: Page, selector: str, *, journey: str, state: str, viewport: str, action: str = "click", value: str = "") -> None:
        self.record(page, selector, journey=journey, state=state, viewport=viewport)
        locator = page.locator(selector).first
        if action == "click":
            locator.click()
        elif action == "fill":
            locator.fill(value)
        elif action == "select":
            locator.select_option(value)
        elif action == "press":
            locator.press(value)
        else:
            raise ValueError(action)

    def check_page(self, page: Page, route_id: str, viewport: str, expected_status: int = 200) -> None:
        response = page.goto(self.origin + route_id, wait_until="networkidle")
        assert response and response.status == expected_status, (route_id, response.status if response else None)
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        for image in page.locator("img").all():
            image.scroll_into_view_if_needed()
        page.wait_for_timeout(80)
        broken = page.locator("img").evaluate_all("els => els.filter(el => !el.complete || el.naturalWidth === 0).map(el => el.getAttribute('src'))")
        forms = page.locator("form").evaluate_all("els => els.map(el => el.action)")
        assert overflow <= 1, (route_id, viewport, overflow)
        assert not broken, (route_id, viewport, broken)
        assert all(urlparse(action).netloc == urlparse(self.origin).netloc for action in forms), forms
        self.matrix.append({"route": route_id, "viewport": viewport, "status": expected_status, "horizontal_overflow_px": overflow, "broken_images": broken, "form_actions": forms})

    def scan_links(self, context: BrowserContext, page: Page) -> list[dict]:
        routes = ["/", "/all-departments", "/category/household-essentials", "/category/personal-care", "/search?q=dish+soap", "/product/dawn-ultra-original-18oz", "/cart", "/checkout/review", "/help", "/account-entry"]
        hrefs: set[str] = set()
        for route in routes:
            page.goto(self.origin + route, wait_until="domcontentloaded")
            hrefs.update(page.locator("a[href]").evaluate_all("els => els.map(el => new URL(el.href).pathname + new URL(el.href).search)"))
        results = []
        for href in sorted(hrefs):
            response = context.request.get(self.origin + href, fail_on_status_code=False)
            results.append({"href": href, "status": response.status})
            assert response.status < 400, (href, response.status)
        return results


def run(args: argparse.Namespace) -> dict:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="walmart-headed-e2e-") as runtime_dir:
        server = ManagedClone(Path(runtime_dir))
        server.start()
        walk = Walk(server.origin, output)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=args.headless, slow_mo=0 if args.headless else 45)
                desktop = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
                page = desktop.new_page()
                walk.attach(page, "desktop")

                desktop.request.post(server.origin + "/__websitebench/reset")
                page.goto(server.origin + "/", wait_until="networkidle")
                assert page.get_by_role("heading", name="Household essentials, right when you need them").is_visible()
                page.screenshot(path=output / "desktop-home.png", full_page=True)

                walk.activate(page, ".fulfillment-button", journey="shop.keyboard-history-persistence.success", state="popover-open", viewport="desktop")
                assert page.locator('[data-panel="fulfillment"]').is_visible()
                page.keyboard.press("Escape")
                assert page.evaluate("document.activeElement.classList.contains('fulfillment-button')")

                page.locator("body").focus()
                for _ in range(12):
                    page.keyboard.press("Tab")
                    if page.evaluate("document.activeElement.id") == "global-search":
                        break
                assert page.evaluate("document.activeElement.id") == "global-search"
                walk.activate(page, "#global-search", journey="shop.search-filter-detail.success", state="search-entry", viewport="desktop", action="fill", value="dish soap")
                walk.record(page, "#global-search", journey="shop.search-filter-detail.success", state="keyboard-enter", viewport="desktop")
                page.locator("#global-search").press("Enter")
                page.wait_for_url("**/search?q=dish+soap")
                assert page.locator(".product-card").count() == 5

                walk.activate(page, 'select[name="brand"]', journey="shop.search-filter-detail.success", state="brand-filter", viewport="desktop", action="select", value="Dawn")
                walk.activate(page, 'select[name="sort"]', journey="shop.search-filter-detail.success", state="price-sort", viewport="desktop", action="select", value="price-low")
                walk.activate(page, ".filters button[type=submit]", journey="shop.search-filter-detail.success", state="apply-filters", viewport="desktop")
                page.wait_for_url("**brand=Dawn**")
                assert page.locator(".product-card").count() == 2
                assert page.locator(".price-row strong").first.inner_text() == "$1.06"
                page.screenshot(path=output / "desktop-filtered-search.png", full_page=True)

                walk.activate(page, '#min-price', journey="shop.search-filter-detail.success", state="minimum-price-filter", viewport="desktop", action="fill", value="2")
                walk.activate(page, ".filters button[type=submit]", journey="shop.search-filter-detail.success", state="apply-price-filter", viewport="desktop")
                page.wait_for_url("**min_price=2**")
                assert page.locator(".product-card").count() == 1

                walk.activate(page, 'a[href="/product/dawn-ultra-original-18oz"]', journey="shop.search-filter-detail.success", state="open-detail", viewport="desktop")
                page.wait_for_url("**/product/dawn-ultra-original-18oz")
                assert page.get_by_role("heading", name="Dawn Ultra Liquid Dish Soap, Original Scent, 18 fl oz").is_visible()
                page.go_back(wait_until="networkidle")
                assert "/search" in page.url
                page.go_forward(wait_until="networkidle")
                assert "/product/dawn-ultra-original-18oz" in page.url

                walk.activate(page, 'input[value="fresh-rain-18"]', journey="shop.variant-cart-review.success", state="variant-selected", viewport="desktop")
                assert page.locator("[data-price]").inner_text() == "$3.38"
                walk.activate(page, ".buy-form button[type=submit]", journey="shop.variant-cart-review.success", state="add-local-cart", viewport="desktop")
                page.wait_for_url("**/cart?added=1")
                assert page.get_by_text("Fresh Rain, 18 fl oz").is_visible()

                walk.activate(page, '.cart-item select[name="quantity"]', journey="shop.cart-update-remove.success", state="quantity-two", viewport="desktop", action="select", value="2")
                walk.activate(page, '.cart-item form[action="/cart/update"] button[type=submit]', journey="shop.cart-update-remove.success", state="submit-quantity-update", viewport="desktop")
                page.wait_for_url("**/cart")
                assert page.get_by_text("$6.76", exact=True).count() >= 1
                page.reload(wait_until="networkidle")
                assert page.get_by_text("$6.76", exact=True).count() >= 1

                server.restart()
                page.reload(wait_until="networkidle")
                assert page.get_by_text("$6.76", exact=True).count() >= 1
                walk.matrix.append({"route":"/cart","viewport":"desktop","state":"restart-persisted","status":200})

                page.goto(server.origin + "/account-entry?mode=register&next=/cart", wait_until="networkidle")
                page.locator("#display-name").fill("Desktop Shopper")
                page.locator("#register-email").fill("desktop@example.com")
                page.locator("#register-password").fill("local-test-password")
                page.get_by_role("button", name="Create account").click()
                page.wait_for_url("**verify=1**")
                verification_code = page.locator(".local-code strong").inner_text()
                page.locator("#code").fill(verification_code)
                page.get_by_role("button", name="Verify and create account").click()
                page.wait_for_url("**/cart")
                assert page.get_by_text("Desktop Shopper", exact=True).is_visible()

                walk.activate(page, 'a[href="/checkout/review"]', journey="shop.variant-cart-review.success", state="open-checkout-review", viewport="desktop")
                assert page.get_by_role("heading", name="How would you like to get your order?").is_visible()
                walk.activate(page, ".zip-form button[type=submit]", journey="shop.checkout-validation.recovery", state="empty-zip", viewport="desktop")
                assert page.get_by_text("Enter a valid 5-digit ZIP code.").is_visible()
                walk.activate(page, "#zip", journey="shop.checkout-validation.recovery", state="invalid-zip", viewport="desktop", action="fill", value="abc")
                walk.activate(page, ".zip-form button[type=submit]", journey="shop.checkout-validation.recovery", state="submit-invalid-zip", viewport="desktop")
                assert page.locator("#zip").get_attribute("aria-invalid") == "true"
                walk.activate(page, "#zip", journey="shop.checkout-validation.recovery", state="valid-zip", viewport="desktop", action="fill", value="95829")
                walk.activate(page, ".zip-form button[type=submit]", journey="shop.variant-cart-review.success", state="review-order", viewport="desktop")
                page.wait_for_url("**reviewed=1**")
                assert page.get_by_role("heading", name="Review your order").is_visible()
                page.screenshot(path=output / "desktop-checkout-review.png", full_page=True)
                page.get_by_role("button", name="Place order").click()
                page.wait_for_url("**/order-confirmation?id=**")
                assert page.get_by_role("heading", name="Thanks, Desktop Shopper!").is_visible()
                assert page.get_by_text("No charge was made and nothing was submitted to Walmart.").is_visible()

                page.goto(server.origin + "/search?q=zzzz-no-match-websitebench", wait_until="networkidle")
                assert page.locator(".product-card").count() == 0
                walk.activate(page, '.no-results a[href="/"]', journey="shop.no-results-recovery.success", state="return-home", viewport="desktop")
                assert page.url.rstrip("/") == server.origin

                page.goto(server.origin + "/all-departments", wait_until="networkidle")
                walk.activate(page, 'a[href="/category/household-essentials"]', journey="shop.department-browse.success", state="open-household", viewport="desktop")
                assert page.get_by_role("heading", name="Household Essentials", exact=True).is_visible()
                for route, status in [("/help",200),("/account-entry",200),("/this-route-does-not-exist",404)]:
                    walk.check_page(page, route, "desktop", status)

                all_routes = ["/", "/all-departments", "/category/household-essentials", "/category/personal-care", "/search?q=dish+soap", "/search?q=zzzz-no-match-websitebench", "/product/dawn-ultra-original-18oz", "/cart", "/checkout/review", "/help", "/account-entry"]
                for route in all_routes:
                    walk.check_page(page, route, "desktop")
                links = walk.scan_links(desktop, page)

                server.restart()
                mobile = browser.new_context(viewport={"width":390,"height":844}, locale="en-US", is_mobile=True)
                mpage = mobile.new_page()
                walk.attach(mpage, "mobile")
                mobile.request.post(server.origin + "/__websitebench/reset")
                for route in all_routes:
                    walk.check_page(mpage, route, "mobile")
                mpage.goto(server.origin + "/", wait_until="networkidle")
                assert mpage.locator(".secondary-nav a").evaluate_all(
                    "links => links.every(link => { const r = link.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; })"
                )
                assert not re.search(r"websitebench|offline clone|reconstruction|source-site", mpage.locator("body").inner_text(), re.I)
                mpage.screenshot(path=output / "mobile-home.png", full_page=True)
                walk.activate(mpage, "#global-search", journey="shop.search-filter-detail.success", state="mobile-search", viewport="mobile", action="fill", value="dish soap")
                mpage.locator("#global-search").press("Enter")
                mpage.wait_for_url("**/search?q=dish+soap")
                walk.activate(mpage, '[data-toggle="filters"]', journey="shop.search-filter-detail.success", state="mobile-filter-open", viewport="mobile")
                assert mpage.locator(".filters").is_visible()
                walk.activate(mpage, 'select[name="brand"]', journey="shop.search-filter-detail.success", state="mobile-brand", viewport="mobile", action="select", value="Dawn")
                walk.activate(mpage, '#max-price', journey="shop.search-filter-detail.success", state="mobile-price", viewport="mobile", action="fill", value="4")
                walk.activate(mpage, ".filters button[type=submit]", journey="shop.search-filter-detail.success", state="mobile-apply", viewport="mobile")
                mpage.wait_for_url("**brand=Dawn**")
                walk.activate(mpage, 'a[href="/product/dawn-ultra-original-18oz"]', journey="shop.variant-cart-review.success", state="mobile-detail", viewport="mobile")
                walk.activate(mpage, 'input[value="fresh-rain-18"]', journey="shop.variant-cart-review.success", state="mobile-variant", viewport="mobile")
                walk.activate(mpage, ".buy-form button[type=submit]", journey="shop.variant-cart-review.success", state="mobile-add", viewport="mobile")
                assert mpage.get_by_role("heading", name="Cart (1 item)").is_visible()
                assert mpage.get_by_role("link", name="Cart with 1 item").is_visible()
                mpage.goto(server.origin + "/account-entry?mode=register&next=/cart", wait_until="networkidle")
                mpage.locator("#display-name").fill("Mobile Shopper")
                mpage.locator("#register-email").fill("mobile@example.com")
                mpage.locator("#register-password").fill("local-test-password")
                mpage.get_by_role("button", name="Create account").click()
                mpage.wait_for_url("**verify=1**")
                mobile_verification_code = mpage.locator(".local-code strong").inner_text()
                mpage.locator("#code").fill(mobile_verification_code)
                mpage.get_by_role("button", name="Verify and create account").click()
                mpage.wait_for_url("**/cart")
                walk.activate(mpage, 'a[href="/checkout/review"]', journey="shop.variant-cart-review.success", state="mobile-checkout", viewport="mobile")
                assert mpage.get_by_text("Subtotal (1 item)", exact=True).is_visible()
                walk.activate(mpage, "#zip", journey="shop.checkout-validation.recovery", state="mobile-zip", viewport="mobile", action="fill", value="95829")
                walk.activate(mpage, ".zip-form button[type=submit]", journey="shop.variant-cart-review.success", state="mobile-review", viewport="mobile")
                assert mpage.get_by_role("button", name="Place order").is_enabled()
                assert not re.search(r"websitebench|offline clone|reconstruction|source-site", mpage.locator("body").inner_text(), re.I)
                mpage.screenshot(path=output / "mobile-checkout-review.png", full_page=True)
                mobile.close()
                desktop.close()
                browser.close()

                allowed_origin = urlparse(server.origin).netloc
                nonlocal_requests = sorted({url for url in walk.requests if urlparse(url).scheme in {"http","https"} and urlparse(url).netloc != allowed_origin})
                console_errors = [item for item in walk.console_errors if "Failed to load resource" not in item["text"]]
                assert not nonlocal_requests, nonlocal_requests
                assert not console_errors, console_errors
                assert not walk.page_errors, walk.page_errors
                bad_responses = [item for item in walk.responses if item["status"] >= 400 and "/this-route-does-not-exist" not in item["url"]]
                assert not bad_responses, bad_responses

                report = {
                    "schema_version":"websitebench.candidate-headed-walk.v1",
                    "site_id":"walmart",
                    "assignment_site_id":"WB201",
                    "headed":not args.headless,
                    "origin":server.origin,
                    "viewports":{"desktop":{"width":1440,"height":900},"mobile":{"width":390,"height":844}},
                    "route_state_matrix":walk.matrix,
                    "activated_control_count":len(walk.ledger),
                    "console_errors":console_errors,
                    "page_errors":walk.page_errors,
                    "nonlocal_requests":nonlocal_requests,
                    "unexpected_error_responses":bad_responses,
                    "links":links,
                    "restart_persistence":"passed",
                    "payment_submission":"absent-by-contract",
                    "local_order_submission":"passed",
                }
                (output / "interaction-ledger.json").write_text(json.dumps({"schema_version":"websitebench.interaction-ledger.v1","entries":walk.ledger}, indent=2)+"\n")
                (output / "run-report.json").write_text(json.dumps(report, indent=2)+"\n")
                return report
        finally:
            server.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(SITE_ROOT / "artifacts" / "playwright" / "2026-08-25-headed-e2e"))
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
