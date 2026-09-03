# -*- coding: utf-8 -*-
"""跨进程重启的持久化（ULTIMATE §13「两进程重启持久化通过」）。

存在的理由：这一条在 REVIEW-vs-ULTIMATE.md 里被我自己标成 ❌ 未测。
既有测试都在单个 server fixture 内完成，证明不了"进程重启后状态还在"——
而这正是 stateful 站点最容易悄悄坏掉的地方（内存态冒充持久态）。
"""
from __future__ import annotations

import itertools

import pytest
from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def _register(client: Client) -> str:
    email = f"restart-creativebug-{next(_seq)}@clone.test"
    client.post("/api/auth/register/start", {"email": email, "password": PW})
    code = mailpit_code(email)
    assert code, "未收到验证码"
    assert client.post("/api/auth/register/verify", {"code": code})[0] == 200
    return email


def test_account_and_enrollment_survive_a_restart(server, restart_server):
    """注册 + 报名 → 重启进程 → 账号仍可登录，报名仍在。"""
    c = Client(server)
    email = _register(c)
    cls = c.get("/api/search?q=&level=beginner")[1]["results"][0]
    assert c.post("/api/enroll", {"class_id": cls["class_id"], "track": "audit"})[0] == 200

    fresh = restart_server()

    c2 = Client(fresh)
    code, body = c2.post("/api/auth/signin", {"email": email, "password": PW})
    assert code == 200, f"重启后旧账号登不上: {body}"
    got = c2.get("/api/myclasses")[1]
    assert any(x["class_id"] == cls["class_id"] for x in got["classes"]), \
        "重启后报名记录丢失"


def test_confirmed_order_survives_a_restart(server, restart_server):
    c = Client(server)
    email = _register(c)
    oid = c.post("/api/checkout", {"plan": "annual"})[1]["order_id"]
    assert c.post("/api/checkout/confirm", {"order_id": oid})[0] == 200

    fresh = restart_server()

    c2 = Client(fresh)
    assert c2.post("/api/auth/signin", {"email": email, "password": PW})[0] == 200
    orders = c2.get("/api/orders")[1]["orders"]
    row = next((o for o in orders if o["order_id"] == oid), None)
    assert row is not None, "重启后订单丢失"
    assert row["state"] == "confirmed", f"重启后订单状态变了: {row['state']}"


def test_session_cookie_does_not_outlive_the_data(server, restart_server):
    """重启后会话可以失效，但账号数据必须还在 —— 两者不能混为一谈。"""
    c = Client(server)
    email = _register(c)
    assert c.get("/api/session")[1]["authenticated"] is True

    fresh = restart_server()

    anon = Client(fresh)
    assert anon.get("/api/session")[1]["authenticated"] is False, "全新客户端不该自带登录态"
    assert anon.post("/api/auth/signin", {"email": email, "password": PW})[0] == 200
