"""Deterministic, configuration-scoped source acquisition with Playwright."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from websitebench.offline_clone.asset_cache import write_bytes_if_changed
from websitebench.site_compiler.canonical import canonical_json_bytes
from websitebench.site_compiler.schema import load_json_document
from websitebench.viewer.capture import detect_access_gate, detect_soft_error

from .errors import WorkflowError
from .io import relative_path, resolve_relative, write_json

SPEC_SCHEMA = "offline-clone-source-acquisition-spec-v2.schema.json"
REPORT_SCHEMA = "offline-clone-source-acquisition-report-v3.schema.json"
CAPTURE_RESOURCE_TYPES = {"stylesheet", "image", "font", "media"}
CSS_URL = re.compile(r"(?is)url\(\s*['\"]?(?P<url>[^'\")\s]+)")
SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WorkflowError(f"source URL must use http or https: {value}")
    if parsed.username or parsed.password:
        raise WorkflowError(f"source URL cannot contain credentials: {value}")
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    default = (parsed.scheme == "http" and port in {None, 80}) or (
        parsed.scheme == "https" and port in {None, 443}
    )
    authority = hostname if default else f"{hostname}:{port}"
    return f"{parsed.scheme.lower()}://{authority}"


def _normalized_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _row_component(row_id: str) -> str:
    cleaned = SAFE_COMPONENT.sub("-", row_id).strip("-.")[:80] or "row"
    digest = hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned}-{digest}"


def _resource_id(url: str) -> str:
    return f"resource.{hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]}"


def _resource_suffix(content_type: str) -> str:
    media_type = content_type.split(";", 1)[0].strip().lower()
    explicit = {
        "text/css": ".css",
        "image/svg+xml": ".svg",
        "font/woff": ".woff",
        "font/woff2": ".woff2",
    }
    return explicit.get(media_type) or mimetypes.guess_extension(media_type) or ".bin"


def _json_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value)


def _artifact(root: Path, path: Path, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": relative_path(root, path),
        "bytes": path.stat().st_size,
    }


def _write_artifact(path: Path, payload: bytes) -> None:
    if not payload:
        payload = b"\n"
    write_bytes_if_changed(path, payload)


def _assert_destination(root: Path, site_id: str, path: Path, label: str) -> Path:
    resolved = resolve_relative(root, path.as_posix())
    site_root = (root / "materials" / site_id).resolve()
    try:
        resolved.relative_to(site_root)
    except ValueError as exc:
        raise WorkflowError(
            f"{label} must stay inside materials/{site_id}: {path}"
        ) from exc
    return resolved


def _validate_spec(root: Path, spec_path: Path | str) -> tuple[Path, dict[str, Any]]:
    spec_file = resolve_relative(root, Path(spec_path).as_posix(), must_exist=True)
    spec = load_json_document(spec_file, SPEC_SCHEMA)
    allowed = {_origin(value) for value in spec["allowed_origins"]}
    if len(allowed) != len(spec["allowed_origins"]):
        raise WorkflowError("allowed_origins must contain unique canonical origins")
    row_ids: set[str] = set()
    for page in spec["pages"]:
        if page["row_id"] in row_ids:
            raise WorkflowError(f"duplicate acquisition row_id: {page['row_id']}")
        row_ids.add(page["row_id"])
        if _origin(page["url"]) not in allowed:
            raise WorkflowError(
                f"page URL origin is outside allowed_origins: {page['url']}"
            )
    return spec_file, spec


def acquire_source(
    repository_root: Path | str,
    spec_path: Path | str,
    output_dir: Path | str,
    report_path: Path | str,
    *,
    browser_channel: str = "chrome",
    executable_path: str | None = None,
    headed: bool = False,
) -> dict[str, Any]:
    """Execute one immutable, anonymous, GET-only source capture matrix."""

    root = Path(repository_root).resolve()
    spec_file, spec = _validate_spec(root, spec_path)
    site_id = spec["site_id"]
    output = _assert_destination(root, site_id, Path(output_dir), "output directory")
    report_file = _assert_destination(root, site_id, Path(report_path), "report")
    if output.exists():
        raise WorkflowError(f"source acquisition output already exists: {output_dir}")
    if report_file.exists():
        raise WorkflowError(f"source acquisition report already exists: {report_path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    started_at = _now()
    try:
        report = _execute_capture(
            root=root,
            spec_file=spec_file,
            spec=spec,
            staging=staging,
            final_output=output,
            started_at=started_at,
            browser_channel=browser_channel,
            executable_path=executable_path,
            headed=headed,
        )
        os.replace(staging, output)
        write_json(report_file, report, create_only=True)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": report["closure"]["status"],
        "site_id": site_id,
        "capture_id": spec["capture_id"],
        "report": relative_path(root, report_file),
        "output": relative_path(root, output),
        "pages": len(report["pages"]),
        "blockers": report["blockers"],
    }


def _execute_capture(
    *,
    root: Path,
    spec_file: Path,
    spec: dict[str, Any],
    staging: Path,
    final_output: Path,
    started_at: str,
    browser_channel: str,
    executable_path: str | None,
    headed: bool,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise WorkflowError("Playwright is required for source acquisition") from exc

    pages: list[dict[str, Any]] = []
    blockers: list[str] = []
    required_urls: set[str] = set()
    downloaded_urls: set[str] = set()
    referenced_urls: set[str] = set()
    missing_ids: set[str] = set()
    physical_resources: set[str] = set()
    failed_request_count = 0
    broken_resource_count = 0
    unresolved_css: set[str] = set()
    blocked_mutations: list[dict[str, str]] = []
    total_resource_bytes = 0
    allowed_origins = {_origin(value) for value in spec["allowed_origins"]}
    limits = spec["limits"]

    launch: dict[str, Any] = {"headless": not headed}
    browser_environment = os.environ.copy()
    dependency_root = Path.home() / "chromium-libs"
    libraries = dependency_root / "usr" / "lib" / "x86_64-linux-gnu"
    fonts = dependency_root / "etc" / "fonts" / "fonts.conf"
    if libraries.is_dir():
        browser_environment["LD_LIBRARY_PATH"] = str(libraries)
    if fonts.is_file():
        browser_environment["FONTCONFIG_FILE"] = str(fonts)
    launch["env"] = browser_environment
    if executable_path:
        launch["executable_path"] = executable_path
    elif browser_channel:
        launch["channel"] = browser_channel

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch)
        try:
            for page_spec in spec["pages"]:
                context = browser.new_context(
                    viewport={
                        "width": page_spec["viewport"]["width"],
                        "height": page_spec["viewport"]["height"],
                    },
                    service_workers="block",
                    accept_downloads=False,
                )
                response_records: list[Any] = []
                request_records: list[dict[str, Any]] = []
                request_failures: list[dict[str, str]] = []
                page_blocked_mutations: list[dict[str, str]] = []

                def route_request(route: Any, request: Any) -> None:
                    method = request.method.upper()
                    if method != "GET":
                        record = {
                            "method": method,
                            "url": _normalized_url(request.url),
                        }
                        page_blocked_mutations.append(record)
                        blocked_mutations.append(record)
                        route.abort("blockedbyclient")
                        return
                    if _origin(request.url) not in allowed_origins:
                        request_failures.append(
                            {
                                "url": _normalized_url(request.url),
                                "resource_type": request.resource_type,
                                "reason": "origin-not-approved",
                            }
                        )
                        route.abort("blockedbyclient")
                        return
                    route.continue_()

                context.route("**/*", route_request)
                page = context.new_page()
                page.on(
                    "request",
                    lambda request: request_records.append(
                        {
                            "method": request.method,
                            "url": _normalized_url(request.url),
                            "resource_type": request.resource_type,
                        }
                    ),
                )
                page.on("response", lambda response: response_records.append(response))
                page.on(
                    "requestfailed",
                    lambda request: request_failures.append(
                        {
                            "url": _normalized_url(request.url),
                            "resource_type": request.resource_type,
                            "reason": str(request.failure or "request-failed"),
                        }
                    ),
                )
                row_dir = staging / "rows" / _row_component(page_spec["row_id"])
                row_dir.mkdir(parents=True, exist_ok=True)
                artifacts: list[dict[str, Any]] = []
                navigation_error: str | None = None
                status_code: int | None = None
                final_url = page_spec["url"]
                try:
                    navigation = page.goto(
                        page_spec["url"],
                        wait_until=page_spec.get("wait_until", "networkidle"),
                        timeout=limits["navigation_timeout_ms"],
                    )
                    status_code = navigation.status if navigation else None
                    if limits["settle_ms"]:
                        page.wait_for_timeout(limits["settle_ms"])
                    final_url = page.url
                except (PlaywrightError, PlaywrightTimeoutError) as exc:
                    navigation_error = str(exc)[:1000]
                    final_url = page.url or page_spec["url"]

                screenshot_path = row_dir / "screenshot.png"
                screenshot_error: str | None = None
                try:
                    page.screenshot(
                        path=str(screenshot_path),
                        full_page=page_spec.get("full_page", True),
                        animations="disabled",
                    )
                    artifacts.append(_staged_artifact(root, staging, final_output, screenshot_path, "screenshot"))
                except PlaywrightError as exc:
                    screenshot_error = str(exc)[:1000]

                dom = page.content() if not page.is_closed() else ""
                body_text = ""
                title = ""
                heading = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=2000)
                    title = page.title()
                    headings = page.locator("h1").all_inner_texts()
                    heading = headings[0] if headings else ""
                except PlaywrightError:
                    pass
                artifact_payloads = {
                    "dom": ("dom.html", dom.encode("utf-8")),
                    "visible-text": ("visible-text.txt", (body_text + "\n").encode("utf-8")),
                    "geometry": (
                        "geometry.json",
                        _json_bytes(_page_geometry(page)),
                    ),
                    "computed-style": (
                        "computed-style.json",
                        _json_bytes(_page_styles(page)),
                    ),
                }
                for kind, (name, payload) in artifact_payloads.items():
                    path = row_dir / name
                    _write_artifact(path, payload)
                    artifacts.append(_staged_artifact(root, staging, final_output, path, kind))

                page_inventory: list[dict[str, Any]] = []
                css_payloads: list[tuple[str, bytes]] = []
                for response in response_records:
                    resource_type = response.request.resource_type
                    if resource_type not in CAPTURE_RESOURCE_TYPES:
                        continue
                    url = _normalized_url(response.url)
                    required_urls.add(url)
                    referenced_urls.add(url)
                    if response.status >= 400:
                        broken_resource_count += 1
                        missing_ids.add(_resource_id(url))
                        continue
                    try:
                        payload = response.body()
                    except PlaywrightError:
                        missing_ids.add(_resource_id(url))
                        continue
                    content_type = response.headers.get("content-type", "application/octet-stream")
                    if not payload or len(payload) > limits["max_resource_bytes"]:
                        missing_ids.add(_resource_id(url))
                        continue
                    if total_resource_bytes + len(payload) > limits["max_total_resource_bytes"]:
                        missing_ids.add(_resource_id(url))
                        continue
                    digest = hashlib.sha256(payload).hexdigest()
                    resource_path = staging / "resources" / digest[:2] / f"{digest}{_resource_suffix(content_type)}"
                    _write_artifact(resource_path, payload)
                    total_resource_bytes += len(payload)
                    downloaded_urls.add(url)
                    physical_resources.add(digest)
                    page_inventory.append(
                        {
                            "url": url,
                            "resource_type": resource_type,
                            "content_type": content_type,
                            "status": response.status,
                            "path": _staged_relative(root, staging, final_output, resource_path),
                            "bytes": len(payload),
                        }
                    )
                    if resource_type == "stylesheet":
                        css_payloads.append((url, payload))
                for css_url, payload in css_payloads:
                    try:
                        css = payload.decode("utf-8")
                    except UnicodeDecodeError:
                        unresolved_css.add(css_url)
                        continue
                    for match in CSS_URL.finditer(css):
                        target = match.group("url").strip()
                        if target.startswith(("data:", "blob:", "#")):
                            continue
                        resolved = _normalized_url(urljoin(css_url, target))
                        if _origin(resolved) in allowed_origins and resolved not in downloaded_urls:
                            unresolved_css.add(resolved)

                network_path = row_dir / "network.json"
                _write_artifact(
                    network_path,
                    _json_bytes(
                        {
                            "requests": request_records,
                            "failures": request_failures,
                            "blocked_mutations": page_blocked_mutations,
                        }
                    ),
                )
                artifacts.append(_staged_artifact(root, staging, final_output, network_path, "network"))
                inventory_path = row_dir / "resource-inventory.json"
                _write_artifact(inventory_path, _json_bytes({"resources": page_inventory}))
                artifacts.append(_staged_artifact(root, staging, final_output, inventory_path, "resource-inventory"))

                relevant_failures = [
                    item
                    for item in request_failures
                    if item["resource_type"] in CAPTURE_RESOURCE_TYPES
                    and item["reason"] != "origin-not-approved"
                ]
                failed_request_count += len(relevant_failures)
                for item in relevant_failures:
                    missing_ids.add(_resource_id(item["url"]))
                    required_urls.add(item["url"])
                access_gate = detect_access_gate(title, heading, body_text)
                soft_error = detect_soft_error(title, heading)
                if screenshot_error:
                    page_status = "failed"
                elif access_gate or soft_error or (status_code is not None and status_code >= 400):
                    page_status = "blocked"
                elif navigation_error or relevant_failures or page_blocked_mutations:
                    page_status = "source-limited"
                else:
                    page_status = "captured"
                page_blockers = [
                    value
                    for value in (
                        f"{page_spec['row_id']}: {navigation_error}" if navigation_error else None,
                        f"{page_spec['row_id']}: screenshot failed: {screenshot_error}" if screenshot_error else None,
                        f"{page_spec['row_id']}: access gate: {access_gate}" if access_gate else None,
                        f"{page_spec['row_id']}: soft error: {soft_error}" if soft_error else None,
                        f"{page_spec['row_id']}: HTTP {status_code}" if status_code is not None and status_code >= 400 else None,
                        f"{page_spec['row_id']}: browser attempted {len(page_blocked_mutations)} non-GET request(s)" if page_blocked_mutations else None,
                    )
                    if value
                ]
                blockers.extend(page_blockers)
                pages.append(
                    {
                        "row_id": page_spec["row_id"],
                        "priority": page_spec["priority"],
                        "requested_url": page_spec["url"],
                        "final_url": final_url,
                        "status": page_status,
                        "viewports": [page_spec["viewport"]["name"]],
                        "artifacts": artifacts,
                    }
                )
                context.close()
        finally:
            browser.close()

    incomplete = [
        page["row_id"]
        for page in pages
        if page["priority"] in {"p0", "p1"} and page["status"] != "captured"
    ]
    if incomplete:
        blockers.append("incomplete P0/P1 source rows: " + ", ".join(incomplete))
    if missing_ids:
        blockers.append(f"missing required source resources: {len(missing_ids)}")
    if unresolved_css:
        blockers.append(f"unresolved CSS resource references: {len(unresolved_css)}")
    blockers = list(dict.fromkeys(value[:2000] for value in blockers))
    complete = not blockers and not missing_ids
    report = {
        "schema_version": "offline-clone.source-acquisition-report.v3",
        "site_id": spec["site_id"],
        "capture_id": spec["capture_id"],
        "capture_provider": "playwright-chrome",
        "source_scope": {
            "path": relative_path(root, spec_file),
            "bytes": spec_file.stat().st_size,
        },
        "started_at": started_at,
        "finished_at": _now(),
        "safety": {
            "methods": ["GET"],
            "anonymous": True,
            "mutations_performed": False,
            "bypass_attempted": False,
            "isolated_context_per_page": True,
        },
        "concurrency": {
            "global_download_jobs": 1,
            "per_origin_download_jobs": 1,
            "per_origin_page_jobs": 1,
            "adaptive_backoff": False,
        },
        "pages": pages,
        "resources": {
            "logical_required": len(required_urls),
            "downloaded": len(downloaded_urls),
            "verified": len(downloaded_urls),
            "referenced": len(referenced_urls),
            "browser_requested": len(required_urls),
            "physical_file_count": len(physical_resources),
            "missing_required_ids": sorted(missing_ids),
        },
        "closure": {
            "status": "complete" if complete else "blocked",
            "failed_request_count": failed_request_count,
            "broken_resource_count": broken_resource_count,
            "unresolved_css_reference_count": len(unresolved_css),
            "blocked_mutation_request_count": len(blocked_mutations),
        },
        "blockers": blockers,
    }
    load_json_document_value = _validate_generated_report(report)
    assert load_json_document_value["site_id"] == spec["site_id"]
    return report


def _staged_relative(root: Path, staging: Path, final: Path, path: Path) -> str:
    return relative_path(root, final / path.relative_to(staging))


def _staged_artifact(
    root: Path,
    staging: Path,
    final: Path,
    path: Path,
    kind: str,
) -> dict[str, Any]:
    value = _artifact(staging, path, kind)
    value["path"] = _staged_relative(root, staging, final, path)
    return value


def _validate_generated_report(value: dict[str, Any]) -> dict[str, Any]:
    temporary_root = Path(tempfile.mkdtemp(prefix="clawbench-acquisition-report-"))
    try:
        path = temporary_root / "report.json"
        path.write_bytes(canonical_json_bytes(value))
        return load_json_document(path, REPORT_SCHEMA)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _page_geometry(page: Any) -> list[dict[str, Any]]:
    if page.is_closed():
        return []
    try:
        return page.evaluate(
            """() => Array.from(document.querySelectorAll('body *')).slice(0, 500)
              .map((node) => {
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                if (rect.width <= 0 || rect.height <= 0 || style.visibility === 'hidden') return null;
                return {
                  tag: node.tagName.toLowerCase(),
                  role: node.getAttribute('role'),
                  text: (node.innerText || '').trim().slice(0, 240),
                  x: Math.round(rect.x * 100) / 100,
                  y: Math.round(rect.y * 100) / 100,
                  width: Math.round(rect.width * 100) / 100,
                  height: Math.round(rect.height * 100) / 100
                };
              }).filter(Boolean)"""
        )
    except Exception:
        return []


def _page_styles(page: Any) -> list[dict[str, Any]]:
    if page.is_closed():
        return []
    try:
        return page.evaluate(
            """() => Array.from(document.querySelectorAll('body, body *')).slice(0, 300)
              .map((node) => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0 || style.visibility === 'hidden') return null;
                return {
                  tag: node.tagName.toLowerCase(),
                  role: node.getAttribute('role'),
                  color: style.color,
                  backgroundColor: style.backgroundColor,
                  fontFamily: style.fontFamily,
                  fontSize: style.fontSize,
                  fontWeight: style.fontWeight,
                  lineHeight: style.lineHeight,
                  display: style.display,
                  position: style.position
                };
              }).filter(Boolean)"""
        )
    except Exception:
        return []
