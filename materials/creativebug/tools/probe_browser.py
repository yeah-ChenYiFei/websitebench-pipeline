"""G0 单页可行性探针：真实浏览器加载一次首页，判断 WAF challenge 能否自然通过。
只加载 1 个页面，不爬取。"""
import sys
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = b.new_context(user_agent=UA, viewport={"width": 1440, "height": 900},
                        locale="en-US", timezone_id="America/Los_Angeles")
    pg = ctx.new_page()
    r = pg.goto("https://www.creativebug.com/", wait_until="domcontentloaded", timeout=60000)
    print("首次响应:", r.status if r else None)
    pg.wait_for_timeout(6000)          # 给 challenge.js 解题 + reload 的时间
    try:
        pg.wait_for_load_state("load", timeout=20000)
    except Exception as e:
        print("load 等待超时:", type(e).__name__)
    html = pg.content()
    text = pg.evaluate("document.body ? document.body.innerText : ''")
    title = pg.title()
    links = pg.evaluate("""() => [...document.querySelectorAll('a[href]')]
        .map(a => a.href).filter(h => h.includes('creativebug.com'))
        .map(h => new URL(h).pathname.replace(/\\/$/,'') || '/')""")
    cookies = [c["name"] for c in ctx.cookies()]
    print("最终 URL:", pg.url)
    print("title:", repr(title))
    print("DOM 字节:", len(html), " 正文词数:", len(text.split()))
    print("站内唯一路由:", len(set(links)))
    print("cookie 名:", cookies)
    print("challenge 残留:", "gokuProps" in html)
    open("recon/home-outlinks.txt", "w").write("\n".join(sorted(set(links))) + "\n")
    open("recon/root.browser.html", "w").write(html)
    b.close()
