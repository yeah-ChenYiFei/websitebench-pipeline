#!/usr/bin/env python3
"""Asset closure capture for the tripit offline clone.

Loads every captured checkpoint URL locally (desktop + mobile) while recording
each network response, saves unique asset payloads under
source-assets/<capture_id>/<host>/<path>, crawls fetched CSS for url()
references that did not fire during render and fetches those too, then builds
source-assets/manifest.json (offline-clone.assets.v1) and mirrors every asset
into clone/static/assets/ as an independent physical copy.

Requires the local capture environment (fonts + shared libs):
    export LD_LIBRARY_PATH="$HOME/chromium-libs/usr/lib/x86_64-linux-gnu"
    export FONTCONFIG_FILE="$HOME/chromium-libs/etc/fonts/fonts.conf"
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from capture_source import CONSENT_COOKIES, UA  # noqa: E402

SITE = pathlib.Path(__file__).resolve().parents[1]
CAPTURE_ID = "2026-08-03.tripit-r1"
ASSET_ROOT = SITE / "source-assets" / CAPTURE_ID
RUNTIME_ROOT = SITE / "clone" / "static" / "assets" / CAPTURE_ID
MANIFEST = SITE / "source-assets" / "manifest.json"

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
EXCLUDE_HOST_FRAGMENTS = (
    "trustarc.com", "consent.trustarc", "google-analytics", "googletagmanager",
    "doubleclick", "facebook", "adobedtm", "demdex", "omtrdc", "hotjar",
    "qualtrics", "onetrust", "www.google.com", "googleadservices",
    "googlesyndication", "bat.bing", "ads.linkedin", "px.ads", "adsrvr",
    "analytics.", "pixel.", "x.com", "twitter.com", "tiktok", "snapchat",
)
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")

PAGES = [
    ("home", "https://www.tripit.com/"),
    ("free", "https://www.tripit.com/web/free"),
    ("pro", "https://www.tripit.com/web/pro"),
    ("how-it-works", "https://www.tripit.com/web/free/how-it-works"),
    ("pricing", "https://www.tripit.com/web/pro/pricing"),
    ("sap-concur", "https://www.tripit.com/web/pro/sap-concur"),
    ("download", "https://www.tripit.com/web/free/download"),
    ("security", "https://www.tripit.com/web/security"),
    ("blog-index", "https://www.tripit.com/web/blog"),
    ("traveler-resource-center", "https://www.tripit.com/web/traveler-resource-center"),
    ("login", "https://www.tripit.com/account/login"),
    ("create", "https://www.tripit.com/account/create"),
    ("forgot-password", "https://www.tripit.com/account/forgotPassword"),
    ("legal-user-agreement", "https://www.tripit.com/uhp/userAgreement"),
    ("legal-privacy", "https://www.tripit.com/uhp/privacyPolicy"),
    ("legal-do-not-share", "https://www.tripit.com/uhp/doNotShare"),
]


def excluded(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.casefold()
    return any(fragment in host for fragment in EXCLUDE_HOST_FRAGMENTS)


def classify(url: str, content_type: str) -> str | None:
    base = content_type.split(";")[0].strip().casefold()
    if base in ASSET_TYPES:
        return ASSET_TYPES[base]
    path = urllib.parse.urlsplit(url).path.casefold()
    for suffix, kind in ((".css", "css"), (".js", "js"), (".woff2", "font"),
                          (".woff", "font"), (".ttf", "font"), (".png", "image"),
                          (".jpg", "image"), (".jpeg", "image"), (".gif", "image"),
                          (".svg", "image"), (".webp", "image"), (".ico", "image")):
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
    # Filesystem safety: collapse any oversize segment to a sha-based name
    # while keeping the extension (some tracking-style URLs embed huge blobs).
    segments = []
    for segment in path.split("/"):
        if len(segment.encode()) > 140:
            stem, dot, suffix = segment.rpartition(".")
            digest = hashlib.sha256(segment.encode()).hexdigest()[:16]
            segment = f"h{digest}.{suffix}" if dot and len(suffix) <= 8 else f"h{digest}"
        segments.append(segment)
    return f"{parts.netloc}/{'/'.join(segments)}"


def main() -> int:
    collected: dict[str, dict] = {}

    def record(url: str, body: bytes, content_type: str, page_id: str, via: str) -> None:
        if excluded(url):
            return
        kind = classify(url, content_type)
        if kind is None or not body:
            return
        entry = collected.setdefault(url, {
            "url": url, "kind": kind, "content_type": content_type,
            "body": body, "referenced_by": set(),
        })
        entry["referenced_by"].add(f"capture:{page_id}:{via}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        crawl_ctx = None
        for vp_name, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
            ctx = browser.new_context(
                viewport={"width": width, "height": height}, locale="en-US",
                timezone_id="America/New_York", user_agent=UA)
            ctx.add_cookies(CONSENT_COOKIES)
            page = ctx.new_page()
            for page_id, url in PAGES:
                responses: list = []
                handler = (lambda resp: responses.append(resp))
                page.on("response", handler)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(4000)
                    page.mouse.wheel(0, 20000)
                    page.wait_for_timeout(1500)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {page_id}/{vp_name}: {str(exc)[:120]}",
                          file=sys.stderr, flush=True)
                page.remove_listener("response", handler)
                for resp in responses:
                    try:
                        if resp.status != 200:
                            continue
                        content_type = resp.headers.get("content-type", "")
                        # Classify BEFORE touching the body: response.body()
                        # blocks forever on still-streaming long-poll or
                        # media responses, and those are never assets.
                        if excluded(resp.url):
                            continue
                        if resp.url in collected:
                            collected[resp.url]["referenced_by"].add(
                                f"capture:{page_id}:{vp_name}")
                            continue
                        if classify(resp.url, content_type) is None:
                            continue
                        if resp.request.resource_type in {
                            "media", "websocket", "eventsource", "ping"
                        }:
                            continue
                        body = resp.body()
                        if len(body) > 8_000_000:
                            continue
                        record(resp.url, body, content_type, page_id, vp_name)
                    except Exception:  # noqa: BLE001 - detached bodies
                        continue
                print(f"  {page_id}/{vp_name}: cumulative assets "
                      f"{len(collected)}", flush=True)
            if vp_name == "mobile":
                crawl_ctx = ctx
            else:
                ctx.close()
        # Crawl CSS url() references missed during render (hover sprites,
        # secondary weights) once, via the last context.
        css_targets: set[str] = set()
        for entry in [e for e in collected.values() if e["kind"] == "css"]:
            text = entry["body"].decode("utf-8", errors="replace")
            for match in CSS_URL.finditer(text):
                ref = match.group(1).strip()
                if ref.startswith(("data:", "#")):
                    continue
                css_targets.add(urllib.parse.urljoin(entry["url"], ref))
        fetched = 0
        for target in sorted(css_targets):
            if target in collected or excluded(target):
                continue
            try:
                resp = crawl_ctx.request.get(target, timeout=10000)
                if resp.status == 200:
                    body = resp.body()
                    if len(body) <= 8_000_000:
                        record(target, body,
                               resp.headers.get("content-type", ""),
                               "css-crawl", "any")
                        fetched += 1
            except Exception:  # noqa: BLE001
                continue
        print(f"  css-crawl: +{fetched} (total {len(collected)})", flush=True)
        crawl_ctx.close()
        browser.close()

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
        first_party = urllib.parse.urlsplit(url).netloc.endswith("tripit.com")
        priority = "p0" if entry["kind"] in {"css", "font"} or first_party else "p1"
        assets.append({
            "id": f"{CAPTURE_ID}.{rel.replace('/', '.')}"[:180] + f".{sha[:10]}",
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
        })
    manifest = {
        "schema_version": "offline-clone.assets.v1",
        "snapshot_id": CAPTURE_ID,
        "created_at": "2026-08-04",
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
