"""离线闭合 —— 对应 invariants.json 的 offline-closure。

判据按"位置"而非域名清单：会发请求的位置一处都不许指向站外；
命名空间与注释署名（xmlns/itemtype/prefix/许可证链接）从不 fetch，允许保留。

**必须先 html.unescape 再匹配。** 属性值里的引号写作 &quot;，源站的
`style="background-image: url(&quot;https://cdn-widget-assets.yotpo.com/…&quot;)"`
因此逃过了裸引号正则：22 处引用留在出货件里，浏览器实测发出 11 次外发请求，
而这三道离线守护全绿。转义是这类漏检的通用入口，不是个案。
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

CLONE = Path(__file__).resolve().parent.parent
FRONTEND = CLONE / "frontend"
IN_SCOPE = ("www.creativebug.com", "creativebug.com")
SEMANTIC_OK = {"schema.org", "ogp.me", "www.w3.org", "craftpip.github.io", "github.com"}

FETCH = re.compile(
    r'\b(?:src|srcset|poster|data-src|formaction)\s*=\s*["\']((?:https?:)?//[^"\']+)'
    r'|<link\b[^>]*href\s*=\s*["\']((?:https?:)?//[^"\']+)'
    r'|url\(\s*["\']?((?:https?:)?//[^)"\']+)', re.I)


def test_no_source_scripts_survive():
    bad = []
    for p in FRONTEND.rglob("index.html"):
        h = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r'<script\b(?![^>]*clone-runtime)', h, re.I):
            bad.append(str(p.relative_to(FRONTEND)))
    assert not bad, f"{len(bad)} 页残留源站脚本，前 3: {bad[:3]}"


def test_no_iframes():
    bad = [str(p.relative_to(FRONTEND)) for p in FRONTEND.rglob("index.html")
           if re.search(r'<iframe\b', p.read_text(encoding="utf-8", errors="replace"), re.I)]
    assert not bad, f"{len(bad)} 页仍有 iframe"


def test_every_checkpoint_route_makes_zero_outbound_requests():
    bad = {}
    for p in FRONTEND.rglob("index.html"):
        h = html.unescape(p.read_text(encoding="utf-8", errors="replace"))
        for m in FETCH.finditer(h):
            u = next(g for g in m.groups() if g)
            host = re.sub(r'^(https?:)?//', '', u).split('/')[0]
            if host not in IN_SCOPE and host not in SEMANTIC_OK:
                bad.setdefault(host, 0)
                bad[host] += 1
    assert not bad, f"会发请求的外域引用: {bad}"


def test_no_third_party_host_in_built_pages():
    # 契约随交付目录走。早先从工作区的 tools/site-config.json 读，
    # cp -r 到新路径后那个文件不在交付物里，测试直接 FileNotFoundError ——
    # 交付物的测试不该依赖交付物之外的文件。
    cfg = json.loads((CLONE.parent / "scope" / "build-contract.json")
                     .read_text(encoding="utf-8"))
    third = set(cfg["third_party_hosts"])
    hits = {}
    for p in FRONTEND.rglob("index.html"):
        h = html.unescape(p.read_text(encoding="utf-8", errors="replace"))
        for m in FETCH.finditer(h):
            u = next(g for g in m.groups() if g)
            host = re.sub(r'^(https?:)?//', '', u).split('/')[0]
            if host in third:
                hits[host] = hits.get(host, 0) + 1
    assert not hits, f"第三方追踪域残留: {hits}"


def test_no_absolute_source_urls_in_clone():
    """协议相对形式一并检查 —— 引擎的 remote-reference 认它，最初漏过一次。"""
    pat = re.compile(
        r'(?:src|href|action|poster|data-src|srcset)\s*=\s*["\']\s*(?:https?:)?//(?:www\.)?creativebug\.com',
        re.I)
    bad = [str(p.relative_to(FRONTEND)) for p in FRONTEND.rglob("index.html")
           if pat.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert not bad, f"{len(bad)} 页仍有指向源站的资源引用，前 3: {bad[:3]}"


def test_recovery_pages_exist_and_differ():
    """边界页与 404 页必须由构建产出并且是两个不同的页面。

    早先它们是手工放进 frontend/ 的，而每次构建都 rm -rf frontend，
    于是三万多条截断链接指向了一个不存在的页面，且静默回落成 404。
    """
    b = FRONTEND / "_clone" / "out-of-scope" / "index.html"
    n = FRONTEND / "_clone" / "not-found" / "index.html"
    assert b.is_file(), "边界页缺失 —— 截断链接会静默回落成 404"
    assert n.is_file(), "404 页缺失"
    hb = b.read_text(encoding="utf-8", errors="replace")
    hn = n.read_text(encoding="utf-8", errors="replace")
    assert 'data-cb-page="boundary"' in hb
    assert 'data-cb-page="not-found"' in hn
    assert hb != hn, "边界页与 404 页内容相同，两种语义分不开"
