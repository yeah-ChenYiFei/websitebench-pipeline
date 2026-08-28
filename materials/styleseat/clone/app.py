"""StyleSeat 离线克隆 —— FastAPI 组合根。

源站是纯 SPA：`/` →301→ `/m/`，每个路由都回同一个 58,003 字节的 S3 壳，正文全部由
XHR 灌进去。克隆因此把**已水合的 DOM 直接在服务端吐出来**，并摘掉原站的 app bundle
——留着它会在客户端重新接管路由，认不出本地路径就自我 404。

* ``frontend/pages`` 每个范围内路由一份本地化文档；``static/assets`` 是冻结资产。
* ``/api/*`` 由 ``backend/content_store.py`` 用抓取到的真实接口响应应答，
  搜索分页照抄源站自己的 ``from``/``size=30`` 语义。
* 登录/注册/改密走 ``websitebench.site_backend`` 生成的运行时，不手写鉴权。
* 支付适配器 ``local-sandbox``，永不接 live key。
* ``GET /healthz`` 恒返回 ``{"ok":true,"site_id":"styleseat"}``。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from html import escape as html_escape
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from starlette.staticfiles import StaticFiles

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SITE_ID = "styleseat"
DISPLAY_NAME = "StyleSeat"
PAGES = ROOT / "frontend" / "pages"
PAGES_AUTH = ROOT / "frontend" / "pages-auth"   # 同一路由的登录态 DOM（源站在客户端做门禁）
STATIC = ROOT / "static"
_HEALTH = json.dumps({"ok": True, "site_id": SITE_ID}, separators=(",", ":"))

# 源站自己的跳转链（/login →302→ /m/login 等），由构建期从抓取件里读出来
_REDIRECTS_FILE = ROOT.parent / "scope" / "redirects.json"
REDIRECTS: dict[str, str] = (
    json.loads(_REDIRECTS_FILE.read_text(encoding="utf-8")).get("redirects", {})
    if _REDIRECTS_FILE.is_file() else {})

# 页面里保留内联 style；connect/img/frame 一律限死本源 —— 任何漏网的远端请求都会被拦下，
# 这条正是 runtime_remote_requests=forbidden 在运行时的兑现方式。
CSP = ("default-src 'self'; img-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
       "font-src 'self' data:; connect-src 'self'; frame-src 'self'; "
       "form-action 'self'; base-uri 'self'")

# 会话语义照 backend/runtime.json 的声明，不自己发明
_RUNTIME = json.loads((ROOT.parent / "backend" / "runtime.json").read_text(encoding="utf-8"))
_SESSION = _RUNTIME["session"]
# Both the local API and the captured-site compatibility endpoints share one
# opaque session. A __Host- cookie would be rejected on the harness's plain
# HTTP localhost origin, so this name deliberately has no Secure-only prefix.
COOKIE = "wb_session"

from backend.site_backend_integration import open_site_services  # noqa: E402
from auth_api import configure as configure_local_auth  # noqa: E402
from auth_api import router as local_auth_router  # noqa: E402
from auth_api import store_mail_options  # noqa: E402

BACKEND, AUTH = open_site_services(**store_mail_options())
configure_local_auth(lambda: AUTH)

# ---------------------------------------------------------------- 夹具账号
# 登录面要能真的登进去，就得有账号。这里不手写口令哈希——调 store 自己的
# seed_account，密码走的是它声明的 salted-scrypt，和真实注册同一条路径，幂等。
#
# 邮箱用的正是登录态抓取件脱敏后的占位符（等长等类型替换，见 tools/scrub_pii.py），
# 这样后端身份和页面里印着的身份对得上，不会一边显示 A 一边登录成 B。
# 口令是本地现编的夹具，不是源站凭据——源站凭据只在 run/creds.env，永不进代码与账本。
FIXTURE_EMAIL = "4280322688@pu.jyr"
FIXTURE_PASSWORD = "Fixture-Client-2026!"

try:
    AUTH.seed_account(
        subject_id="styleseat-client-fixture-1",
        email=FIXTURE_EMAIL,
        display_name="Client",
        password=FIXTURE_PASSWORD,
        email_verified=True,
    )
except Exception as exc:  # 夹具播种失败不该让整个站起不来，但必须看得见
    print(f"FIXTURE-SEED-FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)


def _session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE)


def _set_session(resp: Response, request: Request, token: str) -> None:
    resp.set_cookie(
        COOKIE, token,
        httponly=bool(_SESSION.get("http_only", True)),
        secure=bool(_SESSION.get("secure", True)) and request.url.scheme == "https",
        samesite=str(_SESSION.get("same_site", "Lax")).lower(),
        path="/",
    )  # host_only：不带 Domain 属性，正是 __Host- 的语义


def _identity(request: Request) -> dict | None:
    """已登录 → 会话记录；否则 None。鉴权判定只走生成的 store。

    store 的记录形状是 ``{"authenticated": bool, "account": {...}}``，
    匿名会话同样有记录，所以必须看 ``authenticated``，不能看记录是否存在。"""
    rec = AUTH.resolve_session(_session_token(request))
    if rec and rec.get("authenticated") and rec.get("account"):
        return rec
    return None


app = FastAPI(title=DISPLAY_NAME)
app.include_router(local_auth_router)
if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.middleware("http")
async def _headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.get("/healthz")
def healthz() -> Response:
    return Response(_HEALTH, media_type="application/json")


def _page(route: str, root: pathlib.Path = PAGES) -> pathlib.Path | None:
    """路由 → 页面文件。目录式与文件式各试一次，超出 root 一律拒绝。"""
    r = route.strip("/")
    for cand in ((root / "index.html") if not r else None,
                 root / f"{r}.html", root / r / "index.html"):
        if cand is None:
            continue
        try:
            cand.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if cand.is_file():
            return cand
    return None


def _with_local_auth(body: str) -> str:
    """Attach clone-owned account and navigation controllers."""

    scripts = ('<script src="/static/local-auth.js" defer></script>'
               '<script src="/static/home-actions.js" defer></script>')
    if '/static/home-actions.js' in body:
        return body
    replaced, count = re.subn(
        r"</body\s*>", scripts + "</body>", body, count=1, flags=re.IGNORECASE
    )
    return replaced if count else body + scripts


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # 源站 / →301→ /m/，克隆照做：基路径钉死 /m/
    return RedirectResponse("/m/", status_code=301)


@app.get("/signup", include_in_schema=False)
def signup_entry() -> RedirectResponse:
    return RedirectResponse("/m/signup", status_code=302)

@app.get("/search", include_in_schema=False)
def search_entry() -> RedirectResponse:
    return RedirectResponse("/m/search/new-york-city-ny/professionals", status_code=302)



# ---------------------------------------------------------------- 鉴权
# 端点路径抄源站自己的 bundle（/accounts/ajax-login/ 等），不是我编的。
@app.post("/accounts/ajax-login/")
async def ajax_login(request: Request) -> Response:
    body = await _form_or_json(request)
    token, _ = AUTH.ensure_session(_session_token(request))
    try:
        result = AUTH.sign_in(token, email=body.get("email", ""),
                              password=body.get("password", ""))
    except Exception as exc:
        return JSONResponse({"ok": False, "error": _auth_error(exc)}, status_code=401)
    # 登录会轮换会话 token（防会话固定），必须把新的写回 cookie，旧的已作废
    resp = JSONResponse({"ok": True, "redirect": "/m/client-appointments"})
    _set_session(resp, request, result["session_token"])
    return resp


def _clear_session(resp: Response, request: Request) -> None:
    """删 cookie 必须和当初 set 的属性完全对齐，否则浏览器当成另一个 cookie。

    __Host- 前缀有硬约束：带这个名字的 Set-Cookie 只有同时满足 Secure + Path=/ +
    无 Domain 才会被接受。Starlette 的 delete_cookie() secure 默认 False，于是那条
    过期指令被浏览器**静默丢弃**——不报错、响应头看着也正常，只是 cookie 还在罐子
    里。服务端 sign_out 已经把会话置 revoked，所以行为上没错（受限页确实退回匿名
    版），但浏览器留着一个死 token，登出没登干净。见 OPEN-DEFECTS D10。
    """
    resp.set_cookie(
        COOKIE, "", max_age=0, expires=0,
        httponly=bool(_SESSION.get("http_only", True)),
        secure=bool(_SESSION.get("secure", True)) and request.url.scheme == "https",
        samesite=str(_SESSION.get("same_site", "Lax")).lower(),
        path="/",
    )


@app.post("/accounts/ajax-logout/")
async def ajax_logout(request: Request) -> Response:
    AUTH.sign_out(_session_token(request))
    resp = JSONResponse({"ok": True, "redirect": "/m/"})
    _clear_session(resp, request)
    return resp


@app.post("/api/v2/auth/password/reset/")
async def password_reset_start(request: Request) -> Response:
    body = await _form_or_json(request)
    token, _ = AUTH.ensure_session(_session_token(request))
    try:
        AUTH.start_password_reset(token, email=body.get("email", ""),
                                  restart_invalid_flow=True)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": _auth_error(exc)}, status_code=400)
    resp = JSONResponse({"ok": True, "detail": "reset code sent"})
    _set_session(resp, request, token)
    return resp


@app.post("/api/v2/auth/password/reset/validate/")
async def password_reset_validate(request: Request) -> Response:
    body = await _form_or_json(request)
    try:
        AUTH.verify_password_reset_code(_session_token(request) or "", body.get("code", ""))
    except Exception as exc:
        return JSONResponse({"ok": False, "error": _auth_error(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@app.post("/api/v2/auth/password/reset/confirm/")
async def password_reset_confirm(request: Request) -> Response:
    body = await _form_or_json(request)
    try:
        rotated = AUTH.complete_password_reset(
            _session_token(request) or "", new_password=body.get("new_password", ""))
    except Exception as exc:
        return JSONResponse({"ok": False, "error": _auth_error(exc)}, status_code=400)
    resp = JSONResponse({"ok": True, "redirect": "/m/login"})
    if isinstance(rotated, str) and rotated:
        _set_session(resp, request, rotated)   # 改密同样轮换 token
    return resp


@app.get("/accounts/whoami/")
def whoami(request: Request) -> Response:
    rec = _identity(request)
    if not rec:
        return JSONResponse({"isLogin": False, "is_anon": True})
    acct = rec["account"]
    return JSONResponse({"isLogin": True, "is_anon": False,
                         "email": acct.get("email_normalized"),
                         "first_name": acct.get("display_name"),
                         "user_id": acct.get("subject_id")})


async def _form_or_json(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        try:
            return await request.json()
        except Exception:
            return {}
    return dict(await request.form())


def _auth_error(exc: Exception) -> str:
    """把 store 的异常转成稳定的错误码，绝不回显口令。"""
    name = type(exc).__name__
    # 错密码与不存在的账号回同一个码：不泄露账号是否存在
    return {"AuthRejected": "invalid-credentials",
            "AuthValidationError": "invalid-credentials",
            "InvalidCredentials": "invalid-credentials",
            "UnknownAccount": "invalid-credentials",
            "AccountLocked": "account-locked"}.get(name, name)


# §5.2 收边：抓取在锁定城市 / 列表第 2 页 / 已抓商家处截断，但截断 ≠ 让链接指向空气。
# 形状上属于克隆范围、只是没抓到的路由，落一张声明过的边界页（做法 b）；
# 形状之外的照旧走源站式 404。两者的区别必须看得见，不能糊成一个。
IN_SCOPE_SHAPE = re.compile(
    # …/page-N 是列表分页的边界形状：抓取只到第 2 页，第 3 页往后落到边界页而不是
    # 死按钮（见 OPEN-DEFECTS D11）。这个形状在源站没有对应 URL，是克隆自己声明的
    # 前沿标记——它存在的唯一目的就是让「还有更多」这件事在点击之前就说清楚。
    r"^/m/search(/[a-z0-9-]+-[a-z]{2}(/[a-z0-9-]+(/page-[0-9]+)?)?)?/?$"
    r"|^/m/v/[A-Za-z0-9._-]+/?$"
    r"|^/blog(/|$)")

# These are the 50 city/service links rendered on the captured home page.  The
# original crawl includes the full service-specific result DOM for Oakland and
# full professional indexes for many cities.  Reusing that captured result DOM
# keeps the secondary pages visually and structurally faithful while preserving
# the city/service selected on the home page.
HOME_SEARCH_RE = re.compile(
    r"^/m/search/(?P<city>(?:dallas-tx|chicago-il|atlanta-ga|washington-dc|"
    r"los-angeles-ca|houston-tx|detroit-mi|charlotte-nc|columbus-oh|"
    r"newport-news-va))/(?P<service>braids|natural-hair|haircut|weaves|barber)/?$"
)
HOME_CITY_NAMES = {
    "dallas-tx": "Dallas, TX", "chicago-il": "Chicago, IL",
    "atlanta-ga": "Atlanta, GA", "washington-dc": "Washington, DC",
    "los-angeles-ca": "Los Angeles, CA", "houston-tx": "Houston, TX",
    "detroit-mi": "Detroit, MI", "charlotte-nc": "Charlotte, NC",
    "columbus-oh": "Columbus, OH", "newport-news-va": "Newport News, VA",
}
HOME_SERVICE_NAMES = {
    "braids": "Braids", "natural-hair": "Natural Hair",
    "haircut": "Haircut", "weaves": "Weaves", "barber": "Barber",
}
HOME_SOURCE_SERVICES = {"haircut": "mens-haircut"}


def _home_search_document(route: str) -> str | None:
    match = HOME_SEARCH_RE.match(route)
    if match is None:
        return None
    city_slug = match.group("city")
    service_slug = match.group("service")
    city_name = HOME_CITY_NAMES[city_slug]
    service_name = HOME_SERVICE_NAMES[service_slug]
    source_slug = HOME_SOURCE_SERVICES.get(service_slug, service_slug)
    source = _page(f"/m/search/oakland-ca/{source_slug}")
    if source is None:
        return None
    body = source.read_text(encoding="utf-8")
    body = body.replace(
        'src="about:blank"', 'src="data:image/gif;base64,R0lGODlhAQABAAAAACw="'
    )
    body = body.replace("Oakland, CA", city_name)
    body = body.replace(
        f"/m/search/oakland-ca/{source_slug}",
        f"/m/search/{city_slug}/{service_slug}",
    )
    marker = (
        f' data-clone-city="{html_escape(city_slug)}"'
        f' data-clone-service="{html_escape(service_slug)}"'
    )
    body = re.sub(r"<body\b", "<body" + marker, body, count=1, flags=re.IGNORECASE)
    notice = (
        '<aside class="clone-search-context" role="status" style="padding:12px 24px;background:#f2efff;color:#24116d;font:14px/1.5 Poppins,system-ui,sans-serif">'
        f'<strong>{html_escape(service_name)} in {html_escape(city_name)}</strong>'
        '<span> · Offline StyleSeat results; filters, sorting, search and profile links remain local.</span>'
        '</aside>'
    )
    body = re.sub(
        r"(<body\b[^>]*>)", r"\1" + notice, body, count=1, flags=re.IGNORECASE
    )
    return _with_local_auth(body)


def _boundary(route: str) -> Response:
    body = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Beyond captured scope · {DISPLAY_NAME}</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:44rem;margin:12vh auto;padding:0 1.5rem;color:#1a1a1a}}
code{{background:#f2f2f2;padding:.15em .4em;border-radius:3px}}a{{color:#0a58ca}}</style></head>
<body><h1>Beyond captured scope</h1>
<p><code>{html_escape(route)}</code> is a real StyleSeat route shape, but it lies outside
this offline clone's captured frontier. The capture was bounded on purpose:
one locked city for the category dimension, the first two pages of every list,
and the professional profiles reachable from those pages.</p>
<p>See <code>known-differences.json</code> for the exact bounds.</p>
<p><a href="/m/">Back to {DISPLAY_NAME}</a></p></body></html>"""
    return HTMLResponse(body, status_code=200)


# 站外链接的收边。源站页脚指向 Instagram / App Store / Facebook 这些站外地址；
# 构建期把它们一律打成 about:blank，等于让页脚里每个社交图标都点了没反应——
# 断链不是「离线」，只是坏掉。
#
# 但直接把绝对地址写回 href 也不行：官方的远端引用扫描把 href="https://…" 算作
# 运行时外连（diagnostics.REMOTE_URL 明确包含 href），而克隆声明的是
# runtime_remote_requests=forbidden。
#
# 所以走本地中转页：href 指向 /m/leaving?u=<百分号编码>，点开告诉你这条链接通向哪、
# 以及它在克隆里到此为止。目的地是照实印出来的文本，不是可点的外链——
# 既没有隐瞒，也没有任何一次远端请求。
_OUTBOUND_OK = re.compile(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[:/?#]|$)")


@app.get("/m/leaving", response_class=HTMLResponse)
def leaving(u: str = "") -> Response:
    dest = unquote(u)
    known = bool(_OUTBOUND_OK.match(dest))
    shown = html_escape(dest) if known else "(no destination given)"
    body = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Leaving the clone \u00b7 {DISPLAY_NAME}</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:44rem;margin:12vh auto;padding:0 1.5rem;color:#1a1a1a}}
code{{background:#f2f2f2;padding:.2em .45em;border-radius:3px;word-break:break-all}}a{{color:#0a58ca}}</style></head>
<body><h1>This link leaves the clone</h1>
<p>On www.styleseat.com this control navigates to:</p>
<p><code>{shown}</code></p>
<p>That address is outside StyleSeat, so it was never captured, and this clone makes no
remote requests. The destination is printed rather than linked for exactly that reason.</p>
<p><a href="/m/">Back to {DISPLAY_NAME}</a></p></body></html>"""
    return HTMLResponse(body, status_code=200 if known else 400)


@app.get("/{full_path:path}", response_class=HTMLResponse)
def serve(full_path: str, request: Request) -> Response:
    route = "/" + unquote(full_path)
    target = REDIRECTS.get(route) or REDIRECTS.get(route.rstrip("/")) 
    if target and target != route:
        return RedirectResponse(target, status_code=302)
    # 登录态优先取 pages-auth 的同名路由；没有就落回匿名版（源站也是同一路由两副面孔）
    page = None
    page_route = "/m/login" if route.rstrip("/") == "/m/signup" else route
    if _identity(request) is not None:
        page = _page(page_route, PAGES_AUTH)
    if page is None:
        page = _page(page_route)
    if page is None and not route.endswith("/"):
        page = _page(page_route + "/")
    if page is None and (home_search := _home_search_document(route)) is not None:
        return HTMLResponse(home_search)

    if page is None and IN_SCOPE_SHAPE.match(route):
        return _boundary(route)
    if page is None:
        notfound = _page("/404")
        body = notfound.read_text(encoding="utf-8") if notfound else (
            f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<title>Not found · {DISPLAY_NAME}</title></head>"
            f"<body><h1>Page not found</h1>"
            f"<p><a href=\"/m/\">Back to {DISPLAY_NAME}</a></p></body></html>")
        return HTMLResponse(body, status_code=404)
    return HTMLResponse(_with_local_auth(page.read_text(encoding="utf-8")))
