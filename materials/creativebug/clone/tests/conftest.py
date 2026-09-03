"""测试夹具：每个会话一个独立数据目录与端口，Mailpit 收件箱按运行标签隔离。"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

CLONE = Path(__file__).resolve().parent.parent
MAILPIT_API = "http://127.0.0.1:8025/api/v1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def run_tag() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def server_data_dir(run_tag):
    """这个 session 的数据目录。单独抽出来，重启测试要指向同一份数据。"""
    return Path(tempfile.mkdtemp(prefix=f"websitebench-auth-creativebug-{run_tag}-"))


def _boot(data: Path):
    """在给定数据目录上起一个 app.py 进程，返回 (base_url, proc)。"""
    port = _free_port()
    env = {**os.environ,
           "PORT": str(port),
           "WEBSITEBENCH_SITE_BACKEND_DATABASE": str(data / "creativebug.sqlite3"),
           "WEBSITEBENCH_SMTP_HOST": "127.0.0.1",
           "WEBSITEBENCH_SMTP_PORT": "1025",
           "WEBSITEBENCH_SMTP_FROM": "no-reply@creativebug.clone.test"}
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=CLONE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2).read()
            return base, proc
        except Exception:
            if proc.poll() is not None:
                pytest.fail("server exited:\n" + (proc.stdout.read() if proc.stdout else ""))
            time.sleep(0.25)
    proc.kill()
    pytest.fail("server did not become healthy")


@pytest.fixture
def restart_server(server_data_dir):
    """关掉当前进程之外，另起一个进程指向同一个数据库。

    ULTIMATE §13 要求「两进程重启持久化通过」：只有跨进程验证，才能区分
    真正落盘的状态和进程内存里冒充持久的状态。
    """
    started = []

    def _restart():
        base, proc = _boot(server_data_dir)
        started.append(proc)
        return base

    yield _restart
    for proc in started:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def server(run_tag, server_data_dir):
    data = server_data_dir
    port = _free_port()
    env = {**os.environ,
           "PORT": str(port),
           "WEBSITEBENCH_SITE_BACKEND_DATABASE": str(data / "creativebug.sqlite3"),
           "WEBSITEBENCH_SMTP_HOST": "127.0.0.1",
           "WEBSITEBENCH_SMTP_PORT": "1025",
           "WEBSITEBENCH_SMTP_FROM": "no-reply@creativebug.clone.test"}
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=CLONE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2).read()
            break
        except Exception:
            if proc.poll() is not None:
                pytest.fail("server exited:\n" + (proc.stdout.read() if proc.stdout else ""))
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("server did not become healthy")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class Client:
    """带 cookie 的最小客户端；不用 requests，避免给克隆加运行期依赖。"""

    def __init__(self, base):
        self.base = base
        self.cookies: dict[str, str] = {}

    def _headers(self):
        if not self.cookies:
            return {}
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={**self._headers(),
                                              **({"Content-Type": "application/json"} if data else {})})
        try:
            r = urllib.request.urlopen(req, timeout=20)
            status, raw, hdrs = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw, hdrs = e.code, e.read(), e.headers
        for sc in hdrs.get_all("Set-Cookie") or []:
            k, _, rest = sc.partition("=")
            v = rest.split(";")[0]
            if v:
                self.cookies[k.strip()] = v
            else:
                self.cookies.pop(k.strip(), None)
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"_raw": raw[:200]}
        return status, payload

    def get(self, p): return self.request("GET", p)
    def post(self, p, b=None): return self.request("POST", p, b or {})


@pytest.fixture
def client(server):
    return Client(server)


def mailpit_code(address: str, timeout: float = 15.0) -> str:
    """从 Mailpit 取该地址最新一封邮件里的六位码。"""
    import re
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            q = urllib.parse.quote(f"to:{address}")
            r = urllib.request.urlopen(f"{MAILPIT_API}/search?query={q}", timeout=5)
            msgs = json.loads(r.read()).get("messages", [])
            if msgs:
                mid = msgs[0]["ID"]
                body = json.loads(urllib.request.urlopen(
                    f"{MAILPIT_API}/message/{mid}", timeout=5).read())
                text = (body.get("Text") or "") + (body.get("HTML") or "")
                m = re.search(r"\b(\d{6})\b", text)
                if m:
                    return m.group(1)
        except Exception:
            pass
        time.sleep(0.4)
    raise AssertionError(f"no six-digit code delivered to {address}")


import urllib.parse  # noqa: E402  (mailpit_code 用)
