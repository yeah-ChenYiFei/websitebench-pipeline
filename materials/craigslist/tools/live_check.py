"""Live-equivalent browser verification for the craigslist clone.

The repository's `verify --section live` runner requires an OS-level candidate
sandbox (landlock/seccomp) that this execution environment cannot provide
(`candidate sandbox unavailable: [Errno 95]`). This script performs the same
declared live assertions directly with Playwright against a locally booted
clone, so the evidence is equivalent in substance:

* every checkpoint path answers HTTP 200 (or the declared status);
* every page renders a non-empty <title>;
* no page overflows horizontally in its frozen viewport;
* zero outbound (non-same-origin) runtime requests are observed; and
* screenshots are captured for the visual record.

It is a diagnostic aid produced by the agent; it does not change the
repository's `verify` report status (which stays `incomplete` in this
environment for the sandbox reason above).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[3]
SITE = REPO / "materials" / "craigslist"
CHECKPOINTS = json.loads((SITE / "scope" / "checkpoints.json").read_text())
VERIFY = json.loads((SITE / "scope" / "verify.json").read_text())
DECLARED_STATUS = {k: int(v) for k, v in (VERIFY.get("status") or {}).items()}
DEFERRED = set(VERIFY.get("deferred") or {})
PORT = 8471
BASE = f"http://127.0.0.1:{PORT}"


def main() -> int:
    db_dir = Path(tempfile.mkdtemp(prefix="craigslist-live-"))
    env = dict(os.environ)
    env["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(db_dir / "craigslist.sqlite3")
    server = subprocess.Popen(
        [
            str(REPO / ".venv" / "bin" / "python"),
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        cwd=SITE / "clone",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                import urllib.request

                with urllib.request.urlopen(f"{BASE}/healthz", timeout=2) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(1)
        else:
            print("server did not become healthy")
            return 2

        results: list[dict] = []
        viewports = CHECKPOINTS["viewports"]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                args=["--no-sandbox", "--disable-gpu"]
            )
            for checkpoint in CHECKPOINTS["checkpoints"]:
                vp = viewports.get(checkpoint.get("viewport", "desktop"), viewports["desktop"])
                context = browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
                    ),
                )
                outbound: list[str] = []
                page = context.new_page()
                page.on("request", lambda request: outbound.append(request.url))

                clone_path = checkpoint.get("clone_path") or checkpoint.get("requested_url") or "/"
                url = BASE + clone_path
                response = page.goto(url, wait_until="networkidle", timeout=20000)
                status = response.status if response else None
                title = page.title()
                overflow = page.evaluate(
                    "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
                )
                route_id = checkpoint.get("route_id", "")
                expected = DECLARED_STATUS.get(route_id, 200)
                if route_id in DEFERRED and status in (401, 302, 303):
                    # authenticated surface: the anonymous diagnostic expects
                    # the sign-in/permission boundary, not the member page
                    expected = status
                screenshot_dir = SITE / "artifacts" / "live-equivalent"
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                shot = screenshot_dir / f"{checkpoint['id']}.png"
                page.screenshot(path=str(shot), full_page=False)
                context.close()

                escaped = [
                    url for url in outbound
                    if not url.startswith(BASE) and not url.startswith("data:")
                ]
                ok = status == expected and bool(title) and not overflow and not escaped
                results.append(
                    {
                        "id": checkpoint["id"],
                        "expected_status": expected,
                        "status": status,
                        "title_present": bool(title),
                        "horizontal_overflow": bool(overflow),
                        "outbound_requests": escaped,
                        "ok": ok,
                        "screenshot": str(shot),
                    }
                )
            browser.close()

        passed = sum(1 for row in results if row["ok"])
        report = {
            "schema_version": "offline-clone.live-equivalent.v1",
            "authority": "diagnostic-only",
            "site_id": "craigslist",
            "checkpoints": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "rows": results,
        }
        out = SITE / "artifacts" / "offline-clone" / "live-equivalent-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        for row in results:
            if not row["ok"]:
                print("FAIL:", row["id"], row)
        return 0 if passed == len(results) else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
