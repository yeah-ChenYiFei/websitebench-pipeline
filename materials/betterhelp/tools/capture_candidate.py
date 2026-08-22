from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8458"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "offline-clone" / "candidate-capture"
OUT.mkdir(parents=True, exist_ok=True)

ROUTES = [
    ("home", "/"),
    ("get-started", "/get-started/"),
    ("get-started-state", "/get-started/?skip_redirect_question=1"),
    ("login", "/login/"),
    ("signup", "/signup/"),
    ("about", "/about/"),
    ("faq", "/faq/"),
    ("reviews", "/reviews/"),
]

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    )
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    records = []
    for name, path in ROUTES:
        requests: list[str] = []
        handler = lambda req: requests.append(req.url)
        page.on("request", handler)
        response = page.goto(BASE + path, wait_until="networkidle")
        page.screenshot(path=str(OUT / f"route-{name}.png"), full_page=True)
        page.remove_listener("request", handler)
        records.append(
            {
                "id": name,
                "path": path,
                "status": response.status if response else None,
                "title": page.title(),
                "text_excerpt": page.locator("body").inner_text()[:240],
                "requests": sorted(set(requests)),
            }
        )
    for width, height, name in (
        (1440, 900, "home-desktop-1440x900"),
        (768, 1024, "home-tablet-768x1024"),
        (390, 844, "home-mobile-390x844"),
    ):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(BASE + "/", wait_until="networkidle")
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    (ROOT / "artifacts" / "offline-clone" / "candidate-network-audit.json").write_text(
        json.dumps(
            {
                "schema_version": "betterhelp.candidate-network-audit.v1",
                "base_url": BASE,
                "runtime_remote_requests": "forbidden",
                "routes": records,
                "external_requests": sorted(
                    {
                        url
                        for record in records
                        for url in record["requests"]
                        if not url.startswith(BASE)
                    }
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    browser.close()
print(json.dumps({"routes": len(records), "capture_dir": str(OUT)}))
