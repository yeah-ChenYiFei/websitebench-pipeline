"""Launch all eight offline-clone fixture apps as detached processes.

Usage:
  python scripts/serve_all_clones.py start   # spawn one stable uvicorn per site
  python scripts/serve_all_clones.py status  # poll /healthz and print URLs
  python scripts/serve_all_clones.py urls    # print the fixed review URLs
  python scripts/serve_all_clones.py stop    # stop only recorded processes

PIDs are recorded in ``test-output/serve-clones-pids.json``. Runtime data and
logs remain outside candidate bytes and are isolated per site. The launcher is
cross-platform; it intentionally does not enable reload so a user review stays
bound to one stable process identity.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PID_FILE = REPO / "test-output" / "serve-clones-pids.json"
RUNTIME_ROOT = REPO / "test-output" / "frontend-user-review-runtime"
LOG_ROOT = REPO / "test-output" / "serve-logs"
SITES = [
    ("capterra", 8451),
    ("taskrabbit", 8452),
    ("petfinder", 8453),
    ("edx", 8454),
    ("etsy", 8455),
    ("eventbrite", 8456),
    ("imdb", 8457),
    ("change", 8458),
]


def _python() -> Path:
    candidates = (
        REPO / ".venv" / "bin" / "python",
        REPO / ".venv" / "Scripts" / "python.exe",
    )
    return next((path for path in candidates if path.exists()), Path(sys.executable))


def _healthy(port: int) -> tuple[bool, str]:
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read().decode("utf-8")
        payload = json.loads(body)
        detail = str(payload.get("stage") or payload.get("status") or "healthy")
        return True, detail
    except Exception as error:  # noqa: BLE001
        return False, str(error)[:120]


def _records() -> dict[str, dict[str, int]]:
    if not PID_FILE.exists():
        return {}
    return json.loads(PID_FILE.read_text(encoding="utf-8"))


def start() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    records = _records()
    for site, port in SITES:
        healthy, detail = _healthy(port)
        if healthy:
            print(
                f"[serve] {site} already healthy at "
                f"http://127.0.0.1:{port} ({detail})"
            )
            continue
        app_dir = REPO / "materials" / site / "clone"
        log_path = LOG_ROOT / f"{site}.log"
        log_handle = log_path.open("ab")
        environment = os.environ.copy()
        environment["CLAWBENCH_DATA_DIR"] = str(RUNTIME_ROOT / site)
        environment["PORT"] = str(port)
        process_options: dict[str, object] = {
            "cwd": str(REPO),
            "env": environment,
            "stdout": log_handle,
            "stderr": log_handle,
        }
        if os.name == "nt":
            process_options["creationflags"] = 0x00000008 | 0x00000200
        else:
            process_options["start_new_session"] = True
        proc = subprocess.Popen(
            [
                str(_python()),
                "-m",
                "uvicorn",
                "app:app",
                "--app-dir",
                str(app_dir),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            **process_options,
        )
        log_handle.close()
        records[site] = {"pid": proc.pid, "port": port}
        print(f"[serve] {site} -> http://127.0.0.1:{port} pid={proc.pid}")
        time.sleep(0.3)
    PID_FILE.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def stop() -> None:
    records = _records()
    if not records:
        print("no pid file")
        return
    for site, info in records.items():
        pid = int(info["pid"])
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(pid, signal.SIGTERM)
            print(f"[serve] stop requested for {site} pid={pid}")
        except ProcessLookupError:
            print(f"[serve] {site} pid={pid} was already stopped")
    PID_FILE.unlink()


def status() -> None:
    for site, port in SITES:
        healthy, detail = _healthy(port)
        state = "OK" if healthy else "DOWN"
        print(f"{site:12} {state:4} http://127.0.0.1:{port} {detail}")


def urls() -> None:
    for site, port in SITES:
        print(f"{site:12} http://127.0.0.1:{port}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    actions = {"start": start, "stop": stop, "status": status, "urls": urls}
    if action not in actions:
        choices = ", ".join(actions)
        raise SystemExit(f"unknown action {action!r}; expected one of: {choices}")
    actions[action]()
