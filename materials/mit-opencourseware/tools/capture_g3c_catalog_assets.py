"""Create-only visual recheck for the two G3-C catalog asset states."""

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
CHECKPOINTS = SITE / "scope" / "checkpoints.json"
IDS = ("catalog.math-undergraduate", "catalog.course-number")
VIEWPORT_SOURCES = {
    "catalog.math-undergraduate": "source-current/g3c/viewports-v1/catalog-math-undergraduate-1440x900.png",
    "catalog.course-number": "source-current/g3c/viewports-v1/catalog-course-number-1440x900.png",
}


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


def relative(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace(os.sep, "/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", required=True)
    args = parser.parse_args()
    if not args.iteration.replace("-", "").isalnum():
        raise SystemExit("iteration must contain only letters, digits, and hyphens")

    output = SITE / "artifacts" / "offline-clone" / "g3c-catalog-assets" / args.iteration
    if output.exists():
        raise SystemExit(f"create-only output already exists: {output}")
    candidate = output / "candidate"
    candidate.mkdir(parents=True)

    checkpoint_payload = json.loads(CHECKPOINTS.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in checkpoint_payload["checkpoints"]}
    rows = [by_id[checkpoint_id] for checkpoint_id in IDS]
    assert all("visual_contract" in row for row in rows)
    for checkpoint_id in IDS:
        source = SITE / VIEWPORT_SOURCES[checkpoint_id]
        assert source.is_file() and not source.is_symlink()
        with Image.open(source) as image:
            assert image.size == (1440, 900)

    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=CLONE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    blocked: list[str] = []
    captures: list[dict[str, object]] = []
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
                request_url = route.request.url  # type: ignore[attr-defined]
                if urlparse(request_url).hostname in {"127.0.0.1", "localhost"}:
                    route.continue_()  # type: ignore[attr-defined]
                else:
                    blocked.append(request_url)
                    route.abort()  # type: ignore[attr-defined]

            context.route("**/*", isolate)
            page = context.new_page()
            for checkpoint in rows:
                response = page.goto(origin + str(checkpoint["clone_path"]), wait_until="networkidle")
                assert response is not None and response.status == 200
                page.evaluate("document.fonts && document.fonts.ready")
                local_images = page.locator(
                    '[data-wb-component="catalog-results"] img[data-wb-asset-source][src^="/g3c-catalog-assets/"]'
                )
                assert local_images.count() == 3, (checkpoint["id"], local_images.count())
                assert all(local_images.nth(index).evaluate("image => image.complete && image.naturalWidth > 0") for index in range(3))
                visible_placeholders = page.locator(
                    '[data-wb-component="catalog-results"] .placeholder'
                ).evaluate_all(
                    "nodes => nodes.filter(node => { const r=node.getBoundingClientRect(); "
                    "return r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth; }).length"
                )
                assert visible_placeholders == 0, (checkpoint["id"], visible_placeholders)
                raster = candidate / (str(checkpoint["id"]).replace(".", "-") + "-1440x900.png")
                page.screenshot(path=raster, full_page=False, animations="disabled", caret="hide")
                with Image.open(raster) as image:
                    assert image.size == (1440, 900)
                captures.append({
                    "checkpoint_id": checkpoint["id"],
                    "path": checkpoint["clone_path"],
                    "raster": raster.relative_to(SITE).as_posix(),
                    "sha256": sha256(raster),
                    "bytes": raster.stat().st_size,
                    "visible_local_catalog_images": 3,
                    "visible_placeholders": 0,
                })
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
        "schema_version": "mit-ocw.g3c-catalog-asset-capture.v1",
        "iteration": args.iteration,
        "environment": {
            "viewport": {"width": 1440, "height": 900},
            "device_scale_factor": 1,
            "color_scheme": "light",
            "locale": "en-US",
            "timezone_id": "America/Toronto",
        },
        "browser_remote_requests": 0,
        "capture_count": 2,
        "captures": captures,
    }
    (output / "capture-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    spec_rows: list[dict[str, object]] = []
    for checkpoint, capture in zip(rows, captures, strict=True):
        contract = checkpoint["visual_contract"]
        regions = [{"id": "full", "box": "full", "metric": "normalized_mae", "threshold": 0.06}]
        for region in [*contract["semantic_regions"], *contract.get("media_regions", [])]:
            regions.append({
                "id": region["id"],
                **{key: int(region[key]) for key in ("x", "y", "width", "height")},
                "metric": "normalized_mae",
                "threshold": 0.06,
            })
        spec_rows.append({
            "id": str(checkpoint["id"]).replace(".", "-"),
            "source": {"path": relative(SITE / VIEWPORT_SOURCES[str(checkpoint["id"])], output)},
            "candidate": {"path": relative(SITE / capture["raster"], output)},
            "viewport": {"width": 1440, "height": 900},
            "capture_mode": "viewport",
            "regions": regions,
        })
    spec = {"schema_version": "websitebench.offline-clone.visual-comparison-spec.v1", "checkpoints": spec_rows}
    (output / "visual-comparison-spec.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"captures": 2, "remote_requests": 0, "output": output.relative_to(SITE).as_posix()}))


if __name__ == "__main__":
    main()
