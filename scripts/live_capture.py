"""Anonymous read-only live-site capture engine for offline clone evidence.

Usage:
    python scripts/live_capture.py \
      --plan materials/<site>/source-capture/capture-plan.json \
      --provider auto --stability-runs 3 --jobs 3

Connected Chrome MCP sessions export a provider-neutral run and pass it with
`--provider chrome-mcp --import-provider-run <run.json>`. Without such an
export, `auto` uses Playwright. Both paths preserve the same downstream report
contract.

The plan file schema (clawbench.live-capture-plan.v1):
{
  "schema_version": "clawbench.live-capture-plan.v1",
  "site_id": "edx",
  "output_root": "materials/edx/source-current/2026-07-25",
  "viewports": [{"width":1440,"height":900},{"width":1024,"height":768},{"width":390,"height":844}],
  "pages": [
    {"id": "home", "url": "https://www.edx.org/", "wait_ms": 4000,
     "full_page": true, "scroll_pass": true}
  ]
}

Safety: read-only navigation only. Plans may narrowly allow named GraphQL
queries or exact origin/path POST endpoints that are documented as read-only.
No form submission, credential entry, or mutation is performed. Captures
screenshots, final URLs, redirect chains, visible text, and asset/network
inventory per page. Failures (bot walls, timeouts) are recorded honestly
instead of being retried into distortion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
BLOCK_MARKERS = (
    "access denied",
    "verify you are a human",
    "are you a robot",
    "request blocked",
    "pardon our interruption",
    "px-captcha",
    "datadome",
    "attention required",
    "just a moment",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_page(
    context: Any,
    page_plan: dict[str, Any],
    viewports: list[dict[str, int]],
    out_dir: Path,
    site_id: str,
    approved_origins: set[str],
    approved_read_post_operations: set[str],
    approved_read_post_paths: dict[str, set[str]],
    stability_runs: int = 1,
) -> dict[str, Any]:
    page_id = page_plan["id"]
    url = page_plan["url"]
    wait_ms = int(page_plan.get("wait_ms", 4500))
    full_page = bool(page_plan.get("full_page", True))
    scroll_pass = bool(page_plan.get("scroll_pass", True))
    record: dict[str, Any] = {
        "id": page_id,
        "requested_url": url,
        "status": "pending",
        "viewport_captures": [],
        "network": [],
        "assets": {},
    }
    network_log: list[dict[str, Any]] = []
    blocked_requests: list[dict[str, str]] = []
    allowed_read_posts: list[dict[str, str]] = []
    page = context.new_page()

    def route_request(route: Any) -> None:
        request = route.request
        method = request.method.upper()
        parsed = urlsplit(request.url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        reason = ""
        operations = [
            operation
            for operation in parse_qs(parsed.query).get("op", [])
            if operation
        ]
        graphql_read_post = (
            method == "POST"
            and origin in approved_origins
            and parsed.path in {"/api-proxy/graphql", "/api-proxy/graphql/session"}
            and bool(operations)
            and set(operations).issubset(approved_read_post_operations)
        )
        path_read_post = (
            method == "POST"
            and origin in approved_origins
            and parsed.path in approved_read_post_paths.get(origin, set())
        )
        read_post = graphql_read_post or path_read_post
        if method not in {"GET", "HEAD"} and not read_post:
            reason = "non-read-operation"
        elif parsed.scheme in {"http", "https"} and origin not in approved_origins:
            reason = "unapproved-origin"
        if reason:
            if len(blocked_requests) < 200:
                blocked_requests.append(
                    {
                        "method": method,
                        "origin": origin,
                        "url": request.url[:500],
                        "resource_type": request.resource_type,
                        "reason": reason,
                    }
                )
            route.abort("blockedbyclient")
            return
        if read_post and len(allowed_read_posts) < 100:
            allowed_read_posts.append(
                {
                    "method": method,
                    "origin": origin,
                    "operation": (
                        ",".join(operations)
                        if graphql_read_post
                        else f"path:{parsed.path}"
                    ),
                    "url": request.url[:500],
                }
            )
        route.continue_()

    page.route("**/*", route_request)

    def on_response(response: Any) -> None:
        try:
            entry = {
                "url": response.url[:500],
                "status": response.status,
                "resource_type": response.request.resource_type,
                "content_type": (response.headers or {}).get("content-type", ""),
            }
            network_log.append(entry)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        primary = viewports[0]
        page.set_viewport_size(primary)
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(wait_ms)
        if scroll_pass:
            for _ in range(6):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(450)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(800)
        final_url = page.url
        title = page.title()
        body_text = page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 120000)"
        )
        lowered_title = title.lower()
        lowered_head = body_text[:4000].lower()
        marker_hit = any(
            marker in lowered_head or marker in lowered_title
            for marker in BLOCK_MARKERS
        )
        blocked = marker_hit and (
            len(body_text.strip()) < 2500
            or "just a moment" in lowered_title
            or "access denied" in lowered_title
            or "attention required" in lowered_title
        )
        http_status = response.status if response else None
        record.update(
            {
                "final_url": final_url,
                "title": title,
                "http_status": http_status,
                "blocked_marker_detected": blocked,
                "observed_state": (
                    "source-error"
                    if "server is misbehaving" in lowered_head
                    else "not-found"
                    if "page not found" in lowered_head
                    else "empty"
                    if "no search results" in lowered_head
                    else "default"
                ),
            }
        )
        text_path = out_dir / "browser" / f"{page_id}-visible-text.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(body_text, encoding="utf-8")
        record["visible_text_artifact"] = {
            "path": str(text_path.relative_to(out_dir)),
            "sha256": sha256_file(text_path),
            "bytes": text_path.stat().st_size,
        }
        assets = page.evaluate(
            """() => {
  const grab = (nodes, attr) => Array.from(nodes)
    .map((n) => n[attr] || n.getAttribute(attr) || '')
    .filter(Boolean);
  const imgs = grab(document.querySelectorAll('img'), 'currentSrc')
    .concat(grab(document.querySelectorAll('img'), 'src'));
  const css = grab(
    document.querySelectorAll('link[rel="stylesheet"]'), 'href');
  const icons = grab(
    document.querySelectorAll('link[rel~="icon"]'), 'href');
  const preloadFonts = Array.from(
    document.querySelectorAll('link[rel="preload"][as="font"]'))
    .map((n) => n.href).filter(Boolean);
  const scripts = grab(document.querySelectorAll('script[src]'), 'src');
  const videoPosters = grab(document.querySelectorAll('video[poster]'), 'poster');
  const media = grab(document.querySelectorAll('video source, audio source'), 'src');
  const bg = [];
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el).backgroundImage;
    if (s && s.includes('url(')) {
      const m = s.match(/url\\("?([^\\)"]+)"?\\)/);
      if (m && m[1] && !m[1].startsWith('data:')) bg.push(m[1]);
    }
    if (bg.length > 400) break;
  }
  const fonts = new Set();
  for (const f of document.fonts) {
    fonts.add(f.family + ' | ' + f.style + ' ' + f.weight + ' ' + f.status);
  }
  return {
    images: Array.from(new Set(imgs)).slice(0, 400),
    stylesheets: Array.from(new Set(css)).slice(0, 80),
    icons: Array.from(new Set(icons)).slice(0, 20),
    preload_fonts: Array.from(new Set(preloadFonts)).slice(0, 40),
    scripts: Array.from(new Set(scripts)).slice(0, 200),
    video_posters: Array.from(new Set(videoPosters)).slice(0, 100),
    media: Array.from(new Set(media)).slice(0, 100),
    background_images: Array.from(new Set(bg)).slice(0, 400),
    document_fonts: Array.from(fonts).slice(0, 60),
  };
}"""
        )
        record["assets"] = assets
        try:
            page.add_style_tag(
                content=(
                    "*,*::before,*::after{animation-duration:0s!important;"
                    "animation-delay:0s!important;transition:none!important;"
                    "caret-color:transparent!important}"
                )
            )
            record["stabilization_style"] = "applied"
        except Exception as error:  # noqa: BLE001
            record["stabilization_style"] = "blocked-by-page-csp"
            record["stabilization_style_error"] = str(error)[:300]
        page.evaluate("() => document.fonts && document.fonts.ready")
        dom_snapshot = page.evaluate(
            "() => document.documentElement.outerHTML.slice(0, 2000000)"
        )
        dom_path = out_dir / "browser" / f"{page_id}-dom.html"
        dom_path.write_text(dom_snapshot, encoding="utf-8")
        record["dom_artifact"] = {
            "path": str(dom_path.relative_to(out_dir)),
            "sha256": sha256_file(dom_path),
            "bytes": dom_path.stat().st_size,
        }
        geometry = page.evaluate(
            """() => Array.from(document.querySelectorAll('*'))
  .filter((el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden';
  })
  .slice(0, 2500)
  .map((el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      classes: Array.from(el.classList).slice(0, 8),
      role: el.getAttribute('role'),
      aria_label: el.getAttribute('aria-label'),
      text: (el.innerText || '').trim().slice(0, 180),
      rect: {
        x: Math.round(r.x), y: Math.round(r.y),
        width: Math.round(r.width), height: Math.round(r.height)
      },
      style: {
        display: s.display, position: s.position, color: s.color,
        backgroundColor: s.backgroundColor, fontFamily: s.fontFamily,
        fontSize: s.fontSize, fontWeight: s.fontWeight,
        lineHeight: s.lineHeight, letterSpacing: s.letterSpacing,
        borderRadius: s.borderRadius, boxShadow: s.boxShadow,
        gap: s.gap, padding: s.padding, margin: s.margin
      }
    };
  })"""
        )
        geometry_path = out_dir / "browser" / f"{page_id}-geometry.json"
        geometry_path.write_text(
            json.dumps(geometry, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        record["geometry_artifact"] = {
            "path": str(geometry_path.relative_to(out_dir)),
            "sha256": sha256_file(geometry_path),
            "bytes": geometry_path.stat().st_size,
        }
        record["viewport_layout_artifacts"] = []
        for viewport in viewports:
            page.set_viewport_size(viewport)
            page.wait_for_timeout(1200)
            viewport_layout = page.evaluate(
                r"""() => {
  const nameFor = (el) => {
    const labelledBy = el.getAttribute('aria-labelledby');
    const labelled = labelledBy
      ? labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ')
      : '';
    return (el.getAttribute('aria-label') || labelled || el.getAttribute('alt') ||
      el.getAttribute('title') || el.getAttribute('placeholder') || el.innerText || '')
      .replace(/\s+/g, ' ').trim().slice(0, 240);
  };
  return Array.from(document.querySelectorAll(
    'header,nav,main,aside,footer,section,article,form,dialog,' +
    'h1,h2,h3,a,button,input,select,textarea,[role],[aria-label]'))
    .filter((el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    })
    .slice(0, 1600)
    .map((el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return {
        tag: el.tagName.toLowerCase(), id: el.id || null,
        role: el.getAttribute('role'), accessible_name: nameFor(el),
        classes: Array.from(el.classList).slice(0, 8),
        rect: {x: Math.round(r.x), y: Math.round(r.y),
          width: Math.round(r.width), height: Math.round(r.height)},
        style: {display: s.display, position: s.position, color: s.color,
          backgroundColor: s.backgroundColor, fontFamily: s.fontFamily,
          fontSize: s.fontSize, fontWeight: s.fontWeight, lineHeight: s.lineHeight,
          letterSpacing: s.letterSpacing, border: s.border, borderRadius: s.borderRadius,
          boxShadow: s.boxShadow, gap: s.gap, padding: s.padding, margin: s.margin},
        states: {disabled: Boolean(el.disabled), checked: Boolean(el.checked),
          expanded: el.getAttribute('aria-expanded'), selected: el.getAttribute('aria-selected')}
      };
    });
}"""
            )
            layout_name = (
                f"{page_id}-{viewport['width']}x{viewport['height']}-layout.json"
            )
            layout_path = out_dir / "browser" / layout_name
            layout_path.write_text(
                json.dumps(viewport_layout, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            record["viewport_layout_artifacts"].append(
                {
                    "viewport": viewport,
                    "path": str(layout_path.relative_to(out_dir)),
                    "sha256": sha256_file(layout_path),
                    "bytes": layout_path.stat().st_size,
                }
            )
            for stability_run in range(1, stability_runs + 1):
                suffix = "" if stability_runs == 1 else f"-source-{stability_run}"
                name = (
                    f"{page_id}-{viewport['width']}x{viewport['height']}"
                    f"{suffix}.png"
                )
                shot_path = out_dir / "browser" / name
                try:
                    page.screenshot(
                        path=str(shot_path),
                        full_page=full_page and viewport["width"] >= 1024,
                        timeout=30000,
                    )
                except Exception as error:  # noqa: BLE001
                    record["viewport_captures"].append(
                        {
                            "viewport": viewport,
                            "stability_run": stability_run,
                            "status": "failed",
                            "error": str(error)[:300],
                        }
                    )
                    continue
                record["viewport_captures"].append(
                    {
                        "viewport": viewport,
                        "stability_run": stability_run,
                        "path": str(shot_path.relative_to(out_dir)),
                        "sha256": sha256_file(shot_path),
                        "bytes": shot_path.stat().st_size,
                        "full_page": full_page and viewport["width"] >= 1024,
                        "status": "captured",
                    }
                )
                if stability_run < stability_runs:
                    page.wait_for_timeout(350)
        font_responses = [
            entry
            for entry in network_log
            if entry["resource_type"] == "font"
            or "font" in (entry["content_type"] or "")
        ]
        record["font_responses"] = font_responses[:60]
        record["network_summary"] = {
            "total_responses": len(network_log),
            "by_type": {},
        }
        record["request_policy"] = {
            "approved_origins": sorted(approved_origins),
            "allowed_methods": [
                "GET",
                "HEAD",
                "POST(explicit read-only query allowlist only)",
            ],
            "approved_read_post_operations": sorted(approved_read_post_operations),
            "approved_read_post_paths": {
                origin: sorted(paths)
                for origin, paths in sorted(approved_read_post_paths.items())
            },
            "allowed_read_post_count": len(allowed_read_posts),
            "allowed_read_post_samples": allowed_read_posts,
            "blocked_count": len(blocked_requests),
            "blocked_samples": blocked_requests,
        }
        for entry in network_log:
            kind = entry["resource_type"]
            record["network_summary"]["by_type"][kind] = (
                record["network_summary"]["by_type"].get(kind, 0) + 1
            )
        net_path = out_dir / "network" / f"{page_id}-responses.json"
        net_path.parent.mkdir(parents=True, exist_ok=True)
        net_path.write_text(
            json.dumps(network_log, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        record["network_artifact"] = str(net_path.relative_to(out_dir))
        record["status"] = "blocked" if blocked else "captured"
    except PWTimeout as error:
        record["status"] = "timeout"
        record["error"] = str(error)[:300]
    except Exception as error:  # noqa: BLE001
        record["status"] = "failed"
        record["error"] = str(error)[:300]
    finally:
        page.close()
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--only", default="", help="comma separated page ids")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="launch a headed browser (helps pass anti-bot interstitials)",
    )
    parser.add_argument(
        "--challenge-wait-ms",
        type=int,
        default=0,
        help="extra wait before capture to let bot checks settle",
    )
    parser.add_argument(
        "--channel",
        default="",
        help="browser channel, e.g. chrome or msedge (real browser build)",
    )
    parser.add_argument(
        "--profile-dir",
        default="",
        help="persistent user-data dir (implies persistent context)",
    )
    parser.add_argument(
        "--engine",
        default="chromium",
        choices=["chromium", "firefox"],
        help="playwright browser engine",
    )
    parser.add_argument(
        "--provider",
        choices=["auto", "playwright", "chrome-mcp"],
        default="auto",
        help="capture provider; auto imports Chrome MCP output when supplied, otherwise Playwright",
    )
    parser.add_argument(
        "--import-provider-run",
        type=Path,
        help="provider-neutral Chrome MCP run JSON whose artifacts already live under output_root",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="parallel Playwright page jobs (1-3; persistent profiles require 1)",
    )
    parser.add_argument(
        "--stability-runs",
        type=int,
        default=1,
        choices=[1, 3],
        help="capture one frame or the three source-stability frames required by v3",
    )
    args = parser.parse_args()
    if not 1 <= args.jobs <= 3:
        parser.error("--jobs must be between 1 and 3")
    if args.profile_dir and args.jobs != 1:
        parser.error("--profile-dir requires --jobs 1")
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    approved_origins = {
        str(origin).rstrip("/") for origin in plan.get("approved_origins", [])
    }
    if not approved_origins:
        approved_origins = {
            f"{urlsplit(page['url']).scheme}://{urlsplit(page['url']).netloc}"
            for page in plan["pages"]
        }
    approved_read_post_operations = {
        str(operation)
        for operation in plan.get("approved_read_post_operations", [])
    }
    approved_read_post_paths = {
        str(origin).rstrip("/"): {str(path) for path in paths}
        for origin, paths in plan.get("approved_read_post_paths", {}).items()
    }
    for origin, paths in approved_read_post_paths.items():
        if origin not in approved_origins:
            parser.error(
                f"read-only POST path allowlist uses unapproved origin {origin}"
            )
        for path in paths:
            if not path.startswith("/") or "?" in path or "#" in path:
                parser.error(
                    "read-only POST path allowlist entries must be exact URL "
                    f"paths without query or fragment: {origin}{path}"
                )
    for page_plan in plan["pages"]:
        parsed = urlsplit(page_plan["url"])
        page_origin = f"{parsed.scheme}://{parsed.netloc}"
        if page_origin not in approved_origins:
            parser.error(
                f"page {page_plan['id']} uses unapproved origin {page_origin}"
            )
    out_dir = Path(plan["output_root"])
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = (
        "chrome-mcp"
        if args.provider == "auto" and args.import_provider_run
        else ("playwright" if args.provider == "auto" else args.provider)
    )
    if provider == "chrome-mcp":
        if args.import_provider_run is None:
            parser.error(
                "--provider chrome-mcp requires --import-provider-run; "
                "the connected agent must export the provider-neutral run"
            )
        imported = json.loads(
            args.import_provider_run.read_text(encoding="utf-8")
        )
        if imported.get("site_id") != plan["site_id"]:
            parser.error("imported provider run site_id does not match plan")
        imported["provider"] = "chrome-mcp"
        imported["plan_path"] = str(plan_path)
        imported["mutations_performed"] = False
        imported["methods"] = ["GET"]
        run_path = out_dir / "capture-run.json"
        run_path.write_text(
            json.dumps(imported, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "site_id": plan["site_id"],
                    "provider": "chrome-mcp",
                    "output": str(run_path),
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    only = {item for item in args.only.split(",") if item}
    pages = [
        page
        for page in plan["pages"]
        if not only or page["id"] in only
    ]
    if args.challenge_wait_ms:
        for page_plan in pages:
            page_plan["wait_ms"] = (
                int(page_plan.get("wait_ms", 4500)) + args.challenge_wait_ms
            )
    started = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []

    def capture_with_new_context(page_plan: dict[str, Any]) -> dict[str, Any]:
        with sync_playwright() as worker_pw:
            worker_engine = (
                worker_pw.firefox
                if args.engine == "firefox"
                else worker_pw.chromium
            )
            worker_launch = dict(launch_kwargs)
            worker_browser = worker_engine.launch(**worker_launch)
            worker_context_kwargs = dict(context_kwargs)
            worker_context = worker_browser.new_context(**worker_context_kwargs)
            if args.engine == "chromium":
                worker_context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver',"
                    " {get: () => undefined})"
                )
            try:
                return capture_page(
                    worker_context,
                    page_plan,
                    plan["viewports"],
                    out_dir,
                    plan["site_id"],
                    approved_origins,
                    approved_read_post_operations,
                    approved_read_post_paths,
                    args.stability_runs,
                )
            finally:
                worker_context.close()
                worker_browser.close()

    with sync_playwright() as pw:
        engine_type = pw.firefox if args.engine == "firefox" else pw.chromium
        launch_kwargs: dict[str, Any] = {
            "headless": not args.headed,
        }
        if args.engine == "chromium":
            launch_kwargs["args"] = [
                "--disable-blink-features=AutomationControlled",
                "--lang=en-US",
                "--no-sandbox",
            ]
        if args.channel:
            launch_kwargs["channel"] = args.channel
        elif args.engine == "chromium":
            executable = shutil.which("chromium") or shutil.which(
                "chromium-browser"
            )
            if executable:
                launch_kwargs["executable_path"] = executable
        browser = None
        context_kwargs: dict[str, Any] = {
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "viewport": plan["viewports"][0],
            "device_scale_factor": 1,
        }
        if args.engine == "chromium":
            context_kwargs["user_agent"] = UA
        if args.jobs > 1:
            with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                results = list(executor.map(capture_with_new_context, pages))
            context = None
        elif args.profile_dir:
            context = engine_type.launch_persistent_context(
                args.profile_dir,
                locale="en-US",
                timezone_id="America/New_York",
                viewport=plan["viewports"][0],
                device_scale_factor=1,
                **launch_kwargs,
            )
        else:
            browser = engine_type.launch(**launch_kwargs)
            context = browser.new_context(**context_kwargs)
            if args.engine == "chromium":
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver',"
                    " {get: () => undefined})"
                )
        if context is not None:
            for page_plan in pages:
                print(
                    f"[{plan['site_id']}] capturing {page_plan['id']} ...",
                    flush=True,
                )
                results.append(
                    capture_page(
                        context,
                        page_plan,
                        plan["viewports"],
                        out_dir,
                        plan["site_id"],
                        approved_origins,
                        approved_read_post_operations,
                        approved_read_post_paths,
                        args.stability_runs,
                    )
                )
                time.sleep(1.0)
            context.close()
        if browser is not None:
            browser.close()
    engine = f"playwright-{args.engine}"
    if args.channel:
        engine = f"playwright-{args.channel}"
    if args.headed:
        engine += "-headed"
    if args.profile_dir:
        engine += "-persistent"
    report = {
        "schema_version": "clawbench.live-capture-run.v1",
        "site_id": plan["site_id"],
        "plan_path": str(plan_path),
        "engine": engine,
        "provider": "playwright",
        "user_agent": UA if not args.channel else f"channel:{args.channel}",
        "locale": "en-US",
        "timezone": "America/New_York",
        "methods": [
            "GET",
            "HEAD",
            "POST(explicit read-only query allowlist only)",
        ],
        "mutations_performed": False,
        "stability_runs": args.stability_runs,
        "page_jobs": args.jobs,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pages": results,
    }
    existing = []
    run_path = out_dir / "capture-run.json"
    if run_path.exists():
        try:
            previous = json.loads(run_path.read_text(encoding="utf-8"))
            existing = previous.get("previous_runs", [])
            previous.pop("previous_runs", None)
            existing.append(previous)
        except Exception:
            existing = []
    report["previous_runs"] = existing[-4:]
    run_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(
        {
            "site_id": plan["site_id"],
            "pages": {
                page["id"]: page["status"] for page in results
            },
            "output": str(run_path),
        },
        ensure_ascii=False,
        indent=1,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
