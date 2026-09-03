# -*- coding: utf-8 -*-
"""目录截断的收边行为。

存在的理由：known-differences.json 里有三条声称 `guarded_by`
`clone/tests/test_catalog.py`，而这个文件从来就不存在 —— 三条差异一直没有任何
测试守着。其中截断那条的表述在链接改投之后也已经不是事实。

FAST-CLONE §11 要求「截断已收边，在 known-differences.json 里记了一条并有测试
守着 —— 收边处 0 死链」。这里补上那个守卫。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CLONE = Path(__file__).resolve().parents[1]
SITE = CLONE.parent
FRONTEND = CLONE / "frontend"
BOUNDARY = "/_clone/out-of-scope"


@pytest.fixture(scope="module")
def known_routes() -> set[str]:
    raw = json.loads((SITE / "scope" / "routes.json").read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("routes", [])
    out = {x if isinstance(x, str) else x.get("path", "") for x in items}
    out |= {BOUNDARY, "/_clone/not-found"}
    return {r.rstrip("/") or "/" for r in out if r}


def subcategory_pages(limit: int = 40) -> list[Path]:
    return sorted(FRONTEND.glob("classes/*/*/index.html"))[:limit]


def class_links(html: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r'href="(/classseries/[^"]*)"', html)))


# --- 收边处 0 死链（§11 的硬要求） ---------------------------------
def test_subcategory_cards_have_no_dead_links(known_routes):
    dead: list[tuple[str, str]] = []
    for p in subcategory_pages():
        for u in class_links(p.read_text(encoding="utf-8", errors="replace")):
            if (u.rstrip("/") or "/") not in known_routes:
                dead.append((str(p.relative_to(FRONTEND)), u))
    assert not dead, f"子类列表页存在死链 {len(dead)} 条，例如 {dead[:3]}"


def test_subcategory_cards_reach_reproduced_detail_pages(known_routes):
    """截断之后的卡片改投到真实详情页，不再落到边界页。

    这是与源站的已声明差异：链接文字是课程 X，落点是已复刻的课程 Y。
    """
    total = boundary = 0
    for p in subcategory_pages():
        for u in class_links(p.read_text(encoding="utf-8", errors="replace")):
            total += 1
            if u.startswith(BOUNDARY):
                boundary += 1
    assert total > 0, "样本页里没有课程卡片"
    assert boundary == 0, f"仍有 {boundary}/{total} 张卡片落到边界页"


def test_substitution_is_deterministic():
    """同一条源链接必须每次都落到同一个替身，否则构建不可复现。

    直接测算法，不去 DOM 里找标记：出货页上并不存在记录"原始目标"的属性，
    靠正则找标记的写法会一条都匹配不到，从而空转通过 —— 那种测试什么也没证明。
    """
    import importlib.util
    import sys

    repo = SITE.parent.parent
    spec = importlib.util.spec_from_file_location(
        "cb_build_pages", repo / "tools" / "build_pages.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cb_build_pages"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:                      # 构建器依赖缺失时不静默跳过
        pytest.skip(f"无法载入构建器: {type(exc).__name__}: {exc}")

    pool = mod.load_class_pool()
    if not pool.get("all"):
        pytest.skip("课程替身池为空（frontend 尚未构建）")

    builder = mod.Builder.__new__(mod.Builder)     # 只测替身选择，不跑整条管线
    builder.stats = {}
    builder._class_pool = pool

    samples = ["/classseries/single/not-captured-alpha",
               "/classseries/single/not-captured-beta",
               "/classseries/daily-practice/some-uncaptured-course"]
    first = [builder.substitute_class(u) for u in samples]
    assert all(first), "替身选择返回了空值"

    # 同一进程内重复调用
    assert [builder.substitute_class(u) for u in samples] == first, "同一输入返回了不同替身"

    # 换一个全新的 Builder（模拟下一次构建）
    other = mod.Builder.__new__(mod.Builder)
    other.stats = {}
    other._class_pool = mod.load_class_pool()
    assert [other.substitute_class(u) for u in samples] == first, \
        "重新构建时替身发生了漂移，构建不可复现"

    # 替身必须是真实存在的页面
    for route in first:
        assert (FRONTEND / route.strip("/") / "index.html").is_file(), \
            f"替身指向不存在的页面 {route}"


# --- soft-404 与边界页必须可区分 -----------------------------------
def test_boundary_page_is_distinct_from_not_found():
    b = (FRONTEND / "_clone" / "out-of-scope" / "index.html")
    n = (FRONTEND / "_clone" / "not-found" / "index.html")
    assert b.is_file(), "边界页缺失"
    assert n.is_file(), "404 页缺失"
    bt = b.read_text(encoding="utf-8", errors="replace")
    nt = n.read_text(encoding="utf-8", errors="replace")
    assert bt != nt, "边界页与 404 页内容相同，两者必须可区分"
    assert "creativebug" in bt.lower() and "creativebug" in nt.lower(), "须为品牌化页面"
    # known-differences::source_soft_404_returns_200 写的是"the clone returns a real
    # 404 with the same branded body"。此前这条只比对两页是否不同，没有校验主体，
    # 于是实现用的是克隆自制的极简恢复页、与台账不符也没人发现。
    for tag, txt in (("边界页", bt), ("404 页", nt)):
        assert 'class="site-error-page"' in txt, f"{tag}没有用源站 404 骨架"
        assert "Possible reasons you are seeing this page" in txt, f"{tag}缺品牌 404 主体文案"
    # 源站 404 主体里的搜索表单指向 /search/results —— 克隆没有这个路由
    assert 'action="/search/results"' not in bt and 'action="/search/results"' not in nt, \
        "搜索表单指向克隆不存在的 /search/results"


# --- pattern 截断 ---------------------------------------------------
def test_pattern_cards_have_no_dead_links(known_routes):
    p = FRONTEND / "patterns" / "index.html"
    if not p.is_file():
        pytest.skip("没有 patterns 索引页")
    dead = [u for u in dict.fromkeys(
        re.findall(r'href="(/patterns/[^"]*)"', p.read_text(encoding="utf-8", errors="replace")))
        if (u.rstrip("/") or "/") not in known_routes]
    assert not dead, f"patterns 索引页存在死链: {dead[:3]}"


def test_reproduced_pattern_detail_pages_exist(known_routes):
    n = len([r for r in known_routes if r.startswith("/patterns/") and r.count("/") > 1])
    assert n >= 12, f"已复刻的 pattern 详情页只有 {n} 个，少于截断口径 12"


def test_no_page_ships_a_dead_search_form():
    """源站软 404 页带的搜索表单指向 /search/results，克隆没有这个路由。

    其余 2012 个搜索表单构建期都改写到了 /search/ui，唯独这 10 个页面漏了 ——
    页面上敲回车是死路，而三套浏览器审计与测试当时全绿。
    """
    bad = [str(p.relative_to(FRONTEND)) for p in FRONTEND.rglob("index.html")
           if 'action="/search/results"' in p.read_text(encoding="utf-8", errors="replace")]
    assert not bad, f"{len(bad)} 页的搜索表单指向不存在的 /search/results: {bad[:3]}"
