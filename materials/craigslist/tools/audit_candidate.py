"""Anti-cheat candidate audit.

Boots a candidate and runs the same machine checks the evaluation would:

* smoke: core routes answer the declared status and the health contract;
* persistence: a stateful journey survives refresh (the frontend-only
  shortcut loses state -> FAIL);
* network closure: zero outbound requests and no cross-origin iframe
  (a proxy/iframe candidate -> FAIL).

Usage:
    python audit_candidate.py <candidate-dir> <port> --reference <ref-port>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[3]
SITE = REPO / "materials" / "craigslist"


def _wait_healthy(base: str, timeout: int = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base}/__websitebench/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def audit(candidate_dir: Path, port: int, reference_port: int | None) -> dict:
    env = dict(os.environ)
    env["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
        Path(tempfile.mkdtemp(prefix="cl-audit-")) / "craigslist.sqlite3"
    )
    server = subprocess.Popen(
        [str(REPO / ".venv" / "bin" / "python"), "-m", "uvicorn", "app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=candidate_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    report: dict = {"candidate": str(candidate_dir), "checks": {}}
    try:
        healthy = _wait_healthy(base)
        report["checks"]["health"] = healthy

        # 1. smoke routes
        smoke_paths = ["/", "/toronto/housing/", "/toronto/housing/sub/", "/account/login"]
        smoke_ok = True
        for path in smoke_paths:
            try:
                with urlopen(base + path, timeout=5) as response:
                    ok = response.status == 200
            except Exception:
                ok = False
            smoke_ok = smoke_ok and ok
        report["checks"]["smoke_routes"] = smoke_ok

        # 2. persistence probe: register/login flow must keep session + data
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
            context = browser.new_context()
            page = context.new_page()
            outbound: list[str] = []
            page.on("request", lambda request: outbound.append(request.url))
            try:
                page.goto(base + "/account/login", wait_until="networkidle", timeout=15000)
                page.fill("#email", "poster@example.com")
                page.fill("#password", "Websitebench1!")
                page.click("button[type='submit']")
                page.wait_for_load_state("networkidle", timeout=15000)
                home_url = page.url
                login_ok = "/account/home" in home_url
                page.reload(wait_until="networkidle", timeout=15000)
                after_reload = "/account/home" in page.url
                page.goto(base + "/account/home", wait_until="networkidle", timeout=15000)
                session_persists = page.url.endswith("/account/home") and "log in to continue" not in page.text_content("body")
                report["checks"]["login_persists_across_refresh"] = login_ok and after_reload and session_persists
            except Exception as exc:
                report["checks"]["login_persists_across_refresh"] = False
                report["error"] = str(exc)
            # 3. network + iframe audit
            escaped = [u for u in outbound if not u.startswith(base)]
            report["checks"]["no_outbound_requests"] = not escaped
            report["outbound"] = escaped[:5]
            iframe_srcs = page.eval_on_selector_all(
                "iframe", "els => els.map(e => e.src)"
            ) if page.query_selector("iframe") else []
            report["checks"]["no_cross_origin_iframe"] = all(
                src.startswith(base) for src in iframe_srcs
            )
            report["iframes"] = iframe_srcs
            browser.close()
        return report
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    candidate_dir = Path(sys.argv[1])
    port = int(sys.argv[2])
    reference_port = None
    if "--reference" in sys.argv:
        reference_port = int(sys.argv[sys.argv.index("--reference") + 1])
    report = audit(candidate_dir, port, reference_port)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
