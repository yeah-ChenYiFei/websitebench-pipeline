from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import app
from backend import learning_db
from test_desktop_visual import _clone_server


COURSE = "/learn/neural-networks-deep-learning"
ASSIGNMENT = f"{COURSE}/assignment-submission/3KFZW/introduction-to-deep-learning"
VIEWPORT = {"width": 1692, "height": 979}


@pytest.fixture
def site_client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE", str(tmp_path / "33.sqlite3")
    )
    learning_db.close_services()
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        client.post("/auth/learning-demo", data={"next": "/my-learning"})
        yield client
    learning_db.close_services()


def test_enrolled_pages_ship_versioned_assets_and_no_pre_submit_feedback(
    site_client,
) -> None:
    site_client.post(f"{ASSIGNMENT}/start", data={"honor_code": "accepted"})
    attempt = site_client.get(f"{ASSIGNMENT}/attempt")

    assert re.search(r'/static/enrolled-learning\.css\?v=[^" ]+', attempt.text)
    assert re.search(r'/static/assignment\.js\?v=[^" ]+', attempt.text)
    assert "AI is embedded in tasks across industry and everyday life." not in attempt.text
    assert "clone-local-course-knowledge-derived" not in attempt.text
    for image in (
        "q3-image-1.png",
        "q5-image-1.png",
        "q5-image-2.png",
        "q5-image-3.png",
        "q5-image-4.png",
        "q9-image-1.png",
        "q10-image-1.png",
    ):
        response = site_client.get(f"/static/enrolled/assignment/{image}")
        assert response.status_code == 200, image
        assert response.headers["content-type"] == "image/png"


def test_enrolled_course_fullscreen_geometry_and_network_are_stable(
    tmp_path, monkeypatch
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE", str(tmp_path / "33.sqlite3")
    )
    learning_db.close_services()
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        failed_requests: list[str] = []
        bad_responses: list[str] = []
        console_errors: list[str] = []
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.on("requestfailed", lambda request: failed_requests.append(request.url))
                page.on(
                    "response",
                    lambda response: bad_responses.append(response.url)
                    if response.status >= 400
                    else None,
                )
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                page.goto(base_url + "/login", wait_until="networkidle")
                page.locator('form[action="/auth/learning-demo"]').evaluate(
                    "form => form.submit()"
                )
                page.wait_for_url(re.compile(r".*/my-learning.*"))
                page.goto(base_url + f"{COURSE}/home/module/1", wait_until="networkidle")

                viewport = page.evaluate(
                    "[document.documentElement.clientWidth, document.documentElement.clientHeight]"
                )
                layout = page.locator(".course-learning-layout").bounding_box()
                sidebar = page.locator(".course-learning-nav").bounding_box()
                content = page.locator(".course-learning-content").bounding_box()
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )

                assert viewport == [1692, 979]
                assert layout is not None and layout["width"] >= 1600
                assert sidebar is not None and 270 <= sidebar["width"] <= 330
                assert content is not None and content["width"] >= 1050
                assert overflow <= 1
                assert failed_requests == []
                assert bad_responses == []
                assert console_errors == []
        finally:
            context.close()
            browser.close()
            learning_db.close_services()
