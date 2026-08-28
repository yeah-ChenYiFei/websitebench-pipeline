"""Isolated loopback server fixtures for AMC browser journeys."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLONE_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class CloneProcess:
    def __init__(self, data_dir: Path) -> None:
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.data_dir = data_dir
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        env = {
            **os.environ,
            "PORT": str(self.port),
            "WEBSITEBENCH_DATA_DIR": str(self.data_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=str(CLONE_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output = self.process.stdout.read().decode() if self.process.stdout else ""
                raise RuntimeError(f"clone exited during boot:\n{output[-4000:]}")
            try:
                with urllib.request.urlopen(f"{self.base}/healthz", timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("clone did not become healthy in 30 seconds")

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        self.process = None


@pytest.fixture(scope="session")
def clone_server(tmp_path_factory: pytest.TempPathFactory) -> CloneProcess:
    server = CloneProcess(tmp_path_factory.mktemp("amc-browser-data"))
    server.start()
    yield server
    server.stop()
