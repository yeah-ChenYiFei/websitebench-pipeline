#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""浏览器闭环 —— 真的用鼠标点，而不是打 API。

AUTH-FLOW §7 要求人手工走一遍；这个脚本不替代那一步，
它的作用是让我在交给人之前先确认 UI 层是通的。
API 层 65 条测试全绿而按钮点了没反应 —— 差别就在这里。
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:9120"
MAILPIT = "http://127.0.0.1:8025/api/v1"


def code_for(addr: str, timeout: float = 20.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        try:
            q = urllib.parse.quote(f"to:{addr}")
            msgs = json.loads(urllib.request.urlopen(
                f"{MAILPIT}/search?query={q}", timeout=5).read()).get("messages", [])
            if msgs:
                body = json.loads(urllib.request.urlopen(
                    f"{MAILPIT}/message/{msgs[0]['ID']}", timeout=5).read())
                m = re.search(r"\b(\d{6})\b", (body.get("Text") or "") + (body.get("HTML") or ""))
                if m:
                    return m.group(1)
        except Exception:
            pass
        time.sleep(0.4)
    raise SystemExit(f"Mailpit 未收到发往 {addr} 的验证码")


def main() -> int:
    from playwright.sync_api import sync_playwright
    email = f"loop-{int(time.time())}@clone.test"
    steps: list[tuple[str, bool, str]] = []

    def step(name, ok, note=""):
        steps.append((name, ok, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:42s} {note}")

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        pg = ctx.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:120]))

        pg.goto(BASE + "/trial/create-account", wait_until="domcontentloaded")
        pg.wait_for_timeout(600)
        step("注册页打开", pg.url.endswith("/trial/create-account"))
        step("clone-runtime 已就绪",
             pg.evaluate("document.documentElement.getAttribute('data-cb-clone')") == "ready")

        # 用真实的点击，而不是直接调 API
        form = pg.query_selector("form[data-cb-action='/api/auth/register/start']")
        step("注册表单已接线", form is not None)
        if form:
            for sel, val in (("input[name=email]", email),
                             ("input[name=password]", "Correct-Horse-9")):
                el = form.query_selector(sel)
                if el:
                    el.fill(val)
            btn = form.query_selector("button, input[type=submit]")
            step("找到提交控件", btn is not None,
                 (btn.get_attribute("type") or "无 type") if btn else "")
            resp = []
            pg.on("response", lambda r: resp.append(r) if "/api/auth/" in r.url else None)
            if btn:
                btn.click()
                pg.wait_for_timeout(2500)
            step("点击后确实调用了注册接口", any("/register/start" in r.url for r in resp),
                 f"{len(resp)} 个认证请求")

        got = None
        try:
            got = code_for(email, timeout=15)
        except SystemExit:
            pass
        step("Mailpit 收到六位码", bool(got), got or "未收到")

        step("页面无 JS 报错", not errors, "; ".join(errors[:2]))
        ctx.close(); b.close()

    bad = [n for n, ok, _ in steps if not ok]
    print(f"\n浏览器闭环: {len(steps)-len(bad)}/{len(steps)} 通过")
    if bad:
        print("未通过:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
