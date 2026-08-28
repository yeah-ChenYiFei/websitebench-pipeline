#!/usr/bin/env python3
"""Local-only Playwright assertions for the authenticated Home visual3 layout.

The caller owns server startup and supplies a loopback base URL. The verifier
uses a fresh synthetic account, retains no browser profile or screenshots, and
aborts every request outside that exact loopback origin.
"""

from __future__ import annotations

import argparse
import json
import uuid
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Locator, Page, sync_playwright


def _rect(locator: Locator) -> dict[str, float]:
    value = locator.bounding_box()
    assert value is not None, f"missing geometry for {locator}"
    return {key: round(float(value[key]), 2) for key in ("x", "y", "width", "height")}


def _assert_rect(
    page: Page,
    selector: str,
    expected: dict[str, float],
    *,
    tolerance: float = 1.25,
) -> dict[str, float]:
    actual = _rect(page.locator(selector).first)
    for key, target in expected.items():
        assert abs(actual[key] - target) <= tolerance, (
            f"{selector} {key}: expected {target}±{tolerance}, got {actual[key]}"
        )
    return actual


def _assert_no_horizontal_overflow(page: Page, width: int) -> None:
    values = page.evaluate(
        """() => ({
          html: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          app: document.querySelector('#app').scrollWidth,
          viewport: window.innerWidth
        })"""
    )
    assert values == {"html": width, "body": width, "app": width, "viewport": width}, values


def _signup(context: BrowserContext, base_url: str) -> None:
    local_email = f"visual2-{uuid.uuid4().hex[:12]}@example.com"
    local_password = "visual2-local-" + uuid.uuid4().hex
    response = context.request.post(
        f"{base_url}/api/auth/signup",
        data={
            "name": "Local User",
            "email": local_email,
            "password": local_password,
        },
    )
    assert response.ok, response.status
    mail = context.request.get(
        f"{base_url}/api/auth/mail", params={"purpose": "registration"}
    )
    assert mail.ok, mail.status
    code = mail.json()["verification_code"]
    verified = context.request.post(
        f"{base_url}/api/auth/verify", data={"code": code}
    )
    assert verified.ok, verified.status


def _desktop_geometry(page: Page) -> dict[str, dict[str, float]]:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("/app/home")
    page.locator(".home-learn").wait_for()
    _assert_no_horizontal_overflow(page, 1440)
    checks = {
        "topbar": _assert_rect(page, ".topbar", {"x": 0, "y": 0, "width": 1440, "height": 49}),
        "hamburger": _assert_rect(page, "#hamb", {"x": 18, "y": 10, "width": 28, "height": 28}),
        "create": _assert_rect(page, "#create-btn", {"x": 64, "y": 8, "width": 89, "height": 32}),
        "search": _assert_rect(page, ".searchbox", {"x": 450, "y": 8, "width": 540, "height": 32}),
        "assistant": _assert_rect(page, "#assistant-btn", {"x": 1400, "y": 10, "width": 28, "height": 28}),
        "sidebar": _assert_rect(page, ".sidebar", {"x": 0, "y": 49, "width": 245, "height": 851}),
        "mode_rail": _assert_rect(page, ".mode-rail", {"x": 0, "y": 49, "width": 64, "height": 851}),
        "workspace_rail": _assert_rect(page, ".workspace-rail", {"x": 64, "y": 49, "width": 181, "height": 851}),
        "home_nav": _assert_rect(page, '.workspace-primary a[href="/app/home"]', {"x": 69, "y": 83, "width": 171, "height": 32}),
        "inbox_nav": _assert_rect(page, '.workspace-primary a[href="/app/inbox"]', {"x": 69, "y": 115, "width": 171, "height": 32}),
        "separator": _assert_rect(page, ".workspace-separator", {"x": 73, "y": 155, "width": 163, "height": 1}),
        "tasks_nav": _assert_rect(page, '.workspace-links a[href="/app/tasks"]', {"x": 69, "y": 164, "width": 171, "height": 32}),
        "main": _assert_rect(page, ".content", {"x": 245, "y": 49, "width": 1195, "height": 851}),
        "header": _assert_rect(page, ".home-header", {"x": 269, "y": 49, "width": 1147, "height": 90}),
        "list": _assert_rect(page, ".home-list", {"x": 269, "y": 151, "width": 1147}),
        "tasks_outer": _assert_rect(page, ".home-my-tasks", {"x": 269, "y": 151, "width": 573.5, "height": 416}),
        "tasks_card": _assert_rect(page, ".home-my-tasks .home-card", {"x": 277, "y": 159, "width": 557.5, "height": 400}),
        "tasks_avatar": _assert_rect(page, ".home-avatar", {"x": 302, "y": 186, "width": 24, "height": 24}),
        "tasks_heading": _assert_rect(page, "#home-my-tasks-title", {"x": 334, "y": 184, "height": 28}),
        "tasks_tabs": _assert_rect(page, ".home-task-tabs", {"x": 302, "y": 212, "width": 507.5, "height": 44}),
        "tasks_panel": _assert_rect(page, ".home-task-panel", {"x": 278, "y": 257, "width": 555.5}),
        "projects_outer": _assert_rect(page, ".home-projects", {"x": 842.5, "y": 151, "width": 573.5, "height": 416}),
        "projects_card": _assert_rect(page, ".home-projects .home-card", {"x": 850.5, "y": 159, "width": 557.5, "height": 400}),
        "learn_outer": _assert_rect(page, ".home-learn", {"x": 269, "y": 567, "width": 1147, "height": 416}),
        "learn_card": _assert_rect(page, ".home-learn .home-card", {"x": 277, "y": 575, "width": 1131, "height": 400}),
        "learn_heading": _assert_rect(page, "#home-learn-title span", {"x": 302, "y": 600, "height": 28}),
        "assigned_widget": _assert_rect(page, ".home-assigned", {"x": 269, "y": 983, "width": 573.5, "height": 416}),
        "people_widget": _assert_rect(page, ".home-people", {"x": 842.5, "y": 983, "width": 573.5, "height": 416}),
        "focus_widget": _assert_rect(page, ".home-focus", {"x": 269, "y": 1399, "width": 573.5, "height": 342}),
    }
    card_boxes = page.locator(".learn-card").evaluate_all(
        "els => els.map(el => { const r = el.getBoundingClientRect(); return {x:r.x,right:r.right}; })"
    )
    assert len(card_boxes) == 4
    assert card_boxes[0]["x"] >= 301 and card_boxes[2]["right"] <= 1408
    assert card_boxes[3]["x"] < 1408 < card_boxes[3]["right"], card_boxes
    assert page.locator(".home-task-rows .task-row").count() == 2
    assert page.locator(".mode-button").count() == 6
    assert page.locator(".workspace-links .side-item").count() == 3
    assert page.locator(".home-page").evaluate("el => el.scrollHeight") >= 1741
    return checks


def _mobile_geometry(page: Page) -> dict[str, dict[str, float]]:
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    page.locator(".home-learn").wait_for()
    _assert_no_horizontal_overflow(page, 390)
    sidebar = _rect(page.locator(".sidebar"))
    assert sidebar["x"] + sidebar["width"] <= 0, sidebar
    checks = {
        "topbar": _assert_rect(page, ".topbar", {"x": 0, "y": 0, "width": 390, "height": 49}),
        "create": _assert_rect(page, "#create-btn", {"x": 64, "y": 10, "width": 28, "height": 28}),
        "search": _assert_rect(page, ".searchbox", {"x": 100, "y": 8, "width": 242, "height": 32}),
        "assistant": _assert_rect(page, "#assistant-btn", {"x": 350, "y": 10, "width": 28, "height": 28}),
        "main": _assert_rect(page, ".content", {"x": 0, "y": 49, "width": 390, "height": 795}),
        "header": _assert_rect(page, ".home-header", {"x": 24, "y": 49, "width": 358, "height": 126}),
        "customize": _assert_rect(page, "#home-customize", {"x": 291, "y": 97, "width": 91, "height": 28}),
        "summary": _assert_rect(page, ".home-summary", {"x": 32, "y": 147, "width": 352, "height": 28}),
        "list": _assert_rect(page, ".home-list", {"x": 23, "y": 186, "width": 344}),
        "tasks_outer": _assert_rect(page, ".home-my-tasks", {"x": 24, "y": 186, "width": 342, "height": 416}),
        "tasks_card": _assert_rect(page, ".home-my-tasks .home-card", {"x": 32, "y": 195, "width": 326, "height": 400}),
        "tasks_heading": _assert_rect(page, "#home-my-tasks-title", {"x": 89, "y": 220, "height": 28}),
        "tasks_tabs": _assert_rect(page, ".home-task-tabs", {"x": 57, "y": 248, "width": 276, "height": 44}),
        "tasks_panel": _assert_rect(page, ".home-task-panel", {"x": 33, "y": 293, "width": 324}),
        "projects_outer": _assert_rect(page, ".home-projects", {"x": 23, "y": 602, "width": 344, "height": 416}),
        "projects_card": _assert_rect(page, ".home-projects .home-card", {"x": 31, "y": 610, "width": 328, "height": 400}),
        "projects_list": _assert_rect(page, ".home-project-list", {"x": 32, "y": 663, "width": 326, "height": 168}),
        "project_create": _assert_rect(page, ".home-project-create", {"x": 61, "y": 674, "width": 268, "height": 64}),
        "project_row": _assert_rect(page, ".home-project-row", {"x": 61, "y": 746, "width": 268, "height": 64}),
        "learn_outer": _assert_rect(page, ".home-learn", {"x": 23, "y": 1018, "width": 344, "height": 416}),
        "learn_card": _assert_rect(page, ".home-learn .home-card", {"x": 31, "y": 1026, "width": 328, "height": 400}),
        "learn_heading": _assert_rect(page, "#home-learn-title span", {"x": 56, "y": 1051, "height": 28}),
        "learn_carousel": _assert_rect(page, ".learn-carousel", {"x": 32, "y": 1079, "width": 326, "height": 338}),
        "learn_graphic": _assert_rect(page, ".learn-card:first-child .learn-graphic", {"x": 59, "y": 1106, "width": 318, "height": 180}),
    }
    page.locator("#hamb").click()
    page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().x === 0")
    assert _rect(page.locator(".sidebar"))["x"] == 0
    page.locator("#hamb").click()
    page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
    assert page.locator(".home-page").evaluate("el => el.scrollHeight") >= 2683
    return checks


def _behavior(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.reload()
    page.locator(".home-learn").wait_for()

    page.locator("#hamb").click()
    page.wait_for_function("document.querySelector('.content').getBoundingClientRect().x === 0")
    assert _rect(page.locator(".content"))["x"] == 0
    page.locator("#hamb").click()
    page.wait_for_function("document.querySelector('.content').getBoundingClientRect().x === 245")
    assert _rect(page.locator(".content"))["x"] == 245

    page.locator("#assistant-btn").click()
    page.get_by_role("dialog").get_by_role("button", name="Summarize my tasks").click()
    assert "local task list" in page.locator("#assistant-answer").inner_text()
    page.keyboard.press("Escape")

    page.locator("#workspace-title").click()
    assert page.get_by_role("dialog").get_by_text("Demo Workspace", exact=True).count() >= 1
    page.locator("#modal-ws-cancel").click()

    page.locator("#home-timeframe").click()
    page.get_by_text("My week selected", exact=True).wait_for()

    page.locator("#home-task-options").click()
    page.get_by_role("dialog").get_by_role("button", name="Open My tasks").wait_for()
    page.keyboard.press("Escape")

    page.locator('[data-home-tab="overdue"]').click()
    assert page.locator('[data-home-tab="overdue"]').get_attribute("aria-selected") == "true"
    page.locator('[data-home-tab="upcoming"]').click()

    page.locator("#home-customize").click()
    page.get_by_role("dialog").get_by_role("button", name="Comfortable").click()
    assert page.locator("#customize-result").inner_text() == "Home layout updated locally."
    page.keyboard.press("Escape")

    page.locator("#create-btn").click()
    page.get_by_role("dialog").get_by_role("button", name="Task", exact=True).click()
    page.locator("#nt-name").fill("Visual2 local task")
    page.locator("#nt-create").click()
    page.goto("/app/tasks")
    page.get_by_text("Visual2 local task", exact=True).wait_for()
    page.reload()
    page.get_by_text("Visual2 local task", exact=True).wait_for()
    task_row = page.locator(".task-row", has_text="Visual2 local task")
    task_row.locator("[data-done]").click()
    page.locator(".task-row.done", has_text="Visual2 local task").wait_for()
    page.goto("/app/home")
    page.locator('[data-home-tab="completed"]').click()
    assert page.locator('[data-home-tab="completed"]').get_attribute("aria-selected") == "true"

    page.locator("#home-new-project").click()
    page.locator("#np-name").fill("Visual2 Local Project")
    page.locator("#np-create").click()
    page.wait_for_url("**/app/project/**")
    page.locator('.workspace-primary a[href="/app/home"]').click()
    page.locator(".home-project-head a").click()
    page.get_by_text("Visual2 Local Project", exact=True).wait_for()

    page.locator("#global-search").fill("Visual2 local task")
    page.locator("#global-search").press("Enter")
    page.wait_for_url("**/app/search?q=Visual2%20local%20task")
    page.get_by_text("Visual2 local task", exact=True).wait_for()

    page.goto("/app/home")
    page.locator(".learn-card").first.click()
    page.get_by_role("dialog").get_by_role("button", name="Open related work").click()
    page.wait_for_url("**/app/tasks")

    page.goto("/app/home")
    page.locator('[data-widget="assigned"]').click()
    page.get_by_text("Local assigned options opened", exact=True).wait_for()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    assert parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    base_url = args.base_url.rstrip("/")
    blocked: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            base_url=base_url,
            locale="en-US",
            timezone_id="UTC",
            reduced_motion="reduce",
        )

        def local_only(route) -> None:
            target = urlsplit(route.request.url)
            if (
                target.scheme in {"http", "https"}
                and target.hostname == parsed.hostname
                and target.port == parsed.port
            ):
                route.continue_()
                return
            blocked.append(route.request.url)
            route.abort()

        context.route("**/*", local_only)
        _signup(context, base_url)
        page = context.new_page()
        desktop = _desktop_geometry(page)
        mobile = _mobile_geometry(page)
        _behavior(page)
        assert not blocked, f"remote requests blocked: {blocked}"
        assert context.request.get(
            f"{base_url}/static/source/oat-background.png"
        ).status == 200
        background = page.evaluate(
            "getComputedStyle(document.querySelector('.content')).backgroundImage"
        )
        assert "/static/source/oat-background.png" in background
        context.close()
        browser.close()

    print(json.dumps({
        "status": "passed",
        "desktop_assertions": len(desktop),
        "mobile_assertions": len(mobile),
        "remote_requests": 0,
        "screenshots_written": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
