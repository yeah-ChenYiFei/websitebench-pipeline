#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""其余 trace 的浏览器自查：测验、证书、评分、收藏、偏好、空结果、
权限失败态、帮助/联系、品牌化 404。

依旧只认浏览器里的结果，并且每条都带一个负面用例 —— 只证明"正常路径能过"
的检查，恰好漏掉的就是用户会撞上的那些状态。
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
        print(f"  {'PASS' if ok else 'FAIL'}  {name:40s} {note}")

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])

        print("=== 匿名态：权限失败必须是 401，且不泄露数据 ===")
        anon = b.new_context(); ap = anon.new_page()
        ap.goto(BASE, wait_until="domcontentloaded"); ap.wait_for_timeout(500)
        for ep in ("/api/myclasses", "/api/orders", "/api/preferences", "/api/certificate"):
            r = ap.evaluate("""async (e) => { const r = await fetch(e);
                return [r.status, (await r.text()).slice(0,120)]; }""", ep)
            leaked = any(k in r[1].lower() for k in ("account_", "email", "@"))
            st(f"匿名 {ep}", r[0] in (401, 403) and not leaked,
               f"status={r[0]}{' 疑似泄露' if leaked else ''}")

        print("\n=== 品牌化 404 与边界页是两回事 ===")
        r = ap.goto(f"{BASE}/definitely-not-a-real-page-xyz", wait_until="domcontentloaded")
        st("未知路由回 404", r.status == 404, f"status={r.status}")
        nf = ap.content()
        st("404 是品牌页而非裸文本", "creativebug" in nf.lower() and len(nf) > 3000,
           f"{len(nf)} 字节")
        r2 = ap.goto(f"{BASE}/_clone/out-of-scope", wait_until="domcontentloaded")
        st("边界页回 200", r2.status == 200, f"status={r2.status}")
        st("边界页与 404 内容不同", ap.content() != nf)

        print("\n=== 搜索无结果状态 ===")
        ap.goto(f"{BASE}/search/ui?q=zzzz-no-match-websitebench", wait_until="domcontentloaded")
        ap.wait_for_timeout(900)
        body = ap.inner_text("body").lower()
        st("无结果页给出可见提示", "no classes" in body or "no results" in body,
           body[:60].replace("\n", " "))
        ap.goto(f"{BASE}/search/ui?q=quilting", wait_until="domcontentloaded")
        ap.wait_for_timeout(1200)
        hit = ap.inner_text("body").lower()
        cards = ap.evaluate(
            "() => document.querySelectorAll('.cb-clone-search .card').length")
        st("有结果页渲染出结果（可见）", "results for" in hit, f"可见卡片 {cards}")
        anon.close()

        print("\n=== 登录态：测验 / 证书 / 评分 / 收藏 / 偏好 ===")
        ctx = b.new_context(); pg = ctx.new_page()
        email = f"rest-{int(time.time())}@clone.test"
        pg.goto(f"{BASE}/trial/create-account", wait_until="domcontentloaded")
        pg.wait_for_timeout(600)
        f = open_register_form(pg)
        f.query_selector("input[type=text], input[type=email]").fill(email)
        f.query_selector("input[type=password]").fill(PW)
        f.query_selector("input[type=submit], button").click(); pg.wait_for_timeout(1600)
        c = code_for(email)
        verify_via_ui(pg, c)
        st("登录态建立", pg.evaluate(
            "async () => (await (await fetch('/api/session')).json()).authenticated") is True)

        info = pg.evaluate("""async () => { const s = await (await fetch(
            '/api/search?level=beginner')).json();
            const r = (s.results||s.rows)[0];
            await fetch('/api/enroll',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({class_id:r.class_id,track:'audit'})});
            return r; }""")
        cid, units = info["class_id"], info.get("unit_count") or 1

        # 测验：客户端自称答对不算数
        q = pg.evaluate("""async (cid) => { const r = await fetch('/api/quiz',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:cid,question_id:'q1',answer:'__wrong__',correct:true})});
            return [r.status, await r.json()]; }""", cid)
        st("测验由服务端判分", q[0] == 200 and q[1].get("correct") is not True,
           json.dumps(q[1])[:56])

        # 证书：未完成时不得签发
        cert = pg.evaluate("""async (cid) => { const r = await fetch('/api/certificate',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:cid})}); return [r.status, await r.json()]; }""", cid)
        st("未完课不发证书（409）", cert[0] == 409, f"status={cert[0]}")
        for i in range(units):
            pg.evaluate("""async (a) => fetch('/api/progress',{method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({class_id:a[0],unit_id:'unit-'+a[1],watched:1})})""",
                        [cid, i + 1])
        cert2 = pg.evaluate("""async (cid) => { const r = await fetch('/api/certificate',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:cid})}); return [r.status, await r.json()]; }""", cid)
        st("完课后可发证书", cert2[0] == 200, f"status={cert2[0]}")

        rt = pg.evaluate("""async (cid) => { const r = await fetch('/api/rating',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:cid,stars:5,review:'good'})});
            return [r.status, await r.json()]; }""", cid)
        st("可以评分", rt[0] == 200, f"status={rt[0]}")
        bad = pg.evaluate("""async (cid) => (await fetch('/api/rating',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:cid,stars:99})})).status""", cid)
        st("非法星级被拒", bad == 400, f"status={bad}")
        zero = pg.evaluate("""async (cid) => (await fetch('/api/rating',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:cid,stars:0})})).status""", cid)
        st("0 星被拒", zero == 400, f"status={zero}")
        ghost = pg.evaluate("""async () => (await fetch('/api/rating',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:'no-such-class',stars:5})})).status""")
        st("给不存在的课评分被拒", ghost == 404, f"status={ghost}")

        wl = pg.evaluate("""async (cid) => { const r = await fetch('/api/watchlist',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({class_id:cid})}); return [r.status, await r.json()]; }""", cid)
        st("收藏成功", wl[0] == 200, f"status={wl[0]}")

        pr = pg.evaluate("""async () => { const r = await fetch('/api/preferences',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({preferences:{email_optin:'false'}})});
            return [r.status, await r.json()]; }""")
        st("保存偏好", pr[0] == 200, f"status={pr[0]}")
        got = pg.evaluate("async () => (await (await fetch('/api/preferences')).json())")
        st("偏好确实被持久化",
           (got.get("preferences") or {}).get("email_optin") == "false",
           json.dumps(got)[:56])

        print("\n=== 帮助 / 联系（匿名可用且不回账户数据）===")
        an2 = b.new_context(); p2 = an2.new_page()
        p2.goto(BASE, wait_until="domcontentloaded"); p2.wait_for_timeout(400)
        ct = p2.evaluate("""async () => { const r = await fetch('/api/contact',
            {method:'POST',headers:{'Content-Type':'application/json'},
             body:JSON.stringify({topic:'billing',body:'I need help with my order.'})});
            return [r.status, await r.text()]; }""")
        st("匿名可提交联系表单", ct[0] == 200, f"status={ct[0]}")
        st("联系响应不含账户数据", "account_" not in ct[1], ct[1][:56])
        an2.close(); ctx.close(); b.close()

    print(f"\n=== 汇总 ===\n  检查 {n} 项，失败 {len(fails)} 项")
    for x in fails:
        print("   ·", x)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
