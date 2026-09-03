# -*- coding: utf-8 -*-
"""中和替身与"仅本次会话"行为的守护。

对应 known-differences 里的三条：
  neutralized_refs_use_blank_pixel
  bootstrap_widgets_are_clone_reimplemented
  comment_and_note_actions_are_session_only
"""
from __future__ import annotations

import re
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
FRONTEND = CLONE / "frontend"
RUNTIME = CLONE / "static" / "clone-runtime.js"
PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


def test_no_about_blank_in_shipped_pages():
    """about:blank 不是图片 URL：浏览器仍会发起加载并以
    ERR_UNKNOWN_URL_SCHEME 失败，1007 个页面每页 2~3 条控制台报错，
    可见的 <img> 还会显示成碎图。替身必须是零请求的 data: URI。"""
    bad = []
    for p in FRONTEND.rglob("index.html"):
        if "about:blank" in p.read_text(encoding="utf-8", errors="replace"):
            bad.append(str(p.relative_to(FRONTEND)))
        if len(bad) >= 5:
            break
    assert not bad, f"{len(bad)}+ 页仍用 about:blank 作中和替身: {bad[:5]}"


def test_blank_pixel_is_actually_used():
    """反向钉住：中和确实发生过，而不是把引用整个删了。"""
    hits = 0
    for p in FRONTEND.rglob("index.html"):
        if PIXEL in p.read_text(encoding="utf-8", errors="replace"):
            hits += 1
        if hits >= 3:
            break
    assert hits >= 3, "出货页里找不到中和替身，中和逻辑可能被绕过了"


def test_session_only_features_are_implemented_not_inert():
    """笔记 / 评论点赞 / 通知清除在本站没有服务端端点，
    但按钮不许是死的 —— 必须有同源实现，仅不跨请求持久化。"""
    js = RUNTIME.read_text(encoding="utf-8", errors="replace")
    for fn in ("newAnnotation", "likeComment", "clickReply", "hideActivity"):
        assert re.search(r"window\.%s\s*=" % fn, js), f"{fn} 没有实现，控件是死的"
    assert "sessionStorage" in js, "hideActivity 需要在 reload 后仍然生效"


def test_analytics_stubs_make_no_request():
    """源站埋点函数必须存在（否则 onclick 抛错），且函数体内不许发请求。"""
    js = RUNTIME.read_text(encoding="utf-8", errors="replace")
    for fn in ("ga", "trackLearningJourney"):
        m = re.search(r"window\.%s\s*=\s*function[^;]*;" % fn, js)
        assert m, f"{fn} 未定义"
        body = m.group(0)
        for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "new Image"):
            assert forbidden not in body, f"{fn} 里出现 {forbidden}，埋点不许发请求"
