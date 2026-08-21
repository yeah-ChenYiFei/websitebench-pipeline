"""Public-only desktop visual evidence contract for the Coursera clone."""

from __future__ import annotations

import json
import socket
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

import pytest


SITE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = SITE_ROOT.parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
import websitebench  # noqa: E402

repository_package = str(REPOSITORY_ROOT / "src" / "websitebench")
if repository_package not in websitebench.__path__:
    websitebench.__path__.append(repository_package)
VIEWPORT = {"width": 1692, "height": 979}
PUBLIC_ORACLES = {
    "home.desktop.png",
    "browse.desktop.png",
    "search.desktop.png",
    "specialization.desktop.png",
    "course.desktop.png",
    "login.desktop.png",
    "help.desktop.png",
    "not-found.desktop.png",
}


@dataclass(frozen=True)
class DesktopRoute:
    """One anonymous public route and the landmark its rendered view must retain."""

    path: str
    checkpoint_id: str
    landmark: str
    header: str = ".wb-header"
    footer: str = ".wb-footer"


PUBLIC_ROUTES = (
    DesktopRoute("/", "home.loaded.desktop", ".promo-rail"),
    DesktopRoute("/browse", "browse.loaded.desktop", ".browse-source-heading"),
    DesktopRoute(
        "/search?q=Deep+Learning", "search.results.desktop", ".search-page-layout"
    ),
    DesktopRoute(
        "/specializations/deep-learning",
        "specialization.loaded.desktop",
        ".source-specialization-hero",
    ),
    DesktopRoute(
        "/learn/neural-networks-deep-learning",
        "course.loaded.desktop",
        ".source-course-detail-hero",
    ),
    DesktopRoute("/login", "login.loaded.desktop", ".source-login-card"),
    DesktopRoute(
        "/help",
        "help.loaded.desktop",
        ".help-article",
        header=".help-center-header",
        footer=".help-feedback",
    ),
    DesktopRoute(
        "/websitebench-not-found-33",
        "not-found.loaded.desktop",
        ".source-not-found",
    ),
)


def _png_size(path: Path) -> tuple[int, int]:
    """Read only the fixed PNG header; no source HTML is retained or parsed."""

    with path.open("rb") as image:
        assert image.read(8) == b"\x89PNG\r\n\x1a\n"
        assert image.read(4) == b"\x00\x00\x00\r"
        assert image.read(4) == b"IHDR"
        return struct.unpack(">II", image.read(8))


def _free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _clone_server() -> str:
    """Serve the real ASGI clone briefly for browser-level landmark checks."""

    port = _free_loopback_port()
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
        ],
        cwd=SITE_ROOT / "clone",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                with urlopen(f"{base_url}/healthz", timeout=0.2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("the local clone did not become ready for visual testing")
        yield base_url
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_public_desktop_oracles_are_present_at_the_frozen_viewport() -> None:
    """Catch a missing public source frame or an accidental checkout oracle."""

    evidence = SITE_ROOT / "source-evidence"
    observed = {path.name for path in evidence.glob("*.desktop.png")}

    assert observed == PUBLIC_ORACLES
    for name in PUBLIC_ORACLES:
        assert _png_size(evidence / name) == (1191, 979)


def test_fullscreen_search_result_grid_fills_the_content_shell() -> None:
    """Catch the removed assistant rail leaving a fixed-width results column."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(
            viewport={"width": 2559, "height": 1471}, device_scale_factor=1
        )
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(
                    base_url + "/search?query=Deep%20Learning",
                    wait_until="networkidle",
                )
                shell = page.locator(".search-page-layout").bounding_box()
                grid = page.locator(".search-result-grid").first.bounding_box()
                first = page.locator('[data-result-position="1"]').bounding_box()
                fourth = page.locator('[data-result-position="4"]').bounding_box()

                assert shell is not None
                assert grid is not None
                assert first is not None
                assert fourth is not None
                assert abs(grid["x"] - shell["x"]) <= 1
                # The result grid is intentionally narrower than the shell:
                # the live site renders its result column at ~1054-1330px.
                assert grid["width"] <= shell["width"] + 1
                assert grid["width"] >= 1200
                assert abs(first["y"] - fourth["y"]) <= 1
                # First and fourth cards sit inside the (narrower) grid with a
                # small right padding; the grid is four columns, so card five
                # starts the next row.
                assert first["x"] + first["width"] <= grid["x"] + grid["width"] + 1
                fifth = page.locator('[data-result-position="5"]').bounding_box()
                assert fifth is not None
                assert fifth["y"] > first["y"] + first["height"] / 2
        finally:
            context.close()
            browser.close()


def test_fullscreen_search_result_media_keeps_source_ratio_and_equal_height() -> None:
    """Catch wide cards retaining the obsolete fixed-height result covers."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(
            viewport={"width": 2559, "height": 1471}, device_scale_factor=1
        )
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(
                    base_url + "/search?query=Deep%20Learning",
                    wait_until="networkidle",
                )
                covers = [
                    page.locator(
                        f'[data-result-position="{position}"] .search-result-cover'
                    ).bounding_box()
                    for position in range(1, 5)
                ]
                cards = [
                    page.locator(
                        f'[data-result-position="{position}"]'
                    ).bounding_box()
                    for position in range(1, 5)
                ]

                assert all(box is not None for box in covers)
                assert all(box is not None for box in cards)
                cover_boxes = [box for box in covers if box is not None]
                card_boxes = [box for box in cards if box is not None]
                assert max(box["height"] for box in cover_boxes) - min(
                    box["height"] for box in cover_boxes
                ) <= 1
                for box in cover_boxes:
                    assert 1.76 <= box["width"] / box["height"] <= 1.79
                assert max(box["height"] for box in card_boxes) - min(
                    box["height"] for box in card_boxes
                ) <= 1
        finally:
            context.close()
            browser.close()


def test_primary_search_result_grid_uses_the_source_four_column_breakpoint() -> None:
    """Catch the 1692px source cards being squeezed into short or tall columns.

    The live source renders four result columns at the 1692x979 acceptance
    viewport (card x positions ~158/505/852/1199), so the clone grid must
    match that breakpoint.
    """

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(
                    base_url + "/search?query=Deep%20Learning",
                    wait_until="networkidle",
                )
                cards = [
                    page.locator(
                        f'[data-result-position="{position}"]'
                    ).bounding_box()
                    for position in range(1, 6)
                ]
                covers = [
                    page.locator(
                        f'[data-result-position="{position}"] .search-result-cover'
                    ).bounding_box()
                    for position in range(1, 13)
                ]

                assert all(box is not None for box in cards)
                assert all(box is not None for box in covers)
                card_boxes = [box for box in cards if box is not None]
                cover_boxes = [box for box in covers if box is not None]
                assert max(box["y"] for box in card_boxes[:4]) - min(
                    box["y"] for box in card_boxes[:4]
                ) <= 1
                assert card_boxes[4]["y"] > (
                    card_boxes[0]["y"] + card_boxes[0]["height"]
                )
                assert max(box["height"] for box in cover_boxes) - min(
                    box["height"] for box in cover_boxes
                ) <= 1
        finally:
            context.close()
            browser.close()


def test_ai_starter_cards_align_the_source_best_for_row() -> None:
    """Catch variable title wrapping pushing each starter description lower."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(
                    base_url + "/search?query=Deep%20Learning",
                    wait_until="networkidle",
                )
                page.locator(".search-ai-overview summary").click()
                page.wait_for_timeout(300)
                descriptions = page.locator(
                    "[data-ai-starter-card='true'] > p"
                ).all()
                boxes = [description.bounding_box() for description in descriptions]

                assert len(boxes) == 4
                assert all(box is not None for box in boxes)
                description_boxes = [box for box in boxes if box is not None]
                assert max(box["y"] for box in description_boxes) - min(
                    box["y"] for box in description_boxes
                ) <= 1
        finally:
            context.close()
            browser.close()


def test_wide_search_intent_panel_matches_the_user_supplied_geometry() -> None:
    """Catch equal-width intent choices flattening the wide source panel."""

    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(
            viewport={"width": 2239, "height": 979}, device_scale_factor=1
        )
        try:
            with _clone_server() as base_url:
                page = context.new_page()
                page.goto(
                    base_url + "/search?query=Deep%20Learning",
                    wait_until="networkidle",
                )
                panel = page.locator(".search-intent-panel").bounding_box()
                choices = [
                    choice.bounding_box()
                    for choice in page.locator(".search-intent-panel nav a").all()
                ]

                assert panel is not None
                assert len(choices) == 4
                assert all(choice is not None for choice in choices)
                boxes = [choice for choice in choices if choice is not None]
                assert abs(panel["height"] - 218) <= 2
                for box, expected_width in zip(boxes, (255, 278, 332, 391)):
                    assert abs(box["width"] - expected_width) <= 8
                    assert abs(box["height"] - 84) <= 2
                for left, right in zip(boxes, boxes[1:]):
                    assert abs(right["x"] - (left["x"] + left["width"]) - 24) <= 3
        finally:
            context.close()
            browser.close()


def test_public_capture_provenance_keeps_authentication_out_of_oracles() -> None:
    """Catch public visual evidence retaining an authenticated source capture."""

    provenance = json.loads(
        (SITE_ROOT / "source-evidence" / "desktop-public-captures.json").read_text(
            encoding="utf-8"
        )
    )
    retained = [item for item in provenance["observations"] if item.get("artifact")]

    assert {item["actor"] for item in retained} == {"anonymous"}
    assert {Path(item["artifact"]).name for item in retained} == PUBLIC_ORACLES
    for name in PUBLIC_ORACLES:
        raster = (SITE_ROOT / "source-evidence" / name).read_bytes()
        for marker in (
            b"http://",
            b"https://",
            b"Cookie:",
            b"Set-Cookie:",
            b"Authorization:",
            b"Bearer ",
        ):
            assert marker not in raster
    checkout = next(
        item
        for item in provenance["observations"]
        if item["id"] == "authenticated-checkout-display"
    )
    assert checkout["artifact_retained"] is False


def test_visual_oracles_declare_route_specific_semantic_regions() -> None:
    """Catch an oracle that labels unrelated lower-page content as a footer."""

    spec = json.loads(
        (SITE_ROOT / "scope" / "desktop-visual-comparison-current.json").read_text(
            encoding="utf-8"
        )
    )
    checkpoints = json.loads(
        (SITE_ROOT / "scope" / "checkpoints.json").read_text(encoding="utf-8")
    )["checkpoints"]

    assert spec["schema_version"] == (
        "websitebench.offline-clone.visual-comparison-spec.v1"
    )
    assert {checkpoint["id"] for checkpoint in spec["checkpoints"]} == {
        "home.loaded.desktop",
        "browse.loaded.desktop",
        "search.results.desktop",
        "specialization.loaded.desktop",
        "course.loaded.desktop",
        "login.loaded.desktop",
        "help.loaded.desktop",
        "not-found.loaded.desktop",
    }
    expected_regions = {
        "home.loaded.desktop": {"header", "promotion-rail", "primary-content"},
        "browse.loaded.desktop": {"header", "primary-content"},
        "search.results.desktop": {"header", "filters", "results"},
        "specialization.loaded.desktop": {"header", "hero"},
        "course.loaded.desktop": {"header", "hero"},
        "login.loaded.desktop": {"header", "auth-surface"},
        "help.loaded.desktop": {"header", "primary-content"},
        "not-found.loaded.desktop": {"header", "recovery"},
    }
    for checkpoint in spec["checkpoints"]:
        assert checkpoint["viewport"] == VIEWPORT
        regions = {region["id"]: region for region in checkpoint["regions"]}
        assert regions.keys() == expected_regions[checkpoint["id"]]
        assert all(region["threshold"] > 0 for region in regions.values())
        assert all("ignore_regions" not in region for region in regions.values())
        assert all(
            region["x"] + region["width"] <= VIEWPORT["width"]
            and region["y"] + region["height"] <= VIEWPORT["height"]
            for region in regions.values()
        )
    by_id = {checkpoint["id"]: checkpoint for checkpoint in checkpoints}
    for checkpoint in spec["checkpoints"]:
        declared = by_id[checkpoint["id"]]
        assert declared["evidence_kind"] == "current-direct"
        assert Path(declared["visual_contract"]["source_artifact_path"]).name == Path(
            checkpoint["source"]["path"]
        ).name


def test_candidate_capture_plan_writes_every_declared_visual_candidate() -> None:
    """Catch capture output drifting away from the comparison spec's inputs."""

    from capture_desktop_visuals import declared_candidate_capture_plan

    spec = json.loads(
        (SITE_ROOT / "scope" / "desktop-visual-comparison-current.json").read_text(
            encoding="utf-8"
        )
    )

    expected = {
        checkpoint["id"]: (SITE_ROOT / "scope" / checkpoint["candidate"]["path"])
        for checkpoint in spec["checkpoints"]
    }
    actual = {
        capture.checkpoint_id: capture.output_path
        for capture in declared_candidate_capture_plan()
    }

    assert actual == expected


def test_public_home_rasters_are_declared_with_source_provenance() -> None:
    """Catch shipped source-derived homepage art escaping the asset closure."""

    manifest = json.loads(
        (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
    )
    expected_runtime_paths = {
        "clone/static/home/current-promo-plus.png",
        "clone/static/home/current-promo-teams.png",
        "clone/static/home/current-promo-third.png",
        "clone/static/home/current-promo-barriers.png",
        "clone/static/home/current-promo-teams-small.png",
        "clone/static/source-home-career-promo.png",
        "clone/static/source-home-google-promo.png",
        "clone/static/source-home-trend-google-ai.png",
        "clone/static/source-home-trend-google-analytics.png",
        "clone/static/source-home-trend-microsoft-qa.png",
    }
    rows = {
        item["runtime_path"]: item
        for item in manifest["assets"]
        if item["runtime_path"] in expected_runtime_paths
    }

    assert rows.keys() == expected_runtime_paths
    for runtime_path, row in rows.items():
        source = SITE_ROOT / row["source_path"]
        runtime = SITE_ROOT / runtime_path
        assert source.is_file() and runtime.is_file()
        assert source.read_bytes() == runtime.read_bytes()
        assert row["evidence_kind"] == "current-direct"
        assert row["capture_id"] in {
            "public-home-desktop",
            "coursera-home-login-current-state-open-home",
            "coursera-home-promo-current-2026-08-21",
        }


def test_public_routes_keep_desktop_shell_landmarks_before_screenshots(
    tmp_path: Path,
) -> None:
    """Catch desktop CSS or templates removing a stable public route landmark."""

    playwright = pytest.importorskip("playwright.sync_api")
    try:
        with playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            try:
                screenshots: dict[str, Path] = {}
                with _clone_server() as base_url:
                    for route in PUBLIC_ROUTES:
                        page = context.new_page()
                        response = page.goto(base_url + route.path, wait_until="networkidle")
                        assert response is not None
                        assert response.status in {200, 404}
                        assert page.locator(route.header).is_visible()
                        assert page.locator(route.footer).is_visible()
                        assert page.locator(route.landmark).is_visible()
                        screenshot = tmp_path / f"candidate-{route.checkpoint_id}.png"
                        page.screenshot(path=str(screenshot))
                        assert _png_size(screenshot) == (1692, 979)
                        screenshots[route.checkpoint_id] = screenshot
                        page.close()
                from websitebench.offline_clone.comparison_tools import compare_visual_spec

                spec = json.loads(
                    (SITE_ROOT / "scope" / "desktop-visual-comparison-current.json").read_text(
                        encoding="utf-8"
                    )
                )
                for checkpoint in spec["checkpoints"]:
                    checkpoint["source"]["path"] = str(
                        (SITE_ROOT / "scope" / checkpoint["source"]["path"]).resolve()
                    )
                    checkpoint["candidate"]["path"] = str(
                        screenshots[checkpoint["id"]].resolve()
                    )
                diagnostic_spec = tmp_path / "desktop-visual-comparison.json"
                diagnostic_spec.write_text(
                    json.dumps(spec, ensure_ascii=False), encoding="utf-8"
                )
                report = compare_visual_spec(
                    spec_path=diagnostic_spec,
                    output_path=tmp_path / "visual-comparison-report.json",
                    heatmap_dir=tmp_path / "visual-heatmaps",
                )
                assert report["counts"]["checkpoints_total"] == 8
                assert report["counts"]["regions_total"] == 18
                assert report["status"] in {"passed", "failed"}
                assert sum(
                    len(cp["regions"]) for cp in report["checkpoints"]
                ) == 18
            finally:
                context.close()
                browser.close()
    except Exception as error:
        if "error while loading shared libraries" in str(error):
            pytest.skip(f"Playwright browser unavailable in this environment: {error}")
        raise
