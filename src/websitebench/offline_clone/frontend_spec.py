"""Shared frontend-spec extraction tool.

Opens one approved-origin page with Playwright and enumerates the visible
document structure, headings, semantic regions, interactive controls, forms,
data points (prices, ratings, counts), and style/script references into a
stable, sanitized frontend specification. Clone implementations, interaction
contracts, and backend integration tests can all consume the same spec, which
keeps "the page itself", "the interaction logic", and "the backend data
contract" aligned instead of each side guessing from screenshots.

Safety mirrors the browser-explore tool: approved origins only, source
exploration is GET-only, storage state is never retained, input values are
never collected, and URLs are sanitized (query parameters outside a small
allowlist are dropped).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .toolbox import ToolboxError, origin, safe_url

FRONTEND_SPEC_SCHEMA = "websitebench.offline-clone.frontend-spec.v1"

_MAX_TEXT = 120
# Query parameters that carry navigation contract, kept on collected URLs.
_KEEP_QUERY = {
    "q",
    "query",
    "category",
    "level",
    "topic",
    "duration",
    "rating",
    "language",
    "schedule",
    "sort",
    "next",
    "page",
    "tab",
}

_PRICE_RE = re.compile(
    r"[¥$€£]\s*\d[\d,]*(?:\.\d+)?|"
    r"\b(?:CNY|USD|EUR|GBP)\s*\d[\d,]*(?:\.\d+)?|"
    r"\d[\d,]*(?:\.\d+)?\s*(?:CNY|USD|EUR|GBP)\b",
    re.IGNORECASE,
)
_RATING_RE = re.compile(r"★\s*\d\.\d|\d\.\d\s*(?:star|rating)", re.IGNORECASE)
_COUNT_RE = re.compile(
    r"[\d,]+(?:\s*\+)?\s*(?:courses?|learners?|reviews?|students?|enrolled|"
    r"programs?|degrees?|certificates?)",
    re.IGNORECASE,
)

_ENUMERATE_JS = r"""
() => {
  const out = {
    title: document.title || "",
    lang: document.documentElement.lang || "",
    headings: [],
    regions: [],
    controls: [],
    forms: [],
    styles: [],
    scripts: [],
    canonical: "",
  };
  const visible = (el) => {
    if (el.closest('[aria-hidden="true"]')) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.bottom >= 0 && r.right >= 0;
  };
  const textOf = (el) =>
    (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  const trim = (s, n) => (s || "").slice(0, n);
  for (const h of document.querySelectorAll("h1, h2, h3")) {
    if (!visible(h)) continue;
    const t = textOf(h);
    if (t) out.headings.push({ level: Number(h.tagName[1]), text: trim(t, 120) });
  }
  const regionSel = [
    "header", "nav", "main", "aside", "footer",
    "[role='banner']", "[role='navigation']", "[role='main']",
    "[role='complementary']", "[role='contentinfo']",
  ];
  for (const sel of regionSel) {
    for (const el of document.querySelectorAll(sel)) {
      if (!visible(el)) continue;
      out.regions.push({
        kind: el.tagName.toLowerCase(),
        role: el.getAttribute("role") || "",
        label: trim(el.getAttribute("aria-label") || "", 120),
      });
    }
  }
  const canonical = document.querySelector("link[rel='canonical']");
  if (canonical) out.canonical = canonical.getAttribute("href") || "";
  for (const link of document.querySelectorAll("link[rel~='stylesheet']")) {
    out.styles.push({
      href: link.getAttribute("href") || "",
      media: link.getAttribute("media") || "",
    });
  }
  for (const s of document.querySelectorAll("script[src]")) {
    out.scripts.push(s.getAttribute("src") || "");
  }
  const controlSel =
    "form, button, a[href], [role='button'], [role='tab'], [role='switch'], " +
    "[role='link'], input:not([type='hidden']), select, textarea";
  let idx = 0;
  for (const el of document.querySelectorAll(controlSel)) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const dataId = el.getAttribute("data-testid") ||
      el.getAttribute("data-e2e") || el.getAttribute("data-qa") || "";
    out.controls.push({
      id: "c-" + idx,
      kind: tag,
      type: type,
      text: trim(textOf(el), 120),
      aria_label: trim(el.getAttribute("aria-label") || "", 120),
      href: tag === "a" ? (el.getAttribute("href") || "") : "",
      action: tag === "form" ? (el.getAttribute("action") || "") : "",
      method: tag === "form" ? (el.getAttribute("method") || "get").toLowerCase() : "",
      name: trim(el.getAttribute("name") || "", 60),
      placeholder: trim(el.getAttribute("placeholder") || "", 60),
      required: el.hasAttribute("required"),
      disabled: Boolean(el.disabled) || el.getAttribute("aria-disabled") === "true",
      role: el.getAttribute("role") || "",
      data_testid: dataId,
      options:
        tag === "select"
          ? Array.from(el.querySelectorAll("option")).map((o) => trim(o.textContent || "", 60))
          : [],
    });
    if (tag === "form") out.forms.push({ control_id: "c-" + idx });
    idx += 1;
  }
  return out;
}
"""


def _clean_url(value: str) -> str:
    """Keep path plus allowlisted query parameters; drop everything else.

    Applies to absolute and relative URLs alike, so navigation contracts keep
    their route and meaningful parameters while tracking/token parameters are
    never retained.
    """

    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    kept: list[str] = []
    for part in (parsed.query or "").split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0].casefold()
        if key in _KEEP_QUERY:
            kept.append(part)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path or "/", "&".join(kept), "")
    )


def _sanitize_controls(controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for control in controls:
        item = dict(control)
        if item.get("href"):
            item["href"] = _clean_url(item["href"])
        if item.get("action"):
            item["action"] = _clean_url(item["action"])
        # Never retain a typed or bound value.
        item.pop("value", None)
        cleaned.append(item)
    return cleaned


def _find_data_points(text: str) -> list[dict[str, str]]:
    points: list[dict[str, str]] = []
    for pattern, kind in (
        (_PRICE_RE, "price"),
        (_RATING_RE, "rating"),
        (_COUNT_RE, "count"),
    ):
        for match in pattern.finditer(text):
            points.append({"kind": kind, "text": match.group(0)[:_MAX_TEXT]})
    return points


def extract_frontend_spec(
    *,
    target_url: str,
    allowed_origins: list[str],
    viewport: tuple[int, int],
    environment: str,
    output_path: Path,
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """Extract a sanitized frontend spec from one approved-origin page."""

    if environment not in {"source", "clone"}:
        raise ToolboxError("frontend-spec environment must be source or clone")
    width, height = viewport
    if not (240 <= width <= 7680 and 240 <= height <= 7680):
        raise ToolboxError("viewport dimensions are outside the supported range")
    base_origin = origin(target_url)
    approved = {origin(item) for item in allowed_origins}
    if base_origin not in approved:
        raise ToolboxError("target URL origin is absent from allowed_origins")
    if output_path.exists():
        raise ToolboxError(f"refusing to overwrite existing report: {output_path}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ToolboxError("frontend-spec extraction requires Playwright") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                service_workers="block",
                accept_downloads=False,
            )
            page = context.new_page()
            blocked: list[str] = []
            failed: list[str] = []
            console_errors: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(str(message.text)[:_MAX_TEXT])
                if message.type == "error"
                else None,
            )
            page.on(
                "requestfailed",
                lambda request: failed.append(safe_url(request.url)),
            )

            def route_request(route: Any, request: Any) -> None:
                scheme = urlsplit(request.url).scheme.casefold()
                if scheme in {"data", "blob"}:
                    route.continue_()
                    return
                if origin(request.url) not in approved:
                    blocked.append(safe_url(request.url))
                    route.abort()
                    return
                route.continue_()

            page.route("**/*", route_request)
            try:
                response = page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001 - surface as tool failure
                raise ToolboxError(f"failed to load {target_url}: {exc}") from None
            status = int(response.status) if response is not None else 0
            enumerated = page.evaluate(_ENUMERATE_JS)
            body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
        finally:
            context.close()
            browser.close()

    controls = _sanitize_controls(enumerated.get("controls") or [])
    styles = [
        {
            "href": _clean_url(item["href"]) if item.get("href") else "",
            "media": item.get("media") or "",
        }
        for item in enumerated.get("styles") or []
    ]
    scripts = [_clean_url(item) for item in enumerated.get("scripts") or []]
    data_points = _find_data_points(body_text or "")
    summary = {
        "http_status": status,
        "heading_count": len(enumerated.get("headings") or []),
        "region_count": len(enumerated.get("regions") or []),
        "control_count": len(controls),
        "form_count": len(enumerated.get("forms") or []),
        "data_point_count": len(data_points),
        "style_count": len(styles),
        "script_count": len(scripts),
        "blocked_request_count": len(blocked),
        "failed_request_count": len(failed),
        "console_error_count": len(console_errors),
    }
    report: dict[str, Any] = {
        "schema_version": FRONTEND_SPEC_SCHEMA,
        "authority": "diagnostic-only",
        "target_url": target_url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "viewport": {"width": width, "height": height},
        "environment": environment,
        "document": {
            "title": enumerated.get("title") or "",
            "lang": enumerated.get("lang") or "",
            "canonical": _clean_url(enumerated.get("canonical") or ""),
            "headings": enumerated.get("headings") or [],
            "regions": enumerated.get("regions") or [],
        },
        "controls": controls,
        "data_points": data_points,
        "styles": styles,
        "scripts": scripts,
        "summary": summary,
        "blocked_requests": sorted(set(blocked)),
        "failed_requests": sorted(set(failed)),
        "console_errors": console_errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report
