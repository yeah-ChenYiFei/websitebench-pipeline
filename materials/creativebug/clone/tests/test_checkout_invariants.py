# -*- coding: utf-8 -*-
"""结算确认的服务端不变量。

存在的理由：/api/checkout/confirm 曾经无论请求体是什么都回 200 confirmed ——
UPDATE 匹配不到任何行，订单停在 review，却已经给账户开了 paid 订阅。
接口层测试当时全绿，因为它们只发"带正确 order_id"的请求。
"""
from __future__ import annotations

import itertools

from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def signed_in(server):
    c = Client(server)
    e = f"checkout-creativebug-{next(_seq)}@clone.test"
    c.post("/api/auth/register/start", {"email": e, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(e)})
    assert c.get("/api/session")[1]["authenticated"] is True
    return c


def an_order(c, plan="annual"):
    code, body = c.post("/api/checkout", {"plan": plan})
    assert code == 200, body
    return body["order_id"]


def test_confirm_requires_an_existing_order(server):
    c = signed_in(server)
    assert c.post("/api/checkout/confirm", {"order_id": 999999})[0] == 404
    assert c.post("/api/checkout/confirm", {})[0] == 404


def test_confirm_does_not_grant_paid_subscription_without_an_order(server):
    c = signed_in(server)
    c.post("/api/checkout/confirm", {"order_id": 999999})
    state = c.get("/api/session")[1]
    assert "paid" not in str(state).lower() or state.get("subscription") != "paid"


def test_confirm_marks_the_order_and_records_payment_profile(server):
    c = signed_in(server)
    oid = an_order(c)
    code, body = c.post("/api/checkout/confirm", {"order_id": oid})
    assert code == 200, body
    assert body["state"] == "confirmed"
    # 后端强制规范：支付适配器只允许 local-sandbox，且必须留痕
    assert body["payment_profile"] == "local-sandbox"
    orders = c.get("/api/orders")[1]["orders"]
    row = next(o for o in orders if o["order_id"] == oid)
    assert row["state"] == "confirmed"


def test_confirm_is_not_repeatable(server):
    c = signed_in(server)
    oid = an_order(c)
    assert c.post("/api/checkout/confirm", {"order_id": oid})[0] == 200
    assert c.post("/api/checkout/confirm", {"order_id": oid})[0] == 409


def test_one_account_cannot_confirm_another_accounts_order(server):
    buyer = signed_in(server)
    oid = an_order(buyer)
    intruder = signed_in(server)
    assert intruder.post("/api/checkout/confirm", {"order_id": oid})[0] == 404
    # 受害者的订单必须仍然可以由本人确认
    assert buyer.post("/api/checkout/confirm", {"order_id": oid})[0] == 200


def test_plan_comes_from_the_order_not_the_request(server):
    """客户端不能靠改请求体里的 plan 换一个不同的订阅。"""
    c = signed_in(server)
    oid = an_order(c, plan="annual")
    code, body = c.post("/api/checkout/confirm", {"order_id": oid, "plan": "monthly"})
    assert code == 200, body
    assert body["plan"] == "annual"
