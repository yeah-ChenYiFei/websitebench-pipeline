"""Capture only G4-affected visual checkpoints with loopback-only networking."""

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
SCOPE = SITE / "scope"
BASE_SPEC = SCOPE / "visual-g3c-v8-spec.json"
AFFECTED = {
    "home-default",
    "catalog-default",
    "newsletter-default",
    "course-download-default",
    "video-resource-default",
    "video-static-disabled",
    "catalog-second-batch",
    "catalog-math",
    "catalog-math-undergraduate",
    "catalog-course-number",
    "catalog-empty",
    "catalog-error",
    "catalog-retry-stale",
    "catalog-reload-recovered",
    "catalog-resources",
}
AUXILIARY = {
    "external-boundary-default": "/external-boundary/?url=https%3A%2F%2Fgiving.mit.edu%2Fgive%2Fto%2Focw%2F",
    "data-boundary-default": "/data-boundary/",
}


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", required=True)
    args = parser.parse_args()
    if not args.iteration.replace("-", "").isalnum():
        raise SystemExit("iteration must contain only letters, digits, and hyphens")
    output = SITE / "artifacts" / "offline-clone" / "g4" / args.iteration
    if output.exists():
        raise SystemExit(f"refusing to overwrite create-only output: {output}")
    candidate = output / "candidate"
    candidate.mkdir(parents=True)

    base = json.loads(BASE_SPEC.read_text(encoding="utf-8"))
    rows = [row for row in base["checkpoints"] if row["id"] in AFFECTED]
    assert {row["id"] for row in rows} == AFFECTED and len(rows) == 15
    checkpoints = json.loads((SCOPE / "checkpoints.json").read_text(encoding="utf-8"))["checkpoints"]
    route_by_slug = {row["id"].replace(".", "-"): row["clone_path"] for row in checkpoints}

    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=CLONE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(origin + "/healthz", timeout=0.5) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("candidate server did not become ready")

    blocked: list[str] = []
    local_404: list[str] = []
    failed: list[str] = []
    console: list[str] = []
    page_errors: list[str] = []
    captures: list[dict[str, object]] = []
    try:
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
                if parsed.hostname in {"127.0.0.1", "localhost"} or parsed.scheme == "data":
                    route.continue_()  # type: ignore[attr-defined]
                else:
                    blocked.append(request_url)
                    route.abort("blockedbyclient")  # type: ignore[attr-defined]

            context.route("**/*", isolate)
            context.on("response", lambda response: local_404.append(response.url) if response.status == 404 else None)
            context.on("requestfailed", lambda request: failed.append(request.url))
            page = context.new_page()
            page.on("console", lambda message: console.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            for checkpoint in rows:
                checkpoint_id = checkpoint["id"]
                route = route_by_slug[checkpoint_id]
                response = page.goto(origin + route, wait_until="networkidle")
                assert response is not None and response.status == 200, (checkpoint_id, route)
                page.evaluate("document.fonts && document.fonts.ready")
                path = candidate / f"{checkpoint_id}-1440x900.png"
                page.screenshot(path=path, full_page=False, animations="disabled", caret="hide")
                captures.append({"id": checkpoint_id, "route": route, "path": path.relative_to(SITE).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path), "kind": "formal-source-backed"})
            for checkpoint_id, route in AUXILIARY.items():
                response = page.goto(origin + route, wait_until="networkidle")
                assert response is not None and response.status == 200
                path = candidate / f"{checkpoint_id}-1440x900.png"
                page.screenshot(path=path, full_page=False, animations="disabled", caret="hide")
                captures.append({"id": checkpoint_id, "route": route, "path": path.relative_to(SITE).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path), "kind": "local-only-no-source-visual-contract"})
            browser.close()
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert not blocked and not local_404 and not failed and not console and not page_errors, {
        "blocked": blocked, "local_404": local_404, "failed": failed, "console": console, "page_errors": page_errors
    }
    spec = {"schema_version": base["schema_version"], "checkpoints": []}
    for row in rows:
        clone = json.loads(json.dumps(row))
        source = (SCOPE / clone["source"]["path"]).resolve()
        clone["source"]["path"] = str(source)
        clone["candidate"]["path"] = str((candidate / f'{clone["id"]}-1440x900.png').resolve())
        spec["checkpoints"].append(clone)
    spec_path = output / "visual-spec.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": "mit-ocw.g4-affected-visual-capture.v1",
        "iteration": args.iteration,
        "formal_source_backed": len(rows),
        "auxiliary_local_only": len(AUXILIARY),
        "remote_requests": 0,
        "local_404": 0,
        "failed_requests": 0,
        "console_errors": 0,
        "page_errors": 0,
        "captures": captures,
        "spec": spec_path.relative_to(SITE).as_posix(),
    }
    (output / "capture-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": output.relative_to(SITE).as_posix(), "formal": len(rows), "auxiliary": len(AUXILIARY), "remote": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
