"""认证链路 —— AUTH-FLOW §7 要求的 11 条自动测试。

每条测试用独立邮箱（带站点与运行标签），不清空其他执行者的 Mailpit 邮件。
"""
from __future__ import annotations

import itertools

import pytest
from conftest import mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def addr(run_tag: str) -> str:
    return f"auth-creativebug-{run_tag}-{next(_seq)}@clone.test"


def register(client, email, password=PW):
    s, b = client.post("/api/auth/register/start", {"email": email, "password": password})
    assert s == 200, b
    code = mailpit_code(email)
    s2, b2 = client.post("/api/auth/register/verify", {"code": code})
    return s2, b2, code


# 1. 注册开始产生待验证状态；验证前不得存在可登录账户
def test_pending_registration_cannot_sign_in(client, run_tag):
    email = addr(run_tag)
    s, _ = client.post("/api/auth/register/start", {"email": email, "password": PW})
    assert s == 200
    mailpit_code(email)                      # 邮件确实发出
    s2, _ = client.post("/api/auth/signin", {"email": email, "password": PW})
    assert s2 == 401, "验证前不应存在可登录账户"


# 2. SMTP 邮件的收件人与验证码正确
def test_registration_email_delivered_with_code(client, run_tag):
    email = addr(run_tag)
    client.post("/api/auth/register/start", {"email": email, "password": PW})
    code = mailpit_code(email)
    assert code.isdigit() and len(code) == 6


# 3a. 错误验证码被拒
def test_wrong_code_rejected(client, run_tag):
    email = addr(run_tag)
    client.post("/api/auth/register/start", {"email": email, "password": PW})
    real = mailpit_code(email)
    wrong = "000000" if real != "000000" else "111111"
    s, b = client.post("/api/auth/register/verify", {"code": wrong})
    assert s == 400 and "valid" in b.get("message", "").lower()


# 3b/4. 正确验证码完成注册且会话为已认证
def test_correct_code_completes_registration(client, run_tag):
    email = addr(run_tag)
    s, b, _ = register(client, email)
    assert s == 200 and b.get("redirect") == "/myclasses"
    s2, b2 = client.get("/api/session")
    assert s2 == 200 and b2["authenticated"] is True


# 5. 重复邮箱注册不得创建第二个账户，且公共响应不泄露账户是否存在
def test_duplicate_email_public_response_matches(client, server, run_tag):
    from conftest import Client
    email = addr(run_tag)
    register(client, email)
    fresh = Client(server)
    s_dup, b_dup = fresh.post("/api/auth/register/start", {"email": email, "password": PW})
    other = Client(server)
    s_new, b_new = other.post("/api/auth/register/start", {"email": addr(run_tag), "password": PW})
    assert s_dup == s_new
    assert b_dup.get("message") == b_new.get("message"), "响应文案泄露了账户是否存在"


# 6. 错误密码失败、正确密码成功
def test_password_check(client, server, run_tag):
    from conftest import Client
    email = addr(run_tag)
    register(client, email)
    c2 = Client(server)
    assert c2.post("/api/auth/signin", {"email": email, "password": "wrong-password"})[0] == 401
    assert c2.post("/api/auth/signin", {"email": email, "password": PW})[0] == 200
    assert c2.get("/api/session")[1]["authenticated"] is True


# 7. 登出后保护页不可访问（服务端校验，不是前端跳转）
def test_signout_revokes_access(client, run_tag):
    register(client, addr(run_tag))
    assert client.get("/api/myclasses")[0] == 200
    assert client.post("/api/auth/signout")[0] == 200
    assert client.get("/api/myclasses")[0] == 401
    assert client.get("/api/session")[1]["authenticated"] is False


# 8. 已知与未知邮箱的重置响应完全一致
def test_reset_response_indistinguishable(client, server, run_tag):
    from conftest import Client
    known = addr(run_tag)
    register(client, known)
    a = Client(server).post("/api/auth/reset/start", {"email": known})
    b = Client(server).post("/api/auth/reset/start", {"email": addr(run_tag)})
    assert a == b, "已知与未知邮箱的重置响应不一致，可用于账户枚举"


# 9. 新密码生效、旧密码失效、重置挑战不可重放
def test_reset_rotates_password_once(client, server, run_tag):
    from conftest import Client
    email = addr(run_tag)
    register(client, email)
    client.post("/api/auth/signout")

    r = Client(server)
    assert r.post("/api/auth/reset/start", {"email": email})[0] == 200
    code = mailpit_code(email)
    new_pw = "Brand-New-Pass-7"
    assert r.post("/api/auth/reset/complete", {"code": code, "password": new_pw})[0] == 200

    c = Client(server)
    assert c.post("/api/auth/signin", {"email": email, "password": PW})[0] == 401, "旧密码仍可用"
    assert c.post("/api/auth/signin", {"email": email, "password": new_pw})[0] == 200

    replay = Client(server)
    replay.post("/api/auth/reset/start", {"email": email})
    assert replay.post("/api/auth/reset/complete",
                       {"code": code, "password": "Another-Pass-8"})[0] == 400, "重置码可重放"


# 10. SMTP 模式下不得通过任何接口回显验证码
def test_outbox_never_exposes_challenge(client, run_tag):
    email = addr(run_tag)
    _, body = client.post("/api/auth/register/start", {"email": email, "password": PW})
    code = mailpit_code(email)
    assert code not in str(body), "接口响应里回显了验证码"
    # 这几个调试端点本就不该存在。但"因为 404 所以通过"和"存在且不泄露"
    # 是两回事 —— 断言里把两者分开，否则将来有人加了端点，测试仍会平凡通过。
    for path in ("/api/outbox", "/api/debug/mail"):
        s, b = client.get(path)
        assert s == 404, f"{path} 在 SMTP 模式下不应存在（实得 {s}）"
        assert code not in str(b)
    s, b = client.get("/api/session")
    assert s == 200 and code not in str(b), "会话接口泄露了验证码"


# 11. 同一连接上 POST 之后继续 GET 不出现 501（keep-alive 请求体读尽）
def test_keepalive_post_then_get(client, run_tag):
    email = addr(run_tag)
    client.post("/api/auth/register/start", {"email": email, "password": PW})
    assert client.get("/api/session")[0] == 200
    assert client.get("/healthz")[0] == 200
