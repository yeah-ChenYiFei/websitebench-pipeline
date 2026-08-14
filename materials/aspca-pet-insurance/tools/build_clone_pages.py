#!/usr/bin/env python3
"""Generate the frozen marketing-page documents from captured source HTML.

For every checkpoint route, takes the captured desktop page.html (the
responsive document is viewport-independent), rewrites each asset reference
that resolves to a mirrored asset onto its local /static/assets/... path,
and localizes or drops every remaining remote reference so the shipped
document carries zero remote URLs. Writes the result to
clone/frontend/pages/<checkpoint>.html plus a rewrite report.

Site-specific policy (see scope/implement-notes.md): the marketing pages
ship as post-render frozen DOM, so ALL <script> blocks are dropped (counts
recorded per page) — third-party trackers are excluded from the runtime and
first-party widget JS is not re-executed, keeping the frozen visual state
deterministic. Unmapped references on the site's own content-CDN hosts are
localized onto the deterministic mirror path (host + path under
/static/assets/<capture-id>/) and reported if the payload is missing on
disk; unmapped third-party link/img/iframe tags (tracking pixels, widget
frames) are dropped; remaining third-party navigation hrefs become
/external/<slug> boundary links.

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
CAPTURE_ID = "2026-08-13.aspca-pet-insurance-r1"
CAP_ROOT = SITE / "source-current" / CAPTURE_ID
PAGES_OUT = SITE / "clone" / "frontend" / "pages"
STATIC_PREFIX = f"/static/assets/{CAPTURE_ID}"

CHECKPOINTS = [
    "home", "about-us", "cat-insurance", "dog-insurance",
    "pet-insurance-plan", "research-and-compare", "support", "why-us",
    "not-found",
]

# Every *.aspcapetinsurance.com host is first-party: absolute URLs on these
# hosts become local paths on the clone origin (nav links, canonical, og:url,
# and the hidden first-party tag-container iframe alike).
FIRST_PARTY_HOST_RE = re.compile(r"(?i)^(?:[a-z0-9-]+\.)*aspcapetinsurance\.com$")

# The site's own content CDNs. References on these hosts are visible page
# content (images, css, fonts); when a specific URL is absent from the asset
# manifest (lazy-loaded below the fold or a responsive variant the capture
# viewport never fetched), the reference is still localized onto the
# deterministic mirror path rather than dropped, and the missing payload is
# reported — dropping would delete visible DOM structure.
CONTENT_CDN_HOSTS = {
    "d3544la1u8djza.cloudfront.net",
    "d2hrivdxn8ekm8.cloudfront.net",
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
        # Also map the schemeless and (first-party) path-only variants used
        # in markup.
        parts = urllib.parse.urlsplit(url)
        mapping[f"//{parts.netloc}{parts.path}" +
                (f"?{parts.query}" if parts.query else "")] = local
        if FIRST_PARTY_HOST_RE.match(parts.netloc):
            mapping[parts.path + (f"?{parts.query}" if parts.query else "")] = local
    return mapping


URL_ATTR = re.compile(
    r"""(?is)\b(href|src|srcset|content|data-src|poster)\s*=\s*(["'])(.*?)\2"""
)
SCRIPT_BLOCK = re.compile(r"(?is)<script\b[^>]*>.*?</script>")
LINK_TAG = re.compile(r"(?is)<link\b[^>]*>")
IFRAME_TAG = re.compile(r"(?is)<iframe\b[^>]*>\s*</iframe>")
IMG_TAG = re.compile(r"(?is)<img\b[^>]*>")
REMOTE_URL_VALUE = re.compile(r"(?i)^(?:https?:)?//")
# Inline SVG in an HTML document does not need any xmlns declaration — the HTML
# parser assigns the SVG namespace automatically, and decorative editor
# namespaces (xmlns:svgjs, xmlns:xlink) are inert — so these namespace URIs
# (never fetched) are dropped to keep shipped markup free of remote URLs.
NAMESPACE_DECL = re.compile(r'(?i)\s+xmlns(?::[a-z0-9]+)?="https?://[^"]*"')
# blockquote cite="" on social embeds is invisible provenance metadata, never
# fetched; strip the attribute rather than ship a remote URL in markup.
REMOTE_CITE = re.compile(r'(?i)\s+cite="(?:https?:)?//[^"]*"')
# Microdata breadcrumb annotations (itemtype/vocab) carry schema.org IRIs that
# are semantic identifiers, never fetched — invisible metadata, same policy as
# xmlns/prefix above. itemprop/itemscope carry no URL and are preserved.
MICRODATA_IRI = re.compile(
    r'(?i)\s+(?:itemtype|vocab)="https?://(?:www\.)?schema\.org[^"]*"')


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(
        html_lib.unescape(url.strip()), scheme="https").netloc.casefold()


def rewrite_document(html: str, url_map: dict[str, str], report: dict) -> str:
    def map_url(url: str) -> str | None:
        url = url.strip()
        # Markup attribute values carry HTML-entity-encoded query separators,
        # whereas the url_map keys are built from the manifest source_url and
        # therefore hold raw '&'. Decode entities so query-carrying assets
        # resolve to their vendored payloads.
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

    def cdn_fallback(url: str) -> str | None:
        # Deterministic mirror path for content-CDN references absent from
        # the manifest (never-fetched lazy/responsive variants).
        parts = urllib.parse.urlsplit(html_lib.unescape(url.strip()),
                                      scheme="https")
        if parts.netloc.casefold() not in CONTENT_CDN_HOSTS:
            return None
        local = f"{STATIC_PREFIX}/{parts.netloc}{parts.path}"
        report["cdn_fallback_refs"].append(
            html_lib.unescape(url.strip())[:120])
        return local

    def map_or_fallback(url: str) -> str | None:
        return map_url(url) or cdn_fallback(url)

    def drop_or_keep_tag(match: re.Match, kind: str) -> str:
        tag = match.group(0)
        # Pure network hints never carry content; drop them for any remote
        # target so no preconnect/dns-prefetch host survives into markup.
        if kind == "link" and re.search(
                r'(?i)\brel\s*=\s*["\'](?:preconnect|dns-prefetch)["\']', tag):
            if re.search(r"""(?is)\bhref\s*=\s*["'](?:https?:)?//""", tag):
                report["dropped_tags"].append("link:network-hint")
                return ""
            return tag
        url_match = re.search(r"""(?is)(?:src|href)\s*=\s*["']([^"']+)["']""", tag)
        if not url_match:
            return tag
        url = url_match.group(1)
        if not REMOTE_URL_VALUE.match(url.strip()):
            return tag
        host = host_of(url)
        if (map_url(url) is not None or FIRST_PARTY_HOST_RE.match(host)
                or host in CONTENT_CDN_HOSTS):
            return tag
        # Unmapped third-party reference: tracking pixel, ad-tech noscript
        # frame or uncaptured widget frame — excluded from the frozen runtime.
        report["dropped_tags"].append(f"{kind}:{url[:100]}")
        return ""

    def drop_script(match: re.Match) -> str:
        # Post-render frozen DOM: every script block is dropped (trackers
        # excluded, first-party widget JS not re-executed). ld+json
        # structured-data blocks are counted separately: invisible SEO
        # metadata whose schema.org IRIs are never fetched.
        open_tag = match.group(0)[: match.group(0).find(">") + 1]
        if re.search(r'(?i)type\s*=\s*["\']application/ld\+json["\']', open_tag):
            report["ld_json_dropped"] += 1
        report["script_blocks_dropped"] += 1
        return ""

    html = SCRIPT_BLOCK.sub(drop_script, html)
    html = LINK_TAG.sub(lambda m: drop_or_keep_tag(m, "link"), html)
    html = IFRAME_TAG.sub(lambda m: drop_or_keep_tag(m, "iframe"), html)
    html = IMG_TAG.sub(lambda m: drop_or_keep_tag(m, "img"), html)

    # Invisible remote-IRI metadata: never network requests, but they would
    # trip the textual remote-URL audit.
    html = NAMESPACE_DECL.sub("", html)
    html = REMOTE_CITE.sub("", html)
    html = MICRODATA_IRI.sub("", html)
    # RDFa namespace URIs on <html prefix=...> are metadata, not requests.
    html = re.sub(r'(?is)\sprefix="[^"]*"', "", html, count=1)

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
                mapped = map_or_fallback(pieces[0])
                if mapped:
                    pieces[0] = mapped
                    changed = True
                parts.append(" ".join(pieces))
            if changed:
                report["rewritten"] += 1
                return f'{attr}={quote}{", ".join(parts)}{quote}'
            return match.group(0)
        mapped = map_or_fallback(value)
        if mapped:
            report["rewritten"] += 1
            return f"{attr}={quote}{mapped}{quote}"
        return match.group(0)

    html = URL_ATTR.sub(replace_attr, html)

    # CSS url(...) references inside inline <style> blocks and style attrs.
    def replace_css_url(match: re.Match) -> str:
        target = match.group(1).strip("'\"")
        mapped = map_or_fallback(target)
        if mapped:
            report["rewritten"] += 1
            return f"url({mapped})"
        return match.group(0)

    html = re.sub(r"url\(\s*([^)]+?)\s*\)", replace_css_url, html)

    # First-party absolute URLs (canonical, og:url, nav links, the hidden
    # first-party tag-container iframe) become local paths on the clone
    # origin. Schemeless //host/... variants are localized the same way.
    def strip_origin(match: re.Match) -> str:
        report["first_party_localized"] += 1
        rest = match.group(1)
        return "/" + rest.lstrip("/")

    html = re.sub(
        r"(?i)https?://(?:[a-z0-9-]+\.)*aspcapetinsurance\.com/?"
        r"([^\"'\s<>)]*)",
        strip_origin, html)
    html = re.sub(
        r"(?i)(?<![:\w/])//(?:[a-z0-9-]+\.)*aspcapetinsurance\.com/?"
        r"([^\"'\s<>)]*)",
        strip_origin, html)

    # Remaining third-party navigation targets keep their visible affordance
    # but point at the local external-boundary route.
    def boundary(match: re.Match) -> str:
        url = match.group(3)
        parts = urllib.parse.urlsplit(html_lib.unescape(url), scheme="https")
        slug = re.sub(r"[^a-z0-9.-]+", "-", parts.netloc.casefold()) or "external"
        report["external_boundaries"].append(url[:90])
        return (f"{match.group(1)}={match.group(2)}"
                f"/external/{slug}{match.group(2)}")

    html = re.sub(
        r"""(?is)\b(href)\s*=\s*(["'])(https?://[^"']+|//[^"']+)\2""",
        boundary, html)
    return html


def static_refs(html: str) -> set[str]:
    """Every /static/... path a generated document references."""
    refs = set(re.findall(r"/static/[^\s\"'<>),]+", html))
    return {urllib.parse.urldefrag(r.split("?", 1)[0])[0] for r in refs}


# --- Per-viewport captured-state reconciliation (Osano consent manager) ---
# The shipped document is built from the desktop capture, but the Osano
# consent dialog/widget state is NOT viewport-independent evidence: the
# tablet and mobile captures of the same checkpoint carry
# `osano-cm-dialog--hidden` (dialog dismissed, widget shown) while the
# desktop capture shows the dialog and hides the widget. The frozen visual
# references record those states per viewport, so the clone encodes the
# captured tablet/mobile state behind a max-width media query using the
# capture's own rule bodies (.osano-cm-dialog--hidden /
# .osano-cm-widget--hidden inverse). Nothing here is authored styling: the
# toggle widths are the contract viewports and the effects are the
# capture's own hidden-state rules.
OSANO_DIALOG_HIDDEN = re.compile(r'class="[^"]*osano-cm-dialog--hidden')
OSANO_WIDGET_HIDDEN = re.compile(r'class="[^"]*osano-cm-widget--hidden')
OSANO_RECONCILE_STYLE = (
    "<style data-clone-state-reconciliation=\"osano-per-viewport\">"
    "@media (max-width: 1024px){"
    ".osano-cm-dialog{opacity:0;visibility:hidden}"
    ".osano-cm-widget.osano-cm-widget--hidden"
    "{opacity:1;visibility:visible;transform:none}"
    "}</style>"
)


def osano_state(page_html: str) -> tuple[bool, bool]:
    """(dialog_hidden, widget_hidden) as captured in a page document."""
    return (bool(OSANO_DIALOG_HIDDEN.search(page_html)),
            bool(OSANO_WIDGET_HIDDEN.search(page_html)))


def reconcile_osano_state(checkpoint: str, rewritten: str,
                          report: dict) -> str:
    desktop = osano_state(rewritten)
    if desktop != (False, True):
        return rewritten  # dialog not open on desktop: nothing to reconcile
    smaller = []
    for viewport in ("tablet", "mobile"):
        source = CAP_ROOT / checkpoint / viewport / "page.html"
        if source.exists():
            smaller.append(osano_state(source.read_text()))
    if smaller and all(state == (True, False) for state in smaller):
        report["osano_state_reconciled"] = True
        return rewritten.replace(
            "</head>", OSANO_RECONCILE_STYLE + "</head>", 1)
    return rewritten


def main() -> int:
    url_map = load_url_map()
    PAGES_OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    total_missing: set[str] = set()
    for checkpoint in CHECKPOINTS:
        source = CAP_ROOT / checkpoint / "desktop" / "page.html"
        html = source.read_text()
        report = {"rewritten": 0, "dropped_tags": [], "cdn_fallback_refs": [],
                  "script_blocks_dropped": 0, "ld_json_dropped": 0,
                  "first_party_localized": 0, "external_boundaries": [],
                  "osano_state_reconciled": False}
        rewritten = rewrite_document(html, url_map, report)
        rewritten = reconcile_osano_state(checkpoint, rewritten, report)
        # Mirror the assets-gate audit exactly, including protocol-relative
        # //host references, so this self-check cannot pass while the gate fails.
        remaining = sorted(set(re.findall(
            r"(?ix)(?:https?:)?//(?!localhost|127\.0\.0\.1)"
            r"[a-z0-9.-]+\.[a-z]{2,}[^\"'\s<>)]*",
            rewritten)))
        out_path = PAGES_OUT / f"{checkpoint}.html"
        out_path.write_text(rewritten)
        # Sanity: every referenced /static/... payload should exist on disk.
        missing = sorted(
            ref for ref in static_refs(rewritten)
            if not (SITE / "clone" / ref.lstrip("/")).exists())
        total_missing.update(missing)
        summary[checkpoint] = {
            "bytes": out_path.stat().st_size,
            "rewritten_refs": report["rewritten"],
            "script_blocks_dropped": report["script_blocks_dropped"],
            "ld_json_dropped": report["ld_json_dropped"],
            "dropped_tags": report["dropped_tags"],
            "cdn_fallback_refs": sorted(set(report["cdn_fallback_refs"])),
            "first_party_localized": report["first_party_localized"],
            "external_boundaries": sorted(set(report["external_boundaries"])),
            "osano_state_reconciled": report["osano_state_reconciled"],
            "missing_static_paths": missing,
            "remaining_remote_refs": remaining[:40],
            "remaining_remote_count": len(remaining),
        }
        print(f"  {checkpoint}: rewrote {report['rewritten']}, scripts-dropped "
              f"{report['script_blocks_dropped']}, localized "
              f"{report['first_party_localized']}, tags-dropped "
              f"{len(report['dropped_tags'])}, missing-assets {len(missing)}, "
              f"remote-left {len(remaining)}")
    ok = (len(summary) == len(CHECKPOINTS)
          and all(v["bytes"] > 0 for v in summary.values())
          and all(v["remaining_remote_count"] == 0 for v in summary.values()))
    summary["_totals"] = {
        "pages": len(CHECKPOINTS),
        "remaining_remote_total": sum(
            v["remaining_remote_count"] for v in summary.values()
            if isinstance(v, dict) and "remaining_remote_count" in v),
        "missing_static_paths_union": sorted(total_missing),
        "all_pages_nonzero_and_remote_free": ok,
    }
    (SITE / "clone" / "frontend" / "rewrite-report.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
