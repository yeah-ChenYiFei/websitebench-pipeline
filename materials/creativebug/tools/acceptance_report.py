#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成验收清单：§11 每条出口条件的实测读数。

原则：只填能从产物或运行结果里重新数出来的数。
拿不到读数的条目写「未测量」，不写「通过」——两者不是一回事。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = HERE.parent
SITE = W / "materials" / "creativebug"


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def count_pages() -> int:
    f = SITE / "clone" / "frontend"
    return len(list(f.rglob("index.html"))) if f.is_dir() else 0


def offline_closure() -> dict:
    """全站实测：残留脚本 / iframe / 会发请求的外域。"""
    F = SITE / "clone" / "frontend"
    ALLOW = {"schema.org", "ogp.me", "www.w3.org", "craftpip.github.io", "github.com"}
    FETCH = re.compile(
        r'\b(?:src|srcset|poster|data-src|formaction)\s*=\s*["\']((?:https?:)?//[^"\']+)'
        r'|<link\b[^>]*href\s*=\s*["\']((?:https?:)?//[^"\']+)'
        r'|url\(\s*["\']?((?:https?:)?//[^)"\']+)', re.I)
    sc = ifr = 0
    hosts: dict[str, int] = {}
    for p in F.rglob("index.html"):
        h = p.read_text(encoding="utf-8", errors="replace")
        sc += len(re.findall(r'<script\b(?![^>]*clone-runtime)', h, re.I))
        ifr += len(re.findall(r'<iframe\b', h, re.I))
        for m in FETCH.finditer(h):
            u = next(g for g in m.groups() if g)
            host = re.sub(r'^(https?:)?//', '', u).split('/')[0]
            if host not in ("www.creativebug.com", "creativebug.com") and host not in ALLOW:
                hosts[host] = hosts.get(host, 0) + 1
    return {"scripts": sc, "iframes": ifr, "external_hosts": hosts}


def main() -> int:
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}

    man = jload(SITE / "source-assets" / "manifest.json")
    routes = jload(SITE / "scope" / "routes.json")
    cps = jload(SITE / "scope" / "checkpoints.json")
    kd = jload(SITE / "scope" / "known-differences.json")
    vis = jload(HERE / "_visual.json")
    verify = jload(Path("/tmp/verify-final.json"))

    out["产物"] = {
        "构建页面": count_pages(),
        "声明资产": len(man["assets"]) if man else 0,
        "台账路由": len(routes["routes"]) if routes else 0,
        "检查点": len(cps["checkpoints"]) if cps else 0,
        "known_differences": len(kd["known_differences"]) if kd else 0,
        "known_differences 全部带 guarded_by":
            all(k.get("guarded_by") for k in kd["known_differences"]) if kd else False,
    }

    out["离线闭合"] = offline_closure()

    if verify:
        s = verify["sections"]["static"]
        out["verify_static"] = {"execution_complete": s["execution"]["complete"],
                                "findings": len(s["findings"])}
    else:
        out["verify_static"] = "未测量"

    if vis:
        rows = vis["results"]
        passed = [r for r in rows if r["pass"]]
        out["像素相似度"] = {
            "阈值": vis["threshold"], "比较条数": len(rows),
            "达标": len(passed), "未达标": len(rows) - len(passed),
            "缺帧": len(vis.get("missing", [])),
            "最低": min((r["score"] for r in rows), default=None),
            "中位": sorted(r["score"] for r in rows)[len(rows)//2] if rows else None,
            "未达标明细": [{"id": r["id"], "score": r["score"]} for r in rows if not r["pass"]],
        }
    else:
        out["像素相似度"] = "未测量"

    out["未完成项"] = []
    od = SITE / "OPEN-DEFECTS.md"
    if od.is_file():
        out["未完成项"] = [ln.strip("- ").strip()
                        for ln in od.read_text(encoding="utf-8").splitlines()
                        if ln.startswith("- **") and "已补" not in ln][:20]

    p = SITE / "ACCEPTANCE-READINGS.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:2400])
    print(f"\n→ {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
