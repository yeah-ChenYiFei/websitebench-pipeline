#!/usr/bin/env python3
"""Bounded anonymous GET-only Walmart breadth reconnaissance.

Raw bodies and response headers stay in memory and are never persisted. The
output contains only short DOM-derived labels, sanitized routes, HTTP status,
challenge classification, and provenance.
"""

from __future__ import annotations

import gzip
import http.client
import json
import re
import ssl
import sys
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit


ORIGIN = "https://www.walmart.com"
HOST = "www.walmart.com"
MAX_BODY = 4 * 1024 * 1024
MAX_REDIRECTS = 2
MAX_PRODUCT_DETAILS = 3
KEEP_QUERY = {"q", "query", "page", "sort", "cat_id"}
CHALLENGE_MARKERS = (
    "press & hold",
    "press and hold",
    "verify you are human",
    "robot or human",
    "are you a human",
    "px-captcha",
    "captcha",
    "access denied",
)


def clean_text(value: str, limit: int = 160) -> str:
    return " ".join(value.split())[:limit]


def safe_url(value: str, base: str = ORIGIN + "/") -> str:
    try:
        absolute = urljoin(base, value)
        parsed = urlsplit(absolute)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    query = urlencode(
        [(key, val[:200]) for key, val in parse_qsl(parsed.query) if key.casefold() in KEEP_QUERY]
    )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", query, ""))


def same_origin(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.hostname == HOST and parsed.port in {None, 443}


class PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.controls: list[dict[str, object]] = []
        self.forms: list[dict[str, str]] = []
        self.declared_origins: set[str] = set()
        self._title = False
        self._heading: str | None = None
        self._anchor: dict[str, str] | None = None

    def _resource(self, raw: str) -> str:
        if not raw or raw.startswith(("data:", "blob:", "javascript:", "mailto:", "tel:", "#")):
            return ""
        cleaned = safe_url(raw, self.base_url)
        if cleaned:
            parsed = urlsplit(cleaned)
            self.declared_origins.add(f"{parsed.scheme}://{parsed.netloc}")
        return cleaned

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): (value or "") for key, value in attrs}
        if tag == "title":
            self._title = True
        if tag in {"h1", "h2", "h3"}:
            self._heading = tag
        for attr in ("src", "href", "action"):
            if values.get(attr):
                self._resource(values[attr])
        if tag == "a" and values.get("href"):
            href = safe_url(values["href"], self.base_url)
            self._anchor = {"href": href, "text": ""}
            self.links.append(self._anchor)
        if tag == "form":
            method = (values.get("method") or "get").upper()
            action = safe_url(values.get("action") or self.base_url, self.base_url)
            self.forms.append({"method": method, "action": action})
            self.controls.append(
                {
                    "kind": "form",
                    "type": "",
                    "label": clean_text(values.get("aria-label", ""), 120),
                    "name": clean_text(values.get("name", ""), 80),
                    "placeholder": "",
                    "required": False,
                    "action": action,
                    "method": method,
                }
            )
        if tag in {"button", "input", "select", "textarea"} or values.get("role") in {
            "button",
            "tab",
            "switch",
            "link",
        }:
            self.controls.append(
                {
                    "kind": tag,
                    "type": clean_text(values.get("type", ""), 40),
                    "label": clean_text(
                        values.get("aria-label")
                        or values.get("title")
                        or values.get("alt")
                        or values.get("role", ""),
                        120,
                    ),
                    "name": clean_text(values.get("name", ""), 80),
                    "placeholder": clean_text(values.get("placeholder", ""), 120),
                    "required": "required" in values,
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._title = False
        if tag in {"h1", "h2", "h3"}:
            self._heading = None
        if tag == "a":
            self._anchor = None

    def handle_data(self, data: str) -> None:
        text = clean_text(data, 240)
        if not text:
            return
        if self._title:
            self.title_parts.append(text)
        if self._heading:
            self.heading_parts.append(f"{self._heading}:{text}")
        if self._anchor is not None:
            self._anchor["text"] = clean_text((self._anchor["text"] + " " + text), 120)
        if len(self.text_parts) < 80:
            self.text_parts.append(text)


def fetch(url: str) -> tuple[int, str, str, bytes, bool, list[dict[str, str]]]:
    redirects: list[dict[str, str]] = []
    current = safe_url(url)
    context = ssl.create_default_context()
    for _ in range(MAX_REDIRECTS + 1):
        if not same_origin(current):
            raise ValueError(f"origin rejected: {current}")
        parsed = urlsplit(current)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        conn = http.client.HTTPSConnection(HOST, timeout=20, context=context)
        conn.request(
            "GET",
            path,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/149.0 Safari/537.36 WebsiteBench-Evidence/1",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "close",
            },
        )
        response = conn.getresponse()
        status = int(response.status)
        content_type = response.getheader("content-type", "")[:160]
        encoding = response.getheader("content-encoding", "").casefold()
        location = response.getheader("location", "")
        body = response.read(MAX_BODY + 1)
        conn.close()
        truncated = len(body) > MAX_BODY
        body = body[:MAX_BODY]
        if encoding == "gzip":
            try:
                body = gzip.decompress(body)
            except (EOFError, OSError):
                pass
        if status in {301, 302, 303, 307, 308} and location:
            target = safe_url(location, current)
            if not same_origin(target):
                redirects.append({"status": str(status), "target": target, "followed": "false"})
                return status, current, content_type, body, truncated, redirects
            redirects.append({"status": str(status), "target": target, "followed": "true"})
            current = target
            continue
        return status, current, content_type, body, truncated, redirects
    raise RuntimeError("same-origin redirect limit reached")


def classify_links(links: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = {
        "category": [],
        "product": [],
        "auth": [],
        "help": [],
        "search": [],
        "other": [],
    }
    seen: set[str] = set()
    for link in links:
        url = link.get("href", "")
        if not same_origin(url) or url in seen:
            continue
        seen.add(url)
        path = urlsplit(url).path.casefold()
        text = clean_text(link.get("text", ""), 120)
        item = {"route": urlunsplit(("", "", urlsplit(url).path or "/", urlsplit(url).query, "")), "text": text}
        if path.startswith("/ip/"):
            key = "product"
        elif path.startswith(("/cp/", "/browse/", "/c/")):
            key = "category"
        elif any(part in path for part in ("/account/login", "/account/signup", "/account/forgot")):
            key = "auth"
        elif path.startswith(("/help", "/contact", "/returns")):
            key = "help"
        elif path.startswith("/search"):
            key = "search"
        else:
            key = "other"
        if len(groups[key]) < 30:
            groups[key].append(item)
    return groups


def parse_observation(family: str, requested: str, status: int, final: str, content_type: str, body: bytes, truncated: bool, redirects: list[dict[str, str]]) -> dict[str, object]:
    decoded = body.decode("utf-8", "replace")
    parser = PageParser(final)
    is_markup = "html" in content_type.casefold() or decoded.lstrip().startswith(("<!DOCTYPE", "<html", "<?xml"))
    if is_markup:
        try:
            parser.feed(decoded)
        except Exception:
            pass
    text_probe = clean_text(" ".join(parser.text_parts) if parser.text_parts else decoded[:5000], 5000).casefold()
    challenge_markers = [marker for marker in CHALLENGE_MARKERS if marker in text_probe]
    links = classify_links(parser.links)
    plain_lines = [clean_text(line, 240) for line in decoded.splitlines() if clean_text(line, 240)]
    sitemap_urls = []
    if family == "robots-sitemaps":
        for match in re.finditer(r"(?i)(?:Sitemap:\s*|<loc>)(https://www\.walmart\.com[^<\s]+)", decoded):
            cleaned = safe_url(match.group(1), final)
            if same_origin(cleaned) and cleaned not in sitemap_urls and len(sitemap_urls) < 20:
                sitemap_urls.append(cleaned)
    controls = []
    for item in parser.controls:
        if item not in controls and len(controls) < 60:
            controls.append(item)
    forms = []
    for item in parser.forms:
        if item not in forms and len(forms) < 20:
            forms.append(item)
    return {
        "role": "EA2-breadth-first-explorer",
        "actor": "anonymous-shopper",
        "family": family,
        "action": "GET",
        "tool_category": "same-origin-read-only-http",
        "requested_route": urlunsplit(("", "", urlsplit(requested).path or "/", urlsplit(requested).query, "")),
        "observable_result": {
            "http_status": status,
            "final_route": urlunsplit(("", "", urlsplit(final).path or "/", urlsplit(final).query, "")),
            "content_type": content_type,
            "title": clean_text(" ".join(parser.title_parts), 200),
            "headings": list(dict.fromkeys(parser.heading_parts))[:20],
            "text_labels": list(dict.fromkeys(parser.text_parts))[:25],
            "forms": forms,
            "controls": controls,
            "links": links,
            "sitemap_urls": sitemap_urls,
            "declared_external_origins": sorted(origin for origin in parser.declared_origins if origin != ORIGIN)[:30],
            "redirects": redirects,
            "challenge_markers": challenge_markers,
        },
        "truncation_state": {
            "response_body_read_truncated": truncated,
            "persisted_raw_body": False,
            "text_labels_capped": True,
            "controls_capped": len(parser.controls) > len(controls),
            "links_capped_per_class": True,
        },
        "classification": "inaccessible" if challenge_markers else "direct-observation",
        "rationale": "Unique breadth-first public sibling; response content was reduced to sanitized DOM labels and route structure in memory.",
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: same_origin_bfs.py OUTPUT.json", file=sys.stderr)
        return 2
    output = Path(sys.argv[1]).resolve()
    visits: list[dict[str, object]] = []
    queue: deque[tuple[str, str, str]] = deque(
        [
            ("home", ORIGIN + "/", "home-primary-nav-footer-desktop-structure"),
            ("robots-sitemaps", ORIGIN + "/robots.txt", "official-robots-discovery"),
            ("search-results", ORIGIN + "/search?q=laundry%20detergent", "task-aligned-public-search-success-candidate"),
            ("search-results", ORIGIN + "/search?q=wb201-ea2-no-result-7f3f9", "anonymous-no-results-candidate"),
            ("help-recovery-not-found", ORIGIN + "/wb201-ea2-not-found-probe", "safe-not-found-route"),
        ]
    )
    seen: set[str] = set()
    queued_families: set[str] = {item[0] for item in queue}
    product_count = 0
    while queue:
        family, url, reason = queue.popleft()
        url = safe_url(url)
        if url in seen:
            continue
        seen.add(url)
        try:
            status, final, content_type, body, truncated, redirects = fetch(url)
            observation = parse_observation(family, url, status, final, content_type, body, truncated, redirects)
            observation["rationale"] = reason + "; " + str(observation["rationale"])
            visits.append(observation)
        except Exception as exc:
            visits.append(
                {
                    "role": "EA2-breadth-first-explorer",
                    "actor": "anonymous-shopper",
                    "family": family,
                    "action": "GET",
                    "tool_category": "same-origin-read-only-http",
                    "requested_route": urlunsplit(("", "", urlsplit(url).path or "/", urlsplit(url).query, "")),
                    "observable_result": {"error": clean_text(str(exc), 500)},
                    "truncation_state": {"persisted_raw_body": False},
                    "classification": "unavailable",
                    "rationale": reason + "; unique request failed and was not retried.",
                }
            )
            continue
        result = observation["observable_result"]
        if not isinstance(result, dict) or observation["classification"] == "inaccessible":
            continue
        links = result.get("links", {})
        if not isinstance(links, dict):
            continue
        if family == "home":
            for target_family, key in (("department-category", "category"), ("auth-entry", "auth"), ("help-recovery-not-found", "help")):
                candidates = links.get(key, [])
                if target_family not in queued_families and isinstance(candidates, list) and candidates:
                    route = candidates[0].get("route", "")
                    queue.append((target_family, ORIGIN + route, f"directly linked from {urlsplit(url).path or '/'}"))
                    queued_families.add(target_family)
        if family == "search-results":
            candidates = links.get("product", [])
            if isinstance(candidates, list):
                for item in candidates:
                    if product_count >= MAX_PRODUCT_DETAILS:
                        break
                    route = item.get("route", "")
                    if route and safe_url(ORIGIN + route) not in seen:
                        queue.append(("product-detail", ORIGIN + route, "directly linked from task-aligned search results"))
                        product_count += 1
        if family == "robots-sitemaps":
            sitemap_urls = result.get("sitemap_urls", [])
            if isinstance(sitemap_urls, list) and sitemap_urls:
                queue.append(("robots-sitemaps", sitemap_urls[0], "officially declared by robots.txt"))
    report = {
        "schema_version": "websitebench.trace-guided.ea2-breadth-source-summary.v1",
        "authority": "source-evidence-diagnostic-only",
        "site_id": "WB201",
        "site_key": "walmart",
        "source_origin": ORIGIN,
        "actor": "anonymous-shopper",
        "methods": ["GET"],
        "started_and_finished_at": datetime.now(timezone.utc).isoformat(),
        "safety": {
            "cookies_persisted": False,
            "credentials_or_sensitive_values_collected": False,
            "raw_request_or_response_bodies_persisted": False,
            "source_mutations_performed": False,
            "external_origins_requested": False,
            "redirect_policy": "same-origin-only; maximum two",
        },
        "limits": {
            "max_page_families": 8,
            "max_product_details": MAX_PRODUCT_DETAILS,
            "max_body_bytes_in_memory_per_request": MAX_BODY,
            "equivalent_failed_attempts": 1,
        },
        "visits": visits,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "visits": len(visits), "families": sorted({str(v.get('family')) for v in visits}), "classifications": {name: sum(v.get('classification') == name for v in visits) for name in ('direct-observation', 'inaccessible', 'unavailable')}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
