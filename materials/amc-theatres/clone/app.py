"""Functional, self-contained AMC Theatres WebsiteBench clone."""

from __future__ import annotations

import html
import json
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.site_backend_integration import open_site_services


SITE_ID = "amc-theatres"
DISPLAY_NAME = "AMC Theatres"
backend, auth = open_site_services()
DB_PATH = Path(backend.lifecycle.database_path)
COOKIE = backend.session_cookie["name"]
LOCAL_COOKIE = "websitebench-amc-theatres-session"
app = FastAPI(title=DISPLAY_NAME)


MOVIES = [
    {"slug": "superman", "title": "Superman", "rating": "PG-13", "runtime": "2 HR 9 MIN", "genre": "Action, Adventure", "score": 93, "color": "#1656a0", "tag": "Now Playing", "desc": "A hopeful hero balances his Kryptonian heritage with his human upbringing."},
    {"slug": "jurassic-world-rebirth", "title": "Jurassic World Rebirth", "rating": "PG-13", "runtime": "2 HR 14 MIN", "genre": "Adventure, Thriller", "score": 86, "color": "#1f563a", "tag": "Now Playing", "desc": "An expert team ventures to an isolated equatorial region on a high-stakes mission."},
    {"slug": "f1-the-movie", "title": "F1 The Movie", "rating": "PG-13", "runtime": "2 HR 35 MIN", "genre": "Drama, Sport", "score": 97, "color": "#b51d25", "tag": "Fan Favorite", "desc": "A former racing phenom returns to Formula 1 for one last chance at glory."},
    {"slug": "how-to-train-your-dragon", "title": "How to Train Your Dragon", "rating": "PG", "runtime": "2 HR 5 MIN", "genre": "Family, Fantasy", "score": 95, "color": "#31537b", "tag": "Now Playing", "desc": "A young Viking and a feared dragon form an unlikely friendship."},
    {"slug": "elio", "title": "Elio", "rating": "PG", "runtime": "1 HR 39 MIN", "genre": "Animation, Family", "score": 88, "color": "#6f42a1", "tag": "Now Playing", "desc": "A space-obsessed child is mistaken for Earth's intergalactic ambassador."},
    {"slug": "the-bad-guys-2", "title": "The Bad Guys 2", "rating": "PG", "runtime": "1 HR 44 MIN", "genre": "Animation, Comedy", "score": 91, "color": "#c47220", "tag": "Advance Tickets", "desc": "The reformed crew is pulled into one last globe-trotting heist."},
    {"slug": "the-fantastic-four-first-steps", "title": "The Fantastic Four: First Steps", "rating": "PG-13", "runtime": "1 HR 55 MIN", "genre": "Action, Sci-Fi", "score": 90, "color": "#416a8f", "tag": "Advance Tickets", "desc": "Marvel's first family faces a cosmic threat to their retro-futuristic world."},
    {"slug": "smurfs", "title": "Smurfs", "rating": "PG", "runtime": "1 HR 32 MIN", "genre": "Animation, Comedy", "score": 84, "color": "#3189ce", "tag": "Coming Soon", "desc": "Smurfette leads the crew into the real world to rescue Papa Smurf."},
]

THEATRES = [
    {"slug": "amc-empire-25", "name": "AMC Empire 25", "city": "New York", "state": "NY", "address": "234 West 42nd Street, New York, New York 10036", "miles": 0.2, "features": ["IMAX", "Dolby Cinema", "AMC Signature Recliners"]},
    {"slug": "amc-34th-street-14", "name": "AMC 34th Street 14", "city": "New York", "state": "NY", "address": "312 W 34th St, New York, New York 10001", "miles": 0.7, "features": ["Reserved Seating", "Laser at AMC"]},
    {"slug": "amc-lincoln-square-13", "name": "AMC Lincoln Square 13", "city": "New York", "state": "NY", "address": "1998 Broadway, New York, New York 10023", "miles": 1.1, "features": ["IMAX 70mm", "Dolby Cinema"]},
    {"slug": "amc-village-7", "name": "AMC Village 7", "city": "New York", "state": "NY", "address": "66 Third Ave, New York, New York 10003", "miles": 2.0, "features": ["AMC Signature Recliners", "Open Caption"]},
    {"slug": "amc-century-city-15", "name": "AMC Century City 15", "city": "Los Angeles", "state": "CA", "address": "10250 Santa Monica Blvd, Los Angeles, California 90067", "miles": 3.2, "features": ["IMAX", "Dolby Cinema", "Dine-In Delivery"]},
    {"slug": "amc-river-east-21", "name": "AMC River East 21", "city": "Chicago", "state": "IL", "address": "322 E Illinois St, Chicago, Illinois 60611", "miles": 0.8, "features": ["IMAX", "Reserved Seating"]},
]

SHOWTIMES = ["10:30 AM", "12:15 PM", "1:40 PM", "3:25 PM", "5:10 PM", "7:00 PM", "8:45 PM", "10:15 PM"]


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_site_schema() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS amc_favorites (
              session_token TEXT NOT NULL,
              movie_slug TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(session_token, movie_slug)
            );
            CREATE TABLE IF NOT EXISTS amc_orders (
              order_id TEXT PRIMARY KEY,
              session_token TEXT NOT NULL,
              movie_slug TEXT NOT NULL,
              theatre_slug TEXT NOT NULL,
              showtime TEXT NOT NULL,
              seats_json TEXT NOT NULL,
              total_cents INTEGER NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    if not auth.account_exists("guest@example.com"):
        auth.seed_account(subject_id="amc-demo-member", email="guest@example.com", display_name="AMC Guest", password="demo12345", email_verified=True)


initialize_site_schema()


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def movie(slug: str) -> dict[str, Any] | None:
    return next((item for item in MOVIES if item["slug"] == slug), None)


def theatre(slug: str) -> dict[str, Any] | None:
    return next((item for item in THEATRES if item["slug"] == slug), None)


def cookie_name(request: Request) -> str:
    return COOKIE if request.url.scheme == "https" else LOCAL_COOKIE


def session(request: Request) -> tuple[str, dict[str, Any]]:
    return auth.ensure_session(request.cookies.get(cookie_name(request)))


def with_session(response: HTMLResponse | JSONResponse | RedirectResponse, token: str, request: Request) -> Any:
    name = cookie_name(request)
    if request.cookies.get(name) != token:
        response.set_cookie(name, token, httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/")
    return response


def rotate_site_state(connection: sqlite3.Connection, old_token: str, new_token: str) -> None:
    """Carry anonymous clone state between auth session-owner digests."""

    connection.execute(
        "UPDATE OR IGNORE amc_favorites SET session_token=? WHERE session_token=?",
        (new_token, old_token),
    )
    connection.execute(
        "DELETE FROM amc_favorites WHERE session_token=?",
        (old_token,),
    )
    connection.execute(
        "UPDATE amc_orders SET session_token=? WHERE session_token=?",
        (new_token, old_token),
    )


def user_label(state: dict[str, Any]) -> str:
    account_state = state.get("account") or {}
    return esc(account_state.get("display_name") or "Sign In")


def layout(title: str, body: str, state: dict[str, Any], *, active: str = "") -> str:
    signed_in = bool(state.get("authenticated"))
    account_href = "/account" if signed_in else "/login"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | AMC Theatres</title><link rel="stylesheet" href="/assets/amc.css"></head>
<body><a class="skip" href="#main">Skip to main content</a>
<div class="utility"><div class="wrap"><span>AMC Stubs Members save every Tuesday</span><span>Gift Cards &nbsp; | &nbsp; Offers</span></div></div>
<header><div class="wrap nav"><a class="logo" href="/" aria-label="AMC home"><span>amc</span></a>
<nav aria-label="Primary"><a class="{'on' if active == 'movies' else ''}" href="/movies">Movies</a><a class="{'on' if active == 'theatres' else ''}" href="/movie-theatres">Theatres</a><a class="{'on' if active == 'showtimes' else ''}" href="/showtimes">Showtimes</a><a href="/#offers">Food & Drink</a></nav>
<div class="nav-actions"><button class="icon-button" data-open-search aria-label="Search">⌕</button><a class="account" href="{account_href}">● {user_label(state)}</a></div></div></header>
<div id="search-panel" class="search-panel" hidden><form action="/search"><label for="global-q">Search movies and theatres</label><div><input id="global-q" name="q" placeholder="Try Superman or Empire 25" autofocus><button>Search</button></div></form></div>
<main id="main">{body}</main>
<footer><div class="wrap footer-grid"><div><div class="logo small"><span>amc</span></div><p>Movies make memories.</p></div><div><h3>AMC Theatres</h3><a href="/movies">Movies</a><a href="/movie-theatres">Find a Theatre</a><a href="/showtimes">Showtimes</a></div><div><h3>More</h3><a href="/help">Help Center</a><a href="/account">My AMC</a><a href="/#offers">Offers</a></div></div><p class="copyright">WebsiteBench offline clone · No real purchases are processed.</p></footer>
<div id="toast" role="status" aria-live="polite"></div><script src="/assets/amc.js"></script></body></html>"""


def poster_card(item: dict[str, Any], favorite: bool = False) -> str:
    action = "Remove" if favorite else "Save"
    suffix = " from saved movies" if favorite else ""
    return f"""<article class="movie-card"><a class="poster" style="--poster:{esc(item['color'])}" href="/movies/{esc(item['slug'])}"><span class="poster-kicker">AMC</span><strong>{esc(item['title'])}</strong><small>{esc(item['tag'])}</small></a><div class="card-copy"><p class="eyebrow">{esc(item['rating'])} · {esc(item['runtime'])}</p><h3><a href="/movies/{esc(item['slug'])}">{esc(item['title'])}</a></h3><div class="card-actions"><a class="button compact" href="/showtimes?movie={esc(item['slug'])}">Get Tickets</a><button class="heart {'saved' if favorite else ''}" data-favorite="{esc(item['slug'])}" data-title="{esc(item['title'])}" aria-pressed="{'true' if favorite else 'false'}" aria-label="{action} {esc(item['title'])}{suffix}">♥</button></div></div></article>"""


def favorite_slugs(token: str) -> set[str]:
    owner = auth.session_owner_digest(token)
    with db() as connection:
        return {row[0] for row in connection.execute("SELECT movie_slug FROM amc_favorites WHERE session_token=?", (owner,))}


@app.get("/healthz")
def healthz() -> dict[str, object]:
    with db() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"ok": True, "site_id": SITE_ID, "backend": "sqlite", "payment_adapter": "local-sandbox"}


@app.get("/assets/amc.css")
def css() -> HTMLResponse:
    return HTMLResponse(CSS, media_type="text/css")


@app.get("/assets/amc.js")
def js() -> HTMLResponse:
    return HTMLResponse(JS, media_type="application/javascript")


@app.get("/favicon.ico")
def favicon() -> Response:
    icon = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="30" fill="#d71920"/><text x="32" y="39" text-anchor="middle" font-family="Arial" font-size="22" font-weight="700" fill="white">amc</text></svg>'
    return Response(icon, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    token, state = session(request)
    favorites = favorite_slugs(token)
    cards = "".join(poster_card(item, item["slug"] in favorites) for item in MOVIES[:6])
    body = f"""<section class="hero"><div class="wrap hero-content"><p class="eyebrow light">Experience it in Dolby Cinema</p><h1>See movies<br>the way they were meant to be seen.</h1><p>Reserve your seat for this week's biggest stories.</p><div><a class="button white" href="/showtimes?movie=f1-the-movie">Get Tickets</a><a class="text-link light" href="/movies/f1-the-movie">View details →</a></div></div></section>
<section class="finder"><div class="wrap"><h2>Find a movie at an AMC near you</h2><form action="/showtimes" class="finder-form"><label><span>Movie</span><select name="movie"><option value="">All movies</option>{''.join(f'<option value="{m["slug"]}">{esc(m["title"])}</option>' for m in MOVIES)}</select></label><label><span>Location</span><input name="location" placeholder="City, state or ZIP" value="New York"></label><label><span>Date</span><input name="date" type="date" value="{date.today().isoformat()}"></label><button class="button">Showtimes</button></form></div></section>
<section class="section wrap"><div class="section-heading"><div><p class="eyebrow red">In theatres now</p><h2>Now Playing</h2></div><a href="/movies">View all movies →</a></div><div class="movie-grid">{cards}</div></section>
<section id="offers" class="offers"><div class="wrap offer-grid"><article><span>AMC STUBS</span><h2>Rewards start here</h2><p>Earn points, enjoy free size upgrades and save on Discount Tuesdays.</p><a class="button white" href="/sign-up">Join now</a></article><article><span>PERFECTLY POPPABLE</span><h2>Order ahead</h2><p>Skip the concession line and have your favorites ready when you arrive.</p><a class="button outline-light" href="/showtimes">Choose a showtime</a></article></div></section>"""
    return with_session(HTMLResponse(layout("Movies at AMC", body, state)), token, request)


@app.get("/movies", response_class=HTMLResponse)
def movies(request: Request, q: str = "", genre: str = "All", sort: str = "Featured") -> HTMLResponse:
    token, state = session(request)
    result = list(MOVIES)
    if q:
        result = [m for m in result if q.lower() in (m["title"] + " " + m["genre"]).lower()]
    if genre != "All":
        result = [m for m in result if genre.lower() in m["genre"].lower()]
    if sort == "A-Z":
        result.sort(key=lambda m: m["title"])
    elif sort == "Audience Score":
        result.sort(key=lambda m: m["score"], reverse=True)
    favorites = favorite_slugs(token)
    cards = "".join(poster_card(item, item["slug"] in favorites) for item in result)
    body = f"""<section class="page-head"><div class="wrap"><p class="eyebrow red">AMC Movies</p><h1>Movies at AMC</h1><p>Browse now playing and coming soon titles, then choose your theatre and showtime.</p></div></section><section class="section wrap"><form class="filter-bar"><label>Search<input name="q" value="{esc(q)}" placeholder="Movie title"></label><label>Genre<select name="genre">{''.join(f'<option {"selected" if g == genre else ""}>{g}</option>' for g in ["All","Action","Animation","Family","Comedy","Drama"])}</select></label><label>Sort<select name="sort">{''.join(f'<option {"selected" if s == sort else ""}>{s}</option>' for s in ["Featured","A-Z","Audience Score"])}</select></label><button class="button compact">Apply</button></form><p class="result-count">{len(result)} movies</p><div class="movie-grid">{cards or '<div class="empty"><h2>No movies found</h2><p>Try a broader search or reset the filters.</p><a href="/movies">Reset filters</a></div>'}</div></section>"""
    return with_session(HTMLResponse(layout("Movies", body, state, active="movies")), token, request)


@app.get("/movies/{slug}", response_class=HTMLResponse)
def movie_detail(slug: str, request: Request) -> HTMLResponse:
    token, state = session(request)
    item = movie(slug)
    if item is None:
        return with_session(HTMLResponse(layout("Movie not found", '<section class="empty"><h1>Movie not found</h1><a href="/movies">Browse movies</a></section>', state), status_code=404), token, request)
    times = "".join(f'<a class="showtime" href="/checkout/{esc(slug)}?theatre=amc-empire-25&time={quote(t)}">{esc(t)}</a>' for t in SHOWTIMES[:6])
    saved = slug in favorite_slugs(token)
    body = f"""<section class="detail-hero" style="--poster:{esc(item['color'])}"><div class="wrap detail-grid"><div class="poster large"><span class="poster-kicker">AMC</span><strong>{esc(item['title'])}</strong><small>{esc(item['tag'])}</small></div><div><p class="eyebrow light">{esc(item['tag'])}</p><h1>{esc(item['title'])}</h1><p class="metadata">{esc(item['rating'])} · {esc(item['runtime'])} · {esc(item['genre'])}</p><p class="lede">{esc(item['desc'])}</p><div class="score"><strong>{item['score']}%</strong><span>AMC audience score</span></div><button class="button white heart-detail {'saved' if saved else ''}" data-favorite="{esc(slug)}" data-title="{esc(item['title'])}" aria-pressed="{'true' if saved else 'false'}" aria-label="{'Remove from saved movies' if saved else 'Save to My AMC'}">♥ {'Saved to My AMC' if saved else 'Save to My AMC'}</button></div></div></section><section class="section wrap narrow"><p class="eyebrow red">AMC Empire 25</p><h2>Choose a showtime</h2><p>Today · Reserved seating · Laser at AMC</p><div class="showtime-grid">{times}</div><h2>About the movie</h2><p class="lede dark">{esc(item['desc'])}</p></section>"""
    return with_session(HTMLResponse(layout(item["title"], body, state, active="movies")), token, request)


@app.get("/movie-theatres", response_class=HTMLResponse)
def theatres(request: Request, q: str = "") -> HTMLResponse:
    token, state = session(request)
    result = [t for t in THEATRES if not q or q.lower() in (t["name"] + " " + t["city"] + " " + t["state"] + " " + t["address"]).lower()]
    theatre_cards = "".join(f"""<article class="theatre-card"><div><p class="eyebrow red">{t['miles']} miles away</p><h2><a href="/movie-theatres/{t['state'].lower()}/{t['slug']}">{esc(t['name'])}</a></h2><p>{esc(t['address'])}</p><div class="chips">{''.join(f'<span>{esc(f)}</span>' for f in t['features'])}</div></div><a class="button compact" href="/movie-theatres/{t['state'].lower()}/{t['slug']}">View Showtimes</a></article>""" for t in result)
    body = f"""<section class="page-head dark-head"><div class="wrap"><p class="eyebrow light">Find your AMC</p><h1>Movie Theatres Near You</h1><form class="theatre-search"><input name="q" value="{esc(q)}" placeholder="City, state, ZIP or theatre name"><button class="button white">Search</button></form></div></section><section class="section wrap"><p class="result-count">{len(result)} theatres found</p><div class="theatre-list">{theatre_cards or '<div class="empty"><h2>No theatres found</h2><p>Try a city such as New York, Los Angeles or Chicago.</p></div>'}</div></section>"""
    return with_session(HTMLResponse(layout("Movie Theatres", body, state, active="theatres")), token, request)


@app.get("/movie-theatres/{region}/{slug}", response_class=HTMLResponse)
def theatre_detail(region: str, slug: str, request: Request) -> HTMLResponse:
    del region
    token, state = session(request)
    item = theatre(slug)
    if item is None:
        return with_session(HTMLResponse(layout("Theatre not found", '<section class="empty"><h1>Theatre not found</h1><a href="/movie-theatres">Find a theatre</a></section>', state), status_code=404), token, request)
    listings = []
    for film in MOVIES[:5]:
        times = "".join(f'<a class="showtime" href="/checkout/{film["slug"]}?theatre={slug}&time={quote(t)}">{esc(t)}</a>' for t in SHOWTIMES[:5])
        listings.append(f'<article class="listing"><div><p class="eyebrow">{esc(film["rating"])} · {esc(film["runtime"])}</p><h2><a href="/movies/{film["slug"]}">{esc(film["title"])}</a></h2><p>Reserved seating · Laser at AMC</p></div><div class="showtime-grid">{times}</div></article>')
    body = f"""<section class="page-head theatre-hero"><div class="wrap"><p class="eyebrow light">{esc(item['city'])}, {esc(item['state'])}</p><h1>{esc(item['name'])}</h1><p>{esc(item['address'])}</p><div class="chips light-chips">{''.join(f'<span>{esc(f)}</span>' for f in item['features'])}</div></div></section><section class="section wrap"><div class="date-tabs">{''.join(f'<a class="{"on" if i == 0 else ""}" href="#">{(date.today()+timedelta(days=i)).strftime("%a %b %d")}</a>' for i in range(5))}</div><div class="listing-list">{''.join(listings)}</div></section>"""
    return with_session(HTMLResponse(layout(item["name"], body, state, active="theatres")), token, request)


@app.get("/showtimes", response_class=HTMLResponse)
def showtimes(request: Request, movie: str = "", location: str = "New York", date: str = "") -> HTMLResponse:
    token, state = session(request)
    films = [m for m in MOVIES if not movie or m["slug"] == movie]
    locations = [t for t in THEATRES if location.lower() in (t["city"] + " " + t["state"] + " " + t["address"]).lower()] or THEATRES[:3]
    listings = []
    for venue in locations[:4]:
        film_rows = []
        for film in films[:4]:
            times = "".join(f'<a class="showtime" href="/checkout/{film["slug"]}?theatre={venue["slug"]}&time={quote(t)}">{esc(t)}</a>' for t in SHOWTIMES[:6])
            film_rows.append(f'<div class="showtime-row"><div><h3>{esc(film["title"])}</h3><p>{esc(film["rating"])} · {esc(film["runtime"])}</p></div><div class="showtime-grid">{times}</div></div>')
        listings.append(f'<article class="venue-block"><h2><a href="/movie-theatres/{venue["state"].lower()}/{venue["slug"]}">{esc(venue["name"])}</a></h2><p>{esc(venue["address"])}</p>{"".join(film_rows)}</article>')
    body = f"""<section class="page-head"><div class="wrap"><p class="eyebrow red">Reserve your seats</p><h1>Movie Showtimes</h1><form class="filter-bar showtime-filter"><label>Movie<select name="movie"><option value="">All movies</option>{''.join(f'<option value="{m["slug"]}" {"selected" if m["slug"] == movie else ""}>{esc(m["title"])}</option>' for m in MOVIES)}</select></label><label>Location<input name="location" value="{esc(location)}"></label><label>Date<input type="date" name="date" value="{esc(date or str(__import__('datetime').date.today()))}"></label><button class="button">Update</button></form></div></section><section class="section wrap listing-list">{''.join(listings)}</section>"""
    return with_session(HTMLResponse(layout("Showtimes", body, state, active="showtimes")), token, request)


@app.get("/checkout/{slug}", response_class=HTMLResponse)
def checkout(slug: str, request: Request, theatre: str = "amc-empire-25", time: str = "7:00 PM") -> HTMLResponse:
    token, state = session(request)
    film, venue = movie(slug), globals()["theatre"](theatre)
    if film is None or venue is None:
        return with_session(HTMLResponse(layout("Showtime not found", '<section class="empty"><h1>Showtime not found</h1><a href="/showtimes">Browse showtimes</a></section>', state), status_code=404), token, request)
    seats = "".join(f'<button type="button" class="seat" data-seat="{row}{number}" aria-label="Seat {row}{number}">{row}{number}</button>' for row in "ABCDE" for number in range(1, 9))
    body = f"""<section class="checkout-head"><div class="wrap"><a href="/showtimes">← Back to showtimes</a><h1>{esc(film['title'])}</h1><p>{esc(venue['name'])} · Today at {esc(time)}</p></div></section><section class="checkout-grid wrap"><div><h2>Choose your seats</h2><p>Select up to 8 seats. Reserved seats are held only for this local session.</p><div class="screen">SCREEN</div><div class="seat-map">{seats}</div><div class="seat-legend"><span>□ Available</span><span>■ Selected</span></div></div><aside class="order-card"><h2>Your order</h2><dl><div><dt>Movie</dt><dd>{esc(film['title'])}</dd></div><div><dt>Theatre</dt><dd>{esc(venue['name'])}</dd></div><div><dt>Seats</dt><dd id="selected-seats">None</dd></div><div><dt>Tickets</dt><dd id="ticket-count">0</dd></div><div class="total"><dt>Total</dt><dd id="order-total">$0.00</dd></div></dl><label>Payment simulation<select id="scenario"><option value="sandbox-approved">Simulated approval</option><option value="sandbox-declined">Simulated decline</option><option value="sandbox-retry">Simulated retry</option></select></label><button id="place-order" class="button full" data-movie="{esc(slug)}" data-theatre="{esc(theatre)}" data-time="{esc(time)}" disabled>Complete Sandbox Order</button><p class="fine-print">No card details or real payment are collected.</p></aside></section>"""
    return with_session(HTMLResponse(layout("Choose Seats", body, state)), token, request)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/account") -> HTMLResponse:
    token, state = session(request)
    body = f"""<section class="auth-shell"><div class="auth-card"><p class="eyebrow red">Welcome back</p><h1>Sign in to My AMC</h1><p>Save movies and review your sandbox ticket orders.</p><form id="login-form"><input type="hidden" name="next" value="{esc(next)}"><label>Email<input name="email" type="email" value="guest@example.com" required></label><label>Password<input name="password" type="password" value="demo12345" required></label><button class="button full">Sign In</button><p class="form-message" role="alert"></p></form><p class="auth-switch">New to AMC? <a href="/sign-up">Create an account</a></p><p class="demo-note">Demo: guest@example.com / demo12345</p></div></section>"""
    return with_session(HTMLResponse(layout("Sign In", body, state)), token, request)


@app.get("/sign-up", response_class=HTMLResponse)
def signup_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    body = """<section class="auth-shell"><div class="auth-card"><p class="eyebrow red">AMC Stubs Insider</p><h1>Join for free</h1><p>Create a local demo account to save movies and orders.</p><form id="signup-form"><label>Name<input name="name" required></label><label>Email<input name="email" type="email" required></label><label>Password<input name="password" type="password" minlength="8" required></label><button class="button full">Create Account</button><p class="form-message" role="alert"></p></form><p class="auth-switch">Already a member? <a href="/login">Sign in</a></p></div></section>"""
    return with_session(HTMLResponse(layout("Join AMC Stubs", body, state)), token, request)


@app.get("/account", response_class=HTMLResponse)
def account(request: Request) -> HTMLResponse:
    token, state = session(request)
    if not state.get("authenticated"):
        return with_session(RedirectResponse("/login?next=/account", status_code=303), token, request)
    favorites = favorite_slugs(token)
    cards = "".join(poster_card(m, True) for m in MOVIES if m["slug"] in favorites)
    owner = auth.session_owner_digest(token)
    with db() as connection:
        orders = connection.execute("SELECT * FROM amc_orders WHERE session_token=? ORDER BY created_at DESC", (owner,)).fetchall()
    order_html = "".join(f'<article class="order-row"><div><p class="eyebrow">Order {esc(o["order_id"][-8:])}</p><h3>{esc(movie(o["movie_slug"])["title"] if movie(o["movie_slug"]) else o["movie_slug"])}</h3><p>{esc(theatre(o["theatre_slug"])["name"] if theatre(o["theatre_slug"]) else o["theatre_slug"])} · {esc(o["showtime"])} · Seats {esc(", ".join(json.loads(o["seats_json"])))}</p></div><strong>${o["total_cents"]/100:.2f}<br><span class="status">{esc(o["status"])}</span></strong></article>' for o in orders)
    body = f"""<section class="page-head"><div class="wrap account-head"><div><p class="eyebrow red">My AMC</p><h1>Hello, {user_label(state)}</h1></div><button id="logout" class="button outline">Sign Out</button></div></section><section class="section wrap"><h2>Saved Movies</h2><div class="movie-grid">{cards or '<div class="empty compact-empty"><p>You have no saved movies yet.</p><a href="/movies">Browse movies</a></div>'}</div><div class="section-heading account-orders"><h2>Sandbox Orders</h2></div><div>{order_html or '<div class="empty compact-empty"><p>Your completed sandbox orders will appear here.</p><a href="/showtimes">Find a showtime</a></div>'}</div></section>"""
    return with_session(HTMLResponse(layout("My AMC", body, state)), token, request)


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "") -> HTMLResponse:
    token, state = session(request)
    movies_found = [m for m in MOVIES if q.lower() in (m["title"] + " " + m["genre"]).lower()]
    theatres_found = [t for t in THEATRES if q.lower() in (t["name"] + " " + t["city"] + " " + t["state"]).lower()]
    cards = "".join(poster_card(m, m["slug"] in favorite_slugs(token)) for m in movies_found)
    venue_rows = "".join(f'<article class="theatre-card"><div><h2><a href="/movie-theatres/{t["state"].lower()}/{t["slug"]}">{esc(t["name"])}</a></h2><p>{esc(t["address"])}</p></div></article>' for t in theatres_found)
    body = f"""<section class="page-head"><div class="wrap"><p class="eyebrow red">Search AMC</p><h1>Results for “{esc(q)}”</h1><form class="theatre-search light-search"><input name="q" value="{esc(q)}" required><button class="button">Search</button></form></div></section><section class="section wrap"><h2>Movies ({len(movies_found)})</h2><div class="movie-grid">{cards or '<p>No matching movies.</p>'}</div><h2 class="spaced">Theatres ({len(theatres_found)})</h2><div class="theatre-list">{venue_rows or '<p>No matching theatres.</p>'}</div></section>"""
    return with_session(HTMLResponse(layout("Search", body, state)), token, request)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request) -> HTMLResponse:
    token, state = session(request)
    body = """<section class="page-head"><div class="wrap"><p class="eyebrow red">AMC Help Center</p><h1>How can we help?</h1></div></section><section class="section wrap narrow"><details open><summary>How do sandbox tickets work?</summary><p>Choose a movie, theatre, showtime and seats. Completing an approved simulation stores an order only in this clone's local database.</p></details><details><summary>Can I use a real payment card?</summary><p>No. This WebsiteBench clone never requests or sends real payment information.</p></details><details><summary>How do I save a movie?</summary><p>Use the heart button. Your selection is associated with this browser session and remains visible after refresh.</p></details></section>"""
    return with_session(HTMLResponse(layout("Help Center", body, state)), token, request)


class LoginBody(BaseModel):
    email: str
    password: str


class SignupBody(BaseModel):
    name: str
    email: str
    password: str


class FavoriteBody(BaseModel):
    movie_slug: str


class OrderBody(BaseModel):
    movie_slug: str
    theatre_slug: str
    showtime: str
    seats: list[str]
    scenario: str = "sandbox-approved"


@app.post("/api/login")
def api_login(request: Request, body: LoginBody) -> JSONResponse:
    token, _ = session(request)
    try:
        state = auth.sign_in(
            token,
            email=body.email,
            password=body.password,
            session_rotation_callback=rotate_site_state,
        )
    except Exception:
        return with_session(JSONResponse({"ok": False, "message": "Email or password is incorrect."}, status_code=400), token, request)
    rotated_token = state["session_token"]
    return with_session(JSONResponse({"ok": True, "display_name": state["account"].get("display_name")}), rotated_token, request)


@app.post("/api/signup")
def api_signup(request: Request, body: SignupBody) -> JSONResponse:
    token, _ = session(request)
    if len(body.password) < 8 or "@" not in body.email:
        return with_session(JSONResponse({"ok": False, "message": "Enter a valid email and a password of at least 8 characters."}, status_code=400), token, request)
    if auth.account_exists(body.email):
        return with_session(JSONResponse({"ok": False, "message": "An account with this email already exists."}, status_code=409), token, request)
    try:
        auth.seed_account(subject_id=f"amc-{uuid.uuid4().hex}", email=body.email, display_name=body.name, password=body.password, email_verified=True)
        sign_in_state = auth.sign_in(
            token,
            email=body.email,
            password=body.password,
            session_rotation_callback=rotate_site_state,
        )
    except Exception:
        return with_session(JSONResponse({"ok": False, "message": "Could not create this account."}, status_code=400), token, request)
    return with_session(JSONResponse({"ok": True}), sign_in_state["session_token"], request)


@app.post("/api/logout")
def api_logout(request: Request) -> JSONResponse:
    name = cookie_name(request)
    token = request.cookies.get(name)
    auth.sign_out(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(name, path="/")
    return response


@app.post("/api/favorites")
def api_favorite(request: Request, body: FavoriteBody) -> JSONResponse:
    token, _ = session(request)
    if movie(body.movie_slug) is None:
        return with_session(JSONResponse({"ok": False, "message": "Movie not found."}, status_code=404), token, request)
    owner = auth.session_owner_digest(token)
    with db() as connection:
        exists = connection.execute("SELECT 1 FROM amc_favorites WHERE session_token=? AND movie_slug=?", (owner, body.movie_slug)).fetchone()
        if exists:
            connection.execute("DELETE FROM amc_favorites WHERE session_token=? AND movie_slug=?", (owner, body.movie_slug))
        else:
            connection.execute("INSERT INTO amc_favorites(session_token,movie_slug) VALUES(?,?)", (owner, body.movie_slug))
    return with_session(JSONResponse({"ok": True, "saved": not bool(exists)}), token, request)


@app.post("/api/orders")
def api_order(request: Request, body: OrderBody) -> JSONResponse:
    token, _ = session(request)
    if movie(body.movie_slug) is None or theatre(body.theatre_slug) is None:
        return with_session(JSONResponse({"ok": False, "message": "Movie or theatre not found."}, status_code=404), token, request)
    seats = sorted(set(body.seats))
    if not seats or len(seats) > 8 or any(len(s) not in (2, 3) or s[0] not in "ABCDE" for s in seats):
        return with_session(JSONResponse({"ok": False, "message": "Select between 1 and 8 valid seats."}, status_code=400), token, request)
    if body.scenario == "sandbox-declined":
        return with_session(JSONResponse({"ok": False, "message": "Sandbox payment declined. Choose another simulation."}, status_code=402), token, request)
    if body.scenario == "sandbox-retry":
        return with_session(JSONResponse({"ok": False, "message": "Temporary sandbox error. Please retry."}, status_code=503), token, request)
    if body.scenario != "sandbox-approved":
        return with_session(JSONResponse({"ok": False, "message": "Unknown sandbox scenario."}, status_code=400), token, request)
    order_id = f"AMC-{uuid.uuid4().hex[:12].upper()}"
    total = len(seats) * 1599 + 199
    owner = auth.session_owner_digest(token)
    with db() as connection:
        connection.execute("INSERT INTO amc_orders(order_id,session_token,movie_slug,theatre_slug,showtime,seats_json,total_cents,status) VALUES(?,?,?,?,?,?,?,?)", (order_id, owner, body.movie_slug, body.theatre_slug, body.showtime, json.dumps(seats), total, "approved"))
    return with_session(JSONResponse({"ok": True, "order_id": order_id, "total": f"${total/100:.2f}", "message": "Sandbox order confirmed."}), token, request)


@app.exception_handler(StarletteHTTPException)
def branded_http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse | JSONResponse:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "message": str(exc.detail)}, status_code=exc.status_code)
    if exc.status_code != 404:
        return HTMLResponse(str(exc.detail), status_code=exc.status_code)
    token, state = session(request)
    body = '<section class="empty"><p class="eyebrow red">404</p><h1>We could not find that page</h1><p>Try browsing movies, theatres or current showtimes.</p><a class="button" href="/">Return to AMC home</a></section>'
    return with_session(HTMLResponse(layout("Page Not Found", body, state), status_code=404), token, request)


CSS = r"""
:root{--red:#d71920;--dark:#111;--ink:#1b1b1b;--muted:#656565;--line:#ddd;--cream:#f6f4f0;--max:1180px}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);font-family:Arial,Helvetica,sans-serif;background:#fff}a{color:inherit;text-decoration:none}button,input,select{font:inherit}.wrap{width:min(var(--max),calc(100% - 40px));margin:auto}.skip{position:fixed;top:-60px;left:1rem;z-index:99;background:#fff;padding:12px}.skip:focus{top:10px}.utility{background:#171717;color:#ddd;font-size:12px}.utility .wrap{height:30px;display:flex;align-items:center;justify-content:space-between}header{height:76px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0;z-index:30}.nav{height:100%;display:flex;align-items:center;gap:42px}.logo{display:inline-grid;place-items:center;background:var(--red);color:#fff;border-radius:50%;width:70px;height:48px;font-weight:900;font-size:27px;letter-spacing:-3px;transform:rotate(-5deg)}.logo span{transform:rotate(5deg)}.logo.small{width:62px;height:42px;margin-bottom:20px}.nav nav{display:flex;align-self:stretch}.nav nav a{padding:0 19px;display:flex;align-items:center;font-weight:700;border-bottom:4px solid transparent}.nav nav a:hover,.nav nav a.on{border-color:var(--red)}.nav-actions{margin-left:auto;display:flex;gap:18px;align-items:center}.icon-button{border:0;background:none;font-size:30px;cursor:pointer}.account{font-weight:700}.search-panel{position:fixed;z-index:29;top:106px;left:0;right:0;background:#fff;border-bottom:1px solid #bbb;box-shadow:0 10px 30px #0002;padding:30px}.search-panel form{max-width:760px;margin:auto}.search-panel label{font-weight:700}.search-panel form div,.theatre-search{display:flex;gap:10px;margin-top:10px}.search-panel input,.theatre-search input{flex:1;padding:15px;border:1px solid #999}.search-panel button{background:#222;color:#fff;border:0;padding:0 24px}.hero{min-height:540px;background:radial-gradient(circle at 76% 44%,#376f89 0 5%,#17334f 25%,#07101b 52%,#020304 75%);color:#fff;display:flex;align-items:center;position:relative;overflow:hidden}.hero:after{content:"F1";position:absolute;right:4%;font-size:280px;line-height:1;font-weight:900;font-style:italic;color:#ffffff0c;transform:skew(-10deg)}.hero-content{position:relative;z-index:2}.hero h1{font-size:clamp(43px,6vw,78px);line-height:.95;max-width:800px;margin:12px 0 22px;letter-spacing:-3px}.hero p:not(.eyebrow){font-size:21px;max-width:620px}.eyebrow{text-transform:uppercase;letter-spacing:1.7px;font-size:12px;font-weight:900;color:#555}.eyebrow.red{color:var(--red)}.eyebrow.light{color:#fff}.button{display:inline-flex;align-items:center;justify-content:center;background:var(--red);color:#fff;border:2px solid var(--red);border-radius:2px;padding:14px 22px;font-weight:800;cursor:pointer;min-height:48px}.button:hover{background:#b91016;border-color:#b91016}.button.white{background:#fff;border-color:#fff;color:#111}.button.outline{background:#fff;color:#111;border-color:#222}.button.outline-light{background:transparent;color:#fff;border-color:#fff}.button.compact{padding:9px 13px;min-height:38px;font-size:13px}.button.full{width:100%}.button:disabled{opacity:.45;cursor:not-allowed}.text-link{font-weight:800;margin-left:20px}.text-link.light{color:#fff}.finder{background:var(--cream);padding:30px 0;border-bottom:1px solid #ddd}.finder h2{font-size:24px;margin-top:0}.finder-form,.filter-bar{display:grid;grid-template-columns:1.3fr 1fr 1fr auto;gap:14px;align-items:end}.finder-form label,.filter-bar label,.auth-card label,.order-card label{display:flex;flex-direction:column;gap:7px;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.8px}.finder-form input,.finder-form select,.filter-bar input,.filter-bar select,.auth-card input,.order-card select{height:48px;border:1px solid #aaa;padding:0 12px;background:#fff}.section{padding-top:60px;padding-bottom:70px}.section-heading{display:flex;align-items:end;justify-content:space-between;margin-bottom:25px}.section-heading h2,.section h2{font-size:32px;margin:6px 0}.section-heading a{font-weight:800;color:var(--red)}.movie-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:28px 18px}.poster{aspect-ratio:2/3;background:linear-gradient(155deg,#ffffff18,#0008),var(--poster);color:#fff;display:flex;flex-direction:column;justify-content:flex-end;padding:22px;box-shadow:0 5px 15px #0003;position:relative;overflow:hidden}.poster:before{content:"";position:absolute;width:180px;height:180px;border:40px solid #ffffff10;border-radius:50%;top:-40px;right:-70px}.poster strong{font-size:25px;line-height:1;position:relative;text-transform:uppercase}.poster small{margin-top:12px;position:relative}.poster-kicker{position:absolute;top:20px;left:20px;font-size:14px;font-weight:900;border:2px solid #fff;border-radius:50%;padding:7px}.card-copy{padding:12px 2px}.card-copy h3{margin:4px 0 13px;font-size:18px}.card-actions{display:flex;justify-content:space-between;align-items:center}.heart{border:1px solid #aaa;background:#fff;width:40px;height:38px;font-size:22px;cursor:pointer;color:#777}.heart.saved,.heart-detail.saved{color:var(--red);border-color:var(--red)}.offers{background:#151515;color:#fff;padding:65px 0}.offer-grid{display:grid;grid-template-columns:1fr 1fr;gap:28px}.offer-grid article{padding:45px;background:linear-gradient(135deg,#b4141a,#601014)}.offer-grid article+article{background:linear-gradient(135deg,#5a351c,#17120f)}.offer-grid h2{font-size:38px;margin:12px 0}.offer-grid p{font-size:18px;line-height:1.6}.page-head{background:var(--cream);padding:62px 0 50px;border-bottom:1px solid #ddd}.page-head h1{font-size:54px;letter-spacing:-2px;margin:8px 0}.page-head p{max-width:760px;font-size:18px;line-height:1.55}.dark-head,.theatre-hero{background:#151515;color:#fff}.theatre-search{max-width:720px}.result-count{color:var(--muted);font-weight:700}.filter-bar{padding:22px;background:var(--cream);border:1px solid #ddd}.empty{grid-column:1/-1;text-align:center;padding:70px 20px;background:#f7f7f7}.compact-empty{padding:30px}.detail-hero{background:linear-gradient(115deg,#0c0c0c 20%,var(--poster));color:#fff;padding:70px 0}.detail-grid{display:grid;grid-template-columns:260px 1fr;gap:60px;align-items:center}.poster.large{width:260px}.detail-grid h1{font-size:58px;margin:10px 0}.metadata{font-weight:800}.lede{font-size:19px;line-height:1.65;max-width:700px}.lede.dark{color:#444}.score{display:flex;align-items:center;gap:12px;margin:24px 0}.score strong{font-size:34px}.score span{max-width:90px;font-size:12px;text-transform:uppercase}.narrow{max-width:860px}.showtime-grid{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 40px}.showtime{border:1px solid #222;padding:11px 15px;font-weight:800;background:#fff}.showtime:hover{background:#111;color:#fff}.theatre-list,.listing-list{display:grid;gap:18px}.theatre-card,.venue-block,.listing,.order-row{border:1px solid #d4d4d4;padding:24px;background:#fff}.theatre-card{display:flex;justify-content:space-between;align-items:center;gap:20px}.theatre-card h2,.venue-block h2,.listing h2{margin:4px 0}.chips{display:flex;flex-wrap:wrap;gap:8px}.chips span{background:#eee;padding:7px 10px;font-size:12px;font-weight:700}.light-chips span{background:#ffffff18}.date-tabs{display:flex;overflow:auto;border-bottom:1px solid #aaa;margin-bottom:30px}.date-tabs a{padding:16px 22px;font-weight:800;white-space:nowrap}.date-tabs a.on{color:var(--red);border-bottom:4px solid var(--red)}.listing{display:grid;grid-template-columns:250px 1fr;gap:20px;align-items:center}.venue-block>p{color:#666}.showtime-row{display:grid;grid-template-columns:230px 1fr;gap:20px;padding:25px 0;border-top:1px solid #ddd;align-items:center}.showtime-row h3{margin:0}.showtime-row .showtime-grid{margin:0}.showtime-filter{margin-top:30px}.checkout-head{background:#171717;color:#fff;padding:40px 0}.checkout-head h1{font-size:40px;margin:15px 0 5px}.checkout-grid{display:grid;grid-template-columns:1fr 360px;gap:50px;padding-top:60px;padding-bottom:80px}.screen{background:linear-gradient(#eee,#fff);border-top:8px solid #888;text-align:center;padding:18px;color:#777;letter-spacing:8px;margin:40px 0}.seat-map{display:grid;grid-template-columns:repeat(8,1fr);gap:12px;max-width:640px;margin:auto}.seat{border:2px solid #777;background:#fff;border-radius:8px 8px 3px 3px;height:42px;font-size:11px;cursor:pointer}.seat.selected{background:var(--red);color:#fff;border-color:var(--red)}.seat-legend{display:flex;justify-content:center;gap:30px;margin-top:25px}.order-card{border:1px solid #ccc;padding:25px;align-self:start;position:sticky;top:130px}.order-card h2{margin-top:0}.order-card dl div{display:flex;justify-content:space-between;gap:20px;border-bottom:1px solid #ddd;padding:12px 0}.order-card dt{font-weight:800}.order-card dd{text-align:right;margin:0}.order-card .total{font-size:21px}.fine-print,.demo-note{font-size:12px;color:#666;line-height:1.5}.auth-shell{min-height:680px;background:linear-gradient(135deg,#171717,#4e0e11);padding:65px 20px}.auth-card{background:#fff;max-width:480px;margin:auto;padding:42px;box-shadow:0 20px 60px #0007}.auth-card h1{font-size:38px;margin:8px 0}.auth-card form{display:grid;gap:18px;margin-top:30px}.auth-switch{text-align:center;margin-top:26px}.auth-switch a{color:var(--red);font-weight:800}.form-message{min-height:20px;color:#b00020;margin:0}.account-head{display:flex;justify-content:space-between;align-items:center}.order-row{display:flex;justify-content:space-between;align-items:center}.order-row h3{margin:4px 0}.order-row strong{text-align:right}.status{color:#16733a;text-transform:uppercase;font-size:12px}.account-orders{margin-top:60px}.spaced{margin-top:60px!important}details{border-bottom:1px solid #ccc;padding:20px 0}summary{font-size:20px;font-weight:800;cursor:pointer}details p{line-height:1.7;color:#555}footer{background:#080808;color:#ddd;padding:55px 0 25px}.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:30px}.footer-grid h3{color:#fff}.footer-grid a{display:block;margin:12px 0}.copyright{text-align:center;color:#777;border-top:1px solid #333;margin:35px auto 0;padding-top:20px;font-size:12px}#toast{position:fixed;right:22px;bottom:22px;background:#111;color:#fff;padding:14px 20px;transform:translateY(100px);opacity:0;transition:.25s;z-index:99;max-width:360px}#toast.show{transform:none;opacity:1}@media(max-width:900px){.nav nav{display:none}.movie-grid{grid-template-columns:repeat(2,1fr)}.finder-form,.filter-bar{grid-template-columns:1fr 1fr}.detail-grid,.checkout-grid,.listing,.showtime-row{grid-template-columns:1fr}.order-card{position:static}.offer-grid{grid-template-columns:1fr}}@media(max-width:560px){.utility{display:none}header{top:0}.wrap{width:min(100% - 24px,var(--max))}.nav{gap:12px}.account{font-size:0}.account:before{content:"Account";font-size:14px}.logo{width:57px;height:40px;font-size:23px}.hero{min-height:500px}.hero h1,.page-head h1,.detail-grid h1{font-size:40px}.movie-grid{grid-template-columns:1fr 1fr;gap:20px 10px}.poster{padding:12px}.poster strong{font-size:17px}.poster-kicker{top:10px;left:10px}.finder-form,.filter-bar{grid-template-columns:1fr}.detail-grid{gap:25px}.poster.large{width:210px}.checkout-grid{gap:25px}.seat-map{gap:6px}.seat{font-size:9px}.theatre-card,.order-row{align-items:flex-start;flex-direction:column}.footer-grid{grid-template-columns:1fr 1fr}.footer-grid>div:first-child{grid-column:1/-1}.search-panel{top:76px}}
"""


JS = r"""
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function toast(message){const el=$('#toast');if(!el)return;el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2800)}
$$('[data-open-search]').forEach(b=>b.addEventListener('click',()=>{const p=$('#search-panel');p.hidden=!p.hidden;if(!p.hidden)$('#global-q').focus()}));
$$('[data-favorite]').forEach(button=>button.addEventListener('click',async()=>{const response=await fetch('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({movie_slug:button.dataset.favorite})});const data=await response.json();if(data.ok){button.classList.toggle('saved',data.saved);button.setAttribute('aria-pressed',String(data.saved));const title=button.dataset.title||'movie';button.setAttribute('aria-label',data.saved?`Remove ${title} from saved movies`:`Save ${title}`);if(button.classList.contains('heart-detail'))button.textContent=data.saved?'♥ Saved to My AMC':'♥ Save to My AMC';toast(data.saved?'Saved to My AMC':'Removed from saved movies')}else toast(data.message||'Unable to save')}));
const login=$('#login-form');if(login)login.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(login),response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:f.get('email'),password:f.get('password')})}),data=await response.json();if(data.ok)location.href=f.get('next')||'/account';else $('.form-message',login).textContent=data.message});
const signup=$('#signup-form');if(signup)signup.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(signup),response=await fetch('/api/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:f.get('name'),email:f.get('email'),password:f.get('password')})}),data=await response.json();if(data.ok)location.href='/account';else $('.form-message',signup).textContent=data.message});
const logout=$('#logout');if(logout)logout.addEventListener('click',async()=>{await fetch('/api/logout',{method:'POST'});location.href='/'});
const seats=$$('.seat'),place=$('#place-order');if(place){const render=()=>{const chosen=seats.filter(s=>s.classList.contains('selected')).map(s=>s.dataset.seat);$('#selected-seats').textContent=chosen.join(', ')||'None';$('#ticket-count').textContent=chosen.length;$('#order-total').textContent='$'+((chosen.length*1599+199)/100).toFixed(2);place.disabled=!chosen.length};seats.forEach(seat=>seat.addEventListener('click',()=>{if(!seat.classList.contains('selected')&&seats.filter(s=>s.classList.contains('selected')).length>=8)return toast('Choose up to 8 seats');seat.classList.toggle('selected');render()}));place.addEventListener('click',async()=>{place.disabled=true;const chosen=seats.filter(s=>s.classList.contains('selected')).map(s=>s.dataset.seat),response=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({movie_slug:place.dataset.movie,theatre_slug:place.dataset.theatre,showtime:place.dataset.time,seats:chosen,scenario:$('#scenario').value})}),data=await response.json();if(data.ok){document.querySelector('.checkout-grid').innerHTML=`<div class="empty"><p class="eyebrow red">Order confirmed</p><h1>${data.order_id}</h1><p>Your local sandbox order total is ${data.total}.</p><a class="button" href="/account">View My AMC</a></div>`;toast(data.message)}else{toast(data.message||'Unable to complete order');place.disabled=false}})}
"""
