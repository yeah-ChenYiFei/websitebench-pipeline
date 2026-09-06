"""Create-only native selector captures for the four G3-C home carousels."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import sync_playwright


SITE = Path(__file__).resolve().parents[1]
CLONE = SITE / "clone"
SOURCE = SITE / "source-current" / "g3c" / "components"
COMPONENTS = [
    ("promo", ".home-promo", "carousel-promo-batch2.png", 1440, 200),
    ("featured-courses", "[data-wb-component='featured-courses']", "carousel-featured-courses-batch2.png", 1250, 447),
    ("new-courses", "[data-wb-component='new-courses']", "carousel-new-courses-batch2.png", 1250, 448),
    ("stories", "[data-wb-component='stories']", "carousel-stories-batch2.png", 1440, 653),
]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_ready(origin: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"candidate server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(origin + "/", timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("candidate server did not become ready")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def relative(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace(os.sep, "/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", required=True)
    args = parser.parse_args()
    if not args.iteration.replace("-", "").isalnum():
        raise SystemExit("iteration must contain only letters, digits, and hyphens")

    output = SITE / "artifacts" / "offline-clone" / "g3c-components" / args.iteration
    if output.exists():
        raise SystemExit(f"create-only output already exists: {output}")
    candidate = output / "candidate"
    candidate.mkdir(parents=True)

    for _name, _selector, source_name, width, height in COMPONENTS:
        source = SOURCE / source_name
        assert source.is_file() and not source.is_symlink()
        assert dimensions(source) == (width, height), source

    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=CLONE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    blocked: list[str] = []
    rows: list[dict[str, object]] = []
    try:
        wait_ready(origin, process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=1,
                color_scheme="light",
                reduced_motion="reduce",
                locale="en-US",
                timezone_id="America/Toronto",
            )

            def isolate(route: object) -> None:
                url = route.request.url  # type: ignore[attr-defined]
                if urlparse(url).hostname in {"127.0.0.1", "localhost"}:
                    route.continue_()  # type: ignore[attr-defined]
                else:
                    blocked.append(url)
                    route.abort()  # type: ignore[attr-defined]

            context.route("**/*", isolate)
            page = context.new_page()
            response = page.goto(origin + "/?state=carousel-second-batches", wait_until="networkidle")
            assert response is not None and response.status == 200
            page.evaluate("document.fonts && document.fonts.ready")
            for name, selector, source_name, width, height in COMPONENTS:
                locator = page.locator(selector)
                assert locator.count() == 1, (name, locator.count())
                locator.scroll_into_view_if_needed()
                box = locator.bounding_box()
                assert box is not None
                assert abs(box["width"] - width) < 0.01, (name, box)
                assert abs(box["height"] - height) < 0.01, (name, box)
                raster = candidate / f"{name}.png"
                page.screenshot(
                    path=raster,
                    clip={"x": box["x"], "y": box["y"], "width": width, "height": height},
                    animations="disabled",
                    caret="hide",
                )
                assert dimensions(raster) == (width, height)
                rows.append({
                    "id": name,
                    "selector": selector,
                    "source": f"source-current/g3c/components/{source_name}",
                    "candidate": raster.relative_to(SITE).as_posix(),
                    "bounding_box": box,
                    "dimensions": {"width": width, "height": height},
                    "sha256": sha256(raster),
                    "bytes": raster.stat().st_size,
                })

            response = page.goto(origin + "/", wait_until="networkidle")
            assert response is not None and response.status == 200
            home_raster = candidate / "home-default-1440x900.png"
            page.screenshot(path=home_raster, full_page=False, animations="disabled", caret="hide")
            assert dimensions(home_raster) == (1440, 900)
            browser.close()
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert not blocked, f"remote browser requests attempted: {blocked}"
    report = {
        "schema_version": "mit-ocw.g3c-component-capture.v1",
        "iteration": args.iteration,
        "source_policy": {
            "native_selector_capture": True,
            "source_stretched_or_composited": False,
            "candidate_resized_or_masked": False,
        },
        "environment": {
            "viewport": {"width": 1440, "height": 900},
            "device_scale_factor": 1,
            "color_scheme": "light",
            "locale": "en-US",
            "timezone_id": "America/Toronto",
        },
        "browser_remote_requests": 0,
        "component_count": 4,
        "components": rows,
        "home_default_regression": {
            "source": "source-current/g3c/viewports-v1/home-default-1440x900.png",
            "candidate": home_raster.relative_to(SITE).as_posix(),
            "sha256": sha256(home_raster),
            "bytes": home_raster.stat().st_size,
        },
    }
    report_path = output / "capture-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    spec_rows: list[dict[str, object]] = []
    for row in rows:
        width = int(row["dimensions"]["width"])  # type: ignore[index]
        height = int(row["dimensions"]["height"])  # type: ignore[index]
        spec_rows.append({
            "id": f"home-carousel-{row['id']}",
            "source": {"path": relative(SITE / str(row["source"]), output)},
            "candidate": {"path": relative(SITE / str(row["candidate"]), output)},
            "viewport": {"width": width, "height": height},
            "capture_mode": "viewport",
            "regions": [{"id": "full", "box": "full", "metric": "normalized_mae", "threshold": 0.06}],
        })
    spec_rows.append({
        "id": "home-default-regression",
        "source": {"path": relative(SITE / report["home_default_regression"]["source"], output)},  # type: ignore[index]
        "candidate": {"path": relative(home_raster, output)},
        "viewport": {"width": 1440, "height": 900},
        "capture_mode": "viewport",
        "regions": [{"id": "full", "box": "full", "metric": "normalized_mae", "threshold": 0.06}],
    })
    spec = {"schema_version": "websitebench.offline-clone.visual-comparison-spec.v1", "checkpoints": spec_rows}
    (output / "visual-comparison-spec.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"components": 4, "remote_requests": 0, "output": output.relative_to(SITE).as_posix()}, sort_keys=True))


if __name__ == "__main__":
    main()
