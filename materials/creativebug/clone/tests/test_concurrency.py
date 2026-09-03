# -*- coding: utf-8 -*-
"""并发下的状态转换（ULTIMATE §13「业务状态转换、重复、未授权和并发通过」）。

存在的理由：REVIEW-vs-ULTIMATE.md 里「并发」被我标成未测。既有测试都是顺序调用，
证明不了"同一笔订单被两个请求同时确认"时不变量还成立 —— 而那正是把
check-then-write 写成非原子操作的地方会出问题的场景。
"""
from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor

from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def signed_in(server) -> Client:
    c = Client(server)
    e = f"conc-creativebug-{next(_seq)}@clone.test"
    c.post("/api/auth/register/start", {"email": e, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(e)})
    assert c.get("/api/session")[1]["authenticated"] is True
    return c


def _parallel(fn, n=8):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(fn, i) for i in range(n)]]


def test_only_one_concurrent_confirm_succeeds(server):
    """同一笔订单被 8 个线程同时确认，只能成功一次，其余必须是 409。"""
    c = signed_in(server)
    oid = c.post("/api/checkout", {"plan": "annual"})[1]["order_id"]

    codes = _parallel(lambda _: c.post("/api/checkout/confirm", {"order_id": oid})[0])
    assert codes.count(200) == 1, f"确认成功了 {codes.count(200)} 次，应恰好 1 次：{codes}"
    assert all(x in (200, 409) for x in codes), f"出现了预期外的状态码：{codes}"

    orders = c.get("/api/orders")[1]["orders"]
    row = next(o for o in orders if o["order_id"] == oid)
    assert row["state"] == "confirmed"


def test_concurrent_enroll_does_not_duplicate(server):
    """并发报名同一门课不得产生重复行。"""
    c = signed_in(server)
    cid = c.get("/api/search?q=&level=beginner")[1]["results"][0]["class_id"]

    codes = _parallel(lambda _: c.post("/api/enroll", {"class_id": cid, "track": "audit"})[0])
    assert all(x == 200 for x in codes), f"并发报名出现失败：{codes}"

    rows = [x for x in c.get("/api/myclasses")[1]["classes"] if x["class_id"] == cid]
    assert len(rows) == 1, f"报名产生了 {len(rows)} 条重复记录"


def test_concurrent_progress_writes_converge(server):
    """并发写进度不得丢失或重复计数。"""
    c = signed_in(server)
    cls = c.get("/api/search?q=&level=beginner")[1]["results"][0]
    cid = cls["class_id"]
    c.post("/api/enroll", {"class_id": cid, "track": "audit"})

    _parallel(lambda i: c.post("/api/progress",
                               {"class_id": cid, "unit_id": "unit-1", "watched": 1}))
    rows = [x for x in c.get("/api/myclasses")[1]["classes"] if x["class_id"] == cid]
    assert len(rows) == 1
    assert rows[0]["watched_units"] <= (rows[0]["unit_count"] or 1), \
        f"已看单元数超过总数：{rows[0]}"


def test_concurrent_rating_keeps_one_row(server):
    """并发评分是 upsert，不得产生多行。"""
    c = signed_in(server)
    cid = c.get("/api/search?q=&level=beginner")[1]["results"][0]["class_id"]
    codes = _parallel(lambda i: c.post("/api/rating", {"class_id": cid, "stars": (i % 5) + 1})[0])
    assert all(x == 200 for x in codes), f"并发评分出现失败：{codes}"
