# -*- coding: utf-8 -*-
"""出货页上的每一个交互入口都必须真的接上。

两类失效，成因不同、症状也不同：

1. **内联 handler 调用未定义的全局函数** —— 抓取件保留了源站的
   onclick/onmouseover，源站 JS 按 §4.5 整体剔除后这些函数没有定义。
   点一下抛 ReferenceError。独立审阅实测覆盖 1009/1010 页。

2. **Bootstrap 控件没有行为** —— tab / collapse / dropdown 不写内联
   onclick，bootstrap.js 被剔除后它们**不报错、只是没反应**。
   这一类更危险：三套浏览器审计与 118 条测试当时全绿，而 531 个课程页上
   Chapters / Materials / Gallery / Annotations / Transcript 六个页签
   一个都点不开 —— 内容就在 DOM 里，出不来。

所以判据不能只看"有没有报错"，必须钉住"处理器存不存在"。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
FRONTEND = CLONE / "frontend"
RUNTIME = CLONE / "static" / "clone-runtime.js"

KEYWORDS = {
    "if", "for", "while", "switch", "return", "typeof", "catch", "function",
    "new", "void", "delete", "do", "else", "in", "of", "this", "true",
    "false", "null",
}
HANDLER = re.compile(r'\son\w+\s*=\s*"([^"]*)"', re.I)
# 裸的全局调用：前面不是 '.'，排除 obj.method()
BARE_CALL = re.compile(r'(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(')


def _runtime() -> str:
    return RUNTIME.read_text(encoding="utf-8", errors="replace")


def _defines(js: str, name: str) -> bool:
    return bool(re.search(
        r"(?:function\s+%s\s*\(|window\.%s\s*=)" % (re.escape(name), re.escape(name)),
        js,
    ))


def test_every_inline_handler_function_is_defined():
    js = _runtime()
    missing: dict[str, int] = {}
    for p in FRONTEND.rglob("index.html"):
        html = p.read_text(encoding="utf-8", errors="replace")
        for m in HANDLER.finditer(html):
            for fn in BARE_CALL.findall(m.group(1)):
                if fn in KEYWORDS or _defines(js, fn):
                    continue
                missing[fn] = missing.get(fn, 0) + 1
    assert not missing, (
        "内联 handler 调用了 clone-runtime.js 里没有的函数，点击会抛 "
        f"ReferenceError：{missing}"
    )


def test_bootstrap_widgets_have_a_handler():
    """tab / collapse / dropdown 在出货件里大量存在，就必须有接住它们的代码。

    这条不验证行为（那要浏览器），只钉住"接线存在" —— 因为这类控件失效时
    完全静默，靠跑测试看不出来。
    """
    js = _runtime()
    present = set()
    for p in FRONTEND.rglob("index.html"):
        html = p.read_text(encoding="utf-8", errors="replace")
        for kind in re.findall(r'data-toggle="([a-z]+)"', html):
            present.add(kind)
        if {"tab", "collapse", "dropdown"} <= present:
            break
    need = present & {"tab", "collapse", "dropdown"}
    unwired = [k for k in sorted(need) if f'data-toggle="{k}"' not in js]
    assert not unwired, (
        f"出货页有 data-toggle={unwired} 控件，但 clone-runtime.js 没有接线 —— "
        "bootstrap.js 已按 §4.5 剔除，不补就是静默失效的死控件。"
    )


def test_runtime_exports_are_reachable_from_inline_scope():
    """内联 handler 在全局作用域求值，只能看到 window.*。

    clone-runtime.js 是一个 IIFE：函数写在里面而不 window. 导出，
    内联 handler 一样看不见。这条防的是"以为补了、其实没导出"。
    """
    js = _runtime()
    exported = set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", js))
    assert exported, "clone-runtime.js 没有任何 window.* 导出"
    # 抽查几个由内联 handler 直接点名的
    for fn in ("liopen", "enlarge", "orderReviews", "topFunction"):
        assert fn in exported, f"{fn} 未通过 window 导出，内联 handler 取不到"
