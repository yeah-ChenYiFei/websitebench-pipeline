#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从交付库里清除真实身份数据。

为什么需要它：交付库和本地跑着的库是同一个文件。人用真实邮箱在浏览器里试一次
注册，那条记录就落进交付物 —— 红线是"凭据与 PII 永不入库"。手工删一次不解决
问题，因为下次再试还会进来，所以做成可重复执行的一步，收进 finalize 流水线。

字面量来自 tools/scrub-rules.json（该文件不入库），本脚本不存明文。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RULES = HERE / "scrub-rules.json"
DB = ROOT / "materials" / "creativebug" / "data" / "creativebug.sqlite3"


def needles() -> list[str]:
    if not RULES.is_file():
        return []
    return [r["find"] for r in json.loads(RULES.read_text(encoding="utf-8")) if r.get("find")]


def main() -> int:
    pats = needles()
    if not pats:
        print(f"没有 {RULES}，无法确定要清除什么。")
        return 2
    if not DB.is_file():
        print(f"数据库不存在：{DB}")
        return 0
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    removed = 0
    for t in tables:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        for col in cols:
            for s in pats:
                n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE CAST({col} AS TEXT) LIKE ?",
                              (f"%{s}%",)).fetchone()[0]
                if n:
                    c.execute(f"DELETE FROM {t} WHERE CAST({col} AS TEXT) LIKE ?", (f"%{s}%",))
                    print(f"  {t}.{col}: 删除 {n} 行")
                    removed += n
    c.commit()

    # 删父行会留下孤儿子行。上一次就是这样删掉账户却留下 local_auth_sessions，
    # 外键检查随即失败，服务器直接起不来（LifecycleError）。
    # 反复扫到不动点为止：清掉一批孤儿可能又暴露出下一批。
    for _ in range(8):
        bad = c.execute("PRAGMA foreign_key_check").fetchall()
        if not bad:
            break
        for table, rowid, _parent, _fk in bad:
            c.execute(f'DELETE FROM "{table}" WHERE rowid=?', (rowid,))
            removed += 1
        c.commit()
    left_fk = c.execute("PRAGMA foreign_key_check").fetchall()
    if left_fk:
        print(f"!! 仍有 {len(left_fk)} 条外键违规，未能自动修复")

    # VACUUM：删掉的明文不能留在页尾空闲空间里
    c.execute("VACUUM")

    left = 0
    for t in tables:
        for col in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]:
            for s in pats:
                left += c.execute(f"SELECT COUNT(*) FROM {t} WHERE CAST({col} AS TEXT) LIKE ?",
                                  (f"%{s}%",)).fetchone()[0]
    c.close()
    raw = DB.read_bytes()
    binary_left = sum(1 for s in pats if s.encode() in raw)
    print(f"清除 {removed} 行；库内残留 {left}，二进制层面残留 {binary_left}，"
          f"外键违规 {len(left_fk)}")
    return 0 if (left == 0 and binary_left == 0 and not left_fk) else 1


if __name__ == "__main__":
    sys.exit(main())
