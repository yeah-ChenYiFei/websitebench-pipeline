#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§7.1 控件发现 —— 产出唯一交互分母。

规范要求分母由**运行时**自动发现，不是静态 grep：可见性、disabled、
cursor:pointer 这些只有渲染之后才知道。

产出 scope/interaction-ledger.json：每页的 discovered / excluded（带理由）/ required。
本工具只做发现与分母，不做执行 —— 执行是 §7.2，另有工具。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "materials" / "creativebug"
BASE = "http://127.0.0.1:9120"

# §7.1 的选择器清单，原样落地
SELECTOR = ("a[href], button, input, select, textarea, "
            '[role="button"], [role="link"], [role="tab"], '
            "[onclick], [tabindex], form")

DISCOVER_JS = """
(sel) => {
  const out = {discovered: [], excluded: []};
  const seen = new Set();
  const nodes = [...document.querySelectorAll(sel)];
  // 补充非语义控件：cursor:pointer 且带监听特征
  for (const e of document.querySelectorAll('*')) {
    if (nodes.includes(e)) continue;
    const s = getComputedStyle(e);
    if (s.cursor === 'pointer' && e.children.length === 0 &&
        (e.textContent || '').trim()) nodes.push(e);
  }
  const key = e => {
    const path = [];
    let n = e;
    while (n && n !== document.body && path.length < 6) {
      const idx = n.parentElement ? [...n.parentElement.children].indexOf(n) : 0;
      path.unshift(n.tagName + ':' + idx);
      n = n.parentElement;
    }
    return path.join('>');
  };
  for (const e of nodes) {
    const k = key(e);
    if (seen.has(k)) continue;
    seen.add(k);
    const s = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const rec = {
      key: k,
      tag: e.tagName,
      role: e.getAttribute('role') || null,
      label: ((e.textContent || e.getAttribute('aria-label') ||
               e.getAttribute('placeholder') || e.value || '') + '').trim().slice(0, 40),
      href: e.getAttribute('href'),
      type: e.getAttribute('type'),
    };
    // §7.1：只有真正隐藏/禁用/不可交互才排除，且必须记录理由
    if (s.display === 'none') { rec.reason = 'display:none'; out.excluded.push(rec); continue; }
    if (s.visibility === 'hidden') { rec.reason = 'visibility:hidden'; out.excluded.push(rec); continue; }
    if (r.width === 0 && r.height === 0) { rec.reason = 'zero-size'; out.excluded.push(rec); continue; }
    if (e.disabled === true) { rec.reason = 'disabled'; out.excluded.push(rec); continue; }
    if (e.getAttribute('aria-hidden') === 'true') { rec.reason = 'aria-hidden'; out.excluded.push(rec); continue; }
    if (e.tagName === 'INPUT' && ['hidden'].includes(e.type)) {
      rec.reason = 'input[type=hidden]'; out.excluded.push(rec); continue;
    }
    out.discovered.push(rec);
  }
  return out;
}
"""


def routes(limit: int) -> list[str]:
    raw = json.loads((SITE / "scope" / "routes.json").read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("routes", [])
    paths = [x if isinstance(x, str) else x.get("path", "") for x in items]
    paths = [p for p in paths if p]
    return paths[:limit] if limit else paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只扫前 N 条路由")
    ap.add_argument("--out", default=str(SITE / "scope" / "interaction-ledger.json"))
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright

    rs = routes(a.limit)
    pages: dict[str, dict] = {}
    tot_d = tot_e = 0
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        pg = ctx.new_page()
        for i, route in enumerate(rs, 1):
            try:
                pg.goto(BASE + route, wait_until="domcontentloaded", timeout=20000)
                pg.wait_for_timeout(250)
                res = pg.evaluate(DISCOVER_JS, SELECTOR)
            except Exception as exc:
                pages[route] = {"error": type(exc).__name__}
                continue
            d, e = res["discovered"], res["excluded"]
            tot_d += len(d)
            tot_e += len(e)
            pages[route] = {
                "discovered": len(d),
                "excluded": len(e),
                "required": len(d),          # 目前没有已批准的豁免，required = discovered
                "controls": d,
                "exclusions": e,
            }
            if i % 50 == 0:
                print(f"  {i}/{len(rs)}  累计发现 {tot_d}", flush=True)
        b.close()

    doc = {
        "schema_version": "creativebug.interaction-ledger.v1",
        "viewport": "desktop 1440x900",
        "actor": "anonymous",
        "note": ("§7.0 唯一交互分母。actor=anonymous、viewport=desktop 单一组合；"
                 "登录态与其他 viewport 尚未纳入，coverage 不得按本文件宣称全站 100%。"),
        "selector": SELECTOR,
        "totals": {"routes": len(rs), "discovered": tot_d,
                   "excluded": tot_e, "required": tot_d},
        "pages": pages,
    }
    out = pathlib.Path(a.out)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n路由 {len(rs)}  发现控件 {tot_d}  排除 {tot_e}  required {tot_d}")
    print("写入", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
