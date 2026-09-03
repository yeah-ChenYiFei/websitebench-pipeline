# -*- coding: utf-8 -*-
"""登录失败限流（独立评审 2026-08-30 P2-5）。

发信有限流、验证码尝试有上限，唯独口令尝试没有：实测同一账号连续 12 次
错误口令全部只回 401，可以无限试。
"""
from __future__ import annotations

import itertools

from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def _account(server) -> tuple[Client, str]:
    c = Client(server)
    e = f"throttle-creativebug-{next(_seq)}@clone.test"
    c.post("/api/auth/register/start", {"email": e, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(e)})
    c.post("/api/auth/signout", {})
    return c, e


def test_repeated_wrong_passwords_get_throttled(server):
    c, email = _account(server)
    codes = [c.post("/api/auth/signin", {"email": email, "password": "wrong"})[0]
             for _ in range(8)]
    assert 429 in codes, f"连续错误口令没有触发限流：{codes}"
    assert codes[:5].count(401) >= 1, f"前几次应当是 401 而不是直接限流：{codes}"


def test_throttle_response_carries_retry_after(server):
    c, email = _account(server)
    last = None
    for _ in range(8):
        last = c.post("/api/auth/signin", {"email": email, "password": "wrong"})
        if last[0] == 429:
            break
    assert last[0] == 429
    assert last[1].get("retry_after", 0) > 0, f"429 未给出等待时长：{last[1]}"


def test_unknown_email_is_throttled_the_same_way(server):
    """限流不得成为账户枚举信道：不存在的邮箱也走同一条路径。"""
    c = Client(server)
    ghost = f"nobody-creativebug-{next(_seq)}@clone.test"
    codes = [c.post("/api/auth/signin", {"email": ghost, "password": "wrong"})[0]
             for _ in range(8)]
    assert 429 in codes, f"不存在的邮箱未被限流，构成枚举信道：{codes}"


def test_successful_signin_clears_the_counter(server):
    c, email = _account(server)
    for _ in range(3):
        c.post("/api/auth/signin", {"email": email, "password": "wrong"})
    assert c.post("/api/auth/signin", {"email": email, "password": PW})[0] == 200
    # 计数清零后应当又能容错几次，而不是立刻被限
    assert c.post("/api/auth/signin", {"email": email, "password": "wrong"})[0] == 401
