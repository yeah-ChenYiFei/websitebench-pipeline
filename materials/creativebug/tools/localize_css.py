#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSS 本地化 —— 流水线的一步，不是一次性补丁。

源站 CSS 里的 @import 指向 fonts.googleapis.com，url() 可能指向别的外域。
两者都会让 inspect_asset 按 §7.1 第 10 步判定「CSS asset contains an external
runtime reference」，也确实违反离线闭合。

改写后的字节与抓取件不同，所以按 §7.3(c) 另存一份「实际服务的字节」到
source-assets/served/，runtime 副本从它复制 —— 契约要求两侧字节一致。

必须放在合并资产之后、生成清单之前：合并会用原始文件覆盖 runtime，
早先把这一步做成一次性修复，结果每次重跑收口都被冲掉。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import urllib.parse as up
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "materials" / "creativebug"
SRC = SITE / "source-assets" / "2026-08-28.creativebug-r1"
SERVED = SITE / "source-assets" / "served"
RUN = SITE / "clone" / "static" / "assets"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

IMPORT = re.compile(
    r'@import\s+(?:url\()?["\']?((?:https?:)?//[^"\')\s;]+)["\']?\)?\s*;?', re.I)
EXT_URL = re.compile(r'url\(\s*["\']?((?:https?:)?//[^)"\']+)["\']?\s*\)', re.I)


# 同源根相对 url()。这类既不是 @import 也不是外域，此前两条规则都不碰它，
# 于是 175 个已采集的字体与精灵图在页面上始终 404，全站字形因此不对。
SAME_ORIGIN_URL = re.compile(r'url\(\s*(["\']?)(/[^)"\'\s]+)\1\s*\)', re.I)


def source_path_map() -> dict[str, str]:
    """source_url 的路径 -> /static/assets/<文件名>，取自资产清单。"""
    man = SITE / "source-assets" / "manifest.json"
    if not man.is_file():
        return {}
    data = json.loads(man.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for a in data.get("assets", []):
        src = a.get("source_url") or ""
        run = a.get("runtime_path") or ""
        if not src or not run:
            continue
        path = up.urlparse(src).path
        if path:
            out[path] = "/static/assets/" + run.rsplit("/", 1)[-1]

    # 按文件名兜底：glyphicons / icomoon-cb / proxima-nova / video2 这几套字体
    # 文件确实在 static/assets 下，却没进清单，按路径查不到 —— 它们的
    # @font-face 因此一直指向 /ui/fonts/ 并 404，图标字形全是空的。
    if RUN.is_dir():
        for f in RUN.iterdir():
            if f.is_file() and "-" in f.name:
                out.setdefault("__base__" + f.name.split("-", 1)[1],
                               "/static/assets/" + f.name)
    return out


def family(url: str) -> str:
    u = url if url.startswith("http") else "https:" + url
    q = up.parse_qs(up.urlparse(u).query).get("family", [""])[0]
    return q.split(":")[0].replace("+", " ").strip().lower()


def main() -> int:
    SERVED.mkdir(parents=True, exist_ok=True)
    amap = json.loads((HERE / "_assets.json").read_text(encoding="utf-8"))["assets"]
    s = requests.Session(); s.headers.update({"User-Agent": UA})

    # 已有的字体 CSS：族名 → 本地文件名（SERVED 优先，它是服务字节）
    have: dict[str, str] = {}
    for url, name in amap.items():
        if "fonts.googleapis.com" not in url:
            continue
        for d in (SERVED, SRC):
            if (d / name).is_file():
                have.setdefault(family(url), name)
                break

    # 收集所有 CSS 里请求的字体族，缺的补下来并把 woff2 一并本地化
    need: set[str] = set()
    for f in SRC.glob("*.css"):
        for m in IMPORT.finditer(f.read_text(encoding="utf-8", errors="replace")):
            if "fonts.googleapis.com" in m.group(1):
                need.add(m.group(1))
    fetched = 0
    for url in sorted(need):
        fam = family(url)
        if fam in have:
            continue
        full = url if url.startswith("http") else "https:" + url
        try:
            r = s.get(full, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        txt = r.text
        for m in re.finditer(r'url\((https://fonts\.gstatic\.com/[^)]+)\)', txt):
            fu = m.group(1)
            fn = "font-" + Path(up.urlparse(fu).path).name
            if not (SRC / fn).is_file():
                fr = s.get(fu, timeout=30)
                if fr.status_code == 200:
                    (SRC / fn).write_bytes(fr.content)
                    shutil.copy2(SRC / fn, RUN / fn)
                    amap.setdefault(fu, fn)
            txt = txt.replace(fu, f"/static/assets/{fn}")
        name = f"font-css-{fam.replace(' ', '-')}.css"
        (SERVED / name).write_text(txt, encoding="utf-8")
        shutil.copy2(SERVED / name, RUN / name)
        amap.setdefault(full, name)
        have[fam] = name
        fetched += 1

    # 改写每个 CSS 的 @import、外域 url() 与同源绝对路径 url()
    rewritten = mapped = dropped = 0
    same_origin_mapped = same_origin_unmapped = 0
    pathmap = source_path_map()
    for f in sorted(SRC.glob("*.css")):
        css = f.read_text(encoding="utf-8", errors="replace")
        if not (IMPORT.search(css) or EXT_URL.search(css)
                or SAME_ORIGIN_URL.search(css)):
            continue

        def repl_import(m):
            nonlocal mapped, dropped
            n = have.get(family(m.group(1)))
            if n:
                mapped += 1
                return f'@import url("/static/assets/{n}");'
            dropped += 1
            return ""

        out = IMPORT.sub(repl_import, css)
        out = EXT_URL.sub("url(about:blank)", out)

        def repl_same_origin(m):
            nonlocal same_origin_mapped, same_origin_unmapped
            q, path = m.group(1), m.group(2)
            if path.startswith("/static/assets/"):
                return m.group(0)
            local = pathmap.get(path) or pathmap.get("__base__" + path.rsplit("/", 1)[-1])
            if local:
                same_origin_mapped += 1
                return f"url({q}{local}{q})"
            same_origin_unmapped += 1
            return m.group(0)

        out = SAME_ORIGIN_URL.sub(repl_same_origin, out)
        (SERVED / f.name).write_bytes(out.encode("utf-8"))
        shutil.copy2(SERVED / f.name, RUN / f.name)   # §7.3(a) copy2，两份物理文件
        rewritten += 1

    # 收尾：按文件名把剩下的同源 url() 接到本地资产。

    print(f"按文件名兜底改写 {localize_same_origin_by_basename()} 处")


    (HERE / "_assets.json").write_text(
        json.dumps({"assets": amap}, ensure_ascii=False, indent=1), encoding="utf-8")

    # 自证：改完之后不许还有外部引用
    sys.path.insert(0, str(HERE))
    from precheck import has_external_css_reference
    bad = [p.name for p in RUN.glob("*.css")
           if has_external_css_reference(p.read_text(encoding="utf-8", errors="replace"))]
    print(f"CSS 本地化: 改写 {rewritten} 个，@import 指向本地 {mapped} 处，"
          f"无副本移除 {dropped} 处，补下字体族 {fetched} 个")
    print(f"  残留外部引用的 CSS: {len(bad)}（须 0）{bad[:3]}")
    return 1 if bad else 0


def localize_same_origin_by_basename() -> int:
    """收尾：把已服务 CSS 里剩下的同源 url(/ui/...) 按文件名接到本地资产。

    这些字体（glyphicons / icomoon-cb / proxima-nova / video2）文件在
    static/assets 下，却没进资产清单，按 source_url 查不到，于是 @font-face
    一直指向 /ui/fonts/ 并 404 —— 赞/踩、播放键等图标字形全是空的。
    按文件名兜底，并且必须在**每次构建后**跑，否则重建会把结果覆盖掉。
    """
    by_base = {}
    if RUN.is_dir():
        for f in RUN.iterdir():
            if f.is_file() and "-" in f.name:
                by_base.setdefault(f.name.split("-", 1)[1], "/static/assets/" + f.name)
    pat = re.compile(r"""url\(\s*(['"]?)(/(?:ui|content|assets)/[^)'"\s]+)\1\s*\)""")
    total = 0

    def repl(m):
        nonlocal total
        q, path = m.group(1), m.group(2)
        local = by_base.get(path.split("?")[0].split("#")[0].rsplit("/", 1)[-1])
        if not local:
            return m.group(0)
        total += 1
        return f"url({q}{local}{q})"

    for d in (RUN, SERVED):
        if not d.is_dir():
            continue
        for f in d.glob("*.css"):
            t = f.read_text(encoding="utf-8", errors="replace")
            if "/ui/" not in t and "/content/" not in t:
                continue
            new = pat.sub(repl, t)
            if new != t:
                f.write_text(new, encoding="utf-8")
    return total


if __name__ == "__main__":
    sys.exit(main())

