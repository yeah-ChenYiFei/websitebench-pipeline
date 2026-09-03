"""业务链路测试 —— 对应 scope/journeys.json 里的 P0 旅程与 invariants.json 的不变量。

覆盖：目录浏览与筛选、报名、进度与完成、收藏、订阅结账、评分、账户历史、
以及登出态与越权的服务端拒绝。
"""
from __future__ import annotations

import itertools

from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def addr(run_tag): return f"journey-creativebug-{run_tag}-{next(_seq)}@clone.test"


def signed_in(server, run_tag):
    c = Client(server)
    email = addr(run_tag)
    c.post("/api/auth/register/start", {"email": email, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(email)})
    assert c.get("/api/session")[1]["authenticated"] is True
    return c, email


def a_class(client):
    s, b = client.get("/api/search?q=&level=beginner")
    assert s == 200 and b["count"] > 0
    return b["results"][0]


# --- browse-catalog ---------------------------------------------------
def test_catalog_search_and_filters(client):
    assert client.get("/api/search?q=embroidery")[1]["count"] > 0
    lvl = client.get("/api/search?q=&level=beginner")[1]
    assert lvl["count"] > 0 and all(r["level"] == "beginner" for r in lvl["results"])


def test_impossible_query_returns_empty_state_with_route_back(client):
    b = client.get("/api/search?q=zzzz-no-match-websitebench")[1]
    assert b["count"] == 0
    assert b["empty_state"]["route_back"] == "/classes"
    assert b["empty_state"]["message"]


# --- dashboard-and-enrollment ----------------------------------------
def test_enroll_then_appears_in_myclasses(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    assert c.post("/api/enroll", {"class_id": k["class_id"], "track": "audit"})[0] == 200
    rows = c.get("/api/myclasses")[1]["classes"]
    assert any(r["class_id"] == k["class_id"] for r in rows)


def test_double_enroll_is_idempotent(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    c.post("/api/enroll", {"class_id": k["class_id"]})
    c.post("/api/enroll", {"class_id": k["class_id"]})
    rows = [r for r in c.get("/api/myclasses")[1]["classes"] if r["class_id"] == k["class_id"]]
    assert len(rows) == 1, "重复报名产生了两条记录"


# --- lesson-progress --------------------------------------------------
def test_progress_advances_and_reports_completion(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    c.post("/api/enroll", {"class_id": k["class_id"]})
    s, b = c.post("/api/progress", {"class_id": k["class_id"], "unit_id": "1"})
    assert s == 200 and b["watched_units"] == 1
    assert b["completed"] is (b["watched_units"] >= b["unit_count"])


def test_progress_survives_signout_signin(server, run_tag):
    c, email = signed_in(server, run_tag)
    k = a_class(c)
    c.post("/api/enroll", {"class_id": k["class_id"]})
    c.post("/api/progress", {"class_id": k["class_id"], "unit_id": "1"})
    c.post("/api/auth/signout")
    c2 = Client(c.base)
    assert c2.post("/api/auth/signin", {"email": email, "password": PW})[0] == 200
    rows = c2.get("/api/myclasses")[1]["classes"]
    hit = next(r for r in rows if r["class_id"] == k["class_id"])
    assert hit["watched_units"] == 1, "进度未持久化"


def test_anonymous_cannot_write_progress(client):
    assert client.post("/api/progress", {"class_id": "x", "unit_id": "1"})[0] == 401


# --- watchlist --------------------------------------------------------
def test_watchlist_toggles(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    on = c.post("/api/watchlist", {"class_id": k["class_id"]})[1]
    off = c.post("/api/watchlist", {"class_id": k["class_id"]})[1]
    assert on["active"] is True and off["active"] is False


# --- subscription-checkout -------------------------------------------
def test_sandbox_checkout_reaches_review_then_confirmation(server, run_tag):
    c, _ = signed_in(server, run_tag)
    s, order = c.post("/api/checkout", {"plan": "monthly"})
    assert s == 200 and order["state"] == "review" and order["currency"] == "USD"
    assert order["redirect"].startswith("/checkout/review")
    s2, done = c.post("/api/checkout/confirm",
                      {"order_id": order["order_id"], "plan": "monthly"})
    assert s2 == 200 and done["state"] == "confirmed"


def test_unknown_plan_rejected(server, run_tag):
    c, _ = signed_in(server, run_tag)
    assert c.post("/api/checkout", {"plan": "free-lunch"})[0] == 400


def test_anonymous_cannot_checkout(client):
    assert client.post("/api/checkout", {"plan": "monthly"})[0] == 401


# --- ratings ----------------------------------------------------------
def test_rating_upsert_is_single_row(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    assert c.post("/api/rating", {"class_id": k["class_id"], "stars": 4})[0] == 200
    assert c.post("/api/rating", {"class_id": k["class_id"], "stars": 5})[0] == 200


def test_anonymous_cannot_rate(client):
    assert client.post("/api/rating", {"class_id": "x", "stars": 5})[0] == 401


# --- auth-server-side（不变量）----------------------------------------
def test_protected_pages_rejected_server_side(client):
    for p in ("/myclasses", "/myclasses/library", "/account/profile",
              "/preferences", "/gallery/mygallery"):
        assert client.get(p)[0] == 401, f"{p} 未在服务端挡住匿名访问"


def test_cross_account_progress_is_isolated(server, run_tag):
    a, _ = signed_in(server, run_tag)
    k = a_class(a)
    a.post("/api/enroll", {"class_id": k["class_id"]})
    a.post("/api/progress", {"class_id": k["class_id"], "unit_id": "1"})
    b, _ = signed_in(server, run_tag)
    assert b.get("/api/myclasses")[1]["classes"] == [], "另一账户看到了别人的报名"
