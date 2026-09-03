#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""creativebug 构建器：抓取件 DOM → 可离线服务的页面。

五件事，顺序即语义：
  1. 剔除源站全部 <script>（内联 3664 + 外链）并注入 clone-runtime.js
     —— 依据 FAST-CLONE §4.5「行为等价，不是源码等价」
  2. 去第三方：28 个追踪/广告/社交域的 script、iframe、img 像素、preconnect 全删
  3. 地址改写：同源资产 /ui/* /content/* → /static/assets/<hash>；
     Google Fonts → 本地化；站内链接 → 克隆路由
  4. 截断收边（§5.2(b)）：超出 N=12 的课程卡 → 边界页，不留死链、不用 404
  5. 视频剔除（口径 7）：播放源不下载，播放器换成布局等价占位

产物：clone/frontend/<route>/index.html + 资产提取清单 tools/_assets.json
"""
from __future__ import annotations

import argparse
import hashlib
import html
import sqlite3
import zlib
import json
import re
import sys
import urllib.parse as up
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CFG = json.loads((HERE / "site-config.json").read_text(encoding="utf-8"))
SRC = ROOT / "incoming" / "cb-out" / "pages"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrub import load_rules, scrub_text          # noqa: E402  管线末端的 PII 兜底

SCRUB_LITERALS = load_rules()
OUT = ROOT / "materials" / "creativebug" / "clone" / "frontend"

BASE = f"https://{CFG['canonical_host']}"
IN_SCOPE = set(CFG["in_scope_hosts"])
THIRD = set(CFG["third_party_hosts"])

# 中和外部资源引用时的替身。
# 早先用 about:blank —— 它不是图片 URL，浏览器照样发起加载并以
# ERR_UNKNOWN_URL_SCHEME 失败，1007 个出货页因此每页 2~3 条控制台报错，
# 可见的 <img> 还会显示成碎图（"Login with Amazon" 按钮 708 处即是）。
# 1x1 透明 GIF 的 data: URI 不产生任何请求，也不报错。
BLANK_PIXEL = ("data:image/gif;base64,"
               "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
LOCALIZE = set(CFG["localize_hosts"])
OUT_ORIGIN = set(CFG["out_of_origin_hosts"])
EXTERNAL = set(CFG.get("external_link_hosts", []))
BOUNDARY = CFG["boundary_route"]
AUTH_HOME = "/_clone/home-authenticated"
BOUNDARY_PATHS = tuple(CFG.get("boundary_paths", []))
FORM_ACTIONS = CFG.get("form_actions", {})
FIELD_ALIASES = CFG.get("field_aliases", {})
FORM_ROUTE_DEFAULTS = CFG.get("form_route_defaults", {})
FORM_RETARGET = CFG.get("form_retarget_by_route", {})
VIDEO = re.compile("|".join(CFG["video_patterns"]), re.I)
ASSET_EXT = re.compile(r"\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|otf|eot)($|[?#])", re.I)


# ---------------------------------------------------------------- helpers
def norm_route(raw: str) -> str | None:
    """站内链接 → 归一路由；站外/锚点/协议链接返回 None。"""
    raw = html.unescape(raw.strip())
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    if raw.startswith("//"):
        raw = "https:" + raw
    q = up.urlparse(up.urljoin(BASE + "/", raw))
    if q.netloc and q.netloc not in IN_SCOPE:
        return None
    # 查询串一律丢掉：克隆按路径提供页面，`?from=profile-menu` 这类只是源站的
    # 来源追踪参数。此前把它拼回路由再去 routes 里查，必然查不到，
    # 于是 /account/rewards 这类**真实已复刻**的页面被当成未知路由丢进边界页
    # —— 全站 2571 条，集中在导航与账户菜单。
    return q.path.rstrip("/") or "/"


def asset_key(url: str) -> str:
    """资产 URL → 稳定的本地文件名。内容哈希在下载阶段再核，这里先按 URL 定名。"""
    q = up.urlparse(url if "//" in url else up.urljoin(BASE + "/", url))
    stem = Path(q.path).name or "asset"
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:60]
    h = hashlib.sha1(f"{q.netloc}{q.path}?{q.query}".encode()).hexdigest()[:10]
    return f"{h}-{stem}"


DIV_TAG = re.compile(r"(?i)<(/?)div\b[^>]*>")


def cut_balanced_div(h: str, opener: re.Pattern, replace) -> tuple[str, int]:
    """删掉整个 <div>…</div> 块，按嵌套深度找真正的闭合标签。

    不能用 `<div ...>.*?</div>` 这种非贪婪正则：嵌套结构里它在第一个 </div>
    就收尾，于是开标签被删、外层 </div> 变成孤儿，标记随即失衡。实测这条
    让 534/1009 个出货页的 div 开闭数对不上，浏览器解析时把后续元素提出了
    原来的父节点 —— 课程详情页因此丢掉四层包裹，其中一层带着 overflow:hidden，
    页面从此横向溢出。
    """
    out, pos, n = [], 0, 0
    while True:
        m = opener.search(h, pos)
        if not m:
            out.append(h[pos:])
            break
        out.append(h[pos:m.start()])
        depth, i = 1, m.end()
        while depth and (t := DIV_TAG.search(h, i)):
            depth += -1 if t.group(1) else 1
            i = t.end()
        if depth:                       # 没找到配对的闭合标签：原样保留，不冒险
            out.append(h[m.start():m.end()])
            pos = m.end()
            continue
        out.append(replace(m))
        pos = i
        n += 1
    return "".join(out), n


# 布局必需的第三方样式表：本地自供，不能按"外链一律中和"处理。
# 源站的 trial/create-account 等页面用 Bootstrap 3 栅格（col-xs-*/col-sm-*）排版，
# 而它是从 CDN 加载的，被第三方剥离一并带走 —— 套餐对比表因此塌成一列。
# Bootstrap 是 MIT 开源框架，离线场景下取到本地是标准做法。
VENDORED_CSS = {
    "maxcdn.bootstrapcdn.com/bootstrap/3.3.2/css/bootstrap.min.css":
        "/static/assets/d31bef450e-bootstrap.min.css",
}


def vendor_external_css(h: str) -> tuple[str, int]:
    n = 0
    for needle, local in VENDORED_CSS.items():
        for form in ("//" + needle, "https://" + needle, "http://" + needle):
            if form in h:
                h = h.replace(form, local)
                n += 1
    return h, n


def _asset_path_map() -> dict:
    """source_url 的路径 -> /static/assets/<文件名>，取自资产清单。"""
    import urllib.parse as _up
    man = ROOT / "materials" / "creativebug" / "source-assets" / "manifest.json"
    if not man.is_file():
        return {}
    out = {}
    for a in json.loads(man.read_text(encoding="utf-8")).get("assets", []):
        src, run = a.get("source_url") or "", a.get("runtime_path") or ""
        if src and run:
            out[_up.urlparse(src).path] = "/static/assets/" + run.rsplit("/", 1)[-1]

    # 按文件名兜底：有些资产（glyphicons / icomoon-cb / proxima-nova / video2
    # 这几套字体）文件确实在 static/assets 下，却没进清单，按路径查不到。
    # 文件名形如 <hash>-<原名>，据此补一张 原名 -> 本地路径 的表。
    assets_dir = ROOT / "materials" / "creativebug" / "clone" / "static" / "assets"
    by_base = {}
    if assets_dir.is_dir():
        for f in assets_dir.iterdir():
            if f.is_file() and "-" in f.name:
                by_base.setdefault(f.name.split("-", 1)[1], "/static/assets/" + f.name)
    out["__by_base__"] = by_base
    return out


_INLINE_URL = re.compile(r"""url\(\s*(['"]?)(/[^)'"\s]+)\1\s*\)""")


def localize_inline_css(h: str, amap: dict) -> tuple[str, int]:
    """改写页面内联 <style> 里的同源 url()。

    此前只本地化 static/assets 下的 .css 文件，而 @font-face 写在页面内联
    <style> 里 —— glyphicons / icomoon-cb / proxima-nova / video2 四套字体
    因此一直 404，赞/踩、播放键等图标字形全是空的。
    """
    n = 0

    def one(block: str) -> str:
        nonlocal n

        def repl(m):
            nonlocal n
            q, path = m.group(1), m.group(2)
            if path.startswith("/static/assets/"):
                return m.group(0)
            clean = path.split("?")[0].split("#")[0]
            local = amap.get(clean)
            if not local:
                local = (amap.get("__by_base__") or {}).get(clean.rsplit("/", 1)[-1])
            if not local:
                return m.group(0)
            n += 1
            return f"url({q}{local}{q})"

        return _INLINE_URL.sub(repl, block)

    out = re.sub(r"(?is)(<style[^>]*>)(.*?)(</style\s*>)",
                 lambda m: m.group(1) + one(m.group(2)) + m.group(3), h)
    return out, n


class Builder:
    def __init__(self, routes: set[str], detail_allow: set[str]):
        self.routes = routes                 # 克隆里真实存在的路由
        self.detail_allow = detail_allow     # N=12 截断后保留的课程详情
        self.assets: dict[str, str] = {}     # 原始 URL → 本地文件名
        self.stats = Counter()

    # -- 1. script --------------------------------------------------
    def strip_scripts(self, h: str) -> str:
        h, n = re.subn(r"(?is)<script\b[^>]*>.*?</script\s*>", "", h)
        self.stats["script_removed"] += n
        h, n = re.subn(r"(?is)<noscript\b[^>]*>.*?</noscript\s*>", "", h)
        self.stats["noscript_removed"] += n
        return h

    # -- 2b. 通用外域中和 -------------------------------------------
    def neutralize_external(self, h: str) -> str:
        """按位置判定，不按域名清单判定。

        枚举域名永远漏 —— 1007 页里有 325 个外域，绝大多数是课程正文里的外链。
        真正决定要不要处理的是它出现在哪个位置：
          会发请求（src/srcset/poster/link href/iframe/CSS url()）→ 中和
          导航（a href）→ 边界页
          命名空间与署名（xmlns/itemtype/prefix/注释）→ 原样保留，浏览器从不 fetch
        """
        def in_scope(u: str) -> bool:
            """相对路径（/pimage/…）的 netloc 是空串 —— 那是同源，不是外域。

            早先直接判 netloc in IN_SCOPE，把站内背景图全中和成了 about:blank，
            916/1009 页的区块背景因此变白。
            """
            if u.startswith("//"):
                u = "https:" + u
            netloc = up.urlparse(u).netloc
            return (not netloc) or netloc in IN_SCOPE

        # 会发请求的属性
        def repl_fetch(m):
            attr, quote, url = m.group(1), m.group(2), m.group(3)
            if url.startswith(("data:", "/", "#")) or in_scope(url):
                return m.group(0)
            self.stats["external_fetch_neutralized"] += 1
            return f'{attr}={quote}{BLANK_PIXEL}{quote}'

        h = re.sub(r'\b(src|srcset|poster|data-src|data-srcset|formaction)\s*=\s*(["\'])'
                   r'((?:https?:)?//[^"\']+)\2', repl_fetch, h, flags=re.I)
        # <link href> 是资源加载，不是导航
        def repl_link(m):
            tag = m.group(0)
            u = re.search(r'href\s*=\s*["\']((?:https?:)?//[^"\']+)', tag, re.I)
            if u and not in_scope(u.group(1)):
                self.stats["external_link_tag_removed"] += 1
                return ""
            return tag
        h = re.sub(r'(?i)<link\b[^>]*>', repl_link, h)
        # iframe 一律整块移除（reCAPTCHA、播放器等）
        h, n = re.subn(r'(?is)<iframe\b[^>]*>.*?</iframe\s*>', "", h)
        self.stats["iframe_removed"] += n
        h, n = re.subn(r'(?i)<iframe\b[^>]*/?>', "", h)
        self.stats["iframe_removed"] += n
        # CSS url()
        # 引号可能写成 HTML 实体：属性值里的 " 必须转义，于是内联样式长这样
        #   style="background-image: url(&quot;https://cdn-widget-assets.yotpo.com/…&quot;)"
        # 旧正则只认裸引号，这类第三方背景图整个漏过中和 —— /rewards 与
        # /account/rewards 共 22 处，浏览器实测真的发出 11 次外发请求，离线闭包被打破。
        QUOTE = r'(?:["\']|&quot;|&#34;|&apos;|&#39;)'
        def repl_css(m):
            if in_scope(m.group(1)):
                return m.group(0)
            self.stats["css_url_neutralized"] += 1
            return f"url({BLANK_PIXEL})"
        h = re.sub(rf'url\(\s*{QUOTE}?\s*((?:https?:)?//[^)\s"\']*?)\s*{QUOTE}?\s*\)',
                   repl_css, h, flags=re.I)
        return h

    # -- 2. 第三方 --------------------------------------------------
    def strip_third_party(self, h: str) -> str:
        def host_of(u: str) -> str:
            if u.startswith("//"):
                u = "https:" + u
            return up.urlparse(u).netloc if u.startswith(("http://", "https://")) else ""

        # 整标签删除：iframe / img 像素 / link preconnect|dns-prefetch
        def drop_tag(m):
            tag = m.group(0)
            src = re.search(r'(?:src|href)\s*=\s*["\']([^"\']+)', tag, re.I)
            if src and host_of(html.unescape(src.group(1))) in THIRD:
                self.stats["third_party_tag_removed"] += 1
                return ""
            return tag

        h = re.sub(r"(?is)<iframe\b[^>]*>.*?</iframe\s*>", drop_tag, h)
        h = re.sub(r"(?i)<(?:img|link|source|embed)\b[^>]*/?>", drop_tag, h)
        # 残留的第三方裸 URL（内联 CSS 里的 url() 等）
        for host in THIRD:
            h, n = re.subn(rf"https?://{re.escape(host)}[^\s\"'\)>]*", BLANK_PIXEL, h)
            self.stats["third_party_url_neutralized"] += n
        return h

    def _poster_for(self, h: str) -> str | None:
        """挑一张页内已改写到本地的图作为播放器占位背景。

        源站那块是海报帧，来自 JW Player 的视频 CDN —— 按口径 7 不取。
        但课程页 100% 都有同源 /pimage 图且已下载，用它比放一个纯黑块
        更接近源站，也不需要再取任何视频侧资源。
        """
        m = re.search(r'(?:src|data-src)\s*=\s*["\'](/static/assets/[^"\']+\.(?:jpe?g|png|webp))',
                      h, re.I)
        return m.group(1) if m else None

    # -- 5. 视频 ----------------------------------------------------
    def strip_video(self, h: str) -> str:
        poster = self._poster_for(h)

        def drop(m):
            tag = m.group(0)
            # <video>/<source>/<track> 一律替换：JW Player 用 class="jw-video" +
            # src="blob:..."，早先靠 VIDEO 模式判断导致 76 页原样留下了播放器标签。
            if m.group(0).lower().lstrip().startswith("<video") or VIDEO.search(tag):
                self.stats["video_removed"] += 1
                return self._placeholder(poster)
            return tag
        h = re.sub(r"(?is)<video\b[^>]*>.*?</video\s*>", drop, h)
        h = re.sub(r"(?i)<(?:source|track)\b[^>]*/?>", drop, h)

        # JW Player 的 <video> 嵌在容器里、src 是 blob: URL，上面的规则匹配不到
        # （实测 71 页漏网）。以播放器容器为锚点再补一遍。
        def drop_container(m):
            self.stats["video_container_removed"] += 1
            return self._placeholder(poster)

        h, ncont = cut_balanced_div(
            h,
            re.compile(r'(?i)<div[^>]*\bclass="[^"]*\bjw-(?:media|preview|wrapper)\b[^"]*"[^>]*>'),
            lambda m: self._placeholder(poster))
        self.stats["video_container_removed"] += ncont
        # 嵌套容器会让同一个播放器产出多个占位（实测课程页出现 3 个，且互不相邻，
        # 所以按"相邻去重"是抓不到的）。整页只留第一个，其余直接删掉。
        one = re.compile(r'<div class="cb-clone-player-placeholder"[^>]*></div>')
        seen = {"n": 0}

        def keep_first(m):
            seen["n"] += 1
            if seen["n"] == 1:
                return m.group(0)
            self.stats["placeholder_deduped"] += 1
            return ""
        h = one.sub(keep_first, h)

        # og:video 元数据指向视频 CDN，一并去掉
        h, n = re.subn(r'(?i)<meta[^>]+property="og:video[^"]*"[^>]*>', "", h)
        self.stats["og_video_meta_removed"] += n
        return h

    # -- 3. 资产 ----------------------------------------------------
    def _placeholder(self, poster: str | None) -> str:
        bg = (f"background:#e9e9e9 url('{poster}') center/cover no-repeat;"
              if poster else "background:#e9e9e9;")
        # 不再贴"Video not reproduced"字样：它在课程页上会随嵌套容器出现多次，
        # 观感像是页面坏了。只留海报占位，标记留在 data-* 属性里供诊断使用。
        return ('<div class="cb-clone-player-placeholder" '
                'data-clone-note="video_content_not_reproduced" '
                f'style="width:100%;aspect-ratio:16/9;{bg}"></div>')

    def rewrite_assets(self, h: str) -> str:
        def repl(m):
            attr, quote, url = m.group(1), m.group(2), m.group(3)
            raw = html.unescape(url.strip())
            if not raw or raw.startswith(("#", "data:", "mailto:", "javascript:")):
                return m.group(0)
            full = "https:" + raw if raw.startswith("//") else raw
            q = up.urlparse(up.urljoin(BASE + "/", full))
            host, path = q.netloc, q.path
            is_local = host in IN_SCOPE and any(path.startswith(p) for p in CFG["asset_prefixes"])
            if not (is_local or host in LOCALIZE):
                return m.group(0)
            if not ASSET_EXT.search(path) and host not in LOCALIZE:
                return m.group(0)
            src_url = up.urlunparse(("https", host or CFG["canonical_host"], path, "", q.query, ""))
            name = asset_key(src_url)
            self.assets.setdefault(src_url, name)
            self.stats["asset_rewritten"] += 1
            return f'{attr}={quote}/static/assets/{name}{quote}'

        # 懒加载属性也要改写：源站用 data-src/data-original 承载真实地址，
        # 只改 src 的话图片引用仍指向源站（离线闭合 + 缺图两头都出问题）。
        # <object data="…"> 也是取资源的属性。漏掉它，/trial/create-account 上那个
        # <object type="image/svg+xml" data="/ui/images/signup/whyjoin_hello.svg">
        # 就停在源站路径上 —— 克隆不提供 /ui/ 前缀，浏览器实测 404。
        # repl() 自带前缀与扩展名校验，非资源的 data="…" 会原样返回，不会误伤。
        h = re.sub(
            r'\b(src|href|data-src|data-original|data-lazy|poster|data)\s*=\s*(["\'])([^"\']+)\2',
            repl, h, flags=re.I)

        # style="background-image:url(/pimage/…)" 这类走的不是属性值路径。
        # 不改的话地址停在 /pimage/…，克隆服务器不提供该前缀 → 区块变白。
        def repl_css_url(m):
            raw = html.unescape(m.group(1).strip().strip('"\''))
            if raw.startswith(("data:", "about:")):
                return m.group(0)
            full = "https:" + raw if raw.startswith("//") else raw
            q = up.urlparse(up.urljoin(BASE + "/", full))
            if q.netloc and q.netloc not in IN_SCOPE:
                return m.group(0)
            if not any(q.path.startswith(pre) for pre in CFG["asset_prefixes"]):
                return m.group(0)
            if not ASSET_EXT.search(q.path):
                return m.group(0)
            src_url = up.urlunparse(("https", CFG["canonical_host"], q.path, "", q.query, ""))
            name = asset_key(src_url)
            self.assets.setdefault(src_url, name)
            self.stats["css_url_localized"] += 1
            return f"url(/static/assets/{name})"

        return re.sub(r'url\(\s*([^)]+?)\s*\)', repl_css_url, h, flags=re.I)

    # -- 4. 站内链接 + 截断收边 -------------------------------------
    def substitute_class(self, target: str, page_route: str = "") -> str | None:
        """给未采集的课程链接找一个真实的替身。

        信号优先级（2026-08-30 修正）：
          1. **卡片所在页面自身的子类** —— 在 /classes/sewing/garment-sewing 上做替换，
             替身就该来自 garment-sewing。这是页面结构直接给出的事实。
          2. 页面自身的大类。
          3. 死链 slug 与子类/大类名的子串匹配（旧算法唯一的信号）。
          4. 全站。

        旧算法只有第 3 条，信号太弱：独立评审实测到缝纫课链接指向能量球食谱这类
        跨大类替换，与 link-retargeting.md 里"同子类优先"的描述不符。

        取值按目标路径 CRC32，保证同一条链接每次构建落到同一门课（构建可复现）。
        """
        pool = getattr(self, "_class_pool", None)
        if pool is None:
            pool = self._class_pool = load_class_pool()
        if not pool["all"]:
            return None

        bucket = None
        # 1/2：页面上下文。/classes/<cat>/<sub> 直接给出子类与大类。
        segs = [x for x in (page_route or "").strip("/").split("/") if x]
        if segs and segs[0] == "classes":
            if len(segs) >= 3:
                bucket = pool["by_sub"].get(segs[2].lower())
            if not bucket and len(segs) >= 2:
                bucket = pool["by_cat"].get(segs[1].lower())
        # 课程详情页：用这门课自己的子类
        if not bucket and page_route:
            own = pool["route_meta"].get(page_route.rstrip("/"))
            if own:
                bucket = pool["by_sub"].get((own[1] or "").lower()) \
                    or pool["by_cat"].get((own[0] or "").lower())
        # 3：退回旧的 slug 子串匹配
        if not bucket:
            slug = target.rstrip("/").rsplit("/", 1)[-1].lower().replace("-", "")
            for key in pool["by_sub"]:
                if key and key.replace("-", "") in slug:
                    bucket = pool["by_sub"][key]; break
            if not bucket:
                for key in pool["by_cat"]:
                    if key and key.replace("-", "") in slug:
                        bucket = pool["by_cat"][key]; break
        bucket = bucket or pool["all"]
        return bucket[zlib.crc32(target.encode()) % len(bucket)]

    def rewrite_links(self, h: str, route: str = "") -> str:
        def repl(m):
            attr, quote, url = m.group(1), m.group(2), m.group(3)
            raw = html.unescape(url.strip())
            if raw.startswith("/static/assets/"):
                return m.group(0)
            full = "https:" + raw if raw.startswith("//") else raw
            q = up.urlparse(up.urljoin(BASE + "/", full))
            if BOUNDARY_PATHS and (q.path or "/").rstrip("/") in BOUNDARY_PATHS:
                self.stats["path_boundary"] += 1               # 源站 403 等，不作内容复刻
                return f'{attr}={quote}{BOUNDARY}{quote}'
            if q.netloc and q.netloc not in IN_SCOPE:      # 任何站外导航目标
                self.stats["external_to_boundary"] += 1
                return f'{attr}={quote}{BOUNDARY}{quote}'
            r = norm_route(raw)
            if r is None:
                return m.group(0)
            # 只在页面**确实不存在**时才替换。
            # 曾经还加了 `r not in self.detail_allow`（N=12 截断名单），但实际
            # 构建出的页面比那份名单多，于是 needlepoint-sampler 这类**磁盘上有页面**
            # 的链接也被换掉了 —— 首页 "Enjoy a Free Taste" 的卡片因此 10/10 全部
            # 指向了无关课程，而它们本来是能正常打开的。
            if r.startswith("/classseries/") and r not in self.routes:
                # 未采集的课程：改投到一门真实存在、且页面内容饱满的课。
                # 送进边界页等于把人带进死胡同 —— 每个课程条目都应该点得进去。
                # 2026-08-30 用户最终裁定：源站目标未采集时，指向一门**真实存在
                # 且页面完整**的课，而不是把用户送进"内容未复刻"的死胡同。
                # 判据是"页面确实不存在才替换"——采到的一律指回原目标，
                # 这是与「跳转逻辑要对」并存的，不是二选一。
                alt = self.substitute_class(r, route)
                if alt:
                    self.stats["class_link_substituted"] += 1
                    # 打标记：运行时据此把卡片上显示的标题/讲师改成落点那门课的，
                    # 否则卡片"说一套跳一套"。构建期不去改嵌套的卡片结构 ——
                    # 用正则改嵌套标记正是弄坏 534 个页面的那条路。
                    return (f'data-cb-substituted="{alt}" '
                            f'{attr}={quote}{alt}{quote}')
                self.stats["truncated_to_boundary"] += 1
                return f'{attr}={quote}{BOUNDARY}{quote}'
            if r not in self.routes:
                self.stats["unknown_route_to_boundary"] += 1
                return f'{attr}={quote}{BOUNDARY}{quote}'
            if " " in r:
                # 源站 href 里带未编码空格。这些路由确实被抓到了，
                # 编码后才能在克隆里解析；丢到边界页等于凭空少一个真实页面。
                self.stats["href_percent_encoded"] += 1
                return f'{attr}={quote}{up.quote(r, safe="/")}{quote}'
            return f'{attr}={quote}{r}{quote}'

        # 两种引号各用各的定界，不能用 ["'] 这种字符类：
        #   - 用字符类会在值内部的另一种引号处截断（源站有 ...'s-stories/ 这种
        #     写法），拼出 /_clone/out-of-scope's-stories/ 这类畸形地址；
        #   - 但只认双引号又会漏掉 onclick="...href='/facebook/signin'" 里的
        #     单引号 href，站外 IdP 链接就此漏出去（test_identity_provider_
        #     buttons_reach_boundary 抓到过）。
        h = re.sub(r'\b(href)\s*=\s*(")([^"]+)\2', repl, h, flags=re.I)
        h = re.sub(r"\b(href)\s*=\s*(')([^']+)\2", repl, h, flags=re.I)
        return h

    def sweep_absolute(self, h: str) -> str:
        """兜底（§7.5）：任何属性、内联 CSS 里残留的源站绝对地址一律转成克隆路由。

        rewrite_assets/rewrite_links 只覆盖 src|href；content=、data-*、srcset、
        poster、style 里的 url() 走这一步。跑在最后，因为它是纯文本级替换。
        """
        for host in IN_SCOPE:
            # 协议相对形式 //host/... 必须一起扫 —— 引擎的 remote-reference 检查
            # 认它，我最初的正则只匹配 https?:// 前缀，把它整类漏掉了。
            for prefix in (f"https://{re.escape(host)}", f"http://{re.escape(host)}",
                           f"//{re.escape(host)}"):
                pat = rf"(?<![\w:/]){prefix}(?=[/\"'\s>)])"
                h, n = re.subn(pat, "", h)
                self.stats["absolute_url_swept"] += n
        for host in OUT_ORIGIN | EXTERNAL:
            pat = rf"https?://{re.escape(host)}[^\s\"'\)>]*"
            h, n = re.subn(pat, BOUNDARY, h)
            self.stats["external_url_swept"] += n
        return h

    def strip_jquery_handlers(self, h: str) -> str:
        """剥掉依赖 jQuery 的内联事件。

        源站有 9716 处 on*="$(...)" 分布在 917 页：侧边栏开关、搜索框展开、
        回车提交等。jQuery 随源站脚本一起被剔除（§4.5），这些 handler 全是死的，
        而且每次触发都往控制台抛 "$ is not defined"。
        剥掉之后由 clone-runtime.js 重新实现常见交互 —— 行为等价，不是源码等价。
        """
        def drop(m):
            self.stats["jquery_handler_removed"] += 1
            return ""
        return re.sub(r'\s+on\w+\s*=\s*"[^"]*\$\([^"]*"', drop, h)

    def wire_forms(self, h: str, route: str = "") -> str:
        """在源站表单上补 data-cb-action 与字段别名。

        AUTH-FLOW 第五步：用抓到的原站页面，在现有 DOM 上补 action 与事件监听，
        而不是换成一张自造的通用登录卡片。源站的 action 是绝对地址或 Rails
        风格路径，这里映射到克隆的 /api/*；member[email] 这类字段名同时归一，
        否则 clone-runtime.js 提交上去的键对不上后端。
        """
        def repl(m):
            tag, action = m.group(0), html.unescape(m.group(1))
            path = up.urlparse(action).path or action
            target = FORM_ACTIONS.get(path)
            if not target:
                return tag
            self.stats["form_wired"] += 1
            tag = re.sub(r'\baction\s*=\s*(["\'])[^"\']*\1', f'action="{target}"', tag, flags=re.I)
            if "data-cb-action" not in tag:
                tag = tag[:-1].rstrip() + f' data-cb-action="{target}">'
            return tag

        h = re.sub(r'<form\b[^>]*\baction\s*=\s*["\']([^"\']+)["\'][^>]*>', repl, h, flags=re.I)

        # 源站有些表单没有 action（靠 JS 提交），上面的正则匹配不到。
        # 按路由给它们指定落点 —— 这是 clone-authored 决定，已记入 known-differences。
        # 按路由把指定 id 的表单改投到别的端点。
        # /trial/create-account 上唯一有输入框的是登录模态框的表单，
        # 而这一页的语义是注册 —— 源站靠 JS 切换，JS 剔除后由构建期决定。
        for fid, endpoint in FORM_RETARGET.get(route.rstrip("/") or "/", {}).items():
            def _retarget(m, _fid=fid, _ep=endpoint):
                tag = m.group(0)
                if f'id="{_fid}"' not in tag:
                    return tag
                self.stats["form_retargeted"] += 1
                tag = re.sub(r'\baction\s*=\s*(["\'])[^"\']*\1', f'action="{_ep}"', tag, flags=re.I)
                tag = re.sub(r'\bdata-cb-action\s*=\s*(["\'])[^"\']*\1',
                             f'data-cb-action="{_ep}"', tag, flags=re.I)
                return tag
            # 这个表单成了本页主内容，它所在的模态框不能在启动时被隐藏
            h = re.sub(r'(<div[^>]*id="cb_login_modal")',
                       r'\1 data-cb-inline="1"', h, count=1)
            h = re.sub(r'<form\b[^>]*>', _retarget, h, flags=re.I)

        target = FORM_ROUTE_DEFAULTS.get(route.rstrip("/") or "/")
        if target:
            def repl_bare(m):
                tag = m.group(0)
                if "action=" in tag.lower() or "data-cb-action" in tag:
                    return tag
                self.stats["form_wired_by_route"] += 1
                return tag[:-1].rstrip() + f' action="{target}" data-cb-action="{target}">'
            h = re.sub(r'<form\b[^>]*>', repl_bare, h, flags=re.I)

        for src, dst in FIELD_ALIASES.items():
            h, n = re.subn(rf'(\bname\s*=\s*["\']){re.escape(src)}(["\'])',
                           rf'\g<1>{dst}\g<2>', h)
            self.stats["field_aliased"] += n
        return h

    # CTA 落点纠正：源站这些按钮指向的促销/订阅地址没被采集，改写时统统落到
    # 边界页，于是"开始免费试用""查看更多"点下去都是死胡同。它们该去的页面
    # 我们其实都有，按钮文案就是意图，据此把落点接回去。
    CTA_TARGETS = (
        (re.compile(r"start free trial|get 30 days free|get offer|try creativebug|"
                    r"join now|start subscription|start your free trial", re.I),
         "/trial/create-account"),
        (re.compile(r"view more|view all|see all|browse (all )?classes|shop all", re.I),
         "/classes"),
    )

    def retarget_ctas(self, h: str) -> str:
        def repl(m):
            head, href, tail, text = m.group(1), m.group(2), m.group(3), m.group(4)
            if href not in (BOUNDARY, "javascript:;", "#"):
                return m.group(0)
            plain = re.sub(r"<[^>]+>", " ", text)
            plain = html.unescape(plain).strip()
            if not plain:
                return m.group(0)
            for pat, dest in self.CTA_TARGETS:
                if pat.search(plain) and dest in self.routes:
                    self.stats["cta_retargeted"] += 1
                    return f'{head}"{dest}"{tail}{text}</a>'
            return m.group(0)

        return re.sub(r'(<a\b[^>]*?\bhref\s*=\s*)"([^"]*)"([^>]*>)(.*?)</a\s*>',
                      repl, h, flags=re.I | re.S)

    def inject_runtime(self, h: str) -> str:
        # off-canvas 抽屉在源站默认是收起的（Bootstrap 的 .offcanvas 未加 .show 时
        # visibility:hidden 并移出视口）。剥掉脚本后这条状态没了，面板直接摊在页面流里：
        # /classes/search 底部就是一列 450px 宽的卡片，左边被截、右边大片空白。
        # 补回默认收起状态，与源站呈现一致。
        # 剥掉源站脚本后丢失的默认状态，在这里补回来。都是"向源站靠拢"，不是偏离。
        css = ('<style id="cb-clone-offcanvas-default">'
               # Bootstrap 语义：未打开的 offcanvas 是收起的
               '.offcanvas:not(.show){display:none!important}'
               # 灵感墙：源站里 "ADD YOUR IMAGE" 独占一行，图片网格从下一行开始
               # （见参照帧 gallery-community）。抓取件的结构是
               #   .image-gallery.row > [col-md-3 添加块] + [无 class 的图片容器]
               # 添加块是浮动的 col，图片容器是普通 block，脚本剥离后就贴到了它右边。
               # 源站靠脚本布局，这里用一条 clear 还原它的换行。
               '.image-gallery.row>div:not([class*="col"]){clear:both}'
               '</style>')
        tag = css + '<script src="/static/clone-runtime.js" defer></script>'
        if re.search(r"(?i)</body\s*>", h):
            return re.sub(r"(?i)</body\s*>", tag + "</body>", h, count=1)
        return h + tag

    def build(self, h: str, route: str = "") -> str:
        h = self.strip_scripts(h)
        # 先把要自供的第三方样式换成本地地址，再做外链中和，否则会被一并中和
        h, nv = vendor_external_css(h)
        amap = getattr(self, '_amap', None)
        if amap is None:
            amap = self._amap = _asset_path_map()
        h, ni = localize_inline_css(h, amap)
        self.stats['inline_css_localized'] += ni
        self.stats["vendored_css"] += nv
        h = self.neutralize_external(h)
        h = self.strip_third_party(h)
        # 资产改写要排在视频占位之前：占位背景取的是页内已改写到
        # /static/assets/ 的本地图，顺序反了就永远取不到。
        h = self.rewrite_assets(h)
        h = self.strip_video(h)
        h = self.rewrite_links(h, route)
        h = self.sweep_absolute(h)
        h = self.strip_jquery_handlers(h)
        h = self.retarget_ctas(h)
        h = self.wire_forms(h, route)
        h = self.inject_runtime(h)
        # scrub 收在管线最后一步，而不是只放在 finalize.sh 里。
        # 直接跑 build_pages.py 就会绕过 finalize 的 scrub —— 上一次正是
        # 这样把采集时的真实账号邮箱与内部 id 带进了 302 个出货页。
        return scrub_text(h, SCRUB_LITERALS)[0]



def load_class_pool() -> dict:
    """从业务库取课程，只保留 frontend 下确实有页面的那些。

    "有内容的排前面"：按单元数与是否有讲师排序，取靠前的做替身池，
    这样点进去的是一门信息饱满的课，而不是空壳。
    """
    pool = {"all": [], "by_cat": {}, "by_sub": {}, "route_meta": {}}
    db = ROOT / "materials" / "creativebug" / "data" / "creativebug.sqlite3"
    if not db.is_file():
        return pool
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT route, category, subcategory, unit_count, instructor, title "
            "FROM cb_class ORDER BY (instructor IS NOT NULL) DESC, "
            "unit_count DESC, title ASC").fetchall()
    except Exception:
        return pool
    finally:
        con.close()
    for r in rows:
        route = (r["route"] or "").rstrip("/")
        if not route:
            continue
        if not (OUT / route.strip("/") / "index.html").is_file():
            continue          # 页面没被采集到，不能拿来当替身
        pool["all"].append(route)
        pool["route_meta"][route] = (r["category"], r["subcategory"])
        for key, dest in ((r["category"], "by_cat"), (r["subcategory"], "by_sub")):
            if key:
                pool[dest].setdefault(str(key).lower(), []).append(route)
    return pool


def emit_recovery_pages(builder: "Builder") -> int:
    """生成边界页与 404 页。

    必须由构建器产出，不能手工放在 frontend/ 里 —— 每次构建前都会
    `rm -rf frontend`，手工页会被反复删掉，而全站有三万多条链接指向边界页。
    外壳取自真实抓取件并过同一条构建管线，保证与站点其余部分同构且离线闭合。
    """
    # 边界页/404 页直接取源站自己的品牌化 404 抓取件当模板。
    #
    # 早先是手工拼一个极简恢复页（.cb-clone-recovery），结果两条视觉检查点
    # 长期停在 0.80 上下 —— 不是"克隆自制页天然不可比"，而是根本没用源站的那一版。
    # 实测：直接拿抓取件渲染，对参照帧相似度 0.9743；手工拼的只有 0.83。
    # 手工拼还漏了 <html class="v2">，443 条 .v2 作用域的 CSS 全部不生效，页头是散的。
    #
    # 源站对未知路由回 200 + 品牌化 404 主体；克隆回真 404 + 同一个主体
    # （known-differences::source_soft_404_returns_200 本来就是这么写的）。
    err_src = None
    for cand in SRC.rglob("index.html"):
        t = cand.read_text(encoding="utf-8", errors="replace")
        if 'class="site-error-page"' in t:
            err_src = t
            break
    if err_src is None:
        print("[build_pages] 抓取件里找不到源站 404 主体，跳过边界页构建")
        return 0

    def page(title, h2, reasons, marker):
        """在源站 404 抓取件上只替换 h2 与 reasons，其余原样保留。

        页头/促销条/页脚/CSS 一概不动 —— 那些正是相似度的来源。
        两页仍可区分：data-cb-page 标记不同，文案不同。
        """
        s = err_src
        s = re.sub(r"(?is)<html\b[^>]*>",
                   f'<html class="v2" lang="en" data-cb-page="{marker}">', s, count=1)
        s = re.sub(r"(?is)<title>.*?</title>", f"<title>{title}</title>", s, count=1)
        s = re.sub(r"(?is)(<div class=\"title clearfix\">\s*<h1>404</h1>\s*<h2>).*?(</h2>)",
                   lambda m: m.group(1) + h2 + m.group(2), s, count=1)
        items = "".join(f"<li>{r}</li>" for r in reasons)
        s = re.sub(r"(?is)(<div class=\"reasons\">\s*<p>Possible reasons you are seeing this page:"
                   r"</p>\s*<ul>).*?(</ul>)",
                   lambda m: m.group(1) + items + m.group(2), s, count=1)
        # 页头那个绝对定位的装饰箭头会在这两页上撑出 13px 横向滚动，收掉；
        # 源站派生页不动（那里它不越界）。
        s = s.replace("</head>",
                      '<style>html[data-cb-page="boundary"] .nav-expand-arrow::after,'
                      'html[data-cb-page="not-found"] .nav-expand-arrow::after'
                      "{display:none}</style></head>", 1)
        return s

    pages = {
        BOUNDARY: page("Outside this offline clone - Creativebug",
                       "You\u2019re looking for something this offline clone doesn\u2019t include!",
                       ["This benchmark clone reproduces a bounded slice of the source site.",
                        "The page you followed exists on the live site but was not reproduced here.",
                        "Primary navigation still works."],
                       "boundary"),
        "/_clone/not-found": page("Page not found - Creativebug",
                                  # 源站原文，逐字照抄，让 not-found 检查点可比
                                  "You\u2019re looking for something that doesn\u2019t exist!",
                                  ["The content your searching for has been removed by the administrative wizards.",
                                   "This content you\u2019re after was never created.",
                                   "Aliens."],
                                  "not-found"),
    }
    n = 0
    for route, html_text in pages.items():
        dest = OUT / route.strip("/")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "index.html").write_text(builder.build(html_text, route), encoding="utf-8")
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只构建前 N 页（G2 切片用）")
    a = ap.parse_args()

    if not SRC.is_dir():
        print(f"没有抓取件：{SRC}")
        return 2
    # 路由权威来自抓取日志，不从目录名反推 ——
    # _safe() 会把 & 等字符消毒成 _，反推会得到错误路由（/arts-&-crafts-instructors）
    state = SRC.parent / "_state.jsonl"
    dirmap: dict[str, Path] = {}
    if state.is_file():
        for line in state.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if not rec.get("ok"):
                continue
            d = SRC / rec["dir"] if rec.get("dir") else SRC / (rec["path"].strip("/") or "index")
            if (d / "index.html").is_file():
                dirmap[rec["path"].rstrip("/") or "/"] = d
    # 老记录没有 dir 字段。正确做法不是从目录名反推（消毒与哈希都不可逆），
    # 而是对记录的 path 施加抓取时用的同一个正向变换 _safe()。
    import hashlib as _h
    def safe_dir(path: str) -> Path:
        rel = path.strip("/") or "index"
        rel = re.sub(r"[^A-Za-z0-9._/\-]", "_", rel)
        parts = [seg[:60] for seg in rel.split("/") if seg]
        if sum(len(x) for x in parts) > 150:
            parts = [parts[0][:40], _h.sha1(rel.encode()).hexdigest()[:16]]
        return SRC / Path(*parts)

    if state.is_file():
        for line in state.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if not rec.get("ok"):
                continue
            r = rec["path"].rstrip("/") or "/"
            if r in dirmap:
                continue
            d = safe_dir(rec["path"])
            if (d / "index.html").is_file():
                dirmap[r] = d

    # 首页从未进过抓取清单 —— 它的 DOM 一直在 recon/home.html。
    # 那是真实抓取件，直接用它作为 "/" 的来源。
    home = SRC.parent / "recon" / "home.html"
    if "/" not in dirmap and home.is_file():
        dirmap["/"] = home.parent
        dirmap["__home_file__"] = home
    home_file = dirmap.pop("__home_file__", None)
    files = [(r, (home_file if r == "/" and home_file else d / "index.html"))
             for r, d in sorted(dirmap.items())]
    # 登录态首页：源站给登录用户的是另一个版本（EXPLORE / MY CLASSES / INSPIRATION
    # 三个标签，没有 Log In）。它一直在 recon/after-login.html 里，此前从没被构建，
    # 于是登录之后仍然看到匿名营销首页 —— 用户验收时报的"登录后页面不一样"。
    home_auth = SRC.parent / "recon" / "after-login.html"
    if home_auth.is_file():
        files.append((AUTH_HOME, home_auth))
    routes = set(dirmap) | {"/", BOUNDARY, "/_clone/not-found", AUTH_HOME}
    uf = HERE / "_union.json"
    allow = set(json.loads(uf.read_text(encoding="utf-8"))["truncated_n12"]) if uf.is_file() else set()

    b = Builder(routes, allow)
    if a.limit:
        files = files[: a.limit]
    for route, f in files:
        dest = OUT / (route.strip("/") or "index")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "index.html").write_text(
            b.build(f.read_text(encoding="utf-8", errors="replace"), route), encoding="utf-8")
        b.stats["pages_built"] += 1

    b.stats["recovery_pages"] = emit_recovery_pages(b)

    (HERE / "_assets.json").write_text(
        json.dumps({"assets": b.assets}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(dict(b.stats), ensure_ascii=False, indent=1))
    print(f"\n待下载资产 {len(b.assets)} 个 → tools/_assets.json")
    print(f"页面写入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
