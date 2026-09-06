"""Create-only, network-isolated G4 interaction evidence for the MIT OCW clone."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from playwright.sync_api import Browser, BrowserContext, Locator, Page, sync_playwright


SITE = Path(__file__).resolve().parents[1]
CLONE = SITE / "clone"
SCOPE = SITE / "scope"
REPO = SITE.parents[1]
CONTROL_CONTRACT = SCOPE / "business-contracts" / "interaction-api-contract.json"
CONTROL_INVENTORY = SCOPE / "all-controls-inventory.json"
COMPONENT_MATRIX = SCOPE / "component-state-matrix.json"
CHECKPOINTS = SCOPE / "checkpoints.json"
ARCHIVE_SHA256 = "7ce95a304a80b42f542d2945d8a3d883ad2b27d6a6ebb4c2cde4a886071bbac0"
ARCHIVE_BYTES = 173_887_153
PDF_SHA256 = "37fe0c54b508899a9d02de86a9605aa95cfa353bf3b066afca3b070009a44d56"
PDF_BYTES = 173_890
COURSE_ROOT = "/courses/6-006-introduction-to-algorithms-fall-2011/"
VIDEO_PATH = (
    "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
    "resources/mit14_129s25_lec01_1080p_mp4/"
)
NEWSLETTER_DESTINATION = (
    "https://mit.us6.list-manage.com/subscribe/post?"
    "u=ad81d725159c1f322a0c54837&id=4c04dfddc5&f_id=00e734e1f0"
)
DOWNLOAD_PATHS = {
    COURSE_ROOT + "6.006-fall-2011.zip",
    COURSE_ROOT + "dcc62658425ffabc1dc93e9940589a66_MIT6_006F11_ps1.pdf",
}

JOURNEY_PROOFS = [
    {
        "journey_id": "home-discovery",
        "proofs": [
            "global-search-submit",
            "featured-next",
            "featured-previous",
            "new-next",
            "new-previous",
            "stories-next",
            "stories-previous",
            "home-denominator",
            "navigation-recovery",
        ],
    },
    {
        "journey_id": "catalog-state-recovery",
        "proofs": [
            "catalog-query",
            "catalog-course-tab",
            "catalog-resource-tab",
            "catalog-clear-all",
            "catalog-math-filter",
            "catalog-undergraduate-filter",
            "catalog-sort",
            "catalog-load-more",
            "catalog-retry",
            "catalog-empty-clear",
            "navigation-recovery",
        ],
    },
    {
        "journey_id": "course-material-navigation",
        "proofs": ["course-menu", "resource-download", "route-identity-closure"],
    },
    {
        "journey_id": "download-closure",
        "proofs": ["course-download", "resource-download"],
    },
    {
        "journey_id": "collection-story-information",
        "proofs": ["home-denominator", "route-identity-closure"],
    },
    {
        "journey_id": "newsletter-boundary",
        "proofs": ["newsletter-email", "newsletter-submit"],
    },
    {"journey_id": "video-disabled", "proofs": ["video-play"]},
    {
        "journey_id": "navigation-boundaries",
        "proofs": [
            "external-return",
            "data-boundary-return",
            "home-denominator",
            "navigation-boundary-statuses",
        ],
    },
    {"journey_id": "route-identity-closure", "proofs": ["route-identity-closure"]},
    {
        "journey_id": "presentation-asset-closure",
        "proofs": ["presentation-asset-closure"],
    },
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def failed_stage(stage: str, error: Exception) -> dict[str, Any]:
    return {"stage": stage, "status": "fail", "error": repr(error), "events": {}}


def derive_journey_results(proof_status: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for definition in JOURNEY_PROOFS:
        proofs = definition["proofs"]
        observed = {proof: proof_status.get(proof, "not-executed-with-reason") for proof in proofs}
        if any(status == "fail" for status in observed.values()):
            status = "fail"
        elif any(status != "pass" for status in observed.values()):
            status = "not-executed-with-reason"
        else:
            status = "pass"
        result = {
            "journey_id": definition["journey_id"],
            "status": status,
            "proofs": proofs,
            "proof_status": observed,
        }
        result["fingerprint"] = stable_sha(result)
        results.append(result)
    return results


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def start_server(port: int) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=CLONE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"candidate server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(origin + "/healthz", timeout=0.5) as response:
                if response.status == 200:
                    return process
        except OSError:
            time.sleep(0.1)
    stop_server(process)
    raise RuntimeError("candidate server did not become ready")


def stop_server(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)


def relative_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def snapshot(locator: Locator) -> dict[str, Any] | None:
    if locator.count() == 0:
        return None
    target = locator.first
    payload = target.evaluate(
        """el => ({
          tag: el.tagName.toLowerCase(),
          text: (el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 240),
          attrs: Object.fromEntries(Array.from(el.attributes).map(a => [a.name, a.value])),
          disabled: Boolean(el.disabled), checked: Boolean(el.checked), value: el.value || '',
          focused: document.activeElement === el,
          rect: (() => { const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; })()
        })"""
    )
    payload["visible"] = target.is_visible()
    payload["enabled"] = target.is_enabled()
    return payload


def page_identity(page: Page) -> dict[str, str]:
    return {
        "url": relative_url(page.url),
        "title": page.title(),
        "page_id": page.locator("main").get_attribute("data-wb-page-id") or "",
        "route_family": page.locator("main").get_attribute("data-wb-route-family") or "",
    }


def new_context(browser: Browser, origin: str) -> tuple[BrowserContext, dict[str, list[Any]]]:
    events: dict[str, list[Any]] = {
        "remote_requests": [],
        "local_404": [],
        "failed_requests": [],
        "console_errors": [],
        "page_errors": [],
    }
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        device_scale_factor=1,
        color_scheme="light",
        reduced_motion="reduce",
        locale="en-US",
        timezone_id="America/Toronto",
        accept_downloads=True,
    )

    def isolate(route: Any) -> None:
        parsed = urlparse(route.request.url)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            route.continue_()
        elif parsed.scheme == "data":
            route.continue_()
        else:
            events["remote_requests"].append(route.request.url)
            route.abort("blockedbyclient")

    context.route("**/*", isolate)
    context.on(
        "response",
        lambda response: events["local_404"].append(relative_url(response.url))
        if urlparse(response.url).hostname in {"127.0.0.1", "localhost"} and response.status == 404
        else None,
    )
    def request_failed(request: Any) -> None:
        # Chromium reports an attachment response that successfully becomes a
        # Playwright Download as an aborted document navigation. The download
        # itself is verified byte-for-byte in audit_download; it is not a
        # network failure and must not inflate the failed-request denominator.
        if relative_url(request.url) in DOWNLOAD_PATHS and request.failure == "net::ERR_ABORTED":
            return
        events["failed_requests"].append({"url": request.url, "failure": request.failure or "unknown"})

    context.on("requestfailed", request_failed)
    return context, events


def wire_page_events(page: Page, events: dict[str, list[Any]]) -> None:
    page.on(
        "console",
        lambda message: events["console_errors"].append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))


def goto(page: Page, origin: str, path: str) -> None:
    response = page.goto(origin + path, wait_until="networkidle")
    if response is None or response.status != 200:
        raise AssertionError((path, None if response is None else response.status))


def click_navigation(page: Page, locator: Locator) -> None:
    locator.click()
    page.wait_for_load_state("networkidle")


def validate_expected(before: dict[str, Any], expected: str, control_id: str) -> None:
    assert before is not None, control_id
    if expected == "visible":
        assert before["visible"], control_id
    elif expected == "enabled":
        assert before["enabled"] and not before["disabled"], control_id
    elif expected == "checked":
        assert before["checked"], control_id
    elif expected == "disabled":
        assert before["disabled"] or not before["enabled"], control_id
    else:
        raise AssertionError((control_id, expected))


def audit_download(page: Page, locator: Locator, expected_bytes: int, expected_sha: str) -> dict[str, Any]:
    with page.expect_download(timeout=300_000) as event:
        locator.click()
    download = event.value
    path = download.path()
    assert path is not None
    size, digest = file_sha(path)
    assert (size, digest) == (expected_bytes, expected_sha)
    return {
        "suggested_filename": download.suggested_filename,
        "bytes": size,
        "sha256": digest,
        "failure": download.failure(),
    }


def audit_control(
    browser: Browser,
    origin: str,
    contract: tuple[str, str, str, str],
    checkpoint_paths: dict[str, str],
) -> dict[str, Any]:
    control_id, checkpoint_id, selector, expected = contract
    context, events = new_context(browser, origin)
    page = context.new_page()
    wire_page_events(page, events)
    route = checkpoint_paths[checkpoint_id]
    result: dict[str, Any] = {
        "control_id": control_id,
        "checkpoint_id": checkpoint_id,
        "selector": selector,
        "expected_state": expected,
        "route": route,
        "status": "fail",
    }
    try:
        goto(page, origin, route)
        locator = page.locator(selector).first
        before = snapshot(locator)
        assert before is not None
        validate_expected(before, expected, control_id)
        result["before"] = before
        result["before_page"] = page_identity(page)
        action: dict[str, Any] = {}

        if control_id == "nav-toggle":
            assert not locator.is_visible()
            locator.evaluate("el => el.click()")
            action = {
                "profile_visibility": "desktop-hidden",
                "aria_expanded": locator.get_attribute("aria-expanded"),
                "target_state": page.locator("#global-navigation").get_attribute("data-menu-open"),
            }
            assert action["aria_expanded"] == action["target_state"] == "true"
        elif control_id == "course-menu":
            assert not locator.is_visible()
            locator.evaluate("el => el.click()")
            action = {
                "profile_visibility": "desktop-hidden",
                "aria_expanded": locator.get_attribute("aria-expanded"),
                "target_state": page.locator("#course-material-navigation").get_attribute("data-menu-open"),
            }
            assert action["aria_expanded"] == action["target_state"] == "true"
        elif control_id == "global-search-input":
            locator.focus()
            locator.fill("software")
            action = {"focused": locator.evaluate("el => document.activeElement === el"), "value": locator.input_value()}
            assert action == {"focused": True, "value": "software"}
        elif control_id == "global-search-submit":
            page.locator("[data-wb-control='global-search-input']").fill("software")
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "result_count": page.locator(".results-head h2").inner_text()}
            assert action == {"destination": "/search/?q=software", "result_count": "1 results"}
        elif control_id in {
            "promo-previous",
            "promo-next",
            "featured-next",
            "new-next",
            "stories-next",
            "featured-previous",
            "new-previous",
            "stories-previous",
        }:
            expected_destination = locator.get_attribute("data-wb-state-href") or locator.get_attribute("href")
            assert expected_destination and expected_destination.startswith("/")
            click_navigation(page, locator)
            action = {
                "destination": relative_url(page.url),
                "contracted_state_destination": expected_destination,
            }
            assert action["destination"] == expected_destination
        elif control_id == "catalog-query":
            locator.focus()
            locator.fill("SCIENCE")
            action = {"focused": locator.evaluate("el => document.activeElement === el"), "value": locator.input_value()}
            assert action == {"focused": True, "value": "SCIENCE"}
        elif control_id == "catalog-course-tab":
            goto(page, origin, "/search/?state=resources")
            locator = page.locator(selector).first
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "checked": locator.is_checked()}
            assert action["destination"] == "/search/" and action["checked"]
        elif control_id == "catalog-resource-tab":
            goto(page, origin, "/search/")
            locator = page.locator(selector).first
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "checked": locator.is_checked()}
            assert action["destination"] == "/search/?state=resources" and action["checked"]
        elif control_id == "catalog-clear-all":
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "checked_filters": page.locator("input:checked").count()}
            assert action["destination"] == "/search/"
        elif control_id == "catalog-departments":
            locator.click()
            closed = {"aria": locator.get_attribute("aria-expanded"), "hidden": page.locator("#catalog-department-list").is_hidden()}
            locator.click()
            opened = {"aria": locator.get_attribute("aria-expanded"), "visible": page.locator("#catalog-department-list").is_visible()}
            action = {"closed": closed, "opened": opened}
            assert closed == {"aria": "false", "hidden": True}
            assert opened == {"aria": "true", "visible": True}
        elif control_id == "catalog-math-filter":
            goto(page, origin, "/search/")
            locator = page.locator(selector).first
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "checked": page.locator(selector).is_checked()}
            assert action == {"destination": "/search/?state=math", "checked": True}
        elif control_id == "catalog-undergraduate-filter":
            goto(page, origin, "/search/?state=math")
            locator = page.locator(selector).first
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "checked": page.locator(selector).is_checked()}
            assert action == {"destination": "/search/?state=math-undergraduate", "checked": True}
        elif control_id == "catalog-sort":
            goto(page, origin, "/search/?state=math-undergraduate")
            locator = page.locator(selector).first
            with page.expect_navigation(wait_until="networkidle"):
                locator.select_option(label="MIT course #")
            page.wait_for_load_state("networkidle")
            action = {"destination": relative_url(page.url), "value": page.locator(selector).input_value()}
            assert action == {"destination": "/search/?state=course-number", "value": "MIT course #"}
        elif control_id == "catalog-load-more":
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "cards": page.locator("article.card").count()}
            assert action == {"destination": "/search/?state=second-batch", "cards": 20}
        elif control_id == "catalog-retry":
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "stale_error": page.locator("[data-wb-component='catalog-error']").is_visible()}
            assert action == {"destination": "/search/?state=retry-stale", "stale_error": True}
        elif control_id == "catalog-empty-clear":
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "result_count": page.locator(".results-head h2").inner_text()}
            assert action == {"destination": "/search/?state=clear-recovered", "result_count": "2584 results"}
        elif control_id == "course-download":
            action = audit_download(page, locator, ARCHIVE_BYTES, ARCHIVE_SHA256)
            assert action["suggested_filename"] == "6.006-fall-2011.zip"
        elif control_id == "resource-download":
            action = audit_download(page, locator, PDF_BYTES, PDF_SHA256)
            assert action["suggested_filename"].endswith("MIT6_006F11_ps1.pdf")
        elif control_id == "newsletter-email":
            locator.focus()
            locator.fill("learner@example.test")
            action = {"focused": locator.evaluate("el => document.activeElement === el"), "value": locator.input_value()}
            assert action == {"focused": True, "value": "learner@example.test"}
        elif control_id == "newsletter-submit":
            page.locator("[data-wb-control='newsletter-email']").fill("learner@example.test")
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url), "body": page.locator("main").inner_text()}
            assert action["destination"].startswith("/external-boundary/?url=")
            assert NEWSLETTER_DESTINATION in action["body"]
            assert "subscribed" not in action["body"].casefold()
        elif control_id == "video-play":
            action = {"executed": False, "skip_reason": "control-is-contractually-disabled", "media_requests": 0}
            assert locator.is_disabled()
            assert page.locator("[data-wb-media='disabled-video-poster']").count() == 1
        elif control_id in {"external-return", "data-boundary-return"}:
            click_navigation(page, locator)
            action = {"destination": relative_url(page.url)}
            assert action["destination"] == ("/" if control_id == "external-return" else "/search/")
        else:
            raise AssertionError(f"unhandled control {control_id}")

        result["action"] = action
        result["after_page"] = page_identity(page)
        result["after"] = snapshot(page.locator(selector).first)
        assert not any(events.values()), events
        result["events"] = {key: 0 for key in events}
        result["status"] = "pass"
        result["fingerprint"] = stable_sha(
            {key: result[key] for key in ("control_id", "checkpoint_id", "selector", "expected_state", "before", "action", "after_page")}
        )
        return result
    except Exception as error:
        result["error"] = repr(error)
        result["events"] = events
        return result
    finally:
        context.close()


def audit_recovery(browser: Browser, origin: str) -> dict[str, Any]:
    context, events = new_context(browser, origin)
    page = context.new_page()
    wire_page_events(page, events)
    try:
        goto(page, origin, "/")
        featured_next = page.locator("[data-wb-control='featured-next']")
        expected_forward = featured_next.get_attribute("data-wb-state-href") or featured_next.get_attribute("href")
        assert expected_forward and expected_forward.startswith("/")
        click_navigation(page, featured_next)
        navigated = relative_url(page.url)
        assert navigated == expected_forward
        second_identity = page.locator("[data-wb-component='featured-courses'] article.card h3").all_inner_texts()
        page.go_back(wait_until="networkidle")
        back = relative_url(page.url)
        page.go_forward(wait_until="networkidle")
        forward = relative_url(page.url)
        page.reload(wait_until="networkidle")
        refreshed_identity = page.locator("[data-wb-component='featured-courses'] article.card h3").all_inner_texts()
        page2 = context.new_page()
        wire_page_events(page2, events)
        goto(page2, origin, "/search/?state=math-undergraduate")
        new_context_state = {
            "path": relative_url(page2.url),
            "math_checked": page2.locator("[data-wb-control='catalog-math-filter']").is_checked(),
            "undergraduate_checked": page2.locator("[data-wb-control='catalog-undergraduate-filter']").is_checked(),
        }
        assert back == "/" and forward == expected_forward
        assert second_identity == refreshed_identity
        assert new_context_state == {
            "path": "/search/?state=math-undergraduate",
            "math_checked": True,
            "undergraduate_checked": True,
        }
        assert not any(events.values()), events
        return {
            "status": "pass",
            "expected_forward": expected_forward,
            "navigated": navigated,
            "back": back,
            "forward": forward,
            "refresh_identity_sha256": stable_sha(refreshed_identity),
            "deep_link_new_page": new_context_state,
            "events": {key: 0 for key in events},
        }
    finally:
        context.close()


def audit_home_denominator(browser: Browser, origin: str, passed_controls: set[str]) -> dict[str, Any]:
    context, events = new_context(browser, origin)
    page = context.new_page()
    wire_page_events(page, events)
    try:
        goto(page, origin, "/")
        rows = page.locator("a,button,input,select,textarea,[tabindex]").evaluate_all(
            """els => els.map((el,index) => ({
              index, tag:el.tagName.toLowerCase(), text:(el.innerText||el.value||el.getAttribute('aria-label')||'').trim().replace(/\\s+/g,' ').slice(0,160),
              href:el.href||'', type:el.type||'', control:el.dataset.wbControl||'', external:el.dataset.wbExternal||'',
              visible:!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length), disabled:Boolean(el.disabled)
            })).filter(row => row.visible || row.control === 'nav-toggle')"""
        )
        local_destinations: set[str] = set()
        classified: list[dict[str, Any]] = []
        for row in rows:
            href = str(row["href"])
            if row["external"] or (href and urlparse(href).hostname not in {"127.0.0.1", "localhost"}):
                classification = "external-content-not-visited-by-user-instruction"
            elif href:
                destination = relative_url(href)
                local_destinations.add(destination)
                classification = "safe-local-navigation"
            elif row["disabled"]:
                classification = "contractually-disabled"
            elif row["control"] in passed_controls:
                classification = "executed-by-control-audit"
            else:
                classification = "non-navigation-form-field"
            classified.append({**row, "href": relative_url(href) if href and classification == "safe-local-navigation" else href, "classification": classification})

        executed: list[dict[str, Any]] = []
        for destination in sorted(local_destinations):
            probe = context.new_page()
            wire_page_events(probe, events)
            response = probe.goto(origin + destination, wait_until="networkidle")
            status = None if response is None else response.status
            assert status == 200, (destination, status)
            executed.append({"destination": destination, "status": status, "title": probe.title()})
            probe.close()

        required_information_destinations = {
            "/about/",
            "/collections/introductory-programming/",
            "/educator/",
            "/pages/get-started/",
            "/stories/",
        }
        assert required_information_destinations <= local_destinations

        representative = page.locator("[data-wb-external='giving']").first
        source_href = representative.get_attribute("href")
        click_navigation(page, representative)
        assert relative_url(page.url).startswith("/external-boundary/?url=")
        assert source_href and source_href in page.locator("main").inner_text()
        assert not any(events.values()), events
        return {
            "status": "pass",
            "enumerated": len(classified),
            "classification_counts": {
                kind: sum(row["classification"] == kind for row in classified)
                for kind in sorted({row["classification"] for row in classified})
            },
            "controls": classified,
            "safe_local_destinations_executed": executed,
            "required_information_destinations": sorted(required_information_destinations),
            "representative_external_boundary": {"source_href": source_href, "destination": relative_url(page.url)},
            "events": {key: 0 for key in events},
        }
    finally:
        context.close()


def audit_navigation_boundary_statuses(origin: str) -> dict[str, Any]:
    with urllib.request.urlopen(origin + "/not-found/", timeout=30) as response:
        explicit_status = response.status
        explicit_body = response.read().decode("utf-8", errors="replace")
    assert explicit_status == 200
    assert 'data-wb-page-id="not-found-recovery"' in explicit_body

    hard_404_status: int | None = None
    try:
        urllib.request.urlopen(origin + "/__websitebench_missing_route__", timeout=30)
    except urllib.error.HTTPError as error:
        hard_404_status = error.code
    assert hard_404_status == 404
    return {
        "status": "pass",
        "explicit_not_found_status": explicit_status,
        "hard_missing_route_status": hard_404_status,
    }


def audit_route_identity_closure(origin: str) -> dict[str, Any]:
    pages = read_json(CLONE / "site-data.json")["pages"]
    assert len(pages) == 732
    family_counts: dict[str, int] = {}
    aggregate = hashlib.sha256()
    for path, row in pages.items():
        request_path = quote(path, safe="/?=&%")
        with urllib.request.urlopen(origin + request_path, timeout=60) as response:
            status = response.status
            markup = response.read().decode("utf-8", errors="replace")
        assert status == int(row["status"]), path
        assert f"<title>{escape(str(row['title']))}</title>" in markup, path
        assert f'data-wb-route-family="{row["family"]}"' in markup, path
        assert f'data-wb-page-id="{row["page_id"]}"' in markup, path
        if path == "/":
            assert "Unlocking knowledge" in markup
        else:
            heading = next(
                (str(item["text"]) for item in row["headings"] if str(item.get("text", "")).strip()),
                "",
            )
            assert heading and escape(heading) in markup, path
        family = str(row["family"])
        family_counts[family] = family_counts.get(family, 0) + 1
        aggregate.update(
            json.dumps(
                [path, status, row["title"], family, row["page_id"]],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return {
        "status": "pass",
        "routes_checked": len(pages),
        "route_families": len(family_counts),
        "family_counts": family_counts,
        "identity_fingerprint": aggregate.hexdigest(),
    }


def audit_presentation_asset_closure() -> dict[str, Any]:
    manifest = read_json(SITE / "source-assets" / "manifest.json")
    assets = manifest["assets"]
    assert manifest["remote_runtime_policy"] == "forbidden"
    assert len(assets) == 288
    aggregate = hashlib.sha256()
    total_bytes = 0
    for row in assets:
        runtime_path = SITE / row["runtime_path"]
        size, digest = file_sha(runtime_path)
        assert size == int(row["bytes"]), row["id"]
        assert digest == row["sha256"], row["id"]
        total_bytes += size
        aggregate.update(f"{row['id']}\0{size}\0{digest}\n".encode("utf-8"))

    site_data = read_json(CLONE / "site-data.json")
    initial_unavailable = site_data["unavailable_assets"]
    g3b_unavailable = read_json(SITE / "source-assets" / "g3b-content-asset-addendum.json")["unavailable"]
    assert len(initial_unavailable) == 5
    assert len(g3b_unavailable) == 4
    assert all(int(row["status"]) == 404 for row in initial_unavailable.values())
    assert all(int(row["http_status"]) == 404 for row in g3b_unavailable.values())
    denominator = site_data["final_denominator_status"]
    assert denominator["presentation_assets"] == 288
    assert denominator["presentation_asset_bytes"] == total_bytes
    assert denominator["unavailable_assets"] == 9
    return {
        "status": "pass",
        "assets_checked": len(assets),
        "asset_bytes": total_bytes,
        "asset_fingerprint": aggregate.hexdigest(),
        "unavailable_evidence_records": len(initial_unavailable) + len(g3b_unavailable),
        "unavailable_unique_source_urls": len(set(initial_unavailable) | set(g3b_unavailable)),
        "unavailable_record_breakdown": {"initial": 5, "g3b_addendum": 4},
        "remote_runtime_policy": manifest["remote_runtime_policy"],
    }


def audit_restart(browser: Browser, port: int, process: subprocess.Popen[bytes]) -> tuple[subprocess.Popen[bytes], dict[str, Any]]:
    stop_server(process)
    restarted = start_server(port)
    origin = f"http://127.0.0.1:{port}"
    context, events = new_context(browser, origin)
    page = context.new_page()
    wire_page_events(page, events)
    try:
        goto(page, origin, "/search/?state=math-undergraduate")
        state = {
            "path": relative_url(page.url),
            "math_checked": page.locator("[data-wb-control='catalog-math-filter']").is_checked(),
            "undergraduate_checked": page.locator("[data-wb-control='catalog-undergraduate-filter']").is_checked(),
            "result_count": page.locator(".results-head h2").inner_text(),
        }
        assert state == {
            "path": "/search/?state=math-undergraduate",
            "math_checked": True,
            "undergraduate_checked": True,
            "result_count": "110 results",
        }
        assert not any(events.values()), events
        return restarted, {"status": "pass", "state": state, "events": {key: 0 for key in events}}
    except Exception:
        stop_server(restarted)
        raise
    finally:
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", required=True)
    args = parser.parse_args()
    if not args.iteration.replace("-", "").isalnum():
        raise SystemExit("iteration must contain only letters, digits, and hyphens")
    output = SITE / "artifacts" / "offline-clone" / "g4" / args.iteration
    if output.exists():
        raise SystemExit(f"refusing to overwrite create-only output: {output}")
    output.mkdir(parents=True)

    interaction = read_json(CONTROL_CONTRACT)
    inventory = read_json(CONTROL_INVENTORY)["controls"]
    capabilities = read_json(COMPONENT_MATRIX)["local_capabilities"]
    checkpoint_paths = {row["id"]: row["clone_path"] for row in read_json(CHECKPOINTS)["checkpoints"]}
    contracts = [tuple(row) for row in interaction["controls"]]
    assert len(contracts) == len(inventory) == 30
    assert [row[0] for row in contracts] == [row["id"] for row in inventory]
    assert len(capabilities) == 7

    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    process = start_server(port)
    started_at = time.time()
    control_results: list[dict[str, Any]] = []
    recovery = {"stage": "navigation-recovery", "status": "not-executed-with-reason", "events": {}}
    home_denominator = {"stage": "home-denominator", "status": "not-executed-with-reason", "events": {}}
    restart = {"stage": "service-restart", "status": "not-executed-with-reason", "events": {}}
    navigation_boundaries = {
        "stage": "navigation-boundary-statuses",
        "status": "not-executed-with-reason",
        "events": {},
    }
    route_identity = {
        "stage": "route-identity-closure",
        "status": "not-executed-with-reason",
        "events": {},
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            control_results = [audit_control(browser, origin, row, checkpoint_paths) for row in contracts]
            passed_controls = {row["control_id"] for row in control_results if row["status"] == "pass"}
            try:
                recovery = audit_recovery(browser, origin)
            except Exception as error:
                recovery = failed_stage("navigation-recovery", error)
            try:
                home_denominator = audit_home_denominator(browser, origin, passed_controls)
            except Exception as error:
                home_denominator = failed_stage("home-denominator", error)
            try:
                navigation_boundaries = audit_navigation_boundary_statuses(origin)
            except Exception as error:
                navigation_boundaries = failed_stage("navigation-boundary-statuses", error)
            try:
                route_identity = audit_route_identity_closure(origin)
            except Exception as error:
                route_identity = failed_stage("route-identity-closure", error)
            try:
                process, restart = audit_restart(browser, port, process)
            except Exception as error:
                restart = failed_stage("service-restart", error)
            browser.close()
    finally:
        if process.poll() is None:
            stop_server(process)

    try:
        presentation_assets = audit_presentation_asset_closure()
    except Exception as error:
        presentation_assets = failed_stage("presentation-asset-closure", error)

    failed = [row for row in control_results if row["status"] != "pass"]
    capability_control_map = {
        "local-search": ["global-search-submit", "catalog-query"],
        "local-filter-sort": ["catalog-math-filter", "catalog-undergraduate-filter", "catalog-sort"],
        "local-attachment-download": ["resource-download"],
        "local-course-archive": ["course-download"],
        "external-boundary": ["newsletter-submit", "external-return"],
        "data-boundary": ["data-boundary-return"],
        "video-playback-disabled": ["video-play"],
    }
    capability_results = []
    for capability in capabilities:
        capability_id = capability["id"]
        controls = capability_control_map[capability_id]
        status = "pass" if all(control in passed_controls for control in controls) else "fail"
        capability_results.append(
            {
                "capability_id": capability_id,
                "status": status,
                "control_proofs": controls,
                "source_expectation": capability["source_expectation"],
                "fingerprint": stable_sha({"capability_id": capability_id, "controls": controls, "status": status}),
            }
        )

    proof_status = {row["control_id"]: row["status"] for row in control_results}
    proof_status.update(
        {
            "navigation-recovery": str(recovery["status"]),
            "home-denominator": str(home_denominator["status"]),
            "service-restart": str(restart["status"]),
            "navigation-boundary-statuses": str(navigation_boundaries["status"]),
            "route-identity-closure": str(route_identity["status"]),
            "presentation-asset-closure": str(presentation_assets["status"]),
        }
    )
    journeys = derive_journey_results(proof_status)
    frozen_journey_ids = [row["id"] for row in read_json(SCOPE / "journeys.json")["journeys"]]
    assert [row["journey_id"] for row in journeys] == frozen_journey_ids
    def event_count(container: dict[str, Any], key: str) -> int:
        value = container.get("events", {}).get(key, 0)
        return len(value) if isinstance(value, list) else int(value)

    total_events = {
        key: sum(event_count(row, key) for row in control_results)
        + event_count(recovery, key)
        + event_count(home_denominator, key)
        + event_count(restart, key)
        for key in ("remote_requests", "local_404", "failed_requests", "console_errors", "page_errors")
    }
    recipe_refs = sorted(
        {
            ref
            for row in [*inventory, *capabilities]
            for ref in row["recipe_refs"]
        }
    )
    assert len(recipe_refs) == 37
    recipe_hashes = {
        ref: file_sha(SITE / ref)[1]
        for ref in recipe_refs
    }
    contract_paths = [
        "scope/business-contracts/interaction-api-contract.json",
        "scope/all-controls-inventory.json",
        "scope/component-state-matrix.json",
    ]
    candidate_identity = {
        "site_id": "mit-opencourseware",
        "capture_id": "mit-opencourseware-20260903T032020Z",
        "clone_app_sha256": file_sha(CLONE / "app.py")[1],
        "site_data_sha256": file_sha(CLONE / "site-data.json")[1],
        "contract_sha256": {path: file_sha(SITE / path)[1] for path in contract_paths},
        "recipe_sha256": recipe_hashes,
        "recipe_denominator": {"controls": 30, "local_capabilities": 7, "total": 37},
        "git_branch": subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
    }
    overall_passed = (
        not failed
        and all(row["status"] == "pass" for row in capability_results)
        and all(row["status"] == "pass" for row in journeys)
        and all(
            row["status"] == "pass"
            for row in (
                recovery,
                home_denominator,
                restart,
                navigation_boundaries,
                route_identity,
                presentation_assets,
            )
        )
        and not any(total_events.values())
    )
    report = {
        "schema_version": "mit-ocw.g4-interaction-audit.v1",
        "iteration": args.iteration,
        "status": "passed" if overall_passed else "failed",
        "created_at_unix": started_at,
        "candidate_identity": candidate_identity,
        "environment": {
            "viewport": {"width": 1440, "height": 900},
            "device_scale_factor": 1,
            "color_scheme": "light",
            "reduced_motion": "reduce",
            "locale": "en-US",
            "timezone_id": "America/Toronto",
            "network_policy": "loopback-only; all non-local requests aborted",
        },
        "denominators": {"controls": 30, "local_capabilities": 7, "journeys": 10},
        "summary": {
            "controls_passed": len(passed_controls),
            "controls_failed": len(failed),
            "capabilities_passed": sum(row["status"] == "pass" for row in capability_results),
            "journeys_passed": sum(row["status"] == "pass" for row in journeys),
            **total_events,
        },
        "controls": control_results,
        "capabilities": capability_results,
        "journeys": journeys,
        "navigation_recovery": recovery,
        "service_restart_determinism": restart,
        "home_control_denominator": home_denominator,
        "navigation_boundary_statuses": navigation_boundaries,
        "route_identity_closure": route_identity,
        "presentation_asset_closure": presentation_assets,
        "backend_non_applicability": {
            "accounts": "not-applicable",
            "authentication": "not-applicable",
            "payments": "not-applicable",
            "persistent_writes": "not-applicable",
            "newsletter": "external-boundary-only; no local or real email delivery",
        },
        "download_evidence": {
            "course_archive": {"bytes": ARCHIVE_BYTES, "sha256": ARCHIVE_SHA256, "actual_ui_click": True},
            "problem_set_pdf": {"bytes": PDF_BYTES, "sha256": PDF_SHA256, "actual_ui_click": True},
        },
    }
    report["report_fingerprint"] = stable_sha({key: report[key] for key in report if key not in {"created_at_unix"}})
    report_path = output / "interaction-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not overall_passed:
        print(json.dumps({"report": str(report_path), "summary": report["summary"], "failures": failed}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps({"report": report_path.relative_to(SITE).as_posix(), "summary": report["summary"], "fingerprint": report["report_fingerprint"]}, sort_keys=True))


if __name__ == "__main__":
    main()
