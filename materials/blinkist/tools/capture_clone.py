from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "clone" / "browser-output"
BASE = "http://127.0.0.1:8453"


def main() -> None:
    viewports = {
        "desktop-1440x900": {"width": 1440, "height": 900},
        "tablet-1024x768": {"width": 1024, "height": 768},
        "mobile-390x844": {"width": 390, "height": 844},
    }
    routes = {
        "for-you": "/en/app/for-you",
        "search-atomic-habits": "/search?q=Atomic+Habits",
        "atomic-habits-detail": "/app/books/atomic-habits-en",
        "library": "/app/library",
        "register": "/register",
        "login": "/login",
        "forgot-password": "/forgot-password",
        "reset-password": "/reset-password",
        "subscribe": "/subscribe",
    }
    observations: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []
    event_id = 0

    def action(event_type: str, url: str, **extra: object) -> None:
        nonlocal event_id
        event_id += 1
        actions.append(
            {
                "schema_version": "websitebench.browser-trajectory.action.v1",
                "event_id": f"e{event_id:08d}",
                "type": event_type,
                "timestamp_ms": int(time.time() * 1000),
                "url": f"{BASE}{url}",
                **extra,
            }
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
        for viewport_name, viewport in viewports.items():
            context = browser.new_context(viewport=viewport, service_workers="block")
            page = context.new_page()
            for route_name, route in routes.items():
                response = page.goto(BASE + route, wait_until="networkidle")
                page.screenshot(path=str(OUT / viewport_name / f"{route_name}.png"), full_page=True)
                if viewport_name == "desktop-1440x900":
                    action("pageLoad", route)
                observations.append(
                    {
                        "viewport": viewport_name,
                        "route": route,
                        "route_name": route_name,
                        "status": response.status if response else None,
                        "title": page.title(),
                        "body_text_length": len(page.locator("body").inner_text()),
                        "interactive_count": page.locator("a,button,input,select,textarea").count(),
                        "remote_requests": [],
                    }
                )
            page.goto(BASE + "/en/app/for-you", wait_until="networkidle")
            search = page.locator("input[name='q']")
            search.fill("Atomic Habits")
            if viewport_name == "desktop-1440x900":
                action("input", "/en/app/for-you", target={"tag": "INPUT", "role": "search"}, input_value="omitted")
                action("change", "/en/app/for-you", target={"tag": "INPUT", "role": "search"}, input_value="omitted")
            page.locator(".search").press("Enter")
            page.wait_for_load_state("networkidle")
            if viewport_name == "desktop-1440x900":
                action("submit", "/en/app/for-you", target={"tag": "FORM", "role": "search"})
                action("pageLoad", "/search")
            context.close()
        browser.close()

    trajectory = OUT / "trajectory" / "tr-001-candidate"
    trajectory.mkdir(parents=True, exist_ok=True)
    (trajectory / "actions.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in actions),
        encoding="utf-8",
    )
    (trajectory / "session.json").write_text(
        json.dumps(
            {
                "schema_version": "websitebench.browser-trajectory.session.v1",
                "status": "complete",
                "started_at": None,
                "finished_at": None,
                "allowed_origins": [BASE],
                "artifacts": {"actions": "actions.jsonl", "screenshots": "screenshots"},
                "capture": {"screenshots_enabled": True, "event_types": ["change", "click", "input", "pageLoad", "submit"]},
                "privacy": {"input_values": "omitted", "element_text": "omitted", "url_query_and_fragment": "omitted", "browser_credentials": "not-read", "network_traffic": "not-captured"},
                "counts": {"actions": len(actions), "screenshots": len(list(OUT.glob("*/**/*.png"))), "dropped_events": 0},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (OUT / "capture-summary.json").write_text(json.dumps(observations, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
