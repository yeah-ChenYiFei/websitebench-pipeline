# -*- coding: utf-8 -*-
"""出货件不得对外部主机发起请求。

存在的理由：2026-08-30 补一个漏抓的 CSS 之后跑 merge_assets.py，它按 URL→名字
从 incoming 重新拷贝，把**已经本地化过的 23 个 CSS 覆盖回了原始抓取件**，
`@import url(//fonts.googleapis.com/...)` 因此复活。离线闭包被破坏，
而当时没有任何检查发现——三套浏览器审计全绿、113 条测试全绿。

浏览器审计发现不了，是因为它们只统计**失败**请求：外部请求会成功，
只是打到了第三方。所以必须直接钉住产物里的引用本身。

顺带钉住执行顺序：localize_css.py 必须排在 build_pages.py **和** merge_assets.py
之后。这条在 LESSONS.md 里记过一次（构建重铺 CSS），合并是同一个坑的第二次。
"""
from __future__ import annotations

import re
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
ASSETS = CLONE / "static" / "assets"

# url(...) 与 @import 的目标
REF = re.compile(r"""(?:@import\s+(?:url\()?|url\()\s*['"]?([^'")\s]+)""", re.I)

# 本地或无害的目标：站内绝对路径、相对路径、data:、about:blank
def _is_local(u: str) -> bool:
    u = u.strip()
    if not u:
        return True
    if u.startswith(("data:", "about:", "#")):
        return True
    if u.startswith("//"):          # 协议相对 —— 一定是外部主机
        return False
    if re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I):   # http: https: 等绝对 URL
        return False
    return True                      # /static/... 或 ../fonts/... 都算本地


def test_shipped_css_has_no_external_references():
    offenders = {}
    for f in sorted(ASSETS.glob("*.css")):
        bad = sorted({u for u in REF.findall(f.read_text(encoding="utf-8", errors="replace"))
                      if not _is_local(u)})
        if bad:
            offenders[f.name] = bad[:3]
    assert not offenders, (
        f"{len(offenders)} 个 CSS 仍引用外部主机（离线闭包被破坏）："
        f"{dict(list(offenders.items())[:5])}\n"
        "多半是 merge_assets.py 之后漏跑 localize_css.py。"
    )


def test_shipped_pages_have_no_external_stylesheets_or_scripts():
    """页面上的 <link rel=stylesheet> / <script src> 也不得指向外部主机。"""
    tag = re.compile(
        r"""<(?:link[^>]*\brel\s*=\s*['"]?stylesheet['"]?[^>]*\bhref|script[^>]*\bsrc)"""
        r"""\s*=\s*['"]([^'"]+)['"]""", re.I)
    offenders = {}
    for f in (CLONE / "frontend").rglob("index.html"):
        bad = sorted({u for u in tag.findall(f.read_text(encoding="utf-8", errors="replace"))
                      if not _is_local(u)})
        if bad:
            offenders[str(f.relative_to(CLONE))] = bad[:3]
        if len(offenders) >= 5:
            break
    assert not offenders, f"页面引用了外部样式表/脚本：{offenders}"
