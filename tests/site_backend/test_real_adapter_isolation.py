from __future__ import annotations

import http.client
import importlib.util
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[2]
AMAZON_CLONE = REPO_ROOT / "materials" / "amazon" / "clone"
EDX_APP = REPO_ROOT / "materials" / "edx" / "clone" / "app.py"
PROBE_ENV = "WEBSITEBENCH_REAL_ADAPTER_ISOLATION_PROBE"


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _cookie(headers: dict[str, list[str]]) -> str:
    return headers["set-cookie"][-1].split(";", 1)[0]


def _load_edx_app(data_dir: Path, monkeypatch):
    for name in (
        "WEBSITEBENCH_SITE_BACKEND_RUNTIME",
        "WEBSITEBENCH_SITE_BACKEND_DATABASE",
        "WEBSITEBENCH_DATA_DIR",
        "CLAWBENCH_DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WEBSITEBENCH_EDX_DATA_DIR", str(data_dir))
    edx_clone = str(EDX_APP.parent)
    if edx_clone not in sys.path:
        sys.path.insert(0, edx_clone)
    module_name = "websitebench_cross_site_edx_app"
    sys.modules.pop(module_name, None)
    sys.modules.pop("edx_clone_backend_db", None)
    spec = importlib.util.spec_from_file_location(module_name, EDX_APP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_amazon_and_edx_http_adapters_isolate_accounts_passwords_and_sessions(
    tmp_path: Path, monkeypatch
) -> None:
    if os.environ.get(PROBE_ENV) != "1":
        environment = os.environ.copy()
        environment[PROBE_ENV] = "1"
        for name in (
            "WEBSITEBENCH_SITE_BACKEND_RUNTIME",
            "WEBSITEBENCH_SITE_BACKEND_DATABASE",
            "WEBSITEBENCH_DATA_DIR",
            "CLAWBENCH_DATA_DIR",
        ):
            environment.pop(name, None)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"{Path(__file__).resolve()}::"
                "test_amazon_and_edx_http_adapters_isolate_accounts_"
                "passwords_and_sessions",
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return

    edx = _load_edx_app(tmp_path / "edx", monkeypatch)
    if str(AMAZON_CLONE) not in sys.path:
        sys.path.insert(0, str(AMAZON_CLONE))
    import server as amazon_server
    from store import Store

    edx.reset_fixture_state()

    amazon_store = Store(
        tmp_path / "amazon" / "amazon.sqlite3",
        AMAZON_CLONE / "schema.sql",
        AMAZON_CLONE / "fixtures",
    )
    amazon_store.reset()

    class QuietAmazonHandler(amazon_server.PublicHandler):
        def log_message(self, format_string: str, *args: object) -> None:
            del format_string, args

    QuietAmazonHandler.store = amazon_store
    QuietAmazonHandler.smtp_config = None
    server = amazon_server.ReusableThreadingHTTPServer(
        ("127.0.0.1", 0), QuietAmazonHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    def amazon_request(
        method: str,
        path: str,
        *,
        fields: dict[str, str] | None = None,
        cookie: str = "",
    ) -> tuple[int, dict[str, list[str]], bytes]:
        body = urlencode(fields).encode("utf-8") if fields is not None else None
        headers: dict[str, str] = {}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Content-Length"] = str(len(body))
        if method == "POST":
            headers["Origin"] = f"http://{host}:{port}"
        if cookie:
            headers["Cookie"] = cookie
        connection = http.client.HTTPConnection(host, port, timeout=8)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            response_headers: dict[str, list[str]] = {}
            for name, value in response.getheaders():
                response_headers.setdefault(name.casefold(), []).append(value)
            return response.status, response_headers, response.read()
        finally:
            connection.close()

    shared_email = "same-person@adapter-isolation.example"
    amazon_password = "AmazonAdapterPass123!"
    edx_password = "EdxAdapterPass456!"

    try:
        status, headers, _ = amazon_request("GET", "/")
        assert status == 200
        amazon_pending_cookie = _cookie(headers)
        status, headers, _ = amazon_request(
            "POST",
            "/ap/register",
            fields={
                "customerName": "Shared Adapter User",
                "email": shared_email,
                "password": amazon_password,
                "passwordCheck": amazon_password,
            },
            cookie=amazon_pending_cookie,
        )
        assert status == 303
        assert headers["location"] == ["/ap/cvf/verify?purpose=registration"]
        pending_digest = amazon_server.digest(
            amazon_pending_cookie.split("=", 1)[1]
        )
        message = amazon_store.registration_outbox(pending_digest)
        assert len(message) == 1
        status, headers, _ = amazon_request(
            "POST",
            "/ap/cvf/verify",
            fields={"code": str(message[0]["verification_code"])},
            cookie=amazon_pending_cookie,
        )
        assert status == 303
        amazon_authenticated_cookie = _cookie(headers)

        with TestClient(edx.app, base_url="https://edx.test") as edx_unknown:
            login = edx_unknown.get("/login")
            refused = edx_unknown.post(
                "/login",
                data={
                    "csrf": _csrf(login.text),
                    "username": shared_email,
                    "password": amazon_password,
                    "next": "/dashboard",
                },
                follow_redirects=False,
            )
            assert refused.status_code == 400
            protected = edx_unknown.get("/dashboard", follow_redirects=False)
            assert protected.status_code == 401
            assert 'data-state="unauthorized"' in protected.text

        with TestClient(edx.app, base_url="https://edx.test") as edx_owner:
            registration = edx_owner.get("/register")
            started = edx_owner.post(
                "/register",
                data={
                    "csrf": _csrf(registration.text),
                    "display_name": "Independent edX User",
                    "email": shared_email,
                    "password": edx_password,
                },
                follow_redirects=False,
            )
            assert started.status_code == 303
            inbox = edx_owner.get("/account/inbox?purpose=registration")
            code = re.search(r"<code>([^<]+)</code>", inbox.text)
            assert code is not None
            verification = edx_owner.get("/register/verify")
            completed = edx_owner.post(
                "/register/verify",
                data={
                    "csrf": _csrf(verification.text),
                    "code": code.group(1),
                },
                follow_redirects=False,
            )
            assert completed.status_code == 303
            assert edx_owner.get("/dashboard").status_code == 200
            edx_authenticated_token = edx_owner.cookies.get(
                edx.AUTH_SESSION_COOKIE
            )
            assert edx_authenticated_token

        with TestClient(edx.app, base_url="https://edx.test") as edx_login:
            login = edx_login.get("/login")
            accepted = edx_login.post(
                "/login",
                data={
                    "csrf": _csrf(login.text),
                    "username": shared_email,
                    "password": edx_password,
                    "next": "/dashboard",
                },
                follow_redirects=False,
            )
            assert accepted.status_code == 303

        amazon_replay_token = amazon_authenticated_cookie.split("=", 1)[1]
        with TestClient(edx.app, base_url="https://edx.test") as edx_replay:
            for replay_cookie in (
                amazon_authenticated_cookie,
                f"{edx.AUTH_SESSION_COOKIE}={amazon_replay_token}",
            ):
                replayed = edx_replay.get(
                    "/dashboard",
                    headers={"Cookie": replay_cookie},
                    follow_redirects=False,
                )
                assert replayed.status_code == 401
                assert 'data-state="unauthorized"' in replayed.text

        status, headers, _ = amazon_request("GET", "/")
        assert status == 200
        amazon_login_cookie = _cookie(headers)
        status, _, _ = amazon_request(
            "POST",
            "/ap/signin",
            fields={"email": shared_email},
            cookie=amazon_login_cookie,
        )
        assert status == 303
        status, _, _ = amazon_request(
            "POST",
            "/ap/signin",
            fields={"password": edx_password},
            cookie=amazon_login_cookie,
        )
        assert status == 401

        status, headers, _ = amazon_request("GET", "/")
        assert status == 200
        amazon_login_cookie = _cookie(headers)
        status, _, _ = amazon_request(
            "POST",
            "/ap/signin",
            fields={"email": shared_email},
            cookie=amazon_login_cookie,
        )
        assert status == 303
        status, headers, _ = amazon_request(
            "POST",
            "/ap/signin",
            fields={"password": amazon_password},
            cookie=amazon_login_cookie,
        )
        assert status == 303
        assert headers["location"] == ["/"]

        for replay_cookie in (
            f"{edx.AUTH_SESSION_COOKIE}={edx_authenticated_token}",
            (
                f"{amazon_server.SESSION_COOKIE}="
                f"{edx_authenticated_token}"
            ),
        ):
            status, headers, _ = amazon_request(
                "GET", "/gp/css/order-history", cookie=replay_cookie
            )
            assert status == 303
            assert headers["location"][0].startswith("/ap/signin?")

        assert (
            amazon_server.SESSION_COOKIE
            == "__Host-websitebench-amazon-shopping-mainline-session"
        )
        assert edx.AUTH_SESSION_COOKIE == "__Host-websitebench-edx-session"
        assert amazon_server.SESSION_COOKIE != edx.AUTH_SESSION_COOKIE
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        edx.reset_fixture_state()
