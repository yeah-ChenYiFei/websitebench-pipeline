#!/usr/bin/env python3
"""Faithful anonymous source capture for the ASPCA Pet Health Insurance clone.

Reads scope/source-capture-plan.json and captures every URL-addressable
checkpoint at each configured viewport into source-current/<capture_id>/.
For each (checkpoint, viewport) it writes N full-page frames (frame-1.png ...),
the rendered HTML, a link census, a runtime resource census (the asset-closure
discovery input), and a per-capture meta.json (final url, title, body length,
frame sha256s and an inter-frame identical flag used for flicker calibration).

Channel: all local egress to the source receives a WAF 403, so capture runs in
a Browserbase cloud session driven over CDP by local Playwright. One session
covers every viewport (CDP viewport emulation), which keeps Kameleoon A/B
assignment constant across the whole matrix. The session id and signed connect
URL live only in process memory and are never printed or persisted.

Interaction-dependent funnel/portal states are out of scope here -- they are
captured by capture_states.py in the same artifact layout.

Usage:
    python3 materials/aspca-pet-insurance/tools/capture_source.py \
        --site-dir materials/aspca-pet-insurance [--only home,quote-start] \
        [--settle-ms 5000]

Requires BROWSERBASE_API_KEY in the environment (never persisted).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BB_API = os.environ.get("BROWSERBASE_API_URL", "https://api.browserbase.com").rstrip("/")

# Checkpoints whose state requires scripted interaction; capture_states.py owns
# them. Everything else in the plan with an http(s) url is URL-addressable.
INTERACTIVE_IDS = {
    "quote-start-validation", "quote-rates", "quote-plan-customize",
    "quote-plan-detail", "quote-ineligible", "quote-save", "quote-checkout",
    "portal-login-validation", "portal-forgot-password", "portal-register",
}

# Post-navigation readiness selectors for SPA surfaces (AngularJS funnel and
# the modern-Angular portal render asynchronously after document load).
WAIT_SELECTORS = {
    "quote-start": "text=See My Rates",
    "portal-login": "input[type=password]",
}


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bb_request(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BB_API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-BB-API-Key": os.environ["BROWSERBASE_API_KEY"],
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def bb_create_session(width: int, height: int, timeout_s: int = 3600) -> dict:
    payload = {
        "timeout": timeout_s,
        "keepAlive": False,
        "region": "us-east-1",
        "browserSettings": {
            "blockAds": True,
            "solveCaptchas": True,
            "viewport": {"width": width, "height": height},
        },
        "userMetadata": {"purpose": "websitebench-offline-clone-capture"},
    }
    project_id = os.environ.get("BROWSERBASE_PROJECT_ID")
    if project_id:
        payload["projectId"] = project_id
    return bb_request("POST", "/v1/sessions", payload)


def bb_connect_url(sess: dict) -> str:
    url = sess.get("connectUrl")
    if url:
        return url
    deadline = time.time() + 15
    while time.time() < deadline:
        debug = bb_request("GET", f"/v1/sessions/{sess['id']}/debug")
        ws = debug.get("wsUrl")
        if ws:
            return ws
        time.sleep(1)
    raise RuntimeError("Browserbase debug WebSocket did not become ready")


def bb_release(session_id: str) -> None:
    try:
        bb_request("POST", f"/v1/sessions/{session_id}",
                   {"status": "REQUEST_RELEASE"})
        print("browserbase session release requested")
    except Exception as exc:  # noqa: BLE001
        print(f"browserbase session release failed: {type(exc).__name__}",
              file=sys.stderr)


def hide_scrollbars(page) -> None:
    """Cloud Chrome uses classic scrollbars that consume layout width, unlike
    the overlay scrollbars of the release-gate render environment. Hide them so
    the layout viewport equals the declared viewport exactly."""
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setScrollbarsHidden", {"hidden": True})
    except Exception:  # noqa: BLE001 - fall back to CSS injection
        page.add_init_script(
            "const s=document.createElement('style');"
            "s.textContent='::-webkit-scrollbar{display:none}"
            "html{scrollbar-width:none}';"
            "document.addEventListener('DOMContentLoaded',()=>"
            "document.head.appendChild(s));")


def dismiss_consent(page) -> str | None:
    """Accept the Osano consent dialog once if it renders; consent state then
    persists for the whole session so every frame shares one banner state."""
    try:
        btn = page.locator(".osano-cm-accept-all")
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(900)
            return "osano-accept-all"
    except Exception:  # noqa: BLE001
        pass
    return None


def census(page) -> list[str]:
    return page.eval_on_selector_all(
        "a[href]",
        "els=>Array.from(new Set(els.map(e=>((e.innerText||'').trim().slice(0,48)"
        "+' :: '+e.getAttribute('href'))))).filter(x=>x && !x.startsWith(' :: #'))",
    )


def resource_census(page) -> list[dict]:
    return page.evaluate(
        "()=>performance.getEntriesByType('resource').map(e=>({"
        "url:e.name, initiator:e.initiatorType,"
        "transfer_size:e.transferSize}))")


REGION_JS = """
() => {
  const pick = sels => {
    for (const s of sels) {
      const e = document.querySelector(s);
      if (e) {
        const r = e.getBoundingClientRect();
        if (r.width > 0 && r.height > 0)
          return {selector: s, x: Math.round(r.x + window.scrollX),
                  y: Math.round(r.y + window.scrollY),
                  width: Math.round(r.width), height: Math.round(r.height)};
      }
    }
    return null;
  };
  return {
    header: pick(['header', '[role=banner]', 'nav', '.navbar', '#header']),
    main: pick(['main', '[role=main]', '#main-content', '#content', '[ng-view]', 'router-outlet ~ *']),
    footer: pick(['footer', '[role=contentinfo]', '.footer', '#footer']),
    form: pick(['form']),
    document_height: Math.round(Math.max(
      document.documentElement.scrollHeight, document.body.scrollHeight)),
  };
}
"""

FINGERPRINT_JS = """
() => ({
  user_agent: navigator.userAgent,
  platform: navigator.platform,
  languages: navigator.languages,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  device_pixel_ratio: window.devicePixelRatio,
  inner: {width: window.innerWidth, height: window.innerHeight},
})
"""


def snap_frames(page, dest: pathlib.Path, frames: int) -> list[str]:
    shas: list[str] = []
    for n in range(1, frames + 1):
        fp = dest / f"frame-{n}.png"
        page.screenshot(path=str(fp), full_page=True)
        shas.append(sha256_file(fp))
        if n < frames:
            page.wait_for_timeout(700)
    return shas


def write_capture(page, dest: pathlib.Path, cp: dict, vp_name: str,
                  frames: int, shas: list[str], http_status: int | None,
                  consent: str | None) -> dict:
    (dest / "page.html").write_text(page.content())
    links = census(page)
    (dest / "links.json").write_text(json.dumps(links, indent=2))
    resources = resource_census(page)
    (dest / "resources.json").write_text(json.dumps(resources, indent=2))
    regions = page.evaluate(REGION_JS)
    body_len = len(page.eval_on_selector("body", "e=>e.innerText"))
    meta = {
        "checkpoint": cp["id"], "family": cp["family"],
        "priority": cp["priority"].upper(), "viewport": vp_name,
        "requested_url": cp["url"], "final_url": page.url,
        "http_status": http_status,
        "title": page.title(), "body_text_len": body_len,
        "frames": frames, "frame_sha256": shas,
        "frames_identical": len(set(shas)) == 1,
        "link_count": len(links), "resource_count": len(resources),
        "engine": "browserbase", "nav_fallback": None,
        "consent_action": consent,
        "regions": regions,
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def capture_checkpoint(page, cp: dict, vp: dict, out_root: pathlib.Path,
                       settle_ms: int) -> dict:
    dest = out_root / cp["id"] / vp["name"]
    dest.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
    resp = page.goto(cp["url"], wait_until="domcontentloaded", timeout=60000)
    wait_sel = WAIT_SELECTORS.get(cp["id"])
    if wait_sel:
        try:
            page.wait_for_selector(wait_sel, timeout=20000)
        except Exception:  # noqa: BLE001 - capture whatever rendered
            print(f"  ~ {cp['id']}: readiness selector not seen", file=sys.stderr)
    page.wait_for_timeout(settle_ms)
    consent = dismiss_consent(page)
    frames = int(vp.get("frames", 3))
    shas = snap_frames(page, dest, frames)
    status = resp.status if resp else None
    meta = write_capture(page, dest, cp, vp["name"], frames, shas, status,
                         consent)
    flag = "=" if meta["frames_identical"] else "~"
    print(f"  ok {cp['id']}/{vp['name']} [{status}] {flag} "
          f"body={meta['body_text_len']} links={meta['link_count']} "
          f"res={meta['resource_count']} -> {page.url}")
    return meta


def capture(site_dir: pathlib.Path, only: set[str] | None,
            settle_ms: int) -> int:
    plan = json.loads((site_dir / "scope" / "source-capture-plan.json").read_text())
    capture_id = plan["capture_id"]
    out_root = site_dir / "source-current" / capture_id
    viewport_by_name = {v["name"]: v for v in plan["viewports"]}
    checkpoints = []
    for cp in plan["checkpoints"]:
        if only and cp["id"] not in only:
            continue
        if cp["id"] in INTERACTIVE_IDS or not cp["url"].startswith("http"):
            if only:
                print(f"skipping {cp['id']}: not URL-addressable here")
            continue
        checkpoints.append(cp)
    if not checkpoints:
        print("nothing to capture")
        return 1

    records: list[dict] = []
    sess = bb_create_session(1440, 900)
    print("browserbase session created (id withheld from logs)")
    ws_url = bb_connect_url(sess)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws_url)
            try:
                ctx = browser.contexts[0]
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                hide_scrollbars(page)
                fingerprint_written = False
                for cp in checkpoints:
                    for vp_name in cp["viewports"]:
                        vp = viewport_by_name[vp_name]
                        try:
                            records.append(capture_checkpoint(
                                page, cp, vp, out_root, settle_ms))
                        except Exception as exc:  # noqa: BLE001
                            print(f"  ! {cp['id']}/{vp_name}: {exc}",
                                  file=sys.stderr)
                            records.append({
                                "checkpoint": cp["id"], "viewport": vp_name,
                                "engine": "browserbase",
                                "error": str(exc)[:200]})
                        if not fingerprint_written:
                            fp = page.evaluate(FINGERPRINT_JS)
                            out_root.mkdir(parents=True, exist_ok=True)
                            (out_root / "session-fingerprint.json").write_text(
                                json.dumps(fp, indent=2))
                            fingerprint_written = True
            finally:
                browser.close()
    finally:
        bb_release(sess["id"])

    index_path = out_root / "capture-index.json"
    if only and index_path.is_file():
        fresh = {(r.get("checkpoint"), r.get("viewport")) for r in records}
        previous = json.loads(index_path.read_text()).get("captures", [])
        records = [r for r in previous
                   if (r.get("checkpoint"), r.get("viewport")) not in fresh
                   ] + records
    index = {"schema_version": "aspca-pet-insurance.capture-index.v1",
             "capture_id": capture_id, "captures": records}
    index_path.write_text(json.dumps(index, indent=2))
    print(f"\nwrote {len(records)} capture records -> {index_path}")
    failures = [r for r in records if "error" in r]
    if failures:
        print(f"{len(failures)} capture unit(s) failed", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-dir", default="materials/aspca-pet-insurance")
    ap.add_argument("--only", default="", help="comma-separated checkpoint ids")
    ap.add_argument("--settle-ms", type=int, default=5000)
    args = ap.parse_args()
    only = {s for s in args.only.split(",") if s} or None
    return capture(pathlib.Path(args.site_dir), only, args.settle_ms)


if __name__ == "__main__":
    raise SystemExit(main())
