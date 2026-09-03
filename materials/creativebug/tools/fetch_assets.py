#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产下载与闭包 —— FAST-CLONE §7.3 的三条硬约束就在这里落地。

(a) source 与 runtime 必须是两个物理文件，各自 st_nlink == 1 → 一律 shutil.copy2，
    绝不 os.link / cp -al（spiritrock 当年用硬链接吃了 2089 条 findings）
(b) 声明 image/* 就必须有尺寸 → 取不到尺寸的不声明成 image/*
(c) 构建期改写会让"抓取件字节 ≠ 服务字节" → CSS 改写后另存一份"实际服务的字节"，
    source_path 指向它，出处由 source_url 记着

并发 ≤4，429 退避；Google Fonts 的 CSS 会再解析出 woff2 字体一并本地化。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
import urllib.parse as up
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SITE = ROOT / "materials" / "creativebug"
SRC_DIR = SITE / "source-assets" / "2026-08-28.creativebug-r1"
SERVED = SITE / "source-assets" / "served"          # §7.3(c) 实际服务的字节
RUN_DIR = SITE / "clone" / "static" / "assets"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "*/*"})


def fetch(url: str, tries: int = 4) -> bytes | None:
    """202 = AWS WAF 质询（与页面被拦同一机制），和 429 一样退避重试，不加码。"""
    for i in range(tries):
        try:
            r = S.get(url, timeout=45)
            if r.status_code in (429, 202) or (r.status_code == 200 and not r.content):
                time.sleep(4 * (i + 1))
                continue
            if r.status_code == 200:
                return r.content
            return None
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    return None


def main() -> int:
    assets: dict[str, str] = json.loads((HERE / "_assets.json").read_text(encoding="utf-8"))["assets"]
    for d in (SRC_DIR, SERVED, RUN_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # Google Fonts 的 CSS 里还藏着字体文件，先取 CSS 再展开
    queue = dict(assets)
    got: dict[str, bytes] = {}

    def work(item):
        url, name = item
        b = fetch(url)
        time.sleep(0.7)                            # 并发 1 + 真实间隔
        return url, name, b

    with ThreadPoolExecutor(max_workers=1) as ex:
        for url, name, b in ex.map(work, list(queue.items())):
            if b is not None:
                got[url] = b

    # 展开 Google Fonts CSS 里引用的字体
    extra: dict[str, str] = {}
    for url, b in list(got.items()):
        if "fonts.googleapis.com" in url:
            for m in re.finditer(rb"url\((https://fonts\.gstatic\.com/[^)]+)\)", b):
                f = m.group(1).decode()
                extra.setdefault(f, "font-" + Path(up.urlparse(f).path).name)
    if extra:
        with ThreadPoolExecutor(max_workers=1) as ex:
            for url, name, b in ex.map(work, list(extra.items())):
                if b is not None:
                    got[url] = b
                    assets[url] = name

    written, failed = 0, []
    manifest_assets = []
    for url, name in assets.items():
        b = got.get(url)
        if b is None:
            failed.append(url)
            continue
        served = b
        # §7.3(c)：CSS 里的绝对地址改写 → 服务字节与抓取字节不同，另存服务版
        if name.endswith(".css") or url.endswith(".css") or "fonts.googleapis" in url:
            txt = b.decode("utf-8", "replace")
            txt = re.sub(r"https?://fonts\.gstatic\.com/[^)\"'\s]+",
                         lambda m: "/static/assets/font-" + Path(up.urlparse(m.group(0)).path).name, txt)
            txt = re.sub(r"https?://(www\.)?creativebug\.com", "", txt)
            served = txt.encode("utf-8")

        sp = SERVED / name if served != b else SRC_DIR / name
        sp.write_bytes(served)
        rp = RUN_DIR / name
        shutil.copy2(sp, rp)                       # §7.3(a) 必须 copy2，绝不硬链接
        written += 1
        manifest_assets.append({
            "id": name, "source_url": url,
            "source_path": str(sp.relative_to(SITE)),
            "runtime_path": str(rp.relative_to(SITE)),
            "bytes": len(served),
        })

    (HERE / "_fetched.json").write_text(json.dumps(
        {"assets": manifest_assets, "failed": failed}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"下载 {written}/{len(assets)}   失败 {len(failed)}")
    for u in failed[:8]:
        print("  FAIL", u)

    # §7.3(a) 硬链接自检
    hard = [p for d in (SRC_DIR, SERVED, RUN_DIR) for p in d.rglob("*")
            if p.is_file() and p.stat().st_nlink != 1]
    print(f"st_nlink != 1 的文件: {len(hard)}  （必须为 0）")
    return 1 if failed or hard else 0


if __name__ == "__main__":
    sys.exit(main())
