"""Literal geometry contracts for the user's 1692 × 979 acceptance viewport."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT / "clone"))

from test_desktop_visual import _clone_server  # noqa: E402


VIEWPORT = {"width": 1692, "height": 979}


@pytest.mark.parametrize(
    ("path", "selector"),
    (
        ("/browse/business", "[data-business-shell]"),
        ("/specializations/deep-learning", ".source-specialization-stats"),
        ("/learn/neural-networks-deep-learning", ".source-course-detail-stats"),
    ),
)
def test_fullscreen_primary_content_uses_the_source_1344_pixel_shell(
    path: str, selector: str
) -> None:
    """Catch route families reverting to the obsolete 1088px content cap."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + path, wait_until="networkidle")
                viewport = page.evaluate(
                    "[document.documentElement.clientWidth, document.documentElement.clientHeight]"
                )
                box = page.locator(selector).bounding_box()

                assert viewport == [1692, 979]
                assert box is not None
                assert abs(box["x"] - 174) <= 2
                assert abs(box["width"] - 1344) <= 2
        finally:
            context.close()
            browser.close()


def test_category_footer_keeps_source_columns_in_separate_full_width_rows() -> None:
    """Catch the legacy three-column footer rule overlapping category columns."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/browse/business", wait_until="networkidle")
                footer = page.locator("footer")
                footer_box = footer.bounding_box()
                first_row = [
                    page.get_by_role("heading", name=title, exact=True).bounding_box()
                    for title in (
                        "Skills",
                        "Professional Certificates",
                        "Courses & Specializations",
                        "Career Resources",
                    )
                ]
                second_row = [
                    page.get_by_role("heading", name=title, exact=True).bounding_box()
                    for title in ("Coursera", "Community", "More")
                ]

                assert footer_box is not None
                assert all(box is not None for box in (*first_row, *second_row))
                assert abs(footer_box["x"]) <= 1
                assert abs(footer_box["width"] - 1692) <= 1
                assert len({round(box["y"]) for box in first_row if box}) == 1
                assert len({round(box["y"]) for box in second_row if box}) == 1
                assert all(
                    left["x"] + left["width"] <= right["x"]
                    for left, right in zip(first_row, first_row[1:])
                    if left and right
                )
                assert second_row[0]["y"] > first_row[0]["y"] + first_row[0]["height"]
        finally:
            context.close()
            browser.close()


def test_home_uses_source_shell_compact_purpose_controls_and_stable_images() -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(base_url + "/", wait_until="networkidle")
                shell = page.locator(".source-home-shell").bounding_box()
                purpose = page.locator(".home-purpose").bounding_box()
                purpose_controls = page.locator(".home-purpose a")

                compact_heights = page.locator(".source-list-card .source-card-image").evaluate_all(
                    "els => els.map(el => Math.round(el.getBoundingClientRect().height))"
                )
                product_heights = page.locator(
                    ".source-learning-card:visible .source-card-image"
                ).evaluate_all(
                    "els => els.map(el => Math.round(el.getBoundingClientRect().height))"
                )
                role_heights = page.locator(".source-role-card img").evaluate_all(
                    "els => els.map(el => Math.round(el.getBoundingClientRect().height))"
                )
                control_boxes = [
                    purpose_controls.nth(index).bounding_box()
                    for index in range(purpose_controls.count())
                ]

                assert shell is not None and purpose is not None
                assert abs(shell["x"] - 174) <= 2
                assert abs(shell["width"] - 1344) <= 2
                assert abs(purpose["width"] - 1344) <= 2
                assert 96 <= purpose["height"] <= 112
                assert purpose_controls.count() == 4
                assert all(box is not None and box["width"] < 240 for box in control_boxes)
                assert all(box is not None and box["height"] == 48 for box in control_boxes)
                assert set(compact_heights) == {94}
                assert set(product_heights) == {120}
                assert set(role_heights) == {125}
        finally:
            context.close()
            browser.close()
