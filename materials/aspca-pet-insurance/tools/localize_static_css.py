#!/usr/bin/env python3
"""Localize remote url()/@import references inside mirrored CSS files.

build_clone_pages.py rewrites the frozen HTML documents, but the mirrored
stylesheets under clone/static/assets/ were vendored byte-for-byte from the
capture, so their internal url() references (typekit @font-face payloads,
the p.typekit.net beacon @import, content-CDN background images such as the
homepage hero) still point at remote origins. Offline those requests are
blocked, which drops the brand webfont and the hero photo — the direct cause
of the home visual-contract deviations.

This pass applies the same mapping policy as build_clone_pages.py to every
*.css file under clone/static/assets/:

  1. references found in source-assets/manifest.json map to their vendored
     /static/assets/... payload (query-carrying typekit URLs included);
  2. any remaining remote reference is localized onto the deterministic
     mirror path /static/assets/<capture-id>/<host><path> — if the payload
     was captured it loads, otherwise it 404s locally instead of ever
     leaving the clone origin (visible content preserved where evidence
     exists, offline-clean otherwise);
  3. relative references are left untouched — the mirror preserves the
     source directory structure, so they already resolve locally.

Purely mechanical, idempotent, and report-writing:
clone/frontend/css-localize-report.json records every rewrite and every
localized reference whose payload is absent from disk.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import urllib.parse

TOOLS = pathlib.Path(__file__).resolve().parent
SITE = TOOLS.parent

_spec = importlib.util.spec_from_file_location(
    "build_clone_pages", TOOLS / "build_clone_pages.py")
_bcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bcp)

STATIC_PREFIX = _bcp.STATIC_PREFIX
CSS_ROOT = SITE / "clone" / "static" / "assets"
REPORT_PATH = SITE / "clone" / "frontend" / "css-localize-report.json"

CSS_URL = re.compile(r"(?is)url\(\s*(['\"]?)([^)'\"]+)\1\s*\)")
CSS_IMPORT = re.compile(r"(?is)@import\s+(['\"])([^'\"]+)\1")
REMOTE_VALUE = re.compile(r"(?i)^(?:https?:)?//")


def _mirror_path(url: str) -> str:
    parts = urllib.parse.urlsplit(url, scheme="https")
    return f"{STATIC_PREFIX}/{parts.netloc}{parts.path}"


def localize(text: str, url_map: dict[str, str], report: dict) -> str:
    def map_remote(raw: str) -> str | None:
        url = raw.strip()
        if not REMOTE_VALUE.match(url):
            return None  # relative / data: / fragment — already local
        candidates = [url]
        if url.startswith("https://"):
            candidates.append(url.removeprefix("https:"))
        elif url.startswith("//"):
            candidates.append("https:" + url)
        for candidate in candidates:
            if candidate in url_map:
                report["mapped"] += 1
                return url_map[candidate]
        for candidate in candidates:
            defragged = urllib.parse.urldefrag(candidate)[0]
            if defragged in url_map:
                report["mapped"] += 1
                return url_map[defragged]
        local = _mirror_path(url if not url.startswith("//") else
                             "https:" + url)
        report["deterministic"] += 1
        if not (SITE / "clone" / local.lstrip("/")).exists():
            report["missing_payloads"].append(
                {"reference": url[:140], "local": local[:140]})
        return local

    def sub_url(match: re.Match) -> str:
        mapped = map_remote(match.group(2))
        if mapped is None:
            return match.group(0)
        return f"url({mapped})"

    def sub_import(match: re.Match) -> str:
        mapped = map_remote(match.group(2))
        if mapped is None:
            return match.group(0)
        return f'@import "{mapped}"'

    text = CSS_URL.sub(sub_url, text)
    text = CSS_IMPORT.sub(sub_import, text)
    return text


def main() -> int:
    url_map = _bcp.load_url_map()
    summary: dict[str, dict] = {}
    for path in sorted(CSS_ROOT.rglob("*.css")):
        text = path.read_text(encoding="utf-8", errors="replace")
        report = {"mapped": 0, "deterministic": 0, "missing_payloads": []}
        rewritten = localize(text, url_map, report)
        if rewritten != text:
            path.write_text(rewritten, encoding="utf-8")
        remaining = len(re.findall(
            r"(?ix)url\(\s*['\"]?(?:https?:)?//", rewritten))
        if report["mapped"] or report["deterministic"] or remaining:
            summary[str(path.relative_to(SITE / "clone"))] = {
                **report, "remaining_remote_urls": remaining,
            }
        print(f"  {path.name}: mapped {report['mapped']}, deterministic "
              f"{report['deterministic']}, missing "
              f"{len(report['missing_payloads'])}, remote-left {remaining}")
    totals = {
        "files_rewritten": len(summary),
        "mapped": sum(v["mapped"] for v in summary.values()),
        "deterministic": sum(v["deterministic"] for v in summary.values()),
        "missing_payloads": sum(
            len(v["missing_payloads"]) for v in summary.values()),
        "remaining_remote_total": sum(
            v["remaining_remote_urls"] for v in summary.values()),
    }
    REPORT_PATH.write_text(json.dumps(
        {"_totals": totals, **summary}, indent=2) + "\n")
    print(f"totals: {totals}")
    return 0 if totals["remaining_remote_total"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
