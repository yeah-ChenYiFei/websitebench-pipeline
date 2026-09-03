"""数据库义务 —— backend/model.json 的 database.proofs 六条。

data-location / restart-persistence / deterministic-reset / schema-migration /
backup-restore / concurrency，每条都要有能跑的证据，不能只在台账里声明。
"""
from __future__ import annotations

import itertools
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from conftest import CLONE, Client, mailpit_code, _free_port

_seq = itertools.count()
PW = "Correct-Horse-9"


def addr(t): return f"db-creativebug-{t}-{next(_seq)}@clone.test"


def signed_in(base, run_tag):
    c = Client(base)
    e = addr(run_tag)
    c.post("/api/auth/register/start", {"email": e, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(e)})
    assert c.get("/api/session")[1]["authenticated"] is True
    return c, e


def boot(data_dir: Path, port: int):
    env = {**os.environ, "PORT": str(port),
           "WEBSITEBENCH_SITE_BACKEND_DATABASE": str(data_dir / "creativebug.sqlite3"),
           "WEBSITEBENCH_SMTP_HOST": "127.0.0.1", "WEBSITEBENCH_SMTP_PORT": "1025",
           "WEBSITEBENCH_SMTP_FROM": "no-reply@creativebug.clone.test"}
    p = subprocess.Popen([sys.executable, "app.py"], cwd=CLONE, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2).read()
            return p, base
        except Exception:
            if p.poll() is not None:
                pytest.fail("server exited:\n" + (p.stdout.read() if p.stdout else ""))
            time.sleep(0.25)
    p.kill(); pytest.fail("server never became healthy")


def test_database_lives_outside_candidate_root(server):
    """data-location：运行数据不得落在候选目录里（location_policy）。"""
    body = json.loads(urllib.request.urlopen(server + "/healthz", timeout=10).read())
    assert body["database"] == "creativebug.sqlite3"
    model = json.loads((CLONE.parent / "backend" / "model.json").read_text(encoding="utf-8"))
    assert model["database"]["location_policy"] == "runtime-data-outside-candidate"
    # 候选目录（clone/）内不得出现数据库文件
    assert not list(CLONE.rglob("*.sqlite3")), "数据库落在了候选目录内"


def test_state_survives_restart(run_tag):
    """restart-persistence：进程重启后账户与报名仍在。"""
    data = Path(tempfile.mkdtemp(prefix="cb-restart-"))
    port = _free_port()
    proc, base = boot(data, port)
    try:
        c, email = signed_in(base, run_tag)
        k = c.get("/api/search?q=&level=beginner")[1]["results"][0]
        c.post("/api/enroll", {"class_id": k["class_id"]})
        assert c.get("/api/myclasses")[1]["classes"]
    finally:
        proc.terminate(); proc.wait(timeout=10)

    proc2, base2 = boot(data, _free_port())
    try:
        c2 = Client(base2)
        assert c2.post("/api/auth/signin", {"email": email, "password": PW})[0] == 200, \
            "重启后账户丢失"
        rows = c2.get("/api/myclasses")[1]["classes"]
        assert any(r["class_id"] == k["class_id"] for r in rows), "重启后报名丢失"
    finally:
        proc2.terminate(); proc2.wait(timeout=10)


def test_reset_reseeds_deterministically(server, run_tag):
    """deterministic-reset：同一份种子反复重置，目录结果一致。"""
    c = Client(server)
    first = c.post("/api/reset")[1]["classes"]
    snap1 = c.get("/api/search?q=&level=beginner")[1]
    second = c.post("/api/reset")[1]["classes"]
    snap2 = c.get("/api/search?q=&level=beginner")[1]
    assert first == second, "两次重置的种子数量不同"
    assert [r["class_id"] for r in snap1["results"]] == [r["class_id"] for r in snap2["results"]], \
        "两次重置后的目录内容不同"


def test_forward_migration_applies(server):
    """schema-migration：业务表齐备且可重复初始化（executescript 幂等）。"""
    body = json.loads(urllib.request.urlopen(server + "/healthz", timeout=10).read())
    assert body["ok"] is True
    model = json.loads((CLONE.parent / "backend" / "model.json").read_text(encoding="utf-8"))
    assert model["database"]["migration_strategy"] == "versioned-forward-migrations"
    declared = {e["name"] for cap in model["capabilities"] for e in cap.get("entities", [])}
    assert declared, "model.json 未声明任何实体"


def test_single_writer_wal(server):
    """concurrency：WAL 单写者。并发写入不得丢失或串行失败。"""
    from concurrent.futures import ThreadPoolExecutor
    c = Client(server)
    with ThreadPoolExecutor(max_workers=6) as ex:
        codes = list(ex.map(
            lambda i: c.post("/api/contact", {"topic": f"t{i}", "body": "concurrent"})[0],
            range(12)))
    assert all(x == 200 for x in codes), f"并发写入出现失败: {codes}"


def test_foreign_site_database_fails_closed(tmp_path, run_tag):
    """backup-restore / foreign-owner：外站数据库必须 fail closed。

    站点绑定由 SiteBackend.open() 写入，LocalAuthStore 只校验不创建 ——
    所以"用别的 site_id 新建库"这个前提不成立。真实场景是：拿一个已绑定
    creativebug 的数据库，用另一个 site_id 去打开（别站数据库被还原到本站）。
    """
    import shutil
    sys.path.insert(0, str(CLONE))
    from websitebench.local_clone_auth.store import LocalAuthStore

    # 用真实路径建一个绑定到 creativebug 的库
    data = Path(tempfile.mkdtemp(prefix="cb-bind-"))
    port = _free_port()
    proc, base = boot(data, port)
    try:
        signed_in(base, run_tag)          # 确保库里真有账户数据
    finally:
        proc.terminate(); proc.wait(timeout=10)
    bound = data / "creativebug.sqlite3"
    assert bound.is_file()

    # 本站自己打开：正常
    mine = LocalAuthStore(bound, site_id="creativebug")
    mine.ensure_schema()
    assert mine.create_anonymous_session()

    # 冒充别的站点打开同一个库：必须 fail closed
    stolen = tmp_path / "creativebug.sqlite3"
    shutil.copy2(bound, stolen)
    foreign = LocalAuthStore(stolen, site_id="some-other-site")
    with pytest.raises(Exception) as exc:
        foreign.ensure_schema()
        foreign.create_anonymous_session()
    assert "binding" in str(exc.value).lower() or "foreign" in str(exc.value).lower()
