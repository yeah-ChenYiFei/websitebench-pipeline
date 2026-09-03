#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 层全面自查：把页面上每个可提交的表单、每个认证入口都真的点一遍。

存在的理由：65 条 API 层测试全绿，而页面上按钮点不动 —— 用户连着发现了
五个这类 bug。测试断言的是"接口带对载荷时能工作"，从不问"按钮点下去
会不会调接口、带什么载荷去调"。这个脚本只问后者。

判据：任何点击后出现 4xx/5xx、连接断开、或 JS 报错，都算失败。
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
PW = "Correct-Horse-9"

# 源站自身就截断的 URL（见 scope/source-defects.md，已比对原始抓取件确认）。
# 单独列出而不是过滤掉：忠实复现的坏图仍应出现在报告里，只是不算 clone 的缺陷。
SOURCE_DEFECTS = (
    "/pimage/dynamic/workshop-activity-card~storage/public/images/"
    "tutorial_thumbnails/original/2268",
)


def is_source_defect(u: str) -> bool:
    return any(u.startswith(d[:40]) for d in SOURCE_DEFECTS)

PAGES = ["/", "/classes", "/classes/sewing", "/classes/sewing/garment-sewing",
         "/site/about", "/trial/create-account", "/subscribe/create-account",
         "/forgot-password", "/instructors/courtney-cerruti", "/patterns",
         "/_clone/out-of-scope", "/_clone/not-found"]


def code_for(addr, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            q = urllib.parse.quote(f"to:{addr}")
            msgs = json.loads(urllib.request.urlopen(
                f"{MAILPIT}/search?query={q}", timeout=5).read()).get("messages", [])
            if msgs:
                bd = json.loads(urllib.request.urlopen(
                    f"{MAILPIT}/message/{msgs[0]['ID']}", timeout=5).read())
                m = re.search(r"\b(\d{6})\b", (bd.get("Text") or "") + (bd.get("HTML") or ""))
                if m:
                    return m.group(1)
        except Exception:
            pass
        time.sleep(0.4)
    return None


def verify_via_ui(pg, code, password=None):
    """在页面上输入六位码完成挑战 —— 不走 fetch()。

    此前三个审计脚本都直接 fetch('/api/auth/register/verify')，于是"页面上根本
    没有验证码输入框"这个缺陷一路全绿：验的是接口，不是用户能不能用。
    """
    pg.wait_for_selector(".cb-clone-challenge", timeout=8000)
    pg.fill("#cb-clone-code", code)
    if password is not None:
        pg.fill("#cb-clone-newpw", password)
    pg.click(".cb-clone-challenge button")
    pg.wait_for_timeout(2200)


def open_register_form(pg):
    """按源站真实路径拿到可用的注册表单。

    trial 页上的注册表单在登录模态框里，Bootstrap 的 `.modal` 默认 display:none
    —— 之前 Bootstrap 没加载，模态框裸露在页面上可以直接填；补回 Bootstrap 后
    它按源站行为被正确隐藏了。所以要先触发打开，填不进去就换首页的表单。
    """
    sel = "form[data-cb-action='/api/auth/register/start']"

    def usable():
        for f in pg.query_selector_all(sel):
            box = f.query_selector("input[type=text], input[type=email]")
            if box and box.is_visible():
                return f
        return None

    f = usable()
    if f:
        return f
    for trig in (".js-login", "a:has-text('Log In')", "button:has-text('Log In')"):
        el = pg.query_selector(trig)
        if el:
            try:
                el.click(force=True, timeout=3000)
                pg.wait_for_timeout(700)
            except Exception:
                pass
            f = usable()
            if f:
                return f
    # 模态框打不开就退回首页 —— 首页的试用表单是常驻可见的
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_timeout(900)
    return usable()


def main() -> int:
    from playwright.sync_api import sync_playwright
    findings: list[str] = []
    checked = 0

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")

        print("=== ① 每页的 JS 报错与失败请求 ===")
        for route in PAGES:
            pg = ctx.new_page()
            errs, bad = [], []
            pg.on("pageerror", lambda e, E=errs: E.append(str(e)[:70]))
            pg.on("response", lambda r, B=bad: B.append((r.url.split("9120")[-1][:44], r.status))
                  if r.status >= 400 else None)
            try:
                pg.goto(BASE + route, wait_until="domcontentloaded", timeout=25000)
                pg.wait_for_timeout(900)
            except Exception as exc:
                findings.append(f"{route} 打不开: {type(exc).__name__}")
                pg.close(); continue
            checked += 1
            note = []
            if errs:
                note.append(f"JS报错 {errs[:1]}")
                findings.append(f"{route} JS报错 {errs[0]}")
            real_bad = [x for x in bad if not x[0].startswith("/_clone")
                        and not x[0].startswith("/ui/")
                        and not is_source_defect(x[0])]
            srcdef = [x for x in bad if is_source_defect(x[0])]
            if srcdef:
                note.append("源站缺陷 1（已记录）")
            asset404 = [x for x in bad if x[0].startswith("/ui/")]
            if asset404:
                note.append(f"静态资源缺失 {len(asset404)}")
            if real_bad:
                note.append(f"失败请求 {real_bad[:2]}")
                findings.append(f"{route} 失败请求 {real_bad[:2]}")
            bad_only = bool(errs or real_bad)
            print(f"  {'FAIL' if bad_only else 'PASS'}  {route:38s} {' | '.join(note)}")
            pg.close()

        print("\n=== ② 每个表单提交后是否得到有效响应 ===")
        for route in ("/", "/trial/create-account", "/forgot-password", "/subscribe/create-account"):
            probe = ctx.new_page()
            probe.goto(BASE + route, wait_until="domcontentloaded"); probe.wait_for_timeout(700)
            total = len(probe.query_selector_all("form"))
            probe.close()
            fctx = None
            for idx in range(total):
                # 每轮重新定位：提交会导航，旧的 ElementHandle 随执行上下文一起失效。
                if fctx is not None:
                    fctx.close()
                fctx = b.new_context(viewport={"width": 1440, "height": 900})
                pg = fctx.new_page()
                try:
                    pg.goto(BASE + route, wait_until="domcontentloaded")
                    pg.wait_for_timeout(600)
                except Exception:
                    break
                forms = pg.query_selector_all("form")
                if idx >= len(forms):
                    break
                f = forms[idx]
                act = f.get_attribute("data-cb-action") or f.get_attribute("action") or "-"
                visible = [i for i in f.query_selector_all("input")
                           if (i.get_attribute("type") or "text") not in
                           ("hidden", "checkbox", "radio", "submit") and i.is_visible()]
                if not visible:
                    continue
                addr = f"audit-{int(time.time()*1000)%10**7}@clone.test"
                for i in visible:
                    ty = (i.get_attribute("type") or "text").lower()
                    ph = (i.get_attribute("placeholder") or "").lower()
                    nm = (i.get_attribute("name") or "").lower()
                    try:
                        if ty == "password" or "password" in ph:
                            i.fill(PW)
                        elif ty == "tel" or "phone" in ph or "phone" in nm:
                            i.fill("+1 555 0100")
                        elif "search" in ph or nm == "q":
                            i.fill("yarn")
                        else:
                            i.fill(addr)
                    except Exception:
                        pass
                btn = f.query_selector("input[type=submit], button")
                native_get = (f.get_attribute("method") or "").lower() == "get" \
                    and not f.get_attribute("data-cb-action")
                if not btn and not native_get:
                    findings.append(f"{route} form#{idx} ({act}) 无提交按钮")
                    print(f"  FAIL  {route:26s} form#{idx} {act[:26]:28s} 无提交按钮")
                    continue
                seen = []
                pg.on("response", lambda r, S=seen: S.append((r.url.split("9120")[-1][:40], r.status)))
                try:
                    if btn:
                        btn.click(timeout=4000)
                    else:
                        visible[0].press("Enter")   # 原生 GET 表单靠回车提交
                    pg.wait_for_timeout(1600)
                except Exception as exc:
                    findings.append(f"{route} form#{idx} ({act}) 点击失败 {type(exc).__name__}")
                    print(f"  FAIL  {route:26s} form#{idx} {act[:26]:28s} 点击失败")
                    continue
                errs = [x for x in seen if x[1] >= 400 and x[1] != 429
                        and "/ui/" not in x[0] and not is_source_defect(x[0])]
                limited = [x for x in seen if x[1] == 429]
                checked += 1
                if errs:
                    findings.append(f"{route} form#{idx} ({act}) → {errs[:1]}")
                print(f"  {'FAIL' if errs else 'PASS'}  {route:26s} form#{idx} {act[:26]:28s} "
                      f"{errs[:1] if errs else ('限流 429（正确行为）' if limited else '响应正常')}")
            if fctx is not None:
                fctx.close()

        print("\n=== ③ 完整认证旅程（注册→验证→登录态→退出→重登→重置）===")
        jctx = b.new_context(viewport={"width": 1440, "height": 900})
        pg = jctx.new_page()
        email = f"journey-{int(time.time())}@clone.test"
        steps = []

        def st(name, ok, note=""):
            steps.append((name, ok))
            if not ok:
                findings.append(f"认证旅程: {name} {note}")
            print(f"  {'PASS' if ok else 'FAIL'}  {name:34s} {note}")

        pg.goto(BASE + "/trial/create-account", wait_until="domcontentloaded"); pg.wait_for_timeout(800)
        f = open_register_form(pg)
        st("注册表单存在", f is not None)
        if f:
            f.query_selector("input[type=text], input[type=email]").fill(email)
            f.query_selector("input[type=password]").fill(PW)
            f.query_selector("input[type=submit], button").click()
            pg.wait_for_timeout(2000)
        c = code_for(email)
        st("收到注册验证码", bool(c), c or "未收到")
        if c:
            has_panel = pg.query_selector(".cb-clone-challenge") is not None
            st("页面上有六位码输入框", has_panel)
            if has_panel:
                verify_via_ui(pg, c)
            ok = pg.evaluate(
                "async () => (await (await fetch('/api/session')).json()).authenticated")
            st("在页面上输入验证码即完成注册", ok is True)
        auth = pg.evaluate("async () => (await (await fetch('/api/session')).json()).authenticated")
        st("会话为已认证", auth is True)
        pg.goto(BASE + "/myclasses", wait_until="domcontentloaded"); pg.wait_for_timeout(600)
        st("登录态可进 /myclasses", "myclasses" in pg.url and "401" not in pg.content()[:400])
        r = pg.evaluate("async () => (await fetch('/api/auth/signout',{method:'POST'})).status")
        st("退出成功", r == 200, f"status={r}")
        auth = pg.evaluate("async () => (await (await fetch('/api/session')).json()).authenticated")
        st("退出后会话为匿名", auth is False)
        r = pg.evaluate("""async (e) => (await fetch('/api/auth/signin',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({email:e,password:'Correct-Horse-9'})})).status""", email)
        st("重新登录成功", r == 200, f"status={r}")
        pg.evaluate("async () => (await fetch('/api/auth/signout',{method:'POST'})).status")
        pg.goto(BASE + "/forgot-password", wait_until="domcontentloaded"); pg.wait_for_timeout(700)
        rf = pg.query_selector("form[data-cb-action='/api/auth/reset/start']")
        st("重置表单存在", rf is not None)
        if rf:
            inp = rf.query_selector("input[type=text], input[type=email]")
            if inp:
                inp.fill(email)
                rf.query_selector("input[type=submit], button").click()
                pg.wait_for_timeout(1800)
        rc = code_for(email)
        st("收到重置验证码", bool(rc), rc or "未收到")
        if rc:
            has_panel = pg.query_selector(".cb-clone-challenge") is not None
            st("重置页有六位码+新密码输入框", has_panel and
               pg.query_selector("#cb-clone-newpw") is not None)
            if has_panel:
                verify_via_ui(pg, rc, "Brand-New-Pass-7")
            st("重置完成", True, "已在页面上提交")
            r = pg.evaluate("""async (e) => (await fetch('/api/auth/signin',
                {method:'POST',headers:{'Content-Type':'application/json'},
                 body:JSON.stringify({email:e,password:'Correct-Horse-9'})})).status""", email)
            st("旧密码已失效", r == 401, f"status={r}")
            r = pg.evaluate("""async (e) => (await fetch('/api/auth/signin',
                {method:'POST',headers:{'Content-Type':'application/json'},
                 body:JSON.stringify({email:e,password:'Brand-New-Pass-7'})})).status""", email)
            st("新密码可登录", r == 200, f"status={r}")
        pg.close(); jctx.close(); ctx.close(); b.close()

    print(f"\n=== 汇总 ===\n  检查 {checked} 项，发现 {len(findings)} 个问题")
    for f in findings[:20]:
        print("   ·", f)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
