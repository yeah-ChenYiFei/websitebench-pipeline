#!/usr/bin/env python3
"""Compile and probe the Bluemercury Harbor public seed in a temporary root."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
PUBLIC = REPO / "harbor" / "instances" / "bluemercury" / "public"
RUNNERS = REPO / "harbor" / "instances" / "bluemercury" / "fixtures" / "hidden" / "runners"


def free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="bluemercury-harbor-seed-") as temporary:
        root = Path(temporary) / "candidate"
        shutil.copytree(PUBLIC, root)
        subprocess.run([str(root / "compile.sh")], cwd=root, check=True, timeout=30)
        executable = root / "executable"
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise SystemExit("compile.sh did not produce executable")

        runner_results = []
        for runner in sorted(RUNNERS.glob("check-*.py")):
            completed = subprocess.run(
                [str(runner)],
                cwd=RUNNERS,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "WEBSITEBENCH_CANDIDATE_ROOT": str(root), "SEED": "20", "TZ": "Etc/UTC"},
                check=False,
                timeout=30,
            )
            runner_results.append({"runner": runner.name, "exit_code": completed.returncode})
        if any(item["exit_code"] != 0 for item in runner_results):
            raise SystemExit(json.dumps(runner_results))

        port = free_port()
        data_dir = Path(temporary) / "data"
        data_dir.mkdir()
        environment = os.environ.copy()
        environment.update({"HOST": "127.0.0.1", "PORT": str(port), "DATA_DIR": str(data_dir), "SEED": "20", "TZ": "Etc/UTC"})
        process = subprocess.Popen([str(executable)], cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            body = None
            for _ in range(50):
                if process.poll() is not None:
                    raise SystemExit(process.stderr.read().decode("utf-8", "replace"))
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/__websitebench/health", timeout=1) as response:
                        body = response.read().decode("utf-8")
                    break
                except OSError:
                    time.sleep(0.1)
            if body != '{"status":"ok"}':
                raise SystemExit(f"unexpected health response: {body!r}")
        finally:
            process.terminate()
            process.wait(timeout=10)
        print(json.dumps({"compile": "ok", "executable": True, "health": body, "runners": runner_results}, sort_keys=True))


if __name__ == "__main__":
    main()
