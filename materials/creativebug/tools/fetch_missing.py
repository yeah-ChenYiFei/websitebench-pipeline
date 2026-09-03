#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只补下缺失的资产。

fetch_assets.py 读的是 _assets.json 全量；补缺时那会把已有的上万个重下一遍。
这个脚本只处理磁盘上确实不存在的那些，并保持 §7.3(a)：两份物理副本、copy2。
"""
from __future__ import annotations

import json
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "materials" / "creativebug"
SRC = SITE / "source-assets" / "2026-08-28.creativebug-r1"
RUN = SITE / "clone" / "static" / "assets"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def main() -> int:
    amap = json.loads((HERE / "_assets.json").read_text(encoding="utf-8"))["assets"]
    todo = [(u, n) for u, n in amap.items() if not (RUN / n).is_file()]
    print(f"缺失 {len(todo)} / 引用 {len(amap)}")
    s = requests.Session(); s.headers.update({"User-Agent": UA})
    ok = fail = shell = 0
    lock_log = HERE / "_fetch_missing.jsonl"

    def one(item):
        url, name = item
        for i in range(3):
            try:
                r = s.get(url, timeout=45)
            except requests.RequestException:
                time.sleep(2 * (i + 1)); continue
            if r.status_code in (429, 202) or (r.status_code == 200 and not r.content):
                time.sleep(4 * (i + 1)); continue
            if r.status_code != 200:
                return url, name, None, r.status_code
            body = r.content
            # 源站对不存在的图返回 200 + 品牌化 404 页，这类不能当资产入库
            if body[:600].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                return url, name, None, "html-shell"
            time.sleep(random.uniform(1.4, 2.6))   # 真实间隔
            return url, name, body, 200
        return url, name, None, "retry-exhausted"

    # 口径 6（用户 2026-08-28 裁定）：并发 1、真实间隔。原来是 4 路并发，
    # 与该裁定不符 —— 补几个漏网资产不值得违反速率纪律。
    with ThreadPoolExecutor(max_workers=1) as ex, lock_log.open("a", encoding="utf-8") as fh:
        for url, name, body, status in ex.map(one, todo):
            if body is None:
                if status == "html-shell":
                    shell += 1
                else:
                    fail += 1
                fh.write(json.dumps({"url": url, "ok": False, "status": str(status)}) + "\n")
                continue
            (SRC / name).write_bytes(body)
            shutil.copy2(SRC / name, RUN / name)     # 两份物理文件
            ok += 1
            fh.write(json.dumps({"url": url, "ok": True, "bytes": len(body)}) + "\n")

    hard = [p for d in (SRC, RUN) for p in d.rglob("*")
            if p.is_file() and p.stat().st_nlink != 1]
    print(f"下载 {ok}  失败 {fail}  HTML 外壳拒收 {shell}")
    print(f"st_nlink != 1: {len(hard)}（须 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
