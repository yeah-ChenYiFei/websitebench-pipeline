#!/usr/bin/env python3
"""Generate the fixture-frontend page documents from captured source HTML.

For every checkpoint route, takes the captured desktop page.html (the
responsive document is viewport-independent), rewrites each asset reference
that resolves to a mirrored asset onto its local /static/assets/... path,
and drops script/link references to hosts excluded from the closure
(consent manager, analytics, YouTube player runtime). Writes the result to
clone/frontend/pages/<checkpoint>.html plus a rewrite report.

The rewrite is purely mechanical (URL substitution + excluded-node removal);
the DOM structure, classes, inline styles, and copy are byte-preserved
otherwise, so the visual gate remains the arbiter of fidelity.
"""
from __future__ import annotations

import html as html_lib
import json
import pathlib
import re
import urllib.parse

SITE = pathlib.Path(__file__).resolve().parents[1]
CAPTURE_ID = "2026-08-03.tripit-r1"
CAP_ROOT = SITE / "source-current" / CAPTURE_ID
PAGES_OUT = SITE / "clone" / "frontend" / "pages"
STATIC_PREFIX = f"/static/assets/{CAPTURE_ID}"

EXCLUDED_HOST_RE = re.compile(
    r"(?i)(trustarc\.com|consent\.trustarc|google-analytics|googletagmanager|"
    r"googletagservices|doubleclick|facebook|adobedtm|demdex|omtrdc|hotjar|"
    r"qualtrics|onetrust|www\.google\.com|googleadservices|googlesyndication|"
    r"bat\.bing|ads\.linkedin|px\.ads|adsrvr|analytics\.|pixel\.|"
    r"crazyegg\.com|addtoany\.com|schemaapp\.com|munchkin\.marketo|tiqcdn|"
    r"www\.youtube\.com/(s|iframe_api)|youtube\.com/embed)"
)

CHECKPOINTS = [
    "home", "free", "pro", "how-it-works", "pricing", "sap-concur",
    "download", "security", "blog-index", "traveler-resource-center",
    "login", "create", "forgot-password", "legal-user-agreement",
    "legal-privacy", "legal-do-not-share",
]

# The two .ico favicons carry no dimensions the harness asset verifier can
# derive (ICO is outside inspect_asset's PIL suffix set), so they are served
# byte-exact from the out-of-closure clone/static/site tree rather than the
# manifest-verified assets tree. Their source refs (root-relative in every
# frozen document) are repointed here; the payloads themselves are placed by
# tools/fix_closure_blockers.py. Keys match the exact markup hrefs.
SITE_FILE_MAP = {
    "/themes/custom/tripit_theme/favicon.ico":
        "/static/site/favicon/theme-favicon.ico",
    "/favicon.ico?v=6a073a4": "/static/site/favicon/favicon.ico",
    "/favicon.ico": "/static/site/favicon/favicon.ico",
}


def load_url_map() -> dict[str, str]:
    manifest = json.loads((SITE / "source-assets" / "manifest.json").read_text())
    mapping: dict[str, str] = {}
    for asset in manifest["assets"]:
        url = asset.get("source_url")
        if not url:
            continue
        runtime_rel = asset["runtime_path"]
        local = "/" + runtime_rel.replace("clone/static/", "static/", 1)
        mapping[url] = local
        # Also map the schemeless and path-only variants used in markup.
        parts = urllib.parse.urlsplit(url)
        mapping[f"//{parts.netloc}{parts.path}" +
                (f"?{parts.query}" if parts.query else "")] = local
        if parts.netloc.endswith("tripit.com"):
            mapping[parts.path + (f"?{parts.query}" if parts.query else "")] = local
        # unpkg pins @latest to a concrete version at request time; the capture
        # followed that redirect, so alias the @latest spec the markup carries
        # to the resolved local payload.
        if "lottie-player@" in url:
            alias = re.sub(r"lottie-player@[^/]+/", "lottie-player@latest/", url)
            mapping[alias] = local
    # Favicons served out-of-closure take precedence over any manifest mapping.
    mapping.update(SITE_FILE_MAP)
    return mapping


URL_ATTR = re.compile(
    r"""(?is)\b(href|src|srcset|content|data-src|poster)\s*=\s*(["'])(.*?)\2"""
)
SCRIPT_BLOCK = re.compile(r"(?is)<script\b[^>]*>.*?</script>")
LINK_TAG = re.compile(r"(?is)<link\b[^>]*>")
IFRAME_TAG = re.compile(r"(?is)<iframe\b[^>]*>\s*</iframe>")
IMG_TAG = re.compile(r"(?is)<img\b[^>]*>")
# Inline SVG in an HTML document does not need any xmlns declaration — the HTML
# parser assigns the SVG namespace automatically, and decorative editor
# namespaces (xmlns:svgjs, xmlns:xlink) are inert — so these namespace URIs
# (never fetched) are dropped to keep shipped markup free of remote URLs.
NAMESPACE_DECL = re.compile(r'(?i)\s+xmlns(?::[a-z0-9]+)?="https?://[^"]*"')
# blockquote cite="" on social embeds is invisible provenance metadata, never
# fetched; strip the attribute rather than ship a remote URL in markup.
REMOTE_CITE = re.compile(r'(?i)\s+cite="(?:https?:)?//[^"]*"')


def rewrite_document(html: str, url_map: dict[str, str], report: dict) -> str:
    def map_url(url: str) -> str | None:
        url = url.strip()
        # Markup attribute values carry HTML-entity-encoded query separators
        # (?scope=header&amp;delta=0&amp;...), whereas the url_map keys are built
        # from urlsplit() of the manifest source_url and therefore hold raw '&'.
        # Decode entities so aggregated CSS/JS bundles (the only mirrored assets
        # that carry query strings) resolve to their vendored .q<hash> payloads.
        unescaped = html_lib.unescape(url)
        candidates = [url]
        if unescaped != url:
            candidates.append(unescaped)
        for base in (url, unescaped):
            if base.startswith("https://"):
                candidates.append(base.removeprefix("https:"))
        for candidate in candidates:
            if candidate in url_map:
                return url_map[candidate]
        for candidate in (url, unescaped):
            defragged = urllib.parse.urldefrag(candidate)[0]
            if defragged in url_map:
                return url_map[defragged]
        return None

    def drop_or_keep_tag(match: re.Match, kind: str) -> str:
        tag = match.group(0)
        url_match = re.search(r"""(?is)(?:src|href)\s*=\s*["']([^"']+)["']""", tag)
        if not url_match:
            return tag
        url = url_match.group(1)
        if EXCLUDED_HOST_RE.search(url):
            report["dropped_tags"].append(f"{kind}:{url[:100]}")
            return ""
        return tag

    def drop_or_keep_script(match: re.Match) -> str:
        block = match.group(0)
        open_tag = block[: block.find(">") + 1]
        # Structured-data blocks are invisible SEO metadata whose schema.org /
        # partner IRIs are semantic identifiers, never fetched; drop wholesale.
        if re.search(r'(?i)type\s*=\s*["\']application/ld\+json["\']', open_tag):
            report["dropped_tags"].append("script:ld+json")
            return ""
        # External loader tags and inline analytics bootstraps (crazyegg,
        # addtoany, bing UET, schemaapp) reference excluded hosts anywhere in
        # the element — src attribute or inline body — so match the whole block.
        if EXCLUDED_HOST_RE.search(block):
            report["dropped_tags"].append("script:excluded-host")
            return ""
        return block

    html = SCRIPT_BLOCK.sub(drop_or_keep_script, html)
    html = LINK_TAG.sub(lambda m: drop_or_keep_tag(m, "link"), html)
    html = IFRAME_TAG.sub(lambda m: drop_or_keep_tag(m, "iframe"), html)
    html = IMG_TAG.sub(lambda m: drop_or_keep_tag(m, "img"), html)

    # Inline-SVG namespace declarations are never network requests but would
    # trip the textual remote-URL audit; the HTML parser supplies them.
    html = NAMESPACE_DECL.sub("", html)
    html = REMOTE_CITE.sub("", html)

    def replace_attr(match: re.Match) -> str:
        attr, quote, value = match.group(1), match.group(2), match.group(3)
        if attr.casefold() == "srcset":
            parts = []
            changed = False
            for chunk in value.split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                pieces = chunk.split()
                mapped = map_url(pieces[0])
                if mapped:
                    pieces[0] = mapped
                    changed = True
                parts.append(" ".join(pieces))
            if changed:
                report["rewritten"] += 1
                return f'{attr}={quote}{", ".join(parts)}{quote}'
            return match.group(0)
        mapped = map_url(value)
        if mapped:
            report["rewritten"] += 1
            return f"{attr}={quote}{mapped}{quote}"
        return match.group(0)

    html = URL_ATTR.sub(replace_attr, html)

    # CSS url(...) references inside inline <style> blocks and style attrs.
    def replace_css_url(match: re.Match) -> str:
        target = match.group(1).strip("'\"")
        mapped = map_url(target)
        if mapped:
            report["rewritten"] += 1
            return f"url({mapped})"
        return match.group(0)

    html = re.sub(r"url\(\s*([^)]+?)\s*\)", replace_css_url, html)

    # RDFa namespace URIs on <html prefix=...> are metadata, not requests;
    # the runtime.local-only audit forbids any remote URL in markup.
    html = re.sub(r'(?is)\sprefix="[^"]*"', "", html, count=1)

    # First-party absolute URLs (canonical, og:url, form actions, nav links,
    # inline-script endpoints) become local paths on the clone origin.
    def strip_origin(match: re.Match) -> str:
        report["first_party_localized"] += 1
        rest = match.group(1)
        return "/" + rest.lstrip("/")

    html = re.sub(r"https?://(?:www\.)?tripit\.com/?([^\"'\s<>)]*)",
                  strip_origin, html)

    # Remaining third-party navigation targets keep their visible affordance
    # but point at the local external-boundary route.
    def boundary(match: re.Match) -> str:
        url = match.group(3)
        parts = urllib.parse.urlsplit(url)
        slug = re.sub(r"[^a-z0-9.-]+", "-", parts.netloc.casefold()) or "external"
        report["external_boundaries"].append(url[:90])
        return (f"{match.group(1)}={match.group(2)}"
                f"/external/{slug}{match.group(2)}")

    html = re.sub(
        r"""(?is)\b(href)\s*=\s*(["'])(https?://[^"']+|//[^"']+)\2""",
        boundary, html)
    return html


def main() -> int:
    url_map = load_url_map()
    PAGES_OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for checkpoint in CHECKPOINTS:
        source = CAP_ROOT / checkpoint / "desktop" / "page.html"
        html = source.read_text()
        report = {"rewritten": 0, "dropped_tags": [],
                  "first_party_localized": 0, "external_boundaries": []}
        rewritten = rewrite_document(html, url_map, report)
        # Mirror the assets-gate audit exactly, including protocol-relative
        # //host references, so this self-check cannot pass while the gate fails.
        remaining = sorted(set(re.findall(
            r"(?ix)(?:https?:)?//(?!localhost|127\.0\.0\.1)"
            r"[a-z0-9.-]+\.[a-z]{2,}[^\"'\s<>)]*",
            rewritten)))
        (PAGES_OUT / f"{checkpoint}.html").write_text(rewritten)
        summary[checkpoint] = {
            "rewritten_refs": report["rewritten"],
            "dropped_tags": report["dropped_tags"],
            "first_party_localized": report["first_party_localized"],
            "external_boundaries": sorted(set(report["external_boundaries"])),
            "remaining_remote_refs": remaining[:40],
            "remaining_remote_count": len(remaining),
        }
        print(f"  {checkpoint}: rewrote {report['rewritten']}, localized "
              f"{report['first_party_localized']}, dropped "
              f"{len(report['dropped_tags'])}, remote-left {len(remaining)}")
    (SITE / "clone" / "frontend" / "rewrite-report.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
