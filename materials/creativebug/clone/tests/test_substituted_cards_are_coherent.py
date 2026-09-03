# -*- coding: utf-8 -*-
"""改投卡片必须自洽：图 / 标题 / 讲师三者都指向落点课程。

背景：用户裁定保留链接改投（卡片指向另一门真实课程）。既然裁定如此，
卡片就不能一半说 X、一半指向 Y。

此前的实现是把图 `visibility:hidden` 藏掉、并试图改写标题，但标题候选选择器
只找 p/span/div —— 而标题是个 <a>，于是标题从未被改写过。结果是最差的一种：
**没有图 + 旧标题 + 指向另一门课**，subcategory-list 相似度 0.9485 → 0.9022。

现在换成落点课程自己的缩略图（tools/gen_class_thumbnails.py 生成映射表），
标题与讲师一并改写。这条测试钉住映射表的完整性与接线存在。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
FRONTEND = CLONE / "frontend"
THUMBS = CLONE / "static" / "class-thumbnails.json"
RUNTIME = CLONE / "static" / "clone-runtime.js"


def test_thumbnail_map_exists_and_covers_every_class():
    assert THUMBS.is_file(), "缺 class-thumbnails.json，改投卡片就没有落点图可换"
    thumbs = json.loads(THUMBS.read_text(encoding="utf-8"))
    detail = {f"/classseries/single/{p.parent.name}"
              for p in (FRONTEND / "classseries" / "single").glob("*/index.html")}
    missing = sorted(detail - set(thumbs))
    assert not missing, (
        f"{len(missing)} 门课没有缩略图映射，这些改投卡片只能藏图；"
        f"重跑 tools/gen_class_thumbnails.py。前 3 条: {missing[:3]}")


def test_thumbnail_targets_are_shipped_assets():
    thumbs = json.loads(THUMBS.read_text(encoding="utf-8"))
    assets = CLONE / "static" / "assets"
    bad = [v for v in list(thumbs.values())[:400]
           if not (assets / v.split("/")[-1]).is_file()]
    assert not bad, f"{len(bad)} 条缩略图映射指向未出货的资产，前 3: {bad[:3]}"


def test_runtime_realigns_title_instructor_and_image():
    js = RUNTIME.read_text(encoding="utf-8", errors="replace")
    assert "class-thumbnails.json" in js, "运行时没有读缩略图映射表"
    assert "instructor-link" in js, "运行时没有改写讲师显示名"
    # 标题候选必须包含 <a> —— 只找 p/span/div 正是当初改写失效的原因
    assert re.search(r'querySelectorAll\("a\[href\]"\)', js), \
        "标题候选里没有 a[href]，改写会重新失效"
