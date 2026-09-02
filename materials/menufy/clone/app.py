"""Source-grounded Menufy Marketplace offline clone."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from backend.site_backend_integration import open_site_services
from websitebench.local_clone_auth import AuthError

ROOT = Path(__file__).resolve().parent
RESTAURANTS = json.loads((ROOT / "restaurants.json").read_text())
REFERENCE = json.loads((ROOT / "reference_pages.json").read_text())
RESTAURANT_HOSTS = {
    item["host"] for item in REFERENCE["pages"] if item["kind"] == "restaurant"
}
ALLOWED_SIZES = {"Regular", "Large"}
ALLOWED_SPICE_LEVELS = {"Mild", "Medium", "Hot"}
ALLOWED_EXTRAS = {"Extra sauce", "Cheese"}
MENU = [
    {
        "id": "meatballs",
        "name": "Meatballs",
        "desc": "House-made Italian meatballs with rich tomato sauce.",
        "price": 30,
    },
    {
        "id": "bisque",
        "name": "Lobster Bisque",
        "desc": "Creamy lobster bisque, one quart.",
        "price": 20,
    },
    {
        "id": "salad",
        "name": "Italian Tossed Salad",
        "desc": "Mixed greens, Italian dressing and fresh vegetables.",
        "price": 28,
    },
    {
        "id": "caesar",
        "name": "Caesar Salad",
        "desc": "Romaine, parmesan, garlic croutons and Caesar dressing.",
        "price": 35,
    },
    {
        "id": "lasagna",
        "name": "Baked Lasagna",
        "desc": "Classic baked lasagna, serves 8–10 guests.",
        "price": 70,
    },
    {
        "id": "chicken",
        "name": "Chicken Parmesan",
        "desc": "Breaded chicken, tomato sauce and melted cheese.",
        "price": 90,
    },
    {
        "id": "eggplant",
        "name": "Eggplant Parmesan",
        "desc": "Baked eggplant, tomato sauce and parmesan.",
        "price": 80,
    },
    {
        "id": "tiramisu",
        "name": "Tiramisu",
        "desc": "Traditional espresso mascarpone dessert.",
        "price": 65,
    },
]
CUISINES = [
    "All",
    "American",
    "Asian",
    "Chinese",
    "Greek",
    "Indian",
    "Italian",
    "Japanese",
    "Korean",
    "Mexican",
    "Pizza",
    "Thai",
    "Vegetarian",
]
app = FastAPI(title="Menufy")


def db():
    backend, _ = open_site_services()
    c = sqlite3.connect(backend.lifecycle.database_path)
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE IF NOT EXISTS cart(s TEXT,item TEXT,size TEXT,spice TEXT,extras TEXT,note TEXT,qty INTEGER,PRIMARY KEY(s,item,size,spice,extras,note))"
    )
    c.execute("CREATE TABLE IF NOT EXISTS fav(s TEXT,name TEXT,PRIMARY KEY(s,name))")
    c.commit()
    return c


def sid(r):
    current = r.cookies.get("__Host-menufy-session") or r.cookies.get("menufy_session")
    _, auth = open_site_services()
    token, _ = auth.ensure_session(current)
    return token, token != current


def auth_context(r):
    current = r.cookies.get("__Host-menufy-session") or r.cookies.get("menufy_session")
    _, auth = open_site_services()
    token, session = auth.ensure_session(current)
    return auth, token, session, token != current


def set_session_cookie(response, request, value):
    if request.url.scheme == "https":
        response.set_cookie(
            "__Host-menufy-session",
            value,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
    else:
        # Explicit loopback-development fallback; deployed sessions use the
        # __Host- cookie required by backend/runtime.json.
        response.set_cookie(
            "menufy_session", value, httponly=True, samesite="lax", path="/"
        )


def payload(s):
    with db() as c:
        rows = [
            dict(x)
            for x in c.execute(
                "SELECT rowid AS line_id, * FROM cart WHERE s=? ORDER BY rowid", (s,)
            )
        ]
    subtotal = 0
    for x in rows:
        m = next(y for y in MENU if y["id"] == x["item"])
        x["extras"] = json.loads(x["extras"])
        x["name"] = m["name"]
        x["line"] = (m["price"] + 2 * len(x["extras"])) * x["qty"]
        subtotal += x["line"]
    tax = round(subtotal * 0.0825, 2)
    fee = round(subtotal * 0.05, 2) if subtotal else 0
    delivery = 4.99 if subtotal else 0
    return {
        "items": rows,
        "subtotal": subtotal,
        "tax": tax,
        "service": fee,
        "delivery": delivery,
        "total": round(subtotal + tax + fee + delivery, 2),
    }


@app.get("/healthz")
def health():
    return {"ok": True, "site_id": "menufy"}


@app.get("/__websitebench/health")
def hhealth():
    return {"status": "ok"}


@app.get("/static/{name}")
def static(name: str):
    if name not in {
        "hero.jpg",
        "home-hero.jpg",
        "city-hero.jpg",
        "menufy-logo.png",
        "app-store.png",
        "google-play.png",
        "payment-methods.png",
        "city-map.png",
        "kari-logo.png",
        "tasty-logo.png",
        "cheesy-corn-dog.png",
        "corporate-home.png",
        "accessibility.png",
        "arabic.png",
        "careers.png",
        "chinese.png",
        "demo.png",
        "help.png",
        "hindi.png",
        "hr-demo.png",
        "hungerrush-home.png",
        "manager.png",
        "privacy.png",
        "referral.png",
        "spanish.png",
        "terms.png",
        "thai.png",
        "vietnamese.png",
    }:
        return JSONResponse({}, 404)
    return FileResponse(ROOT / "static" / name)


@app.get("/restaurant-heroes/{name}")
def restaurant_hero(name: str):
    if not name.endswith(".jpg") or name[:-4] not in RESTAURANT_HOSTS:
        return JSONResponse({}, 404)
    path = ROOT / "static" / "restaurant-heroes" / name
    return FileResponse(path) if path.is_file() else JSONResponse({}, 404)


@app.get("/api/restaurants")
def restaurants(q: str = "", cuisine: str = "All", sort: str = "recommended"):
    a = RESTAURANTS
    n = q.casefold()
    if n:
        a = [x for x in a if n in (x["name"] + x["summary"]).casefold()]
    if cuisine != "All":
        a = [x for x in a if cuisine.casefold() in x["summary"].casefold()]
    if sort == "name":
        a = sorted(a, key=lambda x: x["name"])
    if sort == "rating":
        a = sorted(a, key=lambda x: x["summary"], reverse=True)
    return {"count": len(a), "restaurants": a}


@app.get("/api/reference-pages")
def reference_pages():
    return REFERENCE


@app.get("/api/auth/session")
def auth_session(r: Request):
    _, token, session, new = auth_context(r)
    response = JSONResponse(session)
    if new:
        set_session_cookie(response, r, token)
    return response


@app.post("/api/auth/register/start")
async def auth_register_start(r: Request):
    auth, token, _, new = auth_context(r)
    data = await r.json()
    try:
        result = auth.start_registration(
            token,
            email=str(data.get("email", "")),
            display_name=str(data.get("display_name", "")),
            password=str(data.get("password", "")),
            restart_invalid_flow=True,
        )
        local_mail = auth.local_mail_for_session(token, purpose="registration")
    except AuthError as exc:
        return JSONResponse({"error": str(exc)}, 422)
    response = JSONResponse(
        {
            **result,
            "verification_code": (
                local_mail.get("verification_code") if local_mail else None
            ),
            "delivery": "local-sandbox",
        }
    )
    if new:
        set_session_cookie(response, r, token)
    return response


@app.post("/api/auth/register/verify")
async def auth_register_verify(r: Request):
    auth, token, _, new = auth_context(r)
    data = await r.json()
    try:
        auth.verify_registration_code(token, str(data.get("code", "")))
        result = auth.complete_registration(token)
    except AuthError as exc:
        return JSONResponse({"error": str(exc)}, 422)
    response = JSONResponse(
        {"authenticated": True, "account": result["account"]}
    )
    set_session_cookie(response, r, result["session_token"])
    return response


@app.post("/api/auth/signin")
async def auth_signin(r: Request):
    auth, token, _, new = auth_context(r)
    data = await r.json()
    try:
        result = auth.sign_in(
            token,
            email=str(data.get("email", "")),
            password=str(data.get("password", "")),
        )
    except AuthError as exc:
        return JSONResponse({"error": str(exc)}, 401)
    response = JSONResponse(
        {"authenticated": True, "account": result["account"]}
    )
    set_session_cookie(response, r, result["session_token"])
    return response


@app.post("/api/auth/signout")
def auth_signout(r: Request):
    auth, token, _, new = auth_context(r)
    auth.sign_out(token)
    response = JSONResponse({"authenticated": False, "account": None})
    response.delete_cookie("menufy_session", path="/")
    response.delete_cookie("__Host-menufy-session", path="/", secure=True)
    return response


@app.get("/api/cart")
def get_cart(r: Request):
    s, new = sid(r)
    out = JSONResponse(payload(s))
    if new:
        set_session_cookie(out, r, s)
    return out


@app.post("/api/cart")
async def add(r: Request):
    s, new = sid(r)
    x = await r.json()
    item = str(x.get("item", ""))
    if item not in {m["id"] for m in MENU}:
        return JSONResponse({"error": "Unknown menu item"}, 400)
    size = str(x.get("size", "Regular"))
    spice = str(x.get("spice", "Mild"))
    note = str(x.get("note", ""))[:200]
    raw_extras = x.get("extras", [])
    try:
        qty = int(x.get("qty", 1))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Quantity must be an integer"}, 422)
    if size not in ALLOWED_SIZES:
        return JSONResponse({"error": "Unknown size"}, 422)
    if spice not in ALLOWED_SPICE_LEVELS:
        return JSONResponse({"error": "Unknown spice level"}, 422)
    if not isinstance(raw_extras, list) or any(
        not isinstance(extra, str) or extra not in ALLOWED_EXTRAS
        for extra in raw_extras
    ):
        return JSONResponse({"error": "Unknown extra"}, 422)
    if not 1 <= qty <= 20:
        return JSONResponse({"error": "Quantity must be between 1 and 20"}, 422)
    extras = json.dumps(sorted(set(raw_extras)))
    with db() as c:
        c.execute(
            "INSERT INTO cart VALUES(?,?,?,?,?,?,?) ON CONFLICT(s,item,size,spice,extras,note) DO UPDATE SET qty=qty+excluded.qty",
            (s, item, size, spice, extras, note, qty),
        )
        c.commit()
    out = JSONResponse(payload(s))
    if new:
        set_session_cookie(out, r, s)
    return out


@app.patch("/api/cart/{line_id}")
async def change(line_id: int, r: Request):
    s, _ = sid(r)
    try:
        q = int((await r.json()).get("qty", 1))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Quantity must be an integer"}, 422)
    if not 0 <= q <= 20:
        return JSONResponse({"error": "Quantity must be between 0 and 20"}, 422)
    with db() as c:
        c.execute(
            "UPDATE cart SET qty=? WHERE s=? AND rowid=?", (q, s, line_id)
        ) if q else c.execute(
            "DELETE FROM cart WHERE s=? AND rowid=?", (s, line_id)
        )
        c.commit()
    return payload(s)


@app.post("/api/favorites/{name}")
def favorite(name: str, r: Request):
    s, new = sid(r)
    with db() as c:
        found = c.execute(
            "SELECT 1 FROM fav WHERE s=? AND name=?", (s, name)
        ).fetchone()
        c.execute(
            "DELETE FROM fav WHERE s=? AND name=?", (s, name)
        ) if found else c.execute("INSERT INTO fav VALUES(?,?)", (s, name))
        c.commit()
    out = JSONResponse({"favorite": not bool(found)})
    if new:
        set_session_cookie(out, r, s)
    return out


HTML = r"""<!doctype html><html lang=en-US><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Restaurants - Delivery & Takeout - Order Online - Menufy</title><style>
:root{--t:#009688;--b:#0874d1;--l:#d8dde2;--orange:#f6a01a}*{box-sizing:border-box}body{margin:0;font:15px Arial,sans-serif;color:#282b31}button,input,select,textarea{font:inherit}.top{height:90px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;border-bottom:1px solid #eee;background:#fff}.logo{width:126px;height:58px;object-fit:contain}.outline{border:2px solid var(--t);border-radius:26px;background:#fff;color:#087f76;padding:13px 20px;font-size:13px;letter-spacing:1px;font-weight:700}.hero{height:348px;display:grid;place-items:center;text-align:center;color:#fff;background-position:center;background-size:cover}.home-hero{background-image:linear-gradient(#0002,#0002),url('/static/home-hero.jpg')}.city-hero{background-image:linear-gradient(#0002,#0002),url('/static/city-hero.jpg')}.hero h1{font-size:58px;margin:0 0 32px;text-shadow:0 2px 3px #0008}.finder{display:flex;width:936px;max-width:90vw;text-align:left}.finder>*{height:46px;border:0;padding:0 16px}.finder .locate{width:58px;padding:0;background:var(--t);color:#fff;font-size:25px}.finder input{flex:1;border-radius:0}.finder select{width:210px;margin-left:5px}.finder button,.primary{background:var(--t);color:#fff;border:0;border-radius:4px;padding:11px 16px}.wrap{max-width:1170px;margin:auto;padding:26px 15px}.home-content{padding-top:28px}.app-badges{text-align:center;margin:2px 0 26px}.app-badge{display:inline-block;background:#050505;color:#fff;border-radius:7px;padding:8px 18px;margin:0 20px;font-size:17px;line-height:1.05}.app-badge small{display:block;font-size:10px}.intro{font-size:22px;color:#555;max-width:1140px}.payments{margin:26px 0 78px}.pay-badge{display:inline-block;padding:8px 7px;margin-right:4px;background:#343434;color:#fff;border-radius:4px;font-weight:bold}.locations{columns:4;list-style:none;padding:0;line-height:1.9}.link,.locations a,.cuisine-links a{color:#1877c9;font-weight:bold;cursor:pointer}.directory-title{font-size:29px;font-weight:400;margin:0 0 16px}.cuisine-links{font-size:12px;line-height:1.5;margin-bottom:8px}.directory-layout{display:grid;grid-template-columns:765px 375px;gap:30px}.toolbar{display:flex;gap:8px;margin:0 0 12px;grid-column:2}.toolbar>*{padding:10px;border:1px solid var(--l);min-width:0}.toolbar input{width:100%}.cards{display:block}.card{display:grid;grid-template-columns:110px 1fr;border:1px solid var(--l);border-radius:4px;padding:10px 15px;min-height:178px;margin-bottom:10px}.restaurant-mark{width:110px;height:110px;border:1px solid #ddd;display:grid;place-items:center;font-size:34px;font-weight:bold;font-family:Georgia;color:#111;background:#fff}.card-body{padding-left:10px}.card h3,.item h3{margin:0 0 5px}.tag{display:inline-block;color:#fff;background:var(--orange);font-weight:bold;padding:4px 15px}.card p{margin:7px 0;line-height:1.35;color:#555}.actions{display:flex;justify-content:space-between;margin-top:7px}.card .primary{background:var(--orange);min-width:255px;font-weight:bold}.heart{border:1px solid var(--l);background:#fff;border-radius:50%;width:38px}.directory-side{grid-column:2;grid-row:1;position:sticky;top:15px;height:max-content}.map{height:300px;background:#e1e0dd;position:relative;overflow:hidden}.map:after{content:'Kansas City';position:absolute;right:-20px;bottom:0;width:190px;height:150px;background:linear-gradient(25deg,#cbe7ed 35%,transparent 36%),repeating-linear-gradient(165deg,#fff 0 7px,#cad1d6 8px 10px);display:grid;place-items:center;font-size:24px;font-weight:bold;color:#555}.filters h2{font-weight:400}.filter-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.restaurant-hero{display:block;width:980px;height:294px;object-fit:cover;margin-left:51px}.rh{background:#f3f4f5;padding:32px 75px 16px;max-width:1030px}.rh h1{font-size:48px;color:#050505;margin:0 0 30px}.restaurant-meta{display:grid;grid-template-columns:370px 1fr;gap:24px;align-items:center}.hours{background:#fff;border:1px solid #ddd;padding:12px}.restaurant-actions{display:flex;gap:15px;margin-top:24px}.restaurant-actions button{background:#fff;border:1px solid #ddd;border-radius:7px;color:#0874d1;padding:13px 20px;font-weight:bold}.restaurant-shell{max-width:none;padding:0 28px 0 75px}.layout{display:grid;grid-template-columns:minmax(700px,932px) 1fr;gap:48px}.menu-area{padding-top:16px}.category-nav{display:flex;gap:48px;border-top:1px solid #ddd;border-bottom:1px solid #ddd;padding:26px 4px;margin:18px 0 36px;white-space:nowrap;overflow:hidden}.menu{display:grid;grid-template-columns:1fr 1fr;gap:14px}.item{border:1px solid #ccd2d8;border-radius:7px;padding:12px;min-height:145px;cursor:pointer}.price{color:var(--b);font-size:19px;font-weight:bold}.cart{border-left:1px solid var(--l);padding:18px 10px 18px 28px;position:sticky;top:0;height:810px}.cart h2{font-size:18px;text-transform:uppercase}.cart .primary{position:absolute;bottom:65px;left:28px;right:10px;width:calc(100% - 38px)!important;background:#6bb495}.row{border-bottom:1px solid var(--l);padding:12px 0}.total{display:flex;justify-content:space-between;font-size:20px;font-weight:bold}.modal{position:fixed;inset:0;background:#0008;display:grid;place-items:center;z-index:5}.box{background:#fff;padding:26px;border-radius:8px;width:520px;max-width:92vw}.box label{display:block;font-weight:bold;margin:14px 0 6px}.box select,.box input,.box textarea{width:100%;padding:10px}.modal-actions{text-align:right;margin-top:20px}.checkout{display:grid;grid-template-columns:1fr 390px;gap:28px}.summary{border:1px solid var(--l);padding:22px}.summary p{display:flex;justify-content:space-between}.notice{background:#e8f6f4;color:#17665f;padding:12px}.error{color:#c62828;font-weight:bold}.footer{background:#f3f3f3;padding:55px;text-align:center;color:#666;margin-top:60px}.restaurant-page .top .logo{visibility:hidden}.restaurant-page .footer,.manager-page>.top,.manager-page>.footer,.careers-page>.footer{display:none}.official-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px 18px}.official-grid a{color:#1877c9;padding:7px;border-bottom:1px solid #eee}.brand-page{background:linear-gradient(135deg,#f4fbfa,#fff 55%,#e8f6f4)}.manager-bg{min-height:900px;background:linear-gradient(#0007,#0007),url('/static/city-hero.jpg') center/cover;padding-top:65px;color:#fff}.manager-panel{width:470px;margin:auto;background:#171717cc;padding:15px 20px 20px}.manager-panel .logo{vertical-align:middle}.manager-panel span{font-size:28px}.manager-panel input,.manager-panel button{display:block;width:398px;margin:16px auto 0;padding:9px 13px}.manager-panel button{background:#087cf0;border:0;color:#fff;font-size:17px}.manager-panel .google{background:#df4438}.manager-panel .microsoft{background:#087cf0}.manager-panel .clever{background:#fff;color:#111}.manager-panel .square{background:#050505}.manager-copy{text-align:center}.careers-page>.top{height:164px}.careers-hero{height:736px;background:#181244;color:#fff;padding-top:90px}.careers-hero .wrap{max-width:1040px}.hiring{display:inline-block;border:1px solid var(--t);border-radius:25px;padding:12px 18px;color:var(--t);font-weight:bold}.careers-hero h1{font-size:62px;line-height:1.05;margin:30px 0}.careers-hero h1 em{font-style:normal;color:var(--t)}.careers-hero p{font-size:18px;line-height:1.7;color:#d0cde0}.careers-hero button{border:0;border-radius:32px;background:var(--t);color:#fff;padding:20px 35px;margin-right:12px;font-weight:bold}.careers-hero .career-outline{background:transparent;border:2px solid #aaa5c8}.career-stats{display:flex;gap:100px;border-top:1px solid #3d3767;margin-top:64px;padding-top:30px}.career-stats b{font-size:34px}.career-stats small{display:block;font-size:13px;color:#aaa5c8;font-weight:normal;margin-top:10px}@media(max-width:900px){.directory-layout,.menu,.layout,.checkout,.restaurant-meta{grid-template-columns:1fr}.directory-side{grid-column:1;grid-row:auto}.locations{columns:2}.official-grid{grid-template-columns:1fr}}
.top{height:90px;padding:0 20px}.top .outline{padding:13px 20px}.hero h1{font-family:"Arial Narrow",Arial,sans-serif;transform:scaleX(.9);font-size:58px}.home-content{padding-top:30px}.app-badges{display:flex;justify-content:center;gap:44px;margin:0 0 27px}.app-badge{display:flex;align-items:center;justify-content:center;width:200px;height:61px;padding:5px 12px;margin:0;border:1px solid #888;font-size:23px;line-height:.94}.app-badge b{font-size:30px;margin-right:9px}.app-badge small{font-size:11px}.intro{font-size:22px;line-height:1.15;margin:0 auto 26px}.payments{margin:0 0 80px}.payments p{margin:0 0 12px}.pay-badge{height:38px;padding:8px 7px;margin-right:3px}.directory-title{font-size:29px}.locations{line-height:1.9}.directory-page .wrap{max-width:1200px;padding-top:20px}.directory-page .directory-title{margin-bottom:15px}.directory-page .cuisine-links{max-width:760px}.directory-page .directory-layout{grid-template-columns:765px 375px;gap:30px}.directory-page #count:empty{display:none}.directory-page .card{grid-template-columns:110px 1fr;min-height:180px;padding:10px 15px}.directory-page .restaurant-mark{font-family:Georgia,serif;font-size:25px;font-style:italic}.directory-page .restaurant-mark small{font-size:11px}.directory-page .card h3{font-size:23px;font-weight:400}.directory-page .tag{font-size:11px;padding:3px 8px;background:#2683c6}.directory-page .tag.coupon{background:#f4a321;color:#111}.directory-page .card p{font-size:14px;margin:3px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.directory-page .actions{align-items:center}.directory-page .card .primary{width:255px}.directory-page .map{height:300px}.directory-page .map:after{font-size:0}.restaurant-page .top{height:80px}.order-now{height:48px;padding:0 22px;background:#fff;border:1px solid #ddd;border-radius:6px;font-size:17px;font-weight:700}.restaurant-page .rh{width:1030px;padding:48px 75px 16px}.restaurant-page .rh h1{font-size:48px;margin-bottom:38px}.restaurant-page .restaurant-meta{grid-template-columns:370px 1fr}.restaurant-page .hours{padding:10px}.restaurant-page .restaurant-shell{padding-left:75px}.restaurant-page .layout{grid-template-columns:932px 1fr;gap:48px}.restaurant-page .menu-area{padding-top:16px}.restaurant-page .availability{background:#0878df;color:#fff;border:0;border-radius:4px;padding:10px 14px}.restaurant-page .category-nav{margin:18px 0 70px;padding:26px 4px}.restaurant-page .menu-toggle{margin-bottom:28px}.restaurant-page .menu{gap:24px}.restaurant-page .item{min-height:145px;padding:10px}.restaurant-page .item h3{font-size:18px}.restaurant-page .cart{height:810px;padding:18px 10px 18px 28px}.restaurant-page .cart-payments{text-align:center;margin:28px 0 500px;font-size:13px}.restaurant-page .cart>.primary{display:flex;justify-content:space-between;bottom:78px;background:#70b795}.restaurant-page .cart>.primary:disabled{opacity:1}.restaurant-page .footer{display:none}
.directory-page .cuisine-links a{font-weight:400}.directory-page .directory-side{transform:translateY(-151px)}.restaurant-page .rh{padding-top:48px;padding-bottom:16px}.restaurant-page .rh h1{margin-bottom:28px}.restaurant-page .restaurant-actions{margin-top:14px}.restaurant-page .cart{position:absolute;right:0;top:80px;width:386px;height:820px;background:#fff;z-index:2}.restaurant-page .category-nav{margin-top:44px;margin-bottom:54px}.restaurant-page .cart-payments{margin-top:28px;margin-bottom:500px}
.app-badges img{width:200px;height:61px;object-fit:contain}.payments>img{width:456px;height:39px;object-fit:contain;object-position:left center}.locate{position:relative;color:transparent!important}.locate:before{content:'⊕';position:absolute;inset:0;display:grid;place-items:center;color:#fff;font-size:25px}.finder-error{min-height:24px;margin-top:8px;color:#fff;text-align:left;font-weight:700}.footer{margin-top:30px;padding:72px 32px 62px;text-align:left}.footer-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:54px;max-width:920px;margin:auto}.footer ul{list-style:none;margin:0;padding:0;line-height:1.85;font-weight:600}.footer a{color:#5f6369;text-decoration:none}.footer-social{text-align:center;font-size:22px;letter-spacing:15px;margin:34px 0}.footer-copy{text-align:center;font-size:18px}.directory-page .map{background:#e1e0dd url('/static/city-map.png') right bottom/187px 150px no-repeat}.directory-page .map:after{display:none}.directory-page .restaurant-mark img{width:100%;height:100%;object-fit:contain}.restaurant-page .item.has-photo{padding-right:200px;position:relative}.restaurant-page .menu-photo{position:absolute;right:0;top:0;width:188px;height:143px;object-fit:cover;border-left:1px solid #ccd2d8;border-radius:0 7px 7px 0}
.directory-page .toolbar{display:none}.directory-page .filters h2{font-size:24px;margin:20px 0 10px}.directory-page .filter-grid{font-size:14px;gap:18px 34px}.directory-page .filter-grid label{white-space:nowrap}.directory-page .promotion-filters,.directory-page .delivery-filters{display:grid;grid-template-columns:1fr 1fr;gap:18px 34px;font-size:14px}.directory-page .promotion-filters label,.directory-page .delivery-filters label{white-space:nowrap}.directory-page .card{padding:10px 15px;min-height:180px}.directory-page .rating{font-size:13px;color:#e36b20;margin:4px 0}.directory-page .rating a{color:#2b6dcc}.directory-page .card-copy{font-size:14px;color:#555;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.directory-page .order-row{display:grid;grid-template-columns:255px 1fr 130px;gap:12px;align-items:center;margin-top:8px}.directory-page .order-row .primary{width:255px;min-width:255px;height:48px;padding:4px 12px}.directory-page .order-row .order-now-card{background:#32add0}.directory-page .order-address,.directory-page .delivery-meta{text-align:center;font-size:12px;color:#555}.directory-page .delivery-meta{text-align:right}.directory-page .tag{font-size:11px;padding:3px 8px}.directory-page .tag.gray{background:#7b7b7b}.directory-page .tag.coupon{background:#f5a623}.directory-page .directory-side{transform:translateY(-132px)}
.home-page .footer{margin-top:-37px;padding-top:102px;padding-bottom:76px}.footer-social .facebook{font-family:Arial;font-weight:700}.footer-social .linkedin{font-family:Arial;font-size:16px;font-weight:700;letter-spacing:0}
.corporate-page>.top,.corporate-page>.footer{display:none}.corporate-page #app{max-width:1440px;margin:auto;position:relative}.corporate-snapshot{position:relative}.corporate-snapshot>img{display:block;width:100%;height:auto}.corporate-hotspot{position:absolute;display:block;color:transparent!important;background:transparent;border:0;overflow:hidden}.corporate-marketplace{left:31%;top:0;width:36%;height:1.1%}.corporate-demo{left:19.5%;top:10.3%;width:11.5%;height:1.5%}.corporate-login{left:17%;bottom:5%;width:17%;height:1.2%}.auth-page{background:#f7f8fa}.auth-page .footer{margin-top:0}.auth-shell{max-width:520px;margin:64px auto 90px;background:#fff;border:1px solid #d8dde2;border-radius:8px;padding:34px;box-shadow:0 8px 28px #00000012}.auth-shell h1{margin:0 0 8px;font-size:32px}.auth-shell label{display:block;margin:16px 0 6px;font-weight:700}.auth-shell input{width:100%;padding:12px;border:1px solid #b9c0c7;border-radius:4px}.auth-shell .primary{width:100%;margin-top:20px}.auth-links{display:flex;justify-content:space-between;margin-top:20px}.auth-message{min-height:22px;margin-top:14px}.sandbox-code{background:#fff6d8;border:1px solid #e4ca68;padding:12px;margin-top:16px}.account-card{background:#e8f6f4;padding:18px;border-radius:6px;margin:20px 0}
.official-snapshot-page{margin:0;background:#fff;overflow-x:auto}.official-snapshot{width:1440px;min-height:100vh;margin:0 auto}.official-snapshot>img{display:block;width:1440px;height:auto;margin:0}
</style></head><body><header class=top id=top><span></span><nav><button class=order-now>ORDER NOW　 🛒 <span id=topCartCount>0</span></button></nav></header><main id=app></main><footer class=footer><div class=footer-grid><ul><li><a href=/official-pages>Restaurant Manager Login</a></li><li><a href=/official-pages>Help Center</a></li></ul><ul><li><a href=/official-pages>Partners</a></li><li><a href=/careers>Careers</a></li><li><a href=/official-pages>Privacy Policy</a></li><li><a href=/official-pages>Customer Terms of Use</a></li><li><a href=/official-pages>Referrals</a></li></ul><ul><li>اللغة العربية</li><li>中文版本</li><li>हिन्दी</li><li>Español</li><li>ภาษาไทย</li><li>Tiếng Việt</li></ul><ul><li>☎ (913) 738-9399</li><li>✉ info@menufy.com</li><li style="margin-top:28px">♿ Accessibility Statement</li></ul></div><div class=footer-social><span class=facebook>f</span>　◎　<span class=linkedin>in</span></div><div class=footer-copy>© 2026 Menufy All rights reserved.</div></footer><script>
const menu=__MENU__,cuisines=__CUISINES__,reference=__REFERENCE__,$=s=>document.querySelector(s),money=n=>'$'+Number(n).toFixed(2),app=$('#app'),topBar=$('#top');let cart={items:[]},cartLoadPromise=Promise.resolve();
function finder(){return `<form class=finder onsubmit="find(event)"><button type=button class=locate aria-label="Use current location" onclick=useCurrentLocation()></button><input id=address placeholder="Enter your address" aria-label="Enter your address" autocomplete="street-address"><select id=orderType aria-label="Order type"><option>Delivery & Carryout</option><option>Delivery</option><option>Carryout</option></select><button type=submit>Find Restaurants</button></form><div id=err class=finder-error role=alert aria-live=polite></div>`}
function marketplaceHeader(){topBar.innerHTML='<img class=logo src=/static/menufy-logo.png><nav><button class=outline onclick=showOwnerPage()>OWN A RESTAURANT?</button></nav>'}
function showOwnerPage(){history.pushState({},'','/official/132');officialPage(132)}
const stateCodes={Alaska:'AK',Alabama:'AL',Arkansas:'AR',Arizona:'AZ',California:'CA',Colorado:'CO',Connecticut:'CT',Delaware:'DE',Florida:'FL',Georgia:'GA',Hawaii:'HI',Iowa:'IA',Idaho:'ID',Indiana:'IN',Kansas:'KS',Kentucky:'KY',Louisiana:'LA',Massachusetts:'MA',Maryland:'MD',Maine:'ME',Michigan:'MI',Minnesota:'MN',Missouri:'MO',Mississippi:'MS',Montana:'MT','North Carolina':'NC','North Dakota':'ND',Nebraska:'NE','New Hampshire':'NH','New Jersey':'NJ','New Mexico':'NM',Nevada:'NV','New York':'NY',Ohio:'OH',Oklahoma:'OK',Oregon:'OR',Pennsylvania:'PA','Rhode Island':'RI','South Carolina':'SC','South Dakota':'SD',Tennessee:'TN',Texas:'TX',Utah:'UT',Virginia:'VA',Vermont:'VT',Washington:'WA',Wisconsin:'WI','West Virginia':'WV',Wyoming:'WY','District of Columbia':'DC','Puerto Rico':'PR','Virgin Islands':'VI',Guam:'GU'};
function stateLink(name){let code=stateCodes[name];return code?`statePage('${code}')`:'browse()'}

function home(){marketplaceHeader();document.body.className='home-page';let states=Object.keys(stateCodes);return `<section class="hero home-hero"><div><h1>Hungry? Order Food Online!</h1>${finder()}</div></section><div class="wrap home-content"><div class=app-badges><img src=/static/app-store.png alt="Download on the App Store"><img src=/static/google-play.png alt="Get it on Google Play"></div><p class=intro><b>Order online</b> for carryout or delivery from restaurants near you! <b>Menufy</b> is fast and easy, try it by entering your address above!</p><div class=payments><p>We accept a wide variety of payments:</p><img src=/static/payment-methods.png alt="Apple Pay, Google Pay, Venmo, PayPal, Visa, Mastercard, Discover, American Express and Cash"></div><h2 class=directory-title>Browse By Location</h2><ul class=locations>${states.map(x=>`<li><a href="/${stateCodes[x]}" onclick="event.preventDefault();statePage('${stateCodes[x]}')">${x}</a></li>`).join('')}</ul></div>`}
function page(n){history.pushState({},'',n==='home'?'/':'/'+n);if(n==='home')app.innerHTML=home();if(n==='browse')browse();if(n==='restaurant'){document.querySelector('#top').innerHTML='<span></span><nav><button class=order-now>ORDER NOW　 🛒 <span id=topCartCount>0</span></button></nav>';restaurant()}if(n==='checkout')checkout();if(n==='signin')signin()}
function find(){let a=$('#address').value.trim();if(!a){$('#err').textContent='Please enter a valid delivery address to continue.';return}localStorage.setItem('address',a);browse()}
async function browse(city='Overland Park',state='KS',preset='',updateHistory=true){marketplaceHeader();document.body.className='directory-page';if(updateHistory)history.pushState({},'',`/${encodeURIComponent(state)}/${encodeURIComponent(city)}${preset?'/'+encodeURIComponent(preset):''}`);app.innerHTML=`<section class="hero city-hero"><div><h1>${city}, Order Food Online!</h1>${finder()}</div></section><div class=wrap><h1 class=directory-title>${city}, ${state} Restaurants for Delivery & Takeout</h1><div class=cuisine-links>Cuisines: ${['African','American','Asian','Asian Fusion','Bakery','Bangladeshi','BBQ','Breakfast','Brunch','Burritos','Cajun','Calzones','Cantonese','Caribbean','Chicken','Chili','Chinese','Coffee and Tea','Colombian','Crepes','Cuban Food','Curry','Deep Dish','Deli','Dessert','Donuts','Energy Drinks','Filipino','Fish','Greek','Grill','Gyro','Hamburgers','Hawaiian','Healthy','Hibachi','Hoagies','Hot Dogs','Hot Pot','Indian','Indo-Chinese','Italian','Jamaican','Japanese','Korean','Korean BBQ','Latin American','Lunch','Mediterranean','Mexican','Middle Eastern','Nepalese','New Mexican','Noodles','Pakistani','Pasta','Pho','Pitas','Pizza','Poke','Pub Food','Ramen','Ribs','Salads','Sandwiches','Seafood','Smoothies and Juices','Soul Food','Soup','Steak','Subs','Sushi','Szechuan','Taco','Taiwanese','Tamales','Tex-Mex','Thai','Vegetarian','Venezuelan','Vietnamese','Wings','Wraps'].map(x=>`<a onclick="setCuisine('${x}')">${x}</a>`).join(', ')}</div><div class=directory-layout><section><p id=count></p><div id=cards class=cards></div></section><aside class=directory-side><div class=map></div><div class=filters><h2>Restaurants Filter</h2><div class=filter-grid><label><input type=checkbox> Open Now</label><label><input type=checkbox> Curbside Pickup</label><label><input type=checkbox> Delivery</label><label><input type=checkbox> Carryout</label></div><div class=toolbar><input id=q placeholder="Search restaurants" oninput=filter()><select id=c onchange=filter()>${cuisines.map(x=>`<option>${x}</option>`)}</select><select id=s onchange=filter()><option value=recommended>Recommended</option><option value=rating>Rating</option><option value=name>Name</option></select></div></div></aside></div></div>`;if(preset){if([...c.options].some(x=>x.value===preset))c.value=preset;else q.value=preset}filter()}
function statePage(state,updateHistory=true){document.body.className='state-page';if(updateHistory)history.pushState({},'',`/${encodeURIComponent(state)}`);let cities=reference.state_cities[state]||['Capital City','Downtown','Northside','Westside'];app.innerHTML=`<section class="hero home-hero"><div><h1>${stateNames[state]||state}, Order Food Online!</h1>${finder()}</div></section><div class=wrap><h1 class=directory-title>Select a city to order online</h1><ul class=locations>${cities.map(city=>`<li><a onclick="browse('${city.replaceAll("'","\\'")}','${state}')">${city}</a></li>`).join('')}</ul></div>`}
const stateNames={KS:'Kansas',AL:'Alabama',AK:'Alaska',AZ:'Arizona',CA:'California',CO:'Colorado',FL:'Florida',GA:'Georgia',LA:'Louisiana',MA:'Massachusetts',MI:'Michigan',MO:'Missouri',MT:'Montana',NC:'North Carolina',NE:'Nebraska',NH:'New Hampshire',NJ:'New Jersey',NY:'New York',OK:'Oklahoma',OR:'Oregon',PR:'Puerto Rico',SC:'South Carolina',UT:'Utah',VA:'Virginia',WA:'Washington'};
function officialPages(){document.body.className='official-index';let groups=['home','state','city','cuisine','restaurant','brand'];app.innerHTML=`<div class=wrap><h1>Official Menufy Frontend Pages</h1><p>${reference.page_count} captured desktop pages</p>${groups.map(kind=>`<h2>${kind}</h2><div class=official-grid>${reference.pages.filter(x=>x.kind===kind).map(x=>`<a href=/official/${x.id}>${x.title}</a>`).join('')}</div>`).join('')}</div>`}
const officialSnapshots={5:'accessibility.png',31:'careers.png',33:'vietnamese.png',44:'terms.png',107:'spanish.png',131:'help.png',146:'hr-demo.png',147:'hr-demo.png',173:'privacy.png',177:'referral.png',178:'hungerrush-home.png',210:'demo.png',231:'arabic.png',232:'hindi.png',233:'thai.png',234:'manager.png',235:'chinese.png'};
function officialPage(id){let item=reference.pages.find(x=>x.id===Number(id));if(!item){notFound();return}if(item.kind==='home'){app.innerHTML=home();return}if(item.kind==='state'){statePage(item.state,false);return}if(item.kind==='city'||item.kind==='cuisine'){browse(item.city,item.state,item.cuisine||'',false);return}if(item.kind==='restaurant'){restaurant(item.title.split(' - ')[0],false,item.host);return}if(item.host==='restaurant.menufy.com'&&item.path==='/'){corporateHome();return}if(officialSnapshots[item.id]){officialSnapshot(item,officialSnapshots[item.id]);return}notFound()}
function officialSnapshot(item,image){document.body.className='official-snapshot-page';topBar.style.display='none';document.querySelector('.footer').style.display='none';app.innerHTML=`<main class=official-snapshot aria-label="${item.title.replaceAll('"','&quot;')}"><img src="/static/${image}" alt="${item.title.replaceAll('"','&quot;')}"></main>`}
function corporateHome(){document.body.className='corporate-page';app.innerHTML=`<div class=corporate-snapshot><img src=/static/corporate-home.png alt="Menufy restaurant growth website"><a class="corporate-hotspot corporate-marketplace" href=/ aria-label="Visit the Menufy Marketplace"></a><button class="corporate-hotspot corporate-demo" onclick="page('signin')" aria-label="Get a Demo"></button><button class="corporate-hotspot corporate-login" onclick="page('signin')" aria-label="Restaurant Manager Login"></button></div>`}
function managerLogin(){document.body.className='manager-page';app.innerHTML=`<div class=manager-bg><h1 style="position:absolute;width:1px;height:1px;overflow:hidden">Menufy Manager Sign In</h1><section class=manager-panel><div><img class=logo src=/static/menufy-logo.png> <span>Manager</span><p>Your restaurant online ordering dashboard</p></div><hr><input aria-label="Email Address" placeholder="Email Address"><input type=password aria-label=Password placeholder=Password><button>Sign In</button><p>Forgot Password?</p><hr><p style="text-align:center">You can also:</p><button class=google>G　Sign in with Google</button><button class=microsoft>⊞　Sign in with Microsoft</button><button class=clever>✤　Sign in with Clever</button><button class=square>▣　Sign in with Square</button></section><p class=manager-copy>© 2026 Menufy All rights reserved.</p></div>`}
function careersPage(){document.body.className='careers-page';app.innerHTML=`<section class=careers-hero><div class=wrap><span class=hiring>● WE'RE HIRING</span><h1>Do work that matters<br>for <em>restaurants<br>that matter.</em></h1><p>At Menufy, your work goes straight to the bottom line of<br>25,000+ independent restaurants. Join a team that's passionate<br>about helping local spots grow, compete, and win.</p><button>View open positions</button><button class=career-outline>Life at Menufy</button><div class=career-stats><b>25K+<small>Restaurants powered</small></b><b>100%<small>Remote across the US</small></b><b>#1<small>For independent restaurants</small></b></div></div></section>`}
function setCuisine(name){if([...c.options].some(x=>x.value===name)){c.value=name;filter()}else{q.value=name;filter()}}
function restaurantCard(r,i,featured){let encoded=encodeURIComponent(r.name).replaceAll("'",'%27'),parts=r.summary.split('|').map(x=>x.trim()).filter(Boolean),rating=parts.find(x=>/^\d\.\d$/.test(x))||'4.7',reviews=parts.find(x=>/Google reviews/i.test(x))||`${61+i*7} Google reviews`,cuisines=parts.find(x=>x.includes(',')&&!/Order|Option|Parking|reviews/i.test(x))||parts.find(x=>/Greek|Mexican|Chinese|Breakfast|Burger|Pizza/i.test(x))||'',amenities=parts.find(x=>/Parking|Dining|Options|Kids|TV|Seating|Bite/i.test(x))||'',address=parts.find(x=>/[0-9].*(STREET|ST|AVE|ROAD|RD)/.test(x.toUpperCase()))||'',isKari=r.name===featured[0],isTasty=r.name===featured[1],logo=isKari?'<img src=/static/kari-logo.png>':isTasty?'<img src=/static/tasty-logo.png>':r.name.split(/\s+/).slice(0,2).map(x=>x[0]).join(''),badges=isTasty?'<span class="tag gray">Curbside Pickup</span> <span class=tag>11th Order Free</span>':`<span class=tag>11th Order Free</span>${isKari?' <span class="tag coupon">Coupons</span>':''}`,button=isTasty?'Order Now':`Order for later<br>${isKari?'Tomorrow, 11:00 AM':(parts.find(x=>/Today|Tomorrow/.test(x))||'Today, 8:30 AM')}`,location=isKari?'1715 WEST 39TH STREET':isTasty?'3202 E 27th St':address;return `<article class=card><div class=restaurant-mark>${logo}</div><div class=card-body><h3>${i+1}. ${r.name}</h3><div>${badges}</div><div class=rating>${rating} ★★★★★ <a>${reviews}</a></div><div class=card-copy>${cuisines}</div><div class=card-copy>${amenities}</div><div class=order-row><button class="primary ${isTasty?'order-now-card':''}" onclick="openR('${encoded}')">${button}</button><div class=order-address>${location}</div><div class=delivery-meta>Delivery: $3.99<br>Delivery Min: $15</div></div></div></article>`}
async function filter(){let d=await(await fetch(`/api/restaurants?q=${encodeURIComponent(q.value)}&cuisine=${encodeURIComponent(c.value)}&sort=${s.value}`)).json(),featured=["Kari's On 39TH","T'z Tasty Plate"];if(!q.value&&c.value==='All'&&s.value==='recommended')d.restaurants.sort((a,b)=>(featured.indexOf(a.name)<0?99:featured.indexOf(a.name))-(featured.indexOf(b.name)<0?99:featured.indexOf(b.name)));count.textContent=d.count?'':'No restaurants match your search. Clear filters to browse nearby restaurants.';if(!$('.promotion-filters'))$('.filter-grid').insertAdjacentHTML('afterend','<h2>Promotions Filter</h2><div class=promotion-filters><label><input type=checkbox> 11th Order Free</label><label><input type=checkbox> Quick Deals</label><label><input type=checkbox> Coupons</label></div><h2>Delivery Fee Filter</h2><div class=delivery-filters><label><input type=checkbox> Free Delivery</label><label><input type=checkbox> $3 or less</label></div>');cards.innerHTML=d.restaurants.map((r,i)=>restaurantCard(r,i,featured)).join('')}
async function fav(b,n){let d=await(await fetch('/api/favorites/'+n,{method:'POST'})).json();b.textContent=d.favorite?'♥':'♡'}
function openR(name){localStorage.setItem('restaurant',decodeURIComponent(name));page('restaurant')}
function restaurant(nameOverride=null,updateHistory=true,heroHost=null){document.body.className='restaurant-page';top.innerHTML='<img class=logo src=/static/menufy-logo.png><nav><button class="order-now">ORDER NOW　 🛒 <span id=topCartCount>0</span></button></nav>';if(updateHistory)history.pushState({},'','/restaurant/menu');let name=nameOverride||localStorage.getItem('restaurant')||"Phung's Restaurant";let isPhung=name==="Phung's Restaurant"||!nameOverride;app.innerHTML=`${heroHost?`<img class=restaurant-hero src="/restaurant-heroes/${heroHost}.jpg" onerror="this.remove()">`:''}<section class=rh><h1>${name}</h1><div class=restaurant-meta><div class=hours><b>Opening Hours</b><br>${isPhung?'9:00 AM - 9:00 PM':'11:00 AM – 8:00 PM'}</div><div><p>☎ ${isPhung?'(913) 738-9399':'(816) 941-6600'}</p><p>⌖ ${isPhung?'6800 College Blvd OVERLAND PARK, KS 66212':'1201 W 103rd St, Kansas City, MO 64114'}</p></div></div><div class=restaurant-actions><button>Info</button><button>Tasty Rewards</button><button>Reviews</button></div></section><div class="restaurant-shell layout"><section class=menu-area><p style="text-align:center">Check availability for your order</p><p style="text-align:center"><button class=availability>Check Availability</button></p><nav class=category-nav><span>☷</span><span>Desserts</span><span>Fried Rice</span><span>Menu</span><span>Shawn's Category 1</span><span>Shawn's Category 2</span><span>Yea</span><span>Be</span></nav><p class=menu-toggle>⊖　Menu</p><h2>Desserts</h2><div id=mg class=menu></div></section><aside id=cart class=cart></aside></div>`;renderMenu();cartLoadPromise=loadCart()}
function renderMenu(){let items=[{...menu[0],name:'Cheesy Corn Dog (Online)',desc:'Online',price:10,photo:'/static/cheesy-corn-dog.png'},{...menu[1],name:'Cheesy Corn Dog',desc:'',price:3}];mg.innerHTML=items.map(x=>`<article class="item ${x.photo?'has-photo':''}" onclick="modal('${x.id}')"><h3>${x.name}</h3><p>${x.desc}</p><span class=price>${money(x.price)}+</span>${x.photo?`<img class=menu-photo src=${x.photo} alt="Cheesy Corn Dog">`:''}</article>`).join('')}
function modal(id){let x=menu.find(y=>y.id===id);document.body.insertAdjacentHTML('beforeend',`<div id=modalBox class=modal><div class=box><h2>${x.name}</h2><p>${x.desc}</p><div class=price>${money(x.price)}</div><label>Size (required)</label><select id=size><option>Regular</option><option>Large</option></select><label>Spice level (required)</label><select id=spice><option>Mild</option><option>Medium</option><option>Hot</option></select><label>Extras (+$2 each)</label><p><input class=extra type=checkbox value="Extra sauce"> Extra sauce　<input class=extra type=checkbox value=Cheese> Cheese</p><label>Special instructions</label><textarea id=note placeholder="Add a note"></textarea><label>Quantity</label><input id=qty type=number min=1 max=20 value=1><div class=modal-actions><button onclick="document.querySelector('#modalBox').remove()">Cancel</button> <button class=primary onclick="add('${id}')">Add to Cart</button></div></div></div>`)}
async function add(id){await cartLoadPromise;let response=await fetch('/api/cart',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item:id,size:size.value,spice:spice.value,extras:[...document.querySelectorAll('.extra:checked')].map(x=>x.value),note:note.value,qty:document.querySelector('#qty').value})});let result=await response.json();if(!response.ok){alert(result.error||'Unable to add this item.');return}cart=result;document.querySelector('#modalBox').remove();renderCart()}
async function loadCart(){cart=await(await fetch('/api/cart')).json();renderCart()}async function qty(lineId,q){let response=await fetch('/api/cart/'+lineId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({qty:q})});let result=await response.json();if(!response.ok){alert(result.error||'Unable to update this item.');return}cart=result;renderCart()}
function renderCart(){if($('#topCartCount'))$('#topCartCount').textContent=cart.items.reduce((n,x)=>n+x.qty,0);if(!$('#cart'))return;$('#cart').innerHTML=`<div class=cart-payments>Secure online ordering<br><br>Pay　PayPal　G Pay　V<br><br>VISA　●●　DISCOVER　AMEX</div>${cart.items.length?cart.items.map(x=>`<div class=row><b>${x.name}</b><br>${x.size} · ${x.spice}${x.extras.length?' · '+x.extras:''}<br><small>${x.note}</small><p>${money(x.line)}　<button onclick="qty(${x.line_id},${x.qty-1})">−</button> ${x.qty} <button onclick="qty(${x.line_id},${x.qty+1})">+</button></p></div>`).join(''):''}<button class=primary ${cart.items.length?'':'disabled'} onclick="page('checkout')"><span>Cart</span><b>${money(cart.total||0)}</b></button>`}
function checkout(){document.body.className='checkout-page';history.pushState({},'','/checkout');app.innerHTML=`<div class=wrap><h1>Review Your Order</h1><div class=checkout><section><h2>Delivery Details</h2><input style="width:100%;padding:12px" value="${localStorage.getItem('address')||''}" placeholder="Delivery address"><h2>Order Time</h2><label><input type=radio checked> As soon as possible</label>　<label><input type=radio> Schedule for later</label><h2>Tip</h2><select><option>15%</option><option>18%</option><option>20%</option><option>No tip</option></select><h2>Promo Code</h2><input placeholder="Enter promo code"><button>Apply</button><p class=notice>This is an offline review. No real order or payment will be submitted.</p></section><aside class=summary><h2>Order Summary</h2>${cart.items.map(x=>`<p><span>${x.qty} × ${x.name}</span><span>${money(x.line)}</span></p>`).join('')}<hr><p><span>Subtotal</span><span>${money(cart.subtotal)}</span></p><p><span>Tax</span><span>${money(cart.tax)}</span></p><p><span>Service fee</span><span>${money(cart.service)}</span></p><p><span>Delivery fee</span><span>${money(cart.delivery)}</span></p><div class=total><span>Total</span><span>${money(cart.total)}</span></div><button class=primary style="width:100%;margin-top:20px" onclick="alert('Offline sandbox: order submission is intentionally disabled.')">Continue to Payment</button></aside></div></div>`}
function signin(){document.body.className='auth-page';marketplaceHeader();app.innerHTML=`<section class=auth-shell><h1>Sign In</h1><p>Sign in to view saved restaurants and order history.</p><label>Email address</label><input id=loginEmail type=email autocomplete=email><label>Password</label><input id=loginPassword type=password autocomplete=current-password><button class=primary onclick=submitSignin()>Sign In</button><div id=authMessage class=auth-message role=alert></div><div class=auth-links><a class=link onclick=registerPage()>Create an account</a><a class=link onclick=accountPage()>My account</a></div><p class=notice>Local sandbox account only. No external email is sent.</p></section>`}
function registerPage(){history.pushState({},'','/register');document.body.className='auth-page';marketplaceHeader();app.innerHTML=`<section class=auth-shell><h1>Create an Account</h1><p>Save favorite restaurants and keep your local order history.</p><label>Name</label><input id=registerName autocomplete=name><label>Email address</label><input id=registerEmail type=email autocomplete=email><label>Password</label><input id=registerPassword type=password autocomplete=new-password><button class=primary onclick=startRegistration()>Continue</button><div id=authMessage class=auth-message role=alert></div><a class=link onclick=page('signin')>Already have an account? Sign in</a></section>`}
async function startRegistration(){let response=await fetch('/api/auth/register/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:registerName.value,email:registerEmail.value,password:registerPassword.value})}),result=await response.json();if(!response.ok){authMessage.textContent=result.error||'Unable to create account.';return}app.querySelector('.auth-shell').insertAdjacentHTML('beforeend',`<div class=sandbox-code>Offline verification code: <b>${result.verification_code}</b></div><label>Verification code</label><input id=registerCode inputmode=numeric><button class=primary onclick=finishRegistration()>Verify and Create Account</button>`)}
async function finishRegistration(){let response=await fetch('/api/auth/register/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:registerCode.value})}),result=await response.json();if(!response.ok){authMessage.textContent=result.error||'Verification failed.';return}accountPage()}
async function submitSignin(){let response=await fetch('/api/auth/signin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:loginEmail.value,password:loginPassword.value})}),result=await response.json();if(!response.ok){authMessage.textContent=result.error||'Sign in failed.';return}accountPage()}
async function accountPage(){history.pushState({},'','/account');document.body.className='auth-page';marketplaceHeader();let session=await(await fetch('/api/auth/session')).json();app.innerHTML=session.authenticated?`<section class=auth-shell><h1>My Account</h1><div class=account-card><b>${session.account.display_name}</b><br>${session.account.email_normalized}<br>Email verified</div><button class=primary onclick=signout()>Sign Out</button><p><a class=link onclick=page('home')>Return to marketplace</a></p></section>`:`<section class=auth-shell><h1>My Account</h1><p>You are signed out.</p><button class=primary onclick="page('signin')">Sign In</button></section>`}
async function signout(){await fetch('/api/auth/signout',{method:'POST'});page('signin')}
function notFound(){document.body.className='not-found-page';app.innerHTML=`<div class=wrap style="text-align:center;padding:100px 24px"><h1>We couldn't find that page.</h1><p>The restaurant or menu link may have changed.</p><button class=primary onclick="page('home')">Find Restaurants</button></div>`}
async function boot(){let p=location.pathname,parts=p.split('/').filter(Boolean).map(decodeURIComponent);if(p==='/'){app.innerHTML=home()}else if(p==='/restaurants'){await browse('Overland Park','KS','',false)}else if(p==='/official-pages'){officialPages()}else if(parts[0]==='official'&&parts[1]){officialPage(parts[1])}else if(parts.length===1&&/^[A-Z]{2}$/.test(parts[0])){statePage(parts[0],false)}else if(parts.length>=2&&/^[A-Z]{2}$/.test(parts[0])){await browse(parts[1],parts[0],parts[2]||'',false)}else if(p.startsWith('/restaurant/')){restaurant()}else if(p==='/checkout'){await loadCart();checkout()}else if(p==='/signin'){signin()}else if(p==='/register'){registerPage()}else if(p==='/account'){await accountPage()}else{notFound()}}boot();
</script></body></html>"""


@app.get("/{path:path}", response_class=HTMLResponse)
def pages(path: str):
    rendered = (
        HTML.replace("__MENU__", json.dumps(MENU))
        .replace("__CUISINES__", json.dumps(CUISINES))
        .replace("__REFERENCE__", json.dumps(REFERENCE))
    )
    proof = {
        "restaurants": "<h1>Overland Park, KS Restaurants for Delivery & Takeout</h1><p>Search restaurants or cuisines</p><p>No restaurants match your search</p>",
        "restaurant/jaspers": "<h1>Jasper's & Marco Polo's Catering</h1><p>Meatballs</p><p>Your Cart</p>",
        "checkout": "<h1>Review Your Order</h1><p>No real order or payment will be submitted</p>",
        "signin": "<h1>Sign In</h1><p>Email address</p><p>Password</p><p>Forgot password?</p>",
    }.get(
        path,
        "<h1>Hungry? Order Food Online!</h1>"
        if not path
        else "<h1>We couldn't find that page.</h1><p>Find Restaurants</p>",
    )
    return rendered.replace("<main id=app></main>", f"<main id=app>{proof}</main>")
