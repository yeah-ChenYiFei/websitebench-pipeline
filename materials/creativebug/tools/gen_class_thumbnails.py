#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为每门课记录一张缩略图，输出 clone/static/class-thumbnails.json。

为什么需要它：链接改投之后，卡片指向课程 Y，但卡片上的图仍是课程 X 的。
`realignSubstitutedCards()` 早先的处置是把图 `visibility:hidden` 藏掉
（"图对不上就撤掉，不留一张会误导的图"）。方向对，但结果是列表页出现空白瓷砖，
而且标题改写常常没落到实处 —— 卡片变成"没有图 + 旧标题 + 指向另一门课"，
比原样更糟，subcategory-list 的相似度也从 0.9485 掉到 0.9022。

有了这张表，改投卡片可以换成**落点课程自己的图**，卡片三要素（图/标题/讲师）
与落点一致，不再自相矛盾。

取图口径：只从**未被改投**的真实卡片上取（没有 data-cb-substituted 的 <a>），
那种卡片的图就是它自己那门课的图。改投卡片的图属于原课程，不能用。
og:image 不能用 —— 它指向未采集的 highres 变体（见 source-defects.md 第 2 条）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "materials" / "creativebug"
FRONTEND = SITE / "clone" / "frontend"
OUT = SITE / "clone" / "static" / "class-thumbnails.json"

SKIP = re.compile(r"logo|sprite|icon|placeholder|\.svg$", re.I)


def main() -> int:
    """用真正的 HTML 解析器，不用正则。

    早先用正则框 <a>…</a>，把内容窗口限成 600 字符 —— 缩略图锚点里嵌了好几层
    div，闭合标签常常落在窗口外，于是同一页上明明有真实卡片也取不到
    （kintsugi 就是这么漏的）。改用解析器后覆盖从 302 升到实际可得的上限。
    """
    from bs4 import BeautifulSoup

    thumbs: dict[str, str] = {}
    pages = 0
    for p in sorted(FRONTEND.rglob("index.html")):
        pages += 1
        soup = BeautifulSoup(p.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].split("?")[0].split("#")[0].rstrip("/")
            if not href.startswith("/classseries/single/"):
                continue
            if a.has_attr("data-cb-substituted"):
                continue              # 改投卡片的图属于原课程，不能采信
            if href in thumbs:
                continue
            img = a.find("img", src=True)
            if not img:
                continue
            src = img["src"]
            if not src.startswith("/static/assets/") or SKIP.search(src):
                continue
            thumbs[href] = src

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(thumbs, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    total = len(list((FRONTEND / "classseries" / "single").glob("*/index.html")))
    print(f"扫描 {pages} 页；{len(thumbs)} 门课取到缩略图 / 共 {total} 门课程详情页")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
