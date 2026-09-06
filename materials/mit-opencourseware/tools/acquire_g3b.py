"""Acquire immutable G3-B route bodies with anonymous, same-origin GETs.

This is a deliberately narrow content addendum, not a replacement for the G1
capture.  The authoritative ``websitebench.workflow.cli acquire-source`` tool
does preserve DOM and visible text, but also captures a full-page screenshot
and page dependencies for every row.  Repeating that work for 732 already
frozen routes would add duplicate visual/resource evidence to this content-only
closure.  This tool therefore records the exact response body and provenance,
then produces a separately hashed, network-closed HTML fragment.

Each batch contains at most 183 routes, is promoted atomically, and is
create-only.  No external origin is ever requested.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

from websitebench.offline_clone.assets import inspect_asset


SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parents[1]
CLONE = SITE / "clone"
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
ORIGIN = "https://ocw.mit.edu"
BATCH_SIZE = 183
TOTAL_ROUTES = 732
MAX_ASSET_BYTES = 15 * 1024 * 1024
USER_AGENT = "WebsiteBench-MIT-OCW-G3B/1.0 (anonymous public evaluation capture)"
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
DROP_TAGS = {"script", "style", "noscript", "template", "iframe", "audio", "video", "source", "track"}
SAFE_TAGS = {
    "a", "abbr", "address", "article", "aside", "b", "blockquote", "br", "button",
    "caption", "cite", "code", "col", "colgroup", "dd", "del", "details", "dfn",
    "div", "dl", "dt", "em", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "img", "input",
    "kbd", "label", "legend", "li", "main", "mark", "nav", "ol", "option", "p",
    "pre", "q", "s", "samp", "section", "select", "small", "span", "strong", "sub",
    "summary", "sup", "table", "tbody", "td", "textarea", "tfoot", "th", "thead",
    "time", "tr", "u", "ul", "var",
}
SAFE_ATTRS = {
    "abbr", "alt", "aria-checked", "aria-current", "aria-describedby", "aria-expanded",
    "aria-hidden", "aria-label", "aria-labelledby", "aria-live", "aria-pressed", "aria-selected",
    "checked", "class", "colspan", "data-language", "data-title", "datetime", "dir", "disabled",
    "for", "headers", "height", "href", "id", "lang", "max", "maxlength", "method", "min",
    "multiple", "name", "open", "placeholder", "readonly", "rel", "required", "role", "rowspan",
    "selected", "size", "span", "src", "step", "style", "tabindex", "target", "title", "type",
    "value", "width",
}
MIME_SUFFIX = {
    "image/avif": ".avif", "image/gif": ".gif", "image/jpeg": ".jpg",
    "image/png": ".png", "image/svg+xml": ".svg", "image/webp": ".webp",
}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_atomic(path: Path, value: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if compact else json.dumps(value, ensure_ascii=False, indent=2)
    ) + "\n"
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def same_origin(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() == "https" and (parsed.hostname or "").lower() == "ocw.mit.edu" and parsed.port is None


def relative(path: Path) -> str:
    return path.relative_to(SITE).as_posix()


def route_order(data: dict[str, Any]) -> list[dict[str, Any]]:
    pages = data["pages"]
    contract = load(SITE / "scope" / "business-contracts" / "route-state-contract.json")
    representative = [str(row["path"]) for row in contract["representative_acceptance_routes"]]
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for path in representative:
        # Three diagnostic boundary/recovery routes are candidate-only and are
        # intentionally absent from the 732 source-route denominator.
        if path in pages and path not in seen:
            ordered.append(pages[path])
            seen.add(path)
    for row in sorted(pages.values(), key=lambda item: (str(item["family"]), str(item["path"]))):
        if row["path"] not in seen:
            ordered.append(row)
            seen.add(str(row["path"]))
    assert len(ordered) == len(seen) == TOTAL_ROUTES
    assert all(same_origin(str(row["source_url"])) for row in ordered)
    return ordered


def attrs_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): value or "" for name, value in attrs}


class FragmentExtractor(HTMLParser):
    """Capture the first balanced element matching a route-family predicate."""

    def __init__(self, predicate):
        super().__init__(convert_charrefs=False)
        self.predicate = predicate
        self.depth = 0
        self.started = False
        self.done = False
        self.parts: list[str] = []
        self.root_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if not self.started and self.predicate(lower, attrs_dict(attrs)):
            self.started = True
            self.root_tag = lower
            self.depth = 1
            self.parts.append(self.get_starttag_text())
            if lower in VOID_TAGS:
                self.done = True
            return
        if self.started and not self.done:
            self.parts.append(self.get_starttag_text())
            if lower not in VOID_TAGS:
                self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.started and self.predicate(tag.lower(), attrs_dict(attrs)):
            self.started = self.done = True
            self.parts.append(self.get_starttag_text())
        elif self.started and not self.done:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if not self.started or self.done:
            return
        self.parts.append(f"</{tag}>")
        self.depth -= 1
        if self.depth <= 0:
            self.done = True

    def handle_data(self, data: str) -> None:
        if self.started and not self.done:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.started and not self.done:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.started and not self.done:
            self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if self.started and not self.done:
            self.parts.append(f"<!--{data}-->")

    @property
    def fragment(self) -> str:
        return "".join(self.parts)


def selector_for(family: str):
    def identity(tag: str, attrs: dict[str, str]) -> bool:
        classes = set(attrs.get("class", "").split())
        if family == "course-overview":
            return tag == "div" and "course-home-grid" in classes and "col-md-8" in classes
        if family == "course-section-or-deep-link":
            return tag == "main" and attrs.get("id") == "course-content-section"
        if family == "resource-detail-or-index":
            return tag == "div" and "resource-page-container" in classes
        if family in {"course-download", "video-gallery"}:
            return tag == "div" and attrs.get("id") == "main-course-section"
        if family == "collection":
            return tag == "div" and "collection-outer-container" in classes
        if family == "site-information-or-boundary":
            return tag == "div" and "page-single" in classes
        if family in {"story-index", "story-detail"}:
            return tag == "div" and "testimonial-banner" in classes
        if family == "home":
            return tag == "main"
        if family == "catalog-search":
            return tag == "div" and attrs.get("id") == "search-page"
        return False
    return identity


def extract_fragment(raw: bytes, family: str) -> tuple[str, str, bool]:
    text = raw.decode("utf-8", errors="replace")
    extractor = FragmentExtractor(selector_for(family))
    extractor.feed(text)
    fragment = extractor.fragment
    selector = {
        "course-overview": "div.course-home-grid.col-md-8",
        "course-section-or-deep-link": "main#course-content-section",
        "resource-detail-or-index": "div.resource-page-container",
        "course-download": "div#main-course-section",
        "video-gallery": "div#main-course-section",
        "collection": "div.collection-outer-container",
        "site-information-or-boundary": "div.page-single",
        "story-index": "div.testimonial-banner",
        "story-detail": "div.testimonial-banner",
        "home": "main",
        "catalog-search": "div#search-page",
    }[family]
    fallback = False
    # Resource list pages use the course content column rather than the detail
    # container.  This is a documented family variant, not a whole-body
    # fallback.
    if family == "resource-detail-or-index" and not fragment:
        resource_index = FragmentExtractor(
            lambda tag, attrs: tag == "div" and attrs.get("id") == "main-course-section"
        )
        resource_index.feed(text)
        fragment = resource_index.fragment
        if fragment:
            selector = "div#main-course-section (resource-index variant)"
    if family == "course-overview" and not fragment:
        list_page = FragmentExtractor(
            lambda tag, attrs: tag == "div" and attrs.get("id") == "main-course-section"
        )
        list_page.feed(text)
        fragment = list_page.fragment
        if fragment:
            selector = "div#main-course-section (course-list/boundary variant)"
    if family == "site-information-or-boundary" and not fragment:
        info_page = FragmentExtractor(
            lambda tag, attrs: tag == "div" and "page-container" in set(attrs.get("class", "").split())
        )
        info_page.feed(text)
        fragment = info_page.fragment
        if fragment:
            selector = "div.page-container (information variant)"
    # Story body/list content follows the banner as siblings.  Capture the exact
    # SSR central range up to the footer rather than silently dropping it.
    if family in {"story-index", "story-detail"}:
        start = re.search(r'<div\s+class=["\'][^"\']*testimonial-banner[^"\']*["\']', text, re.I)
        end = re.search(r'<(?:footer\b|div\s+id=["\']home-footer["\'])', text[start.start():] if start else "", re.I)
        if start and end:
            stop = start.start() + end.start()
            fragment = f'<div class="g3b-story-source">{text[start.start():stop]}</div>'
            selector = "range:div.testimonial-banner..footer#footer-container"
    if family == "home":
        start = re.search(r'<div\s+class=["\'][^"\']*home-banner[^"\']*["\']', text, re.I)
        end = re.search(r'<footer\s+id=["\']footer-container["\']', text[start.start():] if start else "", re.I)
        if start and end:
            stop = start.start() + end.start()
            fragment = f'<div class="g3b-home-source">{text[start.start():stop]}</div>'
            selector = "range:div.home-banner..footer#footer-container"
    if not fragment:
        body = FragmentExtractor(lambda tag, attrs: tag == "body")
        body.feed(text)
        fragment = body.fragment
        selector = "body:fallback"
        fallback = True
    return fragment, selector, fallback


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.drop = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in DROP_TAGS:
            self.drop += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in DROP_TAGS and self.drop:
            self.drop -= 1

    def handle_data(self, data: str) -> None:
        if not self.drop:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)


def visible_text(fragment: str) -> str:
    parser = TextExtractor()
    parser.feed(fragment)
    return parser.text


def build_known_maps(data: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    route_map: dict[str, str] = {}
    for path, row in data["pages"].items():
        source = normalized_url(str(row["source_url"]))
        route_map[source] = path
        parsed = urlsplit(source)
        bare_path = parsed.path.rstrip("/") or "/"
        aliases = {bare_path, bare_path + "/" if bare_path != "/" else "/"}
        for alias in aliases:
            route_map[urlunsplit((parsed.scheme, parsed.netloc, alias, "", ""))] = path
    download_map = {normalized_url(str(row["url"])): path for path, row in data["downloads"].items()}
    if data.get("pdf"):
        download_map[normalized_url(str(data["pdf"]["source_url"]))] = str(data["pdf"]["path"])
    asset_map: dict[str, str] = {}
    for source, local in {**data.get("asset_url_map", {}), **data.get("g3_visual_url_map", {})}.items():
        asset_map[normalized_url(source)] = str(local)
    addendum = SITE / "source-assets" / "g3b-content-asset-addendum.json"
    if addendum.exists():
        asset_map.update(load(addendum).get("url_map", {}))
    return route_map, download_map, asset_map


class Sanitizer(HTMLParser):
    def __init__(self, *, base_url: str, route_path: str, route_map: dict[str, str], download_map: dict[str, str], asset_map: dict[str, str]):
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.route_path = route_path
        self.route_map = route_map
        self.download_map = download_map
        self.asset_map = asset_map
        self.parts: list[str] = []
        self.drop_depth = 0
        self.drop_stack: list[str] = []
        self.open_stack: list[tuple[str, str]] = []
        self.unknown_same_origin_assets: set[str] = set()
        self.external_assets: set[str] = set()
        self.counts: Counter[str] = Counter()

    def rewrite_href(self, value: str) -> str:
        value = html.unescape(value.strip())
        if not value or value.startswith("#"):
            return value or "#"
        absolute = normalized_url(urljoin(self.base_url, value))
        parsed = urlsplit(absolute)
        if parsed.scheme not in {"http", "https"}:
            self.counts["non_http_href_boundary"] += 1
            return "/external-boundary/?url=" + quote(absolute, safe="")
        identity = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if absolute in self.download_map or identity in self.download_map:
            self.counts["download_href_rewrites"] += 1
            return self.download_map[absolute] if absolute in self.download_map else self.download_map[identity]
        if absolute in self.route_map or identity in self.route_map:
            self.counts["route_href_rewrites"] += 1
            local = self.route_map[absolute] if absolute in self.route_map else self.route_map[identity]
            return local + (f"?{parsed.query}" if parsed.query else "")
        if same_origin(absolute):
            self.counts["same_origin_boundary_rewrites"] += 1
            return "/data-boundary/?url=" + quote(absolute, safe="")
        self.counts["external_boundary_rewrites"] += 1
        return "/external-boundary/?url=" + quote(absolute, safe="")

    def rewrite_asset(self, value: str) -> str | None:
        absolute = normalized_url(urljoin(self.base_url, html.unescape(value.strip())))
        parsed = urlsplit(absolute)
        identity = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if absolute in self.asset_map or identity in self.asset_map:
            self.counts["asset_rewrites"] += 1
            return self.asset_map[absolute] if absolute in self.asset_map else self.asset_map[identity]
        if same_origin(absolute):
            self.unknown_same_origin_assets.add(absolute)
        else:
            self.external_assets.add(absolute)
        self.counts["asset_unavailable"] += 1
        return None

    def clean_style(self, value: str) -> str:
        output = value
        for match in list(re.finditer(r"(?is)url\(\s*['\"]?([^'\")\s]+)", value)):
            source = match.group(1)
            local = self.rewrite_asset(source)
            if local:
                output = output.replace(source, local)
            else:
                output = ""
                self.counts["style_removed"] += 1
                break
        return output

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if self.drop_depth:
            if lower not in VOID_TAGS:
                self.drop_depth += 1
                self.drop_stack.append(lower)
            return
        if lower in DROP_TAGS:
            self.counts[f"removed_{lower}"] += 1
            if lower not in VOID_TAGS:
                self.drop_depth = 1
                self.drop_stack = [lower]
            if lower in {"iframe", "audio", "video"}:
                self.parts.append('<div class="g3b-media-disabled" data-wb-capability="video-playback-disabled">Media playback unavailable offline</div>')
            return
        if lower not in SAFE_TAGS:
            self.counts["unwrapped_tags"] += 1
            if lower not in VOID_TAGS:
                self.open_stack.append((lower, ""))
            return
        cleaned: list[tuple[str, str]] = []
        source_attrs = attrs_dict(attrs)
        if lower == "img":
            source = source_attrs.get("src", "")
            local = self.rewrite_asset(source) if source else None
            if not local:
                escaped = html.escape(normalized_url(urljoin(self.base_url, source)) if source else "missing", quote=True)
                self.parts.append(f'<span class="g3b-asset-unavailable" data-wb-unavailable-source="{escaped}">Image unavailable in this snapshot</span>')
                return
            source_attrs["src"] = local
            source_attrs.pop("srcset", None)
            source_attrs["loading"] = "lazy"
        for name, raw_value in attrs:
            name = name.lower()
            value = raw_value or ""
            if name.startswith("on") or name in {"srcset", "poster", "integrity", "nonce", "crossorigin"}:
                self.counts["removed_attributes"] += 1
                continue
            if name not in SAFE_ATTRS and not name.startswith("data-"):
                continue
            if name == "href":
                value = self.rewrite_href(value)
            elif name == "src":
                value = source_attrs.get("src", value)
            elif name == "style":
                value = self.clean_style(value)
                if not value:
                    continue
            elif name == "action":
                value = self.rewrite_href(value)
            elif name == "target":
                continue
            cleaned.append((name, value))
        if lower == "form":
            method = source_attrs.get("method", "get").lower()
            if method != "get":
                self.counts["blocked_post_forms"] += 1
            cleaned = [(name, value) for name, value in cleaned if name not in {"method", "action"}]
            cleaned.extend((("method", "get"), ("action", "/external-boundary/")))
        # Preserve the original identity for auditing rewritten local edges.
        if lower == "a" and source_attrs.get("href"):
            cleaned.append(("data-wb-source-href", urljoin(self.base_url, source_attrs["href"])))
        rendered = "".join(f' {name}="{html.escape(value, quote=True)}"' for name, value in cleaned)
        self.parts.append(f"<{lower}{rendered}>")
        if lower not in VOID_TAGS:
            self.open_stack.append((lower, lower))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if self.drop_depth:
            self.drop_depth -= 1
            if self.drop_stack:
                self.drop_stack.pop()
            return
        if lower in VOID_TAGS:
            return
        # Pop by the source tag, including unwrapped unsafe elements.  The
        # previous implementation returned early for unsafe end tags and could
        # leave an empty sentinel to corrupt later legal closing tags.
        for index in range(len(self.open_stack) - 1, -1, -1):
            source_tag, output_tag = self.open_stack[index]
            if source_tag == lower:
                trailing = self.open_stack[index:]
                del self.open_stack[index:]
                for _, emitted in reversed(trailing):
                    if emitted:
                        self.parts.append(f"</{emitted}>")
                break

    def handle_data(self, data: str) -> None:
        if not self.drop_depth:
            self.parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self.drop_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.drop_depth:
            self.parts.append(f"&#{name};")

    @property
    def output(self) -> str:
        closing = "".join(
            f"</{emitted}>" for _, emitted in reversed(self.open_stack) if emitted
        )
        return (
            f'<div class="g3b-source-fragment" data-wb-g3b-content="{html.escape(self.route_path, quote=True)}">'
            + "".join(self.parts) + closing + "</div>"
        )


def fetch(client: httpx.Client, url: str, *, max_bytes: int | None = None) -> tuple[httpx.Response, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    last: Exception | None = None
    for attempt in range(1, 4):
        started = now()
        try:
            response = client.get(url)
            content = response.content
            attempts.append({
                "attempt": attempt, "started_at": started, "finished_at": now(),
                "status": response.status_code, "final_url": str(response.url), "bytes": len(content),
            })
            if not same_origin(str(response.url)):
                raise RuntimeError(f"redirect escaped allowed origin: {response.url}")
            if max_bytes is not None and len(content) > max_bytes:
                raise RuntimeError(f"response exceeds {max_bytes} bytes: {len(content)}")
            if response.status_code >= 500:
                raise RuntimeError(f"source HTTP {response.status_code}")
            return response, attempts
        except Exception as exc:
            last = exc
            attempts[-1 if attempts else 0:]
            if attempt < 3:
                time.sleep(0.4 * attempt)
    raise RuntimeError(f"GET failed after 3 attempts: {url}: {last}")


def candidate_asset_urls(fragment: str, base_url: str) -> set[str]:
    class Collector(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.urls: set[str] = set()

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = attrs_dict(attrs)
            if tag.lower() == "img" and values.get("src"):
                self.urls.add(normalized_url(urljoin(base_url, values["src"])))
            for source in re.findall(r"(?is)url\(\s*['\"]?([^'\")\s]+)", values.get("style", "")):
                self.urls.add(normalized_url(urljoin(base_url, source)))

    collector = Collector()
    collector.feed(fragment)
    return collector.urls


def acquire_asset(client: httpx.Client, url: str, source_dir: Path, runtime_dir: Path, batch: int, referenced_by: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not same_origin(url):
        return None, {"url": url, "status": "not-requested-external"}
    try:
        response, attempts = fetch(client, url, max_bytes=MAX_ASSET_BYTES)
    except Exception as exc:
        return None, {"url": url, "status": "fetch-error", "error": str(exc), "attempts": 3}
    mime = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
    if response.status_code != 200:
        return None, {"url": url, "status": "source-http-error", "http_status": response.status_code, "attempts": attempts}
    if not mime.startswith("image/"):
        return None, {"url": url, "status": "not-image", "mime_type": mime, "bytes": len(response.content)}
    content_sha = sha_bytes(response.content)
    suffix = MIME_SUFFIX.get(mime) or mimetypes.guess_extension(mime) or ".bin"
    name = f"{hashlib.sha256(url.encode()).hexdigest()[:16]}-{content_sha}{suffix}"
    source = source_dir / name
    runtime = runtime_dir / name
    source.write_bytes(response.content)
    shutil.copyfile(source, runtime)
    source_info = inspect_asset(source)
    runtime_info = inspect_asset(runtime)
    assert source_info == runtime_info
    assert source.stat().st_ino != runtime.stat().st_ino
    assert not source.is_symlink() and not runtime.is_symlink()
    assert sha_file(source) == sha_file(runtime) == content_sha
    record = {
        "id": f"g3b-{hashlib.sha256(url.encode()).hexdigest()[:12]}-{content_sha[:12]}",
        "priority": "p1", "required": True,
        "source_path": f"source-assets/g3b-content/batch-{batch:02d}/{name}",
        "runtime_path": f"runtime-assets/g3b-content/batch-{batch:02d}/{name}",
        "bytes": len(response.content), "sha256": content_sha, "mime_type": mime,
        "dimensions": source_info["dimensions"], "referenced_by": sorted(set(referenced_by)),
        "evidence_kind": "current-direct", "source_url": url,
        "capture_id": CAPTURE_ID,
    }
    return record, {"url": url, "status": "retained", "asset_id": record["id"], "attempts": attempts}


def ensure_read_path() -> None:
    path = SITE / "scope" / "verify.json"
    payload = load(path)
    read_paths = payload["boot"]["read_paths"]
    if "runtime-content" not in read_paths:
        read_paths.append("runtime-content")
        dump_atomic(path, payload)


def execute(batch: int) -> dict[str, Any]:
    if batch not in range(1, 5):
        raise SystemExit("--batch must be 1..4")
    data_path = CLONE / "site-data.json"
    data = load(data_path)
    ordered = route_order(data)
    selected = ordered[(batch - 1) * BATCH_SIZE:batch * BATCH_SIZE]
    assert len(selected) == BATCH_SIZE

    source_final = SITE / "source-current" / "g3b-content" / f"batch-{batch:02d}"
    runtime_final = SITE / "runtime-content" / "g3b" / f"batch-{batch:02d}"
    source_assets_final = SITE / "source-assets" / "g3b-content" / f"batch-{batch:02d}"
    runtime_assets_final = SITE / "runtime-assets" / "g3b-content" / f"batch-{batch:02d}"
    report_final = source_final / "report.json"
    for destination in (source_final, runtime_final, source_assets_final, runtime_assets_final):
        if destination.exists():
            raise SystemExit(f"immutable batch destination already exists: {destination}")

    stage = Path(tempfile.mkdtemp(prefix=f".g3b-batch-{batch:02d}.", dir=SITE))
    raw_stage = stage / "source" / "raw"
    runtime_stage = stage / "runtime"
    source_asset_stage = stage / "source-assets"
    runtime_asset_stage = stage / "runtime-assets"
    for path in (raw_stage, runtime_stage, source_asset_stage, runtime_asset_stage):
        path.mkdir(parents=True)

    route_map, download_map, asset_map = build_known_maps(data)
    rows: list[dict[str, Any]] = []
    fragments: dict[str, str] = {}
    requested_assets: dict[str, set[str]] = {}
    failures: list[dict[str, str]] = []
    started_at = now()
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_connections=6, max_keepalive_connections=4),
    )
    try:
        for position, route in enumerate(selected, 1):
            path = str(route["path"])
            requested_url = str(route["source_url"])
            name = hashlib.sha256(path.encode()).hexdigest()[:20] + ".html"
            try:
                response, attempts = fetch(client, requested_url)
                raw = response.content
                if response.status_code != int(route["status"]):
                    raise RuntimeError(f"status drift frozen={route['status']} current={response.status_code}")
                fragment, selector, fallback = extract_fragment(raw, str(route["family"]))
                if not fragment:
                    raise RuntimeError("selected content fragment is empty")
                text = visible_text(fragment)
                # Search is a server shell whose content is the frozen search contract.
                if str(route["family"]) != "catalog-search" and len(text) < 20:
                    raise RuntimeError(f"selected content text too short: {len(text)}")
                raw_path = raw_stage / name
                raw_path.write_bytes(raw)
                fragments[path] = fragment
                for asset_url in candidate_asset_urls(fragment, requested_url):
                    requested_assets.setdefault(asset_url, set()).add(path)
                rows.append({
                    "ordinal": (batch - 1) * BATCH_SIZE + position,
                    "path": path, "page_id": route["page_id"], "family": route["family"],
                    "frozen_title": route["title"], "frozen_status": route["status"],
                    "requested_url": requested_url, "final_url": str(response.url),
                    "http_status": response.status_code, "captured_at": attempts[-1]["finished_at"],
                    "attempts": attempts, "raw_path": f"raw/{name}", "raw_bytes": len(raw),
                    "raw_sha256": sha_bytes(raw), "content_selector": selector,
                    "selector_fallback": fallback, "extraction_method": "stdlib-htmlparser-balanced-fragment-v1",
                    "source_visible_text_bytes": len(text.encode()), "source_visible_text_sha256": sha_bytes(text.encode()),
                })
            except Exception as exc:
                failures.append({"path": path, "requested_url": requested_url, "error": str(exc)})
        # Only fetch same-origin image dependencies discovered in the selected body.
        new_asset_records: list[dict[str, Any]] = []
        asset_results: list[dict[str, Any]] = []
        for url in sorted(requested_assets):
            key = normalized_url(url)
            if key in asset_map:
                asset_results.append({"url": key, "status": "already-retained", "local_url": asset_map[key]})
                continue
            record, result = acquire_asset(client, key, source_asset_stage, runtime_asset_stage, batch, sorted(requested_assets[url]))
            asset_results.append(result)
            if record:
                new_asset_records.append(record)
                local = "/g3b-assets/" + Path(str(record["runtime_path"])).name
                asset_map[key] = local
    finally:
        client.close()

    row_by_path = {str(row["path"]): row for row in rows}
    sanitize_totals: Counter[str] = Counter()
    unknown_same_origin: set[str] = set()
    external_asset_refs: set[str] = set()
    for path, fragment in fragments.items():
        row = row_by_path[path]
        sanitizer = Sanitizer(
            base_url=str(row["final_url"]), route_path=path, route_map=route_map,
            download_map=download_map, asset_map=asset_map,
        )
        sanitizer.feed(fragment)
        rendered = sanitizer.output
        rendered_text = visible_text(rendered)
        name = Path(str(row["raw_path"])).name
        runtime = runtime_stage / name
        runtime.write_text(rendered + "\n", encoding="utf-8")
        row.update({
            "runtime_path": f"runtime-content/g3b/batch-{batch:02d}/{name}",
            "runtime_bytes": runtime.stat().st_size,
            "runtime_sha256": sha_file(runtime),
            "runtime_visible_text_bytes": len(rendered_text.encode()),
            "runtime_visible_text_sha256": sha_bytes(rendered_text.encode()),
            "sanitize_rewrite_counts": dict(sorted(sanitizer.counts.items())),
            "unknown_same_origin_asset_references": sorted(sanitizer.unknown_same_origin_assets),
            "external_asset_references_not_requested": sorted(sanitizer.external_assets),
        })
        sanitize_totals.update(sanitizer.counts)
        unknown_same_origin.update(sanitizer.unknown_same_origin_assets)
        external_asset_refs.update(sanitizer.external_assets)

    complete = len(rows) == len(selected) and not failures
    report = {
        "schema_version": "mit-ocw.g3b-content-addendum-batch.v1",
        "capture_id": CAPTURE_ID, "batch_id": f"g3b-content-batch-{batch:02d}",
        "batch_number": batch, "ordering": "representative-first-then-family-path-v1",
        "created_at": now(), "started_at": started_at, "authority": "current-direct-anonymous-same-origin-get",
        "does_not_modify_g1_evidence": True,
        "authoritative_interface_audit": {
            "command": "./.venv/bin/python -m websitebench.workflow.cli acquire-source --help",
            "implementation": "src/websitebench/workflow/acquisition.py",
            "finding": "The authoritative interface retains dom.html and visible-text.txt, but also captures a full-page screenshot and page resources per row.",
            "decision": "Use a narrower content-only GET addendum for 732 frozen URLs to avoid duplicating visual evidence and page-resource capture; preserve exact raw HTML, visible-text hashes, response provenance, and separately hashed sanitized fragments.",
        },
        "request_policy": {"method": "GET", "allowed_origin": ORIGIN, "external_requests": 0, "post_requests": 0, "asset_requests": "same-origin img/style dependencies only"},
        "closure": {"status": "closed" if complete else "incomplete", "expected_routes": len(selected), "captured_routes": len(rows), "failed_routes": len(failures)},
        "counts": {
            "families": dict(sorted(Counter(str(row["family"]) for row in rows).items())),
            "raw_bytes": sum(int(row["raw_bytes"]) for row in rows),
            "runtime_bytes": sum(int(row["runtime_bytes"]) for row in rows),
            "new_assets": len(new_asset_records),
            "new_asset_bytes": sum(int(row["bytes"]) for row in new_asset_records),
            "unknown_same_origin_asset_references": len(unknown_same_origin),
            "external_asset_references_not_requested": len(external_asset_refs),
        },
        "sanitize_rewrite_totals": dict(sorted(sanitize_totals.items())),
        "asset_results": asset_results,
        "unknown_same_origin_asset_references": sorted(unknown_same_origin),
        "external_asset_references_not_requested": sorted(external_asset_refs),
        "failures": failures,
        "routes": rows,
    }
    dump_atomic(stage / "source" / "report.json", report)
    if not complete:
        raise RuntimeError(f"batch {batch} incomplete; staging retained at {stage}: {failures[:3]}")

    # Promote immutable evidence/runtime directories before atomically extending
    # the mutable aggregate indexes.
    for parent in (source_final.parent, runtime_final.parent, source_assets_final.parent, runtime_assets_final.parent):
        parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage / "source", source_final)
    os.replace(stage / "runtime", runtime_final)
    os.replace(stage / "source-assets", source_assets_final)
    os.replace(stage / "runtime-assets", runtime_assets_final)
    stage.rmdir()

    manifest_path = SITE / "source-assets" / "manifest.json"
    manifest = load(manifest_path)
    existing_ids = {item["id"] for item in manifest["assets"]}
    assert not existing_ids.intersection(item["id"] for item in new_asset_records)
    manifest["assets"].extend(new_asset_records)
    dump_atomic(manifest_path, manifest)

    addendum_path = SITE / "source-assets" / "g3b-content-asset-addendum.json"
    addendum = load(addendum_path) if addendum_path.exists() else {
        "schema_version": "mit-ocw.g3b-content-asset-addendum.v1", "capture_id": CAPTURE_ID,
        "authority": "current-direct-anonymous-same-origin-asset-get", "does_not_modify_g1_evidence": True,
        "created_at": now(), "assets": [], "url_map": {}, "unavailable": {},
    }
    addendum["assets"].extend(new_asset_records)
    for item in new_asset_records:
        addendum["url_map"][normalized_url(str(item["source_url"]))] = "/g3b-assets/" + Path(str(item["runtime_path"])).name
    for result in asset_results:
        if result["status"] not in {"retained", "already-retained"}:
            addendum["unavailable"][result["url"]] = result
    addendum["updated_at"] = now()
    dump_atomic(addendum_path, addendum)

    index_path = CLONE / "content-index.json"
    index = load(index_path) if index_path.exists() else {
        "schema_version": "mit-ocw.g3b-content-index.v1", "capture_id": CAPTURE_ID,
        "ordering": "representative-first-then-family-path-v1", "routes": {}, "batches": [],
    }
    assert not set(row_by_path).intersection(index["routes"])
    for row in rows:
        index["routes"][row["path"]] = {
            key: row[key] for key in (
                "path", "page_id", "family", "requested_url", "final_url", "http_status",
                "captured_at", "raw_path", "raw_bytes", "raw_sha256", "content_selector",
                "selector_fallback", "source_visible_text_bytes", "source_visible_text_sha256",
                "runtime_path", "runtime_bytes", "runtime_sha256", "runtime_visible_text_bytes",
                "runtime_visible_text_sha256", "sanitize_rewrite_counts",
            )
        }
        index["routes"][row["path"]]["raw_path"] = (
            f"source-current/g3b-content/batch-{batch:02d}/{row['raw_path']}"
        )
    index["batches"].append({
        "batch_id": report["batch_id"], "report": relative(report_final),
        "routes": len(rows), "raw_bytes": report["counts"]["raw_bytes"],
        "runtime_bytes": report["counts"]["runtime_bytes"], "status": "closed",
    })
    index["updated_at"] = now()
    dump_atomic(index_path, index, compact=True)

    data["phase"] = f"g3b-content-addendum-{len(index['routes'])}-of-{TOTAL_ROUTES}"
    data["g3b_content"] = {
        "status": "partial" if len(index["routes"]) < TOTAL_ROUTES else "closed",
        "index": "content-index.json", "routes": len(index["routes"]),
        "expected_routes": TOTAL_ROUTES, "batches": len(index["batches"]),
        "asset_addendum": "source-assets/g3b-content-asset-addendum.json",
    }
    data["g3b_content_assets"] = {
        Path(str(item["runtime_path"])).name: {
            "runtime_path": item["runtime_path"], "mime_type": item["mime_type"],
            "bytes": item["bytes"], "sha256": item["sha256"],
        } for item in addendum["assets"]
    }
    data["g3b_content_asset_url_map"] = addendum["url_map"]
    dump_atomic(data_path, data, compact=True)
    ensure_read_path()
    return {
        "status": "closed", "batch": batch, "routes": len(rows), "failures": 0,
        "raw_bytes": report["counts"]["raw_bytes"], "runtime_bytes": report["counts"]["runtime_bytes"],
        "new_assets": len(new_asset_records), "new_asset_bytes": report["counts"]["new_asset_bytes"],
        "total_content_routes": len(index["routes"]), "report": relative(report_final),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.batch), indent=2))


if __name__ == "__main__":
    main()
