"""Capture G3-C exact-source checkpoints in an isolated local browser."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


SITE = Path(__file__).resolve().parents[1]
CLONE = SITE / "clone"
CHECKPOINTS = SITE / "scope" / "checkpoints.json"


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
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", required=True)
    parser.add_argument(
        "--capture-mode",
        choices=("viewport", "full-page"),
        default="viewport",
        help="capture the 1440x900 viewport or the complete lazily loaded page",
    )
    parser.add_argument(
        "--checkpoint",
        action="append",
        default=[],
        help="capture only this checkpoint id; repeat for multiple checkpoints",
    )
    args = parser.parse_args()
    if not args.iteration.replace("-", "").isalnum():
        raise SystemExit("iteration must contain only letters, digits, and hyphens")

    checkpoint_payload = json.loads(CHECKPOINTS.read_text())
    captures = [row for row in checkpoint_payload["checkpoints"] if "visual_contract" in row]
    assert len(captures) == 35
    if args.checkpoint:
        requested = set(args.checkpoint)
        available = {str(row["id"]) for row in captures}
        unknown = sorted(requested - available)
        if unknown:
            raise SystemExit(f"unknown visual checkpoint(s): {', '.join(unknown)}")
        captures = [row for row in captures if str(row["id"]) in requested]
    output = SITE / "artifacts" / "offline-clone" / "g3c" / args.iteration / "candidate"
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)

    port = free_port()
    origin = f"http://127.0.0.1:{port}"
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
                request_url = route.request.url  # type: ignore[attr-defined]
                parsed = urlparse(request_url)
                if parsed.hostname in {"127.0.0.1", "localhost"}:
                    route.continue_()  # type: ignore[attr-defined]
                else:
                    blocked.append(request_url)
                    route.abort()  # type: ignore[attr-defined]

            context.route("**/*", isolate)
            page = context.new_page()
            for checkpoint in captures:
                checkpoint_id = checkpoint["id"]
                path = checkpoint["clone_path"]
                suffix = "1440xfull" if args.capture_mode == "full-page" else "1440x900"
                filename = checkpoint_id.replace(".", "-") + f"-{suffix}.png"
                response = page.goto(origin + path, wait_until="networkidle")
                assert response is not None and response.status == 200, (checkpoint_id, path)
                page.evaluate("document.fonts && document.fonts.ready")
                scroll_positions: list[int] = [0]
                if args.capture_mode == "full-page":
                    stable_height = 0
                    stable_count = 0
                    for _ in range(12):
                        height = int(
                            page.evaluate(
                                "Math.max(document.body?.scrollHeight || 0, "
                                "document.documentElement.scrollHeight || 0)"
                            )
                        )
                        page.evaluate("height => scrollTo(0, height)", height)
                        scroll_positions.append(height)
                        page.wait_for_timeout(250)
                        new_height = int(
                            page.evaluate(
                                "Math.max(document.body?.scrollHeight || 0, "
                                "document.documentElement.scrollHeight || 0)"
                            )
                        )
                        if new_height == stable_height:
                            stable_count += 1
                        else:
                            stable_count = 0
                        stable_height = new_height
                        if stable_count >= 2:
                            break
                    page.evaluate("scrollTo(0, 0)")
                    page.wait_for_timeout(250)
                document_height = int(
                    page.evaluate(
                        "Math.max(document.body?.scrollHeight || 0, "
                        "document.documentElement.scrollHeight || 0)"
                    )
                )
                raster = output / filename
                page.screenshot(
                    path=raster,
                    full_page=args.capture_mode == "full-page",
                    animations="disabled",
                    caret="hide",
                )
                rows.append({
                    "checkpoint_id": checkpoint_id,
                    "path": path,
                    "raster": raster.relative_to(SITE).as_posix(),
                    "sha256": sha256(raster),
                    "bytes": raster.stat().st_size,
                    "viewport": {"width": 1440, "height": 900},
                    "capture_mode": args.capture_mode,
                    "document_height": document_height,
                    "scroll_positions": scroll_positions,
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
        "schema_version": "mit-ocw.g3c-candidate-capture.v1",
        "iteration": args.iteration,
        "capture_mode": args.capture_mode,
        "environment": {
            "viewport": {"width": 1440, "height": 900},
            "device_scale_factor": 1,
            "color_scheme": "light",
            "locale": "en-US",
            "timezone_id": "America/Toronto",
        },
        "browser_remote_requests": 0,
        "capture_count": len(rows),
        "captures": rows,
    }
    report_path = output.parent / "capture-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"capture_count": len(rows), "remote_requests": 0, "report": str(report_path.relative_to(SITE))}, sort_keys=True))


if __name__ == "__main__":
    main()
