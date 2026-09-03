"""功能完整性 —— 对应用户口径 10「功能必须实现完整」与 23 条 trace。

截断只作用于种子目录数据，不作用于行为：课少，但每门课该有的行为都真实存在。
"""
from __future__ import annotations

import itertools

from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def addr(t): return f"full-creativebug-{t}-{next(_seq)}@clone.test"


def signed_in(server, run_tag):
    c = Client(server)
    e = addr(run_tag)
    c.post("/api/auth/register/start", {"email": e, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(e)})
    assert c.get("/api/session")[1]["authenticated"] is True
    return c, e


def a_class(c):
    b = c.get("/api/search?q=&level=beginner")[1]
    assert b["count"] > 0
    return b["results"][0]


# --- 搜索筛选：trace 4 要求的多维度 ---------------------------------
def test_search_filters_by_duration_and_rating(client):
    short = client.get("/api/search?q=&duration_max=30")[1]
    assert short["count"] > 0
    assert all(r["duration_minutes"] is None or r["duration_minutes"] <= 30
               for r in short["results"])
    long_ = client.get("/api/search?q=&duration_min=60")[1]
    assert all(r["duration_minutes"] >= 60 for r in long_["results"])


def test_search_filters_by_topic_and_instructor(client):
    topic = client.get("/api/search?q=&topic=sewing")[1]
    assert topic["count"] > 0
    assert all(r["category"] == "sewing" for r in topic["results"])
    inst = topic["results"][0]["instructor"]
    by_inst = client.get(f"/api/search?q=&instructor={inst}")[1]
    assert by_inst["count"] > 0
    assert all(r["instructor"] == inst for r in by_inst["results"])


# --- 账户历史：trace 19 --------------------------------------------
def test_account_history_newest_exposes_status_detail_cancel_and_route_back(server, run_tag):
    c, _ = signed_in(server, run_tag)
    s, order = c.post("/api/checkout", {"plan": "monthly"})
    assert s == 200
    s2, hist = c.get("/api/orders")
    assert s2 == 200
    newest = hist["newest"]
    assert newest and newest["order_id"] == order["order_id"]
    assert newest["state"] == "review"
    assert newest["detail_url"] and newest["cancellable"] is True
    assert hist["route_back"] == "/account/profile"


def test_order_can_be_cancelled(server, run_tag):
    c, _ = signed_in(server, run_tag)
    order = c.post("/api/checkout", {"plan": "annual"})[1]
    s, b = c.post("/api/orders/cancel", {"order_id": order["order_id"]})
    assert s == 200 and b["state"] == "cancelled"
    assert c.post("/api/orders/cancel", {"order_id": order["order_id"]})[0] == 404


# --- 订阅状态机：anonymous → trial → paid → cancelled ---------------
def test_subscription_state_machine(server, run_tag):
    c, _ = signed_in(server, run_tag)
    assert c.get("/api/orders")[1]["subscription"]["state"] == "trial"
    o = c.post("/api/checkout", {"plan": "monthly"})[1]
    c.post("/api/checkout/confirm", {"order_id": o["order_id"], "plan": "monthly"})
    assert c.get("/api/orders")[1]["subscription"]["state"] == "paid"
    s, b = c.post("/api/subscription/cancel")
    assert s == 200 and b["state"] == "cancelled"
    assert c.get("/api/orders")[1]["subscription"]["state"] == "cancelled"


# --- 学习偏好：trace 14 --------------------------------------------
def test_preferences_round_trip(server, run_tag):
    c, _ = signed_in(server, run_tag)
    assert c.get("/api/preferences")[1]["preferences"] == {}
    assert c.post("/api/preferences", {"preferences": {"email_digest": "weekly",
                                                       "autoplay": "off"}})[0] == 200
    got = c.get("/api/preferences")[1]["preferences"]
    assert got["email_digest"] == "weekly" and got["autoplay"] == "off"
    c.post("/api/preferences", {"preferences": {"autoplay": "on"}})
    assert c.get("/api/preferences")[1]["preferences"]["autoplay"] == "on"


def test_preferences_require_auth(client):
    assert client.get("/api/preferences")[0] == 401
    assert client.post("/api/preferences", {"preferences": {"a": "b"}})[0] == 401


# --- 测验：trace 12 -------------------------------------------------
def test_quiz_grades_server_side_and_records_attempt(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    s, b = c.post("/api/quiz", {"class_id": k["class_id"], "unit_id": "1",
                                "answer": "definitely-wrong", "correct": True})
    assert s == 200
    assert b["correct"] is False, "客户端送来的 correct 被采信了"
    assert b["feedback"] and b["attempts"] == 1
    s2, b2 = c.post("/api/quiz", {"class_id": k["class_id"], "unit_id": "1",
                                  "answer": k["class_id"][:1]})
    assert b2["correct"] is True and b2["attempts"] == 2


# --- 证书与完成态：trace 14 -----------------------------------------
def test_certificate_requires_completion(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    c.post("/api/enroll", {"class_id": k["class_id"]})
    assert c.post("/api/certificate", {"class_id": k["class_id"]})[0] == 409, "未完成也发了证书"
    prog = c.post("/api/progress", {"class_id": k["class_id"], "unit_id": "1"})[1]
    assert prog["completed"] is True and prog["certificate_available"] is True
    s, cert = c.post("/api/certificate", {"class_id": k["class_id"]})
    assert s == 200 and cert["certificate_id"]
    listed = c.get("/api/certificate")[1]["certificates"]
    assert any(x["class_id"] == k["class_id"] for x in listed)


# --- 续播：trace 13 -------------------------------------------------
def test_resume_returns_most_recent_class(server, run_tag):
    c, _ = signed_in(server, run_tag)
    res = c.get("/api/resume")[1]
    assert res["resume"] is None and res["route_back"] == "/myclasses"
    k = a_class(c)
    c.post("/api/enroll", {"class_id": k["class_id"]})
    c.post("/api/progress", {"class_id": k["class_id"], "unit_id": "1"})
    got = c.get("/api/resume")[1]["resume"]
    assert got["class_id"] == k["class_id"] and got["watched_units"] == 1


# --- 帮助/支持：trace 21 --------------------------------------------
def test_contact_is_public_and_leaks_no_account_data(server, run_tag):
    """匿名可用；且登录用户提交时，响应里不得回带任何账户标识。

    判据是真实的账户标识（account_id 值、注册邮箱），不是 "email" 这个词 ——
    正常文案里就有 "follow up by email"，用裸词做判据会把它误判成泄露。
    """
    anon = Client(server)
    s, b = anon.post("/api/contact", {"topic": "sign-in", "body": "I cannot reach my classes"})
    assert s == 200 and b["received"] is True

    c, email = signed_in(server, run_tag)
    s2, b2 = c.post("/api/contact", {"topic": "billing", "body": "question about my plan"})
    assert s2 == 200
    blob = str(b2)
    assert email not in blob, "响应回带了注册邮箱"
    assert "account_" not in blob, "响应回带了 account_id"
    assert "session_" not in blob, "响应回带了会话令牌"


def test_contact_validates_required_fields(client):
    assert client.post("/api/contact", {"topic": "", "body": ""})[0] == 400


# --- 确定性重置：backend/model.json 的 deterministic-reset ----------
def test_reset_clears_account_state_and_reseeds(server, run_tag):
    c, _ = signed_in(server, run_tag)
    k = a_class(c)
    c.post("/api/enroll", {"class_id": k["class_id"]})
    assert c.get("/api/myclasses")[1]["classes"]
    s, b = c.post("/api/reset")
    assert s == 200 and b["classes"] > 0
    assert c.get("/api/myclasses")[1]["classes"] == [], "重置后仍有报名记录"
    assert c.get("/api/search?q=&level=beginner")[1]["count"] > 0, "重置后目录种子丢了"
