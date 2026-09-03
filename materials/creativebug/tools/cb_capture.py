#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""creativebug A1 取证脚本 —— 在你自己的 Windows 机器上跑。

分工：人过质询 + 人登录（一次），机器走页（机械劳动）。
会话留在本机的浏览器 profile 里，profile 永不进上传包。

四个模式：
  python cb_capture.py recon           # 第一步：侦查，约 1 分钟
  python cb_capture.py login           # 第二步：开浏览器，你手动登录，关窗即存
  python cb_capture.py capture --urls urls.txt
  python cb_capture.py pack            # 打包（自动排除 profile / cookie）

依赖只有一个：
  pip install playwright && playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import random
import hashlib
import re
import sys
import time
import urllib.parse as up
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.creativebug.com"
HOSTS = ("creativebug.com", "www.creativebug.com")
HERE = Path(__file__).resolve().parent
OUT = HERE / "cb-out"                 # 要上传的产物
PROFILE = HERE / "cb-profile"         # 浏览器 profile：含 cookie，**永不上传**
STATE = OUT / "_state.jsonl"          # 断点续抓日志

# G1 配方：钉死视口/时区/locale，UA 用本机真实 Chrome 的（不覆盖，避免指纹自相矛盾）
VIEWPORT = {"width": 1440, "height": 900}
TZ = "America/Los_Angeles"
LOCALE = "en-US"


def _ctx(p, headless: bool):
    """持久化上下文：质询与登录状态都留在 PROFILE 里，跑第二次不用重来。"""
    PROFILE.mkdir(parents=True, exist_ok=True)
    kw = dict(user_data_dir=str(PROFILE), headless=headless, viewport=VIEWPORT,
              locale=LOCALE, timezone_id=TZ, args=["--disable-blink-features=AutomationControlled"])
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **kw)   # 优先本机真实 Chrome
    except Exception:
        return p.chromium.launch_persistent_context(**kw)                     # 回落 playwright chromium


def _blocked(page) -> bool:
    """WAF 质询特征。命中就退避，不加码。"""
    try:
        if "human verification" in (page.title() or "").lower():
            return True
        return "gokuProps" in page.content()
    except Exception:
        return False


def _settle(page):
    """滚 8 次触发懒加载，再回顶。"""
    try:
        page.wait_for_load_state("load", timeout=25000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    for _ in range(8):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(250)
    page.wait_for_timeout(1500)
    try:
        page.evaluate("window.scrollTo(0,0)")
    except Exception:
        pass


def _links(page) -> list[str]:
    try:
        return page.evaluate(
            """() => [...document.querySelectorAll('a[href]')].map(a => a.href)"""
        ) or []
    except Exception:
        return []


def _paths(urls) -> set[str]:
    out = set()
    for u in urls:
        try:
            q = up.urlparse(u)
        except ValueError:
            continue
        if q.scheme in ("http", "https") and q.netloc in HOSTS:
            out.add((q.path.rstrip("/") or "/"))
    return out


def _safe(path: str) -> Path:
    """路由 → 本地目录名。只允许安全字符，超长走哈希，避免 Windows 路径炸掉。"""
    rel = (path.strip("/") or "index")
    rel = re.sub(r"[^A-Za-z0-9._/\-]", "_", rel)
    parts = [seg[:60] for seg in rel.split("/") if seg]
    if sum(len(x) for x in parts) > 150:
        import hashlib
        parts = [parts[0][:40], hashlib.sha1(rel.encode()).hexdigest()[:16]]
    return OUT / "pages" / Path(*parts)


# ---------------------------------------------------------------- recon
def cmd_recon(_args):
    from playwright.sync_api import sync_playwright

    d = OUT / "recon"
    d.mkdir(parents=True, exist_ok=True)
    report: dict = {"captured_at": datetime.now(timezone.utc).isoformat()}

    with sync_playwright() as p:
        ctx = _ctx(p, headless=False)      # 有头：万一真弹质询你能亲手过
        page = ctx.new_page()
        print("[1/4] 打开首页 …")
        r = page.goto(BASE + "/", wait_until="domcontentloaded", timeout=90000)
        report["home_status"] = r.status if r else None
        _settle(page)
        if _blocked(page):
            print("!! 首页仍是 Human Verification。请在弹出的窗口里手动过一次质询，")
            print("   过完后回到这里按 Enter 继续。")
            input()
            page.reload(wait_until="domcontentloaded")
            _settle(page)
        html = page.content()
        (d / "home.html").write_text(html, encoding="utf-8")
        report["home_bytes"] = len(html)
        report["home_title"] = page.title()
        report["user_agent"] = page.evaluate("navigator.userAgent")
        report["blocked"] = _blocked(page)

        print("[2/4] 抽首页出链（D0 闭合目标）…")
        home_paths = sorted(_paths(_links(page)))
        (d / "home-outlinks.txt").write_text("\n".join(home_paths) + "\n", encoding="utf-8")
        report["home_outlinks"] = len(home_paths)
        seg: dict[str, int] = {}
        for x in home_paths:
            k = x.split("/")[1] if x != "/" else "(root)"
            seg[k] = seg.get(k, 0) + 1
        report["home_first_segments"] = dict(sorted(seg.items(), key=lambda kv: -kv[1])[:30])

        print("[3/4] robots + sitemap（路由权威）…")
        for name, path in (("robots", "/robots.txt"),
                           ("sitemap", "/sitemap.xml"),
                           ("sitemap_index", "/sitemap_index.xml")):
            try:
                resp = ctx.request.get(BASE + path, timeout=45000)
                body = resp.body()
                (d / f"{name}.txt").write_bytes(body)
                report[f"{name}_status"] = resp.status
                report[f"{name}_bytes"] = len(body)
            except Exception as exc:
                report[f"{name}_status"] = f"ERROR {type(exc).__name__}"

        print("[4/4] 登录态判定（不登录，只看当前状态）…")
        text = (page.evaluate("document.body?document.body.innerText:''") or "").lower()
        report["sees_signin_word"] = any(w in text for w in ("sign in", "log in", "login"))
        report["sees_account_word"] = any(w in text for w in ("my account", "sign out", "log out", "dashboard"))
        ctx.close()

    (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== recon 完成 ===")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\n产物在 {d}")
    print("下一步：python cb_capture.py login")


# ---------------------------------------------------------------- login
def cmd_login(_args):
    from playwright.sync_api import sync_playwright

    print("即将打开浏览器。请你手动完成：")
    print("  1. 如果出现 Human Verification，等它自己过或按提示点一下")
    print("  2. 用你的 free trial 账号登录")
    print("  3. 登录后随便点两下（进 dashboard / My Classes / 账户菜单看看）")
    print("  4. 回到这个终端按 Enter —— 会话会存进本机 profile，不会上传\n")
    with sync_playwright() as p:
        ctx = _ctx(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=90000)
        input(">>> 登录完成后按 Enter …")

        d = OUT / "recon"
        d.mkdir(parents=True, exist_ok=True)
        _settle(page)
        (d / "after-login.html").write_text(page.content(), encoding="utf-8")
        links = sorted(_paths(_links(page)))
        (d / "after-login-outlinks.txt").write_text("\n".join(links) + "\n", encoding="utf-8")
        info = {
            "landing_url": page.url,
            "title": page.title(),
            "outlinks": len(links),
            "body_words": len((page.evaluate("document.body?document.body.innerText:''") or "").split()),
            "new_vs_anon": sorted(set(links) - set(
                (d / "home-outlinks.txt").read_text(encoding="utf-8").split()
                if (d / "home-outlinks.txt").is_file() else []))[:60],
        }
        (d / "after-login.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n登录态落点：", info["landing_url"], "|", info["title"])
        print("登录后新增的站内路由（前 60 条）：")
        for x in info["new_vs_anon"]:
            print("   ", x)
        ctx.close()
    print("\n下一步：把 cb-out/recon/ 打包发我（python cb_capture.py pack），我据此定路由清单。")


# ---------------------------------------------------------------- capture
def cmd_capture(args):
    from playwright.sync_api import sync_playwright

    urls = [x.strip() for x in Path(args.urls).read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.limit:
        urls = urls[: args.limit]
    done: set[str] = set()
    if STATE.is_file():
        for line in STATE.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if rec.get("ok"):
                    done.add(rec["path"])
            except Exception:
                pass
    todo = [u for u in urls if u not in done]
    print(f"共 {len(urls)} 条，已完成 {len(done)}，待抓 {len(todo)}")
    OUT.mkdir(parents=True, exist_ok=True)

    ok = fail = 0
    with sync_playwright() as p:
        ctx = _ctx(p, headless=args.headless)
        page = ctx.new_page()
        with STATE.open("a", encoding="utf-8") as log:
            for i, path in enumerate(todo, 1):
                url = BASE + path if path.startswith("/") else path
                rec = {"path": path, "ok": False}
                try:
                    r = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    rec["status"] = r.status if r else None
                    _settle(page)
                    if _blocked(page):
                        # 退避，不加码。连续命中就停下来交回给人。
                        print(f"  !! 第 {i} 条触发质询，退避 60s …")
                        page.wait_for_timeout(60000)
                        page.reload(wait_until="domcontentloaded")
                        _settle(page)
                        if _blocked(page):
                            print("  !! 仍被质询。停止抓取——请手动过一次质询后重跑本命令（会断点续抓）。")
                            log.write(json.dumps({**rec, "error": "waf-challenge"}, ensure_ascii=False) + "\n")
                            break
                    html = page.content()
                    dest = _safe(path)
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / "index.html").write_text(html, encoding="utf-8")
                    rec.update(ok=True, bytes=len(html), title=page.title(),
                               final=page.url, dir=str(dest.relative_to(OUT)).replace("\\", "/"))
                    ok += 1
                except Exception as exc:
                    rec["error"] = f"{type(exc).__name__}: {exc}"[:200]
                    fail += 1
                log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                log.flush()
                if i % 25 == 0 or i == len(todo):
                    print(f"  进度 {i}/{len(todo)}  ok={ok} fail={fail}")
                time.sleep(random.uniform(1.4, 2.6))   # 并发 1 + 真实间隔
        ctx.close()
    print(f"\n完成 ok={ok} fail={fail}")
    print("下一步：python cb_capture.py pack")


# ---------------------------------------------------------------- assets
def cmd_assets(args):
    """在页面上下文里下载资产。

    不能用 ctx.request.get()：那是裸 HTTP 请求，不带 Sec-Fetch-Dest / Sec-Fetch-Mode /
    Referer，AWS WAF 判定为非浏览器流量并返回 202 质询（实测 158 个里挡掉 151 个）。
    改成在已过质询的页面里跑 fetch()，由浏览器自己发请求，头和 cookie 都是真的。
    """
    from playwright.sync_api import sync_playwright

    urls = [u.strip() for u in Path(args.urls).read_text(encoding="utf-8").splitlines() if u.strip()]
    dest = OUT / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    log = OUT / "_assets_state.jsonl"
    done = set()
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if r.get("ok"):
                    done.add(r["url"])
            except Exception:
                pass
    todo = [u for u in urls if u not in done]
    print(f"共 {len(urls)}，已完成 {len(done)}，待下 {len(todo)}")

    JS = """async (u) => {
      try {
        const r = await fetch(u, {credentials: 'include', mode: 'cors'});
        if (!r.ok) return {status: r.status, b64: null};
        const buf = new Uint8Array(await r.arrayBuffer());
        let s = ''; const CH = 0x8000;
        for (let i = 0; i < buf.length; i += CH)
          s += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
        return {status: r.status, b64: btoa(s)};
      } catch (e) { return {status: -1, error: String(e)}; }
    }"""

    ok = fail = 0
    with sync_playwright() as p:
        ctx = _ctx(p, headless=args.headless)
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=90000)
        _settle(page)
        if _blocked(page):
            print("!! 仍被质询，请在窗口里手动过一次后按 Enter")
            input()
        with log.open("a", encoding="utf-8") as fh:
            for i, u in enumerate(todo, 1):
                rec = {"url": u, "ok": False}
                try:
                    # 202 = WAF 质询，实测是阵发性的（一段全挂、之后又全好），
                    # 就地退避重试即可，不必整轮重跑。
                    res = page.evaluate(JS, u)
                    for attempt in range(4):
                        if res.get("status") != 202:
                            break
                        time.sleep(6 * (attempt + 1))
                        page.reload(wait_until="domcontentloaded")
                        if _blocked(page):
                            page.wait_for_timeout(8000)
                        res = page.evaluate(JS, u)
                    rec["status"] = res.get("status")
                    if res.get("b64"):
                        import base64
                        body = base64.b64decode(res["b64"])
                        name = re.sub(r"[^A-Za-z0-9._-]", "_", u.split("/")[-1].split("?")[0])[:80]
                        h = hashlib.sha1(u.encode()).hexdigest()[:10]
                        (dest / f"{h}-{name}").write_bytes(body)
                        rec.update(ok=True, bytes=len(body), file=f"{h}-{name}")
                        ok += 1
                    else:
                        fail += 1
                except Exception as exc:
                    rec["error"] = f"{type(exc).__name__}: {exc}"[:160]
                    fail += 1
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                if i % 25 == 0 or i == len(todo):
                    print(f"  进度 {i}/{len(todo)}  ok={ok} fail={fail}")
                time.sleep(random.uniform(0.3, 0.7))
        ctx.close()
    print(f"\n完成 ok={ok} fail={fail}\n下一步：python cb_capture.py pack")


def cmd_shots(args):
    """拍源站参照帧 —— 像素相似度的比较基准。

    必须在你机器上跑：服务器侧被 WAF 挡着，拍不到源站。
    视口尺寸与时区钉死，与 checkpoints.json 的 viewports 一致，
    否则同一页两次拍出来就有假差异。
    """
    from playwright.sync_api import sync_playwright

    shots = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    dest = OUT / "reference"
    dest.mkdir(parents=True, exist_ok=True)
    VP = {"desktop": {"width": 1440, "height": 900},
          "tablet": {"width": 834, "height": 1112},
          "mobile": {"width": 414, "height": 896}}
    log = OUT / "_shots_state.jsonl"
    done = set()
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if r.get("ok"):
                    done.add(r["id"])
            except Exception:
                pass
    todo = [s for s in shots if s["id"] not in done]
    print(f"共 {len(shots)} 张，已完成 {len(done)}，待拍 {len(todo)}")

    ok = fail = 0
    with sync_playwright() as p:
        ctx = _ctx(p, headless=args.headless)
        with log.open("a", encoding="utf-8") as fh:
            for i, s in enumerate(todo, 1):
                rec = {"id": s["id"], "ok": False}
                page = None
                try:
                    page = ctx.new_page()
                    page.set_viewport_size(VP[s["viewport"]])
                    r = page.goto(BASE + s["path"], wait_until="domcontentloaded", timeout=60000)
                    rec["status"] = r.status if r else None
                    _settle(page)
                    if _blocked(page):
                        print(f"  !! {s['id']} 触发质询，退避 30s")
                        page.wait_for_timeout(30000)
                        page.reload(wait_until="domcontentloaded")
                        _settle(page)
                    png = dest / f"{s['id']}.png"
                    page.screenshot(path=str(png), full_page=False)
                    rec.update(ok=True, file=png.name, bytes=png.stat().st_size)
                    ok += 1
                except Exception as exc:
                    rec["error"] = f"{type(exc).__name__}: {exc}"[:160]
                    fail += 1
                finally:
                    if page:
                        page.close()
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"  {i}/{len(todo)}  {s['id']:38s} {'OK' if rec['ok'] else 'FAIL'}")
                time.sleep(random.uniform(1.0, 2.0))
        ctx.close()
    print(f"\n完成 ok={ok} fail={fail}\n下一步：python cb_capture.py pack")


# ---------------------------------------------------------------- pack
def cmd_pack(_args):
    """只打包 cb-out/；显式排除 profile、cookie、storage_state。打包后做一次自检。"""
    if not OUT.is_dir():
        print("没有 cb-out/，先跑 recon 或 capture")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zpath = HERE / f"cb-upload-{stamp}.zip"
    # 只匹配浏览器 profile 的真实文件名，不做子串匹配 ——
    # 课程 slug 里出现 "cookie" 之类的词不该被误判（如 cookie-cutter-bird-feeders）
    banned_dirs = ("cb-profile",)
    banned_files = ("cookies", "cookies-journal", "storage_state.json",
                    "login data", "web data", "local state", "network action predictor")

    def is_session_artifact(rel: str) -> bool:
        parts = rel.lower().split("/")
        if any(d in parts for d in banned_dirs):
            return True
        return parts[-1] in banned_files
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in OUT.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(HERE).as_posix()
            if is_session_artifact(rel):
                print("  跳过（含会话痕迹）:", rel)
                continue
            z.write(f, rel)
            n += 1
    # 自检：包里不许出现 profile / cookie
    with zipfile.ZipFile(zpath) as z:
        bad = [x for x in z.namelist() if is_session_artifact(x)]
    size_mb = zpath.stat().st_size / 1024 / 1024
    print(f"\n打好了：{zpath}")
    print(f"  文件 {n} 个，{size_mb:.1f} MB")
    print(f"  会话痕迹自检：{'!! 命中 ' + str(bad) if bad else '干净（0 命中）'}")
    print(f"  profile 目录 {PROFILE} 留在本机，没有进包")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="creativebug A1 取证")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("recon")
    sub.add_parser("login")
    c = sub.add_parser("capture")
    c.add_argument("--urls", required=True)
    c.add_argument("--limit", type=int, default=0)
    c.add_argument("--headless", action="store_true")
    sh = sub.add_parser("shots")
    sh.add_argument("--plan", required=True)
    sh.add_argument("--headless", action="store_true")
    s = sub.add_parser("assets")
    s.add_argument("--urls", required=True)
    s.add_argument("--headless", action="store_true")
    sub.add_parser("pack")
    a = ap.parse_args()
    return {"recon": cmd_recon, "login": cmd_login, "capture": cmd_capture,
            "assets": cmd_assets, "shots": cmd_shots, "pack": cmd_pack}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
