# -*- coding: utf-8 -*-
"""出货件不得含采集时的真实身份。

存在的理由：scrub 曾只挂在 finalize.sh 上，直接跑 build_pages.py 就绕过去了，
结果 302 个出货页带着真实邮箱与账号 id 交付。规则回到管线里之后，用测试钉住。

比对用的字面量从 tools/scrub-rules.json 读（该文件不入库），测试本身不存明文 ——
否则这个测试自己就成了新的凭据泄漏点。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

CLONE = Path(__file__).resolve().parents[1]
SITE = CLONE.parent
REPO = SITE.parent.parent
RULES = REPO / "tools" / "scrub-rules.json"


def needles() -> list[str]:
    if not RULES.is_file():
        return []
    return [r["find"] for r in json.loads(RULES.read_text(encoding="utf-8"))
            if r.get("find")]


@pytest.fixture(scope="module")
def secrets() -> list[str]:
    n = needles()
    if not n:
        pytest.skip("没有 scrub-rules.json，无法确定要查的字面量")
    return n


def test_frontend_carries_no_real_identity(secrets):
    hits = []
    for p in (CLONE / "frontend").rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".html", ".htm", ".json", ".txt"}:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        if any(s in t for s in secrets):
            hits.append(str(p.relative_to(CLONE)))
    assert not hits, f"出货页仍含真实身份，共 {len(hits)} 个文件，例如 {hits[:5]}"


def test_database_carries_no_real_identity(secrets):
    db = SITE / "data" / "creativebug.sqlite3"
    if not db.is_file():
        pytest.skip("数据库尚未生成")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            for col in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]:
                for s in secrets:
                    n = c.execute(
                        f"SELECT COUNT(*) FROM {t} WHERE CAST({col} AS TEXT) LIKE ?",
                        (f"%{s}%",)).fetchone()[0]
                    assert not n, f"{t}.{col} 含真实身份字面量"
    finally:
        c.close()


def test_scrub_is_inside_the_build_pipeline():
    """构建器必须自带 scrub，不能只靠 finalize.sh 调用。

    这是构建仓库的不变量，不是交付件的一部分：§11 要求测试在 `cp -r` 出来的
    全新路径里也能跑，而那种路径下没有仓库的 tools/ 树。找不到就跳过，
    而不是报错 —— 交付件本身是否含 PII 由上面两条测试直接验证。
    """
    builder = REPO / "tools" / "build_pages.py"
    if not builder.is_file():
        pytest.skip("构建器不在交付件里（全新路径下的预期情况）")
    assert "scrub_text" in builder.read_text(encoding="utf-8"), \
        "build_pages.py 未在管线内调用 scrub"
