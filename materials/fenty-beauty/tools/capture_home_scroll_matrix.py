from __future__ import annotations

import argparse
import re
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright


VIEWPORTS = (
    {"name": "mobile", "width": 390, "height": 844},
    {"name": "ide-tablet", "width": 768, "height": 900},
    {"name": "desktop", "width": 1440, "height": 900},
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture vertical and horizontal viewport states for the public Fenty home page."
    )
    parser.add_argument("--url", default="https://fentybeauty.com/en-ca")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--settle-ms", type=int, default=7000)
    parser.add_argument(
        "--seed-state",
        choices=("none", "cart", "account", "account-cart"),
        default="none",
        help="Seed local WebsiteBench state before capture. Only use with localhost URLs.",
    )
    parser.add_argument(
        "--open-cart",
        action="store_true",
        help="Open the local My Bag drawer before taking screenshots.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    allowed_hosts = {urlparse(args.url).hostname, "www.fentybeauty.com"}
    manifest: dict[str, object] = {
        "schema_version": "websitebench.fenty-home-scroll-matrix.v1",
        "source_url": args.url,
        "policy": {
            "allowed_hosts": sorted(host for host in allowed_hosts if host),
            "allowed_method": "GET",
            "mutating_actions": False,
        },
        "viewports": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for viewport in VIEWPORTS:
            viewport_dir = args.out / viewport["name"]
            viewport_dir.mkdir(parents=True, exist_ok=True)
            context = browser.new_context(
                viewport={"width": viewport["width"], "height": viewport["height"]},
                locale="en-CA",
                timezone_id="America/Toronto",
                reduced_motion="reduce",
            )
            blocked: list[dict[str, str]] = []

            def route_request(route: Route) -> None:
                request = route.request
                parsed = urlparse(request.url)
                if request.method != "GET":
                    if (
                        args.seed_state != "none"
                        and parsed.hostname in {"127.0.0.1", "localhost"}
                        and parsed.path == "/api/checkout/preview"
                        and request.method == "POST"
                    ):
                        route.continue_()
                        return
                    blocked.append({"method": request.method, "url": request.url, "reason": "non-get"})
                    route.abort()
                    return
                if parsed.scheme in {"http", "https"} and parsed.hostname not in allowed_hosts:
                    blocked.append({"method": request.method, "url": request.url, "reason": "origin"})
                    route.abort()
                    return
                route.continue_()

            context.route("**/*", route_request)
            if args.seed_state != "none":
                parsed_source = urlparse(args.url)
                if parsed_source.hostname not in {"127.0.0.1", "localhost"}:
                    raise ValueError("--seed-state is restricted to localhost captures")
                origin = f"{parsed_source.scheme}://{parsed_source.netloc}"
                context.request.get(f"{origin}/api/bootstrap")
                if args.seed_state in {"account", "account-cart"}:
                    capture_key = re.sub(r"[^a-z0-9]+", "-", args.out.name.lower()).strip("-")
                    context.request.post(
                        f"{origin}/api/auth/register",
                        data={
                            "display_name": f"WebsiteBench Shopper {viewport['name']}",
                            "email": f"{capture_key}-{viewport['name']}@example.test",
                            "password": "WebsiteBench!23",
                        },
                    )
                    context.request.post(
                        f"{origin}/api/account/address",
                        data={
                            "full_name": "WebsiteBench Shopper",
                            "line1": "100 Test Street",
                            "city": "Toronto",
                            "province": "Ontario",
                            "postal_code": "M5V 2T6",
                            "country": "Canada",
                        },
                    )
                    context.request.post(
                        f"{origin}/api/favorites/toggle",
                        data={"product_id": "foundation"},
                    )
                if args.seed_state in {"cart", "account-cart"}:
                    context.request.post(
                        f"{origin}/api/cart/add",
                        data={
                            "product_id": "foundation",
                            "variant": "185",
                            "size": "Standard 32 mL",
                            "quantity": 1,
                        },
                    )
                    context.request.post(
                        f"{origin}/api/cart/add",
                        data={
                            "product_id": "powder",
                            "variant": "Universal",
                            "size": "Standard 8.5 g",
                            "quantity": 1,
                        },
                    )
            page = context.new_page()
            response = page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(args.settle_ms)
            if args.open_cart:
                page.locator('[data-action="open-cart"]').click()
                page.locator("#cart-drawer.open").wait_for()
                page.wait_for_timeout(300)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)

            page_height = int(page.evaluate("document.documentElement.scrollHeight"))
            max_y = max(0, page_height - viewport["height"])
            stride = max(1, int(viewport["height"] * 0.78))
            positions = list(range(0, max_y + 1, stride))
            if not positions or positions[-1] != max_y:
                positions.append(max_y)

            vertical_frames: list[dict[str, object]] = []
            for index, position in enumerate(positions):
                actual_y = int(
                    page.evaluate(
                        "position => { window.scrollTo(0, position); return window.scrollY; }",
                        position,
                    )
                )
                page.wait_for_timeout(350)
                filename = f"vertical-{index:02d}-y{actual_y}.png"
                page.screenshot(path=str(viewport_dir / filename), full_page=False, animations="disabled")
                vertical_frames.append({"index": index, "scroll_y": actual_y, "file": filename})

            page.evaluate("window.scrollTo(0, 0)")
            carousels = page.locator("[data-carousel-slides], [data-home-carousel]")
            carousel_frames: list[dict[str, object]] = []
            for index in range(carousels.count()):
                carousel = carousels.nth(index)
                if not carousel.is_visible():
                    continue
                carousel.scroll_into_view_if_needed()
                metrics = carousel.evaluate(
                    "element => ({scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, "
                    "label: element.getAttribute('aria-label') || "
                    "element.closest('section')?.querySelector('h2')?.textContent?.trim() || "
                    "element.closest('[aria-label]')?.getAttribute('aria-label') || '', "
                    "slideCount: element.querySelectorAll('[data-carousel-slide], [data-product-card], [data-brand-card]').length})"
                )
                max_x = max(0, int(metrics["scrollWidth"]) - int(metrics["clientWidth"]))
                states = (("left", 0), ("middle", max_x // 2), ("right", max_x))
                files: list[dict[str, object]] = []
                for state, target_x in states:
                    actual_x = int(
                        carousel.evaluate(
                            "(element, target) => { element.scrollTo({left: target, behavior: 'instant'}); "
                            "return element.scrollLeft; }",
                            target_x,
                        )
                    )
                    page.wait_for_timeout(350)
                    viewport_file = f"carousel-{index:02d}-{state}-viewport.png"
                    clip_file = f"carousel-{index:02d}-{state}-clip.png"
                    page.screenshot(
                        path=str(viewport_dir / viewport_file),
                        full_page=False,
                        animations="disabled",
                    )
                    carousel.screenshot(path=str(viewport_dir / clip_file), animations="disabled")
                    files.append(
                        {
                            "state": state,
                            "scroll_x": actual_x,
                            "viewport_file": viewport_file,
                            "clip_file": clip_file,
                        }
                    )
                carousel_frames.append({"index": index, **metrics, "maxScrollX": max_x, "states": files})

            manifest["viewports"].append(
                {
                    **viewport,
                    "http_status": response.status if response else None,
                    "page_height": page_height,
                    "vertical_frames": vertical_frames,
                    "carousels": carousel_frames,
                    "blocked_requests": blocked,
                }
            )
            context.close()
        browser.close()

    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "out": str(args.out),
        "viewports": [
            {
                "name": item["name"],
                "vertical_frames": len(item["vertical_frames"]),
                "carousels": len(item["carousels"]),
                "blocked_requests": len(item["blocked_requests"]),
            }
            for item in manifest["viewports"]
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
