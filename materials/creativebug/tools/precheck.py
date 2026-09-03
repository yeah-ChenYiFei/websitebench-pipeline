#!/usr/bin/env python3
"""creativebug 本地 precheck —— FAST-CLONE §7 规格。

逐字复刻引擎 `src/websitebench/offline_clone/assets.py` 的两处语义：
  - `inspect_asset()`        (assets.py:172)  推导顺序即语义，换一步换一个结论
  - `verify_asset_closure()` (assets.py:271)  11 个 issue code
另加 §7.3 三条硬约束、§7.4 路由闭合两条、§7.5 两条扫描。

纯文件系统检查，跑一遍约 2 分钟；不替代官方 verify，只把最容易反复踩的部分
从"验收期发现"提前成"构建期常量"。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import urllib.parse as up
from pathlib import Path
from typing import Any

SITE_HOSTS = ("creativebug.com", "www.creativebug.com")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
# 引擎的 inspect_asset 不把 .ico 交给 PIL（§7.1 第 7 步的后缀表里没有它），
# 因此它推导出 image/vnd.microsoft.icon 且 dimensions=None。声明成 octet-stream
# 会 ASSET_MISMATCH，声明成 image/* 又会 IMAGE_DIMENSIONS_UNDECLARED。
# 出路：生成清单时用 PIL 补出真实尺寸，MIME 用引擎推导的那个。
ICO_SUFFIXES = {".ico"}
MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/x-png": "image/png",
    "text/xml": "application/xml",
    "application/x-javascript": "text/javascript",
    "application/javascript": "text/javascript",
    "font/ttf": "font/ttf",
}


def normalized_mime(mime: str) -> str:
    base = (mime or "").split(";")[0].strip().casefold()
    return MIME_ALIASES.get(base, base)


def svg_dimensions(data: bytes) -> tuple[int, int] | None:
    """§7.1 第 5 步：从 SVG 属性解析尺寸（width/height 优先，回落 viewBox）。"""
    head = data[:4096].decode("utf-8", "replace")
    w = re.search(r'\bwidth\s*=\s*["\']([\d.]+)', head)
    h = re.search(r'\bheight\s*=\s*["\']([\d.]+)', head)
    if w and h:
        try:
            fw, fh = float(w.group(1)), float(h.group(1))
            if fw > 0 and fh > 0:
                return round(fw), round(fh)
        except ValueError:
            pass
    vb = re.search(r'\bviewBox\s*=\s*["\']([^"\']+)', head)
    if vb:
        try:
            _, _, rw, rh = (float(p) for p in vb.group(1).replace(",", " ").split())
        except (TypeError, ValueError):
            return None
        if rw > 0 and rh > 0:
            return round(rw), round(rh)
    return None


def avif_dimensions(data: bytes) -> tuple[int, int] | None:
    """§7.1 第 6 步：AVIF `ispe` box —— 逐字对齐 assets.py::_avif_dimensions。

    前置门不可省：必须先是 ftyp box 且品牌含 avif，才允许解析 ispe。
    早先直接在全文件里搜 ispe，一个 JPEG 里碰巧含这四个字节就会被判成
    AVIF 并算出 3390318844×1795416618 这种鬼数 —— 由引擎 verify 抓出。
    """
    if len(data) < 16 or data[4:8] != b"ftyp" or b"avif" not in data[8:32]:
        return None
    marker = 0
    while True:
        marker = data.find(b"ispe", marker)
        if marker < 0:
            return None
        if marker + 16 <= len(data):
            width = int.from_bytes(data[marker + 8 : marker + 12], "big")
            height = int.from_bytes(data[marker + 12 : marker + 16], "big")
            if width and height:
                return width, height
        marker += 4


def has_external_css_reference(css: str) -> bool:
    """§7.1 第 10 步：CSS 不得含外部运行时引用。"""
    for m in re.finditer(r'url\(\s*["\']?([^"\')]+)', css, re.I):
        u = m.group(1).strip()
        if u.startswith(("http://", "https://", "//")):
            return True
    return bool(re.search(r'@import\s+(url\()?["\']?(https?:)?//', css, re.I))


def inspect_asset(path: Path) -> dict[str, Any]:
    """assets.py:172 的逐字复刻。顺序不可调整。"""
    data = path.read_bytes()
    mime: str | None = None
    dimensions: tuple[int, int] | None = None
    suffix = path.suffix.casefold()
    stripped = data.lstrip().lower()

    # 1 非 html 后缀却是 HTML 外壳
    if suffix not in {".html", ".htm", ".xhtml"} and stripped.startswith(
        (b"<!doctype html", b"<html")
    ):
        raise ValueError("asset contains an HTML response shell")
    # 2/3 字体 magic
    if data.startswith(b"wOF2"):
        mime = "font/woff2"
    elif data.startswith(b"wOFF"):
        mime = "font/woff"
    # 4 后缀声称是字体但 magic 不对
    elif suffix in {".woff", ".woff2"}:
        raise ValueError(f"invalid {suffix.removeprefix('.').upper()} font magic")
    # 5 SVG
    elif suffix == ".svg" or stripped.startswith(b"<svg"):
        dimensions = svg_dimensions(data)
        mime = "image/svg+xml"
    else:
        # 6 AVIF
        avif = avif_dimensions(data)
        if avif:
            mime, dimensions = "image/avif", avif
        # 7 PIL 位图（注意 .ico 不在表里 → 走第 8 步，因此没有内在尺寸）
        elif suffix in IMAGE_SUFFIXES:
            try:
                from PIL import Image

                with Image.open(path) as image:
                    dimensions = image.size
                    mime = Image.MIME.get(image.format or "")
                    image.verify()
            except Exception as exc:
                raise ValueError(f"invalid image content: {exc}") from exc
    # 8 mimetypes 兜底
    guessed, _ = mimetypes.guess_type(path.name)
    mime = mime or guessed or "application/octet-stream"
    # 9 再查一次 HTML 外壳
    if normalized_mime(mime) not in {"text/html", "application/xhtml+xml"} and stripped.startswith(
        (b"<!doctype html", b"<html")
    ):
        raise ValueError("asset contains an HTML response shell")
    # 10 CSS
    if suffix == ".css":
        try:
            css = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"CSS asset is not UTF-8: {exc}") from exc
        if has_external_css_reference(css):
            raise ValueError("CSS asset contains an external runtime reference")
    # 11 MIME 别名归一
    return {
        "bytes": len(data),
        "mime_type": normalized_mime(mime),
        "dimensions": {"width": dimensions[0], "height": dimensions[1]} if dimensions else None,
    }


def _same_bytes(a: Path, b: Path) -> bool:
    """字节相同判定。先比大小再比分块摘要 —— 与逐字节比对同义，
    但不会把两份文件同时整个读进内存（资产从 316 个涨到上万个后这点开销就显著了）。"""
    sa, sb = a.stat().st_size, b.stat().st_size
    if sa != sb:
        return False
    import hashlib
    ha, hb = hashlib.blake2b(), hashlib.blake2b()
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            ba, bb = fa.read(1 << 20), fb.read(1 << 20)
            if not ba:
                break
            ha.update(ba); hb.update(bb)
    return ha.digest() == hb.digest()


class Issues(list):
    def add(self, asset_id: str | None, code: str, msg: str, blocking: bool = True) -> None:
        self.append({"asset": asset_id, "code": code, "message": msg, "blocking": blocking})


def check_asset_closure(root: Path, manifest_path: Path, issues: Issues) -> None:
    """assets.py:271 的 11 个 issue code。"""
    if not manifest_path.is_file():
        issues.add(None, "ASSET_SCOPE_PENDING", f"清单不存在: {manifest_path}")
        return
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = value.get("assets", [])
    closure_status = value.get("closure_status")

    if closure_status == "pending":
        issues.add(None, "ASSET_SCOPE_PENDING", "asset scope has not been frozen")
    required = [a for a in assets if a.get("required")]
    if closure_status == "declared" and not required:
        issues.add(None, "NO_REQUIRED_ASSETS", "declared 范围必须至少有一个 required 资产")

    # 身份检查需要全局视野（跨资产查重），保持串行
    identity: dict[tuple, tuple[str, str]] = {}
    bad_identity: set[str] = set()
    for a in assets:
        aid = a["id"]
        blocking = bool(a.get("required") or a.get("referenced_by") or a.get("priority") == "p0")
        if not a.get("referenced_by") and blocking:
            issues.add(aid, "UNREFERENCED_REQUIRED_ASSET",
                       "required 资产没有任何组件或检查点引用")
        for side in ("source", "runtime"):
            rel = a.get(f"{side}_path")
            if not rel:
                continue
            p = root / rel
            try:
                st = p.stat(follow_symlinks=False)
            except OSError:
                continue
            if getattr(st, "st_nlink", 1) != 1:
                issues.add(aid, "ASSET_MULTIPLE_HARD_LINKS",
                           f"{side} 副本 st_nlink={st.st_nlink}，必须为 1", blocking)
                bad_identity.add(aid); continue
            key = ("physical", st.st_dev, st.st_ino)
            owner = identity.get(key)
            if owner is None:
                identity[key] = (aid, side)
            elif owner[0] == aid:
                issues.add(aid, "SOURCE_RUNTIME_IDENTITY_ALIAS",
                           "source 与 runtime 解析到同一个物理身份", blocking)
                bad_identity.add(aid)
            else:
                issues.add(aid, "DUPLICATE_ASSET_PATH_IDENTITY",
                           f"{side} 复用了 {owner[0]}.{owner[1]} 的物理身份", blocking)
                bad_identity.add(aid)

    # 内容检查是纯 I/O，并行跑；结果按 id 排序回收，保证输出顺序稳定
    from concurrent.futures import ThreadPoolExecutor
    todo = [(a, root) for a in assets if a["id"] not in bad_identity]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for _aid, local in sorted(ex.map(_inspect_pair, todo), key=lambda r: r[0]):
            issues.extend(local)


def _inspect_pair(args):
    """单个资产的内容检查，在线程池里跑。不共享可变状态，只返回本地 issue 列表。

    §7.1 的推导顺序由 inspect_asset 保证，这里不重排；
    §7.3(b) 的 image/* 尺寸降级两侧同步，避免必然的 MISMATCH。
    """
    a, root = args
    local = Issues()
    aid = a["id"]
    blocking = bool(a.get("required") or a.get("referenced_by") or a.get("priority") == "p0")

    paths: dict[str, Path] = {}
    for side in ("source", "runtime"):
        rel = a.get(f"{side}_path")
        if not rel:
            local.add(aid, "ASSET_PATH_INVALID", f"{side}: 缺 {side}_path", blocking)
            continue
        p = root / rel
        if p.is_symlink():
            local.add(aid, "ASSET_PATH_INVALID", f"{side}: 是符号链接", blocking)
            continue
        paths[side] = p
    if set(paths) != {"source", "runtime"}:
        return aid, local

    observed: dict[str, dict] = {}
    for side, p in paths.items():
        try:
            if not p.is_file():
                raise FileNotFoundError(str(p))
            observed[side] = inspect_asset(p)
        except FileNotFoundError as exc:
            local.add(aid, "ASSET_MISSING", f"{side}: {exc}", blocking)
        except (OSError, ValueError) as exc:
            local.add(aid, "ASSET_INVALID", f"{side}: {exc}", blocking)
    if len(observed) != 2:
        return aid, local

    expected = {"bytes": a.get("bytes"),
                "mime_type": normalized_mime(a.get("mime_type", "")),
                "dimensions": a.get("dimensions")}
    for o in observed.values():
        if o["mime_type"].startswith("image/") and o["dimensions"] is None:
            o["mime_type"] = "application/octet-stream"
    if expected["mime_type"].startswith("image/") and expected["dimensions"] is None:
        local.add(aid, "IMAGE_DIMENSIONS_UNDECLARED", "image/* 资产必须声明内在尺寸", blocking)
        return aid, local

    diffs = [f"{side}.{f}={o[f]!r} != 声明 {expected[f]!r}"
             for side, o in observed.items() for f in expected if o[f] != expected[f]]
    if not _same_bytes(paths["source"], paths["runtime"]):
        diffs.append("source 与 runtime 字节不同")
    if diffs:
        local.add(aid, "ASSET_MISMATCH", "; ".join(diffs), blocking)
    return aid, local


def check_hardlinks(dirs: list[Path], issues: Issues) -> None:
    """§7.3(a) `find -type f -links +1` 必须为空。"""
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file() and not p.is_symlink() and p.stat(follow_symlinks=False).st_nlink != 1:
                issues.add(None, "HARDLINK_PRESENT", f"{p} st_nlink>1（必须 shutil.copy2）")


def hrefs(html: str) -> set[str]:
    out = set()
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', html, re.I):
        u = up.urlparse(up.urljoin("https://www.creativebug.com/", m.group(1)))
        if u.scheme in ("http", "https") and u.netloc in SITE_HOSTS:
            out.add((u.path.rstrip("/") or "/"))
    return out


def check_route_closure(frontend: Path, route_index: set[str], issues: Issues,
                        list_routes: list[str]) -> None:
    """§7.4：D0 首页出链 100% 闭合；D2 每类列表前两页出链 100% 闭合。"""
    home = frontend / "index.html"
    if home.is_file():
        dead = sorted(hrefs(home.read_text(encoding="utf-8", errors="replace")) - route_index)
        if dead:
            issues.add(None, "D0_HOME_DEAD_LINKS",
                       f"首页 {len(dead)} 条死链，前 5: {dead[:5]}")
    for route in list_routes:
        for page in (1, 2):
            rel = route.strip("/") or "index"
            cand = [frontend / rel / f"page-{page}" / "index.html",
                    frontend / rel / "index.html"] if page == 1 else \
                   [frontend / rel / f"page-{page}" / "index.html"]
            f = next((c for c in cand if c.is_file()), None)
            if f is None:
                issues.add(None, "D1_LIST_PAGE_MISSING", f"{route} 第 {page} 页缺失")
                continue
            dead = sorted(hrefs(f.read_text(encoding="utf-8", errors="replace")) - route_index)
            if dead:
                issues.add(None, "D2_ITEM_DEAD_LINKS",
                           f"{route} 第 {page} 页 {len(dead)} 条死链，前 5: {dead[:5]}")


def check_outbound(clone: Path, issues: Issues) -> None:
    """§7.5 扫描一：克隆里不该再有指向源站的绝对地址。

    只查会真正发起请求的位置（属性值与 CSS url()）。页面正文里出现的源站网址
    是内容本身 —— 隐私政策在陈述网站地址 —— 改写它等于篡改条款文本。

    实测这一段占 precheck 总耗时九成（1009 个页面约 300MB）。两处提速，
    都不改变判定语义：
      · 先用 bytes.find 做一次廉价的子串预筛，命中了才跑正则
      · 文件级并行，纯 I/O
    """
    # 正则的两个分支都要求 creativebug.com，所以只需筛这一个词。
    # 先前还筛了 url( —— 页面里到处是内联 CSS 的 url()，等于不过滤，
    # 反而把线程开销和多一次读取加了进来，实测比串行还慢。
    needle = b"creativebug.com"
    pat = re.compile(
        rb"""(?:src|href|action|poster|data-src|srcset|content)\s*=\s*["']\s*(?:https?:)?//(?:www\.)?creativebug\.com"""
        rb"""|url\(\s*["']?\s*(?:https?:)?//(?:www\.)?creativebug\.com""",
        re.I)
    targets = [p for p in clone.rglob("*")
               if p.is_file() and p.suffix.lower() in {".html", ".css", ".js", ".json", ".py"}]

    def scan(path: Path) -> str | None:
        b = path.read_bytes()
        # 绝大多数页面根本不含源站域名，预筛掉就不必跑正则
        if needle not in b:
            return None
        return str(path.relative_to(clone)) if pat.search(b) else None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        hits = [h for h in ex.map(scan, targets) if h]
    if hits:
        issues.add(None, "OUTBOUND_ABSOLUTE_URL",
                   f"{len(hits)} 个文件含源站绝对地址，前 5: {sorted(hits)[:5]}")


def check_credentials(deliver_root: Path, issues: Issues) -> None:
    """§7.5 扫描二 / §9 红线 1：扫要交付的字节流（含缓存目录），不是工作树。"""
    # 凭据本身不在服务器上（已 shred）。扫描模式取自 tools/scrub-rules.json
    # ——该文件 600 权限且 gitignore，只保存要查找的串，不保存口令。
    needles: list[bytes] = []
    rules = Path(__file__).resolve().parent / "scrub-rules.json"
    if rules.is_file():
        needles += [r["find"].encode() for r in json.loads(rules.read_text(encoding="utf-8"))]
    needles += [n.encode() for n in
                (os.environ.get("CREATIVEBUG_USER", ""), os.environ.get("CREATIVEBUG_PASS", "")) if n]
    if not needles:
        issues.add(None, "CRED_SCAN_UNAVAILABLE",
                   "既无 scrub-rules.json 也无环境变量，凭据扫描无法执行 —— 这是缺口不是通过",
                   blocking=True)
        return
    hits = []
    for p in deliver_root.rglob("*"):
        if p.is_file():
            try:
                b = p.read_bytes()
            except OSError:
                continue
            if any(n in b for n in needles):
                hits.append(str(p.relative_to(deliver_root)))
    if hits:
        issues.add(None, "CREDENTIAL_LEAK", f"交付目录含凭据: {hits[:5]}")
    for leftover in ("run/creds.env", "run/storage_state.json"):
        if (deliver_root / leftover).exists():
            issues.add(None, "CREDENTIAL_FILE_PRESENT", f"{leftover} 未删除")


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "materials" / "creativebug"
    issues = Issues()

    check_asset_closure(root, root / "source-assets" / "manifest.json", issues)
    check_hardlinks([root / "source-assets", root / "clone" / "static"], issues)

    routes_file = root / "scope" / "routes.json"
    route_index: set[str] = set()
    if routes_file.is_file():
        data = json.loads(routes_file.read_text(encoding="utf-8"))
        route_index = {r.get("path", "").rstrip("/") or "/" for r in data.get("routes", [])}
    list_routes_file = Path(__file__).resolve().parent / "list-routes.json"
    list_routes = json.loads(list_routes_file.read_text()) if list_routes_file.is_file() else []
    if route_index:
        check_route_closure(root / "clone" / "frontend", route_index, issues, list_routes)
    else:
        issues.add(None, "ROUTE_INDEX_EMPTY", "scope/routes.json 为空，闭合率未检查", blocking=False)

    if (root / "clone").is_dir():
        check_outbound(root / "clone", issues)
    check_credentials(root, issues)

    blocking = [i for i in issues if i["blocking"]]
    by_code: dict[str, int] = {}
    for i in issues:
        by_code[i["code"]] = by_code.get(i["code"], 0) + 1
    print(json.dumps({"total": len(issues), "blocking": len(blocking), "by_code": by_code},
                     ensure_ascii=False, indent=1))
    for i in issues[:40]:
        print(f"  [{'B' if i['blocking'] else '-'}] {i['code']}: {i['message']}")
    if len(issues) > 40:
        print(f"  … 另有 {len(issues) - 40} 条")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
