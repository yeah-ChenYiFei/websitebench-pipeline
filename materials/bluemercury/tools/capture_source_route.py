#!/usr/bin/env python3
"""Capture one anonymous, GET-only Bluemercury source route with Playwright."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


SOURCE_HOSTS = {"bluemercury.com", "www.bluemercury.com"}


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
    if parsed.scheme != "https" or parsed.hostname not in SOURCE_HOSTS:
        raise ValueError("source capture URL must be https://bluemercury.com")
    if not args.name.replace("-", "").isalnum():
        raise ValueError("capture name must be alphanumeric with optional hyphens")

    args.out.mkdir(parents=True, exist_ok=True)
    blocked_mutations: list[dict[str, str]] = []
    failed_requests: list[dict[str, str]] = []
    console_errors: list[str] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=str(args.browser),
        )
        context = await browser.new_context(
            viewport={"width": args.width, "height": args.height},
            locale="en-US",
        )

        async def guard(route) -> None:
            request = route.request
            if request.method.upper() != "GET":
                blocked_mutations.append({"method": request.method, "url": request.url})
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", guard)
        page = await context.new_page()
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                {
                    "method": request.method,
                    "url": request.url,
                    "reason": request.failure or "unknown",
                }
            ),
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        response = await page.goto(args.url, wait_until="domcontentloaded", timeout=20_000)
        await page.wait_for_timeout(2_500)
        result: dict[str, object] = {
            "authority": "anonymous-read-only",
            "requested_url": args.url,
            "final_url": page.url,
            "status": response.status if response else None,
            "title": await page.title(),
            "viewport": {"width": args.width, "height": args.height},
            "links": await page.locator("a").count(),
            "buttons": await page.locator("button").count(),
            "forms": await page.locator("form").count(),
            "blocked_mutations": blocked_mutations,
            "failed_requests": failed_requests,
            "console_errors": console_errors,
            "visible_text": (await page.locator("body").inner_text())[:5_000],
        }
        prefix = f"{args.name}-{args.width}x{args.height}"
        await page.screenshot(path=str(args.out / f"{prefix}.png"), full_page=False)
        (args.out / f"{prefix}.html").write_text(await page.content(), encoding="utf-8")
        (args.out / f"{prefix}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        await browser.close()
        return result


def main() -> int:
    args = parse_args()
    result = asyncio.run(capture(args))
    print(
        json.dumps(
            {
                "name": args.name,
                "status": result["status"],
                "final_url": result["final_url"],
                "links": result["links"],
                "buttons": result["buttons"],
                "forms": result["forms"],
                "blocked_mutations": len(result["blocked_mutations"]),
                "failed_requests": len(result["failed_requests"]),
                "console_errors": len(result["console_errors"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
