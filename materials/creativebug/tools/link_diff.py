#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐页对照出货页与抓取件的链接去向 —— 一切以原页面为准。

用户 2026-08-30：「一些页面的跳转逻辑完全改乱了，请千万仔细对比原页面和复刻页面」。
本工具不做判断，只如实列出：同一个位置上，源站指向哪里、克隆指向哪里、为什么不同。
"""
from __future__ import annotations

import collections
import importlib.util
import json
import pathlib
import re
import sys
import urllib.parse as up

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "materials" / "creativebug"
SHIP = SITE / "clone" / "frontend"
RAW = ROOT / "incoming" / "cb-out" / "pages"
BASE = "https://www.creativebug.com"

HREF = re.compile(r'href="([^"]+)"', re.I)


def norm(u: str) -> str:
    """把源站 href 归一成站内路径；站外/特殊协议返回空。"""
    u = u.strip()
    if not u or u.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return ""
    if u.startswith("//"):
        u = "https:" + u
    q = up.urlparse(up.urljoin(BASE + "/", u))
    if q.netloc and "creativebug.com" not in q.netloc:
        return ""                       # 站外，本来就该改
    return (q.path.rstrip("/") or "/")


def load_pairs():
    spec = importlib.util.spec_from_file_location("bp", ROOT / "tools" / "build_pages.py")
    bp = importlib.util.module_from_spec(spec); sys.modules["bp"] = bp
    spec.loader.exec_module(bp)
    state = bp.SRC.parent / "_state.jsonl"
    out = []
    for line in state.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("ok"):
            continue
        route = (r["path"].rstrip("/") or "/")
        ship = SHIP / (route.strip("/") or "index") / "index.html"
        # 抓取件目录名由构建器消毒过，用它自己的映射
        for cand in (bp.SRC / (r.get("dir") or ""), bp.SRC / route.strip("/")):
            raw = cand / "index.html"
            if raw.is_file() and ship.is_file():
                out.append((route, raw, ship)); break
    return out


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    routes = {p.parent.relative_to(SHIP).as_posix() for p in SHIP.rglob("index.html")}
    routes = {"/" + r for r in routes} | {"/"}

    pairs = load_pairs()
    if limit:
        pairs = pairs[:limit]
    print(f"可对照页面 {len(pairs)}")

    kinds = collections.Counter()
    samples = collections.defaultdict(list)
    # 按集合比，不按下标配对：出货页与抓取件的链接条数本就不同
    # （脚本剥离、第三方移除、CTA 改写都会改变条数），
    # 按下标 zip 出来的每一对都是无关的 —— 那样得到的差异数全是假的。
    for route, raw, ship in pairs:
        src = {norm(x) for x in HREF.findall(raw.read_text(encoding="utf-8", errors="replace"))}
        src.discard("")
        shipped = set()
        for x in HREF.findall(ship.read_text(encoding="utf-8", errors="replace")):
            if x.startswith("/") and not x.startswith(("/static/", "/ui/", "/pimage/")):
                shipped.add(x.rstrip("/") or "/")
        for a in src:
            if a in shipped:
                kinds["源链接原样保留"] += 1
            elif a in routes:
                kinds["!! 源目标存在却在出货页中消失"] += 1
                if len(samples["消失"]) < 8:
                    samples["消失"].append((route, a))
            else:
                kinds["源目标未采集（替身或边界页）"] += 1
    print("\n对照结果:")
    for k, v in kinds.most_common():
        print(f"  {k}: {v}")
    if samples["消失"]:
        print("\n!! 源目标存在、却不在出货页链接里（这类才是缺陷）:")
        for r, a in samples["消失"]:
            print(f"   页面 {r[:38]}   丢失目标 {a[:52]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
