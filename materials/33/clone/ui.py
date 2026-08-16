"""Shared, source-grounded desktop presentation for the local Coursera clone."""

from __future__ import annotations

from html import escape


def header(*, authenticated: bool) -> str:
    """Render the two-tier desktop navigation without any remote dependency."""

    account_controls = (
        '<nav class="wb-account-nav" aria-label="学习者账户">'
        '<a href="/my-learning">我的学习</a>'
        '<form action="/auth/logout" method="post">'
        '<button type="submit">退出登录</button></form></nav>'
        if authenticated
        else '<nav class="wb-account-nav" aria-label="账户">'
        '<a href="/login">登录</a><a class="wb-join" href="/signup">免费加入</a>'
        "</nav>"
    )
    return f"""
<div class="wb-audience-bar">
  <div class="wb-shell"><strong>为个人</strong><a href="/about/contact">为商务</a><a href="/browse">为大学</a><a href="/about/contact">为政府</a></div>
</div>
<header class="wb-header">
  <div class="wb-shell wb-header-row">
    <a class="wb-wordmark" href="/" aria-label="Coursera 首页">coursera</a>
    <a class="wb-explore" href="/browse">探索 <span aria-hidden="true">⌄</span></a>
    <a class="wb-degree-link" href="/browse">学位</a>
    <form class="wb-search" action="/search" method="get" role="search">
      <label class="wb-sr-only" for="wb-header-search">搜索课程</label>
      <input id="wb-header-search" name="q" placeholder="您想学习什么？" autocomplete="off">
      <button type="submit" aria-label="搜索"><span aria-hidden="true">⌕</span></button>
    </form>
    {account_controls}
  </div>
</header>
"""


def footer() -> str:
    """Render the local footer and keep every destination inside this clone."""

    return """
<footer class="wb-footer">
  <div class="wb-shell wb-footer-grid">
    <section><h2>Coursera</h2><a href="/browse">课程目录</a><a href="/about/contact">关于我们</a><a href="/help">帮助中心</a></section>
    <section><h2>社区</h2><a href="/my-learning">学习者</a><a href="/browse">合作伙伴</a><a href="/about/contact">企业</a></section>
    <section><h2>更多</h2><a href="/account-recovery">账户访问</a><a href="/help">支持</a><a href="/about/contact">联系我们</a></section>
    <section><h2>移动端学习</h2><p>随时随地继续本地学习旅程。</p></section>
  </div>
  <div class="wb-shell wb-footer-legal">© 2026 Coursera Inc. 保留所有权利。<span>本地 WebsiteBench 离线 clone</span></div>
</footer>
"""


def page(
    *,
    title: str,
    body: str,
    authenticated: bool,
    body_class: str = "",
    document_title: str | None = None,
) -> str:
    """Return one complete local HTML document for a desktop clone route."""

    rendered_title = document_title or f"{title} | Coursera"
    classes = " ".join(part for part in ("wb-page", body_class) if part)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(rendered_title)}</title><link rel="stylesheet" href="/static/site.css"><link rel="stylesheet" href="/static/components.css"><link rel="stylesheet" href="/static/auth.css"><link rel="stylesheet" href="/static/checkout.css"><link rel="stylesheet" href="/static/desktop-base.css"><link rel="stylesheet" href="/static/desktop-chrome.css"><link rel="stylesheet" href="/static/catalog-desktop.css"><link rel="stylesheet" href="/static/course-desktop.css"></head>
<body class="{escape(classes)}">{header(authenticated=authenticated)}<main>{body}</main>{footer()}</body></html>"""
