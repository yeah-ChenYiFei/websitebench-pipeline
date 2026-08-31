from __future__ import annotations

import hashlib
import html
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.site_backend_integration import open_site_services
from backend.site_schema import reset_business
from websitebench.local_clone_auth import AuthError
from websitebench.site_backend.errors import PaymentError


ROOT = Path(__file__).resolve().parent
SITE_ID = "crunchyroll"
DISPLAY_NAME = "Crunchyroll"
BACKEND, AUTH = open_site_services()
DB = BACKEND.lifecycle.database_path
SESSION_COOKIE = BACKEND.session_cookie["name"]
LOCAL_SESSION_COOKIE = f"websitebench-{SITE_ID}-session"
LOCAL_HTTP_COOKIE = os.environ.get("WEBSITEBENCH_LOCAL_HTTP_COOKIE", "1") == "1"
app = FastAPI(
    title=f"{DISPLAY_NAME} offline clone",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

DEMO_EMAIL = "viewer@example.test"
DEMO_PASSWORD = "DemoPass123!"
DEMO_SUBJECT_ID = "crunchyroll-demo-viewer"
AUTH.seed_account(
    subject_id=DEMO_SUBJECT_ID,
    email=DEMO_EMAIL,
    display_name="Anime Fan",
    password=DEMO_PASSWORD,
)

CATALOG = [
    {
        "id": "GRMG8ZQZR",
        "slug": "one-piece",
        "title": "One Piece",
        "genre": "Adventure",
        "maturity": "14+",
        "rating": "4.9",
        "meta": "Sub | Dub",
        "c1": "#20466b",
        "c2": "#e85531",
        "synopsis": "Embark on a voyage with a spirited pirate crew searching for the legendary treasure known as the One Piece.",
        "cast": "Mayumi Tanaka, Kazuya Nakai, Akemi Okamura",
        "audio": "Japanese, English",
        "subtitles": "English (US), Español",
        "related": ["jujutsu-kaisen", "spy-x-family", "attack-on-titan"],
    },
    {
        "id": "GRDV0019R",
        "slug": "jujutsu-kaisen",
        "title": "JUJUTSU KAISEN",
        "genre": "Action",
        "maturity": "16+",
        "rating": "4.8",
        "meta": "Sub | Dub",
        "c1": "#1a263d",
        "c2": "#6550a8",
        "synopsis": "A student enters a hidden world of curses and sorcerers after swallowing a powerful cursed object.",
        "cast": "Junya Enoki, Yuichi Nakamura",
        "audio": "Japanese, English",
        "subtitles": "English (US), Deutsch",
        "related": ["one-piece", "attack-on-titan", "chainsaw-man"],
    },
    {
        "id": "G4PH0WXVJ",
        "slug": "spy-x-family",
        "title": "SPY x FAMILY",
        "genre": "Comedy",
        "maturity": "14+",
        "rating": "4.8",
        "meta": "Sub | Dub",
        "c1": "#27675f",
        "c2": "#e8b1b8",
        "synopsis": "A spy, an assassin, and a telepath form a pretend family while keeping their secret lives hidden.",
        "cast": "Takuya Eguchi, Atsumi Tanezaki",
        "audio": "Japanese, English",
        "subtitles": "English (US), Français",
        "related": ["one-piece", "frieren-beyond-journeys-end", "my-hero-academia"],
    },
    {
        "id": "GR751KNZY",
        "slug": "attack-on-titan",
        "title": "Attack on Titan",
        "genre": "Drama",
        "maturity": "18+",
        "rating": "4.9",
        "meta": "Sub | Dub",
        "c1": "#31261f",
        "c2": "#8f392a",
        "synopsis": "Humanity fights for survival behind enormous walls as a young soldier uncovers the truth about the Titans.",
        "cast": "Yuki Kaji, Yui Ishikawa",
        "audio": "Japanese, English",
        "subtitles": "English (US), Español",
        "related": ["jujutsu-kaisen", "chainsaw-man", "one-piece"],
    },
    {
        "id": "GG5H5XQX4",
        "slug": "frieren-beyond-journeys-end",
        "title": "Frieren: Beyond Journey's End",
        "genre": "Fantasy",
        "maturity": "14+",
        "rating": "4.9",
        "meta": "Sub | Dub",
        "c1": "#31495d",
        "c2": "#b7d3d4",
        "synopsis": "An elven mage retraces a heroic journey to understand the fleeting lives of her former companions.",
        "cast": "Atsumi Tanezaki, Kana Ichinose",
        "audio": "Japanese, English",
        "subtitles": "English (US)",
        "related": ["spy-x-family", "one-piece", "solo-leveling"],
    },
    {
        "id": "GDKHZEJ0K",
        "slug": "solo-leveling",
        "title": "Solo Leveling",
        "genre": "Action",
        "maturity": "16+",
        "rating": "4.8",
        "meta": "Sub | Dub",
        "c1": "#17213a",
        "c2": "#7751bd",
        "synopsis": "The weakest hunter gains a mysterious ability to level up and takes on ever more dangerous dungeons.",
        "cast": "Taito Ban, Genta Nakamura",
        "audio": "Japanese, English",
        "subtitles": "English (US)",
        "related": ["jujutsu-kaisen", "chainsaw-man", "attack-on-titan"],
    },
    {
        "id": "G6NQ5DWZ6",
        "slug": "my-hero-academia",
        "title": "My Hero Academia",
        "genre": "Action",
        "maturity": "14+",
        "rating": "4.7",
        "meta": "Sub | Dub",
        "c1": "#1e593c",
        "c2": "#f4bd35",
        "synopsis": "A determined student without powers inherits a heroic gift and enrolls at the world's leading hero academy.",
        "cast": "Daiki Yamashita, Nobuhiko Okamoto",
        "audio": "Japanese, English",
        "subtitles": "English (US)",
        "related": ["spy-x-family", "jujutsu-kaisen", "one-piece"],
    },
    {
        "id": "GVDHX8QNW",
        "slug": "chainsaw-man",
        "title": "Chainsaw Man",
        "genre": "Action",
        "maturity": "18+",
        "rating": "4.7",
        "meta": "Sub | Dub",
        "c1": "#2b3d27",
        "c2": "#d95a22",
        "synopsis": "A debt-ridden devil hunter is reborn with the power of his chainsaw companion.",
        "cast": "Kikunosuke Toya, Tomori Kusunoki",
        "audio": "Japanese, English",
        "subtitles": "English (US)",
        "related": ["jujutsu-kaisen", "attack-on-titan", "solo-leveling"],
    },
    {
        "id": "GY8VM8MWY",
        "slug": "haikyu",
        "title": "HAIKYU!!",
        "genre": "Sports",
        "maturity": "10+",
        "rating": "4.8",
        "meta": "Sub | Dub",
        "c1": "#19314d",
        "c2": "#f07b20",
        "synopsis": "A determined volleyball player joins forces with a former rival to take their high school team higher.",
        "cast": "Ayumu Murase, Kaito Ishikawa",
        "audio": "Japanese, English",
        "subtitles": "English (US)",
        "related": ["spy-x-family", "my-hero-academia", "one-piece"],
    },
]
CATALOG.append(
    {
        "id": "GT00371630",
        "slug": "daemons-of-the-shadow-realm",
        "title": "Daemons of the Shadow Realm",
        "genre": "Fantasy",
        "maturity": "16+",
        "rating": "4.8",
        "meta": "Sub | Dub",
        "c1": "#172b40",
        "c2": "#e65a2b",
        "synopsis": "Yuru, a young hunter living quietly in a remote village, is pulled into a world of powerful supernatural beings.",
        "cast": "Kensho Ono, Yume Miyamoto",
        "audio": "Japanese, English",
        "subtitles": "English (US), Español",
        "related": ["jujutsu-kaisen", "attack-on-titan", "frieren-beyond-journeys-end"],
    }
)
BY_SLUG = {item["slug"]: item for item in CATALOG}
BY_ID = {item["id"]: item for item in CATALOG}
POSTER_SLUGS = {
    "one-piece",
    "jujutsu-kaisen",
    "spy-x-family",
    "attack-on-titan",
    "my-hero-academia",
    "daemons-of-the-shadow-realm",
    "frieren-beyond-journeys-end",
    "solo-leveling",
    "chainsaw-man",
    "haikyu",
}
EPISODES = [
    {
        "id": "GN7UD8ARD",
        "number": 1,
        "title": "I'm Luffy! The Man Who's Gonna Be King of the Pirates!",
        "duration": 1440,
    },
    {
        "id": "G14U4DMEJ",
        "number": 2,
        "title": "Enter the Great Swordsman! Pirate Hunter Roronoa Zoro!",
        "duration": 1440,
    },
    {
        "id": "G6P8D8N76",
        "number": 3,
        "title": "Morgan versus Luffy! Who's the Mysterious Pretty Girl?",
        "duration": 1440,
    },
    {
        "id": "G50UZEW02",
        "number": 4,
        "title": "Luffy's Past! Enter Red-Haired Shanks!",
        "duration": 1440,
    },
]
DAEMONS_EPISODES = [
    {
        "id": "GE00374585ENUS",
        "number": 1,
        "title": "Asa and Yuru",
        "duration": 1440,
    }
]


def episodes_for(item: dict) -> list[dict]:
    if item["slug"] == "one-piece":
        return EPISODES
    if item["slug"] == "daemons-of-the-shadow-realm":
        return DAEMONS_EPISODES
    return [
        {
            "id": f"{item['id']}-E{number}",
            "number": number,
            "title": f"{item['title']} Episode {number}",
            "duration": 1440,
        }
        for number in range(1, 5)
    ]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(str(DB), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def cookie_name(request: Request) -> str:
    return (
        LOCAL_SESSION_COOKIE
        if LOCAL_HTTP_COOKIE and is_loopback(request)
        else SESSION_COOKIE
    )


def session(request: Request) -> tuple[str, dict]:
    token = getattr(request.state, "session_token", None)
    if token:
        resolved = AUTH.resolve_session(token)
        if resolved is not None:
            return token, resolved
    token = request.cookies.get(cookie_name(request))
    token, value = AUTH.ensure_session(token)
    request.state.session_token = token
    return token, value


def account(request: Request) -> dict | None:
    return session(request)[1].get("account")


def owner(request: Request) -> str | None:
    item = account(request)
    return f"subject:{item['subject_id']}" if item else None


def set_session_cookie(response, request: Request, token: str) -> None:
    secure = bool(BACKEND.session_cookie["secure"]) and not (
        LOCAL_HTTP_COOKIE and is_loopback(request)
    )
    response.set_cookie(
        cookie_name(request),
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def ensure_member_rows(owner_id: str, *, seed_demo: bool = False) -> None:
    with db() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO crunchyroll_profiles(owner,profile_id,name,maturity,language,is_active) VALUES (?,?,?,?,?,1)",
            (owner_id, "main", "Anime Fan", "Mature", "English (US)"),
        )
        connection.execute(
            "INSERT OR IGNORE INTO crunchyroll_profiles(owner,profile_id,name,maturity,language,is_active) VALUES (?,?,?,?,?,0)",
            (owner_id, "kids", "Kids", "Teen", "English (US)"),
        )
        connection.execute(
            "INSERT OR IGNORE INTO crunchyroll_preferences(owner) VALUES (?)",
            (owner_id,),
        )
        device_removed = connection.execute(
            "SELECT 1 FROM crunchyroll_history WHERE owner=? AND item_type='device-deactivated' LIMIT 1",
            (owner_id,),
        ).fetchone()
        if not device_removed:
            connection.execute(
                "INSERT OR IGNORE INTO crunchyroll_devices(owner,device_id,label,last_used) VALUES (?,?,?,?)",
                (owner_id, "web-browser", "Web Browser", "Today"),
            )
        connection.execute(
            "INSERT OR IGNORE INTO crunchyroll_progress(owner,episode_id,position,duration) VALUES (?,?,?,?)",
            (owner_id, EPISODES[0]["id"], 522, EPISODES[0]["duration"]),
        )
        if seed_demo and owner_id == f"subject:{DEMO_SUBJECT_ID}":
            connection.execute(
                "INSERT OR IGNORE INTO crunchyroll_watchlist(owner,series_id) VALUES (?,?)",
                (owner_id, CATALOG[0]["id"]),
            )
            connection.execute(
                "INSERT OR IGNORE INTO crunchyroll_subscriptions(owner,plan,term,status,amount_minor,currency,payment_scenario,flow_id) VALUES (?,?,?,?,?,?,?,?)",
                (
                    owner_id,
                    "Mega Fan",
                    "Monthly",
                    "Active",
                    1399,
                    "USD",
                    "seeded-local",
                    "seeded-demo",
                ),
            )
            exists = connection.execute(
                "SELECT 1 FROM crunchyroll_history WHERE owner=? AND item_type='subscription'",
                (owner_id,),
            ).fetchone()
            if not exists:
                connection.execute(
                    "INSERT INTO crunchyroll_history(owner,item_type,title,status,detail) VALUES (?,?,?,?,?)",
                    (
                        owner_id,
                        "subscription",
                        "Mega Fan Monthly",
                        "Active",
                        "Local sandbox subscription · $13.99/month",
                    ),
                )
        connection.commit()


def page_response(request: Request, document: str, *, status_code: int = 200):
    token, _ = session(request)
    response = HTMLResponse(document, status_code=status_code)
    set_session_cookie(response, request, token)
    return response


def redirect_with_session(request: Request, path: str, token: str | None = None):
    active = token or session(request)[0]
    response = RedirectResponse(path, status_code=303)
    set_session_cookie(response, request, active)
    return response


def nav(request: Request) -> str:
    member = account(request) is not None
    account_links = (
        "<a class='icon-link' href='/profiles'>Profiles</a><a class='icon-link' href='/watchlist'>My List</a><a class='icon-link' href='/account/settings'>Account</a>"
        if member
        else "<a class='icon-link' href='/login'>Log In</a>"
    )
    return f"""<header class="site-header"><button class="menu-button" data-menu-toggle aria-expanded="false" aria-controls="primary-navigation" aria-label="Open menu">☰ <span>Menu</span></button><a class="brand" href="/">crunchyroll</a><nav class="nav" id="primary-navigation" aria-label="Primary"><a href="/videos/popular">Popular</a><div class="nav-group"><button type="button" class="nav-trigger" data-dropdown-toggle="categories" aria-expanded="false">Categories <span>▾</span></button><div class="mega-menu" data-dropdown="categories"><div class="menu-stack"><a href="/videos/new">New</a><a href="/videos/alphabetical">Browse All (A-Z)</a><a href="/simulcastcalendar">Release Calendar</a></div><div class="genre-grid"><strong>Genres</strong><a href="/videos/action">Action</a><a href="/videos/adventure">Adventure</a><a href="/videos/comedy">Comedy</a><a href="/videos/drama">Drama</a><a href="/videos/fantasy">Fantasy</a><a href="/videos/sports">Sports</a></div></div></div><a href="/manga">Manga</a><a href="/games">Games</a><a href="/store">Store</a><div class="nav-group"><button type="button" class="nav-trigger" data-dropdown-toggle="news" aria-expanded="false">News <span>▾</span></button><div class="dropdown" data-dropdown="news"><a href="/news">All News</a><a href="/animeawards">Anime Awards</a><a href="/events">Events &amp; Experiences</a></div></div></nav><div class="header-tools"><a class="premium-link" href="/premium" aria-label="Try Premium">♛</a><a class="search-link" href="/search" aria-label="Search">⌕</a>{account_links}</div></header><div class="nav-scrim" data-menu-close></div>"""


def shell(request: Request, title: str, body: str, *, status_code: int = 200) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#23252b"><title>{esc(title)}</title><link rel="stylesheet" href="/static/styles.css"></head><body>{nav(request)}<main class="page">{body}</main><footer><div class="footer-links"><a href="/help">Help/FAQ</a><a href="/terms">Terms of Use</a><a href="/privacy">Privacy Policy</a><a href="/accessibility">Accessibility</a></div><div>© Crunchyroll, LLC · Offline functional reconstruction with synthetic local data.</div></footer><script src="/static/app.js"></script></body></html>"""


def card(item: dict) -> str:
    image = (
        f"<img src='/static/assets/poster-{esc(item['slug'])}.webp' alt='{esc(item['title'])}' loading='lazy'>"
        if item["slug"] in POSTER_SLUGS
        else f"<strong>{esc(item['title'])}</strong>"
    )
    return f"""<a class="card" data-series="{esc(item["id"])}" href="/series/{esc(item["id"])}/{esc(item["slug"])}"><div class="poster" style="--c1:{item["c1"]};--c2:{item["c2"]}">{image}<span class="poster-action">▶ View Series</span></div><h3>{esc(item["title"])}</h3><div class="meta">{esc(item["meta"])} · ★ {esc(item["rating"])}</div></a>"""


def row(title: str, items: list[dict]) -> str:
    return f"""<section class="section"><div class="section-head"><h2>{esc(title)}</h2><a href="/videos/popular">View All</a></div><div class="cards">{"".join(card(x) for x in items[:5])}</div></section>"""


def auth_card(title: str, contents: str) -> str:
    return f"<section class='auth-wrap'><div class='auth-card'><h1>{esc(title)}</h1>{contents}</div></section>"


def protected(request: Request, next_path: str):
    if account(request) is not None:
        ensure_member_rows(owner(request) or "")
        return None
    q = quote_plus(next_path)
    return page_response(
        request,
        shell(
            request,
            "Sign in required",
            auth_card(
                "Log In Required",
                f"<div class='error'>Log in or create an account to continue.</div><div class='actions'><a class='btn primary' href='/login?next={q}'>Log In</a><a class='btn' href='/register?next={q}'>Create Account</a></div>",
            ),
        ),
        status_code=401,
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "site_id": SITE_ID}


@app.get("/__websitebench/health")
def benchmark_health() -> dict:
    return {"status": "ok"}


@app.post("/__websitebench/reset")
def reset_state() -> dict:
    def reset_all(connection: sqlite3.Connection) -> None:
        BACKEND.lifecycle.reset_embedded(connection, confirm_site_id=SITE_ID)
        reset_business(connection)

    AUTH.reset_site_state(
        site_reset=reset_all,
        seed_accounts=[
            {
                "subject_id": "crunchyroll-demo-viewer",
                "email": DEMO_EMAIL,
                "display_name": "Anime Fan",
                "password": DEMO_PASSWORD,
                "email_verified": True,
            }
        ],
    )
    ensure_member_rows(f"subject:{DEMO_SUBJECT_ID}", seed_demo=True)
    return {"ok": True, "site_id": SITE_ID, "seed": "crunchyroll-seed-v1"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    member = account(request)
    if member:
        ensure_member_rows(owner(request) or "")
    hero = """<section class="hero"><div class="hero-copy"><img class="hero-title" src="/static/assets/hero-title.png" alt="Daemons of the Shadow Realm"><div class="hero-meta">16+ · Sub | Dub · Action, Adventure, Fantasy</div><p>Yuru, a young hunter who lives quietly in a remote village, is pulled into a world of powerful supernatural beings.</p><div class="actions"><a class="btn primary" href="/watch/GE00374585ENUS/asa-and-yuru">▷ Start Watching E1</a><form method="post" action="/watchlist/toggle"><input type="hidden" name="series_id" value="GT00371630"><input type="hidden" name="return_to" value="/"><button class="btn icon-only" aria-label="Add featured title to watchlist">♡</button></form></div></div><div class="hero-dots" aria-label="Featured slide 1 of 4"><span class="active"></span><span></span><span></span><span></span></div></section>"""
    continue_row = row("Continue Watching", CATALOG[:5]) if member else ""
    body = (
        hero
        + continue_row
        + row("Most Popular", CATALOG[:5])
        + row("New Episodes", CATALOG[3:8])
        + row("Because You Watched Action", CATALOG[5:10])
    )
    return page_response(
        request, shell(request, "Watch Popular Anime & Read Manga Online", body)
    )


@app.get("/videos/{kind}", response_class=HTMLResponse)
def browse(request: Request, kind: str, genre: str = "", sort: str = "popular"):
    allowed_genres = {"action", "adventure", "comedy", "drama", "fantasy", "sports"}
    if kind not in {"popular", "new", "alphabetical", *allowed_genres}:
        return not_found(request)
    items = list(CATALOG)
    heading = {
        "popular": "Popular",
        "new": "Newly Added",
        "alphabetical": "Browse All (A-Z)",
        "action": "Action",
        "adventure": "Adventure",
        "drama": "Drama",
        "comedy": "Comedy",
        "fantasy": "Fantasy",
        "sports": "Sports",
    }[kind]
    if kind in allowed_genres:
        items = [x for x in items if x["genre"].casefold() == kind]
    elif genre.casefold() in allowed_genres:
        items = [x for x in items if x["genre"].casefold() == genre.casefold()]
    if kind == "alphabetical" or sort == "alphabetical":
        items = sorted(items, key=lambda x: x["title"])
    cards = "".join(card(x) for x in items)
    body = f"""<section class="section"><div class="eyebrow">Browse anime</div><h1>{esc(heading)}</h1><p class="lede">Explore series available in the offline anime catalog.</p><form class="filter-bar" method="get"><select name="genre" aria-label="Filter by genre"><option value="">All Genres</option>{''.join(f'<option value="{g}" {"selected" if genre.casefold() == g else ""}>{g.title()}</option>' for g in sorted(allowed_genres))}</select><select name="sort" aria-label="Sort"><option value="popular">Most Popular</option><option value="new">Newest</option><option value="alphabetical" {"selected" if sort == "alphabetical" else ""}>Alphabetical</option></select><button class="btn primary">Filter</button></form><div class="cards">{cards}</div></section>"""
    return page_response(request, shell(request, f"{heading} Anime", body))


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    query = q.strip()
    results = (
        [
            x
            for x in CATALOG
            if query.casefold() in (x["title"] + " " + x["genre"]).casefold()
        ]
        if query
        else CATALOG
    )
    if results:
        content = f"<div class='cards'>{''.join(card(x) for x in results)}</div>"
        message = (
            f"{len(results)} matching title{'s' if len(results) != 1 else ''}"
            if query
            else "Browse every title"
        )
    else:
        content = """<div class="empty"><h2>No results found</h2><p>We couldn't find a match. Try another title or clear your search.</p><div class="actions" style="justify-content:center"><a class="btn primary" href="/videos/popular">Browse Popular</a><a class="btn" href="/search">Clear Search</a></div></div>"""
        message = "No matches"
    body = f"""<section class="section"><div class="eyebrow">Anime records and actions</div><h1>Search</h1><form class="filter-bar" role="search"><input name="q" value="{esc(query)}" placeholder="Search anime" aria-label="Search anime"><select name="genre" aria-label="Filter search results"><option>All</option><option>Series</option><option>Episodes</option></select><button class="btn primary">Search</button></form><p class="meta">{esc(message)}</p>{content}</section>"""
    return page_response(request, shell(request, f"Search {query}".strip(), body))


@app.get("/series/{series_id}/{slug}", response_class=HTMLResponse)
def series(request: Request, series_id: str, slug: str):
    item = BY_ID.get(series_id) or BY_SLUG.get(slug)
    if item is None:
        return not_found(request)
    member = account(request) is not None
    saved = False
    if member:
        ensure_member_rows(owner(request) or "")
        with db() as connection:
            saved = (
                connection.execute(
                    "SELECT 1 FROM crunchyroll_watchlist WHERE owner=? AND series_id=?",
                    (owner(request), item["id"]),
                ).fetchone()
                is not None
            )
    watch_action = f"""<form method="post" action="/watchlist/toggle"><input type="hidden" name="series_id" value="{esc(item["id"])}"><input type="hidden" name="return_to" value="/series/{esc(item["id"])}/{esc(item["slug"])}"><button class="btn" type="submit">{"Remove from Watchlist" if saved else "Add to Watchlist"}</button></form>"""
    episodes = episodes_for(item)
    episode_html = "".join(
        f"""<article class="episode"><div class="thumb">E{ep["number"]}</div><div><strong>Episode {ep["number"]} · {esc(ep["title"])}</strong><p>24m · Sub | Dub</p></div><a class="btn primary" href="/watch/{ep["id"]}/{item["slug"]}-episode-{ep["number"]}">Play</a></article>"""
        for ep in episodes
    )
    related = [BY_SLUG[x] for x in item["related"] if x in BY_SLUG]
    hero = f"""<section class="title-hero"><div class="content"><div class="eyebrow">{esc(item["genre"])} · Series</div><h1>{esc(item["title"])}</h1><div><span class="pill">★ {esc(item["rating"])}</span><span class="pill">{esc(item["maturity"])} </span><span class="pill">{esc(item["meta"])}</span></div><p class="lede">{esc(item["synopsis"])}</p><div class="actions"><a class="btn primary" href="/watch/{episodes[0]["id"]}/{item["slug"]}-episode-1">Start Watching E1</a>{watch_action}</div></div></section>"""
    details = f"""<section class="section details-grid"><div><div class="tabs"><a class="active" href="#episodes">Episodes</a><a href="#details">Details</a></div><h2 id="episodes">Season 1</h2><div class="episodes">{episode_html}</div></div><aside id="details"><h2>Details</h2><div class="panel"><div class="row"><span>Maturity Rating</span><strong>{esc(item["maturity"])}</strong></div><div class="row"><span>Audio</span><strong>{esc(item["audio"])}</strong></div><div class="row"><span>Subtitles</span><strong>{esc(item["subtitles"])}</strong></div><div class="row"><span>Cast</span><strong>{esc(item["cast"])}</strong></div><p class="help-text">Content Advisory: fantasy violence and thematic material.</p></div></aside></section>"""
    return page_response(
        request,
        shell(request, item["title"], hero + details + row("More Like This", related)),
    )


@app.post("/watchlist/toggle")
def toggle_watchlist(
    request: Request, series_id: str = Form(""), return_to: str = Form("/watchlist")
):
    guard = protected(request, return_to)
    if guard:
        return guard
    item = BY_ID.get(series_id)
    if not item:
        return redirect_with_session(request, "/watchlist")
    with db() as connection:
        existing = connection.execute(
            "SELECT 1 FROM crunchyroll_watchlist WHERE owner=? AND series_id=?",
            (owner(request), series_id),
        ).fetchone()
        if existing:
            connection.execute(
                "DELETE FROM crunchyroll_watchlist WHERE owner=? AND series_id=?",
                (owner(request), series_id),
            )
        else:
            connection.execute(
                "INSERT INTO crunchyroll_watchlist(owner,series_id) VALUES (?,?)",
                (owner(request), series_id),
            )
        connection.commit()
    safe_return = (
        return_to
        if return_to.startswith("/") and not return_to.startswith("//")
        else "/watchlist"
    )
    return redirect_with_session(request, safe_return)


@app.get("/watchlist", response_class=HTMLResponse)
def watchlist(request: Request):
    guard = protected(request, "/watchlist")
    if guard:
        return guard
    with db() as connection:
        ids = [
            x["series_id"]
            for x in connection.execute(
                "SELECT series_id FROM crunchyroll_watchlist WHERE owner=? ORDER BY created_at DESC",
                (owner(request),),
            )
        ]
    items = [BY_ID[x] for x in ids if x in BY_ID]
    content = (
        f"<div class='cards'>{''.join(card(x) for x in items)}</div>"
        if items
        else "<div class='empty'><h2>Your Watchlist is empty</h2><p>Add a series to find it here.</p><a class='btn primary' href='/videos/popular'>Browse Popular</a></div>"
    )
    return page_response(
        request,
        shell(
            request,
            "My List",
            f"<section class='section'><div class='eyebrow'>Your library</div><h1>My List</h1>{content}</section>",
        ),
    )


@app.get("/manga", response_class=HTMLResponse)
def manga(request: Request):
    books = (
        ("Smoking Behind the Supermarket with You", "manga-1.webp"),
        ("The Summer Hikaru Died", "manga-2.webp"),
        ("That Time I Got Reincarnated as a Slime", "manga-3.webp"),
        ("My Dress-Up Darling", "manga-4.webp"),
    )
    cards = "".join(
        f"<a class='media-card' href='/manga/{i}'><img src='/static/assets/{image}' alt='{esc(title)} cover'><h2>{esc(title)}</h2><span>Read preview →</span></a>"
        for i, (title, image) in enumerate(books, 1)
    )
    body = f"""<section class="editorial-hero manga-hero"><div><div class="eyebrow">Crunchyroll Manga</div><h1>A new way to read manga</h1><p>Discover popular stories and continue reading with a local preview experience.</p><a class="btn primary" href="#manga-library">Explore Manga</a></div></section><section class="section" id="manga-library"><div class="section-head"><h2>Popular right now</h2><a href="/search">Search all</a></div><div class="media-grid">{cards}</div></section>"""
    return page_response(request, shell(request, "Read Manga Online", body))


@app.get("/manga/{book_id}", response_class=HTMLResponse)
def manga_detail(request: Request, book_id: int):
    if book_id not in {1, 2, 3, 4}:
        return not_found(request)
    title = ("Smoking Behind the Supermarket with You", "The Summer Hikaru Died", "That Time I Got Reincarnated as a Slime", "My Dress-Up Darling")[book_id - 1]
    body = f"""<section class="reader"><div class="reader-page"><img src="/static/assets/manga-{book_id}.webp" alt="Cover of {esc(title)}"></div><div class="reader-copy"><div class="eyebrow">Free preview</div><h1>{esc(title)}</h1><p>This local preview contains no account charge and does not contact an external manga service.</p><div class="actions"><button class="btn primary" type="button" data-reader-next>Next Page</button><a class="btn" href="/manga">Back to Manga</a></div><p class="success" data-reader-status hidden>You're at the end of this local preview.</p></div></section>"""
    return page_response(request, shell(request, title, body))


@app.get("/games", response_class=HTMLResponse)
def games(request: Request):
    body = """<section class="editorial-hero games-hero"><div><div class="eyebrow">Crunchyroll Games</div><h1>Play anime-inspired games</h1><p>Discover Game Vault titles included with eligible Premium memberships.</p><div class="actions"><a class="btn primary" href="#game-vault">Browse Game Vault</a><a class="btn" href="/premium">See Premium Plans</a></div></div></section><section class="section" id="game-vault"><h2>Featured Games</h2><div class="feature-grid"><article class="feature-card violet"><strong>River City Girls</strong><p>Beat 'em up action</p><a href="/games/river-city-girls">View Game</a></article><article class="feature-card blue"><strong>Moonstone Island</strong><p>Creature-collecting life sim</p><a href="/games/moonstone-island">View Game</a></article><article class="feature-card red"><strong>Shantae and the Seven Sirens</strong><p>Platform adventure</p><a href="/games/shantae">View Game</a></article></div></section>"""
    return page_response(request, shell(request, "Anime-Inspired Games", body))


@app.get("/games/{game_id}", response_class=HTMLResponse)
def game_detail(request: Request, game_id: str):
    names = {"river-city-girls": "River City Girls", "moonstone-island": "Moonstone Island", "shantae": "Shantae and the Seven Sirens"}
    if game_id not in names:
        return not_found(request)
    body = f"""<section class="title-hero"><div class="content"><div class="eyebrow">Game Vault</div><h1>{esc(names[game_id])}</h1><p class="lede">This page recreates game discovery locally. Game installation is unavailable in the offline fixture.</p><div class="actions"><a class="btn primary" href="/premium">Get Premium Access</a><a class="btn" href="/games">All Games</a></div></div></section>"""
    return page_response(request, shell(request, names[game_id], body))


@app.get("/store", response_class=HTMLResponse)
def store(request: Request):
    body = """<section class="store-hero"><div><div class="eyebrow">Crunchyroll Store</div><h1>Anime merch for every fan</h1><p>Figures, apparel, manga, and exclusive collectibles.</p><a class="btn primary" href="#store-products">Shop Featured</a></div></section><section class="section" id="store-products"><h2>Featured collections</h2><div class="feature-grid"><article class="product-card"><span class="product-art">ONE PIECE</span><h3>Monkey D. Luffy Figure</h3><p>$29.99</p><button class="btn" type="button" data-cart-add>Add to Local Cart</button></article><article class="product-card"><span class="product-art violet">JUJUTSU KAISEN</span><h3>Sorcerer Hoodie</h3><p>$54.95</p><button class="btn" type="button" data-cart-add>Add to Local Cart</button></article><article class="product-card"><span class="product-art blue">SPY x FAMILY</span><h3>Anya Plush</h3><p>$24.99</p><button class="btn" type="button" data-cart-add>Add to Local Cart</button></article></div><div class="cart-toast" data-cart-status hidden>Added to your local demo cart.</div></section>"""
    return page_response(request, shell(request, "Crunchyroll Store", body))


@app.get("/news", response_class=HTMLResponse)
def news(request: Request):
    stories = ("New Anime Arrivals to Watch This Week", "Behind the Scenes with Your Favorite Creators", "The Biggest Announcements from Anime Expo", "Summer Season Streaming Guide")
    articles = "".join(f"<a class='news-card' href='/news/{i}'><img src='/static/assets/news-{i}.webp' alt='{esc(title)}'><div><span class='eyebrow'>Anime News</span><h2>{esc(title)}</h2><p>Read the latest story, interviews, and updates.</p></div></a>" for i, title in enumerate(stories, 1))
    body = f"<section class='section editorial'><div class='section-head'><div><div class='eyebrow'>Crunchyroll News</div><h1>Latest Anime News</h1></div><a class='btn' href='/events'>Events</a></div><div class='news-grid'>{articles}</div></section>"
    return page_response(request, shell(request, "Anime News & Top Stories", body))


@app.get("/news/{story_id}", response_class=HTMLResponse)
def news_detail(request: Request, story_id: int):
    stories = ("New Anime Arrivals to Watch This Week", "Behind the Scenes with Your Favorite Creators", "The Biggest Announcements from Anime Expo", "Summer Season Streaming Guide")
    if story_id not in range(1, 5):
        return not_found(request)
    title = stories[story_id - 1]
    body = f"""<article class="article"><div class="eyebrow">Anime News</div><h1>{esc(title)}</h1><p class="lede">The latest news from the world of anime, recreated from the supplied page materials.</p><img src="/static/assets/news-{story_id}.webp" alt="{esc(title)}"><p>Explore new releases, creator stories, and community highlights. This offline article keeps navigation and reading interactions available without loading remote content.</p><div class="actions"><a class="btn primary" href="/news">All News</a><a class="btn" href="/videos/new">Watch New Anime</a></div></article>"""
    return page_response(request, shell(request, title, body))


@app.get("/events", response_class=HTMLResponse)
def events(request: Request):
    body = """<section class="editorial-hero events-hero"><div><div class="eyebrow">Events &amp; Experiences</div><h1>See Crunchyroll live</h1><p>Explore convention appearances, premieres, and fan experiences.</p><a class="btn primary" href="#upcoming-events">Upcoming Events</a></div></section><section class="section" id="upcoming-events"><h2>Upcoming Events</h2><div class="feature-grid"><article class="panel"><h2>Crunchyroll Expo</h2><p>Sep 18–20 · Local event preview</p><a href="/events/crunchyroll-expo">Event Details</a></article><article class="panel"><h2>Anime NYC</h2><p>Nov 20–22 · Local event preview</p><a href="/events/anime-nyc">Event Details</a></article></div></section>"""
    return page_response(request, shell(request, "Events", body))


@app.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: str):
    names = {"crunchyroll-expo": "Crunchyroll Expo", "anime-nyc": "Anime NYC"}
    if event_id not in names:
        return not_found(request)
    body = f"<section class='section'><div class='eyebrow'>Event Details</div><h1>{esc(names[event_id])}</h1><div class='panel'><p>Schedule and venue details are shown as a local preview. Registration is not performed by this offline clone.</p><a class='btn primary' href='/events'>Back to Events</a></div></section>"
    return page_response(request, shell(request, names[event_id], body))


@app.get("/animeawards", response_class=HTMLResponse)
def anime_awards(request: Request):
    body = """<section class="awards-hero"><div><div class="eyebrow">Crunchyroll Anime Awards</div><h1>Celebrating anime's brightest stars</h1><p>Relive winners, performances, and unforgettable moments.</p><div class="actions"><a class="btn primary" href="#award-highlights">View Highlights</a><a class="btn" href="/news">Awards News</a></div></div></section><section class="section" id="award-highlights"><h2>2026 Highlights</h2><div class="feature-grid"><article class="feature-card gold"><strong>Anime of the Year</strong><p>Discover this year's winner</p></article><article class="feature-card violet"><strong>Best Animation</strong><p>Celebrating outstanding artistry</p></article><article class="feature-card red"><strong>Best Original Anime</strong><p>Honoring bold new stories</p></article></div></section>"""
    return page_response(request, shell(request, "The Anime Awards", body))


@app.get("/simulcastcalendar", response_class=HTMLResponse)
def simulcast_calendar(request: Request, day: str = "Monday"):
    days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    day = day if day in days else "Monday"
    tabs = "".join(
        "<a class='{active}' href='/simulcastcalendar?day={day}'>{label}</a>".format(
            active="active" if item == day else "", day=item, label=item[:3]
        )
        for item in days
    )
    episodes = "".join(f"<article class='calendar-item'><div class='thumb'>E{i}</div><div><h2>{esc(show['title'])}</h2><p>Episode {i} · Available at {9 + i}:00 PM</p></div><a class='btn primary' href='/series/{show['id']}/{show['slug']}'>View Series</a></article>" for i, show in enumerate(CATALOG[:4], 1))
    body = f"<section class='section'><div class='eyebrow'>Release Calendar</div><h1>Simulcast Calendar</h1><div class='calendar-tabs'>{tabs}</div><h2>{esc(day)}</h2><div class='episodes'>{episodes}</div></section>"
    return page_response(request, shell(request, "Simulcast Calendar", body))


@app.get("/premium", response_class=HTMLResponse)
def premium(request: Request, term: str = "monthly"):
    term = "yearly" if term == "yearly" else "monthly"
    prices = {"Fan": "7.99", "Mega Fan": "13.99", "Ultimate Fan": "17.99"}
    plans = []
    benefits = {
        "Fan": [
            "Stream on 1 device",
            "Full anime library",
            "New episodes shortly after Japan",
        ],
        "Mega Fan": [
            "Stream on 4 devices",
            "Offline viewing",
            "Crunchyroll Game Vault",
            "Store benefits",
        ],
        "Ultimate Fan": [
            "Stream on 6 devices",
            "Offline viewing",
            "Exclusive merchandise",
            "Expanded store benefits",
        ],
    }
    for name in ("Fan", "Mega Fan", "Ultimate Fan"):
        price = prices[name] if term == "monthly" else f"{float(prices[name]) * 10:.2f}"
        badge = "<div class='badge'>Most Popular</div>" if name == "Mega Fan" else ""
        plans.append(
            f"""<article class="plan {"featured" if name == "Mega Fan" else ""}">{badge}<h2>{name}</h2><div class="price">${price}<small>/{"mo" if term == "monthly" else "yr"}</small></div><ul>{"".join(f"<li>{esc(x)}</li>" for x in benefits[name])}</ul><form method="post" action="/select-plan"><input type="hidden" name="plan" value="{name}"><input type="hidden" name="term" value="{term}"><button class="btn {"primary" if name == "Mega Fan" else ""}" type="submit">Choose {name}</button></form></article>"""
        )
    body = f"""<section class="section"><div class="eyebrow">Premium membership</div><h1>Upgrade Your Anime Experience with Premium</h1><p class="lede">Choose the plan that fits how you watch.</p><div class="tabs"><a class="{"active" if term == "monthly" else ""}" href="/premium?term=monthly">Monthly</a><a class="{"active" if term == "yearly" else ""}" href="/premium?term=yearly">Yearly</a></div><div class="plans">{"".join(plans)}</div><p class="help-text">Local fixture pricing in USD. Plans renew until cancelled. No real payment information is accepted.</p></section>"""
    return page_response(request, shell(request, "Crunchyroll Premium", body))


@app.post("/select-plan")
def select_plan(request: Request, plan: str = Form(""), term: str = Form("monthly")):
    if plan not in {"Fan", "Mega Fan", "Ultimate Fan"}:
        return redirect_with_session(request, "/premium")
    path = f"/checkout?plan={quote_plus(plan)}&term={'yearly' if term == 'yearly' else 'monthly'}"
    if account(request) is None:
        return redirect_with_session(request, f"/register?next={quote_plus(path)}")
    return redirect_with_session(request, path)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", error: str = ""):
    message = f"<div class='error'>{esc(error)}</div>" if error else ""
    body = auth_card(
        "Log In",
        f"""{message}<form method="post" action="/login"><input type="hidden" name="next" value="{esc(next)}"><div class="field"><label>Email Address<input required type="email" autocomplete="email" name="email"></label></div><div class="field"><label>Password<input required minlength="6" type="password" autocomplete="current-password" name="password"></label></div><button class="btn primary" style="width:100%" type="submit">Log In</button></form><div class="auth-links"><a href="/reset-password">Forgot Password?</a><span>|</span><a href="/register">Create Account</a></div><div class="divider">Demo access</div><form method="post" action="/fixture/session"><input type="hidden" name="next" value="{esc(next)}"><button class="btn soft" style="width:100%" type="submit">Continue with local demo profile</button></form><p class="legal"><a href="/terms">Terms of Use</a> · <a href="/privacy">Privacy Policy</a></p>""",
    )
    return page_response(request, shell(request, "Log In", body))


@app.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
):
    token, _ = session(request)
    if not email or not password:
        return login_form(request, next, "Enter your email address and password.")
    try:
        result = AUTH.sign_in(token, email=email, password=password)
    except AuthError:
        return login_form(request, next, "Email address or password is incorrect.")
    destination = next if next.startswith("/") and not next.startswith("//") else "/"
    ensure_member_rows(f"subject:{result['account']['subject_id']}")
    return redirect_with_session(request, destination, result["session_token"])


@app.post("/fixture/session")
def fixture_session(request: Request, next: str = Form("/")):
    token, _ = session(request)
    result = AUTH.sign_in(token, email=DEMO_EMAIL, password=DEMO_PASSWORD)
    ensure_member_rows(f"subject:{result['account']['subject_id']}", seed_demo=True)
    destination = next if next.startswith("/") and not next.startswith("//") else "/"
    return redirect_with_session(request, destination, result["session_token"])


@app.post("/logout")
def logout(request: Request):
    AUTH.sign_out(request.cookies.get(cookie_name(request)))
    return redirect_with_session(request, "/")


@app.get("/register", response_class=HTMLResponse)
def register_form(
    request: Request,
    next: str = "/checkout?plan=Mega+Fan&term=monthly",
    error: str = "",
):
    message = f"<div class='error'>{esc(error)}</div>" if error else ""
    body = auth_card(
        "Create Account",
        f"""{message}<form method="post" action="/register"><input type="hidden" name="next" value="{esc(next)}"><div class="field"><label>Email Address<input required type="email" autocomplete="email" name="email"></label></div><div class="field"><label>Password<input required minlength="6" type="password" autocomplete="new-password" name="password" aria-describedby="password-help"></label><span id="password-help" class="help-text">Use at least 6 characters, do not use empty spaces</span></div><label class="help-text"><input type="checkbox" name="notifications"> Send me Crunchyroll info, offers, and news.</label><div class="actions"><button class="btn primary" style="width:100%" type="submit">Create Account</button></div></form><div class="auth-links">Already have an account? <a href="/login">Log In</a></div><p class="legal">By creating an account you're agreeing to our <a href="/terms">Terms of Use</a> &amp; <a href="/privacy">Privacy Policy</a>, and you confirm that you are at least 18 years of age. A local verification step follows; no real email is sent.</p>""",
    )
    return page_response(request, shell(request, "Create Account", body))


@app.post("/register")
def register(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/checkout?plan=Mega+Fan&term=monthly"),
):
    token, _ = session(request)
    if not email or not password:
        return register_form(
            request, next, "Enter an email address and password before continuing."
        )
    try:
        AUTH.start_registration(
            token,
            email=email,
            display_name=email.split("@", 1)[0] or "Anime Fan",
            password=password,
        )
        mail = AUTH.local_mail_for_session(token, purpose="registration")
    except (AuthError, ValueError) as exc:
        return register_form(request, next, str(exc))
    if not mail:
        return register_form(
            request, next, "Local verification guidance is unavailable. Try again."
        )
    body = auth_card(
        "Verify Your Email",
        f"""<div class="success">No email was sent. Use this local-only verification code: <strong>{esc(mail["verification_code"])}</strong></div><form method="post" action="/register/verify"><input type="hidden" name="next" value="{esc(next)}"><div class="field"><label>Verification code<input required inputmode="numeric" name="code"></label></div><button class="btn primary" style="width:100%">Verify &amp; Continue</button></form><p class="help-text">The code belongs only to this browser session and expires locally.</p>""",
    )
    return page_response(request, shell(request, "Verify Your Email", body))


@app.post("/register/verify")
def verify_registration(
    request: Request,
    code: str = Form(""),
    next: str = Form("/checkout?plan=Mega+Fan&term=monthly"),
):
    token, _ = session(request)
    try:
        AUTH.verify_registration_code(token, code)
        result = AUTH.complete_registration(token)
    except AuthError as exc:
        return register_form(request, next, str(exc))
    ensure_member_rows(f"subject:{result['account']['subject_id']}")
    destination = next if next.startswith("/") and not next.startswith("//") else "/"
    return redirect_with_session(request, destination, result["session_token"])


@app.get("/reset-password", response_class=HTMLResponse)
def reset_form(request: Request, error: str = "", notice: str = ""):
    message = (
        f"<div class='error'>{esc(error)}</div>"
        if error
        else (f"<div class='success'>{esc(notice)}</div>" if notice else "")
    )
    body = auth_card(
        "Reset Password",
        f"""{message}<p class="help-text">A link would normally be sent to your email address to reset your password. This offline clone sends nothing.</p><form method="post" action="/reset-password"><div class="field"><label>Email Address<input required type="email" autocomplete="email" name="email"></label></div><button class="btn primary" style="width:100%" type="submit">Show Local Guidance</button></form><div class="auth-links"><a href="/login">Return to Log In</a></div><p class="legal"><a href="/terms">Terms of Use</a> · <a href="/privacy">Privacy Policy</a></p>""",
    )
    return page_response(request, shell(request, "Reset Password", body))


@app.post("/reset-password")
def reset_password(request: Request, email: str = Form("")):
    if not email:
        return reset_form(request, "Enter the email address for the account.")
    token, _ = session(request)
    try:
        AUTH.start_password_reset(token, email=email)
    except (AuthError, ValueError):
        pass
    return reset_form(
        request,
        notice="If a matching local account exists, recovery guidance is available in this browser. No reset message was sent.",
    )


@app.get("/profiles", response_class=HTMLResponse)
def profiles(request: Request, error: str = ""):
    guard = protected(request, "/profiles")
    if guard:
        return guard
    with db() as connection:
        rows = connection.execute(
            "SELECT * FROM crunchyroll_profiles WHERE owner=? ORDER BY profile_id",
            (owner(request),),
        ).fetchall()
    cards = "".join(
        f"""<article class="profile {"active" if x["is_active"] else ""}"><div class="avatar">{esc(x["name"][:1])}</div><h2>{esc(x["name"])}</h2><p class="meta">{esc(x["maturity"])} · {esc(x["language"])}</p><form method="post" action="/profiles/switch"><input type="hidden" name="profile_id" value="{esc(x["profile_id"])}"><button class="btn" type="submit">{"Active" if x["is_active"] else "Switch"}</button></form></article>"""
        for x in rows
    )
    body = f"""<section class="section"><div class="eyebrow">Who's watching?</div><h1>Select Profile</h1>{f"<div class='error'>{esc(error)}</div>" if error else ""}<div class="profile-grid">{cards}</div><div class="panel" style="margin-top:24px"><h2>Create or edit a profile</h2><form method="post" action="/profiles"><div class="field"><label>Profile name<input required name="name" maxlength="24"></label></div><div class="field"><label>Maturity<select name="maturity"><option>Teen</option><option selected>Mature</option><option>All Ages</option></select></label></div><div class="field"><label>Language<select name="language"><option>English (US)</option><option>Español</option><option>日本語</option></select></label></div><button class="btn primary">Save Profile</button></form></div></section>"""
    return page_response(request, shell(request, "Select Profile", body))


@app.post("/profiles")
def save_profile(
    request: Request,
    name: str = Form(""),
    maturity: str = Form("Mature"),
    language: str = Form("English (US)"),
):
    guard = protected(request, "/profiles")
    if guard:
        return guard
    clean = name.strip()
    if not clean:
        return profiles(request, "Profile name is required.")
    profile_id = (
        re.sub(r"[^a-z0-9]+", "-", clean.casefold()).strip("-")[:30] or "profile"
    )
    with db() as connection:
        connection.execute(
            "INSERT INTO crunchyroll_profiles(owner,profile_id,name,maturity,language,is_active) VALUES (?,?,?,?,?,0) ON CONFLICT(owner,profile_id) DO UPDATE SET name=excluded.name,maturity=excluded.maturity,language=excluded.language",
            (owner(request), profile_id, clean, maturity, language),
        )
        connection.commit()
    return redirect_with_session(request, "/profiles")


@app.post("/profiles/switch")
def switch_profile(request: Request, profile_id: str = Form("")):
    guard = protected(request, "/profiles")
    if guard:
        return guard
    with db() as connection:
        exists = connection.execute(
            "SELECT 1 FROM crunchyroll_profiles WHERE owner=? AND profile_id=?",
            (owner(request), profile_id),
        ).fetchone()
        if exists:
            connection.execute(
                "UPDATE crunchyroll_profiles SET is_active=0 WHERE owner=?",
                (owner(request),),
            )
            connection.execute(
                "UPDATE crunchyroll_profiles SET is_active=1 WHERE owner=? AND profile_id=?",
                (owner(request), profile_id),
            )
            connection.commit()
    return redirect_with_session(request, "/")


@app.get("/watch/{episode_id}/{slug}", response_class=HTMLResponse)
def watch(request: Request, episode_id: str, slug: str):
    guard = protected(request, request.url.path)
    if guard:
        return guard
    series_item = next((x for x in CATALOG if x["slug"] in slug), None)
    if series_item is None:
        series_item = next(
            (
                item
                for item in CATALOG
                if any(ep["id"] == episode_id for ep in episodes_for(item))
            ),
            CATALOG[0],
        )
    episodes = episodes_for(series_item)
    episode = next((x for x in episodes if x["id"] == episode_id), episodes[0])
    with db() as connection:
        progress = connection.execute(
            "SELECT position,duration FROM crunchyroll_progress WHERE owner=? AND episode_id=?",
            (owner(request), episode["id"]),
        ).fetchone()
    position = int(progress["position"]) if progress else 0
    index = episodes.index(episode)
    next_action = (
        f"<a class='btn primary' href='/watch/{episodes[index + 1]['id']}/{series_item['slug']}-episode-{episodes[index + 1]['number']}'>Next Episode</a>"
        if index + 1 < len(episodes)
        else f"<a class='btn primary' href='/series/{series_item['id']}/{series_item['slug']}'>Back to Series</a>"
    )
    body = f"""<section class="player-shell" data-player><div class="notice">Local controls and progress simulation. No licensed media or remote stream is loaded.</div><h1>{esc(series_item["title"])}</h1><p>Episode {episode["number"]} · {esc(episode["title"])}</p><div class="screen" aria-label="Local video surface"></div><div class="controls"><button data-player-action="toggle" data-state="paused">Play</button><label class="control-label">Seek<input data-progress data-episode="{episode["id"]}" type="range" min="0" max="{episode["duration"]}" value="{position}"></label><output data-progress-output>{position // 60}m</output><label class="control-label">Volume<input type="range" min="0" max="100" value="75"></label><select aria-label="Subtitles"><option>English (US)</option><option>Off</option></select><select aria-label="Audio"><option>Japanese</option><option>English</option></select><button data-player-action="fullscreen">Fullscreen</button></div><div class="actions"><a class="btn" href="/series/{series_item["id"]}/{series_item["slug"]}">Episodes &amp; Seasons</a>{next_action}</div></section>"""
    return page_response(request, shell(request, f"Watch {series_item['title']}", body))


@app.post("/api/progress")
async def save_progress(request: Request):
    if account(request) is None:
        return JSONResponse(
            {
                "error": "sign-in-required",
                "correction": "Log in before saving playback progress.",
            },
            status_code=401,
        )
    data = await request.json()
    episode_id = str(data.get("episode_id", ""))
    try:
        position = max(0, int(data.get("position", 0)))
        duration = max(1, int(data.get("duration", 1440)))
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid-progress"}, status_code=422)
    with db() as connection:
        connection.execute(
            "INSERT INTO crunchyroll_progress(owner,episode_id,position,duration,updated_at) VALUES (?,?,?,?,strftime('%s','now')) ON CONFLICT(owner,episode_id) DO UPDATE SET position=excluded.position,duration=excluded.duration,updated_at=excluded.updated_at",
            (owner(request), episode_id, min(position, duration), duration),
        )
        connection.commit()
    return {"ok": True, "position": min(position, duration)}


@app.get("/checkout", response_class=HTMLResponse)
def checkout(
    request: Request,
    plan: str = "Mega Fan",
    term: str = "monthly",
    error: str = "",
    status: str = "",
):
    guard = protected(request, request.url.path + "?" + request.url.query)
    if guard:
        return guard
    plan = plan if plan in {"Fan", "Mega Fan", "Ultimate Fan"} else "Mega Fan"
    term = "yearly" if term == "yearly" else "monthly"
    amounts = {"Fan": 799, "Mega Fan": 1399, "Ultimate Fan": 1799}
    amount = amounts[plan] * (10 if term == "yearly" else 1)
    message = (
        f"<div class='error'>{esc(error)}</div>"
        if error
        else (f"<div class='success'>{esc(status)}</div>" if status else "")
    )
    body = f"""<section class="section"><div class="eyebrow">Secure local checkout</div><h1>Review Membership</h1>{message}<div class="details-grid"><div class="panel"><h2>{esc(plan)} · {term.title()}</h2><div class="price">${amount / 100:.2f}<small>/{"mo" if term == "monthly" else "yr"}</small></div><p>4 concurrent streams and offline viewing are included with Mega Fan.</p><a href="/premium?term={term}">Change plan</a></div><div class="panel"><h2>Payment option</h2><p class="notice">Local sandbox only. Do not enter a card number, CVV, bank account, wallet, or real payment credential.</p><form method="post" action="/checkout"><input type="hidden" name="plan" value="{esc(plan)}"><input type="hidden" name="term" value="{term}"><div class="field"><label>Sandbox outcome<select name="scenario" required><option value="">Choose a local outcome</option><option value="sandbox-approved">Simulated approval</option><option value="sandbox-declined">Simulated decline</option><option value="sandbox-retry">Simulated retry</option></select></label></div><label class="help-text"><input type="checkbox" required name="terms"> I agree to the Terms of Use and recurring local fixture.</label><div class="actions"><button class="btn primary" type="submit">Start Membership</button></div></form></div></div></section>"""
    return page_response(request, shell(request, "Review Membership", body))


@app.post("/checkout")
def complete_checkout(
    request: Request,
    plan: str = Form(""),
    term: str = Form(""),
    scenario: str = Form(""),
    terms: str = Form(""),
    card_number: str = Form(""),
    cvv: str = Form(""),
):
    guard = protected(request, "/checkout")
    if guard:
        return guard
    if card_number or cvv:
        return checkout(
            request,
            plan or "Mega Fan",
            term or "monthly",
            "Payment credentials are forbidden. Choose only a local sandbox outcome.",
        )
    if (
        plan not in {"Fan", "Mega Fan", "Ultimate Fan"}
        or term not in {"monthly", "yearly"}
        or scenario not in {"sandbox-approved", "sandbox-declined", "sandbox-retry"}
        or not terms
    ):
        return checkout(
            request,
            plan or "Mega Fan",
            term or "monthly",
            "Choose a valid plan, local outcome, and accept the terms before continuing.",
        )
    amount = {"Fan": 799, "Mega Fan": 1399, "Ultimate Fan": 1799}[plan] * (
        10 if term == "yearly" else 1
    )
    owner_id = owner(request) or ""
    fingerprint = hashlib.sha256(
        f"{SITE_ID}|{owner_id}|{plan}|{term}|{amount}|USD".encode()
    ).hexdigest()
    key_suffix = hashlib.sha256(
        f"{owner_id}|{plan}|{term}|{scenario}".encode()
    ).hexdigest()[:24]
    with db() as connection:
        existing = connection.execute(
            "SELECT plan,term,status FROM crunchyroll_subscriptions WHERE owner=?",
            (owner_id,),
        ).fetchone()
    if (
        existing
        and existing["plan"] == plan
        and existing["term"] == term.title()
        and existing["status"] == "Active"
    ):
        return redirect_with_session(request, "/account/history")
    try:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            flow = BACKEND.payments.create_intent(
                owner=owner_id,
                amount_minor=amount,
                currency="USD",
                fingerprint=fingerprint,
                idempotency_key=f"checkout-create:{key_suffix}",
                connection=connection,
            )
            attempt = BACKEND.payments.attempt(
                flow_id=flow["flow_id"],
                owner=owner_id,
                amount_minor=amount,
                currency="USD",
                fingerprint=fingerprint,
                scenario_id=scenario,
                idempotency_key=f"checkout-attempt:{key_suffix}",
                connection=connection,
            )
            if attempt["status"] == "APPROVED":
                BACKEND.payments.consume_approval(
                    connection,
                    flow_id=flow["flow_id"],
                    owner=owner_id,
                    amount_minor=amount,
                    currency="USD",
                    fingerprint=fingerprint,
                )
                connection.execute(
                    "INSERT INTO crunchyroll_subscriptions(owner,plan,term,status,amount_minor,currency,payment_scenario,flow_id) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET plan=excluded.plan,term=excluded.term,status=excluded.status,amount_minor=excluded.amount_minor,currency=excluded.currency,payment_scenario=excluded.payment_scenario,flow_id=excluded.flow_id",
                    (
                        owner_id,
                        plan,
                        term.title(),
                        "Active",
                        amount,
                        "USD",
                        scenario,
                        flow["flow_id"],
                    ),
                )
                connection.execute(
                    "INSERT INTO crunchyroll_history(owner,item_type,title,status,detail) VALUES (?,?,?,?,?)",
                    (
                        owner_id,
                        "subscription",
                        f"{plan} {term.title()}",
                        "Active",
                        f"Local sandbox subscription · ${amount / 100:.2f}/{'month' if term == 'monthly' else 'year'}",
                    ),
                )
    except PaymentError as exc:
        return checkout(request, plan, term, str(exc))
    if attempt["status"] == "DECLINED":
        return checkout(
            request,
            plan,
            term,
            "The local sandbox declined this attempt. Choose another outcome and try again.",
        )
    if attempt["status"] == "RETRYABLE":
        return checkout(
            request,
            plan,
            term,
            "The local sandbox is temporarily unavailable. Retry when ready.",
        )
    return redirect_with_session(request, "/account/history?created=1")


@app.get("/account/history", response_class=HTMLResponse)
def history(request: Request, created: int = 0):
    guard = protected(request, "/account/history")
    if guard:
        return guard
    ensure_member_rows(owner(request) or "")
    with db() as connection:
        rows = connection.execute(
            "SELECT * FROM crunchyroll_history WHERE owner=? ORDER BY created_at DESC,history_id DESC",
            (owner(request),),
        ).fetchall()
    items = "".join(
        f"""<article class="panel history-item"><div><div class="eyebrow">{esc(x["item_type"])}</div><h2>{esc(x["title"])}</h2><p>{esc(x["detail"])}</p><span class="status">{esc(x["status"])}</span></div><div class="actions"><a class="btn" href="/account/settings?tab=billing">Details</a><a class="btn danger" href="/account/settings?tab=billing">Edit or Cancel</a></div></article>"""
        for x in rows
    )
    message = (
        "<div class='success'>Mega Fan membership was saved to your account history.</div>"
        if created
        else ""
    )
    return page_response(
        request,
        shell(
            request,
            "Account History",
            f"<section class='section'><div class='eyebrow'>Account</div><h1>History</h1>{message}{items}<a class='btn' href='/watchlist'>Back to My List</a></section>",
        ),
    )


@app.get("/account/settings", response_class=HTMLResponse)
def settings(request: Request, tab: str = "preferences", saved: int = 0, cancelled: int = 0):
    guard = protected(request, "/account/settings")
    if guard:
        return guard
    ensure_member_rows(owner(request) or "")
    with db() as connection:
        prefs = connection.execute(
            "SELECT * FROM crunchyroll_preferences WHERE owner=?", (owner(request),)
        ).fetchone()
        subscription = connection.execute(
            "SELECT * FROM crunchyroll_subscriptions WHERE owner=?", (owner(request),)
        ).fetchone()
        devices = connection.execute(
            "SELECT * FROM crunchyroll_devices WHERE owner=?", (owner(request),)
        ).fetchall()
    side = """<nav class="side-nav" aria-label="Account settings"><a class="active" href="/account/settings">Preferences</a><a href="/profiles">Profiles</a><a href="/account/history">History</a><a href="/account/settings?tab=billing">Membership &amp; Billing</a><a href="/account/settings?tab=devices">Devices</a></nav>"""
    if tab == "billing":
        plan = (
            f"<h2>{esc(subscription['plan'])} · {esc(subscription['term'])}</h2><p><span class='status'>{esc(subscription['status'])}</span> · ${subscription['amount_minor'] / 100:.2f} {esc(subscription['currency'])}</p>"
            if subscription
            else "<h2>No active membership</h2>"
        )
        notice = "<div class='success'>Your local membership was cancelled.</div>" if cancelled else ""
        cancel = "" if not subscription or subscription["status"] == "Cancelled" else """<button class="btn danger" type="button" data-dialog-open="cancel-membership">Review Cancellation</button>"""
        content = f"""{notice}<div class="panel">{plan}<div class="actions"><a class="btn" href="/premium">Upgrade or Downgrade</a>{cancel}<a class="btn" href="/account/history">Payment History</a></div><p class="help-text">Actions affect only the local sandbox account.</p></div><dialog id="cancel-membership"><form method="dialog"><button class="dialog-close" aria-label="Close">×</button></form><h2>Cancel membership?</h2><p>Your access remains a local simulation. This action can be reversed by choosing another plan.</p><div class="actions"><form method="post" action="/account/subscription/cancel"><button class="btn danger">Confirm Cancellation</button></form><button class="btn" type="button" data-dialog-close>Keep Membership</button></div></dialog>"""
    elif tab == "devices":
        content = (
            "<div class='panel'><h2>Manage Devices</h2>"
            + "".join(
                f"<div class='row'><span><strong>{esc(x['label'])}</strong><br><small>{esc(x['last_used'])}</small></span><form method='post' action='/account/devices/remove'><input type='hidden' name='device_id' value='{esc(x['device_id'])}'><button class='btn' type='submit'>Deactivate</button></form></div>"
                for x in devices
            )
            + ("<p class='help-text'>No active devices remain.</p>" if not devices else "")
            + "</div>"
        )
    else:
        content = f"""<div class="panel"><h2>Playback &amp; Language</h2>{'<div class="success">Preferences saved.</div>' if saved else ""}<form method="post" action="/account/settings"><div class="field"><label>Audio language<select name="audio_language"><option {"selected" if prefs["audio_language"] == "Japanese" else ""}>Japanese</option><option {"selected" if prefs["audio_language"] == "English" else ""}>English</option></select></label></div><div class="field"><label>Subtitle language<select name="subtitle_language"><option>English (US)</option><option>Español</option></select></label></div><label class="row"><span>Autoplay next episode</span><input type="checkbox" name="autoplay" {"checked" if prefs["autoplay"] else ""}></label><label class="row"><span>Notifications</span><input type="checkbox" name="notifications" {"checked" if prefs["notifications"] else ""}></label><div class="field"><label>Privacy<select name="privacy_mode"><option>Standard</option><option>Limited personalization</option></select></label></div><button class="btn primary">Save Preferences</button></form></div>"""
    body = f"<section class='section'><div class='eyebrow'>Account</div><h1>Settings</h1><div class='settings-grid'>{side}<div>{content}</div></div></section>"
    return page_response(request, shell(request, "Account Settings", body))


@app.post("/account/settings")
def save_settings(
    request: Request,
    audio_language: str = Form("Japanese"),
    subtitle_language: str = Form("English (US)"),
    autoplay: str = Form(""),
    notifications: str = Form(""),
    privacy_mode: str = Form("Standard"),
):
    guard = protected(request, "/account/settings")
    if guard:
        return guard
    with db() as connection:
        connection.execute(
            "UPDATE crunchyroll_preferences SET audio_language=?,subtitle_language=?,autoplay=?,notifications=?,privacy_mode=? WHERE owner=?",
            (
                audio_language,
                subtitle_language,
                int(bool(autoplay)),
                int(bool(notifications)),
                privacy_mode,
                owner(request),
            ),
        )
        connection.commit()
    return redirect_with_session(request, "/account/settings?saved=1")


@app.post("/account/subscription/cancel")
def cancel_subscription(request: Request):
    guard = protected(request, "/account/settings?tab=billing")
    if guard:
        return guard
    with db() as connection:
        subscription = connection.execute(
            "SELECT plan,term FROM crunchyroll_subscriptions WHERE owner=?",
            (owner(request),),
        ).fetchone()
        if subscription:
            connection.execute(
                "UPDATE crunchyroll_subscriptions SET status='Cancelled' WHERE owner=?",
                (owner(request),),
            )
            connection.execute(
                "INSERT INTO crunchyroll_history(owner,item_type,title,status,detail) VALUES (?,?,?,?,?)",
                (owner(request), "subscription", f"{subscription['plan']} {subscription['term'].title()}", "Cancelled", "Local sandbox membership cancellation"),
            )
            connection.commit()
    return redirect_with_session(request, "/account/settings?tab=billing&cancelled=1")


@app.post("/account/devices/remove")
def remove_device(request: Request, device_id: str = Form("")):
    guard = protected(request, "/account/settings?tab=devices")
    if guard:
        return guard
    with db() as connection:
        removed = connection.execute(
            "SELECT label FROM crunchyroll_devices WHERE owner=? AND device_id=?",
            (owner(request), device_id),
        ).fetchone()
        connection.execute(
            "DELETE FROM crunchyroll_devices WHERE owner=? AND device_id=?",
            (owner(request), device_id),
        )
        if removed:
            connection.execute(
                "INSERT INTO crunchyroll_history(owner,item_type,title,status,detail) VALUES (?,?,?,?,?)",
                (owner(request), "device-deactivated", removed["label"], "Deactivated", "Local device access removed"),
            )
        connection.commit()
    return redirect_with_session(request, "/account/settings?tab=devices")


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request, q: str = ""):
    query = q.strip()
    topics = (
        ("Using Crunchyroll", "Browse anime records, search titles, manage My List, and use playback controls.", "/videos/popular", "Browse anime"),
        ("Account Access", "Find sign-in, registration, profile, password recovery, and membership guidance.", "/login", "Account access"),
        ("Fix a Problem", "Get guidance for failed actions, billing, subtitles, audio, and video playback.", "/help/contact", "Contact Us"),
    )
    matches = [topic for topic in topics if not query or query.casefold() in (topic[0] + " " + topic[1]).casefold()]
    results = "".join(f"<article class='panel'><h2>{esc(title)}</h2><p>{esc(copy)}</p><a href='{path}'>{esc(label)}</a></article>" for title, copy, path, label in matches)
    if not results:
        results = "<div class='empty'><h2>No help topics found</h2><p>Try another phrase or contact support.</p><a class='btn primary' href='/help/contact'>Contact Us</a></div>"
    body = f"""<section class="section"><div class="eyebrow">Support &amp; Customer Service</div><h1>Crunchyroll Help</h1><form class="filter-bar" method="get"><input name="q" value="{esc(query)}" aria-label="Search help" placeholder="How can we help?"><button class="btn primary">Search</button></form>{f'<p class="meta">{len(matches)} topic(s) found</p>' if query else ''}<div class="plans">{results}</div></section>"""
    return page_response(request, shell(request, "Crunchyroll Help", body))


@app.get("/help/contact", response_class=HTMLResponse)
def contact(request: Request):
    body = """<section class="section"><div class="eyebrow">Support</div><h1>Contact Us</h1><div class="panel"><p>Choose the guidance that matches your issue. This offline support page does not send a ticket or expose private account data.</p><div class="row"><span>Anime records and actions</span><a href="/videos/popular">Browse guidance</a></div><div class="row"><span>Account access</span><a href="/reset-password">Recovery guidance</a></div><div class="row"><span>Failed playback or billing action</span><a href="/account/settings">Account guidance</a></div></div><a class="btn" href="/help">Back to Help</a></section>"""
    return page_response(request, shell(request, "Contact Us", body))


@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return page_response(
        request,
        shell(
            request,
            "Terms of Use",
            "<section class='section'><h1>Terms of Use</h1><p>This offline fixture accepts only synthetic local data and creates no external service effect.</p></section>",
        ),
    )


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return page_response(
        request,
        shell(
            request,
            "Privacy Policy",
            "<section class='section'><h1>Privacy Policy</h1><p>No credentials, cookies, private account data, or payment information are sent to a remote service.</p></section>",
        ),
    )


@app.get("/accessibility", response_class=HTMLResponse)
def accessibility(request: Request):
    return page_response(
        request,
        shell(
            request,
            "Accessibility",
            "<section class='section'><h1>Accessibility</h1><p>Keyboard-labelled controls, semantic headings, visible focus, and responsive layouts are provided throughout this offline experience.</p></section>",
        ),
    )


@app.get("/{path:path}", response_class=HTMLResponse)
def not_found(request: Request, path: str = ""):
    body = """<section class="not-found"><div class="code">404</div><h1>Page Not Found</h1><p>Yuzu says there's nothing to see here!</p><div class="actions" style="justify-content:center"><a class="btn primary" href="/videos/popular">Browse Popular Anime</a><a class="btn" href="/">Take Me Home</a></div></section>"""
    return page_response(
        request, shell(request, "404 - Page Not Found", body), status_code=404
    )
