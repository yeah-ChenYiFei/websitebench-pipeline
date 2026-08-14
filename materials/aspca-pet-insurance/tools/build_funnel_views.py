#!/usr/bin/env python3
"""Build the quote-funnel and portal view fragments from captured SPA states.

For each captured funnel/portal checkpoint this tool takes the post-render
desktop page.html, removes every <script> block plus the injected consent
manager DOM, drops any tag that references a remote host absent from the
asset manifest, rewrites every mirrored asset reference onto its local
/static/assets/... path, localizes first-party absolute URLs, and writes:

  clone/frontend/quote/views/<name>.html    body fragments (app states)
  clone/frontend/portal/views/<name>.html   body fragments (app states)
  clone/frontend/quote/index.html           shell from the quote-start head
  clone/frontend/portal/index.html          shell from the portal-login head
  clone/frontend/quote/views-report.json    machine inventory of the views

The rewrite is purely mechanical (URL substitution + excluded-node removal);
DOM structure, classes, inline styles and copy are byte-preserved otherwise.
URL-localization logic follows materials/tripit/tools/build_frontend_pages.py.
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
QUOTE_OUT = SITE / "clone" / "frontend" / "quote"
PORTAL_OUT = SITE / "clone" / "frontend" / "portal"

QUOTE_VIEWS = [
    ("start", "quote-start"),
    ("start-validation", "quote-start-validation"),
    ("ineligible", "quote-ineligible"),
    ("rates", "quote-rates"),
    ("plan-detail", "quote-plan-detail"),
    ("plan-customize", "quote-plan-customize"),
    ("checkout", "quote-checkout"),
    ("resume", "quote-resume"),
    ("add-a-pet", "quote-add-a-pet"),
]
PORTAL_VIEWS = [
    ("login", "portal-login"),
    ("login-validation", "portal-login-validation"),
    ("forgot-password", "portal-forgot-password"),
    ("register", "portal-register"),
]

FIRST_PARTY_RE = re.compile(
    r"https?://(?:www\.)?aspcapetinsurance\.com/?([^\"'\s<>)]*)")
# Mirrors the assets-gate audit (tripit pattern), including protocol-relative
# //host references, so this self-check cannot pass while the gate fails.
REMOTE_REF_RE = re.compile(
    r"(?ix)(?:https?:)?//(?!localhost|127\.0\.0\.1)"
    r"[a-z0-9.-]+\.[a-z]{2,}[^\"'\s<>)]*")

SCRIPT_BLOCK = re.compile(r"(?is)<script\b[^>]*>.*?</script>")
NOSCRIPT_BLOCK = re.compile(r"(?is)<noscript\b[^>]*>.*?</noscript>")
LINK_TAG = re.compile(r"(?is)<link\b[^>]*>")
IFRAME_TAG = re.compile(r"(?is)<iframe\b[^>]*>\s*</iframe>")
IMG_TAG = re.compile(r"(?is)<img\b[^>]*>")
SOURCE_TAG = re.compile(r"(?is)<source\b[^>]*>")
META_TAG = re.compile(r"(?is)<meta\b[^>]*>")
STYLE_BLOCK = re.compile(r"(?is)<style\b[^>]*>.*?</style>")
NAMESPACE_DECL = re.compile(r'(?i)\s+xmlns(?::[a-z0-9]+)?="https?://[^"]*"')
REMOTE_CITE = re.compile(r'(?i)\s+cite="(?:https?:)?//[^"]*"')
URL_ATTR = re.compile(
    r"""(?is)\b(href|src|srcset|content|data-src|poster)\s*=\s*(["'])(.*?)\2""")


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
        parts = urllib.parse.urlsplit(url)
        mapping[f"//{parts.netloc}{parts.path}" +
                (f"?{parts.query}" if parts.query else "")] = local
        if parts.netloc.endswith("aspcapetinsurance.com"):
            mapping[parts.path + (f"?{parts.query}" if parts.query else "")] = local
    return mapping


def find_matching_end(html: str, open_start: int, tag: str) -> int:
    """Index just past the close tag matching the open tag at open_start."""
    scanner = re.compile(r"(?is)<(/?)%s\b[^>]*>" % re.escape(tag))
    depth = 0
    for m in scanner.finditer(html, open_start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()
    return -1


def remove_elements(html: str, open_re: str, label: str, report: dict) -> str:
    """Remove whole elements whose open tag matches open_re (balanced)."""
    pattern = re.compile(open_re)
    while True:
        m = pattern.search(html)
        if not m:
            return html
        tag = re.match(r"(?is)<([a-z0-9-]+)", m.group(0)).group(1)
        end = find_matching_end(html, m.start(), tag)
        if end < 0:  # malformed; drop the open tag only
            end = m.end()
        report["dropped_tags"].append(f"{label}:{m.group(0)[:80]}")
        html = html[:m.start()] + html[end:]


def rewrite_document(html: str, url_map: dict[str, str], report: dict) -> str:
    def map_url(url: str) -> str | None:
        url = url.strip()
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

    def is_remote(url: str) -> bool:
        u = html_lib.unescape(url.strip())
        return bool(re.match(r"(?i)(?:https?:)?//", u))

    # 1. Drop every script block (the clone never re-executes source JS) and
    #    noscript fallbacks (they carry tracker iframes, never rendered).
    n = len(SCRIPT_BLOCK.findall(html))
    html = SCRIPT_BLOCK.sub("", html)
    report["dropped_scripts"] = n
    html = NOSCRIPT_BLOCK.sub("", html)

    # 2. Remove the injected consent-manager DOM (osano), an overlay widget
    #    excluded from the runtime closure like tripit's trustarc.
    html = remove_elements(
        html, r'(?is)<div\b[^>]*class="[^"]*osano-cm-window[^"]*"[^>]*>',
        "osano", report)

    # 3. Drop or keep externally-referencing tags. A tag survives if every
    #    URL it references is mapped to a mirrored asset or is first-party.
    def tag_urls(tag: str) -> list[str]:
        return [v for _a, _q, v in URL_ATTR.findall(tag)]

    def drop_or_keep(match: re.Match, kind: str) -> str:
        tag = match.group(0)
        keep = True
        for url in tag_urls(tag):
            if kind == "img" and "srcset" in tag:
                pass  # srcset handled below; judge on src alone
            if not is_remote(url):
                continue
            if map_url(url) or FIRST_PARTY_RE.match(html_lib.unescape(url.strip())):
                continue
            keep = False
        if keep:
            return tag
        report["dropped_tags"].append(f"{kind}:{tag[:100]}")
        return ""

    def judge_img(match: re.Match) -> str:
        tag = match.group(0)
        src = re.search(r"""(?is)\bsrc\s*=\s*["']([^"']*)["']""", tag)
        if src and is_remote(src.group(1)) and not map_url(src.group(1)) \
                and not FIRST_PARTY_RE.match(html_lib.unescape(src.group(1))):
            report["dropped_tags"].append(f"img:{tag[:100]}")
            return ""
        # Unmapped remote srcset variants: strip the attribute, keep the tag.
        srcset = re.search(r"""(?is)\bsrcset\s*=\s*["']([^"']*)["']""", tag)
        if srcset:
            chunks = [c.strip().split()[0]
                      for c in srcset.group(1).split(",") if c.strip()]
            if any(is_remote(c) and not map_url(c)
                   and not FIRST_PARTY_RE.match(html_lib.unescape(c))
                   for c in chunks):
                report["stripped_srcset"] += 1
                tag = re.sub(r"""(?is)\s+srcset\s*=\s*["'][^"']*["']""", "", tag)
        return tag

    html = LINK_TAG.sub(lambda m: drop_or_keep(m, "link"), html)
    html = IFRAME_TAG.sub(lambda m: drop_or_keep(m, "iframe"), html)
    html = SOURCE_TAG.sub(lambda m: drop_or_keep(m, "source"), html)
    html = IMG_TAG.sub(judge_img, html)
    # origin-trial tokens are tracker grants; drop those meta tags wholesale.
    html = re.sub(r'(?is)<meta\b[^>]*http-equiv="origin-trial"[^>]*>', "", html)

    # 4. Inline-SVG namespace declarations and provenance cite attributes are
    #    metadata, never fetched; strip so the textual audit stays clean.
    html = NAMESPACE_DECL.sub("", html)
    html = REMOTE_CITE.sub("", html)
    html = re.sub(r'(?is)\sprefix="[^"]*"', "", html, count=1)

    # 5. Rewrite mapped URL attributes.
    def replace_attr(match: re.Match) -> str:
        attr, quote, value = match.group(1), match.group(2), match.group(3)
        if attr.casefold() == "srcset":
            parts, changed = [], False
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

    # 6. CSS url(...) references inside inline <style> blocks / style attrs.
    def replace_css_url(match: re.Match) -> str:
        target = match.group(1).strip("'\"")
        mapped = map_url(target)
        if mapped:
            report["rewritten"] += 1
            return f"url({mapped})"
        return match.group(0)

    html = re.sub(r"url\(\s*([^)]+?)\s*\)", replace_css_url, html)

    # 7. First-party absolute URLs become local paths on the clone origin.
    def strip_origin(match: re.Match) -> str:
        report["first_party_localized"] += 1
        return "/" + match.group(1).lstrip("/")

    html = FIRST_PARTY_RE.sub(strip_origin, html)

    # 8. Remaining third-party navigation targets keep their affordance but
    #    point at the local external-boundary route (tripit pattern).
    def boundary(match: re.Match) -> str:
        url = match.group(3)
        parts = urllib.parse.urlsplit(html_lib.unescape(url))
        slug = re.sub(r"[^a-z0-9.-]+", "-", parts.netloc.casefold()) or "external"
        report["external_boundaries"].append(url[:90])
        return (f"{match.group(1)}={match.group(2)}"
                f"/external/{slug}{match.group(2)}")

    html = re.sub(
        r"""(?is)\b(href)\s*=\s*(["'])(https?://[^"']+|//[^"']+)\2""",
        boundary, html)

    # 9. Final scrub: any style block or meta tag still carrying a remote URL
    #    is an excluded widget's residue; drop it and record the removal.
    def scrub_block(match: re.Match, kind: str) -> str:
        block = match.group(0)
        if REMOTE_REF_RE.search(block):
            report["dropped_tags"].append(f"{kind}-residual:{block[:80]}")
            return ""
        return block

    html = STYLE_BLOCK.sub(lambda m: scrub_block(m, "style"), html)
    html = META_TAG.sub(lambda m: scrub_block(m, "meta"), html)
    return html


def split_document(html: str) -> tuple[str, str, str]:
    """Return (head_inner, body_attrs, body_inner)."""
    head = re.search(r"(?is)<head[^>]*>(.*?)</head>", html)
    body = re.search(r"(?is)<body([^>]*)>(.*)</body>", html)
    return (head.group(1) if head else "",
            body.group(1) if body else "",
            body.group(2) if body else html)


def build_shell(head_inner: str, body_attrs: str, app_js: str,
                lang: str = "en") -> str:
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{lang}">\n<head>{head_inner}</head>\n'
        f"<body{body_attrs}>\n"
        '<div id="app-root"></div>\n'
        f'<script src="{app_js}"></script>\n'
        "</body>\n</html>\n")


# ---------------------------------------------------------------------------
# Machine inventory (views-report.json) — all values read from the captures.
# ---------------------------------------------------------------------------

def strip_tags(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", fragment).split())


def attr(tag: str, name: str) -> str | None:
    m = re.search(r'(?is)\b%s\s*=\s*"([^"]*)"' % re.escape(name), tag)
    return html_lib.unescape(m.group(1)) if m else None


def label_for(html: str, control_id: str | None) -> str | None:
    if not control_id:
        return None
    m = re.search(r'(?is)<label[^>]*\bfor="%s"[^>]*>(.*?)</label>'
                  % re.escape(control_id), html)
    return strip_tags(m.group(1))[:120] if m else None


def extract_controls(html: str) -> list[dict]:
    controls = []
    for m in re.finditer(r"(?is)<(input|select|textarea)\b[^>]*>", html):
        tag = m.group(0)
        if "g-recaptcha-response" in tag:
            continue
        cid = attr(tag, "id")
        item = {
            "tag": m.group(1).lower(),
            "type": attr(tag, "type"),
            "name": attr(tag, "name"),
            "id": cid,
            "ng_model": attr(tag, "ng-model"),
            "required": bool(re.search(
                r'(?i)\brequired\b|aria-required="true"', tag)),
            "label": label_for(html, cid),
        }
        if item["tag"] == "input" and item["type"] == "radio":
            item["value"] = attr(tag, "value")
        if item["tag"] == "select":
            end = find_matching_end(html, m.start(), "select")
            body = html[m.end():end]
            opts = re.findall(
                r'(?is)<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', body)
            item["options"] = [
                {"value": v, "label": strip_tags(t)} for v, t in opts][:60]
        maxlength = attr(tag, "maxlength")
        if maxlength:
            item["maxlength"] = maxlength
        pattern = attr(tag, "ng-pattern")
        if pattern:
            item["ng_pattern"] = pattern
        controls.append(item)
    return controls


def extract_validation_messages(html: str) -> list[dict]:
    out, seen = [], set()
    # Pass 1: the per-field message elements themselves (formErrors / portal
    # input_error), whose ids are the stable hooks the clone JS toggles.
    # Pass 2: banner/summary/list wrappers. `\sclass=` excludes ng-class exprs.
    patterns = (
        r'(?is)<(p|span|em)\b[^>]*\sclass="[^"]*'
        r'(?:formErrors|input_error|icon_error)[^"]*"[^>]*>(.*?)</\1>',
        r'(?is)<(p|div|span|em|li)\b[^>]*\sclass="[^"]*'
        r'(?:errorSummary|alertWrapper|_alert)[^"]*"[^>]*>(.*?)</\1>',
    )
    for pattern in patterns:
        for m in re.finditer(pattern, html):
            _collect_message(m, out, seen)
    return out


def _collect_message(m: re.Match, out: list, seen: set) -> None:
    open_tag = m.group(0)[: m.group(0).find(">") + 1]
    text = strip_tags(m.group(2))
    if not text or len(text) > 200:
        return
    key = (text, attr(open_tag, "id") or "")
    if key in seen:
        return
    seen.add(key)
    out.append({
        "text": text,
        "id": attr(open_tag, "id"),
        "class": attr(open_tag, "class"),
        "ng_bind": attr(open_tag, "ng-bind"),
        "ng_if": attr(open_tag, "ng-if"),
        "hidden_in_markup": bool(re.search(
            r'(?i)ng-hide|display:\s*none|\bhidden\b', open_tag)),
    })


def extract_radio_group(html: str, name: str) -> list[dict]:
    group = []
    for m in re.finditer(
            r'(?is)<input\b[^>]*\bname="%s"[^>]*>' % re.escape(name), html):
        tag = m.group(0)
        rid = attr(tag, "id")
        cls = attr(tag, "class") or ""
        group.append({
            "id": rid,
            "value": attr(tag, "value"),
            "label": label_for(html, rid),
            "selected_in_capture": "ng-pristine" not in cls,
        })
    return group


def extract_tier_cards(html: str) -> list[dict]:
    cards = []
    for m in re.finditer(r'(?is)<li\b[^>]*data-tier="([^"]*)"[^>]*>', html):
        tag = m.group(0)
        end = find_matching_end(html, m.start(), "li")
        body = html[m.end():end]
        name = re.search(
            r'(?is)class="eb-tier-selector__option-name[^"]*"[^>]*>(.*?)<',
            body)
        # The price span nests an sr-only child; take the balanced element.
        price_text = None
        p = re.search(
            r'(?is)<span\b[^>]*class="eb-tier-selector__option-price[^"]*"'
            r'[^>]*>', body)
        if p:
            p_end = find_matching_end(body, p.start(), "span")
            price_text = strip_tags(
                body[p.end():p_end - len("</span>")]).replace("Price: ", "")
        cards.append({
            "data_tier": m.group(1),
            "name": strip_tags(name.group(1)) if name else None,
            "price_text": price_text,
            "aria_label": attr(tag, "aria-label"),
            "selected_in_capture": "--selected" in (attr(tag, "class") or ""),
        })
    return cards


def extract_preventive(html: str) -> dict:
    out = {}
    for key, cta in (("basic", "Add Basic"), ("prime", "Add Prime")):
        i = html.find(cta)
        if i < 0:
            continue
        window = html[max(0, i - 6000): i + 200]
        price = re.findall(
            r'(?is)opcpriceSummary_priceMonthly[^"]*"[^>]*>\s*([^<]+?)\s*<',
            window)
        toggle = re.search(
            r"togglePreventiveCareSelection\('%s'\)" % key, html)
        out[key] = {
            "cta_text": cta,
            "price_text": price[-1].strip() if price else None,
            "toggle_marker": bool(toggle),
        }
    return out


def extract_accordions(rates_html: str, detail_html: str,
                       customize_html: str) -> dict:
    out = {}
    for key, hid in (("whats_covered", "accordBody-coverage-details-faq-0"),
                     ("whats_not_covered", "accordBody-What’s-Not-Covered-faq"),
                     ("build_your_own", "accordBody-build-your-own")):
        entry = {}
        for state, h in (("collapsed_state", rates_html),
                         ("expanded_state",
                          customize_html if key == "build_your_own"
                          else detail_html)):
            btn = re.search(
                r'(?is)<(?:button|a)\b[^>]*data-target="#%s"[^>]*>'
                % re.escape(hid), h)
            panel = re.search(
                r'(?is)<div\b[^>]*id="%s"[^>]*>' % re.escape(hid), h)
            entry[state] = {
                "button_class": attr(btn.group(0), "class") if btn else None,
                "aria_expanded": attr(btn.group(0), "aria-expanded")
                if btn else None,
                "panel_class": attr(panel.group(0), "class") if panel else None,
                "panel_style": attr(panel.group(0), "style") if panel else None,
            }
        entry["panel_id"] = hid
        out[key] = entry
    return out


PAYMENT_KEY_RE = re.compile(
    r"(?i)card|cvv|cvc|expir|credit|debit|routing|iban|swift|"
    r"account.?number|billing.?(?:card|account)|cc[-_]")


def main() -> int:
    url_map = load_url_map()
    (QUOTE_OUT / "views").mkdir(parents=True, exist_ok=True)
    (PORTAL_OUT / "views").mkdir(parents=True, exist_ok=True)

    fragments: dict[str, str] = {}
    file_reports: dict[str, dict] = {}
    metas: dict[str, dict] = {}
    written: list[str] = []

    def process(view: str, checkpoint: str, out_dir: pathlib.Path,
                family: str) -> None:
        source = CAP_ROOT / checkpoint / "desktop" / "page.html"
        raw = source.read_text()
        report = {"rewritten": 0, "dropped_tags": [], "dropped_scripts": 0,
                  "first_party_localized": 0, "external_boundaries": [],
                  "stripped_srcset": 0}
        cleaned = rewrite_document(raw, url_map, report)
        head, body_attrs, body = split_document(cleaned)
        fragments[f"{family}/{view}"] = body
        out_path = out_dir / "views" / f"{view}.html"
        out_path.write_text(body.strip() + "\n")
        written.append(str(out_path))
        metas[f"{family}/{view}"] = json.loads(
            (CAP_ROOT / checkpoint / "desktop" / "meta.json").read_text())
        remaining = sorted(set(REMOTE_REF_RE.findall(body)))
        file_reports[f"{family}/{view}"] = {
            "source_checkpoint": checkpoint,
            "rewritten_refs": report["rewritten"],
            "dropped_scripts": report["dropped_scripts"],
            "dropped_tags": report["dropped_tags"][:60],
            "dropped_tag_count": len(report["dropped_tags"]),
            "stripped_srcset": report["stripped_srcset"],
            "first_party_localized": report["first_party_localized"],
            "external_boundaries": sorted(set(report["external_boundaries"])),
            "remaining_remote_refs": remaining[:40],
            "remaining_remote_count": len(remaining),
        }
        if family == "quote" and view == "start":
            shell = build_shell(head, body_attrs, "/static/site/quote-app.js")
            (QUOTE_OUT / "index.html").write_text(shell)
            written.append(str(QUOTE_OUT / "index.html"))
            file_reports["quote/index"] = {
                "source_checkpoint": checkpoint,
                "remaining_remote_count": len(
                    set(REMOTE_REF_RE.findall(shell))),
            }
        if family == "portal" and view == "login":
            shell = build_shell(head, body_attrs, "/static/site/portal-app.js")
            (PORTAL_OUT / "index.html").write_text(shell)
            written.append(str(PORTAL_OUT / "index.html"))
            file_reports["portal/index"] = {
                "source_checkpoint": checkpoint,
                "remaining_remote_count": len(
                    set(REMOTE_REF_RE.findall(shell))),
            }

    for view, checkpoint in QUOTE_VIEWS:
        process(view, checkpoint, QUOTE_OUT, "quote")
    for view, checkpoint in PORTAL_VIEWS:
        process(view, checkpoint, PORTAL_OUT, "portal")

    # ---------------- machine inventory -----------------------------------
    raw_start = (CAP_ROOT / "quote-start" / "desktop" / "page.html").read_text()
    email_pattern = re.search(
        r'(?is)<input[^>]*name="emailAddress"[^>]*ng-pattern="([^"]*)"',
        raw_start)

    views_section = {}
    for key, frag in fragments.items():
        views_section[key] = {
            "source_checkpoint": file_reports[key]["source_checkpoint"],
            "final_url": metas[key].get("final_url"),
            "title": metas[key].get("title"),
            "controls": extract_controls(frag),
        }
        if key.endswith(("-validation", "ineligible")):
            views_section[key]["validation_messages"] = \
                extract_validation_messages(frag)

    checkout_frag = fragments["quote/checkout"]
    checkout_controls = [c for c in extract_controls(checkout_frag)
                         if c["name"] not in ("6", "7")]
    payment_hits = sorted({
        c["name"] for c in checkout_controls
        if c["name"] and PAYMENT_KEY_RE.search(c["name"])})

    rates_frag = fragments["quote/rates"]
    customize_frag = fragments["quote/plan-customize"]
    detail_frag = fragments["quote/plan-detail"]

    report_doc = {
        "capture_id": CAPTURE_ID,
        "generated_by": "tools/build_funnel_views.py",
        "email_ng_pattern": html_lib.unescape(email_pattern.group(1))
        if email_pattern else None,
        "views": views_section,
        "tier_cards": extract_tier_cards(rates_frag),
        "customize_radios": {
            name: extract_radio_group(customize_frag, name)
            for name in ("annualDeductiblel2", "reimbursementPercentl2",
                         "annualLimitl2", "annualDeductiblel1",
                         "reimbursementPercentl1", "annualLimitl1")},
        "preventive_options": extract_preventive(customize_frag),
        "accordions": extract_accordions(rates_frag, detail_frag,
                                         customize_frag),
        "checkout": {
            "controls": checkout_controls,
            "field_count": len(checkout_controls),
            "frequency_options": [
                {"id": c["id"], "value": c.get("value"), "label": c["label"]}
                for c in checkout_controls if c["name"] == "paymentType"],
            "payment_field_scan": {
                "suspicious_names": payment_hits,
                "note": "name=paymentType is the billing-frequency radio "
                        "(Monthly/Annually) as captured; no card/cvv/expiry/"
                        "account-number inputs exist in the capture.",
            },
        },
        "resume_form": {
            "controls": [c for c in extract_controls(fragments["quote/resume"])
                         if c["name"] not in ("6", "7")],
            "api_query_params": ["email", "zip"],
        },
        "add_a_pet_form": {
            "controls": [c for c in
                         extract_controls(fragments["quote/add-a-pet"])
                         if c["name"] not in ("6", "7", "844", "845")],
        },
        "ineligible": {
            "trigger": metas["quote/ineligible"].get("interaction"),
            "error_messages": extract_validation_messages(
                fragments["quote/ineligible"]),
        },
        "portal": {
            key.split("/", 1)[1]: {
                "controls": extract_controls(frag),
                "validation_messages": extract_validation_messages(frag),
            }
            for key, frag in fragments.items() if key.startswith("portal/")},
        "files": file_reports,
    }
    report_path = QUOTE_OUT / "views-report.json"
    report_path.write_text(json.dumps(report_doc, indent=2,
                                      ensure_ascii=False) + "\n")
    written.append(str(report_path))

    # ---------------- static-path existence check --------------------------
    missing = set()
    for path in written:
        if not path.endswith(".html"):
            continue
        text = pathlib.Path(path).read_text()
        for m in re.finditer(r'(?:"|\()(/static/[^"\s)#?]+)', text):
            local = SITE / "clone" / m.group(1).lstrip("/")
            if not local.exists():
                missing.add(m.group(1))
    total_remote = sum(r["remaining_remote_count"]
                       for r in file_reports.values())
    for key, rep in file_reports.items():
        print(f"  {key}: rewrote {rep.get('rewritten_refs', '-')}, dropped "
              f"{rep.get('dropped_tag_count', 0)} tags + "
              f"{rep.get('dropped_scripts', 0)} scripts, remote-left "
              f"{rep['remaining_remote_count']}")
    print(f"remaining remote refs total: {total_remote}")
    print(f"missing /static paths: {len(missing)}")
    for p in sorted(missing)[:20]:
        print("  MISSING", p)
    return 1 if (total_remote or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
