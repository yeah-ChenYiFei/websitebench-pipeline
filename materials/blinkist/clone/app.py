from __future__ import annotations

import html
import hashlib
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.site_backend_integration import open_site_services
from websitebench.local_clone_auth import AuthConflict, AuthError, AuthRejected
from websitebench.site_backend.errors import PaymentError, PaymentRejected

ROOT = Path(__file__).resolve().parent
BACKEND, AUTH = open_site_services()
DB = BACKEND.lifecycle.database_path
SITE_ID = "blinkist"
SESSION_COOKIE = BACKEND.session_cookie["name"]
LOCAL_SESSION_COOKIE = f"websitebench-{SITE_ID}-session"
COOKIE_SECURE = bool(BACKEND.session_cookie["secure"])
LOCAL_HTTP_COOKIE_OVERRIDE = os.environ.get("WEBSITEBENCH_LOCAL_HTTP_COOKIE", "1") == "1"
APP = FastAPI(title="Blinkist offline clone", docs_url=None, redoc_url=None, openapi_url=None)
APP.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
_DB_SCHEMA_LOCK = threading.Lock()
_DB_SCHEMA_READY = False

def esc(value: object) -> str:
    return html.escape(str(value), quote=True)

def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")

def books() -> list[dict[str, object]]:
    rows = [{"slug": "atomic-habits", "title": "Atomic Habits", "author": "James Clear", "category": "Productivity", "minutes": 25, "color": "#d9e6ff", "description": "An Easy & Proven Way to Build Good Habits & Break Bad Ones.", "narrator": "Amanda Mahr", "rating": 4.6, "ratings": 23456, "key_ideas": 7, "level": "Beginner", "language": "English", "schedule": "On demand"}]
    seed = [
        ("The Psychology of Money", "Morgan Housel", "Money"), ("Deep Work", "Cal Newport", "Productivity"),
        ("Thinking, Fast and Slow", "Daniel Kahneman", "Mind"), ("The 7 Habits of Highly Effective People", "Stephen R. Covey", "Self-improvement"),
        ("Essentialism", "Greg McKeown", "Productivity"), ("The Power of Habit", "Charles Duhigg", "Psychology"),
        ("The Almanack of Naval Ravikant", "Eric Jorgenson", "Success"), ("Mindset", "Carol S. Dweck", "Psychology"),
        ("Teams That Meet the Moment", "Karina Mangu-Ward", "Career & Success"),
        ("The Ambition Penalty", "Stefanie O’Connell", "Career & Success"),
    ]
    rows.extend({"slug": slugify(title), "title": title, "author": author, "category": category, "minutes": 12 + (i % 9), "color": ["#f6dccd", "#d8f0e8", "#f4e6bd", "#e7dafa"][i % 4], "description": f"A concise Blink of {title} with practical ideas you can apply today.", "narrator": "Blinkist Audio", "rating": 4.4, "ratings": 1200 + i, "key_ideas": 6, "level": ("Beginner", "Intermediate", "Advanced")[i % 3], "language": "English", "schedule": "On demand"} for i, (title, author, category) in enumerate(seed, 1))
    for i in range(len(rows), 200):
        title = f"Blinkist Guide {i + 1:03d}"
        rows.append({"slug": slugify(title), "title": title, "author": "Blinkist Editors", "category": ["Career", "Wellbeing", "Leadership", "Science"][i % 4], "minutes": 10 + i % 16, "color": ["#e2ebf8", "#f5ded6", "#e1f0df", "#ede4f6"][i % 4], "description": f"A concise Blink of {title} with practical ideas you can apply today.", "narrator": "Blinkist Audio", "rating": 4.2, "ratings": 800 + i, "key_ideas": 5, "level": ("Beginner", "Intermediate", "Advanced")[i % 3], "language": "English", "schedule": "On demand"})
    return rows

BOOKS = books()
BOOK_BY_SLUG = {str(book["slug"]): book for book in BOOKS}
BOOK_BY_SLUG["the-ambition-penalty"].update({
    "minutes": 20,
    "key_ideas": 5,
    "description": "How Corporate Culture Tells Women to Step Up—and Then Pushes Them Down",
})

def key_ideas_for(book: dict[str, object]) -> list[str]:
    """Return the short, source-aligned idea map shown on a Blink detail page."""
    if book["slug"] == "atomic-habits":
        return [
            "Build identity-based habits",
            "Make the cue obvious",
            "Make the routine attractive",
            "Make the action easy",
            "Make the reward satisfying",
            "Use habit stacking to create a reliable cue",
            "Review and reset when a routine breaks",
        ]
    return [
        f"Notice the central idea in {book['title']}",
        "Turn one insight into a small repeatable action",
        "Use a clear cue to make the action easier to remember",
        "Review the result and adjust the routine",
        "Return to the Blink when you need a quick refresher",
    ][: int(book.get("key_ideas", 5))]

def order_for(request: Request, order_id: str | None = None) -> sqlite3.Row | None:
    if not owner(request):
        return None
    with db() as conn:
        if order_id:
            return conn.execute(
                "SELECT order_id,plan,amount_minor,currency,status,scenario,flow_id,attempt_id,created_at FROM blinkist_orders WHERE owner=? AND order_id=?",
                (owner(request), order_id),
            ).fetchone()
        return conn.execute(
            "SELECT order_id,plan,amount_minor,currency,status,scenario,flow_id,attempt_id,created_at FROM blinkist_orders WHERE owner=? ORDER BY created_at DESC LIMIT 1",
            (owner(request),),
        ).fetchone()

def db() -> sqlite3.Connection:
    global _DB_SCHEMA_READY
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    if not _DB_SCHEMA_READY:
        with _DB_SCHEMA_LOCK:
            if not _DB_SCHEMA_READY:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS blinkist_favorites (owner TEXT NOT NULL, slug TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')), PRIMARY KEY(owner, slug));
                CREATE TABLE IF NOT EXISTS blinkist_subscriptions (owner TEXT PRIMARY KEY, plan TEXT NOT NULL, status TEXT NOT NULL, payment_scenario TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')));
                CREATE TABLE IF NOT EXISTS blinkist_orders (order_id TEXT PRIMARY KEY, owner TEXT NOT NULL, plan TEXT NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL, scenario TEXT NOT NULL, flow_id TEXT NOT NULL, attempt_id TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')));
                CREATE TABLE IF NOT EXISTS blinkist_progress (owner TEXT NOT NULL, slug TEXT NOT NULL, mode TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')), PRIMARY KEY(owner, slug, mode));
                CREATE TABLE IF NOT EXISTS blinkist_assessments (owner TEXT NOT NULL, slug TEXT NOT NULL, score INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0, answers TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')), PRIMARY KEY(owner, slug));
                CREATE TABLE IF NOT EXISTS blinkist_history (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, slug TEXT NOT NULL, action TEXT NOT NULL, mode TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')));
                CREATE TABLE IF NOT EXISTS blinkist_spaces (owner TEXT NOT NULL, space TEXT NOT NULL, slug TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')), PRIMARY KEY(owner, space, slug));
                CREATE TABLE IF NOT EXISTS blinkist_highlights (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, slug TEXT NOT NULL, note TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')));
                CREATE TABLE IF NOT EXISTS blinkist_masterclass_rsvps (owner TEXT NOT NULL, session_id TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')), PRIMARY KEY(owner, session_id));
                CREATE TABLE IF NOT EXISTS blinkist_preferences (owner TEXT PRIMARY KEY, language TEXT NOT NULL DEFAULT 'English', email_all INTEGER NOT NULL DEFAULT 1, daily_pick INTEGER NOT NULL DEFAULT 1, weekly_summary INTEGER NOT NULL DEFAULT 1, top_charts INTEGER NOT NULL DEFAULT 1, insights INTEGER NOT NULL DEFAULT 1, product_news INTEGER NOT NULL DEFAULT 1, surveys INTEGER NOT NULL DEFAULT 1, offers INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS blinkist_connection_checks (owner TEXT PRIMARY KEY, report TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')));
                """)
                conn.commit()
                _DB_SCHEMA_READY = True
    return conn

def current_session(request: Request) -> tuple[str, dict]:
    token = getattr(request.state, "session_token", None) or request.cookies.get(session_cookie_name(request))
    return AUTH.ensure_session(token)

def session_cookie_name(request: Request) -> str:
    return LOCAL_SESSION_COOKIE if is_loopback(request) and LOCAL_HTTP_COOKIE_OVERRIDE else SESSION_COOKIE

def account(request: Request) -> dict | None:
    return current_session(request)[1].get("account")

def owner(request: Request) -> str | None:
    item = account(request)
    return f"account:{item['account_id']}" if item else None

def subscription_for(request: Request) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute("SELECT plan,status,payment_scenario FROM blinkist_subscriptions WHERE owner=?", (owner(request) or "",)).fetchone()

EMAIL_PREFERENCES = [
    ("daily_pick", "Daily Pick", "Daily", "Get the free title of the day via email"),
    ("weekly_summary", "The Summary", "Weekly", "Find out which free titles are coming up in the next week"),
    ("top_charts", "Top Charts", "Monthly", "Discover the most popular titles in the Blinkist app"),
    ("insights", "Your Blinkist", "", "Insights on how you use Blinkist, product news, and surveys to improve your Blinkist experience"),
    ("product_news", "Product News", "Occasionally", "Be the first to discover the latest product updates and new features"),
    ("surveys", "Surveys", "Occasionally", "Get involved in Blinkist's journey and help us improve the product for you"),
    ("offers", "Offers", "Occasionally", "Receive our latest special offers and discounts"),
]

def preferences_for(request: Request) -> sqlite3.Row | None:
    if not owner(request):
        return None
    with db() as conn:
        row = conn.execute("SELECT * FROM blinkist_preferences WHERE owner=?", (owner(request),)).fetchone()
        if row is None:
            conn.execute("INSERT OR IGNORE INTO blinkist_preferences(owner) VALUES (?)", (owner(request),))
            conn.commit()
            row = conn.execute("SELECT * FROM blinkist_preferences WHERE owner=?", (owner(request),)).fetchone()
        return row

def settings_tabs(active: str) -> str:
    tabs = [("Account", "/settings"), ("Content", "/settings/content"), ("Email Preferences", "/settings/email_optins"), ("Connected Services", "/settings/external_services")]
    return "<nav class='settings-tabs' aria-label='Settings'>{}</nav>".format("".join(f"<a class='{'active' if label == active else ''}' href='{href}'>{label}</a>" for label, href in tabs))

def record_history(request: Request, slug: str, action: str, mode: str = "") -> None:
    if not owner(request):
        return
    with db() as conn:
        conn.execute("INSERT INTO blinkist_history(owner,slug,action,mode) VALUES (?,?,?,?)", (owner(request), slug, action, mode))
        conn.commit()

def progress_for(request: Request, slug: str, mode: str) -> sqlite3.Row | None:
    if not owner(request):
        return None
    with db() as conn:
        return conn.execute("SELECT position,completed,updated_at FROM blinkist_progress WHERE owner=? AND slug=? AND mode=?", (owner(request), slug, mode)).fetchone()

def save_progress(request: Request, slug: str, mode: str, position: int, completed: bool = False) -> None:
    if not owner(request):
        return
    with db() as conn:
        conn.execute("INSERT INTO blinkist_progress(owner,slug,mode,position,completed,updated_at) VALUES (?,?,?,?,?,strftime('%s','now')) ON CONFLICT(owner,slug,mode) DO UPDATE SET position=excluded.position,completed=excluded.completed,updated_at=excluded.updated_at", (owner(request), slug, mode, max(0, min(100, position)), int(completed)))
        conn.commit()

def safe_next(value: str | None) -> str:
    candidate = (value or "").strip()
    decoded = unquote(candidate)
    parsed = urlsplit(decoded)
    if (
        candidate.startswith("/")
        and decoded.startswith("/")
        and not candidate.startswith("//")
        and not decoded.startswith("//")
        and "\\" not in candidate
        and "\\" not in decoded
        and "\x00" not in decoded
        and not parsed.netloc
        and not parsed.scheme
    ):
        return candidate
    return "/en/app/for-you"

def is_loopback(request: Request) -> bool:
    host = (request.client.host if request.client else "")
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}

def set_session_cookie(response, request: Request, token: str) -> None:
    secure = COOKIE_SECURE and not (LOCAL_HTTP_COOKIE_OVERRIDE and is_loopback(request))
    response.set_cookie(session_cookie_name(request), token, httponly=True, samesite="lax", secure=secure, path="/")

def shell(title: str, body: str, request: Request, *, active: str = "For You") -> str:
    path = request.url.path
    if active == "For You":
        for prefix, label in (("/settings", "Settings"), ("/en/nc/settings", "Settings"), ("/app/progress", "Settings"), ("/app/history", "Settings"), ("/help", "Help & Support"), ("/app/check", "Help & Support"), ("/app/daily", "Today's Free Blink"), ("/app/explore", "Explore"), ("/app/library", "My Library"), ("/app/spaces", "Spaces"), ("/app/highlights", "Highlights"), ("/app/infographics", "Infographics"), ("/app/masterclasses", "Masterclasses")):
            if path.startswith(prefix):
                active = label
                break
    nav = [("For You", "/en/app/for-you", "⌂"), ("Today's Free Blink", "/app/daily", "♧"), ("Explore", "/app/explore", "⌕"), ("My Library", "/app/library", "♧"), ("Spaces", "/app/spaces", "▦"), ("Highlights", "/app/highlights", "◇"), ("Infographics", "/app/infographics", "▣"), ("Masterclasses", "/app/masterclasses", "◉")]
    links = "".join(f"<a class='nav-item {'active' if label == active else ''}' href='{href}'><span class='nav-icon' aria-hidden='true'>{icon}</span>{esc(label)}</a>" for label, href, icon in nav)
    settings_class = "active" if active == "Settings" else ""
    help_class = "active" if active == "Help & Support" else ""
    user = account(request)
    user_html = "" if user else "<a class='text-link' href='/login'>Log in</a><a class='button small' href='/register'>Get started</a>"
    side_auth = "<form method='post' action='/logout'><button class='nav-item text-link' type='submit'><span class='nav-icon' aria-hidden='true'>⇥</span>Log out</button></form>" if user else ""
    account_slot = f"<div class='account-actions'>{user_html}</div>" if user_html else ""
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)}</title><link rel='stylesheet' href='/static/site.css'><script src='/static/site.js' defer></script></head><body><aside class='sidebar'><a class='brand' href='/en/app/for-you'><span class='brand-mark'>b</span><span>Blinkist</span></a><nav>{links}</nav><div class='side-bottom'><a class='nav-item {settings_class}' href='/settings'><span class='nav-icon' aria-hidden='true'>⚙</span>Settings</a><a class='nav-item {help_class}' href='/help'><span class='nav-icon' aria-hidden='true'>?</span>Help &amp; Support</a>{side_auth}</div></aside><main class='app-main'><header class='topbar'><a class='mobile-brand' href='/en/app/for-you'>Blinkist</a><form class='search' action='/search' method='get'><span class='search-icon' aria-hidden='true'>⌕</span><input name='q' placeholder='Blinks, Guides, Shortcasts or Collections' autocomplete='off'><button class='search-submit' type='submit' aria-label='Search'>⌕</button></form>{account_slot}</header>{body}</main></body></html>"

def card(book: dict[str, object], *, favorite: bool = False) -> str:
    return f"<article class='book-card'><a href='/app/books/{esc(book['slug'])}' class='cover' style='background:{esc(book['color'])}'><span>{esc(str(book['title']).split()[0])}</span></a><div class='book-meta'><a class='book-title' href='/app/books/{esc(book['slug'])}'>{esc(book['title'])}</a><div class='book-author'>{esc(book['author'])}</div><div class='book-foot'><span>{esc(book['category'])}</span><span>{esc(book['minutes'])} min</span>{'<span class="heart filled">♥</span>' if favorite else ''}</div></div></article>"

def page_for_you(request: Request, *, active: str = "For You") -> HTMLResponse:
    with db() as conn:
        favs = {row["slug"] for row in conn.execute("SELECT slug FROM blinkist_favorites WHERE owner=?", (owner(request) or "",))}
    content = "".join(card(book, favorite=str(book["slug"]) in favs) for book in BOOKS[:12])
    masterclass_previews = "".join(f"<div class='masterclass'><div class='mastercover' style='background:{esc(session['color'])}'>{esc(session['title'].split(':')[0])}<small>{esc(':'.join(session['title'].split(':')[1:]).strip())}</small></div><div><strong>{esc(session['date'])}</strong><h2><a href='/app/masterclasses/{esc(session['id'])}'>{esc(session['title'])}</a></h2><p>{esc(session['host'])}</p><p class='muted'>{esc(session['description'])}</p><span class='meta'>Masterclass · Live · {esc(session['duration'])}</span></div></div>" for session in MASTERCLASSES)
    body = f"<section class='content'><section class='source-section'><div class='section-title'><span></span><div><h1>Masterclasses</h1><p>Interactive, expert-led live sessions</p></div><a href='/app/masterclasses'>See all <b>→</b></a></div><div class='masterclass-carousel-wrap'><button class='carousel-arrow prev' type='button' aria-label='Previous masterclass'>‹</button><div class='masterclass-carousel'>{masterclass_previews}</div><button class='carousel-arrow next' type='button' aria-label='Next masterclass'>›</button></div></section><section class='source-section selected-panel'><div class='section-title'><span></span><div><h1>Selected just for you</h1></div></div><div class='feature-banner'><span>Cliffs, Fog, Fire and the<br>Self-Knowledge Imperative</span><div class='feature-book'>What to Make<br>of a Life</div><div><h2>What to Make of a Life</h2><p>Jim Collins</p><span class='meta'>▶ &nbsp;19 min</span></div></div></section><section class='source-section'><div class='section-title'><span></span><div><h1>Recommended for you</h1><p>Browse ideas selected for your interests</p></div><a href='/app/explore'>See all <b>→</b></a></div><div class='book-grid'>{content}</div></section></section>"
    return HTMLResponse(shell("For You | Blinkist", body, request, active=active))

@APP.middleware("http")
async def session_middleware(request: Request, call_next):
    cookie_name = session_cookie_name(request)
    token, _ = AUTH.ensure_session(request.cookies.get(cookie_name))
    request.state.session_token = token
    response = await call_next(request)
    supplied = request.cookies.get(cookie_name)
    if token != supplied and "set-cookie" not in response.headers:
        secure = COOKIE_SECURE and not (LOCAL_HTTP_COOKIE_OVERRIDE and is_loopback(request))
        response.set_cookie(cookie_name, token, httponly=True, samesite="lax", secure=secure, path="/")
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; form-action 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@APP.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return page_for_you(request)

@APP.get("/en/app/for-you", response_class=HTMLResponse)
async def for_you(request: Request):
    return page_for_you(request)

@APP.get("/app/explore", response_class=HTMLResponse)
async def explore(request: Request, category: str | None = None):
    query = request.query_params
    level = query.get("level", "")
    language = query.get("language", "")
    schedule = query.get("schedule", "")
    max_minutes = int(query["max_minutes"]) if query.get("max_minutes", "").isdigit() else 0
    min_rating = float(query["min_rating"]) if re.fullmatch(r"[0-9]+(?:\.[0-9])?", query.get("min_rating", "")) else 0
    selected = [book for book in BOOKS if (
        (not category or str(book["category"]).casefold() == category.casefold())
        and (not level or str(book.get("level", "")).casefold() == level.casefold())
        and (not language or str(book.get("language", "")).casefold() == language.casefold())
        and (not schedule or str(book.get("schedule", "")).casefold() == schedule.casefold())
        and (not max_minutes or int(book["minutes"]) <= max_minutes)
        and (not min_rating or float(book["rating"]) >= min_rating)
    )]
    cards = "".join(card(book) for book in selected)
    params = "&".join(f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in query.multi_items() if k != "category")
    def filter_link(label: str) -> str:
        extra = f"&{params}" if params else ""
        selected_class = "selected" if category and category.casefold() == label.casefold() else ""
        return f"<a class='filter {selected_class}' href='/app/explore?category={quote_plus(label)}{extra}'>{esc(label)}</a>"
    controls = "".join(filter_link(x) for x in ["Productivity", "Mind", "Career", "Wellbeing", "Leadership"])
    def options(values: tuple[object, ...], selected: object) -> str:
        return "".join(f"<option value='{esc(value)}' {'selected' if str(selected) == str(value) else ''}>{esc(label or value)}</option>" for value, label in ((value, str(value)) for value in values))
    level_options = options(("Beginner", "Intermediate", "Advanced"), level)
    duration_options = options((15, 25, 35), max_minutes)
    rating_options = options((4.0, 4.5), min_rating)
    level_options = "<option value=''>All levels</option>" + level_options
    duration_options = "<option value=''>Any length</option>" + duration_options.replace("</option>", " min</option>")
    rating_options = "<option value=''>Any rating</option>" + rating_options.replace("</option>", "+ stars</option>")
    language_options = f"<option value=''>All languages</option><option value='English' {'selected' if language == 'English' else ''}>English</option>"
    schedule_options = f"<option value=''>Any schedule</option><option value='On demand' {'selected' if schedule == 'On demand' else ''}>On demand</option>"
    results = f'<div class="book-grid">{cards}</div>' if cards else '<div class="empty"><h2>No titles match these filters</h2><p>Try a broader topic, duration, or rating.</p><a class="button" href="/app/explore">Clear filters</a></div>'
    body = f"<section class='content'><div class='eyebrow'>EXPLORE</div><h1>Find your next great idea</h1><p class='lede'>Browse 200+ concise book summaries, audio guides, and collections.</p><div class='filter-row'>{controls}</div><form class='advanced-filters' method='get' action='/app/explore'><input type='hidden' name='category' value='{esc(category or '')}'><label>Level<select name='level'>{level_options}</select></label><label>Duration<select name='max_minutes'>{duration_options}</select></label><label>Rating<select name='min_rating'>{rating_options}</select></label><label>Language<select name='language'>{language_options}</select></label><label>Schedule<select name='schedule'>{schedule_options}</select></label><button class='button secondary' type='submit'>Apply filters</button></form><div class='section-head'><h2>{esc(category or 'All titles')}</h2><span class='result-count'>{len(selected)} titles</span></div>{results}</section>"
    return HTMLResponse(shell("Explore | Blinkist", body, request, active="Explore"))

@APP.get("/en/app/explore", response_class=HTMLResponse)
async def explore_localized(request: Request, category: str | None = None):
    return await explore(request, category)

@APP.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = ""):
    query = q.strip().casefold()
    found = [book for book in BOOKS if query in str(book["title"]).casefold() or query in str(book["author"]).casefold()] if query else []
    body = f"<section class='content'><div class='eyebrow'>SEARCH</div><h1>Search results</h1><p class='lede'>{len(found)} results for <strong>{esc(q or 'all titles')}</strong></p>{('<div class=\'book-grid\'>'+''.join(card(book) for book in found)+'</div>') if found else '<div class="empty"><div class="empty-icon">⌕</div><h2>No results yet</h2><p>Try a different title, author, or collection.</p><a class="button" href="/app/explore">Explore all titles</a></div>'}</section>"
    return HTMLResponse(shell("Search | Blinkist", body, request, active="Explore"))

@APP.get("/app/books/{slug}", response_class=HTMLResponse)
async def detail(request: Request, slug: str):
    slug = "atomic-habits" if slug == "atomic-habits-en" else slug
    book = BOOK_BY_SLUG.get(slug)
    if book is None:
        return HTMLResponse(shell("Not found | Blinkist", "<section class='content'><div class='empty'><h1>We couldn't find that Blink</h1><a class='button' href='/app/explore'>Back to Explore</a></div></section>", request), status_code=404)
    is_fav = False
    if owner(request):
        with db() as conn: is_fav = conn.execute("SELECT 1 FROM blinkist_favorites WHERE owner=? AND slug=?", (owner(request), slug)).fetchone() is not None
    fav_label = "In My Library" if is_fav else "Add to My Library"
    ratings = f"{int(book['ratings']):,}"
    premium = subscription_for(request)
    premium_active = bool(premium and premium["status"] == "active")
    action_html = f"<a class='button unlock' href='/app/books/{quote_plus(slug)}/read?mode=listen'>◉ Listen</a><a class='button secondary' href='/app/books/{quote_plus(slug)}/read?mode=text'>Read</a>" if premium_active else f"<a class='button unlock' href='/subscribe?next=/app/books/{quote_plus(slug)}'>▣ Unlock with Premium</a>"
    similar = [BOOK_BY_SLUG[s] for s in ("thinking-fast-and-slow", "the-7-habits-of-highly-effective-people", "deep-work", "essentialism") if s in BOOK_BY_SLUG and s != slug]
    similar_html = "".join(card(item) for item in similar)
    is_atomic = slug == "atomic-habits"
    topics = "<span>⌗ Personal Development</span><span>♧ Psychology</span>" if is_atomic else f"<span>⌗ {esc(book['category'])}</span>"
    author_copy = f"{esc(book['author'])} is the author of {esc(book['title'])}, sharing practical ideas and useful frameworks for everyday learning."
    art_title = "<br>".join(esc(str(book['title']).split()[:2]))
    ideas_html = "".join(f"<li><span>{index}</span><p>{esc(idea)}</p></li>" for index, idea in enumerate(key_ideas_for(book), 1))
    content_map = f"<div class='detail-summary'><div><strong>{esc(book['key_ideas'])} key ideas</strong><span>Short, practical takeaways</span></div><div><strong>{esc(book['minutes'])} minutes</strong><span>Text and audio formats</span></div><div><strong>{esc(book['level'])}</strong><span>{esc(book['schedule'])}</span></div></div>"
    body = f"""<section class='detail-page'>
      <section class='detail-hero'><div class='detail-hero-inner'><div class='detail-copy'>
        <div class='eyebrow'>{esc(book['category'])}</div><h1>{esc(book['title'])}</h1><h2>{esc(book['author'])}</h2>
        <p class='author'>Narrated by {esc(book['narrator'])}</p><p class='detail-desc'>{esc(book['description'])}</p>
        <div class='detail-facts'><span>☆ {esc(book['rating'])} ({esc(ratings)} ratings)</span><span>◷ {esc(book['minutes'])} mins</span><span>♧ {esc(book['key_ideas'])} Key ideas</span><span>♬ Audio &amp; text</span></div>
        <div class='detail-actions'>{action_html}</div><form method='post' action='/app/books/{esc(slug)}/favorite' class='save-form'><button class='save-link' type='submit'>♧ {fav_label}</button></form>
      </div><div class='detail-art' style='--cover:#274d7d'><div class='art-bubbles'></div><strong>{art_title}</strong><small>Practical ideas,<br>remarkable results</small></div></div></section>
      <section class='detail-content'><h2>What's it about?</h2><div class='topic-row'>{topics}</div><p>{esc(book['title'])} distills practical ideas, research, and real-world examples into a focused Blink you can apply today.</p>
        {content_map}<section class='idea-map'><div class='rail-title'><span></span><div><h2>Key ideas</h2><p>The short takeaways in this Blink</p></div></div><ol>{ideas_html}</ol></section>
        <h2>About the author</h2><p>{author_copy}</p><div class='detail-links'><button class='text-action' type='button' data-share='{esc(book['title'])}'>♧ Share with friends</button><a class='text-action' href='/help?topic=amazon'>🛒 Buy on Amazon</a></div>
        <section class='rail'><div class='rail-title'><span></span><div><h2>Similar Blinks</h2><p>Related Blinks you might enjoy</p></div></div><div class='book-grid'>{similar_html}</div></section>
        <section class='rail'><div class='rail-title'><span></span><div><h2>Trending</h2><p>What's popular right now</p></div></div><div class='book-grid'>{''.join(card(item) for item in BOOKS[4:8])}</div></section>
      </section></section>"""
    return HTMLResponse(shell(f"{book['title']} | Blinkist", body, request, active="Explore"))

@APP.post("/app/books/{slug}/favorite")
async def favorite(request: Request, slug: str):
    if not owner(request): return RedirectResponse(f"/login?next={quote_plus('/app/books/' + slug)}", status_code=303)
    if slug not in BOOK_BY_SLUG: return RedirectResponse("/app/explore", status_code=303)
    with db() as conn:
        existing = conn.execute("SELECT 1 FROM blinkist_favorites WHERE owner=? AND slug=?", (owner(request), slug)).fetchone()
        if existing: conn.execute("DELETE FROM blinkist_favorites WHERE owner=? AND slug=?", (owner(request), slug))
        else: conn.execute("INSERT INTO blinkist_favorites(owner,slug) VALUES (?,?)", (owner(request), slug))
        conn.commit()
    return RedirectResponse(f"/app/books/{quote_plus(slug)}", status_code=303)

def book_or_404(slug: str) -> dict[str, object] | None:
    return BOOK_BY_SLUG.get("atomic-habits" if slug == "atomic-habits-en" else slug)

def player_body(request: Request, book: dict[str, object], mode: str, *, preview: bool = False) -> str:
    slug = str(book["slug"])
    row = progress_for(request, slug, mode)
    position = int(row["position"]) if row else 0
    label = "Preview" if preview else ("Listen" if mode == "listen" else "Read")
    intro = "A short local preview" if preview else ("Audio summary" if mode == "listen" else "Key ideas in text")
    action = f"<form method='post' action='/app/books/{quote_plus(slug)}/progress' class='progress-form'><input type='hidden' name='mode' value='{esc(mode)}'><label for='progress'>Your progress <output>{position}%</output></label><input id='progress' name='position' type='range' min='0' max='100' value='{position}'><button class='button primary' type='submit'>Save progress</button></form>"
    return f"<section class='player-page content'><a class='back' href='/app/books/{quote_plus(slug)}'>← Back to {esc(book['title'])}</a><div class='player-header'><div class='mini-cover' style='background:{esc(book['color'])}'>{esc(str(book['title']).split()[0])}</div><div><div class='eyebrow'>{esc(label)}</div><h1>{esc(book['title'])}</h1><p>{esc(intro)} · {esc(book['minutes'])} minutes</p></div></div><div class='player-shell'><div class='player-control'><button class='play-button' type='button' data-player-toggle aria-label='Play {esc(label)}'>▶</button><div><strong data-player-state>Ready to start</strong><p>Offline playback is simulated locally; no source request is made.</p></div><span class='player-time'>00:00 / {int(book['minutes']):02d}:00</span></div><div class='player-copy'><h2>{'First ideas' if preview else 'Build better systems'}</h2><p>Small changes compound into remarkable results. Make the cue obvious, the routine attractive, and the reward satisfying.</p><p>Use this local player to exercise the same route, state, and progress transitions as the captured member experience.</p></div>{action}</div></section>"

@APP.get("/app/books/{slug}/preview", response_class=HTMLResponse)
async def preview(request: Request, slug: str):
    book = book_or_404(slug)
    if book is None:
        return HTMLResponse("Not found", status_code=404)
    record_history(request, str(book["slug"]), "preview", "preview")
    return HTMLResponse(shell(f"Preview {book['title']} | Blinkist", player_body(request, book, "preview", preview=True), request, active="Explore"))

@APP.get("/app/books/{slug}/read", response_class=HTMLResponse)
async def read_book(request: Request, slug: str, mode: str = "text"):
    book = book_or_404(slug)
    if book is None:
        return HTMLResponse("Not found", status_code=404)
    if mode not in {"text", "listen"}:
        mode = "text"
    if not owner(request):
        return RedirectResponse(f"/login?next={quote_plus('/app/books/' + str(book['slug']) + '/read?mode=' + mode)}", status_code=303)
    subscription = subscription_for(request)
    if not subscription or subscription["status"] != "active":
        return RedirectResponse(f"/subscribe?next={quote_plus('/app/books/' + str(book['slug']) + '/read?mode=' + mode)}", status_code=303)
    record_history(request, str(book["slug"]), "open", mode)
    return HTMLResponse(shell(f"{mode.title()} {book['title']} | Blinkist", player_body(request, book, mode), request, active="Explore"))

@APP.post("/app/books/{slug}/progress")
async def update_progress(request: Request, slug: str, mode: str = Form("text"), position: int = Form(0), completed: int = Form(0)):
    book = book_or_404(slug)
    if book is None:
        return RedirectResponse("/app/explore", status_code=303)
    if mode not in {"text", "listen", "preview"}:
        mode = "text"
    save_progress(request, str(book["slug"]), mode, position, bool(completed or position >= 100))
    record_history(request, str(book["slug"]), "complete" if completed or position >= 100 else "progress", mode)
    destination = "/app/books/" + quote_plus(str(book["slug"])) + ("/preview" if mode == "preview" else "/read?mode=" + mode)
    return RedirectResponse(destination, status_code=303)

@APP.get("/app/books/{slug}/listen", response_class=HTMLResponse)
async def listen_book(request: Request, slug: str):
    return await read_book(request, slug, mode="listen")

@APP.get("/app/books/{slug}/assessment", response_class=HTMLResponse)
async def assessment(request: Request, slug: str):
    book = book_or_404(slug)
    if book is None:
        return HTMLResponse("Not found", status_code=404)
    if not owner(request):
        return RedirectResponse(f"/login?next={quote_plus('/app/books/' + str(book['slug']) + '/assessment')}", status_code=303)
    with db() as conn:
        row = conn.execute("SELECT score,completed FROM blinkist_assessments WHERE owner=? AND slug=?", (owner(request), str(book["slug"]))).fetchone()
    result = f"<div class='assessment-result'><strong>{'Assessment complete' if row and row['completed'] else 'Assessment ready'}</strong><span>{row['score'] if row else 0}/3 correct</span></div>"
    first = f"What is the central idea in {esc(book['title'])}?"
    body = f"<section class='content assessment-page'><a class='back' href='/app/books/{quote_plus(str(book['slug']))}'>← Back to {esc(book['title'])}</a><div class='eyebrow'>CHECK YOUR UNDERSTANDING</div><h1>{esc(book['title'])} assessment</h1><p class='lede'>Answer three quick questions based on this Blink.</p>{result}<form method='post' class='assessment-form' action='/app/books/{quote_plus(str(book['slug']))}/assessment'><fieldset><legend>1. {first}</legend><label><input type='radio' name='q1' value='obvious' required> Apply one practical idea</label><label><input type='radio' name='q1' value='random'> Skip the ideas</label></fieldset><fieldset><legend>2. What makes a useful idea easier to use?</legend><label><input type='radio' name='q2' value='small' required> A small repeatable action</label><label><input type='radio' name='q2' value='instant'> Waiting for instant results</label></fieldset><fieldset><legend>3. How should you continue?</legend><label><input type='radio' name='q3' value='reward' required> Review and practice it</label><label><input type='radio' name='q3' value='skip'> Ignore the next step</label></fieldset><button class='button primary' type='submit'>Submit answers</button></form></section>"
    return HTMLResponse(shell("Assessment | Blinkist", body, request, active="Explore"))

@APP.post("/app/books/{slug}/assessment")
async def submit_assessment(request: Request, slug: str, q1: str = Form(""), q2: str = Form(""), q3: str = Form("")):
    book = book_or_404(slug)
    if book is None or not owner(request):
        return RedirectResponse("/login", status_code=303)
    answers = {"q1": q1, "q2": q2, "q3": q3}
    score = sum([q1 == "obvious", q2 == "small", q3 == "reward"])
    with db() as conn:
        conn.execute("INSERT INTO blinkist_assessments(owner,slug,score,completed,answers,updated_at) VALUES (?,?,?,?,?,strftime('%s','now')) ON CONFLICT(owner,slug) DO UPDATE SET score=excluded.score,completed=excluded.completed,answers=excluded.answers,updated_at=excluded.updated_at", (owner(request), str(book["slug"]), score, 1, str(answers)))
        conn.commit()
    record_history(request, str(book["slug"]), "assessment", "text")
    return RedirectResponse(f"/app/books/{quote_plus(str(book['slug']))}/assessment", status_code=303)

@APP.get("/app/library", response_class=HTMLResponse)
async def library(request: Request):
    with db() as conn:
        slugs = [row["slug"] for row in conn.execute("SELECT slug FROM blinkist_favorites WHERE owner=? ORDER BY created_at DESC", (owner(request) or "",))]
    selected = [BOOK_BY_SLUG[slug] for slug in slugs if slug in BOOK_BY_SLUG]
    cards = "".join(card(book, favorite=True) for book in selected)
    body = f"<section class='content'><div class='eyebrow'>MY LIBRARY</div><h1>Your saved Blinks</h1><p class='lede'>Keep the ideas you want to come back to close at hand.</p>{('<div class=\'book-grid\'>'+cards+'</div>') if cards else '<div class="empty"><div class="empty-icon">♡</div><h2>Your library is waiting</h2><p>Save a Blink from Explore and it will appear here.</p><a class="button" href="/app/explore">Explore titles</a></div>'}</section>"
    return HTMLResponse(shell("My Library | Blinkist", body, request, active="My Library"))

@APP.get("/en/app/library", response_class=HTMLResponse)
async def library_localized(request: Request):
    return await library(request)

@APP.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    body = "<section class='auth-page'><div class='auth-card'><div class='eyebrow'>GET STARTED</div><h1>Create your Blinkist account</h1><p>Start building a reading habit with concise ideas.</p><form method='post' action='/register'><label>Email<input type='email' name='email' required autocomplete='email'></label><label>Name<input name='display_name' required value='Reader'></label><label>Password<input type='password' name='password' required minlength='10' autocomplete='new-password'></label><label class='consent-row'><input type='checkbox' name='terms' required> I agree to the <a href='/help?topic=terms'>Terms of Service</a> and <a href='/help?topic=privacy'>Privacy Policy</a>.</label><button class='button primary full' type='submit'>Continue</button></form><p class='auth-switch'>A verification code will be available in the local outbox for this offline clone.</p><p class='auth-switch'>Already a member? <a href='/login'>Log in</a></p></div></section>"
    return HTMLResponse(shell("Create account | Blinkist", body, request))

@APP.post("/register")
async def register(request: Request, email: str = Form(...), display_name: str = Form(...), password: str = Form(...), terms: str = Form("")):
    token, _ = current_session(request)
    if terms != "on":
        return HTMLResponse(shell("Registration | Blinkist", "<section class='auth-page'><div class='auth-card'><h1>We couldn't create your account</h1><p class='error'>Please accept the Terms of Service and Privacy Policy.</p><a class='button' href='/register'>Try again</a></div></section>", request), status_code=422)
    try: result = AUTH.start_registration(token, email=email, display_name=display_name, password=password)
    except AuthError as exc: return HTMLResponse(shell("Registration | Blinkist", f"<section class='auth-page'><div class='auth-card'><h1>We couldn't create your account</h1><p class='error'>{esc(exc)}</p><a class='button' href='/register'>Try again</a></div></section>", request), status_code=422)
    return RedirectResponse(f"/verify?pending={quote_plus(result['pending_id'])}", status_code=303)

@APP.get("/verify", response_class=HTMLResponse)
async def verify_form(request: Request, pending: str = ""):
    body = f"<section class='auth-page'><div class='auth-card'><div class='eyebrow'>CHECK YOUR INBOX</div><h1>Verify your email</h1><p>In the offline clone, verification messages are retained in the local outbox for testing.</p><form method='post' action='/verify'><input type='hidden' name='pending' value='{esc(pending)}'><label>Verification code<input name='code' inputmode='numeric' required></label><button class='button primary full' type='submit'>Verify account</button></form></div></section>"
    return HTMLResponse(shell("Verify email | Blinkist", body, request))

@APP.post("/verify")
async def verify(request: Request, pending: str = Form(...), code: str = Form(...)):
    token, _ = current_session(request)
    try:
        AUTH.verify_registration_code(token, code)
        result = AUTH.complete_registration(token)
    except AuthError as exc: return HTMLResponse(shell("Verify email | Blinkist", f"<section class='auth-page'><div class='auth-card'><h1>Verification failed</h1><p class='error'>{esc(exc)}</p><a class='button' href='/verify?pending={quote_plus(pending)}'>Try again</a></div></section>", request), status_code=422)
    response = RedirectResponse("/en/app/for-you", status_code=303)
    set_session_cookie(response, request, result["session_token"])
    return response

@APP.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = ""):
    destination = safe_next(next)
    body = f"<section class='auth-page'><div class='auth-card'><div class='eyebrow'>WELCOME BACK</div><h1>Log in to Blinkist</h1><form method='post' action='/login'><input type='hidden' name='next' value='{esc(destination)}'><label>Email<input type='email' name='email' required autocomplete='email'></label><label>Password<input type='password' name='password' required autocomplete='current-password'></label><button class='button primary full' type='submit'>Log in</button></form><p class='auth-switch'><a href='/forgot-password'>Forgot password?</a></p><p class='auth-switch'>New here? <a href='/register'>Create an account</a></p></div></section>"
    return HTMLResponse(shell("Log in | Blinkist", body, request))

@APP.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("")):
    token, _ = current_session(request)
    try: result = AUTH.sign_in(token, email=email, password=password)
    except AuthRejected: return HTMLResponse(shell("Log in | Blinkist", "<section class='auth-page'><div class='auth-card'><h1>Log in to Blinkist</h1><p class='error'>Those details don't match an active account.</p><a class='button' href='/login'>Try again</a></div></section>", request), status_code=401)
    response = RedirectResponse(safe_next(next), status_code=303)
    set_session_cookie(response, request, result["session_token"])
    return response

@APP.post("/logout")
async def logout(request: Request):
    cookie_name = session_cookie_name(request)
    AUTH.sign_out(request.cookies.get(cookie_name))
    response = RedirectResponse("/en/app/for-you", status_code=303)
    response.delete_cookie(cookie_name, path="/")
    return response

@APP.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_form(request: Request):
    body = "<section class='auth-page'><div class='auth-card'><div class='eyebrow'>ACCOUNT RECOVERY</div><h1>Reset your password</h1><p>Enter your email and a local verification message will be available if an account matches.</p><form method='post' action='/forgot-password'><label>Email<input type='email' name='email' required autocomplete='email'></label><button class='button primary full' type='submit'>Send recovery message</button></form><p class='auth-switch'><a href='/login'>Back to log in</a></p></div></section>"
    return HTMLResponse(shell("Reset password | Blinkist", body, request))

@APP.post("/forgot-password")
async def forgot_password(request: Request, email: str = Form(...)):
    token, _ = current_session(request)
    try:
        AUTH.start_password_reset(token, email=email)
    except AuthError:
        pass
    return RedirectResponse("/reset-password", status_code=303)

@APP.get("/reset-password", response_class=HTMLResponse)
async def reset_password_form(request: Request):
    body = "<section class='auth-page'><div class='auth-card'><div class='eyebrow'>ACCOUNT RECOVERY</div><h1>Choose a new password</h1><p>Use the six-digit code from the local recovery outbox.</p><form method='post' action='/reset-password'><label>Verification code<input name='code' inputmode='numeric' required></label><label>New password<input type='password' name='new_password' minlength='8' required autocomplete='new-password'></label><button class='button primary full' type='submit'>Update password</button></form></div></section>"
    return HTMLResponse(shell("Choose new password | Blinkist", body, request))

@APP.post("/reset-password")
async def reset_password(request: Request, code: str = Form(...), new_password: str = Form(...)):
    token, _ = current_session(request)
    try:
        AUTH.verify_password_reset_code(token, code)
        new_token = AUTH.complete_password_reset(token, new_password=new_password)
    except AuthError as exc:
        return HTMLResponse(shell("Reset password | Blinkist", f"<section class='auth-page'><div class='auth-card'><h1>Recovery failed</h1><p class='error'>{esc(exc)}</p><a class='button' href='/reset-password'>Try again</a></div></section>", request), status_code=422)
    response = RedirectResponse("/en/app/for-you", status_code=303)
    set_session_cookie(response, request, new_token)
    return response

@APP.get("/subscribe", response_class=HTMLResponse)
async def subscribe_form(request: Request, next: str = "", scenario: str = ""):
    destination = safe_next(next)
    current = subscription_for(request)
    current_label = "Active Premium annual plan" if current and current["status"] == "active" else "Premium annual"
    if scenario in {"sandbox-approved", "sandbox-declined", "sandbox-retry"}:
        labels = {"sandbox-approved": "Simulated approval", "sandbox-declined": "Simulated decline", "sandbox-retry": "Simulated retry"}
        review = f"<div class='notice'><strong>Local sandbox review</strong><p>Scenario: {labels[scenario]}. No card details or external provider are used.</p><form method='post' action='/subscribe'><input type='hidden' name='scenario' value='{scenario}'><input type='hidden' name='next' value='{esc(destination)}'><button class='button primary' type='submit'>Confirm local sandbox</button></form></div>"
    else:
        review = f"<form method='get' action='/subscribe/review'><input type='hidden' name='next' value='{esc(destination)}'><button class='button primary' type='submit'>{'Continue to your Blink' if current and current['status'] == 'active' else 'Review annual plan'}</button></form>"
    body = f"<section class='content'><div class='eyebrow'>BLINKIST PREMIUM</div><h1>Make learning a daily habit</h1><p class='lede'>Unlock the full library with the Premium annual plan.</p><div class='plan-card'><div><h2>{current_label}</h2><p>Unlimited access to Blinks, audio, and collections.</p></div><strong>$99.99 / year</strong>{review}</div><p class='fine-print'>No real payment or external request is made in this offline clone.</p></section>"
    return HTMLResponse(shell("Premium | Blinkist", body, request))

@APP.get("/subscribe/review", response_class=HTMLResponse)
async def subscribe_review(request: Request, next: str = ""):
    destination = safe_next(next)
    body = f"<section class='content'><div class='eyebrow'>ORDER REVIEW</div><h1>Review your Premium annual plan</h1><p class='lede'>Choose a deterministic local outcome to exercise the checkout states.</p><form class='review-form' method='post' action='/subscribe'><input type='hidden' name='next' value='{esc(destination)}'><label><input type='radio' name='scenario' value='sandbox-approved' checked> Approve in local sandbox</label><label><input type='radio' name='scenario' value='sandbox-declined'> Decline in local sandbox</label><label><input type='radio' name='scenario' value='sandbox-retry'> Leave payment retryable</label><div class='plan-card'><strong>Premium annual</strong><span>$99.99 / year · USD</span><button class='button primary' type='submit'>Continue to local payment</button></div></form><p class='fine-print'>No real payment details are accepted or sent.</p></section>"
    return HTMLResponse(shell("Review Premium | Blinkist", body, request))

@APP.post("/subscribe")
async def subscribe(request: Request, scenario: str = Form("sandbox-approved"), next: str = Form("")):
    if not owner(request): return RedirectResponse("/login?next=" + quote_plus("/subscribe?next=" + safe_next(next)), status_code=303)
    existing = subscription_for(request)
    if existing and existing["status"] == "active":
        return RedirectResponse(safe_next(next), status_code=303)
    if scenario not in {"sandbox-approved", "sandbox-declined", "sandbox-retry"}: return JSONResponse({"error": "unknown local payment scenario"}, status_code=422)
    account_owner = owner(request)
    amount_minor = 9999
    fingerprint = hashlib.sha256(f"{account_owner}:premium-annual:USD:{amount_minor}".encode()).hexdigest()
    status = {"sandbox-approved": "active", "sandbox-declined": "declined", "sandbox-retry": "retryable"}[scenario]
    created_at = int(time.time())
    try:
        with BACKEND.lifecycle.connection(transaction=True) as conn:
            flow = BACKEND.payments.create_intent(owner=account_owner, amount_minor=amount_minor, currency="USD", fingerprint=fingerprint, idempotency_key="blinkist-premium-annual", connection=conn)
            attempt = BACKEND.payments.attempt(flow_id=flow["flow_id"], owner=account_owner, amount_minor=amount_minor, currency="USD", fingerprint=fingerprint, scenario_id=scenario, idempotency_key=f"blinkist-premium-annual-{scenario}", connection=conn)
            if attempt["status"] == "APPROVED":
                BACKEND.payments.consume_approval(conn, flow_id=flow["flow_id"], owner=account_owner, amount_minor=amount_minor, currency="USD", fingerprint=fingerprint)
            conn.execute("INSERT INTO blinkist_subscriptions(owner,plan,status,payment_scenario) VALUES (?,?,?,?) ON CONFLICT(owner) DO UPDATE SET plan=excluded.plan,status=excluded.status,payment_scenario=excluded.payment_scenario", (account_owner, "premium-annual", status, scenario))
            order_id = "BLK-" + hashlib.sha256(f"{account_owner}:{attempt['attempt_id']}".encode()).hexdigest()[:10].upper()
            conn.execute(
                "INSERT INTO blinkist_orders(order_id,owner,plan,amount_minor,currency,status,scenario,flow_id,attempt_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,scenario=excluded.scenario",
                (order_id, account_owner, "premium-annual", amount_minor, "USD", status, scenario, flow["flow_id"], attempt["attempt_id"], created_at),
            )
    except (PaymentError, PaymentRejected, sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
        return HTMLResponse(shell("Premium | Blinkist", f"<section class='content'><div class='empty'><h1>Payment could not be completed</h1><p class='error'>{esc(exc)}</p><a class='button' href='/subscribe'>Try again</a></div></section>", request), status_code=422)
    target = "/subscribe/success" if status == "active" else "/subscribe/result"
    return RedirectResponse(f"{target}?order_id={quote_plus(order_id)}&next={quote_plus(safe_next(next))}", status_code=303)

def order_page(request: Request, *, order_id: str, next: str, success: bool) -> HTMLResponse:
    order = order_for(request, order_id)
    if order is None:
        body = "<section class='content'><div class='empty'><h1>Order not found</h1><p>This local checkout result is no longer available for this account.</p><a class='button' href='/subscribe'>Return to Premium</a></div></section>"
        return HTMLResponse(shell("Order result | Blinkist", body, request), status_code=404)
    amount = f"${int(order['amount_minor']) / 100:.2f}"
    if success and order["status"] == "active":
        body = f"<section class='content order-result'><div class='eyebrow'>LOCAL SANDBOX</div><div class='success-mark'>✓</div><h1>Your Premium annual plan is active</h1><p class='lede'>The local checkout was approved. Your account can now open text and audio Blinks.</p><div class='receipt-card'><div><span>Confirmation</span><strong>{esc(order['order_id'])}</strong></div><div><span>Plan</span><strong>Premium annual</strong></div><div><span>Total</span><strong>{amount} {esc(order['currency'])}</strong></div><div><span>Status</span><strong>Approved in local sandbox</strong></div></div><p class='fine-print'>No card details, provider request, real email, or live payment was used.</p><div class='detail-actions'><a class='button primary' href='{esc(safe_next(next))}'>Continue to your Blink</a><a class='button secondary' href='/settings/payment-history'>View payment history</a></div></section>"
    else:
        label = {"declined": "Declined in local sandbox", "retryable": "Retryable in local sandbox"}.get(str(order['status']), str(order['status']))
        body = f"<section class='content order-result'><div class='eyebrow'>LOCAL SANDBOX</div><h1>We couldn't activate Premium yet</h1><p class='lede'>The selected local payment scenario was recorded without contacting a provider.</p><div class='receipt-card'><div><span>Attempt</span><strong>{esc(order['order_id'])}</strong></div><div><span>Plan</span><strong>Premium annual</strong></div><div><span>Result</span><strong>{esc(label)}</strong></div></div><div class='detail-actions'><a class='button primary' href='/subscribe/review?next={quote_plus(safe_next(next))}'>Choose another local outcome</a><a class='button secondary' href='/en/app/for-you'>Back to For You</a></div></section>"
    return HTMLResponse(shell("Order result | Blinkist", body, request))

@APP.get("/subscribe/success", response_class=HTMLResponse)
async def subscribe_success(request: Request, order_id: str = "", next: str = ""):
    return order_page(request, order_id=order_id, next=next, success=True)

@APP.get("/subscribe/result", response_class=HTMLResponse)
async def subscribe_result(request: Request, order_id: str = "", next: str = ""):
    return order_page(request, order_id=order_id, next=next, success=False)

@APP.get("/api/local/outbox")
async def local_outbox(request: Request, purpose: str = "registration"):
    if not is_loopback(request) or os.environ.get("WEBSITEBENCH_LOCAL_OUTBOX_DEBUG", "1") != "1":
        return JSONResponse({"error": "local outbox is loopback-only"}, status_code=404)
    token, _ = current_session(request)
    item = AUTH.local_mail_for_session(token, purpose=purpose)
    if item is None:
        return JSONResponse({"status": "empty", "purpose": purpose})
    return {"status": "LOCAL_ONLY", "purpose": purpose, "recipient": item["recipient"], "verification_code": item["verification_code"]}

@APP.get("/app/progress", response_class=HTMLResponse)
async def progress_page(request: Request):
    rows = []
    if owner(request):
        with db() as conn:
            rows = conn.execute("SELECT slug,mode,position,completed,updated_at FROM blinkist_progress WHERE owner=? ORDER BY updated_at DESC", (owner(request),)).fetchall()
    entries = "".join(f"<article class='progress-row'><div><a href='/app/books/{quote_plus(str(row['slug']))}'>{esc(BOOK_BY_SLUG.get(str(row['slug']), {'title': row['slug']})['title'])}</a><span>{esc(row['mode'].title())}</span></div><div class='progress-meter'><i style='width:{int(row['position'])}%'></i></div><strong>{int(row['position'])}%{' · Complete' if row['completed'] else ''}</strong></article>" for row in rows)
    body = f"<section class='content'><div class='eyebrow'>YOUR LEARNING</div><h1>Progress</h1><p class='lede'>Pick up where you left off across reading and listening.</p>{entries or '<div class="empty"><h2>No progress yet</h2><p>Open a preview or start a Blink to see your progress here.</p><a class="button" href="/app/explore">Explore titles</a></div>'}</section>"
    return HTMLResponse(shell("Progress | Blinkist", body, request, active="For You"))

@APP.get("/app/assessment")
async def assessment_entry(request: Request):
    return RedirectResponse("/app/books/atomic-habits/assessment", status_code=307)

@APP.get("/app/read")
async def read_entry(request: Request):
    return RedirectResponse("/app/books/atomic-habits/read?mode=text", status_code=307)

@APP.get("/app/listen")
async def listen_entry(request: Request):
    return RedirectResponse("/app/books/atomic-habits/read?mode=listen", status_code=307)

@APP.get("/app/history", response_class=HTMLResponse)
async def history_page(request: Request):
    rows = []
    if owner(request):
        with db() as conn:
            rows = conn.execute("SELECT id,slug,action,mode,created_at FROM blinkist_history WHERE owner=? ORDER BY created_at DESC LIMIT 40", (owner(request),)).fetchall()
    entries = "".join(f"<li><div><a href='/app/books/{quote_plus(str(row['slug']))}'>{esc(BOOK_BY_SLUG.get(str(row['slug']), {'title': row['slug']})['title'])}</a><span>{esc(row['action'].replace('_',' ').title())}{(' · ' + esc(row['mode'].title())) if row['mode'] else ''}</span></div><form method='post' action='/app/history/{int(row['id'])}/delete'><button class='text-action' type='submit'>Remove</button></form></li>" for row in rows)
    body = f"<section class='content'><div class='eyebrow'>ACTIVITY</div><h1>History &amp; management</h1><p class='lede'>Review previews, reading sessions, and assessment activity on this device.</p>{('<ul class="history-list">'+entries+'</ul>') if entries else '<div class="empty"><h2>Your activity will appear here</h2><p>Start a Blink to build a local history.</p></div>'}</section>"
    return HTMLResponse(shell("History | Blinkist", body, request, active="For You"))

@APP.post("/app/history/{history_id}/delete")
async def delete_history(request: Request, history_id: int):
    if owner(request):
        with db() as conn:
            conn.execute("DELETE FROM blinkist_history WHERE id=? AND owner=?", (history_id, owner(request)))
            conn.commit()
    return RedirectResponse("/app/history", status_code=303)

@APP.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    user = account(request)
    subscription = subscription_for(request)
    plan = "Premium annual · Active" if subscription and subscription["status"] == "active" else "Basic"
    identity = esc(user["display_name"]) + " · " + esc(user.get("email_normalized", "")) if user else "Not signed in"
    auth_action = "<form class='delete-account-form' method='post' action='/account/delete'><label>Type DELETE to confirm<input name='confirmation' required autocomplete='off' pattern='DELETE'></label><button class='text-action danger' type='submit'>Delete your account</button></form>" if user else "<a class='text-action' href='/login'>Log in</a>"
    email = esc(user.get("email_normalized", "")) if user else "Not signed in"
    body = f"<section class='content settings-page'><div class='eyebrow'>ACCOUNT</div><h1>Settings</h1>{settings_tabs('Account')}<div class='settings-list'><section><h2>Your Subscription plans</h2><h3>{plan}</h3><p>{'Unlimited access to Blinks, audio, and collections.' if subscription and subscription['status'] == 'active' else "You're on the free plan, with access to 1 pre-selected book a day."}</p><a class='text-action' href='/subscribe'>{'Manage plan' if subscription and subscription['status'] == 'active' else 'Upgrade now'}</a><p class='settings-links'><a class='text-action' href='/en/nc/settings/invoices'>Your invoices</a> · <a class='text-action' href='/settings/payment-history'>Your payment history</a></p></section><section><h2>Profile</h2><p>{identity}</p><a class='text-action' href='/settings/profile'>Edit profile</a></section><section><h2>Login variants</h2><p>Email {email}</p><p>Password ••••••••••</p><a class='text-action' href='/forgot-password'>Change Password</a></section><section><h2>Troubleshooting</h2><p>Audio or content not loading? Run a quick check of your connection, account, and audio server — you'll get a code our support team can look up.</p><a class='text-action' href='/app/check'>Run a connection check</a></section><section><h2>Privacy</h2><p>Change which cookies Blinkist may use. You can update your choice at any time.</p><button class='text-action' type='button' data-cookie-settings>Cookie settings</button></section><section><h2>Want to share Blinkist with your team?</h2><p>Did you know we also offer company subscriptions? Click below, or ask your Learning &amp; Development team to get in touch, to find out how you and your team can use Blinkist to level up — personally and professionally.</p><a class='text-action' href='/business/book-a-demo'>Learn more</a></section><section><h2>Delete your account</h2><p>Please note that deleting your account will delete all your content, your library and your completion history. Deleting your account will not automatically end a purchased subscription.</p>{auth_action}</section></div></section>"
    return HTMLResponse(shell("Settings | Blinkist", body, request, active="For You"))

@APP.get("/settings/profile", response_class=HTMLResponse)
async def settings_profile(request: Request):
    user = account(request)
    if not user:
        return RedirectResponse("/login?next=/settings/profile", status_code=303)
    body = f"<section class='content settings-page'><div class='eyebrow'>ACCOUNT</div><h1>Edit profile</h1>{settings_tabs('Account')}<form class='profile-form' method='post' action='/settings/profile'><label>Display name<input name='display_name' value='{esc(user['display_name'])}' minlength='2' maxlength='80' required></label><label>Email<input value='{esc(user['email_normalized'])}' disabled></label><button class='button primary' type='submit'>Save profile</button></form><a class='back' href='/settings'>← Back to Settings</a></section>"
    return HTMLResponse(shell("Edit profile | Blinkist", body, request, active="For You"))

@APP.post("/settings/profile")
async def save_settings_profile(request: Request, display_name: str = Form(...)):
    user = account(request)
    clean_name = display_name.strip()[:80]
    if not user:
        return RedirectResponse("/login?next=/settings/profile", status_code=303)
    if len(clean_name) < 2:
        return HTMLResponse(shell("Edit profile | Blinkist", "<section class='content'><div class='empty'><h1>Profile not saved</h1><p class='error'>Display name must be at least 2 characters.</p><a class='button' href='/settings/profile'>Try again</a></div></section>", request), status_code=422)
    with AUTH.connect() as conn:
        conn.execute("UPDATE local_auth_accounts SET display_name=? WHERE account_id=?", (clean_name, str(user["account_id"])))
        conn.commit()
    return RedirectResponse("/settings", status_code=303)

@APP.post("/account/delete")
async def delete_account(request: Request, confirmation: str = Form("")):
    user = account(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if confirmation != "DELETE":
        return HTMLResponse(shell("Settings | Blinkist", "<section class='content'><div class='empty'><h1>Confirmation required</h1><p class='error'>Type DELETE exactly to remove this local account.</p><a class='button' href='/settings'>Back to Settings</a></div></section>", request), status_code=422)
    account_id = str(user["account_id"])
    account_owner = f"account:{account_id}"
    with AUTH.connect() as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in ("blinkist_favorites", "blinkist_subscriptions", "blinkist_progress", "blinkist_assessments", "blinkist_history", "blinkist_spaces", "blinkist_highlights", "blinkist_masterclass_rsvps", "blinkist_preferences", "blinkist_connection_checks"):
                conn.execute(f"DELETE FROM {table} WHERE owner=?", (account_owner,))
            conn.execute("DELETE FROM local_auth_password_reset_flows WHERE account_id=?", (account_id,))
            conn.execute("DELETE FROM local_auth_sessions WHERE account_id=?", (account_id,))
            conn.execute("DELETE FROM local_auth_accounts WHERE account_id=?", (account_id,))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    response = RedirectResponse("/register", status_code=303)
    response.delete_cookie(session_cookie_name(request), path="/")
    return response

@APP.get("/en/nc/settings/account", response_class=HTMLResponse)
async def settings_account_alias(request: Request):
    return await settings_page(request)

@APP.get("/settings/content", response_class=HTMLResponse)
async def settings_content(request: Request):
    preferences = preferences_for(request)
    selected = preferences["language"] if preferences else "English"
    choices = "".join(f"<button class='choice-button {'selected' if selected == language else ''}' type='submit' name='language' value='{language}'>{language}</button>" for language in ("English", "German", "Spanish"))
    body = f"<section class='content settings-page'><div class='eyebrow'>ACCOUNT</div><h1>Settings</h1>{settings_tabs('Content')}<div class='settings-list'><section><h2>Language</h2><p>We'll show you content in the language you prefer.</p><form class='choice-row' method='post' action='/settings/content'>{choices}</form><div class='notice'>Current language: {esc(selected)}</div></section></div></section>"
    return HTMLResponse(shell("Content settings | Blinkist", body, request, active="For You"))

@APP.post("/settings/content")
async def save_settings_content(request: Request, language: str = Form("English")):
    if owner(request) and language in {"English", "German", "Spanish"}:
        with db() as conn:
            conn.execute("INSERT INTO blinkist_preferences(owner,language) VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET language=excluded.language", (owner(request), language))
            conn.commit()
    return RedirectResponse("/settings/content", status_code=303)

@APP.get("/settings/email_optins", response_class=HTMLResponse)
async def settings_email_optins(request: Request):
    preferences = preferences_for(request)
    values = preferences or {"email_all": 1, **{key: 1 for key, *_ in EMAIL_PREFERENCES}}
    def toggle(name: str, label: str) -> str:
        enabled = bool(values[name])
        return f"<form class='preference-row' method='post' action='/settings/email_optins'><div><strong>{esc(label)}</strong></div><button class='switch {'on' if enabled else ''}' type='submit' name='preference' value='{name}' role='switch' aria-checked='{str(enabled).lower()}'><span></span><span class='sr-only'>{'On' if enabled else 'Off'}</span></button></form>"
    rows = toggle("email_all", "Manage all emails") + "<p class='preference-note'>Turn all emails on or off. You'll still receive emails about your Blinkist account and subscription which we are legally obliged to send you.</p>"
    groups = {"Your Library": EMAIL_PREFERENCES[:3], "Your Blinkist": EMAIL_PREFERENCES[3:]}
    for heading, entries in groups.items():
        rows += f"<h2 class='preference-group'>{heading}</h2>" + "".join(f"<div class='preference-card'><div><strong>{esc(label)}</strong>{f'<span class=\"preference-cadence\">{esc(cadence)}</span>' if cadence else ''}<p>{esc(description)}</p></div>{toggle(key, label)}</div>" for key, label, cadence, description in entries)
    body = f"<section class='content settings-page'><div class='eyebrow'>ACCOUNT</div><h1>Settings</h1>{settings_tabs('Email Preferences')}<div class='settings-list'><section><h2>Manage your email preferences</h2>{rows}<p class='fine-print'>You can activate push notifications on your mobile phone in the app settings.</p></section></div></section>"
    return HTMLResponse(shell("Email preferences | Blinkist", body, request, active="For You"))

@APP.post("/settings/email_optins")
async def save_settings_email_optins(request: Request, preference: str = Form(...)):
    valid = {"email_all", *(key for key, *_ in EMAIL_PREFERENCES)}
    if owner(request) and preference in valid:
        with db() as conn:
            current = preferences_for(request)
            enabled = 0 if current and current[preference] else 1
            conn.execute(f"UPDATE blinkist_preferences SET {preference}=? WHERE owner=?", (enabled, owner(request)))
            if preference == "email_all":
                conn.execute("UPDATE blinkist_preferences SET daily_pick=?,weekly_summary=?,top_charts=?,insights=?,product_news=?,surveys=?,offers=? WHERE owner=?", (enabled, enabled, enabled, enabled, enabled, enabled, enabled, owner(request)))
            conn.commit()
    return RedirectResponse("/settings/email_optins", status_code=303)

@APP.get("/settings/external_services", response_class=HTMLResponse)
async def settings_external_services(request: Request):
    body = "<section class='content settings-page'><div class='eyebrow'>ACCOUNT</div><h1>Settings</h1>" + settings_tabs("Connected Services") + "<div class='settings-list'><section><h2>Kindle connect</h2><p>Send blinks right to your Kindle and read them whenever you want.</p><a class='button primary' href='/subscribe?next=/settings/external_services'>Upgrade now</a><p class='fine-print'>Kindle connection is available for Premium members in this offline clone.</p></section></div></section>"
    return HTMLResponse(shell("Connected services | Blinkist", body, request, active="For You"))

@APP.get("/settings/payment-history", response_class=HTMLResponse)
async def settings_payment_history(request: Request):
    subscription = subscription_for(request)
    history = f"<div class='payment-row'><strong>Premium annual</strong><span>{'Approved in local sandbox' if subscription and subscription['status'] == 'active' else 'No completed purchases'}</span></div>" if subscription and subscription["status"] == "active" else "<div class='empty compact'><h2>You have not purchased any products yet.</h2><a class='button' href='/subscribe'>Explore Premium</a></div>"
    body = f"<section class='content settings-page'><div class='eyebrow'>ACCOUNT</div><h1>Payment history</h1><div class='settings-list'><section>{history}</section></div></section>"
    return HTMLResponse(shell("Payment history | Blinkist", body, request, active="For You"))

@APP.get("/en/nc/settings/invoices", response_class=HTMLResponse)
async def invoices_page(request: Request):
    body = "<section class='content settings-page'><div class='eyebrow'>ACCOUNT</div><h1>Invoices</h1><div class='notice'>If you need an invoice for a local sandbox purchase, contact the local support fixture with your account email. No real invoice or payment provider is contacted.</div><p class='lede'>For subscriptions purchased in the app, invoices are provided by the relevant app store.</p><a class='button' href='/settings'>Back to Settings</a></section>"
    return HTMLResponse(shell("Invoices | Blinkist", body, request, active="For You"))

@APP.get("/app/check", response_class=HTMLResponse)
async def connection_check(request: Request, run: int = 0):
    checks = ["Blinkist website reachable", "Signed in to your account", "Audio server reachable", "Browser audio support", "Error reporting"]
    report = ""
    if run or owner(request):
        report = "All local checks passed"
        if owner(request):
            with db() as conn:
                conn.execute("INSERT INTO blinkist_connection_checks(owner,report,updated_at) VALUES (?,?,strftime('%s','now')) ON CONFLICT(owner) DO UPDATE SET report=excluded.report,updated_at=excluded.updated_at", (owner(request), report))
                conn.commit()
    rows = "".join(f"<li><span class='check-dot'>✓</span><span>{label}</span><strong>Passed</strong></li>" for label in checks)
    body = f"<section class='content check-page'><div class='eyebrow'>TROUBLESHOOTING</div><h1>Connection check</h1><p class='lede'>These checks help us find out why audio or content might not load on your network. We'll try to share the results with our support team automatically.</p><ul class='check-list'>{rows}</ul>{f'<div class=\"notice\">{esc(report)}</div>' if report else ''}<div class='detail-actions'><a class='button primary' href='/app/check?run=1'>Run again</a><button class='button' type='button' data-copy-report>Copy report</button><a class='text-action' href='mailto:support@blinkist.com?subject=Support%20code%3A%20LOCAL'>Contact support</a></div></section>"
    return HTMLResponse(shell("Connection check | Blinkist", body, request, active="For You"))

@APP.get("/help", response_class=HTMLResponse)
async def help_page(request: Request, topic: str = ""):
    focus = f"<div class='notice'>Help topic: {esc(topic)}</div>" if topic else ""
    body = f"<section class='content help-page'><div class='eyebrow'>SUPPORT</div><h1>Help &amp; Support</h1><p class='lede'>Find quick answers for your account and offline learning space.</p>{focus}<div class='help-grid'><details open><summary>How do I save a Blink?</summary><p>Open a title and select Add to My Library. Saved titles appear in My Library.</p></details><details><summary>How does Premium work here?</summary><p>Premium is simulated by the local sandbox. No payment provider or source site is contacted.</p></details><details><summary>Where did my reading progress go?</summary><p>Use Progress or History in Settings. Progress is isolated to this local account and SQLite runtime.</p></details><details><summary>Need to recover access?</summary><p><a href='/forgot-password'>Start password recovery</a> and use the local outbox code.</p></details></div><a class='button' href='/en/app/for-you'>Back to For You</a></section>"
    return HTMLResponse(shell("Help & Support | Blinkist", body, request, active="For You"))

MASTERCLASSES = [
    {"id": "ai-unlocked-how-to-future-proof-yourself", "title": "AI Unlocked: How to Future-Proof Yourself", "host": "Sebastian Kamilli", "date": "Tue, 25 Aug & 1 more date", "description": "Find out what AI really means for your career and leave with a concrete plan to stay ahead.", "duration": "60 min", "color": "#e8ddff"},
    {"id": "become-a-blinkist-power-user-live-guide", "title": "Become a Blinkist Power User: Live Guide", "host": "Chiara Chidini", "date": "Tue, 25 Aug & 3 more dates", "description": "Learn how to get the most out of Blinkist — from navigating the app to building a learning habit that actually sticks", "duration": "45 min", "color": "#d8f0e8"},
    {"id": "thrive-without-the-overdrive-sustainable-success-strategies", "title": "Thrive Without the Overdrive: Sustainable Success Strategies", "host": "Katharina Loth", "date": "Fri, 04 Sep", "description": "Uncover your hidden energy drains and master the balance between doing less and achieving more.", "duration": "60 min", "color": "#f4e6bd"},
    {"id": "work-smarter-not-harder-peak-productivity-tools", "title": "Work Smarter, Not Harder: Peak Productivity Tools", "host": "Sebastian Kamilli", "date": "Thu, 08 Oct & 1 more date", "description": "Reclaim your time with proven strategies used by the world's most productive people.", "duration": "60 min", "color": "#d9e6ff"},
    {"id": "the-innovation-edge-problem-solving-made-simple", "title": "The Innovation Edge: Problem-Solving Made Simple", "host": "Nicole Lenzen", "date": "Wed, 11 Nov", "description": "Build an innovation mindset that makes generating great ideas feel like second nature.", "duration": "60 min", "color": "#f6dccd"},
    {"id": "learn-like-a-pro-master-skills-faster", "title": "Learn Like a Pro: Master Skills Faster", "host": "Sebastian Kamilli", "date": "Wed, 18 Nov", "description": "Unlock the science of learning and pick up new skills faster than you thought possible.", "duration": "60 min", "color": "#e1f0df"},
    {"id": "build-your-own-second-brain-from-info-to-action", "title": "Build Your Own Second Brain: From Info to Action", "host": "Sebastian Kamilli", "date": "Thu, 26 Nov", "description": "Build a personal system that turns information overload into your competitive advantage.", "duration": "60 min", "color": "#ede4f6"},
]

MASTERCLASS_ALIASES = {
    "ai-unlocked": "ai-unlocked-how-to-future-proof-yourself",
    "blinkist-power-user": "become-a-blinkist-power-user-live-guide",
    "thrive-without-the-overdrive": "thrive-without-the-overdrive-sustainable-success-strategies",
    "work-smarter-not-harder": "work-smarter-not-harder-peak-productivity-tools",
    "the-innovation-edge": "the-innovation-edge-problem-solving-made-simple",
    "learn-like-a-pro": "learn-like-a-pro-master-skills-faster",
    "build-your-own-second-brain": "build-your-own-second-brain-from-info-to-action",
}

def canonical_masterclass_id(session_id: str) -> str:
    return MASTERCLASS_ALIASES.get(session_id, session_id)

def masterclass_card(session: dict[str, str]) -> str:
    return f"<article class='session-card'><div class='session-cover' style='background:{esc(session['color'])}'><span>LIVE</span><strong>{esc(session['title'].split(':')[0])}</strong></div><div><div class='eyebrow'>{esc(session['date'])}</div><h2><a href='/app/masterclasses/{esc(session['id'])}'>{esc(session['title'])}</a></h2><p>{esc(session['host'])}</p><p class='muted'>{esc(session['description'])}</p><span class='meta'>Masterclass · Live · {esc(session['duration'])}</span></div></article>"

@APP.get("/app/daily", response_class=HTMLResponse)
async def daily_page(request: Request):
    book = BOOK_BY_SLUG["the-ambition-penalty"]
    progress = progress_for(request, "the-ambition-penalty", "preview")
    percent = int(progress["position"]) if progress else 0
    body = f"<section class='content daily-page'><h1>Today’s Free Blink</h1><p class='lede'>Key ideas from a different title daily—free for 24h!</p><div class='daily-feature'><div class='daily-cover'><span class='daily-timer'>Free for 22hrs 34min 51sec</span><span class='daily-cover-title' aria-hidden='true'>{esc(book['title'])}</span></div><div><div class='eyebrow'>Better than a summary</div><h2>{esc(book['title'])}</h2><p class='daily-byline'>by <strong>{esc(book['author'])}</strong></p><p>{esc(book['description'])}</p><div class='daily-meta'><span>◷ &nbsp;{esc(book['minutes'])} mins</span><span>♧ &nbsp;{esc(book['key_ideas'])} key ideas</span></div><div class='detail-actions'><a class='button primary' href='/app/books/{esc(book['slug'])}/preview'>Start now</a></div><p class='fine-print'>Free—no sign up required</p></div></div><section class='daily-next'><h2>What's it about?</h2><div class='topic-row'><span>◉ &nbsp;Career &amp; Success</span><span>♧ &nbsp;Society &amp; Culture</span><span>▣ &nbsp;Corporate Culture</span></div><p>{esc(book['title'])} pulls back the curtain on why women’s drive to achieve more keeps getting punished rather than rewarded. It equips readers with the language and evidence to push back and shows what real change could look like.</p><a class='text-action' href='/app/explore'>Browse popular titles →</a></section></section>"
    return HTMLResponse(shell("Today's Free Blink | Blinkist", body, request, active="Today's Free Blink"))

@APP.get("/app/spaces", response_class=HTMLResponse)
async def spaces_page(request: Request, space: str = "My reading list"):
    space = (space.strip() or "My reading list")[:60]
    assigned = set()
    if owner(request):
        with db() as conn:
            assigned = {row["slug"] for row in conn.execute("SELECT slug FROM blinkist_spaces WHERE owner=? AND space=?", (owner(request), space))}
    choices = BOOKS[:10]
    rows = "".join(f"<article class='space-row'><a href='/app/books/{esc(book['slug'])}'>{esc(book['title'])}</a><span>{esc(book['author'])}</span>{('<strong>Saved</strong>' if str(book['slug']) in assigned else f'<form method="post" action="/app/spaces/add"><input type="hidden" name="space" value="{esc(space)}"><input type="hidden" name="slug" value="{esc(book["slug"])}"><button class="text-action" type="submit">Add to space</button></form>')}</article>" for book in choices)
    body = f"<section class='content spaces-page'><div class='eyebrow'>SPACES</div><h1>Organize ideas your way</h1><p class='lede'>Keep related Blinks together so you can return to a theme when you need it.</p><form class='space-switcher' method='get' action='/app/spaces'><label>Space name<input name='space' value='{esc(space)}' maxlength='60'></label><button class='button primary' type='submit'>Open space</button></form><div class='space-summary'><strong>{esc(space)}</strong><span>{len(assigned)} saved locally</span></div><div class='space-list'>{rows}</div></section>"
    return HTMLResponse(shell("Spaces | Blinkist", body, request, active="Spaces"))

@APP.post("/app/spaces/add")
async def add_to_space(request: Request, slug: str = Form(...), space: str = Form("My reading list")):
    if not owner(request):
        return RedirectResponse("/login?next=/app/spaces", status_code=303)
    normalized_space = (space.strip() or "My reading list")[:60]
    if slug in BOOK_BY_SLUG:
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO blinkist_spaces(owner,space,slug) VALUES (?,?,?)", (owner(request), normalized_space, slug))
            conn.commit()
        record_history(request, slug, "add_to_space", normalized_space)
    return RedirectResponse(f"/app/spaces?space={quote_plus(normalized_space)}", status_code=303)

@APP.get("/app/highlights", response_class=HTMLResponse)
async def highlights_page(request: Request):
    highlights = []
    if owner(request):
        with db() as conn:
            highlights = conn.execute("SELECT id,slug,note,created_at FROM blinkist_highlights WHERE owner=? ORDER BY created_at DESC", (owner(request),)).fetchall()
    entries = "".join(f"<article class='highlight-card'><blockquote>{esc(row['note'])}</blockquote><a href='/app/books/{quote_plus(str(row['slug']))}'>{esc(BOOK_BY_SLUG.get(str(row['slug']), {'title': row['slug']})['title'])}</a><form method='post' action='/app/highlights/{int(row['id'])}/delete'><button class='text-action' type='submit'>Remove</button></form></article>" for row in highlights)
    sample = "<article class='highlight-card sample'><blockquote>Small changes compound into remarkable results.</blockquote><span>Atomic Habits · Local starter highlight</span></article>" if not entries else ""
    body = f"<section class='content highlights-page'><div class='eyebrow'>HIGHLIGHTS</div><h1>Keep the ideas that stick</h1><p class='lede'>Save a short note while you read, then revisit it from one place.</p><form class='highlight-form' method='post' action='/app/highlights'><label>Book<select name='slug'>{''.join(f"<option value='{esc(book['slug'])}'>{esc(book['title'])}</option>" for book in BOOKS[:12])}</select></label><label>Your highlight<textarea name='note' required maxlength='280' placeholder='Write a note about this idea'></textarea></label><button class='button primary' type='submit'>Save highlight</button></form><div class='highlight-grid'>{entries or sample}</div></section>"
    return HTMLResponse(shell("Highlights | Blinkist", body, request, active="Highlights"))

@APP.post("/app/highlights")
async def add_highlight(request: Request, slug: str = Form(...), note: str = Form(...)):
    if not owner(request):
        return RedirectResponse("/login?next=/app/highlights", status_code=303)
    if slug in BOOK_BY_SLUG and note.strip():
        with db() as conn:
            conn.execute("INSERT INTO blinkist_highlights(owner,slug,note) VALUES (?,?,?)", (owner(request), slug, note.strip()[:280]))
            conn.commit()
        record_history(request, slug, "highlight", "text")
    return RedirectResponse("/app/highlights", status_code=303)

@APP.post("/app/highlights/{highlight_id}/delete")
async def delete_highlight(request: Request, highlight_id: int):
    if owner(request):
        with db() as conn:
            conn.execute("DELETE FROM blinkist_highlights WHERE id=? AND owner=?", (highlight_id, owner(request)))
            conn.commit()
    return RedirectResponse("/app/highlights", status_code=303)

@APP.get("/app/infographics", response_class=HTMLResponse)
async def infographics_page(request: Request, category: str = ""):
    categories = ["All", "Productivity", "Psychology", "Leadership", "Career"]
    selected = [book for book in BOOKS[:16] if not category or category.casefold() == "all" or str(book["category"]).casefold() == category.casefold()]
    filters = "".join(f"<a class='filter {'selected' if (category or 'All').casefold() == item.casefold() else ''}' href='/app/infographics?category={quote_plus(item)}'>{esc(item)}</a>" for item in categories)
    cards = "".join(f"<article class='info-card'><a href='/app/infographics/{esc(book['slug'])}' style='background:{esc(book['color'])}'><span>INFOGRAPHIC</span><strong>{esc(book['title'])}</strong><small>{esc(book['key_ideas'])} ideas · {esc(book['minutes'])} min</small></a><h2>{esc(book['title'])}</h2><p>{esc(book['category'])} · Visual summary</p></article>" for book in selected)
    body = f"<section class='content infographics-page'><div class='eyebrow'>INFOGRAPHICS</div><h1>See the big ideas at a glance</h1><p class='lede'>Visual summaries turn a Blink into a quick reference you can scan and share.</p><div class='filter-row'>{filters}</div><div class='info-grid'>{cards}</div></section>"
    return HTMLResponse(shell("Infographics | Blinkist", body, request, active="Infographics"))

@APP.get("/app/infographics/{slug}", response_class=HTMLResponse)
async def infographic_detail(request: Request, slug: str):
    book = book_or_404(slug)
    if book is None:
        return HTMLResponse("Not found", status_code=404)
    steps = ["Make the cue obvious", "Make the routine attractive", "Make the reward satisfying", "Repeat until it becomes automatic"]
    items = "".join(f"<li><span>{index}</span><strong>{esc(step)}</strong><p>Apply this idea to {esc(book['title'])} in a small, repeatable way.</p></li>" for index, step in enumerate(steps, 1))
    body = f"<section class='content infographic-detail'><a class='back' href='/app/infographics'>← Infographics</a><div class='eyebrow'>VISUAL SUMMARY</div><h1>{esc(book['title'])}</h1><p class='lede'>{esc(book['description'])}</p><ol class='infographic-steps'>{items}</ol><a class='button primary' href='/app/books/{esc(book['slug'])}'>Open full Blink</a></section>"
    return HTMLResponse(shell(f"Infographic: {book['title']} | Blinkist", body, request, active="Infographics"))

@APP.get("/app/masterclasses", response_class=HTMLResponse)
async def masterclasses_page(request: Request):
    sessions = "".join(masterclass_card(session) for session in MASTERCLASSES)
    body = f"<section class='content masterclasses-page'><div class='eyebrow'>MASTERCLASSES</div><h1>Masterclasses: turn insight into action, live</h1><p class='lede'>60-minute interactive live sessions, led by experts, designed to provide practical frameworks.</p><div class='masterclass-list'>{sessions}</div></section>"
    return HTMLResponse(shell("Masterclasses | Blinkist", body, request, active="Masterclasses"))

@APP.get("/app/masterclasses/{session_id}", response_class=HTMLResponse)
async def masterclass_detail(request: Request, session_id: str, registered: int = 0):
    canonical_id = canonical_masterclass_id(session_id)
    session = next((item for item in MASTERCLASSES if item["id"] == canonical_id), None)
    if session is None:
        return HTMLResponse("Not found", status_code=404)
    joined = False
    if owner(request):
        with db() as conn:
            joined = conn.execute("SELECT 1 FROM blinkist_masterclass_rsvps WHERE owner=? AND session_id=?", (owner(request), canonical_id)).fetchone() is not None
    message = "You're registered for this local session." if joined else "Reserve a place in this local session to keep it on your learning calendar."
    body = f"<section class='content masterclass-detail'><a class='back' href='/app/masterclasses'>← Masterclasses</a><div class='session-hero' style='background:{esc(session['color'])}'><span>LIVE MASTERCLASS</span><h1>{esc(session['title'])}</h1></div><div class='eyebrow'>{esc(session['date'])} · {esc(session['duration'])}</div><h2>{esc(session['host'])}</h2><p class='lede'>{esc(session['description'])}</p><div class='notice'>{esc(message)}</div><form method='post' action='/app/masterclasses/{esc(session['id'])}/register'><button class='button primary' type='submit'>{'Registered' if joined else 'Reserve a place'}</button></form></section>"
    return HTMLResponse(shell(f"{session['title']} | Blinkist", body, request, active="Masterclasses"))

@APP.post("/app/masterclasses/{session_id}/register")
async def register_masterclass(request: Request, session_id: str):
    if not owner(request):
        return RedirectResponse(f"/login?next={quote_plus('/app/masterclasses/' + session_id)}", status_code=303)
    canonical_id = canonical_masterclass_id(session_id)
    if any(item["id"] == canonical_id for item in MASTERCLASSES):
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO blinkist_masterclass_rsvps(owner,session_id) VALUES (?,?)", (owner(request), canonical_id))
            conn.commit()
    return RedirectResponse(f"/app/masterclasses/{quote_plus(canonical_id)}?registered=1", status_code=303)

@APP.get("/app/{section}", response_class=HTMLResponse)
async def auxiliary_section(request: Request, section: str):
    if section == "settings":
        return await settings_page(request)
    if section == "help":
        return await help_page(request)
    if section == "progress":
        return await progress_page(request)
    if section == "history":
        return await history_page(request)
    if section == "daily":
        return await daily_page(request)
    if section == "spaces":
        return await spaces_page(request)
    if section == "highlights":
        return await highlights_page(request)
    if section == "infographics":
        return await infographics_page(request)
    if section == "masterclasses":
        return await masterclasses_page(request)
    labels = {"daily": "Today's Free Blink", "spaces": "Spaces", "highlights": "Highlights", "infographics": "Infographics", "masterclasses": "Masterclasses", "settings": "Settings", "help": "Help & Support"}
    label = labels.get(section)
    if label is None:
        return HTMLResponse("Not found", status_code=404)
    return HTMLResponse("Not found", status_code=404)

@APP.get("/{section}", response_class=HTMLResponse)
async def root_auxiliary_section(request: Request, section: str):
    if section not in {"settings", "help"}:
        return HTMLResponse("Not found", status_code=404)
    return await auxiliary_section(request, section)

@APP.get("/api/status")
async def status(request: Request):
    with db() as conn:
        subscription = conn.execute("SELECT plan,status,payment_scenario FROM blinkist_subscriptions WHERE owner=?", (owner(request) or "",)).fetchone()
        count = conn.execute("SELECT COUNT(*) AS n FROM blinkist_favorites WHERE owner=?", (owner(request) or "",)).fetchone()["n"]
    latest_order = order_for(request)
    return {"site_id": SITE_ID, "authenticated": account(request) is not None, "favorite_count": count, "subscription": dict(subscription) if subscription else None, "latest_order": dict(latest_order) if latest_order else None, "catalog_count": len(BOOKS)}

@APP.get("/__websitebench/health")
async def websitebench_health():
    return {"status": "ok"}

@APP.get("/healthz")
async def healthz():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        APP,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "warning"),
    )
