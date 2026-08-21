"""Bean Box offline clone: catalogue, subscription configuration and safe checkout."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import math
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import business  # noqa: E402
from backend.site_backend_integration import open_site_services  # noqa: E402
from websitebench.site_backend import PaymentError  # noqa: E402
from websitebench.local_clone_auth import AuthError  # noqa: E402

SITE_ID = "bean-box"
BACKEND, _AUTH = open_site_services()
ADMIN_TOKEN = os.environ.get("WEBSITEBENCH_BEAN_BOX_ADMIN_TOKEN") or secrets.token_urlsafe(32)
SESSION_COOKIE = "__Host-websitebench-bean-box-session"
LOCAL_SESSION_COOKIE = "websitebench-bean-box-session"
AUTH_COOKIE = "__Host-websitebench-bean-box-auth"
LOCAL_AUTH_COOKIE = "websitebench-bean-box-auth"
OWNER_RE = re.compile(r"^[A-Za-z0-9._:-]{8,240}$")
FIXTURE = {
    "first_name": "Jamie",
    "last_name": "Rivera",
    "email": "jamie.rivera@example.test",
    "address": "101 Test Market St",
    "city": "Seattle",
    "state": "WA",
    "zip": "98101",
}
TASTES = [
    ("curators-choice", "CURATOR'S CHOICE™", "Discover the full spectrum of specialty coffee, hand picked by our expert curator.", "641 coffees curated"),
    ("single-origin", "SINGLE ORIGIN", "Explore distinctive microlots from celebrated farms and producers.", "255 coffees curated"),
    ("light-bright", "LIGHT & BRIGHT", "Lively, floral and fruit-forward coffees.", "234 coffees curated"),
    ("medium-cozy", "MEDIUM & COZY", "Balanced, sweet and crowd-pleasing coffees.", "279 coffees curated"),
    ("dark-toasty", "DARK & TOASTY", "Deep chocolate and caramelized roast notes.", "128 coffees curated"),
    ("espresso", "ESPRESSO", "Rich coffees selected for concentrated brewing.", "121 coffees curated"),
    ("decaf", "DECAF", "Full flavor with a gentler finish.", "94 coffees curated"),
    ("cold-brew", "COLD BREW", "Smooth coffees that shine over ice.", "139 coffees curated"),
]
QUANTITIES = [
    ("trace-six-cup", "6-Cup Size", "6 cups", "Compatibility option; not observed on the current source"),
    ("solo-sipper", "The Solo Sipper", "1 × 12 oz", "About 24–36 cups"),
    ("duo", "The Duo", "2 × 12 oz", "Share or stock up"),
    ("large-solo", "Large Solo", "1 × 2 lb", "About 72–108 cups"),
    ("office-duo", "Office Duo", "2 × 2 lb", "Built for busy mornings"),
]


def _load_session_secret() -> bytes:
    injected = os.environ.get("WEBSITEBENCH_BEAN_BOX_SESSION_SECRET")
    if injected:
        if len(injected) < 32:
            raise RuntimeError("session secret must contain at least 32 characters")
        return injected.encode()
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS bean_box_runtime_secrets(secret_name TEXT PRIMARY KEY, secret_value BLOB NOT NULL)"
        )
        row = connection.execute(
            "SELECT secret_value FROM bean_box_runtime_secrets WHERE secret_name='session-hmac'"
        ).fetchone()
        if row is None:
            value = secrets.token_bytes(32)
            connection.execute(
                "INSERT INTO bean_box_runtime_secrets(secret_name, secret_value) VALUES ('session-hmac', ?)",
                (value,),
            )
        else:
            value = bytes(row[0])
    if len(value) < 32:
        raise RuntimeError("persisted session secret is invalid")
    return value


SESSION_SECRET = _load_session_secret()

app = FastAPI(title="Bean Box offline clone", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def offline_headers(request: Request, call_next):
    cookie_name = LOCAL_SESSION_COOKIE if request.url.hostname in {"127.0.0.1", "localhost", "::1"} else SESSION_COOKIE
    raw_session = request.cookies.get(cookie_name, "")
    owner = _decode_session(raw_session)
    if owner is None:
        owner = f"fixture-actor-{secrets.token_hex(12)}"
    auth_cookie_name = LOCAL_AUTH_COOKIE if request.url.hostname in {"127.0.0.1", "localhost", "::1"} else AUTH_COOKIE
    supplied_auth_token = request.cookies.get(auth_cookie_name)
    auth_token, auth_info = _AUTH.ensure_session(supplied_auth_token)
    request.state.auth_token = auth_token
    request.state.auth_info = auth_info
    account = auth_info.get("account") if auth_info.get("authenticated") else None
    request.state.owner = f"account:{account['account_id']}" if account else owner
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if _decode_session(raw_session) is None:
        # Secure cookies are required on HTTPS deployments. Loopback capture is
        # intentionally allowed over HTTP so the offline browser can retain a
        # stable actor without weakening public deployments.
        response.set_cookie(
            cookie_name,
            _encode_session(owner),
            secure=request.url.hostname not in {"127.0.0.1", "localhost", "::1"},
            httponly=True,
            samesite="lax",
            path="/",
        )
    if auth_token != supplied_auth_token:
        response.set_cookie(
            auth_cookie_name,
            auth_token,
            secure=request.url.hostname not in {"127.0.0.1", "localhost", "::1"},
            httponly=True,
            samesite="lax",
            path="/",
        )
    return response


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def money(minor: int) -> str:
    return f"${minor / 100:,.2f}"


def owner_value(value: object | None) -> str:
    text = str(value or "public-fixture-actor")
    return text if OWNER_RE.fullmatch(text) else "public-fixture-actor"


def _encode_session(owner: str) -> str:
    signature = hmac.new(SESSION_SECRET, owner.encode(), hashlib.sha256).hexdigest()
    return f"{owner}.{signature}"


def _decode_session(value: str) -> str | None:
    owner, separator, signature = value.rpartition(".")
    if not separator or not OWNER_RE.fullmatch(owner):
        return None
    expected = hmac.new(SESSION_SECRET, owner.encode(), hashlib.sha256).hexdigest()
    return owner if hmac.compare_digest(signature, expected) else None


def request_owner(request: Request) -> str:
    return str(getattr(request.state, "owner", "public-fixture-actor"))


def authenticated_account(request: Request) -> dict | None:
    info = getattr(request.state, "auth_info", {})
    return info.get("account") if info.get("authenticated") else None


def _set_auth_cookie(request: Request, response: Response, token: str) -> None:
    loopback = request.url.hostname in {"127.0.0.1", "localhost", "::1"}
    response.set_cookie(
        LOCAL_AUTH_COOKIE if loopback else AUTH_COOKIE,
        token,
        secure=not loopback,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _synthetic_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized.endswith("@example.test"):
        raise ValueError("Only synthetic @example.test email addresses are accepted.")
    return normalized


def submitted_owner(request: Request, value: object | None) -> str:
    owner = request_owner(request)
    if value is not None and str(value) != owner:
        raise ValueError("session actor mismatch")
    return owner


async def _json_object(request: Request) -> tuple[dict | None, JSONResponse | None]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type != "application/json":
        return None, JSONResponse({"error": "application/json required"}, status_code=415)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None, JSONResponse({"error": "malformed JSON"}, status_code=400)
    if not isinstance(payload, dict):
        return None, JSONResponse({"error": "JSON object required"}, status_code=422)
    return payload, None


def cookie_layer() -> str:
    return """<div class='cookie-layer' role='dialog' aria-modal='true' aria-labelledby='cookie-title'><div class='cookie-tip'><strong>One quick step to continue</strong><br><span class='muted'>See the options below</span><br>↓</div><div class='cookie-banner'><h3 id='cookie-title'>Your coffee experience, your choice</h3><div>We use preferences to show your roasts you'll love. No source-site request is made.</div><button class='button' type='button' data-cookie-close>Accept All Cookies</button><button class='button' type='button' data-cookie-close>Limit Cookies</button><a href='/faq' class='button ghost'>Cookie Settings</a></div></div>"""


def cart_count(owner: str) -> int:
    with BACKEND.lifecycle.connection() as connection:
        return sum(int(row["quantity"]) for row in business.cart(connection, owner))


def header(owner: str, current: str = "") -> str:
    def nav(path: str, label: str, key: str) -> str:
        active = " aria-current='page'" if current == key else ""
        return f"<a href='{path}'{active}>{label}</a>"
    return f"""<header class='site-header'><div class='promo'>Free bag when you join today! ▶</div><div class='header-inner'><a class='brand' href='/'>BEAN BOX<span class='bean' aria-hidden='true'></span></a><button class='menu-button' aria-label='Toggle navigation'>☰</button><nav class='nav'>{nav('/coffee-subscription/configure','COFFEE SUBSCRIPTIONS','subscriptions')}{nav('/coffee-gifts','COFFEE GIFTS','gifts')}{nav('/coffee','COFFEE','coffee')}{nav('/coffee-equipment','GEAR','gear')}</nav><div class='nav-right'><a href='/coffee?focus=search'>⌕</a><a href='/account'>MY ACCOUNT</a><a href='/cart'>CART ({cart_count(owner)})</a></div></div></header>"""


def footer() -> str:
    return """<footer class='site-footer'><div class='footer-grid'><div><h3>Products</h3><a href='/coffee-subscription/configure'>Coffee Subscriptions</a><a href='/coffee-gifts'>Coffee Gifts</a><a href='/coffee'>Featured Coffees</a><a href='/coffee-equipment'>Coffee Equipment</a><a href='/coffee-gifts'>Corporate Gifts</a></div><div><h3>Company</h3><a href='/account'>Account</a><a href='/contact'>Contact</a><a href='/about'>About</a><a href='/roasters'>Roasters</a><a href='/blog'>Blog</a><a href='/resources'>Coffee Resources</a></div><div><h3>Policies</h3><a href='/terms'>Terms of Service</a><a href='/privacy'>Privacy Policy</a><a href='/faq'>Accessibility</a><a href='/faq'>FAQ</a><a href='/privacy'>Cookie Preferences</a></div><div class='footer-signup'><h2 class='display'>Stay caffeinated</h2><p>Step up your coffee game with tips and offers. No email is collected here.</p><div class='signup-visual'><span>Enter your email</span><b>JOIN NOW</b></div><div class='payment-marks' aria-label='Payment methods shown for visual parity'>VISA&nbsp;&nbsp;●●&nbsp;&nbsp;AMEX&nbsp;&nbsp;Pay</div></div></div><div class='footer-social' aria-label='Social links'>◎ &nbsp; ● &nbsp; ♥</div><div class='copyright'>Bean Box® · No source affiliation, purchase, email, address or remote payment effect.</div></footer>"""


def page(title: str, body: str, owner: str = "public-fixture-actor", current: str = "", cookies: bool = False, status: int = 200) -> HTMLResponse:
    document = f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)}</title><link rel='stylesheet' href='/static/site.css'></head><body>{header(owner,current)}<main>{body}</main>{footer()}{cookie_layer() if cookies else ''}<script src='/static/site.js' defer></script></body></html>"
    return HTMLResponse(document, status_code=status)


def steps(active: int) -> str:
    labels = ("Tasting Experience", "Quantity", "Review")
    return "<div class='steps'>" + "".join(f"<div class='step {'active' if i == active else ''}'><span class='step-num'>{i}</span>{label}</div>" for i, label in enumerate(labels, 1)) + "</div>"


def hidden_owner(owner: str) -> str:
    return f"<input type='hidden' name='owner' value='{esc(owner)}'>"


@app.get("/__websitebench/health", include_in_schema=False)
async def health() -> Response:
    return Response('{"status":"ok"}', media_type="application/json")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "site_id": SITE_ID})


@app.post("/__admin/reset", include_in_schema=False)
async def reset(request: Request) -> JSONResponse:
    token = request.headers.get("X-WebsiteBench-Admin-Token", "")
    if ADMIN_TOKEN is None:
        return JSONResponse({"error": "admin reset disabled"}, status_code=503)
    if request.client and request.client.host not in {"127.0.0.1", "localhost", "::1", "testclient"}:
        return JSONResponse({"error": "loopback only"}, status_code=403)
    if not hmac.compare_digest(token, ADMIN_TOKEN):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    def reset_all(connection) -> None:
        BACKEND.lifecycle.reset_embedded(connection, confirm_site_id=SITE_ID)
        business.reset_mutable(connection)

    _AUTH.reset_site_state(site_reset=reset_all, seed_accounts=[])
    response = JSONResponse({"reset": True, "site_id": SITE_ID})
    _set_auth_cookie(request, response, _AUTH.create_anonymous_session())
    return response


@app.get("/", include_in_schema=False)
async def home(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    body = """<section class='hero'><div class='hero-copy'><span class='rating-line'>4.5 ★ &nbsp; from 2,000+ coffee lovers</span><h1 class='display'>Say hello to your next favorite coffee.</h1><p>Explore 240 searchable coffee selections modeled after a broad independent-roaster catalogue.</p><a class='button' href='/coffee-subscription/configure'>REVEAL YOUR NEXT FAVORITE</a></div><div class='hero-art'><img class='hero-photo' src='/static/assets/source/hero-oat.webp' alt='Specialty coffee bags with a pour-over carafe and mug on a marble counter'></div></section>
<section class='intro'><h2 class='display'>Personalized coffee subscriptions,<br>curated by our Cup of Excellence judge</h2><div class='curator-badge'>MG</div><p class='review-score'>★★★★★ &nbsp; 2079 reviews</p><div class='ticks'><span>Wake up to the world's best coffee</span><span>Support the top local roasters in the U.S.</span><span>Enjoy coffee fresh and bursting with flavor</span><span>Curated from a broad selection of specialty coffee</span><span>Exclusive member pricing and shipping perks</span><span>Personalize every delivery</span></div><a class='button' href='/coffee-subscription/configure'>PERSONALIZE A PLAN</a></section>
<section class='mission'><h2 class='display'>We're on a mission to bring you better mornings</h2><div class='mission-grid'><div><span class='mission-icon'>◒</span><h3>Let us be your guide</h3><p>Tell us how you brew and what you love. Our curator narrows the choices.</p></div><div><span class='mission-icon'>☕</span><h3>Better coffee for everyone</h3><p>Explore a rotating world of excellent coffees for better mornings at home.</p></div><div><span class='mission-icon'>♧</span><h3>Farm-to-cup sustainability</h3><p>Every coffee selection represents an independent roaster and responsible sourcing.</p></div><div><span class='mission-icon'>☆</span><h3>Enjoy the perks</h3><p>Flexible plans, member-style savings and complete control.</p></div></div></section>
<section class='how-it-works'><h2 class='display'>How it works</h2><div class='how-grid'><div><div class='how-art art-personalize'></div><h3>You personalize</h3><p>Tell us your coffee preference and how often you'd like a shipment.</p></div><div><div class='how-art art-curate'></div><h3>We curate</h3><p>Our experts select coffees that fit the profile you choose.</p></div><div><div class='how-art art-enjoy'></div><h3>You enjoy</h3><p>Every Bean Box delivery arrives ready for you to explore.</p></div></div></section>
<section class='membership'><div class='membership-art'></div><div class='membership-copy'><span class='eyebrow'>Join today and get access to</span><h2 class='display'>Membership has its perks</h2><ul><li>Freshly roasted coffee matched to your taste</li><li>Flexible delivery every 2–6 weeks</li><li>Member-style pricing across 240 coffee selections</li><li>Credits, early access and occasional surprises</li><li>Pause or adjust your plan</li></ul><a class='button secondary' href='/coffee-subscription/configure'>CHOOSE MY PLAN</a></div></section>
<section class='trust'><h2 class='display'>See why thousands trust us with their mornings</h2><p class='review-score'>★★★★★ &nbsp; 2079 REVIEWS</p><div class='review-grid'><blockquote>“An eye-opening way to discover coffees from around the world.”<cite>DESHANT</cite></blockquote><blockquote>“The rotating selections make every delivery a welcome surprise.”<cite>VICTORIA</cite></blockquote><blockquote>“Fresh coffee and flexible timing make mornings easier.”<cite>KATHERINE</cite></blockquote><blockquote>“A responsive experience with consistently good coffee.”<cite>PATRICK</cite></blockquote></div><a class='button secondary' href='#ratings'>SEE MORE REVIEWS</a></section>
<section class='ratings' id='ratings'><h2 class='display'>Ratings & reviews</h2><p class='review-score'>★★★★★ &nbsp; 2079 reviews</p><div class='rating-list'><article><b>NICHOLAS</b><span>★★★★★</span><p>Great variety and a useful way to discover a better fit over time.</p></article><article><b>VICKI</b><span>★★★★★</span><p>Convenient deliveries and interesting coffees from different roasters.</p></article><article><b>JOHN</b><span>★★★★★</span><p>A long-running rotation that keeps each month interesting.</p></article><article><b>JOYEE</b><span>★★★★★</span><p>Easy to adjust around changing coffee usage.</p></article></div></section>
<section class='home-faq'><h2 class='display'>Frequently asked questions</h2><details><summary>WHAT IS BEAN BOX?</summary><p>A specialty coffee discovery and subscription experience curated around your preferences.</p></details><details><summary>HOW DOES THE COFFEE SUBSCRIPTION WORK?</summary><p>Choose preparation, taste, quantity and cadence; then review before checkout.</p></details><details><summary>CAN I CUSTOMIZE MY SUBSCRIPTION?</summary><p>Yes. The observed configurator offers taste profiles, bag quantities and delivery every 2–6 weeks.</p></details><details><summary>HOW FRESH IS THE COFFEE?</summary><p>The source emphasizes delivery within days of roasting rather than shelf storage.</p></details><details><summary>CAN I PAUSE OR CHANGE A PLAN?</summary><p>You can move backward and change choices before confirmation.</p></details><a class='button' href='/faq'>READ THE FULL FAQ</a></section>
<section class='roaster-strip'><h2 class='display'>Bringing you the world's best coffee roasters</h2><div>Broadcast &nbsp; · &nbsp; Camber &nbsp; · &nbsp; Olympia &nbsp; · &nbsp; Partners &nbsp; · &nbsp; Sightglass &nbsp; · &nbsp; Temple</div></section>"""
    return page("World's Best Coffee Subscription | Bean Box®", body, owner, cookies=True)


def subscription_body(draft: dict, owner: str, error: str = "") -> str:
    active = int(draft["step"])
    prefix = steps(active) + "<section class='config-wrap'>"
    if error:
        prefix += f"<div class='errors' role='alert'>{esc(error)}</div>"
    if active == 1:
        cards = "".join(f"<label class='choice'>{'<span class=popular>MOST POPULAR</span>' if key == 'curators-choice' else ''}<input type='radio' name='taste' value='{key}' {'checked' if draft['taste']==key else ''}><span class='choice-icon icon-{key}' aria-hidden='true'></span><span class='choice-copy'><strong>{label}</strong><span>{copy}</span><b>{count}</b></span></label>" for key,label,copy,count in TASTES)
        return prefix + f"<h1 class='display'>What's your ideal coffee tasting experience?</h1><p class='lede'>Choose a preparation, then a profile for your plan.</p><form method='post'>{hidden_owner(owner)}<input type='hidden' name='action' value='to-quantity'><label class='prep-select'>How do you take your coffee?<select name='preparation'><option value='whole-bean' {'selected' if draft['preparation']=='whole-bean' else ''}>Whole Bean</option><option value='freshly-ground' {'selected' if draft['preparation']=='freshly-ground' else ''}>Freshly Ground</option></select></label><div class='choice-grid'>{cards}</div><div class='form-actions'><a class='button secondary' href='/'>Back</a><button class='button' type='submit'>CONTINUE TO QUANTITY</button></div></form></section>"
    if active == 2:
        quantities = "".join(f"<label class='quantity-card'><input type='radio' name='quantity' value='{key}' {'checked' if draft['quantity']==key else ''}><strong>{label}</strong><br>{amount}<br><span class='muted'>{detail}</span></label>" for key,label,amount,detail in QUANTITIES)
        cadence = "".join(f"<label><input type='radio' name='cadence' value='{week}' {'checked' if draft['cadence']==week else ''}> Every {week} weeks{' · Monthly' if week=='4' else ''}</label>" for week in ("2","3","4","5","6"))
        return prefix + f"<h1 class='display'>How much coffee would you like per delivery?</h1><p class='lede'>Choose the amount and schedule that fits your mornings.</p><form method='post'>{hidden_owner(owner)}<input type='hidden' name='action' value='to-review'><div class='quantity-grid'>{quantities}</div><h2>Delivery frequency</h2><div class='cadence'>{cadence}</div><div class='form-actions'><button class='button secondary' name='action' value='back-tasting'>BACK</button><button class='button' type='submit'>CONTINUE TO REVIEW</button></div></form></section>"
    plan_cards = "".join(f"<label class='plan-card'><input type='radio' name='plan' value='{key}' {'checked' if draft['plan']==key else ''}><strong>{label}</strong><p>{copy}</p></label>" for key,label,copy in (("pay-per-delivery","Pay-Per-Delivery","About $17 per 12 oz bag plus $5.45 shipping."),("annual","Annual Plan","About $15 per bag with shipping included.")))
    labels = {"whole-bean":"Whole Bean","freshly-ground":"Freshly Ground","curators-choice":"Curator's Choice™"}
    amount = business.draft_amount_minor(draft)
    return prefix + f"<h1 class='display'>One last step to better mornings</h1><p class='lede'>Review your coffee and choose how you would like to pay.</p><form method='post'>{hidden_owner(owner)}<input type='hidden' name='action' value='checkout'><div class='plan-grid'>{plan_cards}</div><div class='review-box'><span>Preparation</span><strong>{esc(labels.get(draft['preparation'],draft['preparation']))}</strong><span>Taste</span><strong>{esc(labels.get(draft['taste'],draft['taste']))}</strong><span>Quantity</span><strong>{esc(dict((k,a) for k,_,a,_ in QUANTITIES).get(draft['quantity']))}</strong><span>Delivery</span><strong>Every {esc(draft['cadence'])} weeks</strong><span>Today's total</span><strong>{money(amount)}</strong></div><div class='form-actions'><button class='button secondary' name='action' value='back-quantity'>BACK</button><button class='button' type='submit'>CHECKOUT</button></div></form></section>"


@app.get("/coffee-subscription/configure", include_in_schema=False)
async def configure(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    with BACKEND.lifecycle.connection() as connection:
        draft = business.load_draft(connection, owner)
    return page("Bean Box® | Configure Your Coffee Subscription", subscription_body(draft, owner), owner, "subscriptions", cookies=True)


@app.post("/coffee-subscription/configure", include_in_schema=False)
async def configure_post(request: Request) -> Response:
    form = await request.form()
    try:
        owner = submitted_owner(request, form.get("owner"))
    except ValueError:
        return JSONResponse({"error": "session actor mismatch"}, status_code=403)
    action = str(form.get("action") or "")
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        draft = business.load_draft(connection, owner)
        if action == "back-tasting":
            draft["step"] = 1
        elif action == "back-quantity":
            draft["step"] = 2
        elif action == "to-quantity":
            prep, taste = str(form.get("preparation") or ""), str(form.get("taste") or "")
            if prep not in {"whole-bean","freshly-ground"} or taste not in {item[0] for item in TASTES}:
                return page("Choose your coffee", subscription_body(draft, owner, "Choose a preparation and tasting experience."), owner, "subscriptions", status=422)
            draft.update(preparation=prep, taste=taste, step=2)
        elif action == "to-review":
            quantity, cadence = str(form.get("quantity") or ""), str(form.get("cadence") or "")
            if quantity not in {item[0] for item in QUANTITIES} or cadence not in {"2","3","4","5","6"}:
                return page("Choose quantity", subscription_body(draft, owner, "Choose a quantity and delivery frequency."), owner, "subscriptions", status=422)
            draft.update(quantity=quantity, cadence=cadence, step=3)
        elif action == "checkout":
            plan = str(form.get("plan") or "")
            if plan not in {"pay-per-delivery","annual"}:
                return page("Choose a plan", subscription_body(draft, owner, "Choose Pay-Per-Delivery or Annual Plan."), owner, "subscriptions", status=422)
            draft.update(plan=plan, step=3)
            business.save_draft(connection, owner, draft)
            return RedirectResponse("/checkout", status_code=303)
        business.save_draft(connection, owner, draft)
    return page("Bean Box® | Configure Your Coffee Subscription", subscription_body(draft, owner), owner, "subscriptions")


def product_card(row) -> str:
    colors = ("#d7b77d", "#6f75aa", "#d8c9c0", "#9ca878", "#d6907a", "#b3a08b")
    return f"<article class='product-card'><a href='/coffee/{esc(row['slug'])}'><div class='product-art' style='--card:{colors[int(row['id'])%len(colors)]};--tilt:{(int(row['id'])%7)-3}deg'><div class='coffee-bag'>{esc(row['roaster'].split()[0])}<br>COFFEE</div></div><h2>{esc(row['name'])}</h2><em>{esc(row['roast'].title())} · {esc(row['origin'])}</em><span class='price'>{money(int(row['price_minor']))}</span></a></article>"


@app.get("/coffee", include_in_schema=False)
async def coffee(request: Request, q: str = "", roast: str = "", page_number: int = 1) -> HTMLResponse:
    owner = request_owner(request)
    raw_page = request.query_params.get("page", str(page_number))
    try:
        current_page = int(raw_page or "1")
    except ValueError:
        return page("Catalogue | Bean Box®", "<section class='config-wrap'><div class='errors'>Page must be a positive integer.</div></section>", owner, "coffee", status=422)
    if current_page < 1 or current_page > 1000:
        return page("Catalogue | Bean Box®", "<section class='config-wrap'><div class='errors'>Page must be between 1 and 1000.</div></section>", owner, "coffee", status=422)
    with BACKEND.lifecycle.connection() as connection:
        rows, total = business.list_coffees(connection, q.strip()[:80], roast, current_page)
    grid = "".join(product_card(row) for row in rows) if rows else "<div class='zero'><h2>No coffees found</h2><p>Try another coffee, roaster or roast profile.</p><a class='button' href='/coffee'>CLEAR SEARCH</a></div>"
    pages = max(1, math.ceil(total / 18))
    pager = "<nav class='pager' aria-label='Pagination'>" + "".join(f"<a class='{'current' if n==current_page else ''}' href='/coffee?q={quote_plus(q)}&roast={quote_plus(roast)}&page={n}'>{n}</a>" for n in range(max(1,current_page-2), min(pages,current_page+2)+1)) + "</nav>"
    sidebar = "".join(f"<a href='/coffee?roast={key}'>{key.title()} ({count})</a>" for key,count in (("light",80),("medium",80),("dark",80)))
    mobile_filters = f"<details class='mobile-filters'><summary>FILTER</summary><div><strong>Roast profile</strong>{sidebar}<a href='/coffee?q=blend'>Blend (80)</a><a href='/coffee?q=single+origin'>Single origin (160)</a><a href='/coffee'>Clear filters</a></div></details>"
    body = f"<section class='catalogue-layout'><aside class='filters'><h3>Roast Profile</h3>{sidebar}<h3>Coffee Type</h3><a href='/coffee?q=blend'>Blend (80)</a><a href='/coffee?q=single+origin'>Single origin (160)</a><h3>Curation</h3><a href='/coffee?q=curated'>Curator's choice</a><a href='/coffee'>Top-rated</a></aside><div class='catalogue-main'><h1 class='display'>The best specialty coffee beans, curated by a Cup of Excellence judge</h1><form class='searchbar' method='get'><input id='catalog-search' name='q' value='{esc(q)}' placeholder='Search coffee, roaster, origin or taste'><input type='hidden' name='roast' value='{esc(roast)}'><button class='button'>SEARCH</button></form>{mobile_filters}<p><strong>{total}</strong> coffees · page {current_page} of {pages}</p><div class='product-grid'>{grid}</div>{pager}</div></section>"
    return page("Specialty Coffee | Bean Box®", body, owner, "coffee", cookies=True)


@app.get("/coffee/{slug}", include_in_schema=False)
async def coffee_detail(slug: str, request: Request) -> HTMLResponse:
    owner = request_owner(request)
    with BACKEND.lifecycle.connection() as connection:
        row = business.coffee_by_slug(connection, slug)
    if row is None:
        return not_found(owner)
    colors = ("#d7b77d", "#6f75aa", "#d8c9c0", "#9ca878")
    body = f"<article class='detail'><div class='product-art' style='--card:{colors[int(row['id'])%len(colors)]}'><div class='coffee-bag'>{esc(row['roaster'].split()[0])}<br>COFFEE</div></div><div><span class='eyebrow'>{esc(row['roaster'])}</span><h1 class='display'>{esc(row['name'])}</h1><p class='notes'>{esc(row['notes'])}</p><p>★★★★★ {row['rating']} · {row['reviews']} reviews</p><p>{esc(row['description'])}</p><p><span class='badge'>{esc(row['roast'].title())} roast</span> <span class='badge'>{esc(row['coffee_type'].title())}</span></p><h2>{money(int(row['price_minor']))} · 12 oz</h2><form method='post' action='/cart/add'>{hidden_owner(owner)}<input type='hidden' name='coffee_id' value='{row['id']}'><button class='button'>ADD TO CART</button></form><p><a href='/coffee'>← Back to all coffee</a></p></div></article>"
    return page(f"{row['name']} | Bean Box®", body, owner, "coffee")


@app.post("/cart/add", include_in_schema=False)
async def cart_add(request: Request) -> Response:
    form = await request.form()
    try:
        owner = submitted_owner(request, form.get("owner"))
    except ValueError:
        return JSONResponse({"error": "session actor mismatch"}, status_code=403)
    try:
        coffee_id = int(str(form.get("coffee_id") or "0"))
    except ValueError:
        coffee_id = 0
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        exists = connection.execute("SELECT 1 FROM bean_box_coffees WHERE id=?", (coffee_id,)).fetchone()
        if exists is None:
            return JSONResponse({"error":"coffee-not-found"}, status_code=404)
        business.add_cart(connection, owner, coffee_id)
    return RedirectResponse("/cart", status_code=303)


@app.get("/cart", include_in_schema=False)
async def cart_page(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    with BACKEND.lifecycle.connection() as connection:
        rows = business.cart(connection, owner)
    if not rows:
        body = "<section class='cart'><h1 class='display'>Your cart is empty</h1><p>Explore our curated coffee collection or configure a subscription.</p><a class='button' href='/coffee'>SHOP COFFEE</a> <a class='button secondary' href='/coffee-subscription/configure'>CHOOSE A SUBSCRIPTION</a></section>"
    else:
        items = "".join(f"<div class='cart-row'><div class='product-art'><div class='coffee-bag'>COFFEE</div></div><div><h2>{esc(row['name'])}</h2><span>{esc(row['roaster'])} · Qty {row['quantity']}</span></div><strong>{money(int(row['price_minor'])*int(row['quantity']))}</strong></div>" for row in rows)
        total = sum(int(row['price_minor'])*int(row['quantity']) for row in rows)
        body = f"<section class='cart'><h1 class='display'>Your cart</h1>{items}<p class='total'>Subtotal: {money(total)}</p><a class='button' href='/coffee'>KEEP SHOPPING</a></section>"
    return page("Your Cart | Bean Box®", body, owner)


def checkout_body(draft: dict, owner: str, values: dict[str,str] | None = None, error: str = "", success: dict | None = None) -> str:
    amount = business.draft_amount_minor(draft)
    if success:
        return f"<section class='checkout'><div class='success' role='status' tabindex='-1'><span class='eyebrow'>Simulation complete</span><h1 class='display'>Your better mornings are queued</h1><p>Order <strong>{esc(success['order_id'])}</strong> was recorded in the Bean Box account.</p><p>No subscription, email, address or payment was sent to Bean Box or any provider.</p><a class='button' href='/coffee-subscription/configure'>BACK TO SUBSCRIPTIONS</a></div></section>"
    values = values or {}
    scenario_value = values.get("scenario_id", "sandbox-approved")
    def val(name: str) -> str: return esc(values.get(name, ""))
    error_html = f"<div class='errors' role='alert'>{esc(error)}</div>" if error else ""
    summary = f"<div class='panel'><h2>Order summary</h2><div class='summary-line'><span>{esc(draft['taste'].replace('-', ' ').title())}</span><strong>{esc(draft['preparation'].replace('-', ' ').title())}</strong></div><div class='summary-line'><span>Quantity</span><strong>{esc(dict((k,a) for k,_,a,_ in QUANTITIES).get(draft['quantity']))}</strong></div><div class='summary-line'><span>Delivery</span><strong>Every {esc(draft['cadence'])} weeks</strong></div><div class='summary-line'><span>Plan</span><strong>{esc(draft['plan'].replace('-', ' ').title())}</strong></div><div class='summary-line total'><span>Total</span><strong>{money(amount)}</strong></div><p class='muted'>Simulation only. No card fields exist.</p></div>"
    fields = "".join(f"<div class='field {'full' if name in {'email','address'} else ''}'><label for='{name}'>{label}</label><input id='{name}' name='{name}' value='{val(name)}' autocomplete='off' required></div>" for name,label in (("first_name","First name"),("last_name","Last name"),("email","Email fixture"),("address","Address fixture"),("city","City"),("state","State"),("zip","ZIP code")))
    options = "".join(f"<option value='{key}' {'selected' if scenario_value == key else ''}>{label}</option>" for key, label in (("sandbox-approved", "Simulated approval"), ("sandbox-declined", "Simulated decline"), ("sandbox-retry", "Simulated retry")))
    form = f"<form method='post'><div class='fixture-note'><strong>Safety fixture:</strong> use only the synthetic values supplied here. <button type='button' data-fill-fixture>Fill synthetic fixture</button></div>{error_html}<section class='panel'><h2>Shipping details</h2><div class='field-grid'>{fields}</div></section><section class='panel'><h2>Payment simulation</h2><div class='field full'><label for='scenario_id'>Simulation outcome</label><select id='scenario_id' name='scenario_id'>{options}</select></div><p>No card number, CVV, expiry, wallet or banking input is accepted.</p></section>{hidden_owner(owner)}<input type='hidden' name='idempotency_key' value='checkout-{hashlib.sha256((owner+json.dumps(draft,sort_keys=True)).encode()).hexdigest()[:24]}'><button class='button' type='submit'>CONFIRM ORDER</button></form>"
    return f"<section class='checkout'><h1 class='display'>Checkout</h1><div class='checkout-grid'><div>{form}</div><aside>{summary}</aside></div></section>"


@app.get("/checkout", include_in_schema=False)
async def checkout_get(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    with BACKEND.lifecycle.connection() as connection:
        draft = business.load_draft(connection, owner)
    return page("Checkout | Bean Box®", checkout_body(draft, owner), owner)


@app.post("/checkout", include_in_schema=False)
async def checkout_post(request: Request) -> HTMLResponse:
    form = await request.form()
    try:
        owner = submitted_owner(request, form.get("owner"))
    except ValueError:
        return JSONResponse({"error": "session actor mismatch"}, status_code=403)
    items = [(str(key), str(value)) for key, value in form.multi_items()]
    keys = [key for key, _value in items]
    if len(keys) != len(set(keys)) or any(len(key) > 80 or len(value) > 500 for key, value in items):
        owner = request_owner(request)
        with BACKEND.lifecycle.connection() as connection:
            draft = business.load_draft(connection, owner)
        return page("Checkout rejected | Bean Box®", checkout_body(draft, owner, error="Duplicate or oversized checkout fields are forbidden."), owner, status=422)
    fields = dict(items)
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        draft = business.load_draft(connection, owner)
        allowed_fields = set(FIXTURE) | {"owner", "scenario_id", "idempotency_key"}
        unknown = set(fields) - allowed_fields
        if unknown:
            return page("Checkout rejected | Bean Box®", checkout_body(draft, owner, fields, "Only the synthetic shipping fixture and opaque simulation fields are accepted; payment credentials are forbidden."), owner, status=422)
        mismatched = [name for name, expected in FIXTURE.items() if fields.get(name) != expected]
        if mismatched:
            return page("Synthetic fixture required | Bean Box®", checkout_body(draft, owner, fields, "Use the supplied synthetic fixture exactly; real or arbitrary personal data is not accepted."), owner, status=422)
        scenario = fields.get("scenario_id", "")
        if scenario not in {"sandbox-approved","sandbox-declined","sandbox-retry"}:
            return page("Choose payment simulation | Bean Box®", checkout_body(draft, owner, fields, "Choose an approved simulation scenario."), owner, status=422)
        idempotency = fields.get("idempotency_key", "")[:200]
        existing = connection.execute("SELECT order_id,status FROM bean_box_orders WHERE owner=? AND idempotency_key=?", (owner, idempotency)).fetchone()
        if existing:
            prior = connection.execute("SELECT amount_minor,snapshot_json FROM bean_box_orders WHERE order_id=?", (existing["order_id"],)).fetchone()
            prior_snapshot = json.loads(prior["snapshot_json"])
            if int(prior["amount_minor"]) != business.draft_amount_minor(draft) or prior_snapshot.get("draft") != draft:
                return page("Checkout conflict | Bean Box®", checkout_body(draft, owner, fields, "This idempotency key is bound to a different order configuration."), owner, status=409)
            business.create_subscription(connection, owner, existing["order_id"], draft)
            return page("Order recorded | Bean Box®", checkout_body(draft, owner, success={"order_id": existing["order_id"]}), owner)
        amount = business.draft_amount_minor(draft)
        fingerprint = business.payment_fingerprint(owner, draft, amount)
        try:
            flow = BACKEND.payments.create_intent(owner=owner, amount_minor=amount, currency="USD", fingerprint=fingerprint, idempotency_key=f"create.{idempotency}", connection=connection)
            attempt = BACKEND.payments.attempt(flow_id=flow["flow_id"], owner=owner, amount_minor=amount, currency="USD", fingerprint=fingerprint, scenario_id=scenario, idempotency_key=f"attempt.{idempotency}.{scenario}", connection=connection)
            if attempt["status"] != "APPROVED":
                message = "The local payment simulation was declined. Choose Simulated approval and retry." if attempt["status"] == "DECLINED" else "The local payment simulation is retryable. Please retry or choose Simulated approval."
                status = 402 if attempt["status"] == "DECLINED" else 409
                return page("Payment simulation | Bean Box®", checkout_body(draft, owner, fields, message), owner, status=status)
            BACKEND.payments.consume_approval(connection, flow_id=flow["flow_id"], owner=owner, amount_minor=amount, currency="USD", fingerprint=fingerprint)
            order_id = "BB-" + hashlib.sha256((owner + idempotency).encode()).hexdigest()[:10].upper()
            snapshot = {"site_id": SITE_ID, "draft": draft, "shipping_fixture": FIXTURE, "payment": {"adapter": "local-sandbox", "scenario_id": scenario, "is_simulation": True}}
            connection.execute("INSERT INTO bean_box_orders(order_id,owner,idempotency_key,payment_flow_id,status,amount_minor,snapshot_json,created_at) VALUES (?,?,?,?,?,?,?,datetime('now'))", (order_id, owner, idempotency, flow["flow_id"], "local-confirmed", amount, json.dumps(snapshot, sort_keys=True)))
            business.create_subscription(connection, owner, order_id, draft)
        except PaymentError as exc:
            connection.rollback()
            return page("Payment simulation error | Bean Box®", checkout_body(draft, owner, fields, str(exc)), owner, status=422)
    return page("Order recorded | Bean Box®", checkout_body(draft, owner, success={"order_id": order_id}), owner)


@app.get("/api/catalogue/count", include_in_schema=False)
async def catalogue_count() -> JSONResponse:
    with BACKEND.lifecycle.connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM bean_box_coffees").fetchone()[0]
    return JSONResponse({"site_id": SITE_ID, "coffee_records": count})


@app.post("/api/cart/items", include_in_schema=False)
async def api_cart_add(request: Request) -> JSONResponse:
    payload, error = await _json_object(request)
    if error is not None:
        return error
    if not isinstance(payload, dict) or set(payload) - {"coffee_id", "owner"}:
        return JSONResponse({"error": "unknown field"}, status_code=422)
    owner = request_owner(request)
    if payload.get("owner") is not None and payload.get("owner") != owner:
        return JSONResponse({"error": "session actor mismatch"}, status_code=403)
    coffee_id = payload.get("coffee_id")
    if type(coffee_id) is not int or not 1 <= coffee_id <= 240:
        return JSONResponse({"error": "coffee_id required"}, status_code=422)
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        if connection.execute("SELECT 1 FROM bean_box_coffees WHERE id=?", (coffee_id,)).fetchone() is None:
            return JSONResponse({"error": "coffee not found"}, status_code=404)
        business.add_cart(connection, owner, coffee_id)
        count = sum(int(row["quantity"]) for row in business.cart(connection, owner))
    return JSONResponse({"site_id": SITE_ID, "cart_count": count}, status_code=201)


@app.get("/api/cart", include_in_schema=False)
async def api_cart(request: Request) -> JSONResponse:
    owner = request_owner(request)
    supplied = request.query_params.get("owner")
    if supplied is not None and supplied != owner:
        return JSONResponse({"error": "session actor mismatch"}, status_code=403)
    with BACKEND.lifecycle.connection() as connection:
        count = sum(int(row["quantity"]) for row in business.cart(connection, owner))
    return JSONResponse({"site_id": SITE_ID, "cart_count": count})


@app.post("/api/checkout/validate", include_in_schema=False)
async def api_checkout_validate(request: Request) -> JSONResponse:
    payload, error = await _json_object(request)
    if error is not None:
        return error
    if not isinstance(payload, dict) or set(payload) != {"scenario_id"}:
        return JSONResponse({"error": "only opaque scenario_id is accepted"}, status_code=422)
    scenario = payload.get("scenario_id")
    if scenario not in {"sandbox-approved", "sandbox-declined", "sandbox-retry"}:
        return JSONResponse({"error": "unknown local-sandbox scenario"}, status_code=422)
    return JSONResponse({"site_id": SITE_ID, "adapter": "local-sandbox", "scenario_id": scenario})


@app.get("/coffee-gifts", include_in_schema=False)
async def gifts(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    body = "<section class='intro'><span class='eyebrow'>Share a better morning</span><h1 class='display'>Coffee gifts for every kind of coffee lover</h1><p>Explore subscription gifts, tasting boxes, pairings and equipment picks.</p><a class='button' href='/coffee-subscription/configure'>GIVE A SUBSCRIPTION</a></section>"
    return page("Coffee Gifts | Bean Box®", body, owner, "gifts")


@app.get("/coffee-equipment", include_in_schema=False)
async def gear(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    body = "<section class='intro'><span class='eyebrow'>Brew it beautifully</span><h1 class='display'>Coffee equipment</h1><p>Thoughtful brewers, kettles, mugs and scales selected for a better home setup.</p><a class='button' href='/coffee'>PAIR WITH COFFEE</a></section>"
    return page("Coffee Equipment | Bean Box®", body, owner, "gear")


@app.get("/faq", include_in_schema=False)
async def faq(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    questions = (("What is Bean Box?","A curated specialty coffee discovery and subscription experience."),("Can I get ground coffee?","Yes. Choose Freshly Ground during Tasting Experience."),("How often can coffee arrive?","Every 2, 3, 4, 5 or 6 weeks. Four weeks is the monthly option."),("Can I change my plan?","Return to the configurator before confirming."),("Is this a real payment?","No. Checkout accepts only synthetic simulation scenarios and makes zero remote requests."))
    body = "<section class='config-wrap'><h1 class='display'>Frequently asked questions</h1>" + "".join(f"<details class='panel'><summary><strong>{esc(q)}</strong></summary><p>{esc(a)}</p></details>" for q,a in questions) + "</section>"
    return page("FAQ | Bean Box®", body, owner)


@app.get("/roasters", include_in_schema=False)
@app.get("/about", include_in_schema=False)
@app.get("/contact", include_in_schema=False)
@app.get("/blog", include_in_schema=False)
@app.get("/resources", include_in_schema=False)
@app.get("/terms", include_in_schema=False)
@app.get("/privacy", include_in_schema=False)
@app.get("/returns", include_in_schema=False)
async def information_page(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    slug = request.url.path.strip("/")
    content = {
        "roasters": ("Coffee roasters", "A directory-style view of the independent-roaster catalogue represented by the 240 searchable coffee fixtures."),
        "about": ("About this experience", "This experience preserves observed public structure and interactions without claiming source affiliation or redistribution rights."),
        "contact": ("Contact", "Contact submission and real email are outside the frozen anonymous scope. No message or address is collected here."),
        "blog": ("Coffee stories", "An index for the publicly observed editorial route; source articles were not redistributed."),
        "resources": ("Coffee resources", "Explore the working catalogue, configurator and FAQ without any runtime request to the source website."),
        "terms": ("Terms of service", "No source legal text is reproduced. This evaluation experience cannot create a real order or subscription."),
        "privacy": ("Privacy", "The site uses only a site-bound anonymous session. It rejects real payment data and does not send runtime traffic to the source."),
        "returns": ("Returns", "Real fulfillment and returns are unavailable because checkout creates no source order."),
    }
    title, copy = content[slug]
    body = f"<section class='editorial-page' data-content-status='scope-limited'><span class='eyebrow'>Bean Box</span><h1 class='display'>{esc(title)}</h1><p>{esc(copy)}</p><a class='button' href='/coffee'>EXPLORE COFFEE</a></section>"
    return page(f"{title} | Bean Box®", body, owner)


@app.get("/account", include_in_schema=False)
async def account(request: Request) -> HTMLResponse:
    owner = request_owner(request)
    account_info = authenticated_account(request)
    if account_info is None:
        body = "<section class='config-wrap'><h1 class='display'>My account</h1><div class='plan-grid'><div class='panel'><h2>Sign in</h2><p>Use a synthetic account to manage subscriptions.</p><a class='button' href='/account/signin'>SIGN IN</a></div><div class='panel'><h2>Create an account</h2><p>Only @example.test addresses are accepted; no email leaves this site.</p><a class='button secondary' href='/account/register'>REGISTER</a></div></div><p><a href='/account/password-reset'>Forgot your password?</a></p></section>"
        return page("My Account | Bean Box®", body, owner)
    body = f"<section class='config-wrap'><span class='eyebrow'>Account</span><h1 class='display'>Welcome, {esc(account_info['display_name'])}</h1><p>{esc(account_info['email_normalized'])}</p><div class='plan-grid'><a class='panel' href='/account/subscriptions'><h2>Subscriptions</h2><p>Modify, pause, skip, cancel or reactivate plans.</p></a><a class='panel' href='/account/orders'><h2>Order history</h2><p>Review checkout records.</p></a></div><form method='post' action='/account/signout'><button class='button secondary'>SIGN OUT</button></form></section>"
    return page("My Account | Bean Box®", body, owner)


def auth_form(title: str, fields: str, action: str, error: str = "", note: str = "") -> str:
    alert = f"<div class='errors' role='alert'>{esc(error)}</div>" if error else ""
    return f"<section class='config-wrap'><h1 class='display'>{esc(title)}</h1>{alert}<div class='panel'><p>{esc(note)}</p><form method='post' action='{action}'>{fields}<button class='button' type='submit'>CONTINUE</button></form></div></section>"


@app.get("/account/register", include_in_schema=False)
async def register_get(request: Request) -> HTMLResponse:
    fields = "<input type='hidden' name='phase' value='start'><div class='field'><label for='display_name'>Display name</label><input id='display_name' name='display_name' required maxlength='80'></div><div class='field'><label for='email'>Synthetic email</label><input id='email' name='email' type='email' placeholder='student@example.test' required></div><div class='field'><label for='password'>Local password</label><input id='password' name='password' type='password' minlength='10' required></div>"
    return page("Register | Bean Box®", auth_form("Create an account", fields, "/account/register", note="Synthetic identity only. No source account or real email is used."), request_owner(request))


@app.post("/account/register", include_in_schema=False)
async def register_post(request: Request) -> HTMLResponse:
    form = await request.form()
    token = str(request.state.auth_token)
    phase = str(form.get("phase") or "start")
    try:
        if phase == "start":
            email = _synthetic_email(str(form.get("email") or ""))
            _AUTH.start_registration(token, email=email, display_name=str(form.get("display_name") or ""), password=str(form.get("password") or ""))
            mail = _AUTH.local_mail_for_session(token, purpose="registration")
            if mail is None:
                raise AuthError("Local verification message is unavailable.")
            fields = f"<input type='hidden' name='phase' value='verify'><div class='fixture-note'>Local-only verification code: <strong data-local-code>{esc(mail['verification_code'])}</strong></div><div class='field'><label for='code'>Verification code</label><input id='code' name='code' inputmode='numeric' required></div>"
            return page("Verify registration | Bean Box®", auth_form("Verify your local account", fields, "/account/register", note="The code is rendered from the isolated local outbox; no message was sent."), request_owner(request))
        _AUTH.verify_registration_code(token, str(form.get("code") or ""))
        result = _AUTH.complete_registration(token)
        response = RedirectResponse("/account", status_code=303)
        _set_auth_cookie(request, response, str(result["session_token"]))
        return response
    except (AuthError, ValueError) as exc:
        fields = "<input type='hidden' name='phase' value='start'><div class='field'><label>Display name<input name='display_name' required></label></div><div class='field'><label>Synthetic email<input name='email' type='email' required></label></div><div class='field'><label>Local password<input name='password' type='password' minlength='10' required></label></div>"
        return page("Registration error | Bean Box®", auth_form("Create an account", fields, "/account/register", str(exc), "Use a unique @example.test fixture."), request_owner(request), status=422)


@app.get("/account/signin", include_in_schema=False)
async def signin_get(request: Request) -> HTMLResponse:
    fields = "<div class='field'><label for='email'>Synthetic email</label><input id='email' name='email' type='email' required></div><div class='field'><label for='password'>Local password</label><input id='password' name='password' type='password' required></div>"
    return page("Sign in | Bean Box®", auth_form("Sign in", fields, "/account/signin", note="Synthetic accounts only."), request_owner(request))


@app.post("/account/signin", include_in_schema=False)
async def signin_post(request: Request) -> HTMLResponse:
    form = await request.form()
    try:
        email = _synthetic_email(str(form.get("email") or ""))
        result = _AUTH.sign_in(str(request.state.auth_token), email=email, password=str(form.get("password") or ""))
        response = RedirectResponse("/account", status_code=303)
        _set_auth_cookie(request, response, str(result["session_token"]))
        return response
    except (AuthError, ValueError):
        fields = "<div class='field'><label>Synthetic email<input name='email' type='email' required></label></div><div class='field'><label>Local password<input name='password' type='password' required></label></div>"
        return page("Sign in error | Bean Box®", auth_form("Sign in", fields, "/account/signin", "Credentials are invalid.", "Synthetic accounts only."), request_owner(request), status=401)


@app.post("/account/signout", include_in_schema=False)
async def signout(request: Request) -> Response:
    _AUTH.sign_out(str(request.state.auth_token))
    response = RedirectResponse("/account", status_code=303)
    _set_auth_cookie(request, response, _AUTH.create_anonymous_session())
    return response


@app.get("/account/password-reset", include_in_schema=False)
async def password_reset_get(request: Request) -> HTMLResponse:
    fields = "<input type='hidden' name='phase' value='start'><div class='field'><label for='email'>Synthetic email</label><input id='email' name='email' type='email' required></div>"
    return page("Password recovery | Bean Box®", auth_form("Reset local password", fields, "/account/password-reset", note="Only a matching @example.test local account can produce a local code."), request_owner(request))


@app.post("/account/password-reset", include_in_schema=False)
async def password_reset_post(request: Request) -> HTMLResponse:
    form = await request.form()
    token = str(request.state.auth_token)
    phase = str(form.get("phase") or "start")
    try:
        if phase == "start":
            email = _synthetic_email(str(form.get("email") or ""))
            _AUTH.start_password_reset(token, email=email)
            mail = _AUTH.local_mail_for_session(token, purpose="password-reset")
            if mail is None:
                return page("Password recovery | Bean Box®", auth_form("Check the account", "<input type='hidden' name='phase' value='start'><div class='field'><label>Synthetic email<input name='email' type='email' required></label></div>", "/account/password-reset", note="If the account exists, a verification code is available. No email was sent."), request_owner(request))
            fields = f"<input type='hidden' name='phase' value='complete'><div class='fixture-note'>Local-only reset code: <strong data-local-code>{esc(mail['verification_code'])}</strong></div><div class='field'><label>Reset code<input name='code' required></label></div><div class='field'><label>New local password<input name='new_password' type='password' minlength='10' required></label></div>"
            return page("Verify password reset | Bean Box®", auth_form("Choose a new local password", fields, "/account/password-reset", note="No real message or account is involved."), request_owner(request))
        _AUTH.verify_password_reset_code(token, str(form.get("code") or ""))
        new_token = _AUTH.complete_password_reset(token, new_password=str(form.get("new_password") or ""))
        response = RedirectResponse("/account", status_code=303)
        _set_auth_cookie(request, response, new_token)
        return response
    except (AuthError, ValueError) as exc:
        fields = "<input type='hidden' name='phase' value='start'><div class='field'><label>Synthetic email<input name='email' type='email' required></label></div>"
        return page("Password recovery error | Bean Box®", auth_form("Reset local password", fields, "/account/password-reset", str(exc), "Local synthetic accounts only."), request_owner(request), status=422)


def _account_required(request: Request) -> HTMLResponse | None:
    if authenticated_account(request) is None:
        return page("Sign in required | Bean Box®", "<section class='config-wrap'><div class='errors'>Sign in with an account to manage subscriptions.</div><a class='button' href='/account/signin'>SIGN IN</a></section>", request_owner(request), status=401)
    return None


@app.get("/account/subscriptions", include_in_schema=False)
async def subscription_management(request: Request) -> HTMLResponse:
    denied = _account_required(request)
    if denied:
        return denied
    owner = request_owner(request)
    with BACKEND.lifecycle.connection() as connection:
        rows = business.subscriptions(connection, owner)
    if not rows:
        content = "<div class='panel'><h2>No subscriptions yet</h2><a class='button' href='/coffee-subscription/configure'>START A SUBSCRIPTION</a></div>"
    else:
        cards = []
        for row in rows:
            draft = json.loads(row["draft_json"])
            actions = "<button name='action' value='modify'>SAVE CHANGES</button>"
            if row["status"] == "active":
                actions += "<button name='action' value='skip'>SKIP NEXT</button><button name='action' value='pause'>PAUSE</button><button name='action' value='cancel'>CANCEL</button>"
            elif row["status"] == "paused":
                actions += "<button name='action' value='reactivate'>RESUME</button><button name='action' value='cancel'>CANCEL</button>"
            else:
                actions += "<button name='action' value='reactivate'>REACTIVATE</button>"
            cards.append(f"<article class='panel'><h2>{esc(row['subscription_id'])}</h2><p>Status: <strong>{esc(row['status'])}</strong> · skipped {row['skip_count']} · {esc(row['next_delivery_label'])}</p><form method='post' action='/account/subscriptions/{esc(row['subscription_id'])}'><label>Preparation<select name='preparation'><option value='whole-bean' {'selected' if draft['preparation']=='whole-bean' else ''}>Whole Bean</option><option value='freshly-ground' {'selected' if draft['preparation']=='freshly-ground' else ''}>Freshly Ground</option></select></label><label>Cadence<select name='cadence'>{''.join(f'<option value={w} {"selected" if draft["cadence"]==w else ""}>Every {w} weeks</option>' for w in ('2','3','4','5','6'))}</select></label><div class='form-actions'>{actions}</div></form></article>")
        content = "".join(cards)
    return page("Subscriptions | Bean Box®", f"<section class='config-wrap'><h1 class='display'>Manage subscriptions</h1>{content}<p><a href='/account/orders'>View order history</a></p></section>", owner)


@app.post("/account/subscriptions/{subscription_id}", include_in_schema=False)
async def subscription_action(subscription_id: str, request: Request) -> Response:
    denied = _account_required(request)
    if denied:
        return denied
    form = await request.form()
    action = str(form.get("action") or "")
    changes = {"preparation": str(form.get("preparation") or ""), "cadence": str(form.get("cadence") or "")} if action == "modify" else None
    try:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            row = business.update_subscription(connection, request_owner(request), subscription_id, action, changes)
            if row is None:
                return not_found(request_owner(request))
    except ValueError as exc:
        return page("Subscription error | Bean Box®", f"<section class='config-wrap'><div class='errors'>{esc(exc)}</div><a href='/account/subscriptions'>BACK</a></section>", request_owner(request), status=409)
    return RedirectResponse("/account/subscriptions", status_code=303)


@app.get("/account/orders", include_in_schema=False)
async def order_history(request: Request) -> HTMLResponse:
    denied = _account_required(request)
    if denied:
        return denied
    owner = request_owner(request)
    with BACKEND.lifecycle.connection() as connection:
        rows = business.orders(connection, owner)
    items = "".join(f"<article class='panel'><h2>{esc(row['order_id'])}</h2><p>{esc(row['status'])} · {money(int(row['amount_minor']))} · {esc(row['created_at'])}</p></article>" for row in rows) or "<div class='panel'>No orders yet.</div>"
    return page("Order history | Bean Box®", f"<section class='config-wrap'><h1 class='display'>Order history</h1>{items}</section>", owner)


def not_found(owner: str = "public-fixture-actor") -> HTMLResponse:
    return page("Page not found | Bean Box®", "<section class='notfound'><h1 class='display'>This page needs a fresh grind</h1><p>We couldn't find that page.</p><a class='button' href='/'>RETURN HOME</a></section>", owner, status=404)


@app.exception_handler(404)
async def handle_404(request: Request, exc: Exception) -> HTMLResponse:
    return not_found(request_owner(request))
