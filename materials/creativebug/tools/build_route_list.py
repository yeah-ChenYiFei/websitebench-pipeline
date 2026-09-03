#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recon 产物 → 路由清单 + §5.4 页面总数算式。

在服务器端跑，输入是 Windows 那边 recon/login 打回来的 cb-out/recon/。

做三件事：
 1. 归一并合并路由来源（首页出链 / sitemap / 登录后新增），带 §G1 的换行断言
 2. 按 tools/route-rules.json 分桶（规则由证据定，不预设——见 --shape）
 3. 按 §5.4 算页面总数：1 + Σ(列表×2页) + Σ(前两页项数) + 静态页

用法：
  python tools/build_route_list.py --shape           # 先看形状，据此写分桶规则
  python tools/build_route_list.py --emit            # 生成 tools/all.urls
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse as up
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECON = HERE.parent / "incoming" / "cb-out" / "recon"   # 解包后的 recon 目录
RULES = HERE / "route-rules.json"
OUT = HERE / "all.urls"
HOSTS = ("creativebug.com", "www.creativebug.com")


def norm(u: str) -> str | None:
    """URL/路径 → 归一路由。去 fragment、去尾斜杠、只留站内。"""
    u = u.strip()
    if not u or u.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    q = up.urlparse(u if "//" in u else up.urljoin("https://www.creativebug.com/", u))
    if q.netloc and q.netloc not in HOSTS:
        return None
    path = (q.path or "/").rstrip("/") or "/"
    return path + (f"?{q.query}" if q.query else "")


def read_lines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else []


def sitemap_locs(p: Path) -> list[str]:
    if not p.is_file():
        return []
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", p.read_text(encoding="utf-8", errors="replace"))


def gather() -> dict[str, set[str]]:
    """按来源分别收集，保留出处——出处决定这条路由属于 D0 还是 D2。"""
    src: dict[str, set[str]] = {}
    src["home"] = {r for r in map(norm, read_lines(RECON / "home-outlinks.txt")) if r}
    src["after_login"] = {r for r in map(norm, read_lines(RECON / "after-login-outlinks.txt")) if r}
    src["sitemap"] = {r for r in map(norm, sitemap_locs(RECON / "sitemap.txt")) if r}
    src["sitemap"] |= {r for r in map(norm, sitemap_locs(RECON / "sitemap_index.txt")) if r}
    return src


def bucket(route: str, rules: dict) -> str:
    for name, pats in rules.get("buckets", {}).items():
        for pat in pats:
            if re.fullmatch(pat, route):
                return name
    return "unclassified"


def cmd_shape(_a) -> int:
    """先看形状。分桶规则必须由真实读数定，不预设。"""
    if not RECON.is_dir():
        print(f"没找到 recon 目录：{RECON}")
        print("把 Windows 打回来的 cb-upload-*.zip 解到 creativebug-clone/incoming/ 下")
        return 2
    src = gather()
    allr = set().union(*src.values()) if src else set()
    print(f"=== 来源计数 ===")
    for k, v in src.items():
        print(f"  {k:12s} {len(v)}")
    print(f"  {'合计唯一':12s} {len(allr)}")

    rep = RECON / "report.json"
    if rep.is_file():
        print("\n=== recon report ===")
        print(json.dumps(json.loads(rep.read_text(encoding='utf-8')), ensure_ascii=False, indent=1))

    print("\n=== 一级段分布（分桶规则从这里推）===")
    seg = Counter(r.split("/")[1].split("?")[0] if r != "/" else "(root)" for r in allr)
    for k, n in seg.most_common(40):
        print(f"  {n:5d}  /{k}")

    print("\n=== 二级段分布（前 10 个一级段展开）===")
    for top, _ in seg.most_common(10):
        sub = Counter(r.split("/")[2] for r in allr
                      if r != "/" and r.split("/")[1].split("?")[0] == top and len(r.split("/")) > 2)
        if sub:
            print(f"  /{top}/…  {dict(sub.most_common(8))}")

    newly = src.get("after_login", set()) - src.get("home", set())
    print(f"\n=== 登录后新增路由 {len(newly)} 条（判 dashboard 是否存在的依据）===")
    for r in sorted(newly)[:60]:
        print("   ", r)
    return 0


def cmd_emit(_a) -> int:
    if not RULES.is_file():
        print(f"缺 {RULES}。先跑 --shape，据实测读数写分桶规则再来。")
        return 2
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    src = gather()
    allr = sorted(set().union(*src.values()))
    by: dict[str, list[str]] = {}
    for r in allr:
        by.setdefault(bucket(r, rules), []).append(r)

    print("=== 分桶结果 ===")
    for k in sorted(by):
        print(f"  {k:18s} {len(by[k])}")
    unc = by.get("unclassified", [])
    if unc:
        print(f"\n!! {len(unc)} 条未分类，前 20：")
        for r in unc[:20]:
            print("   ", r)
        print("未分类 = 分桶规则不完整。补规则，不要放着——它们会变成 D0 死链。")

    # §5.4 页面总数
    lists = by.get("list", [])
    page_size = rules.get("page_size")
    detail_per_list = (page_size * 2) if page_size else None
    total = (1
             + len(lists) * 2
             + (len(lists) * detail_per_list if detail_per_list else 0)
             + len(by.get("static", []))
             + len(by.get("auth", []))
             + len(by.get("account", [])))
    print(f"""
=== §5.4 页面总数算式 ===
  1 首页
+ {len(lists)} 列表族 × 2 页            = {len(lists)*2}
+ {len(lists)} × {detail_per_list} 项/前两页       = {len(lists)*detail_per_list if detail_per_list else '?（page_size 未测出）'}
+ {len(by.get('static', []))} 静态页
+ {len(by.get('auth', []))} 认证面 + {len(by.get('account', []))} 账户面
-------------------------------------
  合计 ≈ {total}""")
    if not page_size:
        print("!! page_size 没读出来 —— §5.4 算不准。必须从源站接口响应或首屏项数实测，不许猜。")
        return 2

    # §G1 换行断言：合并清单不许把两条 URL 粘成一条
    lines = [r for k in sorted(by) if k != "unclassified" for r in by[k]]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    n = len(OUT.read_text(encoding="utf-8").splitlines())
    assert n == len(lines), f"MERGE-BROKEN: 写入 {len(lines)} 条，读回 {n} 条"
    print(f"\n已写 {OUT}：{n} 条（换行断言通过）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", action="store_true")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    if a.emit:
        return cmd_emit(a)
    return cmd_shape(a)


if __name__ == "__main__":
    sys.exit(main())
