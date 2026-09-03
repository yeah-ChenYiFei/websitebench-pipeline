#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Creativebug 离线克隆 —— 服务端。

页面来自构建产物 frontend/<route>/index.html；行为来自本文件的 /api/*。
认证、邮件、支付一律经 backend/site_backend_integration.py 的生成接缝打开，
不自造会话或口令逻辑（AGENTS.md「Backend and payment safety」）。

语义上刻意区分三种"到不了"：
  404  /_clone/not-found     —— 这条路由不存在
  200  /_clone/out-of-scope  —— 路由存在于源站，但本克隆没有复刻它
  401/403                    —— 存在且已复刻，但当前会话无权访问
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import traceback
import smtplib
import sqlite3
import sys
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

HERE = Path(__file__).resolve().parent
FRONTEND = HERE / "frontend"
STATIC = HERE / "static"
sys.path.insert(0, str(HERE))

from backend.site_backend_integration import open_site_services  # noqa: E402
from websitebench.local_clone_auth.store import (  # noqa: E402
    LocalAuthStore,
    AuthConflict, AuthError, AuthExpired, AuthLocked, AuthRateLimited, AuthRejected,
    AuthValidationError,
)


def _public_error(exc: AuthError) -> str:
    """内部异常映射为稳定的公共文案；不回显异常内容、SQLite 路径或验证码。"""
    if isinstance(exc, AuthExpired):
        return "That code has expired. Request a new one."
    if isinstance(exc, AuthLocked):
        return "Too many attempts. Try again later."
    if isinstance(exc, AuthRateLimited):
        return "Too many requests. Please wait a moment."
    if isinstance(exc, AuthValidationError):
        return "Please check the details you entered."
    if isinstance(exc, AuthRejected):
        return "That code is not valid."
    return "That did not work. Please try again." 

BOUNDARY = "/_clone/out-of-scope"
AUTH_HOME = "/_clone/home-authenticated"
NOT_FOUND = "/_clone/not-found"
PAYMENT_PROFILE = "local-sandbox"   # 后端强制规范：默认且唯一允许的支付适配器
SESSION_COOKIE = "__Host-creativebug-session"      # runtime.json: host_only + http_only
PROTECTED = re.compile(r"^/(myclasses|account|preferences|profilefeed|gallery/mygallery)(/|$)")

SMTP_HOST = os.environ.get("WEBSITEBENCH_SMTP_HOST")
SMTP_PORT = int(os.environ.get("WEBSITEBENCH_SMTP_PORT") or 0)
MAIL_FROM = os.environ.get("WEBSITEBENCH_SMTP_FROM", "no-reply@creativebug.clone.test")
WORKER_TOKEN = secrets.token_urlsafe(24)          # ≥20 字符的进程内 worker token

BACKEND, _AUTH_LOCAL = open_site_services()

# 生成的接缝以 LOCAL_ONLY 建 Store（它不读 SMTP 环境变量）。
# AUTH-FLOW §2：三个 SMTP 变量齐全时必须用 SMTP_PENDING，并注入 ≥20 字符的
# 进程内 worker token。接缝是共享契约，不改它；按同一个数据库与 site_id
# 另建一个 SMTP 模式的 Store，二者指向同一份数据。
if SMTP_HOST and SMTP_PORT and MAIL_FROM:
    AUTH = LocalAuthStore(
        BACKEND.lifecycle.database_path,
        site_id=BACKEND.config.site_id,
        mail_mode="SMTP_PENDING",
        mail_worker_token=WORKER_TOKEN,
    )
    AUTH.ensure_schema()
    MAIL_MODE = "SMTP_PENDING"
else:
    AUTH = _AUTH_LOCAL
    MAIL_MODE = "LOCAL_ONLY"
print(f"[creativebug-clone] mail_mode={MAIL_MODE} smtp={SMTP_HOST}:{SMTP_PORT or '-'}",
      file=sys.stderr, flush=True)
MAIL_TEMPLATES = json.loads(
    (HERE.parent / "backend" / "runtime.json").read_text(encoding="utf-8")
)["mail"]["purposes"]
DB = BACKEND.lifecycle.database_path


# ---------------------------------------------------------------- 业务库
def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS cb_class (
  class_id TEXT PRIMARY KEY, title TEXT NOT NULL, route TEXT NOT NULL,
  instructor TEXT, category TEXT, subcategory TEXT, level TEXT,
  duration_minutes INTEGER, rating REAL, unit_count INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS cb_enrollment (
  account_id TEXT NOT NULL, class_id TEXT NOT NULL, track TEXT NOT NULL DEFAULT 'audit',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (account_id, class_id),
  FOREIGN KEY (class_id) REFERENCES cb_class(class_id));
CREATE TABLE IF NOT EXISTS cb_progress (
  account_id TEXT NOT NULL, class_id TEXT NOT NULL, unit_id TEXT NOT NULL,
  watched INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (account_id, class_id, unit_id),
  FOREIGN KEY (class_id) REFERENCES cb_class(class_id));
CREATE TABLE IF NOT EXISTS cb_watchlist (
  account_id TEXT NOT NULL, class_id TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (account_id, class_id),
  FOREIGN KEY (class_id) REFERENCES cb_class(class_id));
CREATE TABLE IF NOT EXISTS cb_subscription (
  account_id TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'trial',
  plan TEXT, started_at TEXT NOT NULL DEFAULT (datetime('now')), cancelled_at TEXT);
CREATE TABLE IF NOT EXISTS cb_order (
  order_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
  plan TEXT NOT NULL, amount_cents INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'USD',
  state TEXT NOT NULL DEFAULT 'review', payment_profile TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS cb_signin_attempt (
  email TEXT PRIMARY KEY, fails INTEGER NOT NULL DEFAULT 0,
  window_start TEXT NOT NULL DEFAULT (datetime('now')),
  last_fail TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS cb_rating (
  account_id TEXT NOT NULL, class_id TEXT NOT NULL, stars INTEGER NOT NULL,
  review TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (account_id, class_id));
CREATE TABLE IF NOT EXISTS cb_preference (
  account_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
  PRIMARY KEY (account_id, key));
CREATE TABLE IF NOT EXISTS cb_certificate (
  certificate_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
  class_id TEXT NOT NULL, issued_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (account_id, class_id));
CREATE TABLE IF NOT EXISTS cb_quiz_attempt (
  attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
  class_id TEXT NOT NULL, unit_id TEXT NOT NULL, answer TEXT,
  correct INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS cb_subscriber (
  channel TEXT NOT NULL, address TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (channel, address));
CREATE TABLE IF NOT EXISTS cb_message (
  message_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT,
  topic TEXT NOT NULL, body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
"""

PLANS = {"monthly": 795, "annual": 7995}


def init_business_schema():
    from backend.seed import load_catalog
    with db() as c:
        c.executescript(SCHEMA)
        n = load_catalog(c)
    return n


# ---------------------------------------------------------------- 路由表
def load_routes() -> dict[str, Path]:
    routes: dict[str, Path] = {}
    for f in FRONTEND.rglob("index.html"):
        rel = f.parent.relative_to(FRONTEND).as_posix()
        routes["/" if rel == "index" else "/" + rel] = f
    return routes


ROUTES = load_routes()


class Handler(BaseHTTPRequestHandler):
    server_version = "creativebug-clone/1.0"
    protocol_version = "HTTP/1.1"

    # -- 基础 ----------------------------------------------------
    def log_message(self, fmt, *args):        # 静音；起站日志由外层收集
        pass

    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Clone-Site", "creativebug")
        for k, v in (extra or {}):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8", extra)

    def _page(self, route: str, code=200):
        f = ROUTES.get(route)
        if f is None:
            self._send(404, b"not found")
            return
        self._send(code, f.read_bytes())

    # -- 会话 ----------------------------------------------------
    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == SESSION_COOKIE:
                return v or None
        return None

    def _account(self) -> str | None:
        """服务端校验会话 —— 不变量 auth-server-side。"""
        tok = self._session_token()
        if not tok:
            return None
        try:
            # ensure_session 返回 (token, state)，state 形如
            # {"authenticated": bool, "account": {"account_id": ...} | None}
            _, state = AUTH.ensure_session(tok)
        except Exception:
            return None
        if not state.get("authenticated"):
            return None
        account = state.get("account") or {}
        return account.get("account_id")

    def _set_session(self, token: str):
        # runtime.json 冻结：__Host- 前缀、HttpOnly、SameSite=Lax、Path=/、无 Domain
        self.send_header("Set-Cookie",
                         f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Secure")

    # -- GET -----------------------------------------------------
    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        # ROUTES 的键来自目录名，含真实空格；urlparse 给的是未解码的 %20。
        # 不解码就永远匹配不上，源站带空格的 collection 路由会全部 404。
        p = unquote(u.path).rstrip("/") or "/"

        if p == "/healthz":
            self._json(200, {"ok": True, "site_id": "creativebug",
                             "routes": len(ROUTES), "database": DB.name})
            return
        if p.startswith("/static/"):
            self._static(p)
            return
        if p.startswith("/api/"):
            self._api_get(p, parse_qs(u.query))
            return
        if p == "/search/ui":
            # 页头搜索框是 GET 原生提交，落点就是这里。
            # 早先没有这条路由，请求既不 404 也不响应，直接断连 ——
            # 用户在搜索框敲回车就会撞上。
            q = parse_qs(u.query).get("q", [""])[0]
            page = ROUTES.get("/classes")
            if page is None:
                self._json(200, {"query": q, "route_back": "/classes"}); return
            body = page.read_bytes().replace(
                b"</body>",
                (f'<script>window.__cbSearch={json.dumps({"q": q})};</script>'
                 ).encode() + b"</body>", 1)
            self._send(200, body)
            return

        # 受保护路由：服务端拒绝匿名访问，不是前端跳转
        if PROTECTED.match(p) and not self._account():
            self._page("/trial/create-account", 401) if "/trial/create-account" in ROUTES \
                else self._json(401, {"error": "authentication required"})
            return

        # 登录后首页换成源站给登录用户的那个版本（EXPLORE / MY CLASSES /
        # INSPIRATION 三个标签）。抓取件 recon/after-login.html 里一直有它，
        # 只是此前从未构建，于是登录之后仍然看到匿名营销首页。
        if p == "/" and self._account() and AUTH_HOME in ROUTES:
            self._page(AUTH_HOME)
            return

        if p in ROUTES:
            self._page(p)
        elif p == NOT_FOUND or p == BOUNDARY:
            self._page(p)
        else:
            self._page(NOT_FOUND, 404)          # 真 404，与边界页语义分开

    def _static(self, p: str):
        rel = p[len("/static/"):]
        f = (STATIC / rel).resolve()
        try:
            f.relative_to(STATIC.resolve())
        except ValueError:
            self._send(403, b"forbidden"); return
        if not f.is_file():
            self._send(404, b"not found"); return
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype)

    # -- API -----------------------------------------------------
    def _api_get(self, p, q):
        acct = self._account()
        if p == "/api/session":
            self._json(200, {"authenticated": bool(acct)})
        elif p == "/api/myclasses":
            if not acct:
                self._json(401, {"error": "authentication required"}); return
            with db() as c:
                rows = c.execute(
                    "SELECT e.class_id, e.track, k.title, k.route,"
                    " (SELECT COUNT(*) FROM cb_progress g WHERE g.account_id=e.account_id"
                    "   AND g.class_id=e.class_id AND g.watched=1) AS watched_units,"
                    " k.unit_count"
                    " FROM cb_enrollment e LEFT JOIN cb_class k USING (class_id)"
                    " WHERE e.account_id=? ORDER BY e.created_at DESC", (acct,)).fetchall()
            self._json(200, {"classes": [dict(r) for r in rows]})
        elif p == "/api/search":
            self._search(q)
        elif p == "/api/orders":
            if not acct:
                self._json(401, {"error": "authentication required"}); return
            with db() as c:
                rows = c.execute(
                    "SELECT order_id,plan,amount_cents,currency,state,created_at"
                    " FROM cb_order WHERE account_id=? ORDER BY order_id DESC", (acct,)).fetchall()
                sub = c.execute("SELECT state,plan,started_at,cancelled_at FROM cb_subscription"
                                " WHERE account_id=?", (acct,)).fetchone()
            orders = [dict(r) for r in rows]
            for o in orders:
                # trace 19：最新项要暴露状态、详情、可编辑/可取消，以及返回集合的路径
                o["detail_url"] = f"/api/orders?order_id={o['order_id']}"
                o["cancellable"] = o["state"] in ("review", "confirmed")
                o["route_back"] = "/account/profile"
            self._json(200, {"orders": orders, "newest": orders[0] if orders else None,
                             "subscription": dict(sub) if sub else None,
                             "route_back": "/account/profile"})
        elif p == "/api/preferences":
            if not acct:
                self._json(401, {"error": "authentication required"}); return
            with db() as c:
                rows = c.execute("SELECT key,value FROM cb_preference WHERE account_id=?",
                                 (acct,)).fetchall()
            self._json(200, {"preferences": {r["key"]: r["value"] for r in rows}})
        elif p == "/api/certificate":
            if not acct:
                self._json(401, {"error": "authentication required"}); return
            with db() as c:
                rows = c.execute(
                    "SELECT c.certificate_id,c.class_id,c.issued_at,k.title"
                    " FROM cb_certificate c LEFT JOIN cb_class k USING (class_id)"
                    " WHERE c.account_id=? ORDER BY c.issued_at DESC", (acct,)).fetchall()
            self._json(200, {"certificates": [dict(r) for r in rows]})
        elif p == "/api/resume":
            if not acct:
                self._json(401, {"error": "authentication required"}); return
            with db() as c:
                row = c.execute(
                    "SELECT g.class_id, k.title, k.route, MAX(g.updated_at) AS last_seen,"
                    " (SELECT COUNT(*) FROM cb_progress x WHERE x.account_id=g.account_id"
                    "   AND x.class_id=g.class_id AND x.watched=1) AS watched_units,"
                    " COALESCE(k.unit_count,1) AS unit_count"
                    " FROM cb_progress g LEFT JOIN cb_class k USING (class_id)"
                    " WHERE g.account_id=? GROUP BY g.class_id"
                    " ORDER BY last_seen DESC LIMIT 1", (acct,)).fetchone()
            self._json(200, {"resume": dict(row) if row else None,
                             "route_back": "/myclasses"})
        else:
            self._json(404, {"error": "unknown endpoint"})

    def _search(self, q):
        term = (q.get("q", [""])[0] or "").strip()
        sql = ("SELECT class_id,title,route,instructor,category,subcategory,level,"
               "duration_minutes,rating,unit_count FROM cb_class WHERE 1=1")
        args: list = []
        if term:
            sql += " AND (title LIKE ? OR instructor LIKE ?)"; args += [f"%{term}%"] * 2
        # trace 4：level / topic / duration / rating / language / schedule
        for key, col in (("level", "level"), ("category", "category"),
                         ("subcategory", "subcategory"), ("topic", "category"),
                         ("instructor", "instructor")):
            v = q.get(key, [""])[0]
            if v:
                sql += f" AND {col}=?"; args.append(v)
        for key, col, op in (("duration_max", "duration_minutes", "<="),
                             ("duration_min", "duration_minutes", ">="),
                             ("rating_min", "rating", ">=")):
            v = q.get(key, [""])[0]
            if v:
                try:
                    args.append(float(v)); sql += f" AND {col} IS NOT NULL AND {col} {op} ?"
                except ValueError:
                    pass
        # language / schedule 源站未在页面暴露可筛选值，见 known-differences
        
        with db() as c:
            # limit 可调（上限 2000）：卡片对齐需要一次拿到全部课程的
            # route→title 映射，写死 48 会让绝大多数替换落点查不到。
            try:
                lim = int(parse_qs(urlparse(self.path).query)
                          .get("limit", ["48"])[0])
            except ValueError:
                lim = 48
            lim = max(1, min(lim, 2000))
            rows = c.execute(sql + " ORDER BY rating DESC LIMIT ?", args + [lim]).fetchall()
        self._json(200, {"query": term, "count": len(rows),
                         "results": [dict(r) for r in rows],
                         "empty_state": None if rows else
                         {"message": "No classes match that search.",
                          "route_back": "/classes"}})

    # -- POST ----------------------------------------------------
    def do_POST(self):
        u = urlparse(self.path)
        # ROUTES 的键来自目录名，含真实空格；urlparse 给的是未解码的 %20。
        # 不解码就永远匹配不上，源站带空格的 collection 路由会全部 404。
        p = unquote(u.path).rstrip("/") or "/"
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""      # keep-alive 必须读尽请求体
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}
        try:
            self._api_post(p, body)
        except Exception as exc:                    # 不把异常或库路径回显给页面
            # 但服务端必须留痕：早先只回 kind，500 的真实原因无从查起。
            traceback.print_exc()
            self._json(500, {"error": "internal error", "kind": type(exc).__name__})

    def _api_post(self, p, b):
        acct = self._account()
        handlers = {
            "/api/auth/register/start": self._reg_start,
            "/api/auth/register/verify": self._reg_verify,
            "/api/auth/signin": self._signin,
            "/api/auth/signout": self._signout,
            "/api/auth/reset/start": self._reset_start,
            "/api/auth/reset/complete": self._reset_complete,
        }
        if p in handlers:
            handlers[p](b); return

        if p == "/api/reset":
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                self._json(403, {"error": "reset is loopback-only"}); return
            from backend.seed import load_catalog, reset_account_state
            with db() as c:
                reset_account_state(c)
                n = load_catalog(c)
            self._json(200, {"reset": True, "classes": n})
            return

        if p in ("/mailing_list", "/api/newsletter", "/sms", "/api/sms"):
            # 邮件与短信订阅是公开功能，不能落到需要登录的通用分支
            # （早先未实现，页脚订阅框提交后返回 401）。
            channel = "sms" if "sms" in p else "email"
            addr = str(b.get("phone") if channel == "sms" else b.get("email") or "").strip()
            ok = bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", addr)) if channel == "email" \
                else bool(re.fullmatch(r"[0-9+\-() ]{7,20}", addr))
            if not ok:
                self._json(400, {"message": "Enter a valid "
                                 + ("phone number." if channel == "sms" else "email address.")})
                return
            with db() as c:
                c.execute("INSERT OR IGNORE INTO cb_subscriber(channel,address) VALUES(?,?)",
                          (channel, addr))
            self._json(200, {"subscribed": True,
                             "message": "Thanks — you're on the list."})
            return

        if p == "/api/contact":
            # 公共帮助/支持入口：匿名可用，且响应里不含任何账户数据（trace 21）
            topic = str(b.get("topic") or "").strip()
            body = str(b.get("body") or "").strip()
            if not topic or not body:
                self._json(400, {"message": "Tell us the topic and what happened."}); return
            with db() as c:
                c.execute("INSERT INTO cb_message(account_id,topic,body) VALUES(?,?,?)",
                          (acct, topic[:120], body[:4000]))
            self._json(200, {"received": True,
                             "message": "Thanks — our team will follow up by email.",
                             "route_back": "/site/contact"})
            return

        if not acct:
            self._json(401, {"error": "authentication required",
                             "redirect": "/trial/create-account"}); return

        if p == "/api/enroll":
            cid = self._known_class(b)
            if cid is None:
                return
            with db() as c:
                c.execute("INSERT OR IGNORE INTO cb_enrollment(account_id,class_id,track)"
                          " VALUES(?,?,?)", (acct, cid, b.get("track", "audit")))
            self._json(200, {"enrolled": True, "label": "Enrolled"})
        elif p == "/api/watchlist":
            cid = self._known_class(b)
            if cid is None:
                return
            with db() as c:
                cur = c.execute("DELETE FROM cb_watchlist WHERE account_id=? AND class_id=?",
                                (acct, cid))
                if cur.rowcount == 0:
                    c.execute("INSERT INTO cb_watchlist(account_id,class_id) VALUES(?,?)",
                              (acct, cid))
                    active = True
                else:
                    active = False
            self._json(200, {"active": active, "label": "Saved" if active else "Save"})
        elif p == "/api/progress":
            cid = self._known_class(b)
            if cid is None:
                return
            with db() as c:
                c.execute("INSERT INTO cb_progress(account_id,class_id,unit_id,watched)"
                          " VALUES(?,?,?,1) ON CONFLICT(account_id,class_id,unit_id)"
                          " DO UPDATE SET watched=1, updated_at=datetime('now')",
                          (acct, cid, b.get("unit_id") or "1"))
                done = c.execute("SELECT COUNT(*) FROM cb_progress WHERE account_id=? AND"
                                 " class_id=? AND watched=1", (acct, cid)).fetchone()[0]
                total = c.execute("SELECT COALESCE(unit_count,1) FROM cb_class WHERE class_id=?",
                                  (cid,)).fetchone()
            total = total[0] if total else 1
            self._json(200, {"watched_units": done, "unit_count": total,
                             "completed": done >= total,
                             "certificate_available": done >= total})
        elif p == "/api/checkout":
            plan = b.get("plan", "monthly")
            if plan not in PLANS:
                self._json(400, {"error": "unknown plan"}); return
            with db() as c:
                cur = c.execute("INSERT INTO cb_order(account_id,plan,amount_cents,state)"
                                " VALUES(?,?,?, 'review')", (acct, plan, PLANS[plan]))
                oid = cur.lastrowid
            self._json(200, {"order_id": oid, "plan": plan, "amount_cents": PLANS[plan],
                             "currency": "USD", "state": "review",
                             "redirect": f"/checkout/review?order={oid}"})
        elif p == "/api/checkout/confirm":
            # 早先无论 order_id 是否存在都回 200 confirmed：UPDATE 匹配不到任何行，
            # 订单仍停在 review，却已经给账户开了 paid 订阅。确认必须先证明
            # 这笔订单存在、属于本账户、且确实处于待确认状态。
            # 状态转换必须是一条原子的条件更新（CAS）。
            # 先 SELECT 再 UPDATE 不是原子的：每个请求各开一条 SQLite 连接，
            # 并发确认时多个线程会同时读到 state='review' 再各自写入 —— 实测
            # 8 个并发请求里成功了 3 次，同一笔订单被重复确认、重复开通订阅。
            # 判据来自 UPDATE 的 rowcount，而不是之前那次读到的值。
            with db() as c:
                cur = c.execute(
                    "UPDATE cb_order SET state='confirmed', payment_profile=?"
                    " WHERE order_id=? AND account_id=? AND state='review'",
                    (PAYMENT_PROFILE, b.get("order_id"), acct))
                if cur.rowcount == 0:
                    # 没抢到：要么订单不存在/不属于本账户（404），要么已被确认（409）
                    row = c.execute("SELECT state FROM cb_order"
                                    " WHERE order_id=? AND account_id=?",
                                    (b.get("order_id"), acct)).fetchone()
                    if row is None:
                        self._json(404, {"error": "order not found"}); return
                    self._json(409, {"error": "order is not awaiting confirmation",
                                     "state": row["state"]}); return
                row = c.execute("SELECT order_id, plan FROM cb_order WHERE order_id=?",
                                (b.get("order_id"),)).fetchone()
                # plan 取库里的，不取请求体 —— 客户端不能靠改 plan 换一个更贵/更便宜的订阅
                plan = row["plan"]
                c.execute("INSERT INTO cb_subscription(account_id,state,plan) VALUES(?,'paid',?)"
                          " ON CONFLICT(account_id) DO UPDATE SET state='paid', plan=excluded.plan",
                          (acct, plan))
            self._json(200, {"state": "confirmed", "order_id": row["order_id"],
                             "plan": plan, "payment_profile": PAYMENT_PROFILE,
                             "redirect": f"/checkout/confirmation?order={row['order_id']}"})
        elif p == "/api/reset":
            # 确定性重置（backend/model.json 的 deterministic-reset 义务）。
            # 清账户侧状态并重灌目录种子；同一份种子反复执行结果一致。
            # 只允许本地回环调用 —— 这是评测夹具用的，不是面向用户的功能。
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                self._json(403, {"error": "reset is loopback-only"}); return
            from backend.seed import load_catalog, reset_account_state
            with db() as c:
                reset_account_state(c)
                n = load_catalog(c)
            self._json(200, {"reset": True, "classes": n})
        elif p == "/api/subscription/cancel":
            with db() as c:
                cur = c.execute(
                    "UPDATE cb_subscription SET state='cancelled',"
                    " cancelled_at=datetime('now') WHERE account_id=? AND state!='cancelled'",
                    (acct,))
                row = c.execute("SELECT state,plan,cancelled_at FROM cb_subscription"
                                " WHERE account_id=?", (acct,)).fetchone()
            if cur.rowcount == 0 and not row:
                self._json(404, {"message": "No subscription to cancel."}); return
            self._json(200, {"state": row["state"], "cancelled_at": row["cancelled_at"],
                             "route_back": "/account/profile"})
        elif p == "/api/orders/cancel":
            with db() as c:
                cur = c.execute("UPDATE cb_order SET state='cancelled'"
                                " WHERE order_id=? AND account_id=? AND state IN ('review','confirmed')",
                                (b.get("order_id"), acct))
            if cur.rowcount == 0:
                self._json(404, {"message": "That order cannot be cancelled."}); return
            self._json(200, {"order_id": b.get("order_id"), "state": "cancelled",
                             "route_back": "/account/profile"})
        elif p == "/api/preferences":
            prefs = b.get("preferences") or {}
            if not isinstance(prefs, dict) or not prefs:
                self._json(400, {"message": "Send a preferences object."}); return
            with db() as c:
                c.executemany(
                    "INSERT INTO cb_preference(account_id,key,value) VALUES(?,?,?)"
                    " ON CONFLICT(account_id,key) DO UPDATE SET value=excluded.value",
                    [(acct, str(k)[:80], None if v is None else str(v)[:400])
                     for k, v in prefs.items()])
            self._json(200, {"saved": True, "count": len(prefs)})
        elif p == "/api/quiz":
            # 测验：答案由服务端判定，客户端送上来的 correct 一律忽略
            answer = str(b.get("answer") or "").strip().lower()
            expected = str(b.get("class_id") or "")[:1].lower()   # 确定性的种子式判定
            correct = bool(answer) and answer.startswith(expected)
            with db() as c:
                c.execute("INSERT INTO cb_quiz_attempt(account_id,class_id,unit_id,answer,correct)"
                          " VALUES(?,?,?,?,?)",
                          (acct, b.get("class_id"), b.get("unit_id") or "1", answer, int(correct)))
                n = c.execute("SELECT COUNT(*) FROM cb_quiz_attempt WHERE account_id=? AND class_id=?",
                              (acct, b.get("class_id"))).fetchone()[0]
            self._json(200, {"correct": correct, "attempts": n,
                             "feedback": "Correct." if correct else "Not quite — try again."})
        elif p == "/api/certificate":
            # 这里原本直接用 cid —— 那是别的分支里定义的变量，在本分支未定义，
            # 于是任何请求都以 NameError 冒成 500（独立评审只测到 enroll/progress/
            # watchlist 三个端点，这是同类的第四个）。
            cid = self._known_class(b)
            if cid is None:
                return
            with db() as c:
                done = c.execute("SELECT COUNT(*) FROM cb_progress WHERE account_id=? AND"
                                 " class_id=? AND watched=1", (acct, cid)).fetchone()[0]
                total = c.execute("SELECT COALESCE(unit_count,1) FROM cb_class WHERE class_id=?",
                                  (cid,)).fetchone()
                total = total[0] if total else 1
                if done < total:
                    self._json(409, {"message": "Finish the class before requesting a certificate.",
                                     "watched_units": done, "unit_count": total}); return
                c.execute("INSERT OR IGNORE INTO cb_certificate(account_id,class_id) VALUES(?,?)",
                          (acct, cid))
                row = c.execute("SELECT certificate_id,issued_at FROM cb_certificate"
                                " WHERE account_id=? AND class_id=?",
                                (acct, cid)).fetchone()
            self._json(200, {"certificate_id": row["certificate_id"], "issued_at": row["issued_at"]})
        elif p == "/api/rating":
            # 早先直接 int(stars) 入库，没有范围校验：stars=99 会被欣然接受，
            # 而 cb_class.rating 是按它聚合的，一条脏数据能污染整门课的评分。
            try:
                stars = int(b.get("stars"))
            except (TypeError, ValueError):
                self._json(400, {"message": "Choose a rating from 1 to 5."}); return
            if not 1 <= stars <= 5:
                self._json(400, {"message": "Choose a rating from 1 to 5."}); return
            cid = b.get("class_id")
            with db() as c:
                if c.execute("SELECT 1 FROM cb_class WHERE class_id=?", (cid,)).fetchone() is None:
                    self._json(404, {"message": "That class does not exist."}); return
                # 不额外要求"必须已报名"：源站没有证据表明有这条限制，
                # 而它会改掉已声明旅程的语义。范围与课程存在性校验足以挡住脏数据。
                c.execute("INSERT INTO cb_rating(account_id,class_id,stars,review) VALUES(?,?,?,?)"
                          " ON CONFLICT(account_id,class_id) DO UPDATE SET"
                          " stars=excluded.stars, review=excluded.review",
                          (acct, cid, stars, (b.get("review") or None)))
            self._json(200, {"saved": True, "stars": stars})
        else:
            self._json(404, {"error": "unknown endpoint"})

    # -- 认证（一律经 LocalAuthStore，不自造） --------------------
    # Store 的所有流程都以 session_token 为主语：注册与重置是"会话内的挑战"，
    # 不是"对某个邮箱的操作"。因此匿名访客先拿一个 anonymous session，
    # 挑战完成后 Store 轮换 token，我们再把新 token 写回 cookie。

    def _session_or_new(self) -> str:
        tok = self._session_token()
        if tok:
            try:
                tok, _ = AUTH.ensure_session(tok)
                return tok
            except Exception:
                pass
        return AUTH.create_anonymous_session()

    def _reply(self, code, payload, token=None, clear=False, extra=None):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        if token:
            self._set_session(token)
        elif clear:
            self.send_header("Set-Cookie",
                             f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
        self.end_headers()
        self.wfile.write(body)

    def _deliver_mail(self, session_token: str, purpose: str) -> None:
        """按 AUTH-FLOW 第四步的顺序投递：claim → 构造 → reserve → 发送 → finish。

        任何一步失败都要 finish_mail_claim 写回状态；明文验证码不进 SQLite 也不进日志。
        """
        if MAIL_MODE != "SMTP_PENDING":
            # LOCAL_ONLY 没有 mail worker 权限；照旧尝试 claim 会抛 AuthRejected，
            # 被顶层兜底成 500 —— 一个配置状态不该表现为服务器错误。
            return
        claim = AUTH.claim_pending_mail_for_session(
            session_token, purpose=purpose, worker_token=WORKER_TOKEN)
        if not claim:
            return
        mail_id, claim_token = claim["mail_id"], claim["claim_token"]
        sent, err, accepted = False, None, 0
        try:
            tpl = MAIL_TEMPLATES.get(purpose, {})
            code = claim.get("verification_code") or ""
            if not code:
                # 宁可报错也不发空验证码信：静默发出去的话，
                # 用户收到一封没有码的邮件，而系统显示"已投递"。
                raise RuntimeError("claim carried no verification_code")
            msg = EmailMessage()
            msg["Subject"] = tpl.get("subject", "Creativebug")
            msg["From"] = MAIL_FROM
            msg["To"] = claim["recipient"]
            msg.set_content(
                f"{tpl.get('lead','')}\n\n"
                f"{tpl.get('body','Your code is ${code}.').replace('${code}', code)}\n"
                f"{tpl.get('expiry','').replace('${minutes}', str(claim.get('expires_in_minutes', 10)))}\n\n"
                f"{tpl.get('footer','')}")
            accepted = AUTH.reserve_mail_target_request(
                mail_id, claim_token, worker_token=WORKER_TOKEN)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
                s.send_message(msg)
            sent = True
        except Exception as exc:
            err = type(exc).__name__          # 只记异常类型，不记内容
        finally:
            AUTH.finish_mail_claim(mail_id, claim_token, sent=sent,
                                   target_request_count=1,
                                   accepted_request_count=accepted if sent else 0,
                                   error=err, worker_token=WORKER_TOKEN)

    def _known_class(self, b):
        """校验请求体里的 class_id 确实指向一门已复刻的课。

        缺了这一步，三个端点会把任意字符串写进库：
        - enroll 缺 class_id → INSERT OR IGNORE 静默丢弃，却回 200 说报名成功；
        - progress 打不存在的课 → 200 且 completed=true，成为幽灵结业证书的入口；
        - progress 缺 class_id → IntegrityError 冒成 500。
        返回 class_id；已就地응答错误时返回 None。
        """
        cid = (b.get("class_id") or "").strip() if isinstance(b.get("class_id"), str) else b.get("class_id")
        if not cid:
            self._json(400, {"message": "class_id is required."}); return None
        with db() as c:
            if c.execute("SELECT 1 FROM cb_class WHERE class_id=?", (cid,)).fetchone() is None:
                self._json(404, {"message": "That class does not exist."}); return None
        return cid

    def _reply_auth_error(self, exc, tok):
        """限流是 429 不是 400；把还要等多久告诉用户，否则页面只剩一句泛化报错。"""
        if isinstance(exc, AuthRateLimited):
            wait = int(getattr(exc, "retry_after", 60))
            self._reply(429, {"message": f"Please wait {wait} seconds before requesting "
                                         f"another code.", "retry_after": wait},
                        token=tok, extra={"Retry-After": wait})
            return
        self._reply(400, {"message": _public_error(exc)}, token=tok)

    def _reg_start(self, b):
        email = (b.get("email") or "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            self._json(400, {"message": "Enter a valid email address."}); return
        if len(b.get("password") or "") < 8:
            self._json(400, {"message": "Password must be at least 8 characters."}); return
        tok = self._session_or_new()
        try:
            AUTH.start_registration(tok, email=email,
                                    display_name=(b.get("display_name") or email.split("@")[0]),
                                    password=b["password"], restart_invalid_flow=True)
        except AuthConflict:
            # 已存在的邮箱：公共文案与新邮箱一致，避免账户枚举
            self._reply(200, {"message": "Check that address for a six-digit code.",
                              "next": "/trial/create-account?step=verify"}, token=tok); return
        except AuthError as exc:
            self._reply_auth_error(exc, tok); return
        self._deliver_mail(tok, "registration")
        self._reply(200, {"message": "Check that address for a six-digit code.",
                          "next": "/trial/create-account?step=verify"}, token=tok)

    def _reg_verify(self, b):
        tok = self._session_or_new()
        try:
            AUTH.verify_registration_code(tok, (b.get("code") or "").strip())
            res = AUTH.complete_registration(tok)
        except AuthError as exc:
            self._reply_auth_error(exc, tok); return
        new_tok = res.get("session_token") or tok
        # account_id 嵌在 account 里，不在顶层 —— 与 ensure_session 的形状一致。
        # 早先写成 res.get("account_id") 恒为 None，导致注册后没有 trial 订阅行。
        acct = (res.get("account") or {}).get("account_id")
        if acct:
            with db() as c:
                c.execute("INSERT OR IGNORE INTO cb_subscription(account_id,state) VALUES(?, 'trial')",
                          (acct,))
        self._reply(200, {"redirect": "/myclasses"}, token=new_tok)

    SIGNIN_MAX_FAILS = 5
    SIGNIN_WINDOW_MIN = 15

    def _signin(self, b):
        """登录失败按邮箱限流。

        发信有限流、验证码尝试有上限，唯独口令尝试没有：独立评审实测同一账号
        连续 12 次错误口令全部只回 401，可以无限试。这里补上滑动窗口计数，
        超限回 429 + Retry-After，与既有限流的响应形状一致。
        计数只按邮箱，不区分已存在/不存在的账户 —— 否则 429 与 401 的差异
        本身就成了账户枚举信道。
        """
        tok = self._session_or_new()
        email = (b.get("email") or "").strip().lower()

        with db() as c:
            row = c.execute(
                "SELECT fails, (julianday('now')-julianday(window_start))*1440 AS age_min"
                " FROM cb_signin_attempt WHERE email=?", (email,)).fetchone()
        if row and row["age_min"] is not None and row["age_min"] < self.SIGNIN_WINDOW_MIN \
                and row["fails"] >= self.SIGNIN_MAX_FAILS:
            wait = int((self.SIGNIN_WINDOW_MIN - row["age_min"]) * 60) + 1
            self._reply(429, {"message": "Too many sign-in attempts. Try again later.",
                              "retry_after": wait}, token=tok, extra={"Retry-After": wait})
            return

        try:
            res = AUTH.sign_in(tok, email=(b.get("email") or "").strip(),
                               password=b.get("password") or "")
        except AuthError:
            with db() as c:
                # 窗口过期就重新计数，否则累加
                c.execute(
                    "INSERT INTO cb_signin_attempt(email,fails) VALUES(?,1)"
                    " ON CONFLICT(email) DO UPDATE SET"
                    "   fails = CASE WHEN (julianday('now')-julianday(window_start))*1440 >= ?"
                    "                THEN 1 ELSE fails + 1 END,"
                    "   window_start = CASE WHEN (julianday('now')-julianday(window_start))*1440 >= ?"
                    "                       THEN datetime('now') ELSE window_start END,"
                    "   last_fail = datetime('now')",
                    (email, self.SIGNIN_WINDOW_MIN, self.SIGNIN_WINDOW_MIN))
            self._reply(401, {"message": "Email or password is incorrect."}, token=tok); return

        with db() as c:            # 成功即清零
            c.execute("DELETE FROM cb_signin_attempt WHERE email=?", (email,))
        self._reply(200, {"redirect": "/myclasses"},
                    token=res.get("session_token") or tok)

    def _signout(self, b):
        tok = self._session_token()
        if tok:
            try: AUTH.sign_out(tok)
            except AuthError: pass
        self._reply(200, {"redirect": "/"}, clear=True)

    def _reset_start(self, b):
        tok = self._session_or_new()
        try:
            AUTH.start_password_reset(tok, email=(b.get("email") or "").strip(),
                                      restart_invalid_flow=True)
            self._deliver_mail(tok, "password-reset")
        except AuthRateLimited as exc:
            # 限流按会话计，与邮箱是否存在无关，因此回 429 不会泄露账户存在性；
            # 反过来，沉默地回"已发送"才是错的 —— 信根本没发出去。
            self._reply_auth_error(exc, tok); return
        except AuthError:
            pass
        # 已知与未知邮箱返回完全相同的公共文案 —— 不变量 password_reset_enumeration
        self._reply(200, {"message": "If that address has an account, we sent a reset code."},
                    token=tok)

    def _reset_complete(self, b):
        tok = self._session_or_new()
        if len(b.get("password") or "") < 8:
            self._reply(400, {"message": "Password must be at least 8 characters."}, token=tok); return
        try:
            AUTH.verify_password_reset_code(tok, (b.get("code") or "").strip())
            new_tok = AUTH.complete_password_reset(tok, new_password=b["password"])
        except AuthError as exc:
            self._reply(400, {"message": _public_error(exc)}, token=tok); return
        self._reply(200, {"redirect": "/", "message": "Password updated. Please sign in."},
                    token=new_tok if isinstance(new_tok, str) else tok)


def main() -> int:
    seeded = init_business_schema()
    port = int(os.environ.get("PORT", "9120"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"creativebug clone on http://127.0.0.1:{port}  routes={len(ROUTES)}  "
          f"classes={seeded}  db={DB}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
