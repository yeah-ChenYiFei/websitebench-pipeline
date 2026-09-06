"""Capture the two G3-A candidate viewports with an isolated local browser."""

from __future__ import annotations

import argparse
import contextlib
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
CAPTURES = [
    ("home.default", "/", "home-default-1440x900.png"),
    (
        "course-overview.default",
        "/courses/6-006-introduction-to-algorithms-fall-2011/",
        "course-overview-default-1440x900.png",
    ),
]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_ready(origin: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 20
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", required=True)
    args = parser.parse_args()
    if not args.iteration.replace("-", "").isalnum():
        raise SystemExit("iteration must contain only letters, digits, and hyphens")
    output = SITE / "artifacts" / "offline-clone" / "g3a" / args.iteration / "candidate"
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
            )

            def isolate(route: object) -> None:
                request_url = route.request.url  # type: ignore[attr-defined]
                parsed = urlparse(request_url)
                if parsed.hostname in {"127.0.0.1", "localhost"}:
                    route.continue_()  # type: ignore[attr-defined]
                    return
                blocked.append(request_url)
                route.abort()  # type: ignore[attr-defined]

            context.route("**/*", isolate)
            page = context.new_page()
            for checkpoint_id, path, filename in CAPTURES:
                response = page.goto(origin + path, wait_until="networkidle")
                assert response is not None and response.status == 200
                page.screenshot(
                    path=output / filename,
                    full_page=False,
                    animations="disabled",
                    caret="hide",
                )
                rows.append(
                    {
                        "checkpoint_id": checkpoint_id,
                        "path": path,
                        "raster": (output / filename).relative_to(SITE).as_posix(),
                        "viewport": {"width": 1440, "height": 900},
                    }
                )
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
        "schema_version": "mit-ocw.g3a-candidate-capture.v1",
        "iteration": args.iteration,
        "browser_remote_requests": 0,
        "captures": rows,
    }
    report_path = output.parent / "capture-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
