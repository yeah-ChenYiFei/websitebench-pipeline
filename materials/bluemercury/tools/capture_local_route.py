#!/usr/bin/env python3
"""Capture one local Bluemercury route and prove runtime network closure."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--browser", type=Path, required=True)
    return parser.parse_args()


async def capture(args: argparse.Namespace) -> dict[str, object]:
    parsed = urlparse(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("candidate capture URL must be local HTTP")
    args.out.mkdir(parents=True, exist_ok=True)
    external_requests: list[dict[str, str]] = []
    failed_requests: list[dict[str, str]] = []
    console_errors: list[str] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=str(args.browser))
        context = await browser.new_context(viewport={"width": args.width, "height": args.height}, locale="en-US")

        async def local_only(route) -> None:
            request = route.request
            target = urlparse(request.url)
            if target.hostname not in {"127.0.0.1", "localhost"}:
                external_requests.append({"method": request.method, "url": request.url})
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", local_only)
        page = await context.new_page()
        page.on("requestfailed", lambda request: failed_requests.append({"method": request.method, "url": request.url, "reason": request.failure or "unknown"}))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        response = await page.goto(args.url, wait_until="networkidle", timeout=20_000)
        result: dict[str, object] = {
            "requested_url": args.url,
            "final_url": page.url,
            "status": response.status if response else None,
            "title": await page.title(),
            "viewport": {"width": args.width, "height": args.height},
            "links": await page.locator("a").count(),
            "buttons": await page.locator("button").count(),
            "forms": await page.locator("form").count(),
            "external_requests": external_requests,
            "failed_requests": failed_requests,
            "console_errors": console_errors,
            "marker_present": "LOCAL CLONE" in await page.locator("body").inner_text(),
        }
        hero_image = page.locator("[data-hero-image]")
        if await hero_image.count():
            result["hero_image_geometry"] = await hero_image.evaluate(
                "el => { const s=getComputedStyle(el), r=el.getBoundingClientRect(); return {width:r.width,height:r.height,objectFit:s.objectFit,objectPosition:s.objectPosition,content:s.content}; }"
            )
        prefix = f"{args.name}-{args.width}x{args.height}"
        await page.screenshot(path=str(args.out / f"{prefix}.png"), full_page=False)
        (args.out / f"{prefix}.html").write_text(await page.content(), encoding="utf-8")
        (args.out / f"{prefix}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        await browser.close()
        return result


def main() -> int:
    args = parse_args()
    result = asyncio.run(capture(args))
    print(json.dumps({key: result[key] for key in ("status", "final_url", "links", "buttons", "forms", "external_requests", "failed_requests", "console_errors", "marker_present")}, ensure_ascii=False))
    return 1 if result["status"] != 200 or result["external_requests"] or result["failed_requests"] or result["console_errors"] or result["marker_present"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
