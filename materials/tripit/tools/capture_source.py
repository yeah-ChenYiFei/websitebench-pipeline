#!/usr/bin/env python3
"""Faithful anonymous source capture for the TripIt offline clone.

Reads scope/source-capture-plan.json and captures each checkpoint at every
configured viewport into source-current/<capture_id>/. For each (checkpoint,
viewport) it writes N full-page frames (frame-1.png ...), the rendered HTML,
a link census, and a per-capture meta.json (final url, title, body length,
frame sha256s and an inter-frame identical ratio used for flicker calibration).

Environment (this sandbox has no system fonts and geolocates to the EU
TrustArc gate) MUST be set before running -- see the module docstring's
recipe or memory/tripit-local-capture-recipe.md:

    export LD_LIBRARY_PATH="$HOME/chromium-libs/usr/lib/x86_64-linux-gnu"
    export FONTCONFIG_FILE="$HOME/chromium-libs/etc/fonts/fonts.conf"

Usage:
    .venv/bin/python materials/tripit/tools/capture_source.py \
        --site-dir materials/tripit [--only home,login] [--settle-ms 5000]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from playwright.sync_api import sync_playwright

STEEL_API = "https://api.steel.dev/v1"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# TrustArc expressed-consent state so EU gate does not block content render.
CONSENT_COOKIES = [
    {"domain": ".tripit.com", "path": "/", "name": n, "value": v}
    for n, v in [
        ("notice_behavior", "expressed,eu"),
        ("notice_gdpr_prefs", "0,1,2:"),
        ("notice_preferences", "2:"),
        ("notice_location", "eu"),
        ("cmapi_cookie_privacy", "permit 1,2,3"),
        ("cmapi_gtm_bl", ""),
    ]
]


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def steel_request(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{STEEL_API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"steel-api-key": os.environ["STEEL_API_KEY"],
                 "Content-Type": "application/json",
                 "User-Agent": "steel-cli/0.4.4"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def steel_create_session(width: int, height: int) -> dict:
    return steel_request("POST", "/sessions", {
        "region": "lax",
        "dimensions": {"width": width, "height": height},
        "timezone": "America/New_York",
        "inactivityTimeout": 600000,
    })


def hide_scrollbars(page) -> None:
    """Steel cloud Chrome uses classic scrollbars that consume 15px of layout
    width, unlike the overlay scrollbars of local headless capture and of the
    release-gate render environment. Hide them so the layout viewport equals
    the declared viewport exactly (recorded in capture metadata)."""
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


def retry_goto(page, url: str, attempts: int = 5) -> None:
    """tripit.com intermittently nginx-500s Steel egress IPs; retry until a
    real page (not an error shell) is served."""
    last = None
    for _ in range(attempts):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        title = page.title()
        if "500" not in title and "Error" not in title:
            return
        last = title
        page.wait_for_timeout(2000)
    raise RuntimeError(f"still error page after {attempts} attempts: {last!r}")


def robust_goto(page, ctx, url: str) -> str | None:
    """Navigate to url, falling back to an HTTP/1.1 fetch + route-fulfill when
    Chromium's HTTP/2 stack rejects the endpoint (some tripit.com routes emit
    ERR_HTTP2_PROTOCOL_ERROR on direct navigation but serve fine via request)."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        return None
    except Exception as exc:  # noqa: BLE001
        if "ERR_HTTP2" not in str(exc):
            raise
        html = ctx.request.get(url, timeout=30000).text()
        page.route(url, lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=html))
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        return "http2-fallback"


def census(page) -> list[str]:
    return page.eval_on_selector_all(
        "a[href]",
        "els=>Array.from(new Set(els.map(e=>((e.innerText||'').trim().slice(0,48)"
        "+' :: '+e.getAttribute('href'))))).filter(x=>x && !x.startsWith(' :: #'))",
    )


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
    main: pick(['main', '[role=main]', '#main-content', '#content']),
    footer: pick(['footer', '[role=contentinfo]', '.footer', '#footer']),
    form: pick(['form']),
    document_height: Math.round(Math.max(
      document.documentElement.scrollHeight, document.body.scrollHeight)),
  };
}
"""


def capture_checkpoint(page, ctx, cp: dict, vp: dict, out_root: pathlib.Path,
                       settle_ms: int, engine: str) -> dict:
    dest = out_root / cp["id"] / vp["name"]
    dest.mkdir(parents=True, exist_ok=True)
    fallback = None
    if engine == "steel":
        retry_goto(page, cp["url"])
    else:
        fallback = robust_goto(page, ctx, cp["url"])
    page.wait_for_timeout(settle_ms)
    frames = int(vp.get("frames", 1))
    shas: list[str] = []
    for n in range(1, frames + 1):
        fp = dest / f"frame-{n}.png"
        page.screenshot(path=str(fp), full_page=True)
        shas.append(sha256_file(fp))
        if n < frames:
            page.wait_for_timeout(700)
    (dest / "page.html").write_text(page.content())
    links = census(page)
    (dest / "links.json").write_text(json.dumps(links, indent=2))
    regions = page.evaluate(REGION_JS)
    body_len = len(page.eval_on_selector("body", "e=>e.innerText"))
    identical = len(set(shas)) == 1
    meta = {
        "checkpoint": cp["id"], "family": cp["family"],
        "priority": cp["priority"], "viewport": vp["name"],
        "requested_url": cp["url"], "final_url": page.url,
        "title": page.title(), "body_text_len": body_len,
        "frames": frames, "frame_sha256": shas,
        "frames_identical": identical, "link_count": len(links),
        "engine": engine, "nav_fallback": fallback,
        "regions": regions,
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2))
    flag = "=" if identical else "~"
    print(f"  ok {cp['id']}/{vp['name']} [{engine}] {flag} "
          f"body={body_len} links={len(links)} -> {page.url}")
    return meta


def _error_record(cp: dict, vp: dict, engine: str, exc: Exception) -> dict:
    print(f"  ! {cp['id']}/{vp['name']}: {exc}", file=sys.stderr)
    return {"checkpoint": cp["id"], "viewport": vp["name"],
            "engine": engine, "error": str(exc)[:200]}


def capture_viewport_steel(vp: dict, checkpoints: list[dict],
                           out_root: pathlib.Path, settle_ms: int) -> list[dict]:
    """Capture every checkpoint at one viewport inside one Steel session.

    Runs in a worker thread, so it opens its own sync_playwright(): Playwright's
    sync objects are bound to the thread that created them and cannot be driven
    from another. Session count is unchanged from the serial version (one per
    viewport) -- only the wall clock shrinks.

    A Steel session fixes its window dimensions at create time, so a session
    must not be reused across viewports.
    """
    records: list[dict] = []
    with sync_playwright() as p:
        sess = steel_create_session(vp["width"], vp["height"])
        print(f"steel session {sess['id']} ({vp['name']}) "
              f"viewer: {sess['sessionViewerUrl']}")
        browser = p.chromium.connect_over_cdp(sess["websocketUrl"])
        try:
            ctx = browser.contexts[0]
            ctx.add_cookies(CONSENT_COOKIES)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
            hide_scrollbars(page)
            for cp in checkpoints:
                try:
                    records.append(capture_checkpoint(
                        page, ctx, cp, vp, out_root, settle_ms, "steel"))
                except Exception as exc:  # noqa: BLE001
                    records.append(_error_record(cp, vp, "steel", exc))
        finally:
            browser.close()
            steel_request("POST", f"/sessions/{sess['id']}/release")
    return records


def capture_shard_local(shard: list[dict], viewports: list[dict],
                        out_root: pathlib.Path, settle_ms: int) -> list[dict]:
    """Capture a contiguous slice of checkpoints across every viewport.

    One Chromium per worker (not per unit), and its own sync_playwright().
    Iterating `for cp in shard: for vp in viewports` keeps each shard's records
    in the same order the serial version produced, so concatenating the shards
    in input order reproduces the original ordering exactly.
    """
    records: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"])
        try:
            for cp in shard:
                for vp in viewports:
                    ctx = browser.new_context(
                        viewport={"width": vp["width"], "height": vp["height"]},
                        locale="en-US", timezone_id="America/New_York",
                        user_agent=UA)
                    ctx.add_cookies(CONSENT_COOKIES)
                    page = ctx.new_page()
                    try:
                        records.append(capture_checkpoint(
                            page, ctx, cp, vp, out_root, settle_ms, "local"))
                    except Exception as exc:  # noqa: BLE001
                        records.append(_error_record(cp, vp, "local", exc))
                    ctx.close()
        finally:
            browser.close()
    return records


def _shards(items: list[dict], count: int) -> list[list[dict]]:
    """Split into `count` contiguous, near-equal, non-empty slices."""
    count = max(1, min(count, len(items)))
    size, extra = divmod(len(items), count)
    out: list[list[dict]] = []
    start = 0
    for i in range(count):
        stop = start + size + (1 if i < extra else 0)
        out.append(items[start:stop])
        start = stop
    return out


def capture(site_dir: pathlib.Path, only: set[str] | None, settle_ms: int,
            engine: str, workers: int) -> int:
    plan = json.loads((site_dir / "scope" / "source-capture-plan.json").read_text())
    capture_id = plan["capture_id"]
    out_root = site_dir / "source-current" / capture_id
    viewports = plan["viewports"]
    checkpoints = [c for c in plan["checkpoints"]
                   if not only or c["id"] in only]

    # Every (checkpoint, viewport) unit writes to its own out_root/<cp>/<vp>
    # directory and reads nothing another unit produced, so the whole matrix is
    # independent. ex.map (not as_completed) keeps `records` in input order --
    # the order flows into capture-index.json and downstream frozen artifacts.
    records: list[dict] = []
    if engine == "steel":
        lanes = min(workers, len(viewports)) or 1
        print(f"capturing {len(checkpoints)} checkpoints x {len(viewports)} "
              f"viewports across {lanes} steel session(s) in parallel")
        with ThreadPoolExecutor(max_workers=lanes) as ex:
            for chunk in ex.map(
                lambda vp: capture_viewport_steel(
                    vp, checkpoints, out_root, settle_ms),
                viewports,
            ):
                records.extend(chunk)
    else:
        shards = _shards(checkpoints, workers)
        print(f"capturing {len(checkpoints)} checkpoints x {len(viewports)} "
              f"viewports across {len(shards)} local browser(s) in parallel")
        with ThreadPoolExecutor(max_workers=len(shards)) as ex:
            for chunk in ex.map(
                lambda shard: capture_shard_local(
                    shard, viewports, out_root, settle_ms),
                shards,
            ):
                records.extend(chunk)

    index_path = out_root / "capture-index.json"
    if only and index_path.is_file():
        fresh = {(r.get("checkpoint"), r.get("viewport")) for r in records}
        previous = json.loads(index_path.read_text()).get("captures", [])
        records = [r for r in previous
                   if (r.get("checkpoint"), r.get("viewport")) not in fresh
                   ] + records
    index = {"schema_version": "tripit.capture-index.v1", "capture_id": capture_id,
             "captures": records}
    index_path.write_text(json.dumps(index, indent=2))
    print(f"\nwrote {len(records)} capture records -> "
          f"{out_root / 'capture-index.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-dir", default="materials/tripit")
    ap.add_argument("--only", default="", help="comma-separated checkpoint ids")
    ap.add_argument("--settle-ms", type=int, default=5000)
    ap.add_argument("--engine", choices=["steel", "local"], default="steel")
    ap.add_argument("--workers", type=int, default=3,
                    help="parallel lanes; steel caps at one session per "
                         "viewport, local launches one Chromium per lane")
    args = ap.parse_args()
    only = {s for s in args.only.split(",") if s} or None
    return capture(pathlib.Path(args.site_dir), only, args.settle_ms,
                   args.engine, max(1, args.workers))


if __name__ == "__main__":
    raise SystemExit(main())
