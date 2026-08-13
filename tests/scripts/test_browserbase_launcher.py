from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/browserbase-chrome-devtools-mcp"
API_KEY = "test-api-key-that-must-never-appear"
DEBUG_URL = "wss://debug.example.test/signed-secret"
CONNECT_URL = "wss://connect.example.test/other-secret"


class _State:
    creates = 0
    debugs = 0
    releases = 0
    payloads: list[dict[str, object]]

    def __init__(self) -> None:
        self.payloads = []


@pytest.fixture()
def fake_api():
    state = _State()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            assert self.headers["X-BB-API-Key"] == API_KEY
            if self.path == "/v1/sessions/session-test/debug":
                state.debugs += 1
                self._json(200, {"wsUrl": DEBUG_URL})
                return
            self._json(404, {"secret": API_KEY})

        def do_POST(self) -> None:  # noqa: N802
            assert self.headers["X-BB-API-Key"] == API_KEY
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size) or b"{}")
            if self.path == "/v1/sessions":
                state.creates += 1
                state.payloads.append(payload)
                self._json(
                    201,
                    {"id": "session-test", "connectUrl": CONNECT_URL},
                )
                return
            if self.path == "/v1/sessions/session-test":
                state.releases += 1
                assert payload == {"status": "REQUEST_RELEASE"}
                self._json(200, {"status": "COMPLETED", "secret": API_KEY})
                return
            self._json(404, {"secret": API_KEY})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _run(
    tmp_path: Path,
    api_url: str,
    *,
    mcp_status: int,
    keep_alive: bool = False,
    session_id: str | None = None,
):
    fake_mcp = tmp_path / "fake-mcp"
    fake_mcp.write_text(f"#!/bin/sh\nexit {mcp_status}\n", encoding="utf-8")
    fake_mcp.chmod(0o700)
    environment = os.environ.copy()
    for key in (
        "BROWSERBASE_CDP_URL",
        "BROWSERBASE_PROJECT_ID",
        "BROWSERBASE_SESSION_ID",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "BROWSERBASE_API_KEY": API_KEY,
            "BROWSERBASE_API_URL": api_url,
            "BROWSERBASE_KEEP_ALIVE": "true" if keep_alive else "false",
            "WEBSITEBENCH_CHROME_DEVTOOLS_MCP_LAUNCHER": str(fake_mcp),
        }
    )
    if session_id is not None:
        environment["BROWSERBASE_SESSION_ID"] = session_id
    return subprocess.run(
        [str(LAUNCHER)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _assert_sanitized(result: subprocess.CompletedProcess[str]) -> None:
    combined = result.stdout + result.stderr
    assert API_KEY not in combined
    assert DEBUG_URL not in combined
    assert CONNECT_URL not in combined
    assert "signed-secret" not in combined


def test_failure_creates_exactly_one_session_and_releases_it(fake_api, tmp_path) -> None:
    state, api_url = fake_api
    result = _run(tmp_path, api_url, mcp_status=7)
    assert result.returncode == 7
    assert (state.creates, state.debugs, state.releases) == (1, 1, 1)
    assert state.payloads[0]["keepAlive"] is False
    assert state.payloads[0]["userMetadata"] == {
        "purpose": "codex-chrome-devtools"
    }
    assert "session release accepted (HTTP 200)" in result.stderr
    _assert_sanitized(result)


def test_default_success_releases_session(fake_api, tmp_path) -> None:
    state, api_url = fake_api
    result = _run(tmp_path, api_url, mcp_status=0)
    assert result.returncode == 0
    assert (state.creates, state.debugs, state.releases) == (1, 1, 1)
    _assert_sanitized(result)


def test_opted_in_keepalive_preserves_clean_session(fake_api, tmp_path) -> None:
    state, api_url = fake_api
    result = _run(tmp_path, api_url, mcp_status=0, keep_alive=True)
    assert result.returncode == 0
    assert (state.creates, state.debugs, state.releases) == (1, 1, 0)
    assert state.payloads[0]["keepAlive"] is True
    _assert_sanitized(result)


def test_existing_session_attaches_without_create_or_release(fake_api, tmp_path) -> None:
    state, api_url = fake_api
    result = _run(
        tmp_path,
        api_url,
        mcp_status=0,
        session_id="session-test",
    )
    assert result.returncode == 0
    assert (state.creates, state.debugs, state.releases) == (0, 1, 0)
    assert "attaching existing session" in result.stderr
    _assert_sanitized(result)


def test_existing_session_id_is_validated_before_api_call(fake_api, tmp_path) -> None:
    state, api_url = fake_api
    result = _run(
        tmp_path,
        api_url,
        mcp_status=0,
        session_id="../../not-valid",
    )
    assert result.returncode == 2
    assert (state.creates, state.debugs, state.releases) == (0, 0, 0)
    assert "BROWSERBASE_SESSION_ID is invalid" in result.stderr
    _assert_sanitized(result)
