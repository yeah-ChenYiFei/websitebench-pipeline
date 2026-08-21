#!/usr/bin/env python3
"""Run one bounded candidate capture with deterministic process cleanup."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "materials" / "bluemercury" / "clone" / "app.py"
RUNNER = ROOT / "tools" / "offline_clone" / "run.py"


def free(port: int) -> bool:
    with socket.socket() as handle:
        return handle.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    port = 8765
    profile = os.environ.get("CAPTURE_PROFILE", "desktop")
    revision = os.environ.get("CAPTURE_REV")
    if profile not in {"desktop", "mobile"}:
        raise ValueError("CAPTURE_PROFILE must be desktop or mobile")
    if revision is None or not revision.replace("-", "").isalnum():
        raise ValueError("CAPTURE_REV must be an alphanumeric revision label")
    report_path = ROOT / f"materials/bluemercury/artifacts/browser/candidate-{profile}-{revision}-valid.json"
    artifacts_path = ROOT / f"materials/bluemercury/artifacts/browser/candidate-{profile}-{revision}-valid"
    if report_path.exists() or artifacts_path.exists():
        raise FileExistsError(f"refusing to overwrite existing capture: {report_path}")
    if not free(port):
        raise RuntimeError(f"refusing to replace listener on 127.0.0.1:{port}")
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("WEBSITEBENCH_SITE_BACKEND_"):
            environment.pop(key)
    data_dir = ROOT / "materials" / "bluemercury" / "artifacts" / "runtime" / f"visual-{revision}-{profile}-data"
    environment.update(
        {
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "DATA_DIR": str(data_dir),
            "WEBSITEBENCH_SITE_BACKEND_DATABASE": str(data_dir / "bluemercury.sqlite3"),
            "SEED": "20",
            "TZ": "Etc/UTC",
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(APP)],
        cwd=APP.parent,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode("utf-8", "replace"))
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/__websitebench/health", timeout=1
                ) as response:
                    if response.read() == b'{"status":"ok"}':
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("candidate health timeout")
        command = [
            sys.executable,
            str(RUNNER),
            "tools",
            "explore",
            "--spec",
            f"materials/bluemercury/tools/browser-public-{profile}.json",
            "--base-url",
            f"http://127.0.0.1:{port}",
            "--environment",
            "clone",
            "--out",
            str(report_path.relative_to(ROOT)),
            "--artifacts-dir",
            str(artifacts_path.relative_to(ROOT)),
        ]
        return subprocess.run(command, cwd=ROOT, timeout=90, check=False).returncode
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
