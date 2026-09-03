#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拍克隆侧候选帧 —— 与源站参照帧一一对应。

在服务器上跑：起本地克隆站，按 checkpoints.json 逐条截图。
视口、时区、locale 与拍参照帧时钉死一致，否则相似度里会混入配方差异。

登录态检查点需要一个本地账户：脚本自己注册一个（走克隆的真实认证链路，
验证码从 Mailpit 取），不使用任何源站凭据。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "materials" / "creativebug"
# Mailpit 的 UI 端口跟着 run.sh 的 SMTP 端口走（9125/9126），
# 早先硬编码成 8025 —— 那是另一个项目的实例，本站拍登录态帧时取不到验证码。
MAILPIT = os.environ.get("WEBSITEBENCH_MAILPIT_API",
                         "http://127.0.0.1:9126/api/v1")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def mailpit_code(address: str, timeout: float = 20.0) -> str:
    import urllib.parse
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            q = urllib.parse.quote(f"to:{address}")
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
    raise SystemExit(f"Mailpit 没收到发往 {address} 的验证码")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:9120")
    ap.add_argument("--out", default=str(HERE.parent / "artifacts" / "candidate"))
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    cps = json.loads((SITE / "scope" / "checkpoints.json").read_text(encoding="utf-8"))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    VP = cps["viewports"]

    ok = fail = 0
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(user_agent=UA, locale="en-US",
                            timezone_id="America/Los_Angeles",
                            viewport=VP["desktop"])
        # 登录态检查点：在克隆里注册一个本地账户
        email = f"shots-creativebug-{int(time.time())}@clone.test"
        page = ctx.new_page()
        page.goto(a.base + "/healthz", wait_until="domcontentloaded")
        page.evaluate("""async (e) => (await fetch('/api/auth/register/start',
            {method:'POST', headers:{'Content-Type':'application/json'},
             body: JSON.stringify({email:e, password:'Correct-Horse-9'})})).status""", email)
        code = mailpit_code(email)
        st = page.evaluate("""async (c) => (await fetch('/api/auth/register/verify',
            {method:'POST', headers:{'Content-Type':'application/json'},
             body: JSON.stringify({code:c})})).status""", code)
        print(f"克隆内账户就绪 status={st}  {email}")
        page.close()

        # 匿名检查点必须用干净上下文拍。
        # 上面为登录态检查点注册的账户会让整个 ctx 带上会话；克隆现在按会话
        # 切换首页（与源站一致），于是拿着登录态去拍 auth_state=anonymous 的
        # home 检查点，得到的是登录版首页，与匿名参考帧对不上 —— 实测 0.6185。
        anon = b.new_context(user_agent=UA, locale="en-US",
                             timezone_id="America/Los_Angeles",
                             viewport=VP["desktop"])

        for c in cps["checkpoints"]:
            use = anon if c.get("auth_state") == "anonymous" else ctx
            pg = use.new_page()
            try:
                pg.set_viewport_size(VP[c["viewport"]])
                r = pg.goto(a.base + c["route_path"], wait_until="domcontentloaded", timeout=30000)
                # 必须与拍参照帧用的 _settle() 完全一致：滚 8 次触发懒加载再回顶。
                # 参照帧滚过、候选帧没滚，量出来的是配方差异不是保真度差异。
                try:
                    pg.wait_for_load_state("load", timeout=25000)
                except Exception:
                    pass
                pg.wait_for_timeout(2500)
                for _ in range(8):
                    pg.mouse.wheel(0, 1500)
                    pg.wait_for_timeout(250)
                pg.wait_for_timeout(1500)
                pg.evaluate("window.scrollTo(0,0)")
                pg.wait_for_timeout(400)
                png = out / f"{c['id']}.png"
                pg.screenshot(path=str(png), full_page=False)
                status = r.status if r else None
                print(f"  {c['id']:38s} {status} {png.stat().st_size:>7}B")
                ok += 1
            except Exception as exc:
                print(f"  {c['id']:38s} FAIL {type(exc).__name__}")
                fail += 1
            finally:
                pg.close()
        anon.close(); ctx.close(); b.close()
    print(f"\n候选帧 ok={ok} fail={fail} → {out}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
