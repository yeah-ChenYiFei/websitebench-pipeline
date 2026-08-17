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
VIEWPORT = {"width": 1191, "height": 979}
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
        "/search?q=Deep+Learning", "search.results.desktop", ".search-source-layout"
    ),
    DesktopRoute(
        "/specializations/deep-learning", "specialization.loaded.desktop", ".program-hero"
    ),
    DesktopRoute(
        "/learn/neural-networks-deep-learning",
        "course.loaded.desktop",
        ".source-course-hero",
    ),
    DesktopRoute("/login", "login.loaded.desktop", ".auth-modal-card"),
    DesktopRoute(
        "/help",
        "help.loaded.desktop",
        ".help-article",
        header=".help-center-header",
        footer=".help-feedback",
    ),
    DesktopRoute("/websitebench-not-found-33", "not-found.loaded.desktop", ".not-found"),
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
        (SITE_ROOT / "scope" / "desktop-visual-comparison.json").read_text(
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
        "home.loaded.desktop": {"header", "promotion-rail", "privacy-banner"},
        "browse.loaded.desktop": {"header", "category-navigation", "browse-results"},
        "search.results.desktop": {"header", "search-results", "assistant-panel"},
        "specialization.loaded.desktop": {
            "header",
            "program-hero",
            "program-course-list",
        },
        "course.loaded.desktop": {"header", "course-hero", "course-navigation"},
        "login.loaded.desktop": {
            "page-header",
            "identity-modal",
            "modal-lower-area",
        },
        "help.loaded.desktop": {"help-header", "help-article", "help-feedback"},
        "not-found.loaded.desktop": {
            "header",
            "route-recovery",
            "shared-footer",
        },
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
        (SITE_ROOT / "scope" / "desktop-visual-comparison.json").read_text(
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
        assert row["capture_id"] == "public-home-desktop"


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
                        assert _png_size(screenshot) == (1191, 979)
                        screenshots[route.checkpoint_id] = screenshot
                        page.close()
                from websitebench.offline_clone.comparison_tools import compare_visual_spec

                spec = json.loads(
                    (SITE_ROOT / "scope" / "desktop-visual-comparison.json").read_text(
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
                assert report["counts"] == {
                    "checkpoints_total": 8,
                    "checkpoints_passed": 8,
                    "regions_total": 24,
                    "regions_passed": 24,
                }
                assert report["status"] == "passed"
            finally:
                context.close()
                browser.close()
    except Exception as error:
        if "error while loading shared libraries" in str(error):
            pytest.skip(f"Playwright browser unavailable in this environment: {error}")
        raise
