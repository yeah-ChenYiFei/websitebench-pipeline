#!/usr/bin/env python3
"""Asset closure capture for the aspca-pet-insurance offline clone.

Renders every URL-addressable checkpoint (desktop + mobile) inside a
Browserbase cloud session while recording each network response, saves unique
asset payloads under source-assets/<capture_id>/<host>/<path>, then closes the
remainder — CSS url() references and resources.json entries (including the
funnel-walk states) that did not fire during the render pass — and builds
source-assets/manifest.json (offline-clone.assets.v1), mirroring every asset
into clone/static/assets/ as an independent physical copy.

All source traffic goes through the cloud browser: local egress to the source
is blocked by its WAF (403), so APIRequestContext (which egresses locally) is
never used here. Remainder fetches are layered:
  1. in-page fetch() from a page sitting on the source origin (same-origin
     and CORS-enabled CDN assets) returning base64;
  2. scratch-tab page.goto(asset_url) + response body over CDP.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import pathlib
import re
import shutil
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from capture_source import (  # noqa: E402
    INTERACTIVE_IDS, bb_connect_url, bb_create_session, bb_release,
    dismiss_consent,
)

SITE = pathlib.Path(__file__).resolve().parents[1]
CAPTURE_ID = "2026-08-13.aspca-pet-insurance-r1"
ASSET_ROOT = SITE / "source-assets" / CAPTURE_ID
RUNTIME_ROOT = SITE / "clone" / "static" / "assets" / CAPTURE_ID
MANIFEST = SITE / "source-assets" / "manifest.json"
SOURCE_CURRENT = SITE / "source-current" / CAPTURE_ID
FIRST_PARTY_HOSTS = ("aspcapetinsurance.com", "d3544la1u8djza.cloudfront.net")

ASSET_TYPES = {
    "text/css": "css",
    "application/javascript": "js",
    "text/javascript": "js",
    "application/x-javascript": "js",
    "font/woff2": "font",
    "font/woff": "font",
    "application/font-woff2": "font",
    "application/font-woff": "font",
    "font/ttf": "font",
    "image/png": "image",
    "image/jpeg": "image",
    "image/gif": "image",
    "image/svg+xml": "image",
    "image/webp": "image",
    "image/avif": "image",
    "image/x-icon": "image",
    "image/vnd.microsoft.icon": "image",
}
# Analytics, ads, A/B testing, consent management, live payment/captcha and
# review widgets: forbidden as clone runtime (see scope/purpose.json
# out_of_scope) and therefore never mirrored.
EXCLUDE_HOST_FRAGMENTS = (
    "google-analytics", "googletagmanager", "doubleclick", "facebook",
    "adobedtm", "demdex", "omtrdc", "hotjar", "qualtrics", "onetrust",
    "www.google.com", "www.gstatic.com", "googleadservices",
    "googlesyndication", "bat.bing", "ads.linkedin", "px.ads", "adsrvr",
    "analytics.", "pixel.", "x.com", "twitter.com", "tiktok", "snapchat",
    "kameleoon", "osano.com", "js.stripe.com", "m.stripe",
    "trustpilot", "clarity.ms", "quantummetric", "medallia", "invoca",
)
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")

FETCH_B64_JS = """async url => {
  try {
    const r = await fetch(url, {credentials: 'omit'});
    if (!r.ok) return {ok: false, status: r.status};
    const buf = await r.arrayBuffer();
    if (buf.byteLength > 8000000) return {ok: false, status: -2};
    const bytes = new Uint8Array(buf);
    let bin = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk)
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    return {ok: true, status: r.status,
            contentType: r.headers.get('content-type') || '',
            b64: btoa(bin)};
  } catch (e) {
    return {ok: false, status: -1, error: String(e).slice(0, 120)};
  }
}"""


def excluded(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.casefold()
    return any(fragment in host for fragment in EXCLUDE_HOST_FRAGMENTS)


def classify(url: str, content_type: str) -> str | None:
    base = content_type.split(";")[0].strip().casefold()
    if base in ASSET_TYPES:
        return ASSET_TYPES[base]
    path = urllib.parse.urlsplit(url).path.casefold()
    for suffix, kind in ((".css", "css"), (".js", "js"), (".woff2", "font"),
                         (".woff", "font"), (".ttf", "font"),
                         (".png", "image"), (".jpg", "image"),
                         (".jpeg", "image"), (".gif", "image"),
                         (".svg", "image"), (".webp", "image"),
                         (".ico", "image")):
        if path.endswith(suffix):
            return kind
    return None


def local_relpath(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = parts.path.lstrip("/") or "index"
    if path.endswith("/"):
        path += "index"
    if parts.query:
        digest = hashlib.sha256(parts.query.encode()).hexdigest()[:10]
        stem, dot, suffix = path.rpartition(".")
        path = f"{stem}.q{digest}.{suffix}" if dot else f"{path}.q{digest}"
    segments = []
    for segment in path.split("/"):
        if len(segment.encode()) > 140:
            stem, dot, suffix = segment.rpartition(".")
            digest = hashlib.sha256(segment.encode()).hexdigest()[:16]
            segment = (f"h{digest}.{suffix}" if dot and len(suffix) <= 8
                       else f"h{digest}")
        segments.append(segment)
    return f"{parts.netloc}/{'/'.join(segments)}"


def image_dimensions(body: bytes) -> dict | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(body)) as im:
            return {"width": im.width, "height": im.height}
    except Exception:  # noqa: BLE001 - SVG/ICO/PIL-absent
        return None


def load_plan_pages() -> list[tuple[str, str]]:
    plan = json.loads(
        (SITE / "scope" / "source-capture-plan.json").read_text())
    pages = []
    for cp in plan["checkpoints"]:
        if cp["id"] in INTERACTIVE_IDS:
            continue
        if not cp["url"].startswith("http"):
            continue
        pages.append((cp["id"], cp["url"]))
    return pages


def load_resource_targets() -> dict[str, set[str]]:
    """URL -> referenced_by tags, from every captured resources.json."""
    targets: dict[str, set[str]] = {}
    for res_file in sorted(SOURCE_CURRENT.glob("*/*/resources.json")):
        viewport = res_file.parent.name
        checkpoint = res_file.parent.parent.name
        for entry in json.loads(res_file.read_text()):
            url = entry.get("url", "")
            if not url.startswith("http") or excluded(url):
                continue
            if classify(url, "") is None:
                continue
            targets.setdefault(url, set()).add(
                f"capture:{checkpoint}:{viewport}")
    return targets


def main() -> int:
    collected: dict[str, dict] = {}

    def record(url: str, body: bytes, content_type: str,
               refs: set[str]) -> None:
        if excluded(url) or not body:
            return
        kind = classify(url, content_type)
        if kind is None:
            return
        entry = collected.setdefault(url, {
            "url": url, "kind": kind, "content_type": content_type,
            "body": body, "referenced_by": set(),
        })
        entry["referenced_by"].update(refs)

    pages_list = load_plan_pages()
    resource_targets = load_resource_targets()
    print(f"plan pages: {len(pages_list)}, "
          f"resources.json targets: {len(resource_targets)}", flush=True)

    sess = bb_create_session(1440, 900)
    print("browserbase session created (id withheld from logs)")
    ws_url = bb_connect_url(sess)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws_url)
            try:
                ctx = browser.contexts[0]
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                for vp_name, width, height in (("desktop", 1440, 900),
                                               ("mobile", 390, 844)):
                    page.set_viewport_size(
                        {"width": width, "height": height})
                    for page_id, url in pages_list:
                        responses: list = []

                        def handler(resp: object) -> None:
                            responses.append(resp)

                        page.on("response", handler)
                        try:
                            page.goto(url, wait_until="domcontentloaded",
                                      timeout=60000)
                            page.wait_for_timeout(4000)
                            dismiss_consent(page)
                            page.mouse.wheel(0, 20000)
                            page.wait_for_timeout(1500)
                        except Exception as exc:  # noqa: BLE001
                            print(f"  ! {page_id}/{vp_name}: "
                                  f"{str(exc)[:120]}",
                                  file=sys.stderr, flush=True)
                        page.remove_listener("response", handler)
                        for resp in responses:
                            try:
                                if resp.status != 200:
                                    continue
                                content_type = resp.headers.get(
                                    "content-type", "")
                                # Classify BEFORE touching the body:
                                # response.body() blocks on still-streaming
                                # responses, and those are never assets.
                                if excluded(resp.url):
                                    continue
                                if resp.url in collected:
                                    collected[resp.url][
                                        "referenced_by"].add(
                                        f"capture:{page_id}:{vp_name}")
                                    continue
                                if classify(resp.url, content_type) is None:
                                    continue
                                if resp.request.resource_type in {
                                    "media", "websocket", "eventsource",
                                    "ping",
                                }:
                                    continue
                                body = resp.body()
                                if len(body) > 8_000_000:
                                    continue
                                record(resp.url, body, content_type,
                                       {f"capture:{page_id}:{vp_name}"})
                            except Exception:  # noqa: BLE001
                                continue
                        print(f"  {page_id}/{vp_name}: cumulative assets "
                              f"{len(collected)}", flush=True)

                # Remainder: CSS url() references + resources.json targets
                # that never fired during the render pass.
                remainder: dict[str, set[str]] = {}
                for entry in [e for e in collected.values()
                              if e["kind"] == "css"]:
                    text = entry["body"].decode("utf-8", errors="replace")
                    for match in CSS_URL.finditer(text):
                        ref = match.group(1).strip()
                        if ref.startswith(("data:", "#")):
                            continue
                        target = urllib.parse.urljoin(entry["url"], ref)
                        if target not in collected and not excluded(target):
                            remainder.setdefault(target, set()).add(
                                "capture:css-crawl:any")
                for url, refs in resource_targets.items():
                    if url in collected:
                        collected[url]["referenced_by"].update(refs)
                    else:
                        remainder.setdefault(url, set()).update(refs)

                # Layer 1: in-page fetch from a source-origin page.
                page.goto("https://www.aspcapetinsurance.com/",
                          wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                unfetched: dict[str, set[str]] = {}
                got = 0
                for target in sorted(remainder):
                    try:
                        res = page.evaluate(FETCH_B64_JS, target)
                    except Exception:  # noqa: BLE001
                        res = {"ok": False, "status": -1}
                    if res.get("ok"):
                        record(target, base64.b64decode(res["b64"]),
                               res.get("contentType", ""),
                               remainder[target])
                        got += 1
                    else:
                        unfetched[target] = remainder[target]
                print(f"  in-page fetch: +{got}, "
                      f"remaining {len(unfetched)}", flush=True)

                # Layer 2: scratch-tab navigation for what fetch() could not
                # reach (cross-origin CDNs without CORS headers).
                got2 = 0
                still: list[str] = []
                scratch = ctx.new_page()
                for target in sorted(unfetched):
                    try:
                        resp = scratch.goto(target,
                                            wait_until="domcontentloaded",
                                            timeout=30000)
                        if resp is not None and resp.status == 200:
                            body = resp.body()
                            if body and len(body) <= 8_000_000:
                                record(target, body,
                                       resp.headers.get("content-type", ""),
                                       unfetched[target])
                                got2 += 1
                                continue
                        still.append(target)
                    except Exception:  # noqa: BLE001
                        still.append(target)
                scratch.close()
                print(f"  scratch-tab: +{got2}, unresolved {len(still)}",
                      flush=True)
                for target in still:
                    print(f"    unresolved: {target}", flush=True)
            finally:
                browser.close()
    finally:
        bb_release(sess["id"])

    if ASSET_ROOT.exists():
        shutil.rmtree(ASSET_ROOT)
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    assets = []
    for url in sorted(collected):
        entry = collected[url]
        rel = local_relpath(url)
        source_path = ASSET_ROOT / rel
        runtime_path = RUNTIME_ROOT / rel
        source_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(entry["body"])
        runtime_path.write_bytes(entry["body"])
        sha = hashlib.sha256(entry["body"]).hexdigest()
        host = urllib.parse.urlsplit(url).netloc.casefold()
        first_party = any(host.endswith(h) for h in FIRST_PARTY_HOSTS)
        priority = ("p0" if entry["kind"] in {"css", "font"} or first_party
                    else "p1")
        assets.append({
            "id": f"{CAPTURE_ID}.{rel.replace('/', '.')}"[:180]
                  + f".{sha[:10]}",
            "priority": priority,
            "required": True,
            "source_url": url,
            "source_path": str(source_path.relative_to(SITE)),
            "runtime_path": str(runtime_path.relative_to(SITE)),
            "bytes": len(entry["body"]),
            "sha256": sha,
            "mime_type": entry["content_type"].split(";")[0].strip()
                         or "application/octet-stream",
            "referenced_by": sorted(entry["referenced_by"]),
            "dimensions": (image_dimensions(entry["body"])
                           if entry["kind"] == "image" else None),
            "evidence_kind": "current-direct",
            "capture_id": CAPTURE_ID,
        })
    manifest = {
        "schema_version": "offline-clone.assets.v1",
        "snapshot_id": CAPTURE_ID,
        "created_at": "2026-08-13",
        "remote_runtime_policy": "forbidden",
        "closure_status": "complete",
        "assets": assets,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    kinds: dict[str, int] = {}
    for entry in collected.values():
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
    total = sum(len(e["body"]) for e in collected.values())
    print(f"assets: {len(assets)}  bytes: {total}  kinds: {kinds}")
    print(f"manifest -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
