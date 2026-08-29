from __future__ import annotations

import argparse
import json
import uuid

from playwright.sync_api import expect, sync_playwright


ALL_TRACES = [f"WB048-T{i:02d}" for i in range(1, 24)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay every assigned Fenty Beauty trace through visible controls.")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    checks: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # WB048-T01/T03: public entry and real category navigation.
        page.goto(f"{args.base}/en-ca")
        expect(page.locator('[data-action="toggle-menu"]')).to_have_count(0)
        expect(page.locator('[data-action="ask-ai"]')).to_have_count(1)
        expect(page.locator(".home-product-rail").first).to_be_visible()
        page.locator('a[href="/en-ca/collections/makeup-shop-all"]').first.click()
        page.wait_for_url("**/en-ca/collections/makeup-shop-all")
        expect(page.get_by_role("heading", name="SHOP ALL MAKEUP")).to_be_visible()
        checks.append("public homepage navigation reaches the canonical makeup collection")

        # WB048-T04/T05: search/filter/sort and compare visible products.
        filters = page.locator("#catalog-filters")
        filters.locator('input[name="q"]').fill("makeup")
        filters.locator('select[name="sort"]').select_option("price-low")
        filters.get_by_role("button", name="APPLY").click()
        page.wait_for_url("**/collections/makeup-shop-all?**")
        page.locator(".catalog-compare summary").click()
        expect(page.locator('[data-testid="compare-table"]')).to_be_visible()
        compare_text = page.locator('[data-testid="compare-table"]').inner_text()
        for required in ("$", "RATING", "TYPE", "AVAILABILITY"):
            assert required in compare_text
        cards = page.locator('[data-testid="compare-table"] article')
        assert cards.count() >= 2
        checks.append("keyword search, sort/filter and multi-product price/rating/type/availability comparison")

        # WB048-T06/T07/T08: product detail, media, exact 185N shade, size/quantity and save.
        page.goto(f"{args.base}/en-ca/account/register")
        email = f"trace-{uuid.uuid4().hex[:10]}@example.test"
        page.locator('input[name="display_name"]').fill("WebsiteBench Shopper")
        page.locator('input[name="email"]').fill(email)
        page.locator('input[name="password"]').fill("WebsiteBench!23")
        page.locator('input[type="checkbox"]').check()
        page.get_by_role("button", name="CREATE ACCOUNT", exact=True).click()
        page.wait_for_url("**/en-ca/account")
        page.goto(f"{args.base}/en-ca/products/pro-filtr-soft-matte-longwear-foundation-420")
        thumb_box = page.locator(".pdp-thumbs").bounding_box()
        image_box = page.locator(".pdp-main-image").bounding_box()
        details_box = page.locator(".pdp-buy").bounding_box()
        assert thumb_box and image_box and details_box and thumb_box["x"] < image_box["x"] < details_box["x"]
        initial_image = page.locator(".pdp-main-image img").get_attribute("src")
        page.locator("[data-pdp-media]").nth(1).click()
        assert page.locator(".pdp-main-image img").get_attribute("src") != initial_image
        detail_text = page.locator("main").inner_text()
        for required in ("CAD", "Reviews", "DETAILS", "INGREDIENTS", "HANDPICKED FOR YOU"):
            assert required in detail_text
        page.locator('button.variant[data-variant="185N"]').click()
        expect(page.locator("#selected-variant")).to_have_text("185N")
        page.locator('.save-pdp[data-favorite="foundation"]').click()
        expect(page.locator("#toast")).to_contain_text("Saved to favorites")
        page.get_by_test_id("add-to-bag").click()
        expect(page.locator("#cart-drawer")).to_be_visible()
        expect(page.locator("#cart-count")).to_have_text("1")
        page.keyboard.press("Escape")
        checks.append("PDP media/details/reviews, exact shade 185N, option selection and saved item")

        # WB048-T02/T11/T23: add both exact products, change quantity, remove/restore, begin checkout.
        page.goto(f"{args.base}/en-ca/products/invisimatte-instant-setting-blotting-powder")
        page.get_by_test_id("add-to-bag").click()
        expect(page.locator("#cart-count")).to_have_text("2")
        page.keyboard.press("Escape")
        page.goto(f"{args.base}/en-ca/cart")
        expect(page.locator(".source-cart-line")).to_have_count(2)
        assert "185N" in page.locator("main").inner_text()
        assert "Universal" in page.locator("main").inner_text()
        foundation_qty = page.locator('[data-cart-qty="foundation"]')
        foundation_qty.select_option("2")
        expect(page.locator("#cart-count")).to_have_text("3")
        page.locator('[data-cart-qty="foundation"]').select_option("1")
        expect(page.locator("#cart-count")).to_have_text("2")
        page.locator('[data-cart-remove="powder"]').click()
        expect(page.get_by_role("button", name="RESTORE ITEM")).to_be_visible()
        page.get_by_role("button", name="RESTORE ITEM").click()
        expect(page.locator(".source-cart-line:not(.removed)")).to_have_count(2)
        page.get_by_role("link", name="CHECKOUT").click()
        page.wait_for_url("**/en-ca/checkout")
        checks.append("foundation 185N plus Invisible Setting Powder cart, quantity and remove/restore")

        # WB048-T12/T13: address/shipping/promo/payment simulation to final review.
        form = page.locator("#checkout-form")
        form.locator('input[name="email"]').fill(email)
        form.locator('input[name="full_name"]').fill("WebsiteBench Shopper")
        form.locator('input[name="line1"]').fill("100 Test Street")
        form.locator('input[name="city"]').fill("Toronto")
        form.locator('select[name="province"]').select_option(label="Ontario")
        form.locator('input[name="postal_code"]').fill("M5V 2T6")
        form.locator('input[value^="Express Shipping"]').check()
        form.locator('input[name="promo"]').fill("FENTY10")
        form.locator('[data-apply-promo]').click()
        expect(page.locator("#toast")).to_contain_text("Promo applied")
        form.locator('select[name="payment"]').select_option("sandbox-approved")
        form.get_by_role("button", name="REVIEW ORDER").click()
        expect(page.get_by_text("Ready for final review.")).to_be_visible()
        review = page.locator("#checkout-review").inner_text()
        for required in ("185N", "Universal", "Discount", "Express Shipping", "sandbox-approved", "No real order has been placed"):
            assert required in review, (required, review)
        checks.append("delivery option, promo, local payment simulation and final order review")

        # WB048-T09/T10/T14/T19: profile/address, order history/actions, sign out and back in.
        page.goto(f"{args.base}/en-ca/account/favorites")
        expect(page.locator('[data-product-card="foundation"]')).to_be_visible()
        page.goto(f"{args.base}/en-ca/account/addresses")
        address = page.locator("#address-form")
        address.locator('input[name="full_name"]').fill("WebsiteBench Shopper")
        address.locator('input[name="line1"]').fill("100 Test Street")
        address.locator('input[name="city"]').fill("Toronto")
        address.locator('input[name="province"]').fill("Ontario")
        address.locator('input[name="postal_code"]').fill("M5V 2T6")
        address.get_by_role("button", name="SAVE ADDRESS").click()
        expect(page.get_by_text("100 Test Street")).to_be_visible()
        page.goto(f"{args.base}/en-ca/account/orders")
        order = page.locator(".source-order-card").first
        order_id = order.get_attribute("data-order")
        assert order_id
        expect(order).to_contain_text("Processing")
        expect(order).to_contain_text("185N")
        order.get_by_role("button", name="REORDER").click()
        expect(page.locator("#cart-count")).not_to_have_text("2")
        page.locator(f'[data-order="{order_id}"]').get_by_role("button", name="CANCEL ORDER").click()
        expect(page.locator(f'[data-order="{order_id}"]')).to_contain_text("Cancelled")
        page.locator(f'[data-order="{order_id}"]').get_by_role("button", name="START RETURN").click()
        expect(page.locator(f'[data-order="{order_id}"]')).to_contain_text("Return requested")
        expect(page.locator(f'[data-order="{order_id}"] a[href="/en-ca/collections/makeup-shop-all"]')).to_be_visible()
        page.locator("[data-logout]").first.click()
        page.wait_for_url("**/en-ca")
        page.goto(f"{args.base}/en-ca/account/login")
        expect(page.get_by_role("button", name="CONTINUE WITH GOOGLE")).to_be_disabled()
        page.locator('input[name="email"]').fill(email)
        page.locator('input[name="password"]').fill("WebsiteBench!23")
        page.get_by_role("button", name="SIGN IN", exact=True).click()
        page.wait_for_url("**/en-ca/account")
        expect(page.get_by_role("heading", name="WebsiteBench Shopper")).to_be_visible()
        checks.append("profile/address, saved items, newest order actions/history and sign-out/sign-in")

        # WB048-T15-T18/T20-T22: no results, auth entries, validation/permission, help and 404.
        page.goto(f"{args.base}/en-ca/search?q=zzzz-no-match-websitebench")
        expect(page.locator('[data-testid="no-results"]')).to_be_visible()
        expect(page.get_by_role("link", name="BACK TO ALL MAKEUP")).to_be_visible()
        page.goto(f"{args.base}/en-ca/account/recover")
        expect(page.get_by_role("link", name="RETURN TO SIGN IN")).to_be_visible()
        page.locator('input[name="email"]').fill(email)
        page.get_by_role("button", name="PREVIEW RESET").click()
        expect(page.locator("#auth-error")).to_contain_text("No message was sent")
        page.goto(f"{args.base}/en-ca/checkout")
        form = page.locator("#checkout-form")
        form.locator('input[name="email"]').fill("")
        form.get_by_role("button", name="REVIEW ORDER").click()
        expect(page.locator("#checkout-error")).to_contain_text("Complete the required")
        page.goto(f"{args.base}/en-ca/pages/help-center")
        expect(page.get_by_role("heading", name="HELP CENTER")).to_be_visible()
        help_text = page.locator("main").inner_text().casefold()
        for required in ("orders + returns", "account access", "product + shade help"):
            assert required in help_text, (required, help_text)
        response = page.goto(f"{args.base}/en-ca/not-a-real-fenty-page")
        assert response and response.status == 404
        expect(page.get_by_test_id("not-found")).to_be_visible()
        expect(page.get_by_role("link", name="SHOP MAKEUP")).to_be_visible()
        checks.append("no-results, auth/recovery/validation, public help and branded 404 recovery")

        context.close()
        browser.close()

    print(json.dumps({"ok": True, "base": args.base, "checks": checks, "trace_status": {trace: "passed" for trace in ALL_TRACES}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
