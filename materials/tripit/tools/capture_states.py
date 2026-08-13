#!/usr/bin/env python3
"""Interaction-state capture for anonymous tripit.com surfaces via Steel.

Captures GET-only, side-effect-free interaction states (menus opened, client
validation displayed by typing + blur — no form submission, no non-GET
requests). Writes the same frame/meta layout as capture_source.py under
source-current/<capture_id>/<state_id>/<viewport>/.
"""
from __future__ import annotations

import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from capture_source import (  # noqa: E402
    CONSENT_COOKIES, census, hide_scrollbars, REGION_JS, retry_goto,
    sha256_file, steel_create_session, steel_request,
)

SITE = pathlib.Path("materials/tripit")
OUT = SITE / "source-current" / "2026-08-03.tripit-r1"

STATES = [
    {
        "id": "home-lang-menu-open",
        "family": "marketing",
        "priority": "P1",
        "url": "https://www.tripit.com/",
        "viewports": [("desktop", 1440, 900)],
        "actions": "open-language-menu",
    },
    {
        "id": "home-mobile-menu-open",
        "family": "marketing",
        "priority": "P0",
        "url": "https://www.tripit.com/",
        "viewports": [("mobile", 390, 844)],
        "actions": "open-mobile-menu",
    },
    {
        "id": "login-client-validation",
        "family": "auth",
        "priority": "P1",
        "url": "https://www.tripit.com/account/login",
        "viewports": [("desktop", 1440, 900)],
        "actions": "invalid-email-blur",
    },
]


def perform(page, action: str) -> dict:
    note = {"action": action, "performed": []}
    if action == "open-language-menu":
        for sel in ["button:has-text('EN')", "[aria-label*='language' i]",
                    ".language-selector", "button:has-text('English')"]:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                page.wait_for_timeout(800)
                note["performed"].append(f"click:{sel}")
                break
    elif action == "open-mobile-menu":
        for sel in ["button[aria-label*='menu' i]", ".hamburger",
                    "button.navbar-toggler", "[class*='menu-toggle']",
                    "[class*='hamburger']", "header button"]:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                page.wait_for_timeout(800)
                note["performed"].append(f"click:{sel}")
                break
    elif action == "invalid-email-blur":
        email = page.locator("#email_address")
        if email.count():
            email.first.click()
            email.first.type("not-an-email")
            page.keyboard.press("Tab")
            page.wait_for_timeout(800)
            note["performed"].append("type-invalid-email+tab-blur")
    return note


def main() -> int:
    records = []
    with sync_playwright() as p:
        for state in STATES:
            for name, width, height in state["viewports"]:
                sess = steel_create_session(width, height)
                print(f"steel {sess['id']} ({state['id']}/{name})")
                browser = p.chromium.connect_over_cdp(sess["websocketUrl"])
                ctx = browser.contexts[0]
                ctx.add_cookies(CONSENT_COOKIES)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.set_viewport_size({"width": width, "height": height})
                hide_scrollbars(page)
                dest = OUT / state["id"] / name
                dest.mkdir(parents=True, exist_ok=True)
                try:
                    retry_goto(page, state["url"])
                    page.wait_for_timeout(4000)
                    note = perform(page, state["actions"])
                    shas = []
                    for n in range(1, 4):
                        fp = dest / f"frame-{n}.png"
                        page.screenshot(path=str(fp), full_page=True)
                        shas.append(sha256_file(fp))
                        if n < 3:
                            page.wait_for_timeout(700)
                    (dest / "page.html").write_text(page.content())
                    links = census(page)
                    (dest / "links.json").write_text(json.dumps(links, indent=2))
                    regions = page.evaluate(REGION_JS)
                    meta = {
                        "checkpoint": state["id"], "family": state["family"],
                        "priority": state["priority"], "viewport": name,
                        "requested_url": state["url"], "final_url": page.url,
                        "title": page.title(),
                        "body_text_len": len(page.eval_on_selector(
                            "body", "e=>e.innerText")),
                        "frames": 3, "frame_sha256": shas,
                        "frames_identical": len(set(shas)) == 1,
                        "link_count": len(links), "engine": "steel",
                        "nav_fallback": None, "regions": regions,
                        "interaction": note,
                    }
                    (dest / "meta.json").write_text(json.dumps(meta, indent=2))
                    records.append(meta)
                    print(f"  ok {state['id']}/{name} {note['performed']}")
                except Exception as exc:  # noqa: BLE001
                    records.append({"checkpoint": state["id"], "viewport": name,
                                    "error": str(exc)[:200]})
                    print(f"  ! {state['id']}/{name}: {exc}", file=sys.stderr)
                browser.close()
                steel_request("POST", f"/sessions/{sess['id']}/release")
    index_path = OUT / "state-capture-index.json"
    index_path.write_text(json.dumps(
        {"schema_version": "tripit.state-capture-index.v1",
         "captures": records}, indent=2))
    print(f"wrote {len(records)} state records -> {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
