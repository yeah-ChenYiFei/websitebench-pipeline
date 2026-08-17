"""Coursera-inspired WebsiteBench offline clone."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import checkout, learning_db
from catalog import load_catalog_seed
from websitebench.local_clone_auth import AuthError
from websitebench.site_backend import PaymentConflict, PaymentError, PaymentRejected
from ui import footer as desktop_footer
from ui import header as desktop_header
from ui import page as desktop_page


SITE_ID = "33"
DISPLAY_NAME = "Coursera"
STATIC_DIR = Path(__file__).resolve().parent / "static"
VERIFY_SESSION_TOKEN_ENV = "WEBSITEBENCH_VERIFY_SESSION_TOKEN"
VERIFY_SESSION_TOKEN_HEADER = "X-WebsiteBench-Verify-Token"

SUBJECTS = {
    "arts-and-humanities": "Arts and Humanities",
    "business": "Business",
    "computer-science": "Computer Science",
    "data-science": "Data Science",
    "health": "Health",
    "information-technology": "Information Technology",
    "language-learning": "Language Learning",
    "math-and-logic": "Math and Logic",
    "personal-development": "Personal Development",
    "physical-science-and-engineering": "Physical Science and Engineering",
    "social-sciences": "Social Sciences",
}
SUBJECT_SLUGS = {subject: slug for slug, subject in SUBJECTS.items()}

SUBJECTS_ZH = {
    "Arts and Humanities": "艺术与人文",
    "Business": "商业",
    "Computer Science": "计算机科学",
    "Data Science": "数据科学",
    "Health": "健康",
    "Information Technology": "信息技术",
    "Language Learning": "语言学习",
    "Math and Logic": "数学与逻辑",
    "Personal Development": "个人发展",
    "Physical Science and Engineering": "物理科学与工程",
    "Social Sciences": "社会科学",
}

SUBJECT_ICONS = {
    "arts-and-humanities": "✎",
    "business": "▣",
    "computer-science": "‹›",
    "data-science": "↗",
    "health": "✚",
    "information-technology": "▰",
    "language-learning": "◎",
    "math-and-logic": "▦",
    "personal-development": "◇",
    "physical-science-and-engineering": "△",
    "social-sciences": "♧",
}

app = FastAPI(title=DISPLAY_NAME)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "font-src 'self'; script-src 'none'; connect-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def _header(*, authenticated: bool = False) -> str:
    return desktop_header(authenticated=authenticated)


def _footer() -> str:
    return desktop_footer()


def _request_authenticated(request: Request) -> bool:
    """Resolve only this request's existing site-bound session."""

    backend, auth = learning_db.services()
    cookie = backend.session_cookie
    session = auth.resolve_session(request.cookies.get(cookie["name"]))
    return bool(session and session["authenticated"])


def _page(
    request: Request,
    title: str,
    body: str,
    *,
    body_class: str = "",
    document_title: str | None = None,
    search_value: str = "",
    checkout_chrome: bool = False,
) -> str:
    return desktop_page(
        title=title,
        body=body,
        authenticated=_request_authenticated(request),
        body_class=body_class,
        document_title=document_title,
        search_value=search_value,
        checkout_chrome=checkout_chrome,
    )


async def _form_values(request: Request) -> dict[str, str]:
    parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _request_session(request: Request):
    backend, auth = learning_db.services()
    cookie = backend.session_cookie
    token, session = auth.ensure_session(request.cookies.get(cookie["name"]))
    return backend, auth, token, session


def _set_session_cookie(response: Response, backend, token: str) -> None:
    cookie = dict(backend.session_cookie)
    name = cookie.pop("name")
    response.set_cookie(name, token, **cookie)


def _session_html(request: Request, title: str, body: str) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    response = HTMLResponse(_page(request, title, body))
    _set_session_cookie(response, backend, token)
    return response


def _auth_failure(request: Request, message: str, *, status_code: int) -> HTMLResponse:
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local account</p><h1>We couldn't continue</h1><p class="safe-note">{escape(message)}</p><a href="/login">Return to sign in</a></div></section>"""
    return HTMLResponse(_page(request, "Account action", body), status_code=status_code)


def _synthetic_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not normalized.endswith(".test"):
        raise ValueError("Use a synthetic .test address in this offline clone.")
    return normalized


def _safe_next_path(value: str | None) -> str:
    """Return one strictly local continuation or the learner dashboard."""

    fallback = "/my-learning"
    candidate = (value or "").strip()
    if not candidate or re.search(r"%(?![0-9A-Fa-f]{2})", candidate):
        return fallback
    try:
        parsed = urlsplit(candidate)
        decoded_path = unquote(parsed.path)
    except ValueError:
        return fallback
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(
            ord(character) < 32 or ord(character) == 127 for character in decoded_path
        )
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        return fallback
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))


def _authenticated_subject(request: Request):
    backend, auth, token, session = _request_session(request)
    if not session["authenticated"]:
        raise HTTPException(
            status_code=401, detail="Sign in with a local account to continue"
        )
    return backend, auth, token, str(session["account"]["subject_id"])


def _permission_page(request: Request, message: str) -> HTMLResponse:
    body = f"""<section class="not-found permission-prompt"><p class="eyebrow">Local account required</p><h1>{escape(message)}</h1><p>Sign in with a site-33 .test account. No source account is contacted.</p><a class="primary-button" href="/login">Sign in locally</a></section>"""
    return HTMLResponse(_page(request, "Sign in required", body), status_code=401)


def _enrollment_required_page(request: Request, message: str) -> HTMLResponse:
    body = f"""<section class="not-found permission-prompt"><p class="eyebrow">Active enrollment required</p><h1>{escape(message)}</h1><p>Select a local free or audit track, or complete the inferred sandbox checkout for paid access.</p><a class="primary-button" href="/specializations/deep-learning">Choose a local enrollment</a></section>"""
    return HTMLResponse(_page(request, "Enrollment required", body), status_code=403)


def _checkout_not_found(request: Request) -> HTMLResponse:
    body = """<section class="not-found"><h1>Checkout not found</h1><p>The checkout record is unavailable for this local learner.</p><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Checkout not found", body), status_code=404)


@app.post("/__websitebench/session", include_in_schema=False)
async def websitebench_session(request: Request) -> Response:
    """Open a verifier-owned fixture session using only its ephemeral token."""

    expected = os.environ.get(VERIFY_SESSION_TOKEN_ENV, "")
    if not expected:
        return Response(status_code=404)
    supplied = request.headers.get(VERIFY_SESSION_TOKEN_HEADER, "")
    if not hmac.compare_digest(supplied, expected):
        return Response(status_code=403)
    values = await _form_values(request)
    aliases = {
        "empty-learner": "learner-empty",
        "progress-learner": "learner-in-progress",
    }
    subject_id = aliases.get(values.get("account", ""))
    if set(values) != {"account"} or subject_id is None:
        return Response(status_code=400)
    account = next(
        record
        for record in learning_db.SEED_ACCOUNTS
        if record["subject_id"] == subject_id
    )
    backend, auth, token, _session = _request_session(request)
    signed_in = auth.sign_in(
        token,
        email=str(account["email"]),
        password=str(account["password"]),
    )
    response = Response(status_code=204)
    _set_session_cookie(response, backend, str(signed_in["session_token"]))
    return response


def _order_not_found(request: Request) -> HTMLResponse:
    body = """<section class="not-found"><h1>Order not found</h1><p>The order record is unavailable for this local learner.</p><a href="/orders">Back to order history</a></section>"""
    return HTMLResponse(_page(request, "Order not found", body), status_code=404)


def _checkout_validation(
    request: Request, message: str, *, status_code: int = 422
) -> HTMLResponse:
    body = f"""<section class="not-found"><p class="eyebrow">Safe local checkout</p><h1>Checkout could not continue</h1><p>{escape(message)}</p><a href="/specializations/deep-learning">Back to Deep Learning</a></section>"""
    return HTMLResponse(_page(request, "Checkout validation", body), status_code=status_code)


def _checkout_totals() -> str:
    return """<dl class="checkout-totals"><div><dt>之后为 ¥196/月</dt><dd>¥196/月</dd></div><div><dt>今天应付</dt><dd>¥0</dd></div><div class="checkout-total"><dt>今日合计：¥0</dt><dd>¥0</dd></div></dl>"""


def _order_rows(records: list[dict[str, Any]]) -> str:
    if not records:
        return """<div class="empty-state"><h2>No local orders yet</h2><p>Approved sandbox checkouts will appear here.</p><a href="/specializations/deep-learning">Back to Deep Learning</a></div>"""
    return "".join(
        f"""<article class="catalog-card order-card" data-order-status="{escape(str(record["status"]))}"><p class="eyebrow">{"已付款" if record["status"] == "PAID" else "已取消"}</p><h2>深度学习专项课程</h2><p>订单 {escape(str(record["order_id"]))}</p><p>今天应付：¥0</p><a href="/orders/{escape(str(record["order_id"]))}">查看订单详情</a></article>"""
        for record in records
    )


async def _exact_checkout_attempt_values(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type != "application/x-www-form-urlencoded":
        raise ValueError("Submit exactly scenario_id and idempotency_key.")
    try:
        pairs = parse_qsl(
            (await request.body()).decode("utf-8"), keep_blank_values=True
        )
    except UnicodeDecodeError as exc:
        raise ValueError("Submit exactly scenario_id and idempotency_key.") from exc
    if len(pairs) != 2 or {key for key, _value in pairs} != {
        "scenario_id",
        "idempotency_key",
    }:
        raise ValueError("Submit exactly scenario_id and idempotency_key.")
    return dict(pairs)


def _learning_not_found(request: Request) -> HTMLResponse:
    body = """<section class="not-found"><p class="error-code">404</p><h1>Learning item not found</h1><p>The item is unavailable for this local learner.</p><a class="primary-button" href="/my-learning">Return to My Learning</a></section>"""
    return HTMLResponse(_page(request, "Learning item not found", body), status_code=404)


def _enrollment_rows(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<div class="empty-state"><h2>还没有本地报名记录</h2><a href="/specializations/deep-learning">浏览深度学习专项课程</a></div>'
    rows = []
    for record in records:
        course_id = str(record["course_id"])
        catalog_record = _record_by_id(course_id)
        course_title = (
            str(catalog_record["title"])
            if catalog_record is not None
            else "Unavailable course"
        )
        course_href = (
            "/learn/neural-networks-deep-learning/lesson/lesson-neural-intro"
            if course_id == learning_db.COURSE_ID
            else f"/learn/{escape(course_id)}"
        )
        paid = record["track"] == "paid"
        if paid and record.get("order_id"):
            cancellation = f'<a href="/orders/{escape(str(record["order_id"]))}">管理本地付费订单</a>'
            origin = "由模拟成功的 local-sandbox 结账创建。"
        else:
            cancellation = (
                f'<form action="/enrollments/{record["enrollment_id"]}/cancel" method="post"><button type="submit">取消报名</button></form>'
                if record["status"] == "active"
                else ""
            )
            origin = "未创建结账或付款记录。"
        status_label = "进行中" if record["status"] == "active" else "已取消"
        track_label = {"free": "免费学习", "audit": "旁听", "paid": "付费"}.get(
            str(record["track"]), str(record["track"])
        )
        reactivated_note = (
            "<p>此前已取消；本地报名现已重新启用。</p>"
            if record["status"] == "active" and record["canceled_at"]
            else ""
        )
        rows.append(
            f"""<article class="catalog-card enrollment-card" data-enrollment-id="{record["enrollment_id"]}"><p class="eyebrow">{status_label}</p><h2>{escape(course_title)}</h2><p>{escape(track_label)}轨道</p>{reactivated_note}<p>{origin}</p>{cancellation}<a href="{course_href}">打开课程</a></article>"""
        )
    return "".join(rows)


@app.exception_handler(404)
async def branded_not_found(request: Request, _exception: Exception) -> HTMLResponse:
    body = """<section class="not-found"><p class="error-code">404</p><h1>我们无法找到您要查找的页面</h1><p>页面可能已移动，但您仍可继续浏览课程或重新搜索。</p><div><a class="wb-primary" href="/browse">浏览课程目录</a><a class="secondary-button" href="/search">搜索课程目录</a><a class="secondary-button" href="/">返回首页</a></div></section>"""
    return HTMLResponse(_page(request, "Page not found", body), status_code=404)


def _record_href(record: dict[str, Any]) -> str:
    if record["type"] == "specialization":
        return "/specializations/deep-learning"
    return f"/learn/{record['id']}"


_EVIDENCE_NOTES = {
    "structural-only": (
        "Only the public course structure was observed; displayed details are "
        "a deterministic offline simulation."
    ),
    "inferred-architecture": (
        "Course architecture was inferred; displayed details are a deterministic "
        "offline simulation."
    ),
    "truthful-simulation": (
        "Displayed catalog details are a deterministic offline simulation, "
        "not verified source facts."
    ),
}

_SERIES_EVIDENCE_NOTES = {
    "structural-only": "Source-observed course structure; displayed details are simulated.",
    "inferred-architecture": "Inferred course structure; displayed details are simulated.",
    "truthful-simulation": "Course and displayed details are an offline simulation.",
}

_CARD_EVIDENCE_NOTES = {
    "structural-only": "Evidence: public structure observed; details simulated.",
    "inferred-architecture": "Evidence: architecture inferred; details simulated.",
    "truthful-simulation": "Evidence: offline simulation; not source-verified.",
}


def _evidence_note(record: dict[str, Any], *, compact: bool = False) -> str:
    classification = record["source_evidence_classification"]
    if classification == "directly-observed":
        return ""
    if compact:
        message = _SERIES_EVIDENCE_NOTES[classification]
    else:
        message = _EVIDENCE_NOTES[classification]
    return (
        f'<p class="evidence-note" data-evidence-classification="{escape(classification)}">'
        f"{escape(message)}</p>"
    )


def _card_evidence_note(record: dict[str, Any]) -> str:
    classification = record["source_evidence_classification"]
    if classification == "directly-observed":
        return ""
    return (
        f'<p class="evidence-note" data-evidence-classification="{escape(classification)}">'
        f"{escape(_CARD_EVIDENCE_NOTES[classification])}</p>"
    )


def _card(record: dict[str, Any]) -> str:
    return f"""
<article class="catalog-card" data-catalog-record="{escape(record["id"])}">
  <div class="card-art" aria-hidden="true"><span>{escape(record["subject"][0])}</span></div>
  <p class="provider">{escape(record["provider"])}</p>
  <h2><a href="{escape(_record_href(record))}">{escape(record["title"])}</a></h2>
  <p class="rating">★ {record["rating"]:.1f} · 评分与评论</p>
  <p>{escape(record["level"])} · {escape(record["type"].title())} · {escape(record["duration"])}</p>
  {_card_evidence_note(record)}
</article>"""


def _trend_card(record: dict[str, Any]) -> str:
    type_label = "专项课程" if record["type"] == "specialization" else "课程"
    href = str(record.get("href") or _record_href(record))
    thumb_asset = record.get("thumb_asset")
    thumb = (
        f'<img src="{escape(str(thumb_asset))}" alt="" loading="lazy">'
        if thumb_asset
        else escape(record["provider"][0])
    )
    return f"""
<a class="trend-mini-card" href="{escape(href)}" data-catalog-record="{escape(record["id"])}">
  <span class="trend-thumb" aria-hidden="true">{thumb}</span>
  <span class="trend-copy"><span class="trend-provider">{escape(record["provider"])}</span><strong>{escape(record["title"])}</strong><small>{escape(type_label)} · ★ {record["rating"]:.1f}</small></span>
</a>"""


def _trend_column(title: str, records: list[dict[str, Any]]) -> str:
    return (
        f'<section class="trend-column"><h3>{escape(title)} <span aria-hidden="true">→</span></h3>'
        + "".join(_trend_card(record) for record in records)
        + "</section>"
    )


def _home_lower_sections() -> str:
    logos = (
        "Google",
        "IBM",
        "Microsoft",
        "University of Illinois",
        "OpenAI",
        "DeepLearning.AI",
        "Stanford University",
        "University of Michigan",
        "University of Pennsylvania",
    )
    categories = (
        ("商务", "/browse/business"),
        ("人工智能", "/search?q=Generative+AI"),
        ("数据科学", "/browse/data-science"),
        ("计算机科学", "/browse/computer-science"),
        ("个人发展", "/browse/personal-development"),
        ("医疗保健", "/browse/health"),
        ("语言学习", "/browse/language-learning"),
        ("社会科学", "/browse/social-sciences"),
        ("艺术与人文", "/browse/arts-and-humanities"),
        ("物理科学与工程", "/browse/physical-science-and-engineering"),
        ("数学和逻辑", "/browse/math-and-logic"),
    )
    releases = (
        ("Google 人工智能要点", "/search?q=Google+%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD%E8%A6%81%E7%82%B9", "Google"),
        ("Google 项目管理", "/search?q=Google+Project+Management", "Google"),
        ("Google 网络安全", "/search?q=Google+Cybersecurity", "Google"),
        ("Python", "/search?q=Python", "课程"),
        ("IBM 数据分析师", "/search?q=IBM+Data+Analyst", "IBM"),
        ("项目管理基础", "/search?q=Project+Management", "课程"),
    )
    career_tiles = (
        ("数据科学家", "/search?q=data+scientist"),
        ("机器学习工程师", "/search?q=machine+learning+engineer"),
        ("内容创作者", "/search?q=content+creator"),
        ("数据分析师", "/search?q=data+analyst"),
        ("商业智能分析师", "/search?q=business+intelligence+analyst"),
    )
    faqs = (
        "Coursera 是否经过认证，Coursera 证书是否得到雇主的认可？",
        "Coursera 证书值得吗？",
        "什么是 Coursera Plus，值得吗？",
        "Coursera 是否提供免费在线课程？",
        "Coursera 上最受欢迎的课程有哪些？",
        "Coursera 如何帮助我找到工作或提升职业生涯？",
    )
    logo_markup = "".join(
        f'<span class="source-logo-pill">{escape(name)}</span>' for name in logos
    )
    category_markup = "".join(
        f'<a class="source-category-chip" href="{href}">{escape(label)}</a>'
        for label, href in categories
    )
    release_markup = "".join(
        f'<a class="source-release-card" href="{href}"><span>{escape(provider)}</span><strong>{escape(title)}</strong><small>了解更多</small></a>'
        for title, href, provider in releases
    )
    career_markup = "".join(
        f'<a href="{href}">{escape(label)}</a>' for label, href in career_tiles
    )
    faq_markup = "".join(
        f'<details><summary>{escape(question)}</summary><p>此离线 clone 提供本地课程目录、搜索、账户入口、报名与学习流程，用于复刻 Coursera 的核心公开体验。</p></details>'
        for question in faqs
    )
    return f"""
<section class="source-plus-band"><div><p>Coursera Plus</p><h2>订阅即可解锁 10,000 多门课程</h2><p>开始 7 天免费试用，浏览证书、专项课程和职业技能内容。</p></div><a href="/checkout/deep-learning">开始 7 天免费试用</a></section>
<section class="source-partners"><h2>学习来自 350 多家领先大学和公司的知识</h2><div>{logo_markup}</div></section>
<section class="source-career-split"><article><p>开启新的职业生涯</p><h2>为热门职业做好就业准备</h2><a href="/browse">探索计划</a></article><article><p>获得学位</p><h2>从顶尖大学获取在线学位</h2><a href="/browse">探索学位</a></article></section>
<section class="source-category-section"><h2>探索类别</h2><div>{category_markup}</div></section>
<section class="source-release-section"><div class="source-section-heading"><h2>热门新版本</h2><a href="/browse">探索课程</a></div><div class="source-release-grid">{release_markup}</div></section>
<section class="source-career-question"><h2>是什么让您今天来到 Coursera？</h2><nav>{career_markup}</nav><a class="source-explore-all" href="/browse">探索所有</a></section>
<section class="source-outcomes"><h2>91% 的学员取得了积极的职业成果</h2><p>为什么人们选择 Coursera</p><div><blockquote>“课程让我能够更清晰地规划职业下一步。”<cite>Sarah W.</cite></blockquote><blockquote>“灵活学习帮助我持续提升技能。”<cite>Noeris B.</cite></blockquote><blockquote>“项目练习让我能把知识应用到工作中。”<cite>Abdullahi M.</cite></blockquote></div></section>
<section class="source-faq"><h2>Frequently asked questions</h2>{faq_markup}</section>"""


def _home_cookie_banner(request: Request) -> str:
    if request.cookies.get("coursera_privacy_choice") in {"accept", "reject"}:
        return ""
    return """<aside class="source-cookie-banner" aria-label="隐私偏好"><form class="cookie-icon-form" action="/privacy-preferences" method="post"><button type="submit" name="choice" value="settings" class="cookie-icon" aria-label="Cookie settings">✓×</button></form><p>We process your personal information to measure and improve our sites and service, to assist our marketing campaigns and to provide personalized content and advertising. You can exercise your privacy rights by using the buttons on the right. For more information see our privacy notice. <a href="/privacy">Privacy Notice</a></p><div class="cookie-actions"><a href="/privacy">Your Privacy Rights</a><form action="/privacy-preferences" method="post"><button type="submit" name="choice" value="reject">Reject</button></form><form action="/privacy-preferences" method="post"><button type="submit" name="choice" value="accept">Accept</button></form></div><form class="cookie-close-form" action="/privacy-preferences" method="post"><button type="submit" name="choice" value="reject" class="cookie-close" aria-label="Close">×</button></form></aside>"""


def _related_search_card(record: dict[str, Any]) -> str:
    return f"""
<a class="search-related-card" href="{escape(_record_href(record))}" data-catalog-record="{escape(record["id"])}">
  <span class="related-thumb" aria-hidden="true">{escape(record["provider"][0])}</span>
  <span class="related-copy"><span>{escape(record["provider"])}</span><strong>{escape(record["title"])}</strong><small>Best for: learners comparing deep learning options</small></span>
</a>"""


def _card_grid(records: list[dict[str, Any]]) -> str:
    return (
        '<div class="card-grid course-collection">'
        + "".join(_card(record) for record in records)
        + "</div>"
    )


def _category_pills() -> str:
    return (
        '<nav class="subject-tile-grid" aria-label="按主题浏览课程">'
        + "".join(
            f'<a class="subject-tile" href="/browse/{slug}"><span class="subject-tile-icon" aria-hidden="true">{SUBJECT_ICONS[slug]}</span>{escape(SUBJECTS_ZH[subject])}</a>'
            for slug, subject in SUBJECTS.items()
        )
        + "</nav>"
    )


def _compact_category_pills() -> str:
    return (
        '<nav class="browse-category-pills" aria-label="Explore Categories">'
        + "".join(
            f'<a href="/browse/{slug}"><span aria-hidden="true">{SUBJECT_ICONS[slug]}</span>{escape(SUBJECTS_ZH[subject])}</a>'
            for slug, subject in SUBJECTS.items()
        )
        + "</nav>"
    )


def _option(value: str, label: str, selected: str) -> str:
    chosen = " selected" if value == selected else ""
    return f'<option value="{escape(value)}"{chosen}>{escape(label)}</option>'


def _select(name: str, label: str, values: list[str], selected: str) -> str:
    options = [_option("", f"All {label.casefold()}", selected)]
    options.extend(_option(value, value, selected) for value in values)
    return f'<label>{escape(label)}<select name="{name}">{"".join(options)}</select></label>'


def _filter_catalog(
    *,
    q: str,
    category: str,
    level: str,
    topic: str,
    duration: str,
    rating: float | None,
    language: str,
    schedule: str,
    sort: str,
) -> list[dict[str, Any]]:
    records = load_catalog_seed()
    query = q.strip().casefold()
    topic_query = topic.strip().casefold()
    subject = SUBJECTS.get(category)

    def matches(record: dict[str, Any]) -> bool:
        searchable = " ".join(
            [
                record["title"],
                record["topic"],
                record["subject"],
                record["provider"],
                *record["instructors"],
            ]
        ).casefold()
        return (
            (not query or query in searchable)
            and (not category or subject == record["subject"])
            and (not level or level.casefold() == record["level"].casefold())
            and (not topic_query or topic_query in record["topic"].casefold())
            and (not duration or duration.casefold() == record["duration"].casefold())
            and (rating is None or record["rating"] >= rating)
            and (not language or language.casefold() == record["language"].casefold())
            and (not schedule or schedule.casefold() == record["schedule"].casefold())
        )

    filtered = [record for record in records if matches(record)]
    if sort == "rating-desc":
        filtered.sort(key=lambda record: -record["rating"])
    elif sort == "title-desc":
        filtered.sort(key=lambda record: record["title"].casefold(), reverse=True)
    else:
        filtered.sort(key=lambda record: record["title"].casefold())
    return filtered


def _record_by_id(record_id: str) -> dict[str, Any] | None:
    return next(
        (record for record in load_catalog_seed() if record["id"] == record_id),
        None,
    )


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "site_id": SITE_ID}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> str:
    catalog = load_catalog_seed()
    by_id = {record["id"]: record for record in catalog}
    most_popular = [
        {
            **by_id["applied-data-analysis"],
            "title": "Google 数据分析",
            "provider": "Google",
            "thumb_asset": "/static/source-home-trend-google-analytics.png",
            "href": "/search?q=Google+%E6%95%B0%E6%8D%AE%E5%88%86%E6%9E%90",
        },
        by_id["machine-learning-foundations"],
        by_id["python-programming"],
    ]
    weekly_focus = [
        {
            **by_id["tech-support"],
            "title": "Microsoft 初级质量保证/软件测试工程师",
            "provider": "Microsoft",
            "thumb_asset": "/static/source-home-trend-microsoft-qa.png",
            "href": "/search?q=Microsoft+QA",
        },
        by_id["financial-accounting"],
        by_id["business-strategy"],
    ]
    ai_skills = [
        {
            **by_id["responsible-ai-basics"],
            "title": "用于头脑风暴和规划的 AI",
            "provider": "Google",
            "thumb_asset": "/static/source-home-trend-google-ai.png",
            "href": "/search?q=Google+AI",
        },
        by_id["deep-learning-specialization"],
        by_id["medical-neuroscience"],
    ]
    body = f"""
<section class="promo-rail" data-source-home-promo="true" aria-label="推荐学习内容"><article class="promo-panel promo-panel-dark" data-source-promo-image-card="true"><img src="/static/source-home-google-promo.png" alt="" aria-hidden="true"><div class="source-promo-overlay"><p class="promo-provider">Google</p><h1>New! Learn vibe coding with Google</h1><p>Build custom apps using AI, all without writing a single line of code.</p><a class="promo-action" href="/search?q=Google+AI">Enroll now <span aria-hidden="true">→</span></a></div></article><article class="promo-panel promo-panel-blue" data-source-promo-image-card="true"><img src="/static/source-home-career-promo.png" alt="" aria-hidden="true"><div class="source-promo-overlay"><p class="promo-provider">Coursera</p><h2>开始、转换或提升您的职业生涯</h2><p>与来自顶级机构的 10,000 多门课程一起成长</p><a class="promo-action promo-action-light" href="/signup">免费加入 <span aria-hidden="true">→</span></a></div></article></section>
<div class="carousel-dots" aria-hidden="true"><span></span><span></span><span></span></div>
<section class="home-trends" aria-labelledby="home-trends-heading"><h2 id="home-trends-heading">趋势课程</h2><div class="trend-columns">{_trend_column("最受欢迎", most_popular)}{_trend_column("每周聚焦", weekly_focus)}{_trend_column("紧缺的 AI 技能", ai_skills)}</div></section>
<section class="career-ready"><h2>为热门职业做好就业准备 <span aria-hidden="true">→</span></h2><p>入门无需经验。</p><nav aria-label="热门职业主题"><a href="/browse/data-science">数据</a><a href="/browse/business">商业</a><a href="/browse/business">销售与市场营销</a><a href="/browse/information-technology">信息技术</a><a href="/browse/computer-science">软件工程</a></nav></section>
{_home_lower_sections()}
{_home_cookie_banner(request)}"""
    return _page(
        request,
        "Online Courses, Certificates, & Degrees",
        body,
        body_class="catalog-landing",
        document_title="Coursera | Online Courses, Certificates, & Degrees",
    )


@app.post("/privacy-preferences")
async def privacy_preferences(request: Request) -> Response:
    values = await _form_values(request)
    choice = values.get("choice", "reject")
    if choice not in {"accept", "reject", "settings"}:
        choice = "reject"
    if choice == "settings":
        response = RedirectResponse("/privacy", status_code=303)
    else:
        response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "coursera_privacy_choice",
        "accept" if choice == "accept" else "reject",
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/privacy", response_class=HTMLResponse)
def privacy_notice(request: Request) -> HTMLResponse:
    body = """<section class="page-heading"><p class="eyebrow">Privacy Notice</p><h1>隐私与 Cookie 偏好</h1><p>此离线 clone 只保存本地演示偏好，不连接 Coursera，不发送营销请求，也不保存真实个人资料。</p><form class="auth-form" action="/privacy-preferences" method="post"><button type="submit" name="choice" value="accept">Accept</button><button type="submit" name="choice" value="reject">Reject</button></form><a href="/">返回首页</a></section>"""
    return HTMLResponse(_page(request, "Privacy Notice", body))


@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request) -> HTMLResponse:
    body = """<section class="page-heading"><p class="eyebrow">Terms</p><h1>本地服务条款</h1><p>此页面用于 WebsiteBench 离线复刻验收。报名、付款、学习记录和账户操作均为本地合成数据，不产生真实 Coursera 外部效果。</p><a href="/">返回首页</a></section>"""
    return HTMLResponse(_page(request, "Terms", body))


@app.get("/browse", response_class=HTMLResponse)
def browse(request: Request) -> str:
    catalog = load_catalog_seed()
    popular_ids = (
        "applied-data-analysis",
        "machine-learning-foundations",
        "python-programming",
        "business-strategy",
    )
    popular_records = [
        record
        for record_id in popular_ids
        if (record := _record_by_id(record_id)) is not None
    ]
    remaining_records = [
        record for record in catalog if record["id"] not in popular_ids
    ]
    popular_filters = """<nav class="popular-filters" aria-label="热门课程分类"><strong>全部</strong><a href="/browse/business">商业</a><a href="/browse/data-science">数据科学</a><a href="/browse/information-technology">信息技术</a><a href="/browse/computer-science">计算机科学</a></nav>"""
    popular = (
        '<div class="source-popular-row"><div class="card-grid popular-grid">'
        + "".join(_card(record) for record in popular_records)
        + '</div></div><details class="more-popular"><summary>显示更多课程</summary><div class="card-grid expanded-popular-grid">'
        + "".join(_card(record) for record in remaining_records[:8])
        + "</div></details>"
    )
    roles = """<section class="browse-roles"><div class="role-filters"><strong>级别：初级</strong><span>热门</span><span>软件工程与信息技术</span><span>商务</span><span>销售与市场营销</span><span>数据科学与分析</span><span>医疗保健</span></div><h2>探索角色</h2><p>通过 7 天免费试听这些高级课程，提升您的职业发展并掌握新技能</p><div class="role-explorer-row"><article class="role-explorer-card"><h3>数据科学家</h3><p>数据科学家利用统计数据、机器学习和 visualization 来分析大型数据集。</p><a href="/search?q=data+scientist">查看所有</a></article><article class="role-explorer-card"><h3>机器学习工程师</h3><p>机器学习工程师使用大型数据集和神经网络构建现代化模型。</p><a href="/search?q=machine+learning">提供方</a></article></div></section>"""
    body = f"""<section class="browse-source-heading"><h1>Explore Categories</h1>{_compact_category_pills()}</section><section class="browse-popular"><h2>最受欢迎</h2>{popular_filters}{popular}</section>{roles}<section class="wb-section browse-all-subjects"><h2>按主题浏览课程</h2>{_category_pills()}</section>"""
    return _page(
        request,
        "Online Course Catalog by Topic and Skill",
        body,
        body_class="browse-page catalog-landing",
    )


@app.get("/browse/{category}", response_class=HTMLResponse)
def browse_category(request: Request, category: str) -> str:
    subject = SUBJECTS.get(category)
    if subject is None:
        raise HTTPException(status_code=404)
    records = [record for record in load_catalog_seed() if record["subject"] == subject]
    localized_subject = SUBJECTS_ZH[subject]
    body = f"""<nav class="catalog-breadcrumbs"><a href="/browse">浏览</a><span>›</span>{escape(localized_subject)}</nav><section class="catalog-heading"><h1>{escape(localized_subject)}</h1><p>探索灵活课程，按自己的节奏培养实用技能。</p></section><section class="wb-section"><h2>热门课程</h2>{_card_grid(records)}</section>"""
    return _page(request, f"{subject} Online Courses", body)


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    query: str = "",
    category: str = "",
    level: str = "",
    topic: str = "",
    duration: str = "",
    rating: float | None = None,
    language: str = "",
    schedule: str = "",
    sort: str = "title-asc",
) -> str:
    catalog = load_catalog_seed()
    q = q or query
    records = _filter_catalog(
        q=q,
        category=category,
        level=level,
        topic=topic,
        duration=duration,
        rating=rating,
        language=language,
        schedule=schedule,
        sort=sort,
    )
    rating_value = "" if rating is None else f"{rating:g}"
    form = f"""
<form class="filters source-filter-panel" action="/search" method="get">
  <h2>筛选和排序</h2>
  <label class="search-wide">搜索<input name="q" value="{escape(q)}" placeholder="课程、主题或技能"></label>
  {_select("category", "主题", list(SUBJECTS), category)}
  {_select("level", "级别", ["Beginner", "Intermediate", "Advanced", "Mixed"], level)}
  <label>主题关键词<input name="topic" value="{escape(topic)}" placeholder="例如 Neural"></label>
  {_select("duration", "课程长度", sorted({record["duration"] for record in catalog}), duration)}
  {_select("rating", "评分", ["4.5", "4.7", "4.8", "4.9"], rating_value)}
  {_select("language", "语言", sorted({record["language"] for record in catalog}), language)}
  {_select("schedule", "学习节奏", sorted({record["schedule"] for record in catalog}), schedule)}
  <label>排序<select name="sort">{_option("title-asc", "标题 A–Z", sort)}{_option("title-desc", "标题 Z–A", sort)}{_option("rating-desc", "评分最高", sort)}</select></label>
  <button class="wb-primary" type="submit">显示结果</button>
</form>"""
    if records:
        result_body = _card_grid(records)
    else:
        clear_query = urlencode({"q": ""})
        recommendations = _card_grid(catalog[:3])
        result_body = f"""<div class="empty-state"><h2>没有找到与“{escape(q)}”匹配的课程</h2><p>请尝试更宽泛的关键词、移除筛选条件，或浏览全部主题。</p><div class="empty-state-links"><a href="/search?{clear_query}">清除搜索</a><a href="/search">重置全部筛选</a><a href="/browse">浏览可用课程</a></div><section class="recommendations"><h3>推荐课程</h3><p>当前 Coursera 也会针对该关键词显示学习建议；本地 clone 保留一组可浏览的恢复选项。</p>{recommendations}</section></div>"""
    ai_overview = ""
    if q:
        lead = next((record for record in records if "Deep Learning" in record["title"]), None)
        if lead is None:
            lead = _record_by_id("deep-learning-specialization")
        lead_card = _trend_card(lead) if lead is not None else ""
        related = [
            record
            for record_id in (
                "neural-networks-deep-learning",
                "machine-learning-foundations",
                "convolutional-neural-networks",
            )
            if (record := _record_by_id(record_id)) is not None
        ]
        related_cards = "".join(_related_search_card(record) for record in related)
        ai_overview = f"""<section class="search-ai-overview"><h2>AI 概览</h2><p>You are looking for {escape(q)} from DeepLearning.AI:</p>{lead_card}<p class="ai-summary">This specialization covers key deep learning techniques including convolutional and recurrent neural networks, and computer vision applications.</p><a href="/specializations/deep-learning">显示更多</a><section class="search-related"><h3>其他类似课程：</h3><div class="search-related-cards">{related_cards}</div></section><nav class="ai-question-chips" aria-label="AI suggested prompts"><a href="/search?q=compare+deep+learning">对比这些课程</a><a href="/search?q=why+recommend+deep+learning">为什么向我推荐这些课程？</a><a href="/search?q=beginner+deep+learning">哪一个最适合完全的初学者？</a></nav></section>"""
    chips = """<nav class="source-filter-chips" aria-label="搜索筛选"><a href="#filters">筛选和排序</a><a href="/search?category=data-science">主题</a><a href="/search?duration=3+weeks+at+10+hours+a+week">课程长度</a><a href="/search?q=Deep+Learning">了解产品</a><a href="/search?language=English">语言</a><a href="/search?level=Beginner">级别</a></nav>"""
    body = f"""<section class="search-source-layout"><div class="search-source-main">{ai_overview}<section class="source-results"><h2>所有结果</h2>{chips}<div class="results" data-result-count="{len(records)}"><h3>{len(records)} 个结果</h3>{result_body}</div></section></div><aside class="search-chat-panel" aria-label="Coursera assistant"><div class="chat-notice"><strong>您的隐私与本次聊天</strong><p>您的聊天记录可能会被暂时保存，以便为您提供个性化体验。</p><button type="button">确定</button></div><div class="chat-thread"><p>You'll find a mix of Deep Learning specializations, courses, and professional certificates.</p><div class="chat-levels"><span>Beginner</span><span>Intermediate</span><span>Advanced</span></div><label>或者提问…<input placeholder="Deep Learning Specialization"></label></div></aside></section><section id="filters" class="search-filter-details">{form}</section>"""
    return _page(
        request,
        "Search",
        body,
        document_title=(
            "Coursera | Online Courses From Top Universities. Join for Free"
        ),
        search_value=q,
    )


@app.get("/specializations/deep-learning", response_class=HTMLResponse)
def deep_learning_specialization(request: Request) -> str:
    specialization = _record_by_id("deep-learning-specialization")
    if specialization is None:
        raise HTTPException(status_code=404)
    components = [
        record
        for record in load_catalog_seed()
        if record.get("parent_specialization_id") == specialization["id"]
    ]
    course_list = "".join(
        f"""<li><span class="course-number">{index}</span><div><p>课程 {index}</p><h3><a href="/learn/{escape(record["id"])}">{escape(record["title"])}</a></h3><p>{escape(record["duration"])} · {escape(record["level"])}</p>{_evidence_note(record, compact=True)}</div></li>"""
        for index, record in enumerate(components, start=1)
    )
    _backend, _auth, _token, session = _request_session(request)
    enrollment_action = (
        """<div class="enrollment-actions"><form class="enrollment-options" action="/enrollments" method="post"><input type="hidden" name="course_id" value="deep-learning-specialization"><label>报名轨道<select name="track" required><option value="free">免费学习</option><option value="audit">旁听</option></select></label><button class="secondary-button" type="submit">保存本地报名</button></form><a class="wb-primary" href="/checkout/deep-learning">进入本地结账</a><p>本地结账仅使用 local-sandbox，不会产生真实付款。</p></div>"""
        if session["authenticated"]
        else '<div class="enrollment-actions"><a class="wb-primary" href="/login?next=/checkout/deep-learning">免费注册</a><a class="secondary-button" href="/login?next=/specializations/deep-learning">登录后报名或旁听</a></div>'
    )
    body = f"""
<nav class="course-breadcrumbs"><a href="/browse">浏览</a><span>›</span><a href="/browse/data-science">数据科学</a><span>›</span>Deep Learning</nav>
<section class="program-hero"><div><p class="provider">DeepLearning.AI</p><h1>深度学习专项课程</h1><p class="lead">掌握深度学习基础，构建机器学习能力，并把 AI 知识应用到真实问题中。</p><p>讲师：<strong>Andrew Ng 等 3 位讲师</strong> <span class="badge">顶级讲师</span></p><section class="trial-card"><h2>7 天免费试用</h2><p>无限制访问专项课程中的全部课程，可随时取消。</p><p><strong>试用结束后，¥196/月</strong></p>{enrollment_action}</section></div><img src="/static/deep-learning-mark.svg" alt="Deep Learning program mark"></section>
<section class="program-facts"><div><strong>5 门课程系列</strong><span>系统学习一个主题</span></div><div><strong>4.8 ★</strong><span>来自学习者评分</span></div><div><strong>中级水平</strong><span>建议具备基础经验</span></div><div><strong>灵活安排</strong><span>每周 10 小时，约 3 个月</span></div></section>
<section class="detail-section"><h2>你将学到什么</h2><p>构建和训练深度神经网络，分析模型表现，并将卷积模型和序列模型用于实践任务。</p><h2>课程系列</h2><ol class="course-series">{course_list}</ol></section>"""
    return _page(
        request,
        "Deep Learning Specialization",
        body,
    )


@app.get("/checkout/deep-learning", response_class=HTMLResponse)
def checkout_plan(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, _subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before choosing a checkout plan")
    body = f"""
<nav class="course-breadcrumbs checkout-breadcrumbs"><a href="/specializations/deep-learning">Deep Learning Specialization</a><span>›</span><span>结帐</span></nav>
<section class="source-checkout-shell">
  <main class="source-checkout-main">
    <h1>结帐</h1>
    <p class="checkout-required">所有字段均为必填字段</p>
    <p class="safe-note">该页面按当前观察到的 Coursera 结账信息重建。不会提交真实付款数据，也不会联系 Coursera。</p>
    <form class="source-checkout-form" action="/checkout/deep-learning" method="post" autocomplete="off">
      <input type="hidden" name="course_id" value="deep-learning-specialization">
      <input type="hidden" name="plan_id" value="deep-learning-specialization-paid">
      <section class="checkout-billing" aria-labelledby="billing-heading">
        <h2 id="billing-heading">账单信息</h2>
        <label>全名<input id="billing-name" type="text" placeholder="请输入您的姓名" autocomplete="off"></label>
        <label>国家/地区<select id="billing-country" autocomplete="off"><option>中国</option><option>美国</option><option>新加坡</option></select></label>
      </section>
      <section class="source-payment-card" aria-labelledby="payment-heading">
        <h2 id="payment-heading">支付方式</h2>
        <div class="payment-choice is-selected"><span>银行卡</span><span>Visa · Mastercard · American Express</span></div>
        <label>卡号<input id="synthetic-card-number" inputmode="numeric" autocomplete="off" placeholder="1234 1234 1234 1234"></label>
        <div class="payment-grid">
          <label>到期日<input id="synthetic-expiry" autocomplete="off" placeholder="MM / YY"></label>
          <label>安全码<input id="synthetic-cvv" inputmode="numeric" autocomplete="off" placeholder="CVC"></label>
        </div>
        <label class="save-card"><input id="synthetic-save-card" type="checkbox"> 保存付款方式以供将来购买</label>
        <div class="payment-choice paypal-choice"><span>Paypal</span><span>使用 PayPal 继续</span></div>
      </section>
      <p class="checkout-terms">点击“开始免费试用”即表示你同意 Coursera 的<a href="/terms">服务条款</a>和<a href="/privacy">隐私声明</a>。本 clone 使用 local-sandbox，只创建本地草稿。</p>
      <button class="wb-primary checkout-start" type="submit">开始免费试用</button>
    </form>
    <p class="checkout-safety"><strong>开始 7 天免费试用。</strong>今天应付 ¥0；试用结束后可在本地订单历史中取消。</p>
    <a class="checkout-return" href="/specializations/deep-learning">返回专项课程</a>
  </main>
  <aside class="source-checkout-summary" aria-label="订单摘要">
    <article class="summary-course">
      <a href="/specializations/deep-learning">Deep Learning</a>
      <p>由 DeepLearning.AI 提供</p>
      <a class="summary-remove" href="/specializations/deep-learning">移除</a>
    </article>
    <p class="summary-note">无绑定合同。可随时取消。</p>
    <dl class="summary-prices">
      <div><dt>月度订阅</dt><dd>7 天免费试用</dd></div>
      <div><dt>之后为 ¥196/月</dt><dd>¥196/月</dd></div>
      <div class="summary-total"><dt>今日合计：¥0</dt><dd>¥0</dd></div>
    </dl>
    <p class="summary-small">试用期结束前取消不会收费。此离线版本不会提交真实付款数据。</p>
  </aside>
</section>"""
    return HTMLResponse(
        _page(request, "Deep Learning checkout plan", body, checkout_chrome=True)
    )


@app.get("/payments/checkout", response_class=HTMLResponse)
def source_checkout_alias(request: Request) -> HTMLResponse:
    """Expose the observed source-shaped checkout entry locally."""

    return checkout_plan(request)


@app.post("/payments/checkout")
async def source_checkout_alias_post(request: Request) -> Response:
    """Create the same owner-bound local draft from the observed source path."""

    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before starting checkout")
    values = await _form_values(request)
    try:
        draft = checkout.create_draft(
            subject,
            course_id=values.get("course_id", "deep-learning-specialization"),
            plan_id=values.get("plan_id", ""),
        )
    except ValueError as exc:
        return _checkout_validation(request, str(exc))
    return RedirectResponse(f"/checkout/{draft['draft_id']}/payment", status_code=303)


@app.post("/checkout/deep-learning")
async def create_checkout(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before starting checkout")
    values = await _form_values(request)
    try:
        draft = checkout.create_draft(
            subject,
            course_id=values.get("course_id", ""),
            plan_id=values.get("plan_id", ""),
        )
    except ValueError as exc:
        return _checkout_validation(request, str(exc))
    return RedirectResponse(f"/checkout/{draft['draft_id']}/payment", status_code=303)


@app.get("/checkout/{draft_id}/payment", response_class=HTMLResponse)
def checkout_payment(request: Request, draft_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to open this synthetic payment page")
    try:
        checkout.get_draft(subject, draft_id)
    except LookupError:
        return _checkout_not_found(request)
    body = f"""<nav class="course-breadcrumbs"><a href="/checkout/deep-learning">结账</a><span>›</span>付款方式</nav><section class="checkout-shell"><p class="eyebrow">本地安全演示</p><h1>付款方式</h1><p class="safe-note"><strong>请不要输入真实付款信息。</strong>下方演示输入内容只保留在当前浏览器页面，不会作为表单字段提交或保存。</p><form class="synthetic-payment" action="/checkout/{escape(draft_id)}/review" method="get" autocomplete="off"><label>示例卡号<input id="synthetic-card-number" inputmode="numeric" autocomplete="off" placeholder="仅用于本地演示"></label><label>示例有效期<input id="synthetic-expiry" autocomplete="off" placeholder="MM / YY"></label><label>示例安全码<input id="synthetic-cvv" inputmode="numeric" autocomplete="off" placeholder="仅用于本地演示"></label><button class="wb-primary" type="submit">继续（不提交上述内容）</button></form><a href="/specializations/deep-learning">返回专项课程</a></section>"""
    return HTMLResponse(_page(request, "本地付款方式", body, checkout_chrome=True))


@app.get("/checkout/{draft_id}/review", response_class=HTMLResponse)
def checkout_review(request: Request, draft_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to review this checkout")
    try:
        checkout.get_draft(subject, draft_id)
    except LookupError:
        return _checkout_not_found(request)
    idempotency_key = f"browser-attempt:{secrets.token_urlsafe(18)}"
    body = f"""<nav class="course-breadcrumbs"><a href="/checkout/{escape(draft_id)}/payment">付款方式</a><span>›</span>确认</nav><section class="checkout-shell"><p class="eyebrow">仅限本地 sandbox</p><h1>确认免费试用</h1><p>这是一项本地演示，不会产生外部或真实付款效果。</p>{_checkout_totals()}<p class="checkout-terms">点击下方操作即表示您已阅读本地演示的使用条款，并可在订单历史中取消。</p><form class="sandbox-scenarios" action="/checkout/{escape(draft_id)}/attempt" method="post"><input type="hidden" name="idempotency_key" value="{escape(idempotency_key)}"><fieldset><legend>选择确定的本地 sandbox 结果</legend><label><input type="radio" name="scenario_id" value="sandbox-approved" required>模拟成功</label><label><input type="radio" name="scenario_id" value="sandbox-declined" required>模拟被拒绝</label><label><input type="radio" name="scenario_id" value="sandbox-retry" required>模拟需重试</label></fieldset><button class="wb-primary" type="submit">开始免费试用</button></form><a href="/specializations/deep-learning">返回专项课程</a></section>"""
    return HTMLResponse(_page(request, "确认本地结账", body, checkout_chrome=True))


@app.post("/checkout/{draft_id}/attempt")
async def checkout_attempt(request: Request, draft_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to submit this local checkout")
    try:
        values = await _exact_checkout_attempt_values(request)
    except ValueError as exc:
        return _checkout_validation(request, str(exc))
    if values["scenario_id"] not in {
        "sandbox-approved",
        "sandbox-declined",
        "sandbox-retry",
    }:
        return _checkout_validation(request, "Choose one available sandbox scenario.")
    try:
        result = checkout.attempt(
            subject,
            draft_id,
            scenario_id=values["scenario_id"],
            idempotency_key=values["idempotency_key"],
        )
    except LookupError:
        return _checkout_not_found(request)
    except PaymentConflict as exc:
        return _checkout_validation(request, str(exc), status_code=409)
    except PaymentRejected as exc:
        return _checkout_validation(request, str(exc), status_code=409)
    except PaymentError as exc:
        return _checkout_validation(request, str(exc))
    if result["outcome"] == "approved":
        return RedirectResponse(
            f"/orders/{result['order']['order_id']}", status_code=303
        )
    heading = "模拟付款被拒绝" if result["outcome"] == "declined" else "模拟付款需要重试"
    body = f"""<section class="checkout-shell"><p class="eyebrow">本地 sandbox 结果</p><h1>{heading}</h1><p>未创建订单或付费报名，也没有尝试任何外部付款。</p><a class="wb-primary" href="/checkout/{escape(draft_id)}/review">选择其他本地结果</a><a href="/specializations/deep-learning">返回专项课程</a></section>"""
    return HTMLResponse(_page(request, "本地 sandbox 结果", body))


@app.get("/learn/{course_id}/preview", response_class=HTMLResponse)
def course_preview(request: Request, course_id: str) -> str:
    record = _record_by_id(course_id)
    if record is None or record["type"] != "course":
        raise HTTPException(status_code=404)
    first_lesson = record["syllabus"][0]
    body = f"""<nav class="course-breadcrumbs"><a href="/learn/{escape(course_id)}">{escape(record["title"])}</a><span>›</span>免费预览</nav><section class="preview-shell"><p class="eyebrow">无需报名</p><h1>免费预览：{escape(record["title"])}</h1>{_evidence_note(record)}<div class="lesson-player"><span aria-hidden="true">▶</span><div><h2>{escape(first_lesson)}</h2><p>此本地示例介绍核心概念并提供简短练习；预览不会创建学习进度或连接外部服务。</p></div></div><a class="secondary-button" href="/learn/{escape(course_id)}">返回课程详情</a></section>"""
    return _page(request, f"Free preview: {record['title']}", body)


@app.get("/learn/{course_id}", response_class=HTMLResponse)
def course_detail(request: Request, course_id: str) -> str:
    record = _record_by_id(course_id)
    if record is None or record["type"] != "course":
        raise HTTPException(status_code=404)
    syllabus = "".join(f"<li>{escape(item)}</li>" for item in record["syllabus"])
    instructors = ", ".join(escape(item) for item in record["instructors"])
    tracks = "".join(f"<li>{escape(item)}</li>" for item in record["enrollment_tracks"])
    subject_slug = SUBJECT_SLUGS[record["subject"]]
    specialization_membership = (
        '<p>此课程属于 <a href="/specializations/deep-learning">'
        "Deep Learning 专项课程</a></p>"
        if record.get("parent_specialization_id") == "deep-learning-specialization"
        else ""
    )
    enrollment_course_id = str(
        record.get("parent_specialization_id") or record["id"]
    )
    _backend, _auth, _token, session = _request_session(request)
    enrollment_action = (
        f"""<form class="enrollment-options" action="/enrollments" method="post"><input type="hidden" name="course_id" value="{escape(enrollment_course_id)}"><label>报名轨道<select name="track" required><option value="free">免费学习</option><option value="audit">旁听</option></select></label><button class="wb-primary" type="submit">保存本地报名</button></form>"""
        if session["authenticated"]
        else f'<a class="wb-primary" href="/login?next=/learn/{escape(record["id"])}">免费注册</a>'
    )
    localized_titles = {
        "neural-networks-deep-learning": "神经网络与深度学习",
    }
    display_title = localized_titles.get(record["id"], record["title"])
    skill_chips = "".join(
        f"<span>{escape(skill)}</span>"
        for skill in (
            "人工智能和机器学习",
            "深度学习",
            "人工智能",
            "模型优化",
            "模型训练",
            "卷积神经网络",
            "应用机器学习",
            "监督学习",
            "机器学习方法",
        )
    )
    body = f"""
<nav class="course-breadcrumbs"><a href="/">⌂</a><span>›</span><a href="/browse">浏览</a><span>›</span><a href="/browse/{escape(subject_slug)}">{escape(SUBJECTS_ZH[record["subject"]])}</a><span>›</span>机器学习</nav>
<section class="course-hero source-course-hero" data-course-detail="{escape(record["id"])}"><div><p class="provider">{escape(record["provider"])}</p><h1>{escape(display_title)}</h1>{specialization_membership}<p>位教师：<strong>{instructors}</strong> <span class="badge">顶尖授课教师</span></p>{enrollment_action}<a class="secondary-button" href="/learn/{escape(record["id"])}/preview">预览课程</a></div><div class="course-orbit" aria-hidden="true"></div></section>
<section class="course-stats"><div><strong>4 个模块</strong><span>深入了解一个主题并学习基础知识。</span></div><div><strong>{record["rating"]:.1f} ★</strong><span>123,795 条评论</span></div><div><strong>中级 等级</strong><span>推荐体验</span></div><div><strong>灵活的计划</strong><span>3 周 在 10 小时 一周，自行安排学习进度</span></div><div><strong>👍 96%</strong><span>大多数学生喜欢此课程</span></div></section>
<nav class="course-tabs" aria-label="课程详情"><a href="#about">关于</a><a href="#outcomes">结果</a><a href="#modules">单元</a><a href="#recommendations">推荐</a><a href="#reviews">评价</a><a href="#enroll">审阅</a></nav>
<section id="about" class="course-source-detail"><h2>您将获得的技能</h2><div class="skill-chip-row">{skill_chips}</div>{_evidence_note(record)}<h2>您将学习的工具</h2><p>{escape(record["prerequisites"])}</p></section>
<section class="detail-grid course-lower-detail"><article id="modules"><h2>课程模块</h2><ol>{syllabus}</ol></article><article><h2>讲师</h2><p>{instructors}</p></article><article><h2>先修知识</h2><p>{escape(record["prerequisites"])}</p></article><article id="reviews"><h2>评论</h2><p>{escape(record["reviews_summary"])}</p></article><article><h2>价格</h2><p>{escape(record["pricing"])}</p></article><article id="enroll"><h2>报名选项</h2><ul>{tracks}</ul></article></section>"""
    return _page(request, record["title"], body)


def _auth_page(
    request: Request, kind: str, *, next_path: str = "/my-learning"
) -> str:
    if kind == "login":
        body = f"""
<section class="auth-modal-shell"><div class="auth-modal-backdrop" aria-hidden="true"><div class="auth-modal-course"><p>DeepLearning.AI</p><strong>神经网络与深度学习</strong><span>免费注册后开始学习</span></div></div><div class="auth-modal-card auth-card"><button class="auth-modal-close" type="button" aria-label="关闭">×</button><p class="eyebrow">Coursera</p><h1>登录或创建账户</h1><p class="safe-note" id="credential-note">此离线 clone 不会将凭据提交到 Coursera 或任何外部服务；仅使用合成的 .test 账号。</p><form class="auth-form" action="/auth/login" method="post" aria-describedby="credential-note" autocomplete="off"><input type="hidden" name="next" value="{escape(next_path)}"><label>电子邮件<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>密码<input type="password" name="password" placeholder="输入密码" required></label><button type="submit">继续</button></form><div class="identity-options"><a href="/auth/provider/google">继续使用 Google</a><a href="/auth/provider/facebook">继续使用 Facebook</a><a href="/auth/provider/apple">继续使用 Apple</a></div><a href="/account-recovery">登录时遇到问题？</a><p>还没有账户？<a href="/signup">免费注册</a></p><p>继续即表示您同意 Coursera 的<a href="/help#terms">使用条款</a>和<a href="/help#terms">隐私声明</a>。</p></div></section>"""
        return _page(request, "Login - Continue Learning", body)
    body = """
<section class="auth-modal-shell"><div class="auth-modal-backdrop" aria-hidden="true"><div class="auth-modal-course"><p>DeepLearning.AI</p><strong>从一门课程开始新的学习旅程</strong><span>本地数据仅保存在此 clone 中</span></div></div><div class="auth-modal-card auth-card"><button class="auth-modal-close" type="button" aria-label="关闭">×</button><p class="eyebrow">Coursera</p><h1>登录或创建账户</h1><p class="safe-note" id="signup-note">仅使用合成的 .test 数据。注册验证代码只会出现在 site-33 本地收件箱中。</p><form class="auth-form" action="/auth/registration/start" method="post" aria-describedby="signup-note" autocomplete="off"><label>姓名<input name="full_name" placeholder="离线学习者" required></label><label>电子邮件<input type="email" name="email" placeholder="learner@coursera.test" required></label><label>创建密码<input type="password" name="password" placeholder="创建密码" required></label><button type="submit">免费加入</button></form><div class="identity-options"><a href="/auth/provider/google">继续使用 Google</a><a href="/auth/provider/facebook">继续使用 Facebook</a><a href="/auth/provider/apple">继续使用 Apple</a></div><p>验证代码仅显示在受此浏览器会话保护的本地收件箱中，不会发送真实邮件。</p><p>继续即表示您同意 Coursera 的<a href="/help#terms">使用条款</a>和<a href="/help#terms">隐私声明</a>。</p><p>已有账户？<a href="/login">登录</a></p></div></section>"""
    return _page(request, "Signup - Start Learning", body)


@app.get("/login", response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    next_path = _safe_next_path(request.query_params.get("next"))
    response = HTMLResponse(
        _auth_page(
            request,
            "login",
            next_path=next_path,
        )
    )
    _set_session_cookie(response, backend, token)
    return response


@app.get("/signup", response_class=HTMLResponse)
def signup(request: Request) -> HTMLResponse:
    backend, _auth, token, _session = _request_session(request)
    response = HTMLResponse(_auth_page(request, "signup"))
    _set_session_cookie(response, backend, token)
    return response


@app.post("/auth/registration/start")
async def registration_start(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        email = _synthetic_email(values.get("email", ""))
        auth.start_registration(
            token,
            email=email,
            display_name=values.get("display_name", values.get("full_name", "")),
            password=values.get("password", ""),
        )
    except ValueError as exc:
        return _auth_failure(request, str(exc), status_code=422)
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=409)
    response = RedirectResponse("/local-inbox?purpose=registration", status_code=303)
    _set_session_cookie(response, backend, token)
    return response


@app.post("/auth/registration/verify")
async def registration_verify(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        auth.verify_registration_code(token, values.get("code", ""))
        completed = auth.complete_registration(
            token,
            subject_factory=learning_db.create_profile,
        )
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=400)
    response = RedirectResponse("/onboarding", status_code=303)
    _set_session_cookie(response, backend, str(completed["session_token"]))
    return response


@app.post("/auth/login")
async def auth_login(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        email = _synthetic_email(values.get("email", ""))
        signed_in = auth.sign_in(
            token,
            email=email,
            password=values.get("password", ""),
        )
    except (AuthError, ValueError) as exc:
        return _auth_failure(request, str(exc), status_code=401)
    response = RedirectResponse(_safe_next_path(values.get("next")), status_code=303)
    _set_session_cookie(response, backend, str(signed_in["session_token"]))
    return response


@app.post("/auth/logout")
def auth_logout(request: Request) -> Response:
    backend, auth = learning_db.services()
    cookie = backend.session_cookie
    auth.sign_out(request.cookies.get(cookie["name"]))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(
        cookie["name"],
        path="/",
        secure=True,
        httponly=True,
        samesite="Lax",
    )
    return response


@app.get("/auth/provider/{provider}", response_class=HTMLResponse)
def provider_boundary(request: Request, provider: str) -> str:
    labels = {"google": "Google", "facebook": "Facebook", "apple": "Apple"}
    label = labels.get(provider)
    if label is None:
        raise HTTPException(status_code=404)
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">{label}</p><h1>Offline identity boundary</h1><p>No external sign-in was opened. {label} identity is unavailable in this deterministic clone.</p><a href="/login">Use a local .test account</a></div></section>"""
    return _page(request, f"{label} offline boundary", body)


@app.get("/local-inbox", response_class=HTMLResponse)
def local_inbox(request: Request, purpose: str = "registration") -> HTMLResponse:
    if purpose not in {"registration", "password-reset"}:
        raise HTTPException(status_code=404)
    backend, auth, token, _session = _request_session(request)
    mail = auth.local_mail_for_session(token, purpose=purpose)
    if mail is None:
        content = "<p>No local message is available for this browser session.</p>"
    else:
        content = f"""<p>Template: {escape(str(mail["template"]))}</p><p class="verification-code" data-verification-code="{escape(str(mail["verification_code"]))}">{escape(str(mail["verification_code"]))}</p><form class="auth-form" action="{"/auth/registration/verify" if purpose == "registration" else "/auth/recovery/complete"}" method="post"><label>Verification code<input name="code" required></label>{'<label>New password<input type="password" name="new_password" required></label>' if purpose == "password-reset" else ""}<button type="submit">Verify locally</button></form>"""
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local outbox delivery</p><h1>Coursera local inbox</h1><p>No real email was sent. This message is visible only to the browser session that requested it.</p>{content}</div></section>"""
    response = HTMLResponse(_page(request, "Local inbox", body))
    if mail is not None:
        response.headers["X-Local-Inbox-Purpose"] = purpose
    _set_session_cookie(response, backend, token)
    return response


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request) -> str:
    _backend, _auth, _token, _subject = _authenticated_subject(request)
    body = """<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">Local learner profile</p><h1>Tell us about your learning goals</h1><form class="auth-form" action="/onboarding" method="post"><label>Current role<input name="current_role" required></label><label>Learning goal<input name="learning_goal" required></label><button type="submit">Save local profile</button></form></div></section>"""
    return _page(request, "Learner onboarding", body)


@app.post("/onboarding")
async def save_onboarding(request: Request) -> Response:
    _backend, _auth, _token, subject = _authenticated_subject(request)
    values = await _form_values(request)
    try:
        learning_db.update_profile(
            subject,
            current_role=values.get("current_role", ""),
            learning_goal=values.get("learning_goal", ""),
        )
    except ValueError as exc:
        return _auth_failure(request, str(exc), status_code=422)
    return RedirectResponse("/my-learning", status_code=303)


@app.get("/my-learning", response_class=HTMLResponse)
def my_learning(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view My Learning")
    enrollments = learning_db.list_enrollments(subject)
    learning_tools = ""
    if learning_db.has_active_enrollment(subject):
        state = learning_db.learning_state(subject)
        certificate = (
            "Certificate available"
            if state["certificate_available"]
            else "Certificate available after all lessons and quizzes"
        )
        review = learning_db.get_review(subject, "deep-learning-specialization")
        current_rating = int(review["rating"]) if review else 5
        current_review = str(review["review_text"]) if review else ""
        rating_options = "".join(
            f'<option value="{rating}"{" selected" if rating == current_rating else ""}>{rating} stars</option>'
            for rating in range(1, 6)
        )
        learning_tools = f"""<div class="learning-actions"><a data-resume-lesson="{escape(state["resume_lesson_id"])}" href="/learn/neural-networks-deep-learning/lesson/{escape(state["resume_lesson_id"])}">继续学习</a><span>{certificate}</span></div><section class="learning-review"><h2>课程评价</h2><p>您的本地评价可随时更新。</p><form class="auth-form" action="/learning/review" method="post"><label>评分<select name="rating" required>{rating_options}</select></label><label>评价<textarea name="review_text" required>{escape(current_review)}</textarea></label><button type="submit">保存本地评价</button></form></section>"""
    body = f"""<section class="learning-page"><p class="eyebrow">site-33 学习者</p><h1>我的学习</h1><p>报名、进度和书签均保留在此离线 clone 中。</p>{learning_tools}<section class="wb-section"><div class="card-grid">{_enrollment_rows(enrollments)}</div></section><nav class="learning-history-links"><a href="/account/preferences">学习偏好</a><a href="/account/history">报名历史</a><a href="/orders">订单历史</a></nav></section>"""
    return HTMLResponse(_page(request, "My Learning", body))


@app.get("/account/history", response_class=HTMLResponse)
def account_history(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view enrollment history")
    body = f"""<section class="page-heading"><p class="eyebrow">本地账户历史</p><h1>报名历史</h1><p>已取消的项目仍会保留，并且仅对其所有者可见。</p></section><section class="section"><div class="card-grid">{_enrollment_rows(learning_db.list_enrollments(subject))}</div><a href="/orders">查看订单历史</a> · <a href="/my-learning">返回我的学习</a></section>"""
    return HTMLResponse(_page(request, "报名历史", body))


@app.get("/orders", response_class=HTMLResponse)
def order_history(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view order history")
    records = checkout.list_orders(subject)
    body = f"""<section class="page-heading"><p class="eyebrow">仅限所有者的本地历史</p><h1>订单历史</h1><p>只有模拟成功的 local-sandbox 结账会创建持久订单。已取消的快照仍会显示。</p></section><section class="section"><div class="card-grid">{_order_rows(records)}</div><a href="/my-learning">返回我的学习</a></section>"""
    return HTMLResponse(_page(request, "订单历史", body))


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to view this order")
    try:
        order = checkout.get_order(subject, order_id)
    except LookupError:
        return _order_not_found(request)
    cancellation = (
        f"""<form action="/orders/{escape(order_id)}/cancel" method="post"><button type="submit">取消本地付费报名</button></form>"""
        if order["status"] == "PAID"
        else "<p>该订单及其付费报名已经取消；不可变快照仍保留在历史中。</p>"
    )
    status_label = "已付款" if order["status"] == "PAID" else "已取消"
    body = f"""<nav class="course-breadcrumbs"><a href="/orders">订单历史</a><span>›</span>{escape(order_id)}</nav><section class="checkout-shell" data-order-status="{escape(str(order["status"]))}"><p class="eyebrow">本地 sandbox 订单</p><h1>{status_label}</h1><p>订单 {escape(order_id)}</p><p>深度学习专项课程 · {escape(str(order["plan_label"]))}</p><p class="safe-note">这是不可变的本地模拟快照，没有发生真实付款或外部购买。</p>{_checkout_totals()}{cancellation}<a href="/orders">返回订单历史</a><a href="/specializations/deep-learning">返回专项课程</a></section>"""
    return HTMLResponse(_page(request, "订单详情", body))


@app.post("/orders/{order_id}/cancel")
def cancel_order(request: Request, order_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before canceling this order")
    try:
        checkout.cancel_order(subject, order_id)
    except LookupError:
        return _order_not_found(request)
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@app.post("/enrollments")
async def create_enrollment(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before enrolling")
    values = await _form_values(request)
    try:
        learning_db.enroll(
            subject,
            course_id=values.get("course_id", ""),
            track=values.get("track", ""),
        )
    except ValueError as exc:
        return HTMLResponse(
            _page(
                request,
                "Enrollment validation",
                f'<section class="not-found"><h1>Check enrollment choices</h1><p>{escape(str(exc))}</p></section>',
            ),
            status_code=422,
        )
    return RedirectResponse("/my-learning", status_code=303)


@app.post("/enrollments/{enrollment_id}/cancel")
def cancel_enrollment(request: Request, enrollment_id: int) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in before changing enrollment")
    try:
        learning_db.cancel_enrollment(subject, enrollment_id)
    except LookupError:
        return HTMLResponse(
            _page(
                request,
                "Enrollment not found",
                '<section class="not-found"><h1>Enrollment not found</h1><p>The record is unavailable for this local learner.</p></section>',
            ),
            status_code=404,
        )
    except ValueError:
        try:
            order = checkout.get_order_for_enrollment(subject, enrollment_id)
        except LookupError:
            return RedirectResponse("/orders", status_code=303)
        return RedirectResponse(f"/orders/{order['order_id']}", status_code=303)
    return RedirectResponse("/account/history", status_code=303)


@app.get(
    "/learn/neural-networks-deep-learning/lesson/{lesson_id}",
    response_class=HTMLResponse,
)
def learning_lesson(request: Request, lesson_id: str) -> HTMLResponse:
    try:
        lesson = learning_db.get_lesson(lesson_id)
    except LookupError:
        raise HTTPException(status_code=404) from None
    backend, auth, token, session = _request_session(request)
    if not session["authenticated"] and not lesson["preview"]:
        return _permission_page(request, "Sign in to open this lesson")
    subject = (
        str(session["account"]["subject_id"]) if session["authenticated"] else None
    )
    active_enrollment = bool(subject and learning_db.has_active_enrollment(subject))
    if not lesson["preview"] and not active_enrollment:
        return _enrollment_required_page(request, "Enroll locally to open this lesson")
    state = learning_db.learning_state(subject) if active_enrollment else None
    previous_link = (
        f'<a href="/learn/neural-networks-deep-learning/lesson/{escape(lesson["previous_lesson_id"])}">Previous lesson</a>'
        if lesson["previous_lesson_id"]
        else ""
    )
    next_link = (
        f'<a href="/learn/neural-networks-deep-learning/lesson/{escape(lesson["next_lesson_id"])}">Next lesson</a>'
        if lesson["next_lesson_id"]
        else ""
    )
    outline = "".join(
        f"<li><strong>{escape(module['title'])}</strong><ul>"
        + "".join(
            f'<li><a href="/learn/neural-networks-deep-learning/lesson/{escape(item["lesson_id"])}">{escape(item["title"])}</a></li>'
            for item in module["lessons"]
        )
        + "</ul></li>"
        for module in lesson["outline"]
    )
    learner_controls = ""
    if active_enrollment:
        bookmarked = lesson_id in state["bookmarks"]
        choices = "".join(
            f'<label><input type="radio" name="answer" value="{escape(choice)}" required>{escape(choice)}</label>'
            for choice in json.loads(str(lesson["quiz"]["choices_json"]))
        )
        learner_controls = f"""<div class="lesson-actions"><form action="/learning/bookmarks/{escape(lesson_id)}" method="post"><input type="hidden" name="bookmarked" value="{"0" if bookmarked else "1"}"><button type="submit">{"Remove bookmark" if bookmarked else "Bookmark lesson"}</button></form><form action="/learning/progress/{escape(lesson_id)}" method="post"><button type="submit">Mark complete</button></form></div><section><h2>{escape(lesson["quiz"]["title"])}</h2><p>{escape(lesson["quiz"]["question"])}</p><form class="auth-form" action="/learning/quizzes/{escape(lesson["quiz"]["quiz_id"])}" method="post">{choices}<button type="submit">Submit local quiz</button></form></section>"""
    else:
        learner_controls = '<p class="safe-note">Public offline preview. Sign in locally to save progress.</p>'
    body = f"""<nav class="breadcrumbs"><a href="/my-learning">My Learning</a><span>›</span>{escape(lesson["module_title"])}</nav><section class="lesson-layout"><aside><h2>Course outline</h2><ol>{outline}</ol></aside><article><p class="eyebrow">Module {lesson["module_position"]} of 3</p><h1>{escape(lesson["title"])}</h1><p>{escape(lesson["body"])}</p><nav>{previous_link} {next_link}</nav>{learner_controls}</article></section>"""
    response = HTMLResponse(_page(request, lesson["title"], body))
    _set_session_cookie(response, backend, token)
    return response


@app.post("/learning/bookmarks/{lesson_id}")
async def learning_bookmark(request: Request, lesson_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to save bookmarks")
    values = await _form_values(request)
    try:
        learning_db.set_bookmark(
            subject, lesson_id, bookmarked=values.get("bookmarked") == "1"
        )
    except LookupError:
        return _learning_not_found(request)
    return RedirectResponse(
        f"/learn/neural-networks-deep-learning/lesson/{lesson_id}", status_code=303
    )


@app.post("/learning/progress/{lesson_id}")
def learning_progress(request: Request, lesson_id: str) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to save progress")
    try:
        learning_db.complete_lesson(subject, lesson_id)
    except LookupError:
        return _learning_not_found(request)
    return RedirectResponse("/my-learning", status_code=303)


@app.post("/learning/quizzes/{quiz_id}", response_class=HTMLResponse)
async def learning_quiz(request: Request, quiz_id: str) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to submit a quiz")
    values = await _form_values(request)
    try:
        attempt = learning_db.submit_quiz(subject, quiz_id, values.get("answer", ""))
    except LookupError:
        return _learning_not_found(request)
    except ValueError as exc:
        return HTMLResponse(
            _page(
                request,
                "Quiz validation",
                f"<section class='not-found'><h1>Check your answer</h1><p>{escape(str(exc))}</p></section>",
            ),
            status_code=422,
        )
    body = f"""<section class="page-heading"><p class="eyebrow">本地测验反馈</p><h1>测验得分：{attempt["score"]}</h1><p>{escape(attempt["feedback"])}</p><a href="/my-learning">返回我的学习</a></section>"""
    return HTMLResponse(_page(request, "测验反馈", body))


@app.post("/learning/review")
async def learning_review(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to save an offline review")
    values = await _form_values(request)
    try:
        learning_db.upsert_review(
            subject,
            rating=int(values.get("rating", "0")),
            review_text=values.get("review_text", ""),
        )
    except LookupError:
        return _learning_not_found(request)
    except (ValueError, TypeError) as exc:
        return HTMLResponse(
            _page(
                request,
                "Review validation",
                f"<section class='not-found'><h1>Check your review</h1><p>{escape(str(exc))}</p></section>",
            ),
            status_code=422,
        )
    return RedirectResponse("/my-learning", status_code=303)


@app.get("/account/preferences", response_class=HTMLResponse)
def account_preferences(request: Request) -> HTMLResponse:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to manage learning preferences")
    preferences = learning_db.get_preferences(subject)
    checked = " checked" if preferences["email_updates"] else ""
    body = f"""<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">本地学习设置</p><h1>学习偏好</h1><form class="auth-form" action="/account/preferences" method="post"><label>语言<input name="language" value="{escape(preferences["language"])}" required></label><label>时区<input name="timezone" value="{escape(preferences["timezone"])}" required></label><label><input type="checkbox" name="email_updates" value="1"{checked}>本地学习提醒</label><button type="submit">保存偏好</button></form></div></section>"""
    return HTMLResponse(_page(request, "学习偏好", body))


@app.post("/account/preferences")
async def save_preferences(request: Request) -> Response:
    try:
        _backend, _auth, _token, subject = _authenticated_subject(request)
    except HTTPException:
        return _permission_page(request, "Sign in to manage learning preferences")
    values = await _form_values(request)
    try:
        learning_db.update_preferences(
            subject,
            language=values.get("language", ""),
            timezone=values.get("timezone", ""),
            email_updates=values.get("email_updates") == "1",
        )
    except ValueError as exc:
        return HTMLResponse(
            _page(
                request,
                "Preference validation",
                f"<section class='not-found'><h1>Check preferences</h1><p>{escape(str(exc))}</p></section>",
            ),
            status_code=422,
        )
    return RedirectResponse("/account/preferences", status_code=303)


@app.get("/account-recovery", response_class=HTMLResponse)
def account_recovery(request: Request) -> HTMLResponse:
    body = """<section class="auth-shell single"><div class="auth-card"><p class="eyebrow">账户访问</p><h1>重置您的 Coursera 密码</h1><p>不会发送外部重置消息。仅使用合成的 .test 地址；公开响应不会透露该地址是否存在。</p><form class="auth-form" action="/auth/recovery/start" method="post" autocomplete="off"><label>账户电子邮件<input type="email" name="address" placeholder="learner@coursera.test" required></label><p class="field-guidance">匹配的 site-33 本地账号只会在此浏览器的本地收件箱中收到验证码。</p><button type="submit">打开本地恢复流程</button></form><a href="/login">返回登录</a></div></section>"""
    return _session_html(request, "Password Recovery", body)


@app.post("/auth/recovery/start")
async def recovery_start(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        email = _synthetic_email(values.get("email", values.get("address", "")))
        auth.start_password_reset(token, email=email)
    except ValueError as exc:
        return _auth_failure(request, str(exc), status_code=422)
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=429)
    response = RedirectResponse("/local-inbox?purpose=password-reset", status_code=303)
    response.headers["X-Auth-Message"] = (
        "If a matching local account exists, a local verification message is available."
    )
    _set_session_cookie(response, backend, token)
    return response


@app.post("/auth/recovery/complete")
async def recovery_complete(request: Request) -> Response:
    backend, auth, token, _session = _request_session(request)
    values = await _form_values(request)
    try:
        auth.verify_password_reset_code(token, values.get("code", ""))
        new_token = auth.complete_password_reset(
            token,
            new_password=values.get("new_password", ""),
        )
    except AuthError as exc:
        return _auth_failure(request, str(exc), status_code=400)
    response = RedirectResponse("/my-learning", status_code=303)
    _set_session_cookie(response, backend, new_token)
    return response


@app.get("/help", response_class=HTMLResponse)
def help_center(request: Request) -> str:
    account_controls = (
        '<nav class="wb-account-nav"><a href="/my-learning">我的学习</a><form action="/auth/logout" method="post"><button type="submit">退出登录</button></form></nav>'
        if _request_authenticated(request)
        else '<nav class="wb-account-nav"><a href="/login">登录</a><a class="wb-join" href="/signup">免费加入</a></nav>'
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Learner Help Center | Coursera</title><link rel="stylesheet" href="/static/desktop-base.css"><link rel="stylesheet" href="/static/course-desktop.css"></head>
<body class="help-center-page"><header class="help-center-header"><a class="wb-wordmark" href="/">coursera</a><form action="/help" method="get" role="search"><label class="wb-sr-only" for="help-search">Search for help</label><input id="help-search" name="q" placeholder="Search for help"><button type="submit">⌕</button></form>{account_controls}</header>
<main class="help-article-shell"><nav class="help-breadcrumbs"><a href="/help">Learner Help Center</a><span>›</span><a href="/help#account">Account & notifications</a><span>›</span><span>Troubleshooting login and account issues</span></nav><article class="help-article"><h1>Troubleshooting login and account issues</h1><p><em>Reading time: 3 minutes</em></p><p>This article can help you troubleshoot:</p><ul><li>Login issues on Coursera.</li><li>Issues with verifying or changing your email.</li></ul><p>If you want to reset your password, see <a href="/account-recovery">Reset your Coursera password</a>.</p><p>If you are part of an organization’s learning program that uses single sign-on, use <a href="/login">single sign-on guidance to log in</a>.</p><aside class="help-skip"><strong>Skip to:</strong><ul><li><a href="#unable">Unable to log in</a><ul><li>Error message: “We couldn't find an account associated with that email address”</li><li>Log in using SSO</li></ul></li><li><a href="#email">Issues selecting images after log in</a></li><li><a href="#verify">I can't verify my email</a></li><li><a href="#change">Changes to your Coursera email</a></li></ul></aside><h2 id="unable">Unable to log in</h2><blockquote><p>If you’re having trouble logging in, follow these steps:</p></blockquote><ol><li>Double check your email address for misspellings. The email address must match exactly what you typed in when you signed up.</li><li>Use the steps in our article on <a href="/account-recovery">resetting your password</a>.</li><li>Return to <a href="/login">Coursera sign in</a> without submitting credentials here.</li></ol><h2 id="account">Account access and failed actions</h2><p><strong>账户访问</strong>、registration, password recovery, checkout errors and <strong>失败的操作</strong> are represented locally. No private account data is exposed.</p><p><a href="/browse">Browse course catalog</a> · <a href="/search">Search course catalog</a> · <a href="/about/contact">Contact support</a></p><section id="terms"><h2>Terms and privacy</h2><p>Continuing in this clone uses local WebsiteBench data only. No real email, payment, or Coursera account effect is produced.</p></section></article><aside class="help-floating"><strong>New! Search with AI</strong><button type="button">×</button><p>Ask a question and get an instant answer.</p></aside><aside class="help-feedback"><strong>Was this article helpful?</strong><button type="button">👍 Yes</button><button type="button">👎 No</button></aside></main></body></html>"""


@app.get("/about/contact", response_class=HTMLResponse)
def contact(request: Request) -> str:
    body = """<section class="page-heading contact-hero"><p class="eyebrow">Coursera support</p><h1>Contact Us</h1><p>Choose the local guidance area that best fits your question.</p></section><section class="support-grid"><article><h2>Learner Support</h2><p>Get local help with finding courses, previewing materials, and account-entry guidance.</p><a href="/help">Open learner help</a></article><article><h2>Inquiries</h2><p>General questions are represented as offline guidance only; no message is transmitted.</p><a href="/browse">Explore available learning</a></article><article><h2>Partnerships</h2><p>Business, university, and government contact actions are outside this offline scope.</p><a href="/">Return home</a></article></section>"""
    return _page(request, "Contact", body)
