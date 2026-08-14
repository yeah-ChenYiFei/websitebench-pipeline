#!/usr/bin/env python3
"""Diagnose why the See My Rates submit does not advance the funnel route.

Fills the Willow scenario like capture_states.py, then before and after the
submit click dumps: every .ng-invalid control, visible modal/error text, the
hash route, console messages, and any request to the quoting service
(/api/q/). Saves screenshots to /tmp/aspca-run-notes/ for inspection.
Diagnostic-only; no artifacts are written under materials/.
"""
from __future__ import annotations

import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from capture_source import (  # noqa: E402
    bb_connect_url, bb_create_session, bb_release, dismiss_consent,
    hide_scrollbars,
)
from capture_states import Walk, fill_willow, fresh_funnel  # noqa: E402

INVALID_JS = """() => Array.from(document.querySelectorAll('.ng-invalid'))
  .filter(e => e.tagName !== 'FORM' && e.tagName !== 'NG-FORM')
  .map(e => ({tag: e.tagName.toLowerCase(), id: e.id || null,
              name: e.getAttribute('name') || null,
              classes: (e.className || '').toString().slice(0, 160)}))"""

VISIBLE_TEXT_JS = """sel => Array.from(document.querySelectorAll(sel))
  .filter(e => e.offsetParent !== null)
  .map(e => e.innerText.trim()).filter(Boolean).slice(0, 20)"""


def dump(page, tag: str) -> None:
    print(f"--- {tag} ---", flush=True)
    print("hash:", page.evaluate("()=>location.hash"), flush=True)
    print("ng-invalid:", json.dumps(page.evaluate(INVALID_JS), indent=1),
          flush=True)
    print("modals:", page.evaluate(
        VISIBLE_TEXT_JS, "[class*='modal'], [role='dialog']"), flush=True)
    print("errors:", page.evaluate(
        VISIBLE_TEXT_JS, "[class*='error'], [role='alert']"), flush=True)
    page.screenshot(
        path=f"/tmp/aspca-run-notes/diag-{tag}.png", full_page=True)


def main() -> int:
    sess = bb_create_session(1440, 900)
    print("browserbase session created (id withheld from logs)")
    ws_url = bb_connect_url(sess)
    api_events: list[str] = []
    console: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws_url)
            try:
                ctx = browser.contexts[0]
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                hide_scrollbars(page)
                page.set_viewport_size({"width": 1440, "height": 900})
                page.on("console", lambda m: console.append(
                    f"{m.type}: {m.text[:200]}"))
                page.on("request", lambda r: api_events.append(
                    f"req {r.method} {r.url[:160]}")
                    if "/api/" in r.url else None)
                page.on("response", lambda r: api_events.append(
                    f"res {r.status} {r.url[:160]}")
                    if "/api/" in r.url else None)
                walk = Walk(page, "willow-capture-2026-08-13"
                                  "@websitebench.invalid", False)
                fresh_funnel(walk)
                dismiss_consent(page)
                fill_willow(walk)
                page.wait_for_timeout(1500)
                dump(page, "pre-submit")
                page.locator("button.g-recaptcha[type=submit]").first.click()
                for wait_tag in ("t5", "t15", "t30"):
                    page.wait_for_timeout(
                        5000 if wait_tag == "t5" else 10000
                        if wait_tag == "t15" else 15000)
                    dump(page, wait_tag)
                    if page.evaluate("()=>location.hash") != "#/start":
                        break
                print("api events:", flush=True)
                for e in api_events:
                    print("  ", e, flush=True)
                print("console (errors/warnings):", flush=True)
                for c in console:
                    if c.startswith(("error", "warning")):
                        print("  ", c, flush=True)
            finally:
                browser.close()
    finally:
        bb_release(sess["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
