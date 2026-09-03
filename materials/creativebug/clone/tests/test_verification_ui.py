# -*- coding: utf-8 -*-
"""六位验证码必须有页面落点。

AUTH-FLOW §5 要求接通"六位码输入或邮件链接落点"，完成标准是"关键流程不依赖
手工修改 cookie 或浏览器控制台"。

此前 register/start 成功后只贴一句 "Check that address for a six-digit code."，
页面上却没有任何地方能输入这个码；密码重置同样缺。而三个浏览器审计脚本都是直接
fetch('/api/auth/register/verify') 的，所以这个缺陷一路全绿 —— 验的是接口，
不是用户能不能用。
"""
from __future__ import annotations

from pathlib import Path

import pytest

RUNTIME = Path(__file__).resolve().parents[1] / "static" / "clone-runtime.js"


@pytest.fixture(scope="module")
def js() -> str:
    return RUNTIME.read_text(encoding="utf-8")


def test_runtime_renders_a_code_input(js):
    assert "cb-clone-challenge" in js, "运行时没有验证码面板"
    assert "cb-clone-code" in js, "没有六位码输入框"
    assert 'autocomplete: "one-time-code"' in js, "验证码框缺 one-time-code 语义"


def test_registration_and_reset_both_have_a_landing_point(js):
    assert "/api/auth/register/verify" in js, "注册验证没有页面落点"
    assert "/api/auth/reset/complete" in js, "密码重置没有页面落点"
    assert "cb-clone-newpw" in js, "重置缺新密码输入框"


def test_challenge_is_reachable_from_the_step_query(js):
    """register/start 的响应指向 ?step=verify，直接打开也必须有落点。"""
    assert "hydrateChallengeStep" in js
    assert '"verify"' in js


def test_wrong_code_surfaces_an_error(js):
    """错误码/过期码的文案要显示出来，而不是静默失败。"""
    assert "That code is not valid." in js


def test_modal_context_uses_a_centered_overlay(js):
    """表单在模态框里时，面板要做成居中浮层。

    就地替换会藏掉 689px 高的模态表单，只剩一个空壳，页面看起来像坏了 ——
    而且 focus() 还会把视口滚到那片空白上。
    """
    assert "cb-clone-challenge-backdrop" in js, "模态场景缺浮层背景"
    assert "preventScroll" in js, "focus 会把视口滚到空白处"
    assert ".cb-modal, .modal, .modal-dialog" in js, "没有判断表单是否在模态框内"


def test_no_secret_is_read_by_the_frontend(js):
    """前端不得读数据库、worker token 或 SMTP 配置（AUTH-FLOW §5）。"""
    for forbidden in ("worker_token", "WEBSITEBENCH_SMTP", "sqlite", "outbox"):
        assert forbidden not in js, f"前端不应出现 {forbidden}"
