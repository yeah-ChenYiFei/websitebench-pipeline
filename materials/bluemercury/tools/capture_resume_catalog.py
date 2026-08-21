#!/usr/bin/env python3
"""Capture deterministic local catalog/search evidence with an isolated Edge context."""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "materials" / "bluemercury" / "artifacts" / "browser" / "resume-current"
BASE = os.environ.get("CLONE_BASE_URL", "http://127.0.0.1:8765")
EDGE = os.environ.get("EDGE_EXECUTABLE")
if not EDGE:
    EDGE = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=EDGE,
            args=["--disable-gpu"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            service_workers="block",
        )
        try:
            for name, path in (
                ("resume-desktop-collection", "/collections/skin-care"),
                ("resume-desktop-search", "/search?q=moisturizer&type=product"),
            ):
                external: list[str] = []
                page = context.new_page()
                page.on(
                    "request",
                    lambda request: external.append(request.url)
                    if not request.url.startswith(BASE)
                    else None,
                )
                response = page.goto(BASE + path, wait_until="networkidle")
                page.locator(".product-grid").wait_for(state="visible")
                cards = page.locator(".product-card")
                links = page.locator(".product-card a[href^='/products/']")
                result = {
                    "name": name,
                    "path": path,
                    "status": response.status if response else None,
                    "heading": page.locator(".catalog-head h1").inner_text(),
                    "product_count_text": page.locator(".catalog-head").inner_text(),
                    "product_cards": cards.count(),
                    "detail_links": links.count(),
                    "grid_visible": cards.count() > 0,
                    "external_requests": sorted(set(external)),
                    "screenshot": f"{name}.png",
                }
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
                results.append(result)
                page.close()
        finally:
            context.close()
            browser.close()
    (OUT / "catalog-grid-check.json").write_text(
        json.dumps(
            {
                "schema_version": "bluemercury.catalog-grid-check.v1",
                "base_url": BASE,
                "browser": "Microsoft Edge via Playwright",
                "viewport": "1440x900",
                "routes": results,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
