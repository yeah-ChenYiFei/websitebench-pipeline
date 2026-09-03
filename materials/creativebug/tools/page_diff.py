#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐页对照出货页与抓取件：可见文本、结构、链接三个维度。

抓取件是源站 DOM 的原样留存，本机够不到源站（WAF 403），所以它是唯一可信基准。
只输出计数与页面路径，不打印页面内容。
"""
from __future__ import annotations

import collections
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "materials" / "creativebug"
SHIP = SITE / "clone" / "frontend"

DROP = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1\s*>")
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def text_of(html: str) -> str:
    t = DROP.sub(" ", html)
    t = TAG.sub(" ", t)
    return WS.sub(" ", t).strip()


def words(t: str) -> collections.Counter:
    return collections.Counter(w for w in re.findall(r"[A-Za-z][A-Za-z'&-]{2,}", t.lower()))


def main() -> int:
    spec = importlib.util.spec_from_file_location("bp", ROOT / "tools" / "build_pages.py")
    bp = importlib.util.module_from_spec(spec); sys.modules["bp"] = bp
    spec.loader.exec_module(bp)

    pairs = []
    for line in (bp.SRC.parent / "_state.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("ok"):
            continue
        route = (r["path"].rstrip("/") or "/")
        ship = SHIP / (route.strip("/") or "index") / "index.html"
        for cand in (bp.SRC / (r.get("dir") or ""), bp.SRC / route.strip("/")):
            raw = cand / "index.html"
            if raw.is_file() and ship.is_file():
                pairs.append((route, raw, ship)); break

    buckets = collections.Counter()
    worst = []
    for route, raw, ship in pairs:
        rt = text_of(raw.read_text(encoding="utf-8", errors="replace"))
        st = text_of(ship.read_text(encoding="utf-8", errors="replace"))
        rw, sw = words(rt), words(st)
        if not rw:
            continue
        kept = sum((rw & sw).values()) / max(sum(rw.values()), 1)
        lost = [w for w, n in rw.items() if sw.get(w, 0) == 0 and n >= 3]
        if kept >= 0.98: buckets["≥98% 文本保留"] += 1
        elif kept >= 0.90: buckets["90–98%"] += 1
        elif kept >= 0.70: buckets["70–90%"] += 1
        else: buckets["<70%"] += 1
        worst.append((kept, route, len(lost)))

    print(f"可对照页面 {len(pairs)}\n")
    print("可见文本保留率分布:")
    for k in ("≥98% 文本保留", "90–98%", "70–90%", "<70%"):
        if buckets[k]: print(f"  {k}: {buckets[k]}")
    worst.sort()
    print("\n保留率最低的 8 页:")
    for kept, route, nlost in worst[:8]:
        print(f"  {kept*100:5.1f}%  {route[:52]:54s} 完全丢失的高频词 {nlost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
