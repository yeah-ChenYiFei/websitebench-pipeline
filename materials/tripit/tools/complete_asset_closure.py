#!/usr/bin/env python3
"""Complete the tripit asset closure from the FROZEN source HTML.

The render-based capture (capture_assets.py) records whatever fired during a
headless re-render, which misses first-party assets that only the frozen
captured documents reference (auth-page chrome, the create-form widget JS,
below-the-fold Lottie payloads, blog slideshow imagery). This tool is the
authoritative completion pass: it parses every frozen desktop+mobile
page.html, resolves each first-party asset reference to the exact URL the
markup carries (query string included), fetches only those that are not yet
declared, crawls fetched CSS for transitive url()/@import dependencies, and
merges the new payloads into source-assets/manifest.json using the harness
inspect_asset() as the single source of truth for bytes/sha/mime/dimensions.

Tracking / analytics hosts are never fetched — they are dropped from the
shipped markup by build_frontend_pages.py instead.

GET-only, idempotent: re-running fetches nothing once the closure is complete.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from websitebench.offline_clone.assets import inspect_asset  # noqa: E402

SITE = pathlib.Path(__file__).resolve().parents[1]
CAPTURE_ID = "2026-08-03.tripit-r1"
CAP_ROOT = SITE / "source-current" / CAPTURE_ID
ASSET_ROOT = SITE / "source-assets" / CAPTURE_ID
RUNTIME_ROOT = SITE / "clone" / "static" / "assets" / CAPTURE_ID
MANIFEST = SITE / "source-assets" / "manifest.json"

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

PAGE_URLS = {
    "home": "https://www.tripit.com/",
    "free": "https://www.tripit.com/web/free",
    "pro": "https://www.tripit.com/web/pro",
    "how-it-works": "https://www.tripit.com/web/free/how-it-works",
    "pricing": "https://www.tripit.com/web/pro/pricing",
    "sap-concur": "https://www.tripit.com/web/pro/sap-concur",
    "download": "https://www.tripit.com/web/free/download",
    "security": "https://www.tripit.com/web/security",
    "blog-index": "https://www.tripit.com/web/blog",
    "traveler-resource-center": "https://www.tripit.com/web/traveler-resource-center",
    "login": "https://www.tripit.com/account/login",
    "create": "https://www.tripit.com/account/create",
    "forgot-password": "https://www.tripit.com/account/forgotPassword",
    "legal-user-agreement": "https://www.tripit.com/uhp/userAgreement",
    "legal-privacy": "https://www.tripit.com/uhp/privacyPolicy",
    "legal-do-not-share": "https://www.tripit.com/uhp/doNotShare",
}

# Analytics / consent / advertising hosts are excluded from the closure and
# dropped from shipped markup; never fetch them here either.
TRACKING = re.compile(
    r"(?i)(trustarc|google-analytics|googletagmanager|googletagservices|"
    r"doubleclick|facebook|adobedtm|demdex|omtrdc|hotjar|qualtrics|onetrust|"
    r"googleadservices|googlesyndication|bat\.bing|ads\.linkedin|px\.ads|"
    r"adsrvr|crazyegg|addtoany|schemaapp|munchkin\.marketo|tiqcdn|marketo|"
    r"snapchat|tiktok|/x\.com|//x\.com|twitter\.com|youtube|pixel\.|analytics\.)"
)
ASSET_EXT = re.compile(
    r"\.(css|js|mjs|woff2?|ttf|otf|eot|png|jpe?g|gif|svg|webp|avif|ico|json)(\?|$)",
    re.I)
ATTR = re.compile(r"""(?is)\b(?:src|href|data-src|poster)\s*=\s*["']([^"']+)["']""")
SRCSET = re.compile(r"""(?is)\bsrcset\s*=\s*["']([^"']+)["']""")
CSS_URL = re.compile(r"""url\(\s*['\"]?([^'\")]+)['\"]?\s*\)""")
CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?['\"]([^'\"]+)['\"]""")


def is_first_party(url: str) -> bool:
    return urllib.parse.urlsplit(url).netloc.casefold().endswith("tripit.com")


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
            segment = f"h{digest}.{suffix}" if dot and len(suffix) <= 8 else f"h{digest}"
        segments.append(segment)
    return f"{parts.netloc}/{'/'.join(segments)}"


def collect_refs(html: str) -> set[str]:
    refs: set[str] = set()
    for m in ATTR.finditer(html):
        refs.add(m.group(1).strip())
    for m in SRCSET.finditer(html):
        for chunk in m.group(1).split(","):
            piece = chunk.strip().split()
            if piece:
                refs.add(piece[0].strip())
    for m in CSS_URL.finditer(html):
        ref = m.group(1).strip()
        if not ref.startswith(("data:", "#")):
            refs.add(ref)
    return refs


def fetch(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                print(f"  ! {resp.status} {url}", file=sys.stderr)
                return None
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! ERR {str(exc)[:60]} {url}", file=sys.stderr)
        return None


def store(url: str, body: bytes) -> tuple[pathlib.Path, pathlib.Path]:
    rel = local_relpath(url)
    src = ASSET_ROOT / rel
    run = RUNTIME_ROOT / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    run.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(body)
    run.write_bytes(body)
    return src, run


def make_entry(url: str, src: pathlib.Path, run: pathlib.Path,
               referenced_by: list[str]) -> dict:
    info = inspect_asset(run)
    rel = local_relpath(url)
    mime = info.get("mime_type") or MIME_FALLBACK(url)
    entry = {
        # The manifest id must be lowercase (schema pattern ^[a-z0-9._-]+$);
        # source_url/paths stay case-exact so they keep matching the markup.
        "id": (f"{CAPTURE_ID}.{rel.replace('/', '.')}"[:180]
               + f".{info['sha256'][:10]}").lower(),
        "priority": "p0" if is_first_party(url) else "p1",
        "required": True,
        "source_url": url,
        "source_path": str(src.relative_to(SITE)),
        "runtime_path": str(run.relative_to(SITE)),
        "bytes": info["bytes"],
        "sha256": info["sha256"],
        "mime_type": mime,
        "referenced_by": sorted(set(referenced_by)),
        "dimensions": info.get("dimensions"),
        "evidence_kind": "current-direct",
        "capture_id": CAPTURE_ID,
    }
    return entry


def MIME_FALLBACK(url: str) -> str:
    ext = pathlib.PurePosixPath(urllib.parse.urlsplit(url).path).suffix.casefold()
    return {
        ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
        ".json": "application/json", ".woff2": "font/woff2", ".woff": "font/woff",
        ".ttf": "font/ttf", ".otf": "font/otf", ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
        ".svg": "image/svg+xml", ".webp": "image/webp", ".avif": "image/avif",
        ".ico": "image/x-icon",
    }.get(ext, "application/octet-stream")


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    existing_urls = {a["source_url"] for a in manifest["assets"]}
    existing_paths = {
        urllib.parse.urlsplit(a["source_url"]).path
        for a in manifest["assets"] if is_first_party(a["source_url"])
    }

    # 1. Gather first-party asset refs from every frozen document, absolutized,
    #    tracking which (page, viewport) referenced each.
    wanted: dict[str, set[str]] = {}
    for page, base in PAGE_URLS.items():
        for vp in ("desktop", "mobile"):
            doc = CAP_ROOT / page / vp / "page.html"
            if not doc.exists():
                continue
            for ref in collect_refs(doc.read_text()):
                if ref.startswith(("data:", "mailto:", "tel:", "javascript:",
                                   "#", "blob:")):
                    continue
                if TRACKING.search(ref):
                    continue
                absu = urllib.parse.urljoin(base, ref)
                parts = urllib.parse.urlsplit(absu)
                if not parts.netloc.casefold().endswith("tripit.com"):
                    continue
                if not ASSET_EXT.search(parts.path):
                    continue
                clean = urllib.parse.urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, parts.query, ""))
                if clean in existing_urls or parts.path in existing_paths:
                    continue
                wanted.setdefault(clean, set()).add(f"capture:{page}:{vp}")

    print(f"missing first-party refs to fetch: {len(wanted)}")
    new_entries: list[dict] = []
    fetched_css: list[tuple[str, bytes]] = []
    for url in sorted(wanted):
        body = fetch(url)
        if body is None:
            continue
        src, run = store(url, body)
        entry = make_entry(url, src, run, sorted(wanted[url]))
        new_entries.append(entry)
        existing_urls.add(url)
        print(f"  + {entry['bytes']:>8}  {url.replace('https://www.tripit.com','')[:70]}")
        if url.lower().split("?")[0].endswith(".css"):
            fetched_css.append((url, body))

    # 2. Transitive CSS dependency crawl (jquery-ui theme images, @import chains).
    seen_css = {u for u, _ in fetched_css}
    while fetched_css:
        css_url, css_body = fetched_css.pop()
        text = css_body.decode("utf-8", errors="replace")
        deps: set[str] = set()
        for m in CSS_URL.finditer(text):
            r = m.group(1).strip()
            if not r.startswith(("data:", "#")):
                deps.add(r)
        for m in CSS_IMPORT.finditer(text):
            deps.add(m.group(1).strip())
        for ref in deps:
            absu = urllib.parse.urljoin(css_url, ref)
            parts = urllib.parse.urlsplit(absu)
            if not parts.netloc.casefold().endswith("tripit.com"):
                continue
            if not ASSET_EXT.search(parts.path):
                continue
            if TRACKING.search(absu):
                continue
            clean = urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path, parts.query, ""))
            if clean in existing_urls or parts.path in existing_paths:
                continue
            body = fetch(clean)
            if body is None:
                continue
            src, run = store(clean, body)
            entry = make_entry(clean, src, run, ["capture:css-crawl:any"])
            new_entries.append(entry)
            existing_urls.add(clean)
            print(f"  +css {entry['bytes']:>8}  {clean.replace('https://www.tripit.com','')[:66]}")
            if clean.lower().split("?")[0].endswith(".css") and clean not in seen_css:
                seen_css.add(clean)
                fetched_css.append((clean, body))

    if not new_entries:
        print("closure already complete; nothing added.")
        return 0

    manifest["assets"].extend(new_entries)
    manifest["assets"].sort(key=lambda a: a["source_url"])
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nadded {len(new_entries)} assets -> manifest now "
          f"{len(manifest['assets'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
