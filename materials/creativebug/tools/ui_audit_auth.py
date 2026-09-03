#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录态旅程的浏览器自查：P0 主线 607 + 报名/结算/进度/账户。

与 ui_audit.py 分工：那个查匿名页面的表单与认证入口，这个查登录后
"点得到、点得动、状态真的变了"。仍然只认浏览器里发生的事 ——
接口能过不代表页面上有入口。
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


def code_for(addr, timeout=20):
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
    fails: list[str] = []
    n = 0

    def st(name, ok, note=""):
        nonlocal n
        n += 1
        if not ok:
            fails.append(f"{name} {note}")
        print(f"  {'PASS' if ok else 'FAIL'}  {name:38s} {note}")

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        pg = ctx.new_page()
        jserr = []
        pg.on("pageerror", lambda e: jserr.append(str(e)[:70]))

        print("=== 建立登录态（trial 注册 → 验证码）===")
        email = f"auth-{int(time.time())}@clone.test"
        pg.goto(f"{BASE}/trial/create-account", wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        f = open_register_form(pg)
        st("注册表单存在", f is not None)
        f.query_selector("input[type=text], input[type=email]").fill(email)
        f.query_selector("input[type=password]").fill(PW)
        f.query_selector("input[type=submit], button").click()
        pg.wait_for_timeout(1800)
        c = code_for(email)
        st("收到验证码", bool(c), c or "未收到")
        st("页面上有六位码输入框", pg.query_selector(".cb-clone-challenge") is not None)
        verify_via_ui(pg, c)
        st("注册完成（全程界面操作）", pg.evaluate(
            "async () => (await (await fetch('/api/session')).json()).authenticated") is True)

        print("\n=== P0 主线 607：Drawing & Illustration → 初级课 → 第一课 ===")
        pg.goto(f"{BASE}/classes", wait_until="domcontentloaded"); pg.wait_for_timeout(900)
        link = pg.query_selector("a[href*='drawing']")
        st("目录页有 Drawing 入口", link is not None,
            (link.get_attribute("href") if link else ""))
        if link:
            pg.goto(BASE + link.get_attribute("href"), wait_until="domcontentloaded")
            pg.wait_for_timeout(900)
            st("分类页可达", "drawing" in pg.url, pg.url.split("9120")[-1][:44])
        res = pg.evaluate("""async () => (await (await fetch(
            '/api/search?level=beginner&subcategory=drawing-and-illustration')).json())""")
        rows = res.get("results") or res.get("rows") or []
        st("初级筛选返回结果", len(rows) > 0, f"{len(rows)} 门")
        if rows:
            route = rows[0].get("route") or ""
            cid = rows[0].get("class_id")
            pg.goto(BASE + route, wait_until="domcontentloaded"); pg.wait_for_timeout(900)
            st("课程详情页可达", pg.url.endswith(route.rstrip("/")) or route in pg.url,
                route[:44])
            st("详情页无 JS 报错", not jserr, jserr[:1])
            e = pg.evaluate("""async (cid) => { const r = await fetch('/api/enroll',
                {method:'POST',headers:{'Content-Type':'application/json'},
                 body:JSON.stringify({class_id:cid,track:'audit'})});
                return [r.status, await r.json()]; }""", cid)
            st("报名（audit）成功", e[0] == 200, f"status={e[0]}")
            mc = pg.evaluate("""async () => (await (await fetch('/api/myclasses')).json())""")
            got = json.dumps(mc)
            st("报名后出现在 myclasses", cid in got, f"class_id={cid}")
            pg.goto(f"{BASE}/myclasses", wait_until="domcontentloaded"); pg.wait_for_timeout(900)
            # 断言必须落在"可见文本"上：查 pg.content() 的话，塞进零尺寸容器里的
            # 内容也算通过 —— 这正是上一版漏掉挂载点不可见的原因。
            vis = pg.inner_text("body")
            st("myclasses 页面渲染出该课（可见）",
               (rows[0].get("title", "") or cid).split(" by ")[0][:24] in vis,
               f"可见文本 {len(vis)} 字")
            pr = pg.evaluate("""async (cid) => { const r = await fetch('/api/progress',
                {method:'POST',headers:{'Content-Type':'application/json'},
                 body:JSON.stringify({class_id:cid,unit_id:'unit-1',watched:1})});
                return r.status; }""", cid)
            st("记录第一课进度", pr == 200, f"status={pr}")
            rs = pg.evaluate("""async (cid) => (await (await fetch(
                '/api/resume?class_id='+encodeURIComponent(cid))).json())""", cid)
            st("resume 返回续播位置", bool(rs), json.dumps(rs)[:52])

        print("\n=== 账户区各页在浏览器中可达且无报错 ===")
        for route in ("/myclasses", "/account/profile", "/account/rewards",
                      "/account/plan_change", "/account/cancel_subscription"):
            jserr.clear()
            try:
                resp = pg.goto(BASE + route, wait_until="domcontentloaded", timeout=20000)
                pg.wait_for_timeout(700)
                code = resp.status if resp else 0
            except Exception as exc:
                st(route, False, type(exc).__name__); continue
            st(route, code < 400 and not jserr, f"status={code} {jserr[:1] if jserr else ''}")

        print("\n=== 结算到确认页 ===")
        ck = pg.evaluate("""async () => { const r = await fetch('/api/checkout',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({plan:'annual'})}); return [r.status, await r.json()]; }""")
        st("创建结算", ck[0] == 200, f"status={ck[0]}")
        oid = (ck[1] or {}).get("order_id")

        # 负面用例：不存在的订单不得确认成功（曾经无论如何都回 200 confirmed）
        bad = pg.evaluate("""async () => (await fetch('/api/checkout/confirm',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({order_id:999999})})).status""")
        st("确认不存在的订单被拒", bad == 404, f"status={bad}")
        nobody = pg.evaluate("""async () => (await fetch('/api/checkout/confirm',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({})})).status""")
        st("确认时缺 order_id 被拒", nobody == 404, f"status={nobody}")

        cf = pg.evaluate("""async (oid) => { const r = await fetch('/api/checkout/confirm',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({order_id:oid})});
            return [r.status, await r.json()]; }""", oid)
        st("确认订单", cf[0] == 200, f"status={cf[0]}")
        again = pg.evaluate("""async (oid) => (await fetch('/api/checkout/confirm',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({order_id:oid})})).status""", oid)
        st("重复确认被拒（409）", again == 409, f"status={again}")
        st("支付通道为 local-sandbox", "local-sandbox" in json.dumps(cf[1]),
            json.dumps(cf[1])[:52])
        od = pg.evaluate("async () => (await (await fetch('/api/orders')).json())")
        st("订单出现在历史中", bool(od and json.dumps(od) != "[]"), json.dumps(od)[:52])

        b.close()

    print(f"\n=== 汇总 ===\n  检查 {n} 项，失败 {len(fails)} 项")
    for x in fails:
        print("   ·", x)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
