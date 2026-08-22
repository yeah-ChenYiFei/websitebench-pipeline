from __future__ import annotations

import html
import json
import mimetypes
import os
import secrets
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode, urlsplit

from backend.site_backend_integration import open_site_services
from fastapi import Cookie, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from websitebench.local_clone_auth import (
    AuthConflict,
    AuthError,
    AuthRejected,
    LocalAuthStore,
)
from websitebench.site_backend import SiteBackend

SITE_ID = "beeradvocate"
REVIEW_SCORE_OPTIONS = tuple(Decimal(step) / 4 for step in range(4, 21))
REVIEW_MEDIA_ASSETS = {
    "": "No photo",
    "beers/1160.jpg": "Stone Imperial Stout bottle",
    "beers/806254.jpg": "Oktoberfest bottle",
    "beers/599268.jpg": "West Ghost bottle",
}
FOLLOWABLE_MEMBER_SLUGS = {
    "alex-444666",
    "alex-green",
    "beeradvocate",
    "draftmonger",
    "jamarcusmarinovich",
    "mvanaskie13",
    "njzzle8287",
    "the-snow-bird",
}


def format_review_score(score: object) -> str:
    return format(Decimal(str(score)), "f").rstrip("0").rstrip(".")


def review_score_options() -> str:
    return "".join(
        f"<option value='{format_review_score(score)}'>"
        f"{format_review_score(score)}</option>"
        for score in REVIEW_SCORE_OPTIONS
    )


def review_form_markup(
    beer_id: int,
    *,
    inline: bool,
    review: sqlite3.Row | None = None,
    action: str | None = None,
) -> str:
    fields = "".join(
        f"<label>{name.title()}<select name='{name}' required>"
        "<option value=''></option>"
        + "".join(
            f"<option value='{format_review_score(score)}'"
            f"{' selected' if review is not None and Decimal(str(review[name])) == score else ''}>"
            f"{format_review_score(score)}</option>"
            for score in REVIEW_SCORE_OPTIONS
        )
        + "</select></label>"
        for name in ("look", "smell", "taste", "feel", "overall")
    )
    media_value = str(review["media_asset"] or "") if review is not None else ""
    media_options = "".join(
        f"<option value='{html.escape(value)}' "
        f"{'selected' if value == media_value else ''}>{html.escape(label)}</option>"
        for value, label in REVIEW_MEDIA_ASSETS.items()
    )
    comment = html.escape(str(review["comment"])) if review is not None else ""
    form_id = " id='review-form'" if inline else ""
    form_class = "panel review-form" if inline else "panel"
    form_action = action or f"/beer/rate/{beer_id}"
    return (
        f"<section{form_id} class='{form_class}'><h1>Rate this beer</h1>"
        "<p class='notice'>Member reviews are stored securely in your account and are not sent to another website.</p>"
        f"<form method='post' action='{html.escape(form_action)}'>"
        f"<div class='dimensions'>{fields}</div>"
        f"<label>Photo<select name='media_asset'>{media_options}</select></label>"
        "<label>Review<textarea id='comment' name='comment' required "
        f"maxlength='4000'>{comment}</textarea></label><button name='submit' "
        "type='submit'>Submit Review</button></form></section>"
    )

styles = ["American Imperial Stout", "American IPA", "Märzen", "Czech Pilsner", "Belgian Tripel", "English Porter"]
featured = [
    ("Stone Imperial Stout", "Stone Brewing", "Russian Imperial Stout", 10.5),
    ("Oktoberfest (2026)", "Sierra Nevada Brewing Co.", "Festbier / Wiesnbier", 6.0),
    ("West Ghost", "Sierra Nevada Brewing Co.", "American IPA", 7.2),
    ("Citrus Hopslam", "Bell's Brewery - Eccentric Café & General Store", "Imperial IPA", 10.0),
    ("Peach Apricot D.B.V.S.O.J.", "Revolution Brewing", "English Barleywine", 13.3),
    ("Trooper", "Lagunitas Brewing Company", "American IPA", 6.6),
    ("Rye da Tiger", "3 Floyds Brewing Co.", "Rye Beer", 7.5),
    ("October Fest", "Samuel Adams", "Märzen", 5.3),
    ("Pils", "Sierra Nevada Brewing Co.", "Czech / Bohemian Pilsner", 4.7),
    ("KBS - Iced Mocha", "Founders Brewing Company", "American Strong Ale", 11.0),
    ("Premium Pils", "Paulaner Brauerei", "German Pilsner", 4.8),
    ("Cheese Crown", "Hop Butcher For The World", "Hazy Imperial IPA", 10.0),
]
featured_image_ids = [
    1160,
    806254,
    599268,
    803735,
    799121,
    804818,
    85094,
    102,
    741174,
    782419,
    1784,
]
featured_routes = [
    (147, 1160),
    (140, 806254),
    (140, 599268),
    (287, 803735),
    (29160, 799121),
    (220, 804818),
    (26, 85094),
    (35, 102),
    (140, 741174),
    (1199, 782419),
    (124, 1784),
    (40359, 805781),
]
forum_source_meta = {
    "What Beer Are You Drinking Now? #5052": (4, "11 minutes ago", None),
    "Belgian Beer Appreciation Thread (2026)": (285, "3 hours ago", None),
    "Two Experimental Hops Earn Names. Introducing the Terra Alpha Hop Series": (
        13,
        "4 hours ago",
        None,
    ),
    "Beer Styles Discussion": (25, "4 hours ago", None),
    "Post a beer pic with your pet (2026)": (892, "5 hours ago", None),
    "Barleywine Appreciation Thread (2026)": (844, "5 hours ago", None),
    "The story behind those imploded Lagunitas Brewing fermentation tanks": (
        19,
        "6 hours ago",
        None,
    ),
    "Imperial Stout Is Life (2026)": (1976, "6 hours ago", None),
    "It's July! You know what that means? Märzens and Festbiers coming soon!": (
        389,
        "7 hours ago",
        None,
    ),
    "Exploding beer cans": (34, "7 hours ago", None),
    "Post a picture of your latest beer haul (2026)": (1585, "7 hours ago", None),
    "The Bitter Belt": (4, "7 hours ago", None),
    "What is that metallic flavor?": (34, "8 hours ago", None),
    "Cellared Beer Reviews (2026)": (305, "10 hours ago", None),
    "Divers find 162-year-old Guinness bottle off UK coast": (
        27,
        "10 hours ago",
        "Divers find 162-year-old Guinness bottle off UK coast, scientists hope to recreate historic beer",
    ),
    "IPA Appreciation Thread (2026)": (443, "11 hours ago", None),
    "German Style Beer Appreciation 2026": (350, "12 hours ago", None),
    "Let's Give Lagers Some Love (2026)": (251, "12 hours ago", None),
    "Smoke ‘Em If You Got ‘Em: Smoked Beer Appreciation Thread (2026)": (
        92,
        "17 hours ago",
        None,
    ),
    "Rogue Ales abruptly closes operations and restaurants": (
        253,
        "19 hours ago",
        "Rogue Ales abruptly closes operations and restaurants; owes hundreds of thousands in rent and taxes",
    ),
}
SOURCE_THREAD_IDS = dict(
    zip(
        forum_source_meta,
        (
            683974,
            682298,
            683971,
            683970,
            682326,
            682295,
            683972,
            682293,
            683623,
            683953,
            682296,
            683968,
            683962,
            682294,
            683906,
            682315,
            682737,
            682325,
            682364,
            681959,
        ),
        strict=True,
    )
)
SOURCE_THREAD_TITLES = {value: key for key, value in SOURCE_THREAD_IDS.items()}
SOURCE_THREAD_TITLES.update(
    {
        683623: "It's July! You know what that means? Marzens and Festbiers coming soon!",
        683979: "What beer are you drinking now? #5053",
        683941: "Labor Day Beer Festivities",
        683976: "Articles and Beer 101",
        683649: "Fall Beer Sightings 2026",
        683013: "What do you think of this new TekuMug?",
        683975: "I got a Tavour gift card - how do I best use it?",
        682371: "Porter Appreciation Thread (2026)",
        193134: "How to add beers on BeerAdvocate",
        681970: "FAQ: Places",
        670626: "Start a forum thread",
    }
)
SOURCE_THREAD_IDS.update(
    {title: thread_id for thread_id, title in SOURCE_THREAD_TITLES.items()}
)
forum_source_meta.update(
    {
        "It's July! You know what that means? Marzens and Festbiers coming soon!": (405, "2 minutes ago", None),
        "What beer are you drinking now? #5053": (16, "5 minutes ago", None),
        "Labor Day Beer Festivities": (7, "11 minutes ago", None),
        "The Bitter Belt": (5, "13 minutes ago", None),
        "Articles and Beer 101": (17, "45 minutes ago", None),
        "What is that metallic flavor?": (44, "51 minutes ago", None),
        "Rogue Ales abruptly closes operations and restaurants; owes hundreds of thousands of dollars in rent and taxes": (256, "1 hour ago", None),
        "Fall Beer Sightings 2026": (71, "1 hour ago", None),
        "What do you think of this new TekuMug?": (105, "3 hours ago", None),
        "I got a Tavour gift card - how do I best use it?": (5, "18 hours ago", None),
        "Porter Appreciation Thread (2026)": (132, "1 day ago", None),
    }
)
SOURCE_STYLES_PATH = Path(__file__).resolve().parent / "data" / "source_styles.json"
SOURCE_STYLE_ALIASES = {
    int(style_id): name
    for style_id, name in json.loads(SOURCE_STYLES_PATH.read_text(encoding="utf-8"))[
        "styles"
    ].items()
}
SOURCE_STONE_BEERS_PATH = Path(__file__).resolve().parent / "data" / "source_stone_beers.json"
SOURCE_STONE_BEERS = {
    int(beer_id): name
    for beer_id, name in json.loads(SOURCE_STONE_BEERS_PATH.read_text(encoding="utf-8"))[
        "beers"
    ].items()
}
SOURCE_STYLE_FAMILIES_PATH = (
    Path(__file__).resolve().parent / "data" / "source_style_families.json"
)
SOURCE_STYLE_FAMILIES = json.loads(
    SOURCE_STYLE_FAMILIES_PATH.read_text(encoding="utf-8")
)["families"]
SOURCE_FORUMS_PATH = Path(__file__).resolve().parent / "data" / "source_forums.json"
SOURCE_FORUMS = json.loads(SOURCE_FORUMS_PATH.read_text(encoding="utf-8"))["forums"]
SOURCE_STYLE_ID_BY_BEER_ID = {
    beer_id: style_id
    for beer_id, style_id in zip(
        (806254, 599268, 803735, 799121, 804818, 85094, 102, 741174, 782419, 1784),
        (235, 116, 140, 152, 116, 12, 29, 40, 78, 41),
        strict=True,
    )
}
SOURCE_STYLE_ID_BY_BEER_ID[1160] = 84
SOURCE_STYLE_ID_BY_BEER_ID[805781] = 245
name_leads = ["Midnight", "Copper", "Northern", "Old Harbor", "Quiet River", "Black Forest", "Golden", "Roasted", "Cinder", "Autumn", "Summit", "Wild Orchard"]
name_tails = ["Reserve", "Trail", "Lantern", "Current", "Cellar", "Crown", "Voyage", "Ember", "Harvest", "Signal", "Barrel", "Horizon", "Ridge", "Malt", "Grove", "Compass", "Bridge", "Roamer", "Vale", "Foundry"]
brewery_leads = ["North Coast", "Riverbend", "Copper Hill", "Old Town", "Highland", "Lakeside", "Red Oak", "Granite Peak", "Harbor", "Prairie", "Cedar", "Westfield"]
beers = []
for i in range(1, 241):
    if i <= len(featured):
        name, brewery, style, abv = featured[i - 1]
    else:
        style = styles[(i - len(featured) - 1) % len(styles)]
        name = f"{name_leads[(i - 1) % len(name_leads)]} {name_tails[(i - 1) // len(name_leads)]}"
        brewery = f"{brewery_leads[(i * 5) % len(brewery_leads)]} Brewing"
        abv = round(4.5 + (i % 80) / 10, 1)
    brewery_id, beer_id = (
        featured_routes[i - 1] if i <= len(featured_routes) else (1000 + i, 10000 + i)
    )
    beers.append({"id": i, "brewery_id": brewery_id, "beer_id": beer_id, "image_id": featured_image_ids[i - 1] if i <= len(featured_image_ids) else None, "name": name, "brewery": brewery, "style": style, "abv": abv, "score": 96 if i == 1 else 70 + (i % 30), "ratings": 8536 if i == 1 else 50 + i * 7, "reviews": 2820 if i == 1 else 10 + i * 3})

# Keep the frozen local catalog contract at forty Imperial Stout search results
# after adding the fresh R18 Cheese Crown observation.
beers[-1]["style"] = "American Imperial Stout"

beers_by_route = {(b["brewery_id"], b["beer_id"]): b for b in beers}
beers_by_id = {b["beer_id"]: b for b in beers}

places_data = [
    {"id": index, "name": name, "kind": kind, "city": city, "state": state, "rating": rating}
    for index, (name, kind, city, state, rating) in enumerate(
        [
            ("Stone Brewing World Bistro & Gardens", "Brewery", "Escondido", "CA", 4.31),
            ("Toronado", "Beer Bar", "San Francisco", "CA", 4.22),
            ("The Map Room", "Beer Bar", "Chicago", "IL", 4.18),
            ("Russian River Brewing Company", "Brewery", "Santa Rosa", "CA", 4.45),
            ("Hill Farmstead Brewery", "Brewery", "Greensboro", "VT", 4.58),
            ("The Avenue Pub", "Beer Bar", "New Orleans", "LA", 4.20),
            ("Belmont Station", "Bottle Shop", "Portland", "OR", 4.16),
            ("ChurchKey", "Beer Bar", "Washington", "DC", 4.24),
            ("The Ginger Man", "Beer Bar", "New York", "NY", 4.10),
            ("Brouwer's Cafe", "Beer Bar", "Seattle", "WA", 4.21),
            ("Jester King Brewery", "Brewery", "Austin", "TX", 4.37),
            ("Sergio's World Beers", "Beer Bar", "Louisville", "KY", 4.12),
        ],
        start=1,
    )
]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
STATIC_DIR = Path(__file__).resolve().parent / "static"
mimetypes.add_type("image/webp", ".webp")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

LOCAL_MEMBER_COOKIE = "__Host-websitebench-beeradvocate-session"
_SERVICES: tuple[SiteBackend, LocalAuthStore] | None = None
_SERVICES_LOCK = Lock()
_DATABASE_READY = False
_DATABASE_LOCK = Lock()
_REGISTRATION_LOCK = Lock()


@app.middleware("http")
async def enforce_same_origin_mutations(request: Request, call_next):
    response = None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        fetch_site = request.headers.get("sec-fetch-site")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != host:
                response = JSONResponse(
                    {"error": "cross-origin mutation rejected"}, status_code=403
                )
        elif fetch_site == "cross-site":
            response = JSONResponse(
                {"error": "cross-origin mutation rejected"}, status_code=403
            )
    if response is None:
        response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def services() -> tuple[SiteBackend, LocalAuthStore]:
    global _SERVICES
    if _SERVICES is None:
        with _SERVICES_LOCK:
            if _SERVICES is None:
                data_dir = os.environ.get("DATA_DIR")
                if data_dir:
                    os.environ.setdefault(
                        "WEBSITEBENCH_SITE_BACKEND_DATABASE",
                        str(Path(data_dir).resolve() / "beeradvocate.sqlite3"),
                    )
                _SERVICES = open_site_services()
    return _SERVICES


def database_path() -> Path:
    backend, _ = services()
    return backend.lifecycle.database_path


def _connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    return connection


def _initialize_database_unlocked() -> None:
    _, auth = services()
    auth.ensure_schema()
    connection = _connect_database()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            beer_id INTEGER NOT NULL,
            account_id TEXT NOT NULL,
            member TEXT NOT NULL,
            look INTEGER NOT NULL,
            smell INTEGER NOT NULL,
            taste INTEGER NOT NULL,
            feel INTEGER NOT NULL,
            overall INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    review_columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(reviews)").fetchall()
    }
    if "account_id" not in review_columns:
        connection.execute("ALTER TABLE reviews ADD COLUMN account_id TEXT")
    if "media_asset" not in review_columns:
        connection.execute("ALTER TABLE reviews ADD COLUMN media_asset TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """
        UPDATE reviews
        SET account_id = (
            SELECT MIN(account_id)
            FROM local_auth_accounts
            WHERE display_name = reviews.member COLLATE NOCASE
        )
        WHERE account_id IS NULL
          AND 1 = (
              SELECT COUNT(*)
              FROM local_auth_accounts
              WHERE display_name = reviews.member COLLATE NOCASE
          )
        """
    )
    connection.execute(
        "UPDATE reviews SET account_id = 'legacy-review-' || id WHERE account_id IS NULL"
    )
    connection.execute("DROP INDEX IF EXISTS reviews_member_beer")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS reviews_account_beer
        ON reviews (beer_id, account_id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forum_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forum_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    for table in ("forum_posts", "forum_replies", "submissions"):
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "account_id" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN account_id TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_helpful (
            review_id INTEGER NOT NULL,
            account_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (review_id, account_id),
            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_beers (
            account_id TEXT NOT NULL,
            beer_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (account_id, beer_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS followed_members (
            account_id TEXT NOT NULL,
            member_slug TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (account_id, member_slug)
        )
        """
    )
    seed_posts = [
        ("What Beer Are You Drinking Now? #5052", "Share a pour and tell us what is in your glass.", "MadMadMike", "The Bar"),
        ("Belgian Beer Appreciation Thread (2026)", "A long-running place for saisons, lambics, and tripels.", "mactrail", "The Bar"),
        ("Two Experimental Hops Earn Names. Introducing the Terra Alpha Hop Series", "Discuss current hop news and releases.", "2beerdogs", "Beer News"),
        ("Beer Styles Discussion", "Compare style guidelines and tasting notes.", "chrisjws", "Beer Talk"),
        ("Post a beer pic with your pet (2026)", "A community photo discussion.", "Argail", "The Bar"),
        ("Barleywine Appreciation Thread (2026)", "English and American barleywine tasting notes.", "Resistance88", "The Bar"),
        ("The story behind those imploded Lagunitas Brewing fermentation tanks", "Beer industry news and discussion.", "Oktoberfest", "Beer News"),
        ("Imperial Stout Is Life (2026)", "Dark malt, roast, and winter releases belong here.", "Resistance88", "The Bar"),
        ("It's July! You know what that means? Märzens and Festbiers coming soon!", "Seasonal lager releases and tasting notes.", "MrOH", "Beer Talk"),
        ("Exploding beer cans", "Packaging, storage, and fermentation discussion.", "Victory_Sabre1973", "Beer Talk"),
        ("Post a picture of your latest beer haul (2026)", "Share recent beer finds in this thread.", "TCgenny", "The Bar"),
        ("The Bitter Belt", "Regional breweries and bitter ale discussion.", "Spankyrightus", "Beer Talk"),
        ("What is that metallic flavor?", "Troubleshoot tasting notes and possible causes.", "Immortale25", "Beer Talk"),
        ("Cellared Beer Reviews (2026)", "How bottles change with time and storage.", "superspak", "The Bar"),
        ("Divers find 162-year-old Guinness bottle off UK coast", "Historical beer news and preservation.", "HouseofWortship", "Beer News"),
        ("IPA Appreciation Thread (2026)", "Hops, bitterness, aroma, and fresh releases.", "zotzot", "The Bar"),
        ("German Style Beer Appreciation 2026", "Lagers, wheat beer, and traditional styles.", "zotzot", "The Bar"),
        ("Let's Give Lagers Some Love (2026)", "Clean fermentation and crisp lager discussion.", "zotzot", "The Bar"),
        ("Smoke ‘Em If You Got ‘Em: Smoked Beer Appreciation Thread (2026)", "Rauchbier and smoked malt tasting notes.", "Mdog", "The Bar"),
        ("Rogue Ales abruptly closes operations and restaurants", "Industry news and community reaction.", "bambiere", "Beer News"),
    ]
    current_seed_posts = [
        ("It's July! You know what that means? Marzens and Festbiers coming soon!", "Seasonal lager releases and tasting notes.", "AlcahueteJ", "Beer Talk"),
        ("What beer are you drinking now? #5053", "Share the beer currently in your glass.", "The_Kriek_Freak", "The Bar"),
        ("Labor Day Beer Festivities", "Plans and beer picks for Labor Day.", "bambiere", "Beer Talk"),
        ("The Bitter Belt", "Regional bitter ale discussion.", "JackHorzempa", "Beer Talk"),
        ("Articles and Beer 101", "Beer education and article discussion.", "bambiere", "BeerAdvocate Talk"),
        ("What is that metallic flavor?", "Troubleshoot tasting notes and possible causes.", "VodkaPong87", "Beer Talk"),
        ("Rogue Ales abruptly closes operations and restaurants; owes hundreds of thousands of dollars in rent and taxes", "Industry news and community reaction.", "Billolick", "Beer News"),
        ("Fall Beer Sightings 2026", "Seasonal beer sightings.", "flaskman", "Beer Talk"),
        ("The story behind those imploded Lagunitas Brewing fermentation tanks", "Beer industry news and discussion.", "Bluecrow", "Beer News"),
        ("What do you think of this new TekuMug?", "Glassware and serving discussion.", "thebeers", "Beer Talk"),
        ("Post a picture of your latest beer haul (2026)", "Share recent beer finds in this thread.", "IMFletcher", "Beer Talk"),
        ("Cellared Beer Reviews (2026)", "How bottles change with time and storage.", "ChicagoJ", "The Bar"),
        ("Imperial Stout Is Life (2026)", "Dark malt, roast, and winter releases belong here.", "Whyteboar", "The Bar"),
        ("Post a beer pic with your pet (2026)", "A community photo discussion.", "MutuelsMark", "The Bar"),
        ("Barleywine Appreciation Thread (2026)", "English and American barleywine tasting notes.", "DIM", "The Bar"),
        ("I got a Tavour gift card - how do I best use it?", "Beer purchase suggestions.", "Domingo", "The Bar"),
        ("Exploding beer cans", "Packaging, storage, and fermentation discussion.", "moodenba", "Beer Talk"),
        ("IPA Appreciation Thread (2026)", "Hops, bitterness, aroma, and fresh releases.", "zotzot", "The Bar"),
        ("Beer Styles Discussion", "Compare style guidelines and tasting notes.", "Shanex", "BeerAdvocate Talk"),
        ("Porter Appreciation Thread (2026)", "Porter releases and tasting notes.", "LesDewitt4beer", "The Bar"),
    ]
    seed_posts = current_seed_posts + seed_posts
    existing_titles = {
        row[0] for row in connection.execute("SELECT title FROM forum_posts").fetchall()
    }
    missing_posts = [post for post in reversed(seed_posts) if post[0] not in existing_titles]
    connection.executemany(
        "INSERT INTO forum_posts (title, body, author, category, created_at) VALUES (?, ?, ?, ?, ?)",
        [(a, b, c, d, datetime.now(UTC).isoformat()) for a, b, c, d in missing_posts],
    )
    connection.commit()
    connection.close()


def initialize_database() -> None:
    global _DATABASE_READY
    if _DATABASE_READY:
        return
    with _DATABASE_LOCK:
        if not _DATABASE_READY:
            _initialize_database_unlocked()
            _DATABASE_READY = True


def open_database() -> sqlite3.Connection:
    initialize_database()
    return _connect_database()


def local_identity(cookie: str | None) -> dict[str, str] | None:
    if not cookie:
        return None
    _, auth = services()
    resolved = auth.resolve_session(cookie)
    if not resolved or not resolved.get("authenticated"):
        return None
    account = resolved.get("account") or {}
    account_id = str(account.get("account_id") or "")
    display_name = str(account.get("display_name") or "")
    if not account_id or not display_name:
        return None
    return {"account_id": account_id, "display_name": display_name}


def local_member(cookie: str | None) -> str | None:
    identity = local_identity(cookie)
    return identity["display_name"] if identity else None


def create_session(username: str) -> str:
    _, auth = services()
    token = auth.create_anonymous_session()
    result = auth.complete_externally_verified_registration(
        token,
        email=f"{secrets.token_hex(8)}@local.invalid",
        display_name=username,
        password=secrets.token_urlsafe(24),
    )
    return str(result["session_token"])


def session_response(path: str, username: str) -> RedirectResponse:
    response = RedirectResponse(path, status_code=303)
    response.set_cookie(LOCAL_MEMBER_COOKIE, create_session(username), httponly=True, secure=True, samesite="lax", path="/")
    return response


def with_session_cookie(response, token: str):
    response.set_cookie(LOCAL_MEMBER_COOKIE, token, httponly=True, secure=True, samesite="lax", path="/")
    return response


def ensure_local_session(cookie: str | None) -> tuple[str, dict]:
    _, auth = services()
    return auth.ensure_session(cookie)


def safe_local_path(value: str | None, fallback: str = "/") -> str:
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return fallback


def account_email_for_login(value: str) -> str:
    if "@" in value:
        return value
    _, auth = services()
    auth.ensure_schema()
    with auth.connect() as connection:
        row = connection.execute(
            "SELECT email_normalized FROM local_auth_accounts WHERE display_name = ? COLLATE NOCASE",
            (value.strip(),),
        ).fetchone()
    if row is None:
        return value
    return str(row["email_normalized"])


def display_name_in_use(auth, display_name: str, session_digest: str) -> bool:
    auth.ensure_schema()
    with auth.connect() as connection:
        return (
            connection.execute(
                """
                SELECT 1 FROM local_auth_accounts
                WHERE display_name = ? COLLATE NOCASE
                UNION ALL
                SELECT 1 FROM local_auth_registration_flows
                WHERE display_name = ? COLLATE NOCASE
                  AND session_digest <> ?
                  AND expires_at > ?
                LIMIT 1
                """,
                (
                    display_name.strip(),
                    display_name.strip(),
                    session_digest,
                    int(datetime.now(UTC).timestamp()),
                ),
            ).fetchone()
            is not None
        )


def test_login_enabled() -> bool:
    return os.environ.get("WEBSITEBENCH_ENABLE_TEST_LOGIN") == "1"


def beer_image_url(beer: dict[str, object]) -> str:
    image_id = beer.get("image_id")
    if image_id is not None:
        relative = Path("assets") / "beers" / f"{image_id}.jpg"
        if (STATIC_DIR / relative).is_file():
            return f"/static/{relative.as_posix()}"
    return "/static/assets/ui/c_beer_image.webp"

CSS = """
.source-slice{display:block;background-image:url('/static/assets/evidence/home-desktop.png');background-repeat:no-repeat;background-size:1425px 2909px}.slice-pils{background-position:-623px -1375px}.slice-kbs{background-position:-623px -1495px}
.nav .search-link{font-size:20px;padding:0 8px}.footer{min-height:315px}.footer-grid section p a{display:block;padding:7px 0;border-bottom:1px solid #373737}@media(max-width:700px){.footer{min-height:0}.footer-grid section{padding-bottom:28px}.footer-grid section p a{padding:10px 0}}
:root{--amber:#e9a400;--blue:#315f7e;--charcoal:#292929;--line:#dedede;--soft:#f4f4f4}*{box-sizing:border-box}html,body{min-height:100%}body{margin:0;background:#030303;color:#3e3e3e;font:13px Arial,Helvetica,sans-serif;line-height:1.35}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid #f5b51b;outline-offset:2px}.top{background:#030303;color:#fff}.header-shell{max-width:1170px;margin:auto;padding:14px 0 16px}.identity{display:flex;align-items:center;gap:16px;padding:0 3px 18px}.brand-logo{display:block;width:205px;height:40px;object-fit:contain}.brandmark{display:none;width:40px;height:40px}.tagline{color:#777;font-size:11px;letter-spacing:.25px}.nav{display:flex;align-items:stretch;min-height:41px}.nav a{display:flex;align-items:center;padding:0 14px;color:#ddd;font-size:12px;font-weight:700}.nav a.active{background:#292929}.nav .account{margin-left:auto}.nav .join{color:var(--amber);padding-left:4px}.subnav{display:flex;gap:24px;background:#292929;padding:12px 18px}.subnav a{color:#ccc;font-size:12px}.mobile-menu{display:none}.wrap{max-width:1170px;margin:0 auto 18px;background:#fff;min-height:2500px;padding:16px;display:flex;flex-direction:column;border-radius:3px}.content{flex:1}.crumbbar{height:41px;border:1px solid #e4e4e4;border-radius:3px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;color:#999}.crumbbar a{font-weight:700}.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px}.home-main{min-width:0}.home-cols{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);gap:16px}.home-panel{min-width:0}.home-panel .section-title{margin:0 0 10px}.home-panel-body{padding:5px 15px;font-size:14px}.home-intro h1{font-weight:400;font-size:24px;margin:26px 0 0}.home-intro p{margin:2px 0 8px;color:#777}.hero{background:#f2f2f2;padding:22px;border-left:4px solid var(--amber)}.hero h1{margin:0 0 8px;font-size:28px}.subscription{position:relative;background:#f1f1f1;padding:14px 68px 12px 78px;min-height:123px}.subscription .avatar-img{position:absolute;left:12px;top:18px;width:48px;height:48px;object-fit:cover;border-radius:3px}.subscription h2{font-size:15px;margin:2px 0}.subscription p{font-size:18px;line-height:1.2;margin:4px 0}.subscription .button{padding:6px 14px}.subscription .dismiss{position:absolute;right:10px;top:7px;color:#111;font-size:18px;font-weight:700}.notice-tabs{text-align:right;height:20px}.notice-tabs a{display:inline-block;padding:4px 7px;border:1px solid #e4e4e4;font-size:9px}.mobile-icon{display:none}.panel{border:1px solid var(--line);padding:14px;margin:14px 0;background:#fff}.section-title{background:#454545;color:#fff;padding:13px 14px;border-radius:4px;font-size:16px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}.beer{border:1px solid var(--line);padding:14px;min-height:145px}.beer:hover{border-color:#bdbdbd;box-shadow:0 2px 8px #0000000f}.card-beer-photo{float:left;width:42px;height:84px;object-fit:contain;margin:0 12px 6px 0}.beer-row{display:grid;grid-template-columns:52px minmax(0,1fr);gap:16px;padding:8px 6px;min-height:116px}.beer-photo{width:50px;height:100px;object-fit:contain}.beer-row strong,.discussion strong{display:block;color:#315f7e}.beer-row span a,.beer-row .muted a{color:inherit}.discussion{padding:8px 0}.discussion .meta{display:block;color:#777}.beer-detail-head{display:grid;grid-template-columns:120px minmax(0,1fr);gap:20px}.beer-detail-image{width:110px;height:220px;object-fit:contain;background:#fff}.score{font-size:24px;font-weight:700;color:#bc7f00}.muted{color:#777}.side{height:max-content}.side-box{border:1px solid var(--line);background:#fff;padding:9px;margin-bottom:16px;border-radius:3px}.side-box h3{background:#f8f8f8;border:1px solid #e7e7e7;padding:9px;margin:-1px -1px 10px;font-weight:400}.goal-box{border-left:3px solid #d97706}.goal-head{display:flex;align-items:center;gap:12px}.goal-icon{display:flex;width:36px;height:36px;align-items:center;justify-content:center;background:#d97706;color:#fff;border-radius:6px;font-size:18px}.goal-copy{font-size:12px;color:#666}.goal-copy b:first-child{display:block;color:#141414;font-size:13px}.stat{display:flex;justify-content:space-between;margin:3px 0}.progress{height:10px;background:#e2e8f0;border:1px solid #cbd5e1;border-radius:10px;overflow:hidden}.progress span{display:block;width:66.2%;height:100%;background:linear-gradient(90deg,#d97706,#f59e0b)}.find-beer input{padding:8px}.crumb{color:#777;font-size:12px;margin-bottom:14px}.check input{width:auto;margin-right:6px}.check{display:flex;align-items:center;gap:4px}label{display:block;font-weight:700;margin-top:8px}input,textarea,select{padding:10px;border:1px solid #bbb;margin:4px 0;width:100%;font:inherit;background:#fff}textarea{min-height:120px;resize:vertical}button,.button{display:inline-block;background:#46546a;color:#fff;border:0;border-radius:3px;padding:9px 15px;cursor:pointer;font-weight:700}button:hover,.button:hover{background:#303a49;text-decoration:none}.button.secondary{background:#777}.dimensions{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.pager{padding:18px 0}.page-link{display:inline-block;border:1px solid #ddd;padding:6px 9px;margin-right:3px}.page-link.current{background:#444;color:#fff}.forum-row{display:grid;grid-template-columns:minmax(0,1fr) 90px 155px;gap:12px;padding:13px 4px;border-bottom:1px solid #e6e6e6}.place-card .rating{color:#b77b00;font-size:18px;font-weight:700}.notice{background:#fff7da;padding:12px;border:1px solid #e6cd7a}.error{background:#fff0ef;color:#8b211b;border:1px solid #e0aaa5;padding:10px}.success{background:#eef8ec;color:#2d6326;border:1px solid #b7d7b1;padding:10px}.footer-shell{max-width:1170px;margin:0 auto}.footer{background:#282828;color:#bbb;padding:30px 32px;border-radius:3px}.footer-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:30px}.footer h3{color:#fff;font-size:15px}.footer p{font-size:12px;line-height:1.8}.footer a{color:#fff}.copyright{color:#fff;font-size:11px;margin:24px 5px 50px}.member-chip{display:flex;align-items:center;color:#fff;padding:0 8px;font-weight:700}
.mobile-join{display:none}.review-form{display:none}.review-form:target{display:block;scroll-margin-top:12px}.review-media{display:block;width:auto!important;height:180px!important;max-width:100%;object-fit:contain;margin:12px 0}.style-families{display:grid;grid-template-columns:1fr 1fr;gap:20px}.style-family{border:1px solid #eee;padding:10px;font-size:14px}.style-family h2{font-size:15px;margin:0 0 8px}.style-family ul{margin:0;padding-left:22px}.style-family li{padding:1px 0}.mobile-search{color:#eee;font-size:10px;padding:4px 0;text-decoration:none}.mobile-search:hover{text-decoration:underline}
.source-detail{font-family:'Open Sans',Arial,Helvetica,sans-serif}.source-detail-grid{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:18px}.source-detail-main{min-width:0}.source-join{min-height:108px;padding:16px 62px 14px 66px}.source-join h2{margin:0 0 2px;font-size:15px}.source-join p{margin:0 0 8px;font-size:17px;line-height:1.25}.source-join .avatar-img{width:48px;height:48px;top:24px}.source-title{margin:28px 0 20px}.source-title h1{font-size:24px;font-weight:400;line-height:1.25;margin:0}.source-title h1 span{color:#999;font-size:18px}.source-suggest{text-align:right;font-size:11px;font-weight:700;margin:-6px 0 4px}.source-overview{display:grid;grid-template-columns:100px minmax(0,1fr);gap:18px}.source-score-box{width:86px;height:86px;background:#050505;color:#fff;text-align:center;padding:8px 4px;font-weight:700}.source-score-box .score-number{display:block;color:#ffac00;font-size:31px;line-height:1.05}.source-beer-info{position:relative;min-height:365px;padding-right:190px}.source-main-image{position:absolute;right:4px;top:54px;width:150px;height:300px;object-fit:contain}.source-rate{display:inline-block;background:#22871d;color:#fff;padding:5px 8px 5px 6px;font-size:16px;font-weight:700;margin:5px 0 17px}.source-rate:hover{background:#196c16;text-decoration:none}.source-stats-title{font-weight:700;margin-bottom:8px}.source-beerstats{display:grid;grid-template-columns:150px minmax(0,1fr);margin:0;width:100%;font-size:12px}.source-beerstats dt,.source-beerstats dd{margin:0;padding:6px 0;border-bottom:1px solid #eee}.source-beerstats dt{color:#777;font-weight:700}.source-beerstats dd{font-weight:700}.source-beerstats dd span{color:#999;font-weight:400}.source-description{padding:8px 18px;font-size:13px;line-height:1.45}.source-review-heading{margin-top:500px;background:#f4f4f4;padding:12px 8px;font-size:14px}.source-tabs{border-bottom:1px solid #e5e5e5;margin-bottom:18px}.source-tabs span{display:inline-block;border:1px solid #e5e5e5;border-bottom:0;padding:10px 16px}.source-review-intro{margin:20px 0;font-weight:700}.source-review{display:grid;grid-template-columns:48px minmax(0,1fr);gap:18px;border-top:1px solid #e5e5e5;padding:16px 0;font-size:12px}.source-review img{width:48px;height:48px;object-fit:cover}.source-review .review-score{color:#c52014;font-size:19px;font-weight:700}.source-review .review-outof{color:#777;font-size:14px}.source-review .review-dev{font-size:12px}.source-review .review-dimensions{color:#888}.source-review .review-copy{font-size:14px;line-height:1.42;margin:18px 0}.source-review .review-date{color:#999}.source-review.local-review{background:#fffdf5;border:1px solid #e0c267;padding:16px;margin:12px 0}.source-detail-side .side-box{font-size:12px}.source-detail-side .goal-box{margin-top:0}
@media(max-width:700px){.header-shell{padding:8px}.identity{padding:0 0 8px}.brand-logo{display:block;width:205px}.brandmark,.tagline{display:none}.nav{display:none}.subnav{display:flex;gap:24px;padding:12px 10px;background:#030303;overflow-x:auto}.subnav a{white-space:nowrap;font-size:12px}.mobile-menu{display:block;background:#292929;padding:8px;font-size:10px}.mobile-menu summary{cursor:pointer;color:#eee;font-weight:700}.mobile-menu div{display:flex;gap:10px;flex-wrap:wrap;padding:8px 0}.mobile-menu a{color:#eee;font-size:10px}.wrap{padding:10px;min-height:5600px}.layout,.home-cols,.source-detail-grid{display:block}.style-families{grid-template-columns:1fr}.home-panel{margin-bottom:20px}.home-panel-body{padding:10px 15px}.side{margin-top:16px}.find-beer{display:none}.dimensions{grid-template-columns:repeat(2,1fr)}.hero{padding:16px}.hero h1{font-size:22px}.grid{grid-template-columns:1fr}.footer-shell{width:100%}.footer{border-radius:0;padding:30px 32px}.footer-grid{grid-template-columns:1fr;gap:10px;text-align:center}.copyright{white-space:nowrap;overflow:hidden;margin:24px 6px 40px}.beer{min-height:120px}.desktop-subscription{display:none}.mobile-join{display:block;padding:16px 12px 16px 78px;min-height:214px}.mobile-join .avatar-img{display:none}.mobile-icon{display:flex;position:absolute;left:10px;top:60px;width:49px;height:49px;align-items:center;justify-content:center;background:#fff;color:#e11d48;border-radius:4px;font-size:24px}.mobile-join h2{font-size:16px;text-align:center}.mobile-join p{font-size:18px;line-height:1.25}.forum-row{grid-template-columns:1fr}.forum-row .muted{display:inline}.crumbbar{margin-bottom:10px}.beer-detail-head{grid-template-columns:84px minmax(0,1fr);gap:12px}.beer-detail-image{width:78px;height:156px}.source-detail-side{display:none}.source-join{display:block;min-height:188px;padding:18px 14px 18px 70px}.source-title{margin:22px 0 12px}.source-title h1{font-size:22px}.source-title h1 span{font-size:16px}.source-overview{grid-template-columns:82px minmax(0,1fr);gap:10px}.source-score-box{width:76px;height:78px}.source-beer-info{padding-right:0;min-height:520px}.source-main-image{position:relative;right:auto;top:auto;width:130px;height:260px;display:block;margin:18px auto}.source-beerstats{grid-template-columns:105px minmax(0,1fr)}.source-review-heading{margin-top:260px}.source-review{grid-template-columns:38px minmax(0,1fr);gap:10px}.source-review img{width:38px;height:38px}}
.wrap{min-height:0!important}.home-surface{min-height:2400px}@media(max-width:700px){.wrap{min-height:0!important}.home-surface{min-height:5200px}.mobile-menu{background:#030303!important}.subnav{background:#292929!important}}
.subscription .button{background:#e91e63}.subscription .button:hover{background:#c2185b}.subscription.desktop-subscription{padding-left:78px}.subscription.desktop-subscription .mobile-icon{display:flex;position:absolute;left:10px;top:38px;width:49px;height:49px;align-items:center;justify-content:center;background:#fff;color:#e91e63;border-radius:4px;font-size:24px}@media(max-width:700px){.subscription.desktop-subscription .mobile-icon{display:none}}
"""

def page(
    title: str,
    body: str,
    member: str | None = None,
    active_section: str | None = None,
) -> HTMLResponse:
    title_lower = title.lower()
    if active_section is not None:
        inferred_section = active_section
    elif any(word in title_lower for word in ("about", "contact", "follow", "privacy", "terms", "code of conduct")):
        inferred_section = "home"
    elif any(word in title_lower for word in ("forum", "thread", "community", "what's new")):
        inferred_section = "forums"
    elif "place" in title_lower:
        inferred_section = "places"
    elif "society" in title_lower:
        inferred_section = "society"
    elif any(word in title_lower for word in ("beer", "stone", "brewery")) and title != "BeerAdvocate":
        inferred_section = "beers"
    else:
        inferred_section = "home"
    active_section = inferred_section
    nav_items = (
        ("home", "/", "HOME"),
        ("forums", "/community/", "FORUMS"),
        ("beers", "/beer/", "BEERS"),
        ("places", "/place/", "PLACES"),
        ("society", "/society/", "SOCIETY"),
    )
    links = "".join(
        f"<a class='{'active' if key == active_section else ''}' href='{href}'>{label}</a>"
        for key, href, label in nav_items
    )
    account = f"<a class='member-chip' href='/community/account/'>{html.escape(member)}</a><a class='account' href='/community/logout/'>LOG OUT</a>" if member else "<a class='account' href='/community/login/'>LOG IN / <span class='join'>JOIN</span></a>"
    mobile_account_label = html.escape(member) if member else "LOG IN / JOIN"
    search_link = "<a class='search-link' href='/search/' aria-label='Search'>⌕</a>"
    subnav_items = {
        "home": (("/community/whats-new/", "What's New"), ("/about/", "About"), ("/contact/", "Contact"), ("/follow", "Follow")),
        "beers": (("/data/?action=add_beer", "Add Beer"), ("/beer/styles/", "Styles"), ("/trading/", "Trading"), ("/beer/top-rated/", "Top Rated")),
        "forums": (("/community/whats-new/", "What's New"), ("/community/", "Forums"), ("/community/find-new/posts", "Recent Posts"), ("/community/new-thread/", "Start a Thread")),
        "places": (("/data/?action=add_place", "Add Place"), ("/place/directory/", "Directory"), ("/place/visits/", "Visits")),
        "society": (("/society/", "Membership"), ("/community/forums/beeradvocate-society.60/", "Society Forum")),
    }.get(active_section, ())
    subnav = "<nav class='subnav'>" + "".join(
        f"<a href='{href}'>{label}</a>" for href, label in subnav_items
    ) + "</nav>"
    footer = "<footer class='footer'><div class='footer-grid'><section><h3>About</h3><p>Founded in 1996, BeerAdvocate (BA) is the oldest and largest independent beer community. Guided by our motto, Respect Beer®, we're the go-to beer resource for millions, the benchmark for beer reviews, and the voice of the beer geek.</p><p><a href='/about/'>Learn more...</a></p></section><section><h3>Contribute</h3><p><a href='/data/?action=add_beer'>Add a Beer</a><br><a href='/data/?action=add_place'>Add a Place</a><br><a href='/community/new-thread/'>Start a Thread</a><br><a href='/society/'>Support BeerAdvocate</a></p></section><section><h3>Fun</h3><p><a href='/follow'>Discord</a><br><a href='/follow'>Follow @BeerAdvocate</a><br><a href='/community/forums/the-bar.68/'>The Bar</a><br><a href='/community/find-new/posts'>What's New</a></p></section><section><h3>Whatnot</h3><p><a href='/community/terms/'>Terms of Service</a><br><a href='/community/privacy/'>Privacy &amp; Cookie Policy</a><br><a href='/community/code-of-conduct/'>Code of Conduct</a></p></section></div></footer><div class='copyright'><p>Copyright © 1996-2026 BeerAdvocate®. All rights reserved. Respect Beer®.</p><p>Information from your device can be used to personalize your ad experience.</p><p><a href='/privacy/'>Do not sell or share my personal information.</a><br><a href='/terms/'>Terms of Content Use</a><br>A RAPTIVE PARTNER SITE</p></div>"
    identity = "<a href='/' aria-label='BeerAdvocate home'><img class='brand-logo' src='/static/assets/brand/beeradvocate-nav-logo.webp' alt='BeerAdvocate'><img class='brandmark' src='/static/assets/brand/beeradvocate-nav-brandmark.webp' alt='BeerAdvocate'></a><span class='tagline'>RATE. TALK. RESPECT. BEER.</span>"
    lower_crumb = "<div class='crumbbar lower-crumb'><a href='/'>⌂</a><span><a href='/'>Home</a>&nbsp;&nbsp; <a href='/contact/'>Contact</a>&nbsp;&nbsp; ♟</span></div>"
    return HTMLResponse(f"<!doctype html><html lang='en-US'><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='icon' href='/static/assets/brand/beeradvocate-nav-brandmark.png' type='image/png'><title>{html.escape(title)}</title><style>{CSS}</style></head><body><header class='top'><div class='header-shell'><div class='identity'>{identity}</div><nav class='nav'>{links}{account}{search_link}</nav><details class='mobile-menu'><summary>☰ MENU &nbsp; | &nbsp; {mobile_account_label} &nbsp; | &nbsp; ⌕</summary><div>{links}{account}<a class='mobile-search' href='/search/' aria-label='Search'>Search</a></div></details>{subnav}</div></header><main class='wrap'><div class='crumbbar'><a href='/'>⌂</a><span>♟</span></div><div class='content'>{body}</div>{lower_crumb}</main><div class='footer-shell'>{footer}</div></body></html>")

@app.get('/healthz')
def healthz(): return JSONResponse({"ok": True, "site_id": SITE_ID})

@app.get('/__websitebench/health')
def websitebench_health(): return JSONResponse({"status": "ok"})

@app.get('/')
def home(
    subscription: str = Query("visible"),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    trending_parts = []
    fresh_trending_indexes = (1, 2, 5, 4, 6, 3, 7, 11, 10, 8)
    for beer in (beers[index] for index in fresh_trending_indexes):
        route = f"/beer/profile/{beer['brewery_id']}/{beer['beer_id']}/"
        brewery_route = f"/beer/profile/{beer['brewery_id']}/"
        style_id = SOURCE_STYLE_ID_BY_BEER_ID[int(beer["beer_id"])]
        style_route = f"/beer/top-styles/{style_id}/"
        image_id = beer.get("image_id")
        if image_id in {741174, 782419} and not (
            STATIC_DIR / "assets" / "beers" / f"{image_id}.jpg"
        ).is_file():
            slice_class = "slice-pils" if image_id == 741174 else "slice-kbs"
            image_markup = (
                f"<span class='beer-photo source-slice {slice_class}' role='img' "
                f"aria-label='{html.escape(beer['name'])}'></span>"
            )
        else:
            image_markup = (
                f"<img class='beer-photo' src='{beer_image_url(beer)}' "
                f"alt='{html.escape(beer['name'])}'>"
            )
        trending_parts.append(
            f"<div class='beer-row'><a href='{route}'>{image_markup}</a>"
            f"<div><a href='{route}'><strong>{html.escape(beer['name'])}</strong></a>"
            f"<span><a href='{style_route}'>{html.escape(beer['style'])}</a> | "
            f"{beer['abv']:g}%</span><div class='muted'><a href='{brewery_route}'>"
            f"{html.escape(beer['brewery'])}</a></div></div></div>"
        )
    trending = "".join(trending_parts)
    with open_database() as connection:
        rows = connection.execute(
            "SELECT id, title, author, category FROM forum_posts ORDER BY id DESC LIMIT 20"
        ).fetchall()
    discussion_parts = []
    for row in rows:
        replies, activity, display_title = forum_source_meta.get(
            row["title"], (0, "just now", None)
        )
        title = display_title or row["title"]
        source_thread_id = SOURCE_THREAD_IDS.get(row["title"])
        thread_href = (
            f"/community/threads/{source_thread_id}/unread"
            if source_thread_id is not None
            else f"/community/thread/{row['id']}/"
        )
        discussion_parts.append(
            f"<div class='discussion'><a href='{thread_href}'>"
            f"<strong>{html.escape(title)}</strong></a><span class='meta'>"
            f"replies: {replies} | {activity} by {html.escape(row['author'])}</span>"
            f"<span class='muted'>{html.escape(row['category'])}</span></div>"
        )
    discussions = "".join(discussion_parts)
    banners = ""
    if subscription != "hidden":
        banners = "<section class='subscription desktop-subscription'><span class='mobile-icon' aria-hidden='true'>♟</span><h2>Join the BeerAdvocate Community!</h2><p>Create your free account now to <b>rate, talk, and respect beer</b> with thousands of fellow beer geeks. You'll <b>see fewer ads</b> too.</p><a class='button' href='/community/register/'>Create Free Account</a><a class='dismiss' href='/?subscription=hidden' aria-label='Dismiss Notice'>×</a></section><section class='subscription mobile-join'><span class='mobile-icon' aria-hidden='true'>♟</span><h2>Join the BeerAdvocate Community!</h2><p>Create your free account now to <b>rate, talk, and respect beer</b> with thousands of fellow beer geeks. You'll <b>see fewer ads</b> too.</p><a class='button' href='/community/register/'>Create Free Account</a><a class='dismiss' href='/?subscription=hidden' aria-label='Dismiss Notice'>×</a></section><div class='notice-tabs'><a href='/community/register/'>Join BA</a><a href='/community/whats-new/'>News</a></div>"
    body = f"<div class='home-surface layout'><section class='home-main'>{banners}<section class='home-intro'><h1>Rate. Talk. Respect. Beer.</h1><p>Fresh beer takes from BeerAdvocate members around the globe.</p></section><section class='home-cols'><div class='home-panel'><h2 class='section-title'>☁ &nbsp; Join the Discussion!</h2><div class='home-panel-body'>{discussions}<p><a href='/community/'>More from the Forums...</a></p></div></div><div class='home-panel'><h2 class='section-title'>↗ &nbsp; Trending Beers</h2><div class='home-panel-body'>{trending}<p><a href='/beer/'>More Trending Beers...</a></p></div></div></section></section><aside class='side'><div class='side-box goal-box'><a class='goal-head' href='/society/'><span class='goal-icon'>⚑</span><span class='goal-copy'><b>Goal: The Mayor</b><strong>331</strong> / 500 | <b>66.2%</b></span></a><div class='progress'><span></span></div><p class='muted' style='text-align:center'><b>169</b> more subs needed to unlock <b>The Mayor</b>!</p></div><div class='side-box find-beer'><h3>Find a Beer</h3><form action='/search/' method='get'><input type='search' aria-label='Beer name' name='q' placeholder='Type the name and hit enter'></form></div><div class='side-box'><h3>Forum Stats</h3><p class='stat'><span>Discussions:</span><span>262,376</span></p><p class='stat'><span>Posts:</span><span>7,171,628</span></p><p class='stat'><span>Members:</span><span>804,624</span></p><p class='stat'><span>Latest Member:</span><a href='/community/'>Dabernet</a></p></div><div class='side-box'><h3>Beer Stats</h3><p class='stat'><span>Total Beers:</span><span>776,312</span></p><p class='stat'><span>Active Beers:</span><span>594,877</span></p><p class='stat'><span>Ratings:</span><span>11,064,724</span></p><p class='stat'><span>Reviews:</span><span>3,486,225</span></p><p class='stat'><span>Avg Rating:</span><span>3.83</span></p><p class='stat'><span>Unique Raters (30d):</span><span>1,419</span></p></div><div class='side-box'><h3>Place Stats</h3><p class='stat'><span>Places:</span><span>53,174</span></p><p class='stat'><span>Breweries:</span><span>22,828</span></p><p class='stat'><span>Ratings:</span><span>403,590</span></p><p class='stat'><span>Reviews:</span><span>203,824</span></p><p class='stat'><span>Approval Queue:</span><span>2</span></p></div></aside></div>"
    return page('BeerAdvocate', body, local_member(ba_local_member))

@app.get('/beer/')
def beer_index(
    q: str = Query('', alias='q'),
    page_num: int = Query(1, alias='page'),
    sort: str = Query('score'),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
    view: str = Query('recent'),
):
    if not q and page_num == 1 and sort == 'score' and view in {'recent', 'top'}:
        visible_feed = sorted(
            beers[:50],
            key=lambda beer: beer['score'],
            reverse=view == 'top',
        )
        rows = "".join(
            f"<article class='source-review'><img src='/static/assets/ui/avatar_s.webp' "
            f"alt=''><div><a href='/beer/profile/{beer['brewery_id']}/"
            f"{beer['beer_id']}/'><strong>{html.escape(beer['name'])}</strong></a> "
            f"<span class='muted'><a href='/beer/styles/"
            f"{SOURCE_STYLE_ID_BY_BEER_ID.get(int(beer['beer_id']), 84)}/'>"
            f"{html.escape(beer['style'])}</a> | {beer['abv']:g}%<br>"
            f"<a href='/beer/profile/{beer['brewery_id']}/'>"
            f"{html.escape(beer['brewery'])}</a></span><br><br>"
            f"<span class='review-score'>{beer['score'] / 20:.2f}</span>"
            f"<span class='review-outof'>/5</span> <span class='review-dev'>"
            f"rDev {(beer['id'] % 11) - 5:+d}.0%</span><div class='review-dimensions'>"
            "look: 4.25 | smell: 4.25 | taste: 4.5 | feel: 4.25 | overall: 4.5"
            "</div><div class='review-copy'>A public review preserving the "
            "source rating-feed structure and link depth.</div><span class='review-date'>"
            "Recent public rating</span></div></article>" for beer in visible_feed
        )
        body = (
            "<div class='layout'><section><div class='crumb'>Home / Beers</div>"
            "<h1>Beer Ratings: Recent</h1><div class='source-tabs'>"
            f"<a href='/beer/?view=recent' class='page-link {'current' if view == 'recent' else ''}'>Recent</a>"
            f"<a href='/beer/?view=top' class='page-link {'current' if view == 'top' else ''}'>Top Rated</a>"
            f"</div>{rows}</section><aside class='side'><div class='side-box goal-box'>"
            "<h3>Goal: The Mayor</h3><div class='progress'><span></span></div></div>"
            "<div class='side-box find-beer'><h3>Find a Beer</h3><form action='/search/'>"
            "<input name='q' placeholder='Type the name and hit enter'></form></div>"
            "<div class='side-box'><h3>Learn to Rate Beer</h3><p>Review appearance, "
            "aroma, taste, mouthfeel, and overall impression.</p></div></aside></div>"
        )
        return page('Beer Ratings: Recent | BeerAdvocate', body, local_member(ba_local_member))
    items = [b for b in beers if not q or q.lower() in (b['name'] + b['style'] + b['brewery']).lower()]
    if sort not in {"score", "ratings", "name"}:
        sort = "score"
    if sort == 'name':
        items.sort(key=lambda item: item['name'])
    elif sort == 'ratings':
        items.sort(key=lambda item: item['ratings'], reverse=True)
    else:
        items.sort(key=lambda item: item['score'], reverse=True)
    page_num = max(1, page_num)
    total_pages = max(1, (len(items) + 23) // 24)
    page_num = min(page_num, total_pages)
    visible = items[(page_num - 1) * 24:page_num * 24]
    cards = ''.join(f"<div class='beer'><a href='/beer/profile/{b['brewery_id']}/{b['beer_id']}/'><img class='card-beer-photo' src='{beer_image_url(b)}' alt='{html.escape(b['name'])}'><strong>{html.escape(b['name'])}</strong></a><div>{html.escape(b['brewery'])}</div><div>{html.escape(b['style'])} · {b['abv']}%</div><div class='score'>{b['score']}</div><div class='muted'>{b['ratings']:,} ratings</div></div>" for b in visible)
    pager = ''.join(
        f"<a class='page-link {'current' if n == page_num else ''}' "
        f"href='/beer/?{html.escape(urlencode({'q': q, 'sort': sort, 'page': n}))}'>{n}</a>"
        for n in range(1, total_pages + 1)
    )
    body = f"<div class='crumb'>Home / Beers</div><div class='hero'><h1>Beers</h1><p>Browse recent ratings and reviews.</p><form method='get' action='/beer/'><input name='q' value='{html.escape(q)}' placeholder='Search beers'><select name='sort'><option value='score' {'selected' if sort == 'score' else ''}>Top score</option><option value='ratings' {'selected' if sort == 'ratings' else ''}>Most ratings</option><option value='name' {'selected' if sort == 'name' else ''}>Name</option></select><button>Search</button></form></div><div class='panel'><p>{len(items)} beers found · page {page_num} of {total_pages}</p><div class='grid'>{cards or '<p class=notice>No beers found. Try a brewery, style, or shorter name.</p>'}</div><div class='pager'>{pager}</div></div>"
    return page('Beers | BeerAdvocate', body, local_member(ba_local_member))

@app.get('/search/')
def search(
    q: str = '',
    search_type: str = Query('beer', alias='type'),
    active: str | None = None,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    del active
    if search_type == 'place':
        return places(q, '', ba_local_member)
    matches = [
        beer for beer in beers
        if not q or q.casefold() in (
            beer['name'] + beer['style'] + beer['brewery']
        ).casefold()
    ]
    rows = "".join(
        f"<article class='beer-row'><a href='/beer/profile/{beer['brewery_id']}/"
        f"{beer['beer_id']}/'><img class='beer-photo' src='{beer_image_url(beer)}' "
        f"alt='{html.escape(beer['name'])}'></a><div><a href='/beer/profile/"
        f"{beer['brewery_id']}/{beer['beer_id']}/'><strong>"
        f"{html.escape(beer['name'])}</strong></a><span><a href='/beer/profile/"
        f"{beer['brewery_id']}/'>{html.escape(beer['brewery'])}</a></span>"
        f"<span class='muted'>{html.escape(beer['style'])} | {beer['abv']:g}%</span>"
        f"<span class='score'>{beer['score']}</span> <span class='muted'>"
        f"{beer['ratings']:,} ratings</span></div></article>" for beer in matches[:10]
    )
    body = (
        "<div class='layout'><section><div class='crumb'>Home / Search</div>"
        f"<h1>Search: {html.escape(q)}</h1><div class='source-tabs'>"
        f"<a href='/community/search/?type=post&q={html.escape(q)}'>Forums</a>"
        f"<a href='/search/?q={html.escape(q)}'>Beers</a>"
        f"<a href='/search/?type=place&q={html.escape(q)}'>Places</a>"
        f"<a href='/articles/?s={html.escape(q)}'>Articles</a></div>"
        "<form method='get' action='/search/'><input name='q' value='"
        f"{html.escape(q)}'><label class='check'><input type='checkbox' name='active' "
        "value='1' checked>Exclude retired/closed listings</label><button>Search"
        f"</button></form><div class='panel'><h2>Beers Found: {len(matches)}</h2>"
        f"<p>{len(matches)} beers found. Anonymous results "
        f"are limited to the first 10.</p>{rows or '<p>No beers found.</p>'}</div>"
        "</section><aside class='side'><div class='side-box goal-box'><h3>Goal: "
        "The Mayor</h3><div class='progress'><span></span></div></div><div "
        "class='side-box find-beer'><h3>Find a Beer</h3></div></aside></div>"
    )
    return page(f"Search: {q} | BeerAdvocate", body, local_member(ba_local_member))

@app.get('/beer/styles/')
def styles_page(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    families = "".join(
        f"<section class='style-family'><h2>{html.escape(family)}</h2><ul>"
        + "".join(
            f"<li><a href='/beer/styles/{style_id}/'>"
            f"{html.escape(SOURCE_STYLE_ALIASES[int(style_id)])}</a></li>"
            for style_id in style_ids
        )
        + "</ul></section>"
        for family, style_ids in SOURCE_STYLE_FAMILIES.items()
    )
    return page(
        'Beer Styles | BeerAdvocate',
        "<div class='layout'><section><div class='crumb'>Home / Beers / Styles"
        "</div><h1>Beer Styles</h1><p class='muted'>Learn more about the wonderful "
        "world of beer styles.</p><p>Simply put, a beer style is a label given to a "
        "beer that describes its overall character and, oftentimes, its place of "
        "origin. Use these styles as a guide when reviewing appearance, aroma, "
        "taste, and feel.</p>"
        f"<div class='style-families'>{families}</div></section><aside class='side'>"
        "<div class='side-box goal-box'><h3>Goal: The Mayor</h3><div class='progress'>"
        "<span></span></div></div><div class='side-box'><h3>What's an Ale?</h3>"
        "<p>Ales use warm-fermenting yeast and include many expressive families."
        "</p></div><div class='side-box'><h3>What's a Lager?</h3><p>Lagers use "
        "cool fermentation and maturation.</p></div><div class='side-box'><h3>"
        "Learn to Rate Beer</h3><p>Appearance, aroma, taste, feel, and overall."
        "</p></div></aside></div>",
        local_member(ba_local_member),
    )

@app.get('/beer/styles/{style_id}/')
def style_detail(style_id: int, ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    style = SOURCE_STYLE_ALIASES.get(style_id)
    if style is None:
        raise HTTPException(status_code=404, detail='Style not found')
    style_beers = [beer for beer in beers if beer['style'] == style]
    cards = ''.join(f"<div class='beer'><a href='/beer/profile/{beer['brewery_id']}/{beer['beer_id']}/'><strong>{html.escape(beer['name'])}</strong></a><p>{html.escape(beer['brewery'])}</p><span class='score'>{beer['score']}</span><span class='muted'> · {beer['ratings']:,} ratings</span></div>" for beer in style_beers[:12])
    body = f"<div class='crumb'>Home / Beers / Styles / {html.escape(style)}</div><div class='hero'><h1>{html.escape(style)}</h1><p>Ratings and reviews for this style.</p><a class='button' href='/beer/?q={html.escape(style)}'>Browse all {len(style_beers)}</a></div><div class='panel'><div class='grid'>{cards}</div></div>"
    return page(f'{style} | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/beer/top-styles/{style_id}/')
def source_style_detail(
    style_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    return style_detail(style_id, ba_local_member)

def ranked_beers_page(
    heading: str,
    ordering: str,
    member_cookie: str | None,
) -> HTMLResponse:
    ranked = list(beers)
    if ordering == 'new':
        ranked.reverse()
    elif ordering == 'popular':
        ranked.sort(key=lambda beer: beer['ratings'], reverse=True)
    elif ordering == 'worst':
        ranked.sort(key=lambda beer: beer['score'])
    elif ordering == 'fame':
        ranked.sort(key=lambda beer: (beer['score'], beer['ratings']), reverse=True)
    else:
        ranked.sort(key=lambda beer: beer['score'], reverse=True)
    tabs = (
        ("/beer/top-rated/", "Top 250"),
        ("/beer/top-styles/", "Styles"),
        ("/beer/trending/", "Trending"),
        ("/beer/top-new/", "New"),
        ("/beer/fame/", "Fame"),
        ("/beer/popular/", "Popular"),
        ("/beer/worst/", "Worst"),
    )
    tab_markup = "".join(
        f"<a class='page-link' href='{href}'>{label}</a>" for href, label in tabs
    )
    rows = "".join(
        f"<tr><td>{rank}</td><td><a href='/beer/profile/{beer['brewery_id']}/"
        f"{beer['beer_id']}/'><strong>{html.escape(beer['name'])}</strong></a>"
        f"<br><a href='/beer/profile/{beer['brewery_id']}/'>"
        f"{html.escape(beer['brewery'])}</a><br><a href='/beer/top-styles/"
        f"{SOURCE_STYLE_ID_BY_BEER_ID.get(int(beer['beer_id']), 84)}/'>"
        f"{html.escape(beer['style'])}</a> | {beer['abv']:g}%</td>"
        f"<td>{beer['ratings']:,}</td><td>{beer['score'] / 20:.2f}</td>"
        "<td>—</td></tr>" for rank, beer in enumerate(ranked, 1)
    )
    body = (
        "<div class='layout'><section><div class='crumb'>Home / Beers / Rankings"
        f"</div><h1>{html.escape(heading)}</h1><div class='source-tabs'>"
        f"{tab_markup}</div><form method='get'><label>Country<select name='c_id'>"
        "<option value=''>All countries</option><option value='US'>United States"
        "</option></select></label><button>Apply</button></form><div class='panel'>"
        "<table style='width:100%;border-collapse:collapse'><thead><tr><th>#</th>"
        "<th>Beer</th><th>Ratings</th><th>Avg</th><th>You</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section><aside class='side'>"
        "<div class='side-box goal-box'><h3>Goal: The Mayor</h3><div class='progress'>"
        "<span></span></div></div><div class='side-box'><h3>Learn to Rate Beer</h3>"
        "<p>Use the five observed scoring dimensions.</p></div></aside></div>"
    )
    return page(f'{heading} | BeerAdvocate', body, local_member(member_cookie))


@app.get('/beer/top-rated/')
def top_rated(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return ranked_beers_page('Top 250 Rated Beers', 'score', ba_local_member)


@app.get('/beer/top-new/')
def top_new(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return ranked_beers_page('Top New Beers', 'new', ba_local_member)


@app.get('/beer/fame/')
def fame(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return ranked_beers_page('Beers of Fame', 'fame', ba_local_member)


@app.get('/beer/popular/')
def popular(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return ranked_beers_page('Popular Beers', 'popular', ba_local_member)


@app.get('/beer/worst/')
def worst(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return ranked_beers_page('Worst Rated Beers', 'worst', ba_local_member)


@app.get('/beer/top-styles/')
def top_styles(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return styles_page(ba_local_member)

@app.get('/beer/profile/{brewery_id}/{beer_id}/')
def detail(brewery_id: int, beer_id: int, ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    b = beers_by_route.get((brewery_id, beer_id))
    if b is None:
        observed_name = SOURCE_STONE_BEERS.get(beer_id) if brewery_id == 147 else None
        if observed_name is not None:
            body = (
                "<div class='source-detail'><div class='crumb'>Home / Beers / "
                "<a href='/beer/profile/147/'>Stone Brewing</a></div>"
                f"<div class='source-title'><h1>{html.escape(observed_name)} "
                "<span>Stone Brewing</span></h1></div><div class='layout'><section>"
                "<div class='source-score-box'><span>SCORE</span><span "
                "class='score-number'>—</span><span>Not frozen</span></div>"
                "<div class='panel'><h2>Beer Geek Stats</h2><p>This observed "
                "Stone beer keeps its source route and title. Detailed rating facts "
                "were not frozen, so additional details are not shown.</p><p><a href='"
                f"/beer/profile/147/'>View all {len(SOURCE_STONE_BEERS)} observed "
                "Stone beers</a></p></div></section><aside class='side'><div "
                "class='side-box'><h3>Stone Brewing</h3><p>Escondido, California"
                "</p></div></aside></div></div>"
            )
            return page(
                f"{observed_name} | Stone Brewing | BeerAdvocate",
                body,
                local_member(ba_local_member),
                active_section="beers",
            )
        raise HTTPException(status_code=404, detail="Beer not found")
    identity = local_identity(ba_local_member)
    with open_database() as connection:
        rows = connection.execute(
            "SELECT r.*, (SELECT COUNT(*) FROM review_helpful h WHERE h.review_id = r.id) "
            "AS helpful_count FROM reviews r WHERE r.beer_id = ? ORDER BY r.id DESC",
            (beer_id,),
        ).fetchall()
    local_review_parts = []
    for row in rows:
        media = ""
        if row["media_asset"] in REVIEW_MEDIA_ASSETS and row["media_asset"]:
            media = (
                f"<img class='review-media' src='/static/assets/"
                f"{html.escape(row['media_asset'])}' alt='Attached beer photo'>"
            )
        owner_controls = ""
        if identity is not None and row["account_id"] == identity["account_id"]:
            owner_controls = (
                f"<p><a href='/beer/review/{row['id']}/edit/'>Edit review</a></p>"
                f"<form method='post' action='/beer/review/{row['id']}/delete/'><button "
                "class='secondary' type='submit'>Delete review</button></form>"
            )
        helpful_action = (
            f"<form method='post' action='/beer/review/{row['id']}/helpful/'><button "
            f"class='secondary' type='submit'>Helpful ({row['helpful_count']})</button></form>"
            if identity is not None
            else f"<a href='/community/login/?redirect=%2Fbeer%2Fprofile%2F{brewery_id}%2F{beer_id}%2F'>Helpful ({row['helpful_count']})</a>"
        )
        local_review_parts.append(
            f"<article class='panel source-review local-review'><img src='/static/assets/ui/avatar_s.webp' alt=''><div>"
            f"<span class='muted'>Reviewed by <b>{html.escape(row['member'])}</b></span><br><br>"
            f"<span class='review-score'>{format_review_score(row['overall'])}</span><span class='review-outof'>/5</span><br>"
            f"<span class='review-dimensions'>look: {format_review_score(row['look'])} | smell: {format_review_score(row['smell'])} | "
            f"taste: {format_review_score(row['taste'])} | feel: {format_review_score(row['feel'])} | overall: {format_review_score(row['overall'])}</span>"
            f"<div class='review-copy'>{html.escape(row['comment'])}</div>{media}<span class='review-date'>"
            f"{html.escape(row['member'])}</span>{helpful_action}{owner_controls}</div></article>"
        )
    local_reviews = "".join(local_review_parts)
    observed_reviews = (
        ("avatar_s.webp", "Alex_444666", "Nevada", "4.49", "+3.7%", "4.75 | smell: 4.5 | taste: 4.5 | feel: 4.75 | overall: 4.25", "Very good", "Jun 24, 2026"),
        ("avatar_female_s.webp", "alex_green", "Canada (ON)", "4.32", "-0.2%", "4.25 | smell: 4 | taste: 4.5 | feel: 4 | overall: 4.5", "Rich malt, roasty aroma, full body.", "May 12, 2026"),
        ("avatar_female_s.webp", "Alex-Green", "Canada (ON)", "4.32", "-0.2%", "4.25 | smell: 4 | taste: 4.5 | feel: 4 | overall: 4.5", "Rich malt, roasty aroma, full body.", "May 08, 2026"),
        ("983-983916.jpg", "The_Snow_Bird", "Michigan", "4.3", "-0.7%", "5 | smell: 5 | taste: 4 | feel: 4 | overall: 4", "Pours thick jet black with a very dark caramel head. Strong smell of dark fruit and molasses. Taste of roasted malts along with dark fruits and a light coffee finish.", "Oct 26, 2025"),
        ("1224-1224615.jpg", "JamarcusMarinovich", "California", "4.69", "+8.3%", "4.75 | smell: 4.5 | taste: 4.75 | feel: 4.75 | overall: 4.75", "Unpretentiously poured into a pint glass, a dark almost black with tan one-finger head. Slight lacing and minimal retention. Looks fabulous. Nose of chocolate and nuttiness is quite good, but the taste and mouthfeel is where it's at. Nice blend of maltiness, chocolate, sweetness and roastiness. A smooth sipper; this surprised me in a great way. Very good.", "Aug 09, 2025"),
        ("1368-1368434.jpg", "DraftMonger", "Denmark", "3.99", "-7.9%", "3 | smell: 4 | taste: 4 | feel: 4 | overall: 4.25", "Black and blue can with Stone's iconic Devil head. Pours opaque dark brown with a big beige head. Aroma is fairly intense with a dark malty and toasted odor, dark chocolate and licorice. Light carbonation. Medium thick, oily, soft and slightly viscous. Fine potent boozer.", "May 27, 2025"),
        ("1213-1213070.jpg", "njzzle8287", "Texas", "5", "+15.5%", "5 | smell: 5 | taste: 5 | feel: 5 | overall: 5", "Poured into a tulip pint at about 45F. Jet black and totally opaque with a desert-sand colored head that lasts much longer than anticipated. Smells of caramel and cocoa with a nice yeasty zest. The mouthfeel is amazing and overall absolutely superb.", "Feb 17, 2025"),
        ("1045-1045082.jpg", "mvanaskie13", "Pennsylvania", "4.22", "-2.5%", "4.25 | smell: 4 | taste: 4.25 | feel: 4.5 | overall: 4.25", "Poured into a chalice: color is solid black, head is tan with fine to small bubbles and presents one finger thick. Smell is boozy up front, then roast, chocolate, toast, malt, earth and grassy hops. Overall a big beer that drinks lighter but brings forward chocolate, roast and light coffee.", "Feb 16, 2025"),
    )
    source_reviews = "".join(
        f"<article class='source-review'><a href='/community/members/{html.escape(user.lower())}/'><img src='/static/assets/{'ui' if avatar.startswith('avatar_') else 'avatars'}/{avatar}' alt=''></a><div><span class='muted'>Reviewed by <b><a href='/community/members/{html.escape(user.lower())}/'>{html.escape(user)}</a></b> from {html.escape(location)}</span><br><br><span class='review-score'>{score}</span><span class='review-outof'>/5</span>&nbsp;&nbsp;<span class='review-dev'>rDev {deviation}</span><br><span class='review-dimensions'>look: {dimensions}</span><div class='review-copy'>{html.escape(copy)}</div><span class='review-date'>{date}</span></div></article>"
        for avatar, user, location, score, deviation, dimensions, copy, date in observed_reviews
    )
    member = identity["display_name"] if identity is not None else None
    rate_href = "#review-form" if member else f"/community/login/?redirect=%2Fbeer%2Fprofile%2F{brewery_id}%2F{beer_id}%2F"
    rate_label = "Rate It"
    inline_review_form = review_form_markup(beer_id, inline=True) if member else ""
    avatar = "/static/assets/avatars/0-2.jpg"
    join_notice = f"<section class='subscription source-join'><span class='mobile-icon' aria-hidden='true'>♟</span><img class='avatar-img' src='{avatar}' alt=''><h2>Join the BeerAdvocate Community!</h2><p>Create your free account now to <b>rate, talk, and respect beer</b> with thousands of fellow beer geeks. You'll <b>see fewer ads</b> too.</p><a class='button' href='/community/register/'>Create Free Account</a><a class='dismiss' href='/?subscription=hidden' aria-label='Dismiss Notice'>×</a></section>" if member is None else ""
    style_id = SOURCE_STYLE_ID_BY_BEER_ID.get(int(beer_id), 84)
    saved = False
    if identity is not None:
        with open_database() as connection:
            saved = connection.execute(
                "SELECT 1 FROM saved_beers WHERE account_id = ? AND beer_id = ?",
                (identity["account_id"], beer_id),
            ).fetchone() is not None
    save_control = (
        f"<form method='post' action='/beer/{beer_id}/save/'><button class='secondary' "
        f"type='submit'>{'Unsave' if saved else 'Save beer'}</button></form>"
        if identity is not None
        else f"<a href='/community/login/?redirect=%2Fbeer%2Fprofile%2F{brewery_id}%2F{beer_id}%2F'>Save beer</a>"
    )
    overview = f"<div class='source-title'><h1>{html.escape(b['name'])}<br><span><a href='/beer/profile/{brewery_id}/'>{html.escape(b['brewery'])}</a></span></h1></div><div class='source-suggest'><a href='/beer/share/{beer_id}/'>Share</a> · <a href='/beer/compare/?beer={beer_id}'>Compare</a></div><div class='source-overview'><div class='source-score-box'><span>SCORE</span><span class='score-number'>{b['score']}</span><span>World-Class</span></div><div class='source-beer-info'><img class='source-main-image' src='{beer_image_url(b)}' alt='{html.escape(b['name'])}'><a class='source-rate showReview text Tooltip' href='{rate_href}'>✓ {rate_label}</a>{save_control}<div class='source-stats-title'>Beer Geek Stats <span class='muted'>| Print Shelf Talker</span></div><dl class='source-beerstats'><dt>From:</dt><dd><a href='/beer/profile/{brewery_id}/'>{html.escape(b['brewery'])}</a><br><span>Escondido, California, United States</span></dd><dt>Style:</dt><dd><a href='/beer/top-styles/{style_id}/'>{html.escape(b['style'])}</a><br><span>Ranked #55</span></dd><dt>ABV:</dt><dd>{b['abv']}%</dd><dt>Score:</dt><dd>{b['score']}<br><span>Ranked #991</span></dd><dt>Avg:</dt><dd>4.33 <span>| pDev: 9.24%</span></dd><dt>Ratings:</dt><dd>{b['ratings']:,} <span>| reviews: {b['reviews']:,}</span></dd><dt>Status:</dt><dd><span style='color:#22871d'>Active</span></dd><dt>Rated:</dt><dd><span>Jun 24, 2026</span></dd><dt>Added:</dt><dd><span>Sep 21, 2001</span></dd><dt>Wants:</dt><dd><span>850</span></dd><dt>Gots:</dt><dd><span>2,313</span></dd></dl></div></div>"
    description = "<div class='source-description'><p>Formerly known as Imperial Russian Stout</p><p>Ask any hardcore Stone enthusiast about our most legendary beers and you’re bound to hear mention of this one. Nearly jet black with a fluffy hot chocolate-colored head, a goblet of this obsidian wonder held to the sky could block out the sun. Redolent with dark chocolate and heavy roast up front, gracefully supported by nuances of coffee, black currant, molasses as it finishes… this beaut is ageable for years. Some of us are still enjoying our bottles from the early 2000’s. So, to look ahead, what will your stock of the 2022 edition of the Stone Imperial Stout be in 2037?</p></div>"
    side = "<aside class='source-detail-side'><div class='side-box goal-box'><a class='goal-head' href='/society/'><span class='goal-icon'>⚑</span><span class='goal-copy'><b>Goal: The Mayor</b><strong>331</strong> / 500 | <b>66.2%</b></span></a><div class='progress'><span></span></div><p class='muted' style='text-align:center'><b>169</b> more subs needed to unlock <b>The Mayor</b>!</p></div><div class='side-box find-beer'><h3>Find a Beer</h3><form action='/search/' method='get'><input type='search' aria-label='Beer name' name='q' placeholder='Type the name and hit enter'></form></div></aside>"
    body = f"<div class='source-detail'><div class='crumb'>Home / Beers / <a href='/beer/profile/{brewery_id}/'>{html.escape(b['brewery'])}</a></div><div class='source-detail-grid'><section class='source-detail-main'>{join_notice}{overview}{inline_review_form}{description}<div class='source-review-heading'><b>View: Beers | Place Reviews</b></div><div class='source-tabs'><span>Recent</span></div><div class='source-review-intro'>Recent ratings and reviews.</div>{local_reviews}{source_reviews}</section>{side}</div></div>"
    return page(f"{b['name']} | {b['brewery']} | BeerAdvocate", body, member)


@app.get('/beer/profile/{brewery_id}/')
def brewery_detail(
    brewery_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    brewery_beers = [beer for beer in beers if beer["brewery_id"] == brewery_id]
    if not brewery_beers:
        raise HTTPException(status_code=404, detail="Brewery not found")
    brewery = str(brewery_beers[0]["brewery"])
    if brewery_id == 147:
        cards = "".join(
            f"<tr><td><a href='/beer/profile/147/{beer_id}/'><strong>"
            f"{html.escape(name)}</strong></a></td><td>Active</td><td>—</td>"
            f"<td>—</td></tr>" for beer_id, name in SOURCE_STONE_BEERS.items()
        )
        beer_listing = (
            "<table style='width:100%;border-collapse:collapse'><thead><tr>"
            "<th>Beer</th><th>Status</th><th>Ratings</th><th>Score</th></tr>"
            f"</thead><tbody>{cards}</tbody></table>"
        )
    else:
        cards = "".join(
            f"<div class='beer'><a href='/beer/profile/{brewery_id}/"
            f"{beer['beer_id']}/'><strong>{html.escape(beer['name'])}</strong></a>"
            f"<p>{html.escape(beer['style'])} · {beer['abv']:g}%</p>"
            f"<span class='score'>{beer['score']}</span></div>"
            for beer in brewery_beers
        )
        beer_listing = f"<div class='grid'>{cards}</div>"
    body = (
        f"<div class='crumb'>Home / Places / United States / California / "
        f"{html.escape(brewery)}</div><div class='layout'><section><div class='hero'>"
        f"<h1>{html.escape(brewery)}</h1><p>Brewery · Escondido, California, "
        "United States</p><a class='button' href='/data/?action=add_beer'>Add a "
        "Beer</a></div><div class='source-tabs'><span>Active</span><a class='page-link' "
        "href='?view=new'>New</a><a class='page-link' href='?view=inactive'>Inactive"
        "</a><a class='page-link' href='?view=retired'>Retired</a><a "
        "class='page-link' href='?view=all'>All</a></div><div class='panel'><h2>"
        f"Active Beers ({len(SOURCE_STONE_BEERS) if brewery_id == 147 else len(brewery_beers)})"
        f"</h2>{beer_listing}</div></section><aside class='side'><div class='side-box'>"
        "<h3>Beer Stats</h3><p>Active beer listings and ratings.</p></div><div "
        "class='side-box'><h3>Place Stats</h3><p><a href='/place/directory/9/US/CA/'>"
        "California</a></p><p>Locations and public place data.</p></div></aside></div>"
    )
    return page(
        f"{brewery} | BeerAdvocate",
        body,
        local_member(ba_local_member),
        active_section="places",
    )


def login_markup(redirect: str, error: str | None = None) -> str:
    error_html = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    return f"<div class='layout'><section class='panel'><h1>Log in</h1>{error_html}<form method='post' action='/community/login/login'><input type='hidden' name='redirect' value='{html.escape(redirect)}'><label>Username or email<input name='login' autocomplete='username' required></label><label class='check'><input type='radio' name='register' value='1'> <span>No, create an account now.</span></label><label class='check'><input type='radio' name='register' value='0' checked> <span>Yes, my password is:</span></label><label>Password<input name='password' type='password' autocomplete='current-password' required></label><p><a href='/community/lost-password/'>Forgot your password?</a></p><label class='check'><input type='checkbox' name='remember' checked> <span>Stay logged in</span></label><button>Log in</button></form><p><a href='/community/register/?redirect={html.escape(redirect)}'>Create an account</a></p></section><aside class='side'><div class='side-box goal-box'><h3>Goal: The Mayor</h3><div class='progress'><span></span></div></div><div class='side-box'><h3>Find a Beer</h3></div></aside></div>"


def register_markup(redirect: str, error: str | None = None) -> str:
    error_html = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    return f"<div class='panel'><h1>Join BeerAdvocate</h1><p>Create an account for ratings and community participation.</p>{error_html}<form method='post' action='/community/register/start'><input type='hidden' name='redirect' value='{html.escape(redirect)}'><label>Username<input name='username' minlength='1' maxlength='120' autocomplete='username' required></label><label>Email<input name='email' type='email' autocomplete='email' required></label><label>Password<input name='password' type='password' minlength='8' maxlength='128' autocomplete='new-password' required></label><label>Confirm Password<input name='confirm_password' type='password' minlength='8' maxlength='128' autocomplete='new-password' required></label><label>Gender<select name='gender'><option value=''>Unspecified</option><option>Male</option><option>Female</option><option>Non-binary</option></select></label><label>Date of Birth<input name='dob' type='date'></label><label>Verification<input name='verification' value='Verification complete' readonly></label><label class='check'><input name='weekly_updates' type='checkbox' value='1'> <span>Receive the weekly BeerAdvocate update.</span></label><label class='check'><input name='terms' type='checkbox' value='accepted' required> <span>I agree to the community rules.</span></label><p><a href='/terms/'>Terms</a> · <a href='/privacy/'>Privacy Policy</a></p><button>Create account</button></form><p><a href='/community/login/?redirect={html.escape(redirect)}'>Already have an account?</a></p></div>"

@app.get('/community/login/')
def login(redirect: str = '/'):
    return page(
        'Log in | Community | BeerAdvocate',
        login_markup(safe_local_path(redirect)),
        active_section="none",
    )

@app.get('/community/register/')
def register(redirect: str = '/'):
    return page(
        'Register | Community | BeerAdvocate',
        register_markup(safe_local_path(redirect)),
        active_section="none",
    )


@app.post('/community/register/start')
def register_start(username: str = Form(...), email: str = Form(...), password: str = Form(...), confirm_password: str = Form(...), terms: str | None = Form(default=None), redirect: str = Form('/'), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    target = safe_local_path(redirect)
    if password != confirm_password:
        response = page('Register | Community | BeerAdvocate', register_markup(target, 'Passwords do not match.'))
        response.status_code = 422
        return response
    if terms != 'accepted':
        response = page('Register | Community | BeerAdvocate', register_markup(target, 'Accept the community rules to continue.'))
        response.status_code = 422
        return response
    _, auth = services()
    token, _ = auth.ensure_session(ba_local_member)
    try:
        with _REGISTRATION_LOCK:
            session_digest = auth.session_owner_digest(token)
            if display_name_in_use(auth, username, session_digest):
                raise AuthConflict("Username is already in use.")
            auth.start_registration(
                token,
                email=email,
                display_name=username,
                password=password,
            )
    except AuthError as exc:
        response = page('Register | Community | BeerAdvocate', register_markup(target, str(exc)))
        response.status_code = 409 if isinstance(exc, AuthConflict) else 422
        return with_session_cookie(response, token)
    body = f"<div class='panel'><h1>Verify your account</h1><p class='success'>Your verification request is ready.</p><p>Continue to activate your account.</p><form method='post' action='/community/register/complete'><input type='hidden' name='redirect' value='{html.escape(target)}'><button>Verify and activate account</button></form></div>"
    return with_session_cookie(page('Verify account | BeerAdvocate', body), token)


@app.post('/community/register/complete')
def register_complete(redirect: str = Form('/'), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    target = safe_local_path(redirect)
    if not ba_local_member:
        return RedirectResponse('/community/register/', status_code=303)
    _, auth = services()
    try:
        local_mail = auth.local_mail_for_session(ba_local_member, purpose='registration')
        if local_mail is None:
            raise AuthRejected('Verification challenge is unavailable or expired.')
        auth.verify_registration_code(ba_local_member, str(local_mail['verification_code']))
        result = auth.complete_registration(ba_local_member)
    except AuthError as exc:
        response = page('Register | Community | BeerAdvocate', register_markup(target, str(exc)))
        response.status_code = 422
        return response
    return with_session_cookie(RedirectResponse(target, status_code=303), str(result['session_token']))

@app.get('/community/')
def community(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    with open_database() as connection:
        rows = connection.execute("SELECT id,title,author,category,created_at FROM forum_posts ORDER BY id DESC").fetchall()
    section_at = {
        0: "MAIN",
        5: "REGIONAL",
        8: "EUROPE",
        15: "UNITED STATES",
        25: "INTERESTS",
        30: "BEER TRADING",
    }
    forum_parts = []
    for index, (slug, name) in enumerate(SOURCE_FORUMS.items()):
        if index in section_at:
            forum_parts.append(f"<h2 class='section-title'>{section_at[index]}</h2>")
        forum_parts.append(
            f"<div class='forum-row'><div><a href='/community/forums/{slug}/'>"
            f"<strong>{html.escape(name)}</strong></a><span class='muted'>Public "
            "beer discussion forum</span></div><span class='muted'>"
            f"{(index + 37) * 113:,}<br>discussions</span><span class='muted'>"
            "Latest public post</span></div>"
        )
    new_posts = "".join(
        f"<p><a href='/community/thread/{row['id']}/'>"
        f"{html.escape(row['title'])}</a><br><span class='muted'>"
        f"{html.escape(row['author'])}</span></p>" for row in rows[:8]
    )
    body = (
        "<div class='layout'><section><div class='crumb'>Home / Forums</div>"
        "<h1>Beer Forums</h1><p><a class='button' href='/community/new-thread/'>"
        f"Start a Thread</a></p><div class='panel'>{''.join(forum_parts)}</div>"
        "</section><aside class='side'><div class='side-box'><h3>New Posts</h3>"
        f"{new_posts}</div><div class='side-box'><h3>Forum Stats</h3><p>"
        "Discussions: 262,382</p><p>Messages: 7,172,160</p><p>Members: "
        "804,638</p></div></aside></div>"
    )
    return page('Forums | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/community/thread/{post_id}/')
def thread_detail(post_id: int, ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    with open_database() as connection:
        post = connection.execute("SELECT * FROM forum_posts WHERE id = ?", (post_id,)).fetchone()
        replies = connection.execute("SELECT * FROM forum_replies WHERE post_id = ? ORDER BY id", (post_id,)).fetchall()
    if post is None:
        raise HTTPException(status_code=404, detail='Thread not found')
    reply_html = ''.join(f"<article class='panel'><p>{html.escape(reply['body'])}</p><p class='muted'>{html.escape(reply['author'])}</p></article>" for reply in replies)
    member = local_member(ba_local_member)
    reply_form = f"<div class='panel'><h2>Reply</h2><form method='post' action='/community/thread/{post_id}/reply'><label>Reply<textarea name='body' required maxlength='4000'></textarea></label><button>Post Reply</button></form></div>" if member else f"<p class='notice'><a href='/community/login/?redirect=/community/thread/{post_id}/'>Log in</a> to reply.</p>"
    body = f"<div class='crumb'>Forums / {html.escape(post['category'])}</div><article class='panel'><h1>{html.escape(post['title'])}</h1><p>{html.escape(post['body'])}</p><p class='muted'>Started by {html.escape(post['author'])}</p></article>{reply_html}{reply_form}"
    return page(f"{post['title']} | BeerAdvocate", body, member)


@app.get('/community/threads/{source_thread_id:int}/unread')
@app.get('/community/threads/{source_thread_id:int}/')
def source_thread_redirect(source_thread_id: int):
    title = SOURCE_THREAD_TITLES.get(source_thread_id)
    if title is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    with open_database() as connection:
        row = connection.execute(
            "SELECT id FROM forum_posts WHERE title = ?", (title,)
        ).fetchone()
    if row is None:
        body = (
            "<div class='crumb'>Forums / Public thread</div>"
            f"<article class='panel'><h1>{html.escape(title)}</h1>"
            "<p>This read-only thread landing preserves the observed source "
            "navigation target. New replies are stored in your account. "
            "threads.</p><p><a href='/community/'>Back to Forums</a></p></article>"
        )
        return page(f"{title} | BeerAdvocate", body)
    return RedirectResponse(f"/community/thread/{row['id']}/", status_code=302)


def source_thread_id(thread_slug: str) -> int | None:
    tail = thread_slug.rsplit(".", 1)[-1]
    return int(tail) if tail.isdigit() else None


@app.get('/community/threads/{thread_slug}/page-{page_num}')
@app.get('/community/threads/{thread_slug}/')
def source_thread_slug(
    thread_slug: str,
    page_num: int = 1,
):
    thread_id = source_thread_id(thread_slug)
    if thread_id is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    response = source_thread_redirect(thread_id)
    if isinstance(response, HTMLResponse) and page_num > 1:
        response.headers["X-WebsiteBench-Source-Page"] = str(page_num)
    return response


@app.get('/community/posts/{post_id}/')
def source_post_permalink(post_id: int):
    body = (
        "<div class='crumb'>Forums / Post permalink</div>"
        f"<article class='panel' id='post-{post_id}'><h1>Forum post</h1>"
        f"<p>Post #{post_id}</p><p>This public permalink is available for reading.</p><a href='/community/'>Back to Forums</a>"
        "</article>"
    )
    return page("Forum post | BeerAdvocate", body)


@app.post('/community/thread/{post_id}/reply')
def thread_reply(post_id: int, body: str = Form(...), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    identity = local_identity(ba_local_member)
    if identity is None:
        return RedirectResponse(f'/community/login/?redirect=/community/thread/{post_id}/', status_code=303)
    if not body.strip() or len(body.strip()) > 4000:
        raise HTTPException(status_code=422, detail='Reply must contain 1 to 4000 characters')
    with open_database() as connection:
        if connection.execute("SELECT 1 FROM forum_posts WHERE id = ?", (post_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail='Thread not found')
        connection.execute(
            "INSERT INTO forum_replies (post_id,body,author,created_at,account_id) VALUES (?,?,?,?,?)",
            (post_id, body.strip(), identity['display_name'], datetime.now(UTC).isoformat(), identity['account_id']),
        )
        connection.commit()
    return RedirectResponse(f'/community/thread/{post_id}/', status_code=303)


@app.get('/community/new-thread/')
def new_thread_form(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    member = local_member(ba_local_member)
    if member is None:
        return RedirectResponse('/community/login/?redirect=/community/new-thread/', status_code=303)
    body = "<div class='panel'><h1>Start a Thread</h1><form method='post' action='/community/new-thread/'><label>Forum<select name='category'><option>The Bar</option><option>Beer Talk</option><option>Beer News</option><option>Regional</option></select></label><label>Title<input name='title' minlength='3' maxlength='160' required></label><label>Message<textarea name='body' maxlength='8000' required></textarea></label><button>Post Thread</button></form></div>"
    return page('Start a Thread | BeerAdvocate', body, member)


@app.post('/community/new-thread/')
def new_thread(title: str = Form(...), body: str = Form(...), category: str = Form(...), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    identity = local_identity(ba_local_member)
    if identity is None:
        return RedirectResponse('/community/login/?redirect=/community/new-thread/', status_code=303)
    if not 3 <= len(title.strip()) <= 160 or not 1 <= len(body.strip()) <= 8000:
        raise HTTPException(status_code=422, detail='Thread title or message is invalid')
    if category not in {'The Bar', 'Beer Talk', 'Beer News', 'Regional'}:
        raise HTTPException(status_code=422, detail='Forum category is invalid')
    with open_database() as connection:
        cursor = connection.execute(
            "INSERT INTO forum_posts (title,body,author,category,created_at,account_id) VALUES (?,?,?,?,?,?)",
            (title.strip(), body.strip(), identity['display_name'], category, datetime.now(UTC).isoformat(), identity['account_id']),
        )
        connection.commit()
        post_id = int(cursor.lastrowid)
    return RedirectResponse(f'/community/thread/{post_id}/', status_code=303)

@app.get('/place/directory/')
@app.get('/place/')
def places(q: str = '', kind: str = '', ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    matches = [place for place in places_data if (not q or q.casefold() in (place['name'] + place['city'] + place['state']).casefold()) and (not kind or place['kind'] == kind)]
    cards = ''.join(f"<article class='beer place-card'><a href='/place/{place['id']}/'><strong>{html.escape(place['name'])}</strong></a><p>{html.escape(place['kind'])} · {html.escape(place['city'])}, {html.escape(place['state'])}</p><span class='rating'>{place['rating']:.2f}</span></article>" for place in matches)
    body = (
        "<div class='hero'><h1>Places</h1><p>Find breweries, bars, and beer "
        "destinations.</p><form method='get' action='/place/list/'>"
        f"<label>Name<input name='name' value='{html.escape(q)}'></label>"
        "<label>City<input name='city'></label><label>Country<select name='c_id'>"
        "<option value=''>All countries</option><option value='US'>United States"
        "</option></select></label><label>State<select name='s_id'><option value=''>"
        "All states</option><option value='CA'>California</option></select></label>"
        "<div class='dimensions'><label class='check'><input type='checkbox' "
        "name='brewery' value='1'>Brewery</label><label class='check'><input "
        "type='checkbox' name='eatery' value='1'>Food</label><label class='check'>"
        "<input type='checkbox' name='bar' value='1'>Bar</label><label class='check'>"
        "<input type='checkbox' name='store' value='1'>Store</label><label class='check'>"
        "<input type='checkbox' name='homebrew' value='1'>Homebrew</label></div>"
        "<label class='check'><input type='checkbox' name='active' value='1' "
        "checked>Exclude closed locations</label><button name='submit'>Find Places"
        "</button></form></div>"
        f"<div class='panel'><p>{len(matches)} places found</p><div class='grid'>"
        f"{cards or '<p class=notice>No matching places found.</p>'}</div></div>"
    )
    return page('Places | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/place/list/')
def place_list(
    name: str = '',
    city: str = '',
    c_id: str = '',
    s_id: str = '',
    brewery: str | None = None,
    eatery: str | None = None,
    bar: str | None = None,
    store: str | None = None,
    homebrew: str | None = None,
    active: str | None = None,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    del eatery, store, homebrew, active
    query = " ".join(value for value in (name, city, c_id, s_id) if value).strip()
    kind = "Brewery" if brewery is not None else "Beer Bar" if bar is not None else ""
    return places(query, kind, ba_local_member)


@app.get('/place/city/{city_id}/')
def place_city(
    city_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    city_names = {28: "San Diego"}
    city = city_names.get(city_id, f"City directory {city_id}")
    matches = [place for place in places_data if place["city"] == city]
    cards = "".join(
        f"<article class='beer place-card'><a href='/place/{place['id']}/'>"
        f"<strong>{html.escape(place['name'])}</strong></a><p>"
        f"{html.escape(place['kind'])} · {html.escape(place['city'])}, "
        f"{html.escape(place['state'])}</p></article>" for place in matches
    )
    body = (
        f"<div class='crumb'>Home / Places / {html.escape(city)}</div>"
        f"<div class='hero'><h1>{html.escape(city)} Beer Guide</h1>"
        "<p>Breweries, beer bars, stores, and destinations.</p></div>"
        f"<div class='panel'>{cards or '<p>No listings in this snapshot.</p>'}"
        "</div>"
    )
    return page(f"{city} Beer Guide | BeerAdvocate", body, local_member(ba_local_member))


@app.get('/place/directory/{region_id}/{country}/')
@app.get('/place/directory/{region_id}/{country}/{state}/')
def place_region(
    region_id: int,
    country: str,
    state: str = '',
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    state_name = {"CA": "California"}.get(state.upper(), state.upper())
    heading = state_name or {"US": "United States"}.get(country.upper(), country.upper())
    matches = [
        place for place in places_data
        if not state or place["state"].casefold() == state.casefold()
    ]
    cards = "".join(
        f"<article class='beer place-card'><a href='/place/{place['id']}/'>"
        f"<strong>{html.escape(place['name'])}</strong></a><p>"
        f"{html.escape(place['city'])}, {html.escape(place['state'])}</p></article>"
        for place in matches
    )
    body = (
        f"<div class='crumb'>Places / {html.escape(country.upper())} / "
        f"{html.escape(state.upper())}</div><div class='hero'><h1>"
        f"{html.escape(heading)} Beer Guide</h1><p>Region {region_id}</p></div>"
        f"<div class='panel'><div class='grid'>{cards}</div></div>"
    )
    return page(f"{heading} Beer Guide | BeerAdvocate", body, local_member(ba_local_member))


@app.get('/place/{place_id:int}/')
def place_detail(place_id: int, ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    place = next((item for item in places_data if item['id'] == place_id), None)
    if place is None:
        raise HTTPException(status_code=404, detail='Place not found')
    body = f"<div class='crumb'>Home / Places / {html.escape(place['state'])}</div><div class='layout'><section><div class='hero'><h1>{html.escape(place['name'])}</h1><p>{html.escape(place['kind'])} · {html.escape(place['city'])}, {html.escape(place['state'])}</p><div class='score'>{place['rating']:.2f}</div></div><div class='panel'><h2>About this place</h2><p>Directory details and community information.</p><h2>Community Notes</h2><p>Beer selection, service, and atmosphere.</p></div></section><aside class='side'><div class='side-box'><h3>Place Stats</h3><p>Rating <b>{place['rating']:.2f}</b></p><p>United States</p></div></aside></div>"
    return page(f"{place['name']} | BeerAdvocate", body, local_member(ba_local_member))

@app.post('/community/login/login')
def login_post(login: str = Form(...), password: str = Form(...), redirect: str = Form('/'), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    target = safe_local_path(redirect)
    _, auth = services()
    token, _ = auth.ensure_session(ba_local_member)
    try:
        result = auth.sign_in(token, email=account_email_for_login(login), password=password)
    except AuthError:
        response = page('Log in | Community | BeerAdvocate', login_markup(target, 'The username/email or password is incorrect.'))
        response.status_code = 401
        return with_session_cookie(response, token)
    return with_session_cookie(RedirectResponse(target, status_code=303), str(result['session_token']))

@app.post('/community/login/local-test')
def local_test_login(redirect: str = Form('/beer/profile/147/1160/')):
    if not test_login_enabled():
        raise HTTPException(status_code=404, detail="Test login is disabled")
    return session_response(safe_local_path(redirect, '/beer/profile/147/1160/'), 'Local Test Member')


@app.get('/community/logout/')
def logout_form(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    member = local_member(ba_local_member)
    if member is None:
        return RedirectResponse('/', status_code=303)
    body = "<div class='panel'><h1>Log out</h1><p>End your member session?</p><form method='post' action='/community/logout/'><button>Log out</button> <a class='button secondary' href='/'>Cancel</a></form></div>"
    return page('Log out | BeerAdvocate', body, member)


@app.post('/community/logout/')
def logout(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    _, auth = services()
    auth.sign_out(ba_local_member)
    response = RedirectResponse('/', status_code=303)
    response.delete_cookie(LOCAL_MEMBER_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response

@app.get('/society/')
@app.get('/community/forums/beeradvocate-society.60/')
def society(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    body = "<div class='hero'><h1>BeerAdvocate Society</h1><p>The member-support community area.</p><a class='button' href='/community/register/'>Join the Community</a></div><div class='panel'><h2>Society Milestones</h2><p>331 of 500 members toward The Mayor milestone.</p><div class='progress'><span></span></div><h2>Member Benefits</h2><p>Community participation, ratings, forum threads, and account identity are available here.</p></div>"
    return page('BeerAdvocate Society', body, local_member(ba_local_member))


@app.get('/community/forums/{forum_id}/page-{page_num}')
@app.get('/community/forums/{forum_id}/')
def forum_category(
    forum_id: str,
    page_num: int = 1,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    numeric_id = forum_id.rsplit(".", 1)[-1]
    category = {
        "68": "The Bar",
        "37": "Beer News",
        "39": "Beer Talk",
        "18": "BeerAdvocate Talk",
        "beeradvocate-talk.18": "Beer Talk",
    }.get(forum_id) or {
        "68": "The Bar",
        "37": "Beer News",
        "39": "Beer Talk",
        "18": "BeerAdvocate Talk",
    }.get(numeric_id)
    if category is None:
        category = forum_id.rsplit(".", 1)[0].replace("-", " ").title()
    with open_database() as connection:
        rows = connection.execute(
            "SELECT id,title,author,category FROM forum_posts "
            "WHERE category = ? ORDER BY id DESC",
            (category,),
        ).fetchall()
    items = "".join(
        f"<div class='forum-row'><div><a href='/community/thread/{row['id']}/'>"
        f"<strong>{html.escape(row['title'])}</strong></a>"
        f"<span class='muted'>{html.escape(row['category'])}</span></div>"
        f"<span></span><span class='muted'>{html.escape(row['author'])}</span></div>"
        for row in rows
    )
    pagination = "".join(
        f"<a class='page-link {'current' if number == page_num else ''}' "
        f"href='/community/forums/{html.escape(forum_id)}/page-{number}'>"
        f"{number}</a>" for number in range(1, 7)
    )
    body = (
        f"<div class='hero'><h1>{html.escape(category)}</h1>"
        f"<p>Current discussions · page {page_num}.</p>"
        "<a class='button' href='/community/new-thread/'>Start a Thread</a></div>"
        f"<div class='panel'>{items or '<p>No threads yet.</p>'}"
        f"<div class='pager'>{pagination}</div></div>"
    )
    return page(f"{category} | BeerAdvocate", body, local_member(ba_local_member))


@app.get('/community/find-new/posts')
@app.get('/community/whats-new/')
def whats_new(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    with open_database() as connection:
        rows = connection.execute("SELECT id,title,author,category FROM forum_posts ORDER BY id DESC LIMIT 20").fetchall()
    items = ''.join(f"<div class='forum-row'><div><a href='/community/thread/{row['id']}/'><strong>{html.escape(row['title'])}</strong></a><span class='muted'>{html.escape(row['category'])}</span></div><span></span><span class='muted'>{html.escape(row['author'])}</span></div>" for row in rows)
    return page("What's New | BeerAdvocate", f"<div class='hero'><h1>What's New</h1><p>Recent community activity.</p></div><div class='panel'>{items}</div>", local_member(ba_local_member))


@app.get('/community/members/{member_slug}/')
def member_profile(
    member_slug: str,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    display_name = member_slug.replace("-", "_")
    identity = local_identity(ba_local_member)
    following = False
    if identity is not None:
        with open_database() as connection:
            following = connection.execute(
                "SELECT 1 FROM followed_members WHERE account_id=? AND member_slug=?",
                (identity['account_id'], member_slug),
            ).fetchone() is not None
    follow_control = (
        f"<form method='post' action='/community/members/{html.escape(member_slug)}/follow/'>"
        f"<button type='submit'>{'Unfollow' if following else 'Follow'}</button></form>"
        if identity is not None
        else "<a class='button' href='/community/login/'>Follow</a>"
    )
    body = (
        f"<div class='panel'><h1>{html.escape(display_name)}</h1>"
        "<p class='muted'>BeerAdvocate community member</p>"
        f"{follow_control}<p>{'Following' if following else 'Public profile'}</p>"
        "<h2>Recent activity</h2><p>Public ratings and reviews appear on the "
        "beer pages where they were observed.</p>"
        "<p><a href='/beer/profile/147/1160/'>View recent beer reviews</a></p></div>"
    )
    return page(
        f"{display_name} | Community | BeerAdvocate",
        body,
        local_member(ba_local_member),
    )


@app.post('/community/members/{member_slug}/follow/')
def toggle_member_follow(
    member_slug: str,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    identity = local_identity(ba_local_member)
    if identity is None:
        raise HTTPException(status_code=401, detail="Member session required")
    if not member_slug or len(member_slug) > 120 or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in member_slug
    ):
        raise HTTPException(status_code=404, detail="Member not found")
    with open_database() as connection:
        local_target = connection.execute(
            "SELECT 1 FROM local_auth_accounts WHERE lower(replace(display_name, ' ', '-'))=?",
            (member_slug.casefold(),),
        ).fetchone()
        if member_slug.casefold() not in FOLLOWABLE_MEMBER_SLUGS and local_target is None:
            raise HTTPException(status_code=404, detail="Member not found")
        existing = connection.execute(
            "SELECT 1 FROM followed_members WHERE account_id=? AND member_slug=?",
            (identity['account_id'], member_slug),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO followed_members (account_id,member_slug,created_at) VALUES (?,?,?)",
                (identity['account_id'], member_slug, datetime.now(UTC).isoformat()),
            )
        else:
            connection.execute(
                "DELETE FROM followed_members WHERE account_id=? AND member_slug=?",
                (identity['account_id'], member_slug),
            )
        connection.commit()
    return RedirectResponse(f'/community/members/{member_slug}/', status_code=303)


@app.get('/community/account/')
def account_dashboard(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    identity = local_identity(ba_local_member)
    if identity is None:
        return RedirectResponse('/community/login/?redirect=/community/account/', status_code=303)
    with open_database() as connection:
        reviews = connection.execute(
            "SELECT * FROM reviews WHERE account_id=? ORDER BY id DESC",
            (identity['account_id'],),
        ).fetchall()
        saved_ids = [
            int(row['beer_id']) for row in connection.execute(
                "SELECT beer_id FROM saved_beers WHERE account_id=? ORDER BY created_at DESC",
                (identity['account_id'],),
            ).fetchall()
        ]
        followed = connection.execute(
            "SELECT member_slug FROM followed_members WHERE account_id=? ORDER BY created_at DESC",
            (identity['account_id'],),
        ).fetchall()
        threads = connection.execute(
            "SELECT id,title FROM forum_posts WHERE account_id=? ORDER BY id DESC",
            (identity['account_id'],),
        ).fetchall()
        replies = connection.execute(
            "SELECT post_id,body FROM forum_replies WHERE account_id=? ORDER BY id DESC",
            (identity['account_id'],),
        ).fetchall()
        contributions = connection.execute(
            "SELECT kind,title FROM submissions WHERE account_id=? ORDER BY id DESC",
            (identity['account_id'],),
        ).fetchall()
    review_items = "".join(
        f"<li><a href='/beer/review/{row['id']}/edit/'>{html.escape(row['comment'])}</a>"
        f" <span class='muted'>beer #{row['beer_id']}</span></li>" for row in reviews
    ) or "<li>No reviews yet.</li>"
    saved_items = "".join(
        f"<li><a href='/beer/profile/{beers_by_id[beer_id]['brewery_id']}/{beer_id}/'>"
        f"{html.escape(beers_by_id[beer_id]['name'])}</a></li>"
        for beer_id in saved_ids if beer_id in beers_by_id
    ) or "<li>No saved beers yet.</li>"
    followed_items = "".join(
        f"<li><a href='/community/members/{html.escape(row['member_slug'])}/'>"
        f"{html.escape(row['member_slug'])}</a></li>" for row in followed
    ) or "<li>No followed members yet.</li>"
    community_items = "".join(
        f"<li><a href='/community/thread/{row['id']}/'>{html.escape(row['title'])}</a></li>"
        for row in threads
    ) + "".join(
        f"<li><a href='/community/thread/{row['post_id']}/'>{html.escape(row['body'])}</a></li>"
        for row in replies
    )
    community_items = community_items or "<li>No community posts yet.</li>"
    contribution_items = "".join(
        f"<li>{html.escape(row['kind'].title())}: {html.escape(row['title'])}</li>"
        for row in contributions
    ) or "<li>No contributions yet.</li>"
    body = (
        f"<div class='panel'><h1>{html.escape(identity['display_name'])}</h1>"
        "<p class='muted'>Account activity and management</p>"
        f"<h2>Reviews</h2><ul>{review_items}</ul><h2>Saved beers</h2><ul>{saved_items}</ul>"
        f"<h2>Following</h2><ul>{followed_items}</ul><h2>Community activity</h2>"
        f"<ul>{community_items}</ul><h2>Contributions</h2><ul>{contribution_items}</ul>"
        "<p><a href='/help/'>Help and recovery</a></p></div>"
    )
    return page('Your Account | BeerAdvocate', body, identity['display_name'])


def information_page(title: str, paragraphs: list[str], member: str | None) -> HTMLResponse:
    content = ''.join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)
    return page(f'{title} | BeerAdvocate', f"<div class='panel'><h1>{html.escape(title)}</h1>{content}</div>", member)


@app.get('/about/')
@app.get('/community/about/')
def about(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return information_page('About BeerAdvocate', ['Founded in 1996, BeerAdvocate is an independent beer community.', 'Explore ratings, reviews, places, and community discussions.'], local_member(ba_local_member))


@app.get('/community/lost-password/')
def lost_password(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    body = (
        "<div class='panel'><h1>Lost Password</h1><p>Account recovery is handled securely here.</p><form method='post' action='/community/lost-password/start/'>"
        "<label>Email<input type='email' name='email' required></label>"
        "<button type='submit'>Start recovery</button></form></div>"
    )
    return page('Lost Password | BeerAdvocate', body, local_member(ba_local_member))


@app.post('/community/lost-password/start/')
def lost_password_start(
    email: str = Form(...),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    _, auth = services()
    token, _ = auth.ensure_session(ba_local_member)
    try:
        auth.start_password_reset(token, email=email)
    except AuthError:
        pass
    body = (
        "<div class='panel'><h1>Check your recovery state</h1>"
        "<p class='success'>If a matching account exists, a recovery "
        "challenge is ready.</p>"
        "<p>Automatic completion is disabled because an independent account-control channel is required. The application will not expose "
        "or auto-consume the challenge.</p><p><a href='/community/login/'>"
        "Return to login</a> · <a href='/help/'>Get help</a></p></div>"
    )
    return with_session_cookie(page('Password Recovery | BeerAdvocate', body), token)


@app.post('/community/lost-password/complete/')
def lost_password_complete(
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    del new_password, confirm_password, ba_local_member
    raise HTTPException(
        status_code=403,
        detail="Password recovery requires an independent account-control channel",
    )


@app.get('/help/')
@app.get('/community/help/')
def help_page(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    body = (
        "<div class='panel'><h1>Help and Recovery</h1><p>Use these "
        "routes to recover from common states.</p><ul>"
        "<li><a href='/community/login/'>Sign in</a></li>"
        "<li><a href='/community/register/'>Create an account</a></li>"
        "<li><a href='/community/lost-password/'>Reset a password</a></li>"
        "<li><a href='/search/'>Search beers</a></li>"
        "<li><a href='/community/contact/'>Contact information</a></li>"
        "</ul></div>"
    )
    return page('Help | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/community/search/')
@app.get('/community/search/{page_num}/')
def forum_search(
    page_num: int = 1,
    q: str = '',
    search_type: str = Query('post', alias='type'),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    body = (
        "<div class='crumb'>Forums / Search</div><div class='hero'><h1>Search "
        f"Forums</h1><p>Page {page_num} · {html.escape(search_type)}</p><form "
        "method='get' action='/community/search/1/'><input type='hidden' "
        "name='searchform' value='1'><input name='q' value='"
        f"{html.escape(q)}'><select name='o'><option value='date'>Most recent"
        "</option></select><button>Search</button></form></div>"
    )
    return page('Search Forums | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/community/misc/quick-navigation-menu')
def quick_navigation(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    body = (
        "<div class='panel'><h1>Quick Navigation</h1><p><a href='/community/'>"
        "Forums</a></p><p><a href='/beer/'>Beers</a></p><p><a href='/place/'>"
        "Places</a></p></div>"
    )
    return page('Quick Navigation | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/community/account/dismiss-notice')
def dismiss_notice(notice_id: int = 0):
    return RedirectResponse(f'/?subscription=hidden&notice_id={notice_id}', status_code=302)


@app.get('/articles/')
@app.get('/articles/archive/')
def articles(
    s: str = '',
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    return information_page(
        f'Articles: {s}' if s else 'Articles',
        ['Public article navigation is available without source requests.'],
        local_member(ba_local_member),
    )


@app.get('/respect-beer/')
def respect_beer(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    return information_page(
        'Respect Beer',
        ['BeerAdvocate is guided by its Respect Beer® motto.'],
        local_member(ba_local_member),
    )


@app.get('/community/conversations/add')
def contact_conversation(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    return information_page(
        'Start a Conversation',
        ['External messages are disabled; this page does not send messages.'],
        local_member(ba_local_member),
    )


@app.get('/contact/')
@app.get('/community/contact/')
def contact(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return information_page('Contact', ['Contact actions are currently unavailable.', 'Please use the community pages for discussion.'], local_member(ba_local_member))


@app.get('/follow')
@app.get('/follow/')
@app.get('/community/follow/')
def follow(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return information_page('Follow BeerAdvocate', ['Social actions are currently unavailable.', 'Use the forums and What’s New page to follow community activity.'], local_member(ba_local_member))


@app.get('/terms/')
@app.get('/community/terms/')
def terms(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return information_page('Terms of Service', ['Use your account responsibly and respect other community members.', 'Reviews and discussions should be accurate and constructive.'], local_member(ba_local_member))


@app.get('/privacy/')
@app.get('/community/privacy/')
def privacy(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return information_page('Privacy & Cookie Policy', ['Your session and community records are protected by this service.', 'We do not share account information with third parties.'], local_member(ba_local_member))


@app.get('/code/')
@app.get('/community/code-of-conduct/')
def code_of_conduct(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return information_page('Code of Conduct', ['Respect beer and respect other community members.', 'Keep reviews specific, useful, and free of harassment.'], local_member(ba_local_member))


@app.get('/trading/')
def trading(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    body = (
        "<div class='hero'><h1>Beer Trading</h1>"
        "<p>Browse trading discussions without contacting another person.</p>"
        "</div><div class='panel'><h2>Trading Forums</h2>"
        "<p>This site does not send offers, private messages, or shipments.</p>"
        "<p><a href='/community/'>Browse community discussions</a></p></div>"
    )
    return page('Beer Trading | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/beer/trending/')
def trending_beers(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    return beer_index('', 1, 'ratings', ba_local_member)


@app.get('/place/visits/')
def place_visits(
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    cards = "".join(
        f"<article class='beer place-card'><a href='/place/{place['id']}/'>"
        f"<strong>{html.escape(place['name'])}</strong></a>"
        f"<p>{html.escape(place['city'])}, {html.escape(place['state'])}</p>"
        "<span class='muted'>Directory visit</span></article>"
        for place in places_data[:6]
    )
    body = (
        "<div class='hero'><h1>Place Visits</h1>"
        "<p>A deterministic visit list for the directory.</p></div>"
        f"<div class='panel'><div class='grid'>{cards}</div></div>"
    )
    return page('Place Visits | BeerAdvocate', body, local_member(ba_local_member))


def submission_form(kind: str, action: str) -> str:
    details_label = 'Brewery, style, and ABV' if kind == 'beer' else 'Type, city, and state'
    return f"<div class='panel'><h1>Add a {kind.title()}</h1><p class='notice'>This creates a pending contribution; nothing is sent to the source website.</p><form method='post' action='{action}'><label>Name<input name='title' minlength='2' maxlength='160' required></label><label>{details_label}<textarea name='details' maxlength='2000' required></textarea></label><button>Save Contribution</button></form></div>"


@app.get('/beer/add/')
def add_beer_form(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    member = local_member(ba_local_member)
    if member is None:
        return RedirectResponse('/community/login/?redirect=/beer/add/', status_code=303)
    return page('Add a Beer | BeerAdvocate', submission_form('beer', '/beer/add/'), member)


@app.post('/beer/add/')
def add_beer(title: str = Form(...), details: str = Form(...), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return save_submission('beer', title, details, ba_local_member)


@app.get('/place/add/')
def add_place_form(ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    member = local_member(ba_local_member)
    if member is None:
        return RedirectResponse('/community/login/?redirect=/place/add/', status_code=303)
    return page('Add a Place | BeerAdvocate', submission_form('place', '/place/add/'), member)


@app.post('/place/add/')
def add_place(title: str = Form(...), details: str = Form(...), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    return save_submission('place', title, details, ba_local_member)


@app.get('/data/')
def source_data_action(
    action: str = Query(...),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    if action == "add_beer":
        return add_beer_form(ba_local_member)
    if action == "add_place":
        return add_place_form(ba_local_member)
    raise HTTPException(status_code=404, detail="Data action not found")


def save_submission(kind: str, title: str, details: str, cookie: str | None):
    identity = local_identity(cookie)
    if identity is None:
        return RedirectResponse(f'/community/login/?redirect=/{kind}/add/', status_code=303)
    if not 2 <= len(title.strip()) <= 160 or not 1 <= len(details.strip()) <= 2000:
        raise HTTPException(status_code=422, detail='Contribution fields are invalid')
    with open_database() as connection:
        connection.execute(
            "INSERT INTO submissions (kind,title,details,author,created_at,account_id) VALUES (?,?,?,?,?,?)",
            (kind, title.strip(), details.strip(), identity['display_name'], datetime.now(UTC).isoformat(), identity['account_id']),
        )
        connection.commit()
    body = f"<div class='panel'><h1>Contribution saved</h1><p class='success'>{html.escape(title.strip())} is queued for review.</p><a class='button' href='/{kind}/'>Return to {kind.title()}s</a></div>"
    return page('Contribution saved | BeerAdvocate', body, identity['display_name'])

@app.get('/beer/rate/{beer_id}/')
def rate_form(beer_id: int, ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    if beer_id not in beers_by_id:
        raise HTTPException(status_code=404, detail="Beer not found")
    if local_member(ba_local_member) is None:
        return RedirectResponse(f'/community/login/?redirect=%2Fbeer%2Frate%2F{beer_id}%2F', status_code=303)
    member = local_member(ba_local_member)
    return page('Rate Beer | BeerAdvocate', review_form_markup(beer_id, inline=False), member)

def validate_review_input(scores: tuple[Decimal, ...], comment: str, media_asset: str) -> None:
    if any(score not in REVIEW_SCORE_OPTIONS for score in scores):
        raise HTTPException(
            status_code=422,
            detail="scores must use 0.25 increments between 1 and 5",
        )
    if not comment.strip() or len(comment.strip()) > 4000:
        raise HTTPException(status_code=422, detail="comment required")
    if media_asset not in REVIEW_MEDIA_ASSETS:
        raise HTTPException(status_code=422, detail="unknown media asset")


@app.post('/beer/rate/{beer_id}')
def rate(beer_id: int, look: Decimal = Form(...), smell: Decimal = Form(...), taste: Decimal = Form(...), feel: Decimal = Form(...), overall: Decimal = Form(...), comment: str = Form(...), media_asset: str = Form(''), ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE)):
    b = beers_by_id.get(beer_id)
    if b is None:
        raise HTTPException(status_code=404, detail="Beer not found")
    identity = local_identity(ba_local_member)
    if identity is None:
        raise HTTPException(status_code=401, detail="Member session required")
    member = identity["display_name"]
    scores = (look, smell, taste, feel, overall)
    validate_review_input(scores, comment, media_asset)
    with open_database() as connection:
        connection.execute(
            """
            INSERT INTO reviews (
                beer_id, account_id, member, look, smell, taste, feel, overall,
                comment, media_asset, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (beer_id, account_id) DO UPDATE SET
                member = excluded.member,
                look = excluded.look,
                smell = excluded.smell,
                taste = excluded.taste,
                feel = excluded.feel,
                overall = excluded.overall,
                comment = excluded.comment,
                media_asset = excluded.media_asset,
                created_at = excluded.created_at
            """,
            (
                beer_id,
                identity["account_id"],
                member,
                *(float(score) for score in scores),
                comment.strip(),
                media_asset,
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()
    return RedirectResponse(f"/beer/profile/{b['brewery_id']}/{b['beer_id']}/", status_code=303)


def owned_review(review_id: int, identity: dict[str, str]) -> sqlite3.Row:
    with open_database() as connection:
        review = connection.execute(
            "SELECT * FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if review["account_id"] != identity["account_id"]:
        raise HTTPException(status_code=403, detail="Review belongs to another account")
    return review


def review_redirect(review: sqlite3.Row) -> str:
    beer = beers_by_id.get(int(review["beer_id"]))
    if beer is None:
        raise HTTPException(status_code=404, detail="Beer not found")
    return f"/beer/profile/{beer['brewery_id']}/{beer['beer_id']}/"


@app.get('/beer/review/{review_id}/edit/')
def edit_review_form(
    review_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    identity = local_identity(ba_local_member)
    if identity is None:
        return RedirectResponse('/community/login/', status_code=303)
    review = owned_review(review_id, identity)
    return page(
        'Edit Review | BeerAdvocate',
        review_form_markup(
            int(review['beer_id']),
            inline=False,
            review=review,
            action=f'/beer/review/{review_id}/edit/',
        ),
        identity['display_name'],
    )


@app.post('/beer/review/{review_id}/edit/')
def edit_review(
    review_id: int,
    look: Decimal = Form(...),
    smell: Decimal = Form(...),
    taste: Decimal = Form(...),
    feel: Decimal = Form(...),
    overall: Decimal = Form(...),
    comment: str = Form(...),
    media_asset: str = Form(''),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    identity = local_identity(ba_local_member)
    if identity is None:
        raise HTTPException(status_code=401, detail="Member session required")
    review = owned_review(review_id, identity)
    scores = (look, smell, taste, feel, overall)
    validate_review_input(scores, comment, media_asset)
    with open_database() as connection:
        connection.execute(
            "UPDATE reviews SET look=?,smell=?,taste=?,feel=?,overall=?,comment=?,"
            "media_asset=?,created_at=? WHERE id=? AND account_id=?",
            (
                *(float(score) for score in scores),
                comment.strip(),
                media_asset,
                datetime.now(UTC).isoformat(),
                review_id,
                identity['account_id'],
            ),
        )
        connection.commit()
    return RedirectResponse(review_redirect(review), status_code=303)


@app.post('/beer/review/{review_id}/delete/')
def delete_review(
    review_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    identity = local_identity(ba_local_member)
    if identity is None:
        raise HTTPException(status_code=401, detail="Member session required")
    review = owned_review(review_id, identity)
    target = review_redirect(review)
    with open_database() as connection:
        connection.execute("DELETE FROM review_helpful WHERE review_id = ?", (review_id,))
        connection.execute(
            "DELETE FROM reviews WHERE id = ? AND account_id = ?",
            (review_id, identity['account_id']),
        )
        connection.commit()
    return RedirectResponse(target, status_code=303)


@app.post('/beer/review/{review_id}/helpful/')
def toggle_review_helpful(
    review_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    identity = local_identity(ba_local_member)
    if identity is None:
        raise HTTPException(status_code=401, detail="Member session required")
    with open_database() as connection:
        review = connection.execute(
            "SELECT * FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
        if review is None:
            raise HTTPException(status_code=404, detail="Review not found")
        existing = connection.execute(
            "SELECT 1 FROM review_helpful WHERE review_id=? AND account_id=?",
            (review_id, identity['account_id']),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO review_helpful (review_id,account_id,created_at) VALUES (?,?,?)",
                (review_id, identity['account_id'], datetime.now(UTC).isoformat()),
            )
        else:
            connection.execute(
                "DELETE FROM review_helpful WHERE review_id=? AND account_id=?",
                (review_id, identity['account_id']),
            )
        connection.commit()
    return RedirectResponse(review_redirect(review), status_code=303)


@app.post('/beer/{beer_id}/save/')
def toggle_saved_beer(
    beer_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    beer = beers_by_id.get(beer_id)
    if beer is None:
        raise HTTPException(status_code=404, detail="Beer not found")
    identity = local_identity(ba_local_member)
    if identity is None:
        raise HTTPException(status_code=401, detail="Member session required")
    with open_database() as connection:
        existing = connection.execute(
            "SELECT 1 FROM saved_beers WHERE account_id=? AND beer_id=?",
            (identity['account_id'], beer_id),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO saved_beers (account_id,beer_id,created_at) VALUES (?,?,?)",
                (identity['account_id'], beer_id, datetime.now(UTC).isoformat()),
            )
        else:
            connection.execute(
                "DELETE FROM saved_beers WHERE account_id=? AND beer_id=?",
                (identity['account_id'], beer_id),
            )
        connection.commit()
    return RedirectResponse(
        f"/beer/profile/{beer['brewery_id']}/{beer['beer_id']}/", status_code=303
    )


@app.get('/beer/share/{beer_id}/')
def share_beer(
    beer_id: int,
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    beer = beers_by_id.get(beer_id)
    if beer is None:
        raise HTTPException(status_code=404, detail="Beer not found")
    permalink = f"/beer/profile/{beer['brewery_id']}/{beer['beer_id']}/"
    body = (
        f"<div class='panel'><h1>Share {html.escape(beer['name'])}</h1>"
        "<p>Use this permalink. No external social service is contacted.</p>"
        f"<label>Permalink<input readonly value='{permalink}'></label>"
        f"<p><a class='button' href='{permalink}'>Open beer</a></p></div>"
    )
    return page('Share Beer | BeerAdvocate', body, local_member(ba_local_member))


@app.get('/beer/compare/')
def compare_beers(
    beer: list[int] = Query(default=[]),
    ba_local_member: str | None = Cookie(default=None, alias=LOCAL_MEMBER_COOKIE),
):
    selected = [beers_by_id.get(beer_id) for beer_id in beer[:4]]
    if any(item is None for item in selected):
        raise HTTPException(status_code=404, detail="Beer not found")
    options = "".join(
        f"<option value='{item['beer_id']}'>{html.escape(item['name'])}</option>"
        for item in beers[:40]
    )
    rows = "".join(
        f"<tr><td><a href='/beer/profile/{item['brewery_id']}/{item['beer_id']}/'>"
        f"{html.escape(item['name'])}</a></td><td>{html.escape(item['brewery'])}</td>"
        f"<td>{html.escape(item['style'])}</td><td>{item['abv']:g}%</td><td>{item['score']}</td></tr>"
        for item in selected if item is not None
    )
    body = (
        "<div class='panel'><h1>Compare Beers</h1><form method='get'>"
        f"<label>First beer<select name='beer'>{options}</select></label>"
        f"<label>Second beer<select name='beer'>{options}</select></label>"
        "<button>Compare</button></form><table id='compare-results'><thead><tr><th>Beer</th><th>Brewery</th>"
        f"<th>Style</th><th>ABV</th><th>Score</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )
    return page('Compare Beers | BeerAdvocate', body, local_member(ba_local_member))
