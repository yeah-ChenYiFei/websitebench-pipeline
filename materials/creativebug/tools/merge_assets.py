#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把用户机器取回的资产合并进克隆。

§7.3(a)：source 与 runtime 必须是两个物理文件、各自 st_nlink == 1，
一律 shutil.copy2，绝不 os.link / cp -al。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import urllib.parse as up
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "materials" / "creativebug"
SRC = SITE / "source-assets" / "2026-08-28.creativebug-r1"
RUN = SITE / "clone" / "static" / "assets"
INCOMING = HERE.parent / "incoming" / "cb-out"


def asset_key(url: str) -> str:
    q = up.urlparse(url)
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(q.path).name or "asset")[:60]
    h = hashlib.sha1(f"{q.netloc}{q.path}?{q.query}".encode()).hexdigest()[:10]
    return f"{h}-{stem}"


def main() -> int:
    for d in (SRC, RUN):
        d.mkdir(parents=True, exist_ok=True)
    state = INCOMING / "_assets_state.jsonl"
    if not state.is_file():
        print("没有 _assets_state.jsonl")
        return 1
    recs = {}
    for line in state.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["url"]] = r

    amap = json.loads((HERE / "_assets.json").read_text(encoding="utf-8"))["assets"]
    merged = skipped = html_shell = 0
    for url, rec in recs.items():
        if not rec.get("ok") or not rec.get("file"):
            continue
        src = INCOMING / "assets" / rec["file"]
        if not src.is_file():
            continue
        # 源站对不存在的图片返回 200 + 品牌化 404 页，下载器据此记为成功。
        # 这类响应必须在合并阶段就拦掉 —— 只在 source-assets 里删一次没用，
        # 收口流水线每次重跑都会从 incoming 重新合并进来。
        if src.read_bytes()[:600].lstrip().lower().startswith((b"<!doctype html", b"<html")):
            html_shell += 1
            continue
        name = amap.get(url) or asset_key(url)
        amap.setdefault(url, name)
        shutil.copy2(src, SRC / name)          # 两份物理副本
        shutil.copy2(SRC / name, RUN / name)
        merged += 1
    skipped = sum(1 for r in recs.values() if not r.get("ok"))

    (HERE / "_assets.json").write_text(
        json.dumps({"assets": amap}, ensure_ascii=False, indent=1), encoding="utf-8")

    # 幂等清理：早先落进来的 HTML 外壳要主动清掉。
    # 只在合并入口拦截不够 —— 加过滤器之前已经落盘的那些不会自己消失。
    purged = 0
    for d in (SRC, RUN, SITE / "source-assets" / "served"):
        if not d.is_dir():
            continue
        for f in list(d.iterdir()):
            if not f.is_file() or f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                continue
            if f.read_bytes()[:600].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                f.unlink()
                purged += 1
    if purged:
        print(f"清理历史遗留的 HTML 外壳 {purged} 个")

    hard = [p for d in (SRC, RUN) for p in d.rglob("*")
            if p.is_file() and p.stat().st_nlink != 1]
    print(f"合并 {merged} 个，未取得 {skipped} 个，HTML 外壳拦截 {html_shell} 个")
    print(f"source-assets {len(list(SRC.glob('*')))}  runtime {len(list(RUN.glob('*')))}")
    print(f"st_nlink != 1: {len(hard)}（须 0）")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
