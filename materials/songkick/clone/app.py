"""Source-grounded, stateful Songkick offline clone."""

from __future__ import annotations

import html
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# StaticFiles derives Content-Type from the stdlib mimetypes table, which does not
# know .webp in every environment; register the frozen asset types explicitly so the
# served MIME matches source-assets/manifest.json.
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("font/woff2", ".woff2")
from pydantic import BaseModel, Field

from backend.site_backend_integration import open_site_services
from backend.songkick_domain import SongkickStore
from websitebench.local_clone_auth import (
    AuthConflict,
    AuthError,
    AuthRateLimited,
    AuthRejected,
    AuthValidationError,
)


SITE_ID = "songkick"
CAPTURE_ID = "songkick-20260904T132056Z-g1-remediation"
ROOT = Path(__file__).resolve().parent
CONTENT: dict[str, Any] = json.loads((ROOT / "content.json").read_text(encoding="utf-8"))
backend, auth = open_site_services()
store = SongkickStore(auth, backend.lifecycle.database_path)
COOKIE = backend.session_cookie["name"]
FIXTURE_COOKIE = "websitebench-songkick-fixture-session"

app = FastAPI(title="Songkick", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


class Registration(BaseModel):
    email: str
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class Credentials(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


class Verification(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class ResetStart(BaseModel):
    email: str


class ResetFinish(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ArtistTracking(BaseModel):
    tracked: bool


class EventState(BaseModel):
    status: Literal["none", "interested", "attended"]


class Preferences(BaseModel):
    location: str = Field(min_length=1, max_length=120)
    theme: Literal["light", "dark"]
    locale: Literal["en", "fr", "es", "de", "pt"]
    cookie_preferences: dict[str, bool] = {}


def token(request: Request) -> str | None:
    value = request.cookies.get(COOKIE)
    if value is not None:
        return value
    if os.environ.get("WEBSITEBENCH_FIXTURE_TOKEN"):
        return request.cookies.get(FIXTURE_COOKIE)
    return None


def set_cookie(response: Response, value: str) -> None:
    if os.environ.get("WEBSITEBENCH_FIXTURE_TOKEN"):
        set_fixture_cookie(response, value)
        return
    response.set_cookie(
        COOKIE,
        value,
        secure=bool(backend.session_cookie["secure"]),
        httponly=True,
        samesite="lax",
        path="/",
    )


def set_fixture_cookie(response: Response, value: str) -> None:
    """Set the isolated verifier cookie on its loopback HTTP transport only."""

    response.set_cookie(
        FIXTURE_COOKIE,
        value,
        secure=False,
        httponly=True,
        samesite="strict",
        path="/",
    )


def ensure_session(request: Request, response: Response) -> tuple[str, dict[str, Any]]:
    supplied = token(request)
    resolved, session = auth.ensure_session(supplied)
    if supplied != resolved:
        set_cookie(response, resolved)
    return resolved, session


@app.exception_handler(AuthError)
async def auth_error(_: Request, exc: AuthError) -> JSONResponse:
    if isinstance(exc, AuthValidationError):
        status = 422
    elif isinstance(exc, AuthConflict):
        status = 409
    elif isinstance(exc, AuthRateLimited):
        status = 429
    elif isinstance(exc, AuthRejected):
        status = 401
    else:
        status = 400
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, AuthRateLimited) else None
    return JSONResponse({"detail": str(exc)}, status_code=status, headers=headers)


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.get("/healthz")
@app.get("/__websitebench/health")
def health() -> dict[str, object]:
    return {"ok": True, "site_id": SITE_ID, "capture_id": CAPTURE_ID}


@app.get("/api/content")
def content() -> dict[str, Any]:
    return CONTENT


@app.get("/api/search")
def search(q: str = "") -> JSONResponse:
    normalized = q.strip().casefold()
    hit = CONTENT["search_states"][0]
    miss = CONTENT["search_states"][1]
    state = hit if normalized and "coldplay" in normalized else miss
    controls = []
    for item in state["controls"]:
        rendered = dict(item)
        href = item.get("href")
        if href:
            rendered["local_path"] = href.get("path", "/concerts")
        controls.append(rendered)
    return JSONResponse(
        {
            "state": state["id"],
            "query": q,
            "dialog_text": state["dialog_text"],
            "result_link_count": state["result_link_count"],
            "controls": controls,
        },
        headers={"X-Songkick-Data-Source": "local-frozen"},
    )


@app.get("/api/auth/session")
def auth_session(request: Request, response: Response) -> dict[str, Any]:
    _, session = ensure_session(request, response)
    return {"authenticated": bool(session["authenticated"]), "account": session["account"]}


@app.post("/api/auth/register/start")
def register_start(payload: Registration, request: Request, response: Response) -> dict[str, Any]:
    session, _ = ensure_session(request, response)
    return auth.start_registration(
        session,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
    )


@app.get("/api/auth/local-mail/{purpose}")
def local_mail(purpose: str, request: Request, response: Response) -> dict[str, Any]:
    session, _ = ensure_session(request, response)
    return {"message": auth.local_mail_for_session(session, purpose=purpose)}


@app.post("/api/auth/register/verify")
def register_verify(payload: Verification, request: Request, response: Response) -> dict[str, Any]:
    session, _ = ensure_session(request, response)
    auth.verify_registration_code(session, payload.code)
    result = auth.complete_registration(session, subject_factory=store.subject_factory)
    set_cookie(response, result["session_token"])
    return {"authenticated": True, "account": result["account"]}


@app.post("/api/auth/sign-in")
def sign_in(payload: Credentials, request: Request, response: Response) -> dict[str, Any]:
    session, _ = ensure_session(request, response)
    result = auth.sign_in(session, email=payload.email, password=payload.password)
    set_cookie(response, result["session_token"])
    return {"authenticated": True, "account": result["account"]}


@app.post("/api/auth/sign-out")
def sign_out(request: Request, response: Response) -> dict[str, bool]:
    auth.sign_out(token(request))
    response.delete_cookie(
        COOKIE,
        path="/",
        secure=bool(backend.session_cookie["secure"]),
        httponly=True,
        samesite="lax",
    )
    if os.environ.get("WEBSITEBENCH_FIXTURE_TOKEN"):
        response.delete_cookie(
            FIXTURE_COOKIE,
            path="/",
            secure=False,
            httponly=True,
            samesite="strict",
        )
    return {"signed_out": True}


@app.post("/api/auth/password-reset/start")
def password_reset_start(payload: ResetStart, request: Request, response: Response) -> dict[str, Any]:
    session, _ = ensure_session(request, response)
    return auth.start_password_reset(session, email=payload.email)


@app.post("/api/auth/password-reset/verify")
def password_reset_verify(payload: Verification, request: Request, response: Response) -> dict[str, bool]:
    session, _ = ensure_session(request, response)
    auth.verify_password_reset_code(session, payload.code)
    return {"verified": True}


@app.post("/api/auth/password-reset/complete")
def password_reset_complete(payload: ResetFinish, request: Request, response: Response) -> dict[str, bool]:
    session, _ = ensure_session(request, response)
    new_token = auth.complete_password_reset(session, new_password=payload.password)
    set_cookie(response, new_token)
    return {"completed": True}


@app.get("/api/me/preferences")
def get_preferences(request: Request) -> dict[str, Any]:
    return store.preferences(token(request))


@app.put("/api/me/preferences")
def put_preferences(payload: Preferences, request: Request) -> dict[str, Any]:
    return store.update_preferences(token(request), **payload.model_dump())


@app.get("/api/me/library")
def library(request: Request) -> dict[str, Any]:
    return store.library(token(request))


@app.put("/api/me/artists/{artist_id}")
def track_artist(artist_id: str, payload: ArtistTracking, request: Request) -> dict[str, Any]:
    return store.set_artist_tracking(token(request), artist_id, payload.tracked)


@app.put("/api/me/events/{event_id}")
def event_state(event_id: str, payload: EventState, request: Request) -> dict[str, Any]:
    return store.set_event_status(token(request), event_id, payload.status)


@app.post("/__websitebench/session")
def fixture_session(request: Request, response: Response) -> dict[str, bool]:
    """Verifier-only session seam; unavailable unless boot explicitly enables it."""

    expected = os.environ.get("WEBSITEBENCH_FIXTURE_TOKEN")
    supplied = request.headers.get("x-websitebench-fixture-token")
    if not expected or supplied != expected:
        return JSONResponse({"detail": "not found"}, status_code=404)
    anonymous, _ = auth.ensure_session(token(request))
    subject_id = "songkick-verifier-fan"
    auth.seed_account(
        subject_id=subject_id,
        email="verifier@songkick.invalid",
        display_name="Songkick verifier",
        password=expected,
    )
    store.ensure_fixture_profile(subject_id)
    result = auth.sign_in(
        anonymous,
        email="verifier@songkick.invalid",
        password=expected,
    )
    set_fixture_cookie(response, result["session_token"])
    return {"authenticated": True}


PAGE_BY_PATH: dict[str, dict[str, Any]] = {}
PAGE_BY_ID: dict[str, dict[str, Any]] = {}
for _page in CONTENT["pages"]:
    PAGE_BY_PATH.setdefault(urlsplit(_page["requested_path"]).path or "/", _page)
    PAGE_BY_ID[_page["id"]] = _page

EXTERNAL_LINK_BY_ID = {item["id"]: item["href"] for item in CONTENT.get("external_links", [])}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def local_href(value: str | None) -> str:
    if not value:
        return "#"
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"}:
        if parsed.hostname in {"songkick.com", "www.songkick.com", "accounts.songkick.com"}:
            if parsed.path == "/blog":
                return "/__external__?destination=" + quote("https://blog.songkick.com/", safe="")
            return (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        return "/__external__?destination=" + quote(value, safe="")
    return value if value.startswith("/") else "#"


def image_asset_for(*needles: str) -> dict[str, str]:
    lowered = [needle.casefold() for needle in needles]
    for item in CONTENT["assets"]["images"]:
        haystack = (item["source_url"] + " " + item["alt"]).casefold()
        if all(needle in haystack for needle in lowered):
            return item
    for item in CONTENT["assets"]["images"]:
        if "default_images/large_avatar/default-artist" in item["source_url"]:
            return item
    return CONTENT["assets"]["images"][0]


def image_for(*needles: str) -> str:
    return image_asset_for(*needles)["local_url"]


def external_anchor(external_id: str, label: str, *, class_name: str = "") -> str:
    """Render a source-native external identity; JS terminates it at the local boundary."""

    class_attr = f' class="{esc(class_name)}"' if class_name else ""
    return (
        f'<a{class_attr} data-wb-external-id="{esc(external_id)}" '
        f'href="{esc(EXTERNAL_LINK_BY_ID[external_id])}">{esc(label)}</a>'
    )


HOME_ARTIST_ASSETS = {
    "108359": "/assets/source/locale-es/108359-large-avatar.jpg",
    "276130": "/assets/source/locale-es/276130-large-avatar.jpg",
    "428874": "/assets/source/locale-es/428874-large-avatar.png",
    "544909": "/assets/source/locale-es/544909-large-avatar.jpg",
    "68043": "/assets/source/locale-es/68043-large-avatar.jpg",
    "8030683": "/assets/source/locale-es/8030683-large-avatar.jpg",
}
for _home_asset in (ROOT / "assets/source/home").glob("*-large-avatar.*"):
    HOME_ARTIST_ASSETS[_home_asset.name.split("-", 1)[0]] = (
        "/assets" + "/source/home/" + _home_asset.name
    )


def contract_control_payload(page: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "id": f'{page["id"]}-{item["id"]}',
            "kind": item.get("kind", ""),
            "text": item.get("text", ""),
            "label": item.get("label", ""),
            "type": item.get("type", ""),
            "source_href": item.get("href", ""),
            "local_href": local_href(item.get("href")) if item.get("href") else "",
            "disabled": bool(item.get("disabled")),
        }
        for item in page.get("controls", [])
        if item.get("contracted")
    ]


def nav(locale: str = "en", concerts_label: str | None = None, page_id: str = "") -> str:
    labels = {
        "en": ("Montreal concerts", "Artists", "Festivals", "Search for events or artists", "Sign up", "Log in"),
        "de": ("Konzerte in deiner Nähe", "Künstler", "Festivals", "Suchen", "Anmelden", "Einloggen"),
        "es": ("Conciertos cerca de ti", "Artistas", "Festivales", "Buscar", "Regístrate", "Iniciar sesión"),
        "fr": ("Concerts à proximité", "Artistes", "Festivals", "Rechercher", "S'inscrire", "Se connecter"),
        "pt": ("Shows perto de você", "Artistas", "Festivais", "Pesquisar", "Inscrever-se", "Entrar"),
    }
    concerts, artists, festivals, search, signup, login = labels.get(locale, labels["en"])
    if concerts_label:
        concerts = concerts_label
    tourbox = (
        external_anchor("external-033", "Tourbox for artists", class_name="public-nav-link")
        if page_id == "home"
        else '<a class="public-nav-link" href="/__external__?destination=https%3A%2F%2Ftourbox.songkick.com%2F">Tourbox for artists</a>'
    )
    return f"""
    <header class="site-header" data-wb-component="global-header">
      <nav class="site-nav shell" data-wb-component="desktop-navigation" aria-label="Primary">
        <a class="logo" href="/" aria-label="Songkick home"><span class="public-brand">Songkick</span><span class="authenticated-brand" hidden>S</span></a>
        <a class="public-nav-link" href="/concerts">{esc(concerts)}</a><a class="public-nav-link" href="/artists">{esc(artists)}</a>
        <a class="public-nav-link" href="/festivals">{esc(festivals)}</a>{tourbox}
        <a class="authenticated-nav-link" data-wb-component="authenticated-navigation" href="/" hidden>Discover</a><a class="authenticated-nav-link" href="/concerts" hidden>Concerts</a><a class="authenticated-nav-link" href="/home" hidden>Plans <b>0</b></a><a class="authenticated-nav-link" href="/artists" hidden>Artists</a><a class="authenticated-nav-link" href="/session/filter_metro_area" hidden>Locations⌄</a>
        <button class="nav-search" id="search-trigger" data-wb-capability="global-search" aria-label="Find concerts" type="button"><span aria-hidden="true">⌕</span> {esc(search)}</button>
        <a class="pink-nav public-nav-link" href="/signup/new">{esc(signup)}</a><a class="public-nav-link" href="/session/new">{esc(login)}</a>
        <button class="account-button" id="account-button" type="button" aria-label="Account" hidden>●</button>
      </nav>
    </header>"""


def search_modal() -> str:
    return """
    <div class="modal-backdrop" id="search-modal" data-wb-component="search-modal" data-search-state="empty" hidden>
      <section class="search-dialog" role="dialog" aria-modal="true" aria-labelledby="search-heading">
        <button class="modal-close" type="button" data-close-search aria-label="Close">×</button>
        <h2 id="search-heading">Search</h2>
        <label for="global-search-input">Search for events by artist, venue or location</label>
        <div class="search-field"><span>⌕</span><input id="global-search-input" autocomplete="off"><input id="global-search-input-aux" tabindex="-1" aria-hidden="true" hidden><button type="button" id="search-clear">Clear</button></div>
        <div id="search-results" aria-live="polite"></div>
      </section>
    </div>
    <div class="account-menu" id="account-menu" data-wb-component="authenticated-account-menu" hidden>
      <strong id="account-name">Your account</strong><a href="/home">Account settings</a>
      <button type="button" id="logout-button" data-wb-capability="auth-logout">Log out</button>
    </div>"""


def home_content(locale: str = "en") -> str:
    localized = {
        "en": ("Your city,<br>your mu<span>sic</span>", "Discover the best live music, tailored to your own music taste", "Sign up", "Trending in", "More in Montreal"),
        "de": ("Deine Stadt,<br>deine Mu<span>sik</span>", "Entdecke die beste Live-Musik, angepasst an deinen eigenen Musikgeschmack", "Anmelden", "Im Trend in", "Mehr in Montreal"),
        "es": ("Tu ciudad,<br>tu mús<span>ica</span>", "Descubre la mejor música en vivo, adaptada a tu propio gusto musical", "Regístrate", "Tendencia en", "Más en Montreal"),
        "fr": ("Ta ville,<br>ta musi<span>que</span>", "Découvre la meilleure musique live, adaptée à tes goûts musicaux", "S'inscrire", "Tendance à", "Plus à Montreal"),
        "pt": ("Sua cidade,<br>sua mú<span>sica</span>", "Descubra a melhor música ao vivo, adaptada ao seu próprio gosto musical", "Inscrever-se", "Em alta em", "Mais em Montreal"),
    }
    headline, tagline, signup, trending, more = localized.get(locale, localized["en"])
    hero = CONTENT["assets"].get("hero") or image_for("large_avatar")
    # The frozen page eagerly loaded artwork for the first seven event cards;
    # later cards stayed text-only until a subsequent carousel state.
    preferred_events = [
        ("68043", "Gorillaz", "/concerts/43080603-gorillaz-at-bell-centre"),
        ("276130", "AC/DC", "/concerts/42871026-acdc-at-parc-jeandrapeau"),
        ("8030683", "Doja Cat", "/concerts/42813883-doja-cat-at-centre-bell"),
        ("108359", "The Black Keys", "/concerts/43040084-black-keys-at-place-bell"),
        ("544909", "Weezer", "/concerts/43123261-weezer-at-place-bell"),
        ("233074", "The Smashing Pumpkins", "/concerts/43221020-smashing-pumpkins-at-bell-centre"),
        ("10112623", "Olivia Rodrigo", "/concerts/43188402-olivia-rodrigo-at-bell-centre"),
        (None, "Olivia Rodrigo", "/concerts/43188401-olivia-rodrigo-at-bell-centre"),
        (None, "Two Door Cinema Club", "/concerts/43101173-two-door-cinema-club-at-mtelus"),
        (None, "Jungle", "/concerts/43119672-jungle-at-place-bell"),
        (None, "Interpol", "/concerts/43189166-interpol-at-lolympia"),
        (None, "Alabama Shakes", "/concerts/43087593-alabama-shakes-at-mtelus"),
        (None, "Metric", "/concerts/43105233-metric-at-place-bell"),
        (None, "Steve Lacy", "/concerts/43365625-steve-lacy-at-place-bell"),
        (None, "Ludovico Einaudi", "/concerts/43275231-ludovico-einaudi-at-maison-symphonique"),
    ]
    popular_artists = [
        ("732760", "Naughty Boy", "/artists/732760-naughty-boy"),
        ("292712", "Kenny Chesney", "/artists/292712-kenny-chesney"),
        ("428874", "Miranda Lambert", "/artists/428874-miranda-lambert"),
        ("371884", "Boyz II Men", "/artists/371884-boyz-ii-men"),
        ("9465704", "Manuel Turizo", "/artists/9465704-manuel-turizo"),
        ("3181021", "Sleeping With Sirens", "/artists/3181021-sleeping-with-sirens"),
        ("5738549", "Cuco", "/artists/5738549-cuco"),
        ("442995", "Switchfoot", "/artists/442995-switchfoot"),
        ("321361", "Duffy", "/artists/321361-duffy"),
        ("407294", "Hunter Hayes", "/artists/407294-hunter-hayes"),
        ("4130211", "Jess Glynne", "/artists/4130211-jess-glynne"),
        ("9734829", "Myke Towers", "/artists/9734829-myke-towers"),
        ("158338", "Chaka Khan", "/artists/158338-chaka-khan"),
        ("2144", "Craig David", "/artists/2144-craig-david"),
        (None, "E-40", "/artists/416142-e40"),
    ]
    biggest_tours = [
        ("941964", "Bruno Mars", "/artists/941964-bruno-mars"),
        ("5820634", "Harry Styles", "/artists/5820634-harry-styles"),
        ("519159", "Chris Brown", "/artists/519159-chris-brown"),
        ("68043", "Gorillaz", "/artists/68043-gorillaz"),
        ("927852", "Tame Impala", "/artists/927852-tame-impala"),
        ("8030683", "Doja Cat", "/artists/8030683-doja-cat"),
        ("832745", "J. Cole", "/artists/832745-j-cole"),
        ("273530", "Usher", "/artists/273530-usher"),
        ("10112623", "Olivia Rodrigo", "/artists/10112623-olivia-rodrigo"),
        ("544909", "Weezer", "/artists/544909-weezer"),
        ("152971", "Tiësto", "/artists/152971-tiesto"),
        ("129375", "Journey", "/artists/129375-journey"),
        ("804901", "Two Door Cinema Club", "/artists/804901-two-door-cinema-club"),
        ("9046429", "Noah Kahan", "/artists/9046429-noah-kahan"),
        ("8589549", "Bryson Tiller", "/artists/8589549-bryson-tiller"),
    ]
    event_control_labels = [
        "Gorillaz Sat 03 Oct Bell Centre Montreal, QC, Canada",
        "AC/DC Sat 12 Sep Parc Jean-Drapeau Montreal, QC, Canada",
        "Doja Cat Fri 27 Nov Centre Bell Montreal, QC, Canada",
        "The Black Keys Fri 16 Oct Place Bell Montreal, QC, Canada",
        "Weezer Sat 26 Sep Place Bell Montreal, QC, Canada",
        "The Smashing Pumpkins Fri 09 Oct Bell Centre Montreal, QC, Canada",
        "Olivia Rodrigo Thu 22 Oct Bell Centre Montreal, QC, Canada",
        "Olivia Rodrigo Wed 21 Oct Bell Centre Montreal, QC, Canada",
        "Two Door Cinema Club Thu 01 Oct MTELUS Montreal, QC, Canada",
        "Jungle Sun 13 Sep Place Bell Montreal, QC, Canada",
        "Interpol Sat 03 Oct L'Olympia Montreal, QC, Canada",
        "Alabama Shakes Tue 15 Sep MTELUS Montreal, QC, Canada",
        "Metric Wed 07 Oct Place Bell Montreal, QC, Canada",
        "Steve Lacy Tue 06 Oct Place Bell Montreal, QC, Canada",
        "Ludovico Einaudi Sun 27 Sep Maison Symphonique Montreal, QC, Canada",
    ]

    def card_image(artist_id: str, label: str, media: str = "") -> str:
        media_attr = f' data-wb-media="{esc(media)}"' if media else ""
        return (
            f'<img{media_attr} src="{esc(HOME_ARTIST_ASSETS[artist_id])}" '
            f'alt="{esc(label)}">'
        )

    event_cards = "".join(
        f'<article class="poster-card"><a href="{esc(path)}">'
        + (
            card_image(artist_id, label, "event-card-images" if index == 0 else "")
            if artist_id else ""
        )
        + f'<span>{esc(label)}</span></a><button class="poster-open" type="button" data-card-href="{esc(path)}" aria-label="{esc(event_control_labels[index] if locale == "en" else label)}">Details</button><button class="poster-interest" type="submit" aria-label="Interested in {esc(label)}">♡</button></article>'
        for index, (artist_id, label, path) in enumerate(preferred_events)
    )
    artist_cards = "".join(
        f'<article class="round-card"><a href="{esc(path)}">'
        + (
            card_image(artist_id, name, "artist-card-images" if index == 0 else "")
            if artist_id else '<span class="entity-artwork-missing" aria-hidden="true"></span>'
        )
        + f'<span>{esc(name)}</span></a><button type="button" data-card-href="{esc(path)}" aria-label="{esc(name)}">Track</button></article>'
        for index, (artist_id, name, path) in enumerate(popular_artists)
    )
    tour_cards = "".join(
        f'<article class="round-card tour-card"><a href="{esc(path)}">{card_image(artist_id, name)}<span>{esc(name)}</span></a><button type="button" data-card-href="{esc(path)}" aria-label="{esc(name)}">Track</button></article>'
        for artist_id, name, path in biggest_tours
    )
    genres = ["Indie & Alt", "Electronic", "Hip-Hop", "Jazz", "Metal", "Pop", "R&B", "Rock"]
    genre_cards = "".join(
        f'<a class="genre-card" href="/genres/{esc(label.lower().replace(" & ", "-").replace(" ", "-"))}">{esc(label)}</a>'
        for label in genres
    )
    dashboard_events = [
        ("Luke Combs, Treaty Oak Revival, Avery Anna", "/assets/source/a0595-large-avatar-5b543e354d.jpg", "Sat 15 May 2027"),
        ("Dinosaur Jr.", "/assets/source/a0871-dashboard-dinosaur-jr-45f76aee46.jpg", "Tue 02 Mar 2027"),
        ("Jonas Brothers", "/assets/source/a0264-large-avatar-ff0798384f.jpg", "Tue 03 Nov 2026"),
        ("Whipped Cream", "/assets/source/a0872-dashboard-whipped-cream-af3c0b0fdb.jpg", "Fri 20 Nov 2026"),
        ("Oso Oso And Liquid Mike", "/assets/source/a0873-dashboard-oso-oso-3668d164fa.jpg", "Thu 05 Nov 2026"),
        ("Katy Nichole And Cade Thompson", "/assets/source/a0874-dashboard-katy-nichole-10211128.jpg", "Sun 01 Nov 2026"),
    ]
    dashboard_cards = "".join(
        f'<a class="dashboard-event" href="/concerts"><img src="{esc(asset)}" alt=""><strong>{esc(name)}</strong><span>{esc(date)}</span><button type="button" aria-label="Interested">♡</button></a>'
        for name, asset, date in dashboard_events
    )
    return f"""
      <div class="home-ad"></div>
      <section class="home-hero" id="home" data-wb-component="home-hero" data-wb-media="home-hero-background" style="--hero:url('{esc(hero)}')">
        <div class="shell hero-inner"><h1>{headline}</h1><div class="swirl" data-wb-media="brand-fonts-and-icons">S</div>
        <button class="hero-theme" id="theme-toggle" data-wb-capability="theme-toggle" aria-label="Softer light background" type="button">☾</button>
        <p>{esc(tagline)}</p><a class="primary-button" href="/signup/new">{esc(signup)}</a><a class="your-artists-link" href="/signup/new?source_product=skweb&amp;metro_area_id=30136&amp;locale=en">Your artists</a></div>
      </section>
      <main class="home-main">
        <section class="dark-section" data-wb-component="home-event-carousel"><div class="section-title"><h2><small>{esc(trending)}</small> Montreal</h2><a data-wb-component="location-banner" href="/metro-areas/27377-canada-montreal">{esc(more)}</a></div><div class="card-row" id="event-carousel">{event_cards}</div><button class="carousel-previous" data-carousel="event-carousel" type="button" aria-label="Previous events" disabled>‹</button><button class="carousel-next" data-carousel="event-carousel" type="button" aria-label="Next events">›</button></section>
        <section class="light-section" data-wb-component="home-artist-carousel"><h2>Most popular in Montreal</h2><a class="more-near-you" href="/metro-areas/27377-canada-montreal">More in Montreal</a><div class="card-row artists" id="artist-carousel">{artist_cards}</div><button class="carousel-previous artist-carousel-previous" data-carousel="artist-carousel" type="button" aria-label="Previous artists" disabled>‹</button><button class="carousel-next artist-carousel-next" data-carousel="artist-carousel" type="button" aria-label="Next artists">›</button></section>
        <section class="home-app-promo"><h2>Get the Songkick app</h2><p>Where artists and fans get more out of live music.</p><a href="/app" aria-label="Get the Songkick app">Get the app</a>{external_anchor("external-023", "App Store")}{external_anchor("external-028", "Google Play")}</section>
        <section class="light-section tour-section" data-wb-component="home-biggest-tours"><h2>Biggest tours of 2026</h2><div class="card-row artists" id="tour-carousel">{tour_cards}</div></section>
        <section class="genre-section" data-wb-component="home-genre-grid"><h2>By genre</h2><div class="genre-grid">{genre_cards}</div></section>
        <nav class="home-shortcuts" aria-label="Artist discovery"><a href="/leaderboards/popular_artists">Most popular artists worldwide</a><a href="/leaderboards/trending_artists">Trending artists worldwide</a><a href="/artists/197928-coldplay">Coldplay</a><a href="/artists/139648-rihanna">Rihanna</a><a href="/artists/4363463-weeknd">The Weeknd</a><a href="/artists/182968-eminem">Eminem</a><a href="/artists/556955-drake">Drake</a><a href="/artists/217815-taylor-swift">Taylor Swift</a><a href="/artists/552177-kanye-west">Kanye West</a><a href="/artists/181875-maroon-5">Maroon 5</a><a href="/artists/974908-lady-gaga">Lady Gaga</a><a href="/artists/10355080-westside-cowboy">Westside Cowboy</a><a href="/artists/10145653-omd">OMD</a><a href="/artists/10188892-mary-in-the-junkyard">Mary In The Junkyard</a><a href="/artists/10256720-manwomanchainsaw">Man/Woman/Chainsaw</a><a href="/artists/25867-stardust">Stardust</a><a href="/live-stream-concerts">Live streams</a><a href="/metro-areas/nearby">Concerts near you</a><a href="/metro-areas/nearby">Concerts near you</a><a href="/session/filter_metro_area">Change location</a><a href="/session/new">Log in to your account</a><a href="/signup/new">Sign up</a><a href="/artists">Popular artists</a><a href="/__external__?destination=https%3A%2F%2Ftourbox.songkick.com%2F">Tourbox for artists</a><a href="/__external__?destination=https%3A%2F%2Ftourbox.songkick.com%2F">Tourbox for artists</a><a href="/metro-areas/nearby" aria-label="More near you">More near you</a><a href="/festivals">Festivals</a><a href="/">English</a><a href="/__external__?destination=https%3A%2F%2Fplay.google.com%2Fstore%2Fapps%2Fdetails">Google Play</a><a href="/metro-areas/nearby/genre/pop">Pop</a></nav>
      </main>
      <section class="authenticated-dashboard" data-wb-component="authenticated-dashboard" hidden><nav><div class="shell"><a href="/session/filter_metro_area">⌖<strong>Your locations</strong>⌄</a><a href="#trending">↗<strong>Trending</strong></a><button class="dashboard-theme" type="button">☾</button></div></nav><main id="trending" class="shell"><h2>Trending concerts in Kansas City, MO, US <a href="/metro-areas/949-us-kansas-city">View more in Kansas City</a></h2><div class="dashboard-events">{dashboard_cards}</div></main></section>"""


def control_links(page: dict[str, Any], contains: str, limit: int = 12) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for control in page["controls"]:
        href = control.get("href") or ""
        text = control["text"] or control["label"]
        key = (href, text)
        if contains in href and text and key not in seen:
            seen.add(key)
            result.append(control)
        if len(result) >= limit:
            break
    return result


def collection_content(page: dict[str, Any], page_number: int = 1) -> str:
    heading = next((item["text"] for item in page["headings"] if item["level"] == 1), page["title"].split("|")[0])
    frozen_event_links = [
        ("Steve Lacy at Place Bell", "/concerts/43365625-steve-lacy-at-place-bell"),
        ("Gipsy Kings at MTELUS", "/concerts/43371713-gipsy-kings-at-mtelus"),
        ("Gorgon City at New City Gas", "/concerts/43381053-gorgon-city-at-new-city-gas"),
        ("YEBBA at L'Olympia", "/concerts/43383403-yebba-at-lolympia"),
        ("Donavon Frankenreiter at Le Ministère", "/concerts/43382897-donavon-frankenreiter-at-le-ministere"),
        ("Salif Keita at Place des Arts", "/concerts/43390372-salif-keita-at-place-des-arts"),
        ("Clara La San at L'Olympia", "/concerts/43371714-clara-la-san-at-lolympia"),
        ("Too Many Zooz at Théâtre Fairmount Theatre", "/concerts/43390357-too-many-zooz-at-theatre-fairmount-theatre"),
        ("I Hate Models at Hall Est Du Stade Olympique", "/concerts/43371710-i-hate-models-at-hall-est-du-stade-olympique"),
        ("Sullivan King at MTELUS", "/concerts/43382670-sullivan-king-at-mtelus"),
    ]
    captured_links = control_links(page, "/concerts/", limit=50) or control_links(page, "/artists/", limit=50) or control_links(page, "/festivals/", limit=50)
    links = (
        [{"text": text, "label": text, "href": href} for text, href in frozen_event_links]
        if page_number == 1
        else captured_links[10:20]
    )
    rows = "".join(
        f'<article class="list-card"><div class="date-tile"><b>{index + 6}</b><span>OCT</span></div><div><h3><a href="{esc(local_href(item["href"]))}">{esc(item["text"] or item["label"])}</a></h3><p>Montreal, QC, Canada</p></div><button type="button" aria-label="Interested">♡</button></article>'
        for index, item in enumerate(links[:10])
    )
    if not rows:
        rows = "".join(f'<article class="list-card"><div><h3>{esc(item["text"])}</h3></div></article>' for item in page["headings"][1:])
    event_count = next(
        (
            item["text"].split()[0]
            for item in page["headings"]
            if item["level"] == 2 and "upcoming concert" in item["text"]
        ),
        "888",
    )
    date_links = [
        ("All", "/metro-areas/27377-canada-montreal"),
        ("Tonight", "/metro-areas/27377-canada-montreal/tonight"),
        ("This weekend", "/metro-areas/27377-canada-montreal/this-weekend"),
        ("This month", "/metro-areas/27377-canada-montreal/this-month"),
        ("Oct", "/metro-areas/27377-canada-montreal/october-2026"),
        ("Nov", "/metro-areas/27377-canada-montreal/november-2026"),
        ("Dec", "/metro-areas/27377-canada-montreal/december-2026"),
        ("2026", "/metro-areas/27377-canada-montreal/2026"),
        ("2027", "/metro-areas/27377-canada-montreal/2027"),
    ]
    date_chips = '<div class="chips">' + "".join(f'<a class="chip{" active" if index == 0 else ""}" href="{href}">{label}</a>' for index, (label, href) in enumerate(date_links)) + '</div>'
    artist_filter = '<p>Filter by artist</p><a class="chip active" href="/metro-areas/27377-canada-montreal">All</a><button type="submit" class="chip spotify">● Your favorite artists</button>'
    genres = [
        ("All", "/metro-areas/27377-canada-montreal"),
        ("Rock", "/metro-areas/27377-canada-montreal/genre/rock"),
        ("Comedy", "/metro-areas/27377-canada-montreal/genre/comedy"),
        ("Pop", "/metro-areas/27377-canada-montreal/genre/pop"),
        ("Hip-Hop", "/metro-areas/27377-canada-montreal/genre/hip-hop"),
        ("R&B", "/metro-areas/27377-canada-montreal/genre/r-and-b"),
        ("Indie & Alt", "/metro-areas/27377-canada-montreal/genre/indie-alternative"),
        ("Electronic", "/metro-areas/27377-canada-montreal/genre/electronic"),
        ("Country", "/metro-areas/27377-canada-montreal/genre/country"),
        ("Classical", "/metro-areas/27377-canada-montreal/genre/classical"),
        ("Metal", "/metro-areas/27377-canada-montreal/genre/metal"),
        ("Latin", "/metro-areas/27377-canada-montreal/genre/latin"),
        ("Folk & Blues", "/metro-areas/27377-canada-montreal/genre/folk"),
        ("Jazz", "/metro-areas/27377-canada-montreal/genre/jazz"),
        ("Funk & Soul", "/metro-areas/27377-canada-montreal/genre/funk-soul"),
        ("Reggae", "/metro-areas/27377-canada-montreal/genre/reggae"),
    ]
    genre_filter = '<div data-wb-component="genre-filter"><p>Filter by genre</p><div class="chips">' + "".join(f'<a class="chip" href="{href}">{label}</a>' for label, href in genres) + "</div></div>"
    compact_date = page["id"] in {
        "montreal-today",
        "montreal-next-7-days",
        "montreal-next-30-days",
    }
    if compact_date:
        filters = f'<p>Filter by date</p>{date_chips}<hr>{artist_filter}<hr>{genre_filter.replace("<p>Filter by genre</p>", "")}'
    else:
        date_inputs = '<div class="date-inputs"><input type="text" aria-label="From" placeholder="▣  From"><input type="text" aria-label="To" placeholder="▣  To"><input type="submit" aria-label="Apply date range" value="⌕"></div>'
        filters = f"{artist_filter}<hr><p>Filter by date</p>{date_chips}{date_inputs}<hr>{genre_filter}"
    return f"""
      <div class="top-ad"></div><main class="shell content-shell">
      <h1>{esc(heading)}</h1><p>Find tickets to all live music, concerts, tour dates and festivals in and around your city.</p>
      <p>Currently there are <strong>{esc(event_count)}</strong> upcoming events.</p>
      <nav class="collection-shortcuts" aria-label="Upcoming periods"><a href="/en/metro-areas/27377-canada-montreal">Today ·</a><a href="/en/metro-areas/27377-canada-montreal">Next 7 days ·</a><a href="/en/metro-areas/27377-canada-montreal">Next 30 days</a></nav>
      <section class="filter-panel" data-wb-component="date-filter">{filters}</section>
      <section class="event-list" data-wb-component="event-list"><h2>{esc(page["headings"][1]["text"] if len(page["headings"]) > 1 else "Upcoming events")}</h2>{rows}</section>
      <nav class="pagination" aria-label="Pagination" data-wb-capability="collection-pagination"><a href="?page=1">Previous</a><a class="{'active' if page_number == 1 else ''}" href="?page=1">1</a><a class="{'active' if page_number == 2 else ''}" href="?page=2">2</a><a href="?page=2">Next</a></nav>
      </main>"""


def genre_content() -> str:
    hero_url = "/assets/source/a0875-genre-rock-brief-6726a0ae21.webp"
    featured = [
        ("Steve Lacy", "/concerts/43365625-steve-lacy-at-place-bell"),
        ("Gipsy Kings", "/concerts/43371713-gipsy-kings-at-mtelus"),
        ("Gorgon City", "/concerts/43381053-gorgon-city-at-new-city-gas"),
        ("YEBBA", "/concerts/43383403-yebba-at-lolympia"),
        ("Sullivan King", "/concerts/43382670-sullivan-king-at-mtelus"),
    ]
    cards = "".join(
        f'<a class="genre-event-card" href="{esc(path)}"><img src="{esc(image_for(name, "large_avatar"))}" alt=""><strong>{esc(name)}</strong><span>Montreal</span></a>'
        for name, path in featured
    )
    return f"""
      <main class="genre-landing" data-wb-component="genre-landing">
        <section class="genre-guide-hero"><img src="{hero_url}" data-source-asset="https://www.songkick.com/images/nw/components/genres/rock.webp" alt="Rock musician performing"><div class="shell"><div class="genre-guide-copy"><h1 aria-label="Your ultimate Rock concert guide">Your ultimate Rock<br>concert guide</h1><p>Lighters up - you’ve come to the home of high voltage rock. Discover the best, biggest and shreddiest rock concerts near you in 2023. Catch up with everything you need to know about the rock music scene, from the best venues to trending new rock artists. From hard rock to pop punk to new wave, we’ve got you covered.</p></div></div></section>
        <section class="shell genre-guide-body"><h2>Top Rock Concerts in Montreal</h2><div class="genre-trending"><h3>Trending concerts near you</h3><a href="/metro-areas/nearby/genre/rock">Rock concerts near you</a><div class="genre-event-row">{cards}</div></div><h2>Top rock venues worldwide</h2><h2>Top cities for Rock events worldwide</h2><h2>Trending Rock Artists</h2></section>
      </main>"""


def concerts_content(_: dict[str, Any]) -> str:
    events = [
        ("Louis-Jean Cormier", "/concerts/43203206-louisjean-cormier-at-bieres-et-saveurs"),
        ("GreenWoodz", "/concerts/43216570-greenwoodz-at-place-bourget"),
        ("Andréanne A. Malette", "/concerts/43234983-andreanne-a-malette-at-festival-belle-banlieue"),
        ("Julyan", "/concerts/43308709-julyan-at-laval-en-folie"),
        ("La Grand-Messe", "/concerts/43316120-la-grandmesse-at-laval-en-folie"),
    ]
    cards = "".join(
        f'<a class="concerts-ticket-card" href="{esc(path)}"><img src="{esc(image_asset_for(name, "large_avatar")["local_url"])}" alt="{esc(name)}"><small>OUTDOORS</small><strong>{esc(name)}</strong></a>'
        for name, path in events
    )
    return f"""
      <main class="concerts-landing" data-wb-component="concerts-landing">
        <section class="concerts-brief"><div class="shell"><h1>Take your pick from<br>the best concerts in<br>your area</h1><p>With every concert in every city, find the perfect concert<br>based on your music taste with a free Songkick account.</p><a class="primary-button" href="/signup/new">Find my favorite artists&nbsp; →</a></div></section>
        <section class="concerts-picks"><div class="shell"><h2>The hottest tickets in Montreal</h2><div class="concerts-feature"><h3>Outdoor concerts</h3><div class="concerts-ticket-row">{cards}</div></div></div></section>
      </main>"""


def artists_content(_: dict[str, Any]) -> str:
    artists = [
        ("Coldplay", "/artists/197928-coldplay"),
        ("Rihanna", "/artists/139648-rihanna"),
        ("The Weeknd", "/artists/4363463-weeknd"),
        ("Eminem", "/artists/182968-eminem"),
        ("Drake", "/artists/556955-drake"),
        ("Taylor Swift", "/artists/217815-taylor-swift"),
        ("Bruno Mars", "/artists/941964-bruno-mars"),
        ("Kanye West", "/artists/552177-kanye-west"),
        ("Maroon 5", "/artists/181875-maroon-5"),
        ("Lady Gaga", "/artists/974908-lady-gaga"),
    ]
    cards = []
    for index, (name, path) in enumerate(artists, start=1):
        asset = image_asset_for(name, "huge_avatar")
        cards.append(
            f'<a class="leader-card" href="{esc(path)}"><img data-wb-media="{"artist-card-images" if index == 1 else ""}" src="{esc(asset["local_url"])}" alt="{esc(name)}"><small>{index}</small><strong>{esc(name)}</strong></a>'
        )
    return f"""
      <main data-wb-component="artist-list">
        <section class="artists-intro"><div class="shell"><h1>Discover concerts for<br>your favorite artists</h1><p>Be the first to know about concerts, tour announcements<br>&amp; news based on the music you love</p><a class="primary-button" href="/signup/new">Find my favorite artists →</a></div></section>
        <section class="shell leaderboards"><h2>Artist Leaderboards</h2><div class="leader-row"><div class="leader-copy"><h3>Most popular<br>artists worldwide</h3><p>Discover who fans are tracking now.</p><a href="/leaderboards/popular_artists">View more artists</a></div>{''.join(cards)}</div>
        <h2>Who’s trending right now?</h2><p>Follow rising artists and receive local concert alerts.</p><a href="/leaderboards/trending_artists">Trending artists worldwide</a></section>
      </main>"""


def venue_content(page: dict[str, Any]) -> str:
    name = next((item["text"] for item in page["headings"] if item["level"] == 1), "Venue")
    venue_id = numeric_id(page["requested_path"], "/venues/")
    asset = image_asset_for(f"venues/{venue_id}/", "col2")
    location = "Laval, QC, Canada" if venue_id == "3536914" else "Montreal, QC, Canada"
    upcoming = next(
        (item["text"].split(" ", 1)[0] for item in page["controls"] if item["text"].endswith("Upcoming concerts")),
        "0",
    )
    past = next(
        (item["text"].split(" ", 1)[0] for item in page["controls"] if item["text"].endswith("Past concerts")),
        "0",
    )
    count_index = next(
        (index for index, item in enumerate(page["controls"]) if item["text"].endswith("Past concerts")),
        0,
    )
    specific_page = dict(page)
    specific_page["controls"] = page["controls"][count_index + 1 :]
    rows = []
    seen_concerts: set[str] = set()
    for item in specific_page["controls"]:
        href = item.get("href") or ""
        label = (item.get("text") or item.get("label") or "").strip()
        if "/concerts/" not in href or label.upper() == "BUY TICKETS" or href in seen_concerts:
            continue
        seen_concerts.add(href)
        rows.append(item)
        if len(rows) == 4:
            break
    venue_dates = {
        "20838": ["Thursday 03 September 2026", "Friday 11 September 2026"],
        "4016319": ["Wednesday 09 September 2026", "Thursday 10 September 2026"],
        "1086866": ["Saturday 05 September 2026", "Saturday 12 September 2026"],
        "4661630": ["Saturday 14 November 2026"],
    }
    concert_rows = []
    for index, item in enumerate(rows):
        artist_name = item["text"] or "Live concert"
        avatar = image_asset_for(artist_name, "large_avatar")["local_url"]
        reminder = '<div class="legacy-reminder"><strong>Don’t miss out.</strong><span>Save this event to your plans and we\'ll remind you when it\'s coming up!</span></div>' if index == 0 else ""
        dates = venue_dates.get(venue_id, [])
        event_date = dates[index] if index < len(dates) else ("Wednesday 09 September 2026" if index == 0 else "Saturday 12 September 2026")
        concert_rows.append(
            f'<article class="legacy-event"><img class="legacy-event-avatar" src="{esc(avatar)}" alt=""><p><strong>{esc(event_date)}</strong></p><h3><a href="{esc(local_href(item["href"]))}">{esc(artist_name)}</a></h3><p><a href="{esc(page["requested_path"])}">{esc(name)}</a>, {esc(location)}</p><div><a class="buy-button" href="/__external__?destination=Ticketmaster%20CA">BUY TICKETS</a><button data-event-status="interested" data-event-id="{index}">INTERESTED</button><button data-event-status="attended" data-event-id="{index}">GOING</button></div>{reminder}</article>'
        )
    concerts = "".join(concert_rows)
    empty_image = venue_id == "4661630"
    hero_image = "" if empty_image else f'<img src="{esc(asset["local_url"])}" alt="{esc(name)}">'
    venue_theme = "empty" if empty_image else "photo"
    see_all = '<a href="#all">See all ›</a>' if any(item["text"] == "See all" for item in page["controls"]) else ""
    directions_ids = {
        "venue-new-city-gas": "external-003",
        "venue-place-des-arts": "external-004",
        "venue-mtelus": "external-005",
        "venue-lolympia": "external-006",
        "venue-theatre-fairmount": "external-007",
        "venue-le-ministere": "external-008",
        "venue-detail": "external-009",
        "venue-place-bell": "external-009",
        "venue-hall-est-stade-olympique": "external-010",
    }
    directions_id = directions_ids.get(page["id"])
    directions = external_anchor(directions_id, "➤ Get directions") if directions_id else ""
    address_copy = (
        "⌖&nbsp; 4545, avenue Pierre-De Coubertin, H1V0B2, Montreal, QC, Canada "
        if empty_image else ""
    )
    address = f'<section class="venue-address"><div class="shell">{address_copy}{directions}<button type="submit" data-wb-capability="event-going">GOING</button><button type="submit" data-wb-capability="event-was-there">I WAS THERE</button></div></section>'
    return f"""
      <div class="top-ad"></div><main data-wb-component="venue-profile">
      <section class="venue-hero" data-venue-theme="{venue_theme}" data-wb-media="venue-map-static-treatment"><div class="shell venue-grid"><div><h1>{esc(name)}</h1><h2>⌖ {esc(location)} <span>›</span></h2><div class="venue-counts"><div><b>{esc(upcoming)}</b><small>Upcoming concerts</small></div><div><b>{esc(past)}</b><small>Past concerts</small></div></div></div>{hero_image}</div></section>
      <section class="shell legacy-events"><h2>Upcoming concerts {see_all}</h2>{concerts}</section>{address}</main>"""


def festivals_content(_: dict[str, Any]) -> str:
    countries = ["🇺🇸 US", "🇬🇧 UK", "🇦🇺 Australia", "🇩🇪 Germany", "🇨🇦 Canada", "🇧🇷 Brazil", "🇮🇩 Indonesia", "🇪🇸 Spain", "🇳🇱 Netherlands", "🇫🇷 France", "🇹🇷 Turkey", "🇲🇽 Mexico", "🇸🇪 Sweden", "🇮🇹 Italy", "🇦🇷 Argentina", "🇮🇪 Ireland", "🇧🇪 Belgium"]
    return f"""
      <main class="shell festival-finder" data-wb-component="festival-list"><section class="festival-splash"><h1>Find your perfect festival in<br>Canada</h1><h3>Discover the best music festival for you and get tickets.</h3><a class="primary-button" href="#countries">FIND A FESTIVAL</a></section>
      <section id="countries"><h2>Find festivals by country</h2><div class="country-chips">{''.join(f'<button type="button">{esc(country)}</button>' for country in countries)}</div></section>
      <section class="festival-featured"><h2>Popular festivals in Canada</h2><div class="festival-pages" aria-label="Featured festival pages"><button type="button" aria-label="2 of 5">2</button><button type="button" aria-label="3 of 5">3</button><button type="button" aria-label="4 of 5">4</button><button type="button" aria-label="5 of 5">5</button></div><article><a href="/festivals/3556859-music4cancer/id/43273560-music4cancer-2026">Music4Cancer 2026</a><button type="submit">GOING</button></article><article><a href="/festivals/2471479-de-montgolfieres-de-gatineau/id/43145267-festival-de-montgolfires-de-gatineau-2026">Festival de montgolfières de Gatineau 2026</a></article><article><a href="/festivals/3780431-sammy-virji-parc-jeandrapeau/id/43155807-sammy-virji--parc-jeandrapeau-2026">Sammy Virji @ Parc Jean-Drapeau 2026</a></article></section></main>"""


def festival_content(page: dict[str, Any]) -> str:
    name = next((item["text"] for item in page["headings"] if item["level"] == 1), "Festival")
    event_id = page["requested_path"].rstrip("/").split("/")[-1].split("-", 1)[0]
    asset = image_asset_for(f"events/{event_id}/", "huge_avatar")
    return f"""
      <div class="top-ad"></div><main class="shell event-page festival-profile" data-wb-component="festival-profile"><a class="event-flag" href="https://support.songkick.com/hc/en-us/requests/new" data-wb-external-id="external-031">Flag a problem</a>
      <section class="event-hero festival-hero"><div class="event-summary"><h1>{esc(name)}</h1><p class="lineup-copy">with <strong>Bad Religion, Face To Face, Guttermouth, Teenage Bottlerocket, A Wilhelm Scream, Death By Stereo, Satanic Surfers, MakeWar</strong>, and more…</p><button class="event-interest" id="event-interest" data-event-id="{esc(event_id)}" data-wb-capability="event-interest">♡ Interested</button><p><strong>25</strong> RSVPs</p><div class="event-facts"><p>▣ Thursday 10 September 2026 – Saturday 12 September 2026</p><p>⌖ Hôtel de Ville de Sainte-Thérèse, Sainte-Thérèse, QC, Canada</p></div></div><img data-wb-media="festival-artwork" src="{esc(asset["local_url"])}" alt="{esc(name)}"></section>
      <div class="event-columns"><section><div class="event-jumps"><button>Line-up</button><button>Venue</button><button>Reviews</button><button>More events</button></div><div class="sale-bar"><span>On sale for 2 months</span><b>Event is in 1 week</b></div><h2>Line-up</h2><div class="white-card"><h3><a href="/artists/70768-bad-religion">Bad Religion</a> · Face To Face · Guttermouth</h3></div></section>
      <aside class="tickets"><h2>Buy tickets</h2><div class="ticket-item"><strong>Bad Religion</strong><span>10 September 2026 – 12 September 2026</span></div><a href="/__external__?destination=Festival%20Website">Festival Website <small>On sale now</small> ›</a></aside></div></main>"""


def location_content(_: dict[str, Any], state: str = "") -> str:
    columns = {
        "Popular US locations": ["SF Bay Area, CA, US", "Los Angeles (LA), CA, US", "New York (NYC), NY, US", "Portland, OR, US", "Washington, DC, US", "Philadelphia, PA, US", "Seattle, WA, US", "Chicago, IL, US", "Orlando, FL, US", "Pittsburgh, PA, US"],
        "Popular UK locations": ["London, UK", "Manchester, UK", "Glasgow, UK", "Edinburgh, UK", "Birmingham, UK", "Newcastle Upon Tyne, UK", "Bristol, UK", "Belfast, UK", "Brighton, UK", "Liverpool, UK"],
        "Popular EU locations": ["Berlin, Germany", "Paris, France", "Amsterdam, Netherlands", "Barcelona, Spain", "Copenhagen, Denmark", "Stockholm, Sweden", "Dublin, Ireland", "Prague, Czech Republic", "Rome, Italy", "Budapest, Hungary"],
    }
    region_paths = {
        "SF Bay Area, CA, US": "/metro-areas/26330-us-sf-bay-area",
        "Los Angeles (LA), CA, US": "/metro-areas/17835-us-los-angeles-la",
        "New York (NYC), NY, US": "/metro-areas/7644-us-new-york-nyc",
        "Portland, OR, US": "/metro-areas/12283-us-portland",
        "Washington, DC, US": "/metro-areas/1409-us-washington",
        "Philadelphia, PA, US": "/metro-areas/5202-us-philadelphia",
        "Seattle, WA, US": "/metro-areas/2846-us-seattle",
        "Chicago, IL, US": "/metro-areas/9426-us-chicago",
        "Orlando, FL, US": "/metro-areas/3733-us-orlando",
        "Pittsburgh, PA, US": "/metro-areas/22443-us-pittsburgh",
    }
    groups = []
    for title, cities in columns.items():
        choices = "".join(
            f'<li><a href="{esc(region_paths[city])}">{esc(city)}</a></li>' if city in region_paths
            else f'<li><button type="button" data-location="{esc(city)}">{esc(city)}</button></li>'
            for city in cities
        )
        groups.append(f'<section><h2>{esc(title)}</h2><ol>{choices}</ol></section>')
    search_value = "Toronto" if state == "search-toronto" else "zzzzsongkicknoresult" if state == "search-empty" else ""
    if state == "search-toronto":
        locations = [("Toronto, ON, Canada", ""), ("Newcastle, NSW, Australia", "Toronto"), ("Toronto, ON, Canada", "New Toronto"), ("Toronto, MI, US", ""), ("Wichita, KS, US", "Toronto"), ("Toronto, OH, US", "")]
        result = '<p class="location-result-summary">There are 6 locations that match “Toronto”.</p>' + "".join(
            f'<article class="location-result-row"><i aria-hidden="true">●</i><div><a href="#">{esc(city)}</a>{" <span>" + esc(alias) + "</span>" if alias else ""}<button type="button" data-location="{esc(city)}">SAVE LOCATION</button></div></article>'
            for city, alias in locations
        )
    elif state == "search-empty":
        result = '<div class="location-no-results"><h2>Sorry, we found no results for “zzzzsongkicknoresult”.</h2><strong>Suggestions:</strong><p>Try searching for a larger city near you. You can’t save your location to a country or state. If you searched for a zip code or postcode, we don’t accept those yet. Try searching for a city.</p></div>'
    else:
        result = ""
    return f"""
      <main class="shell location-page" data-wb-component="location-picker"><h1>Change location <small>(Montreal, QC, Canada)</small></h1><form id="location-form"><input type="text" id="location-query" name="location" aria-label="Location" value="{esc(search_value)}"><button type="submit">SEARCH</button></form><div id="location-results" role="status">{result}</div><div class="location-columns">{''.join(groups)}</div></main>"""


def numeric_id(path: str, marker: str) -> str:
    tail = path.split(marker, 1)[1] if marker in path else "0"
    return tail.split("-", 1)[0].split("/", 1)[0]


def artist_content(page: dict[str, Any]) -> str:
    name = next((item["text"] for item in page["headings"] if item["level"] == 1), "Artist")
    artist_id = numeric_id(page["requested_path"], "/artists/")
    photo = image_for(f"artists/{artist_id}/", "huge_avatar")
    source_profiles = {
        "10355080": ("westside-cowboy", "On tour", "12,698", "24", "24", "SEP", "Dublin, Ireland", "Whelan's", "26"),
        "197928": ("coldplay", "Off tour", "4,588,396", "0", "", "", "", "", ""),
        "139648": ("rihanna", "Off tour", "4,545,791", "0", "", "", "", "", ""),
        "4363463": ("the-weeknd", "On tour", "4,345,205", "10", "05", "SEP", "Lisbon, Portugal", "Estádio do Restelo", "356"),
        "182968": ("eminem", "Off tour", "4,226,051", "0", "", "", "", "", ""),
        "556955": ("drake", "Off tour", "4,094,616", "0", "", "", "", "", ""),
        "217815": ("taylor-swift", "Off tour", "4,073,840", "0", "", "", "", "", ""),
        "941964": ("bruno-mars", "On tour", "3,913,689", "31", "05", "SEP", "Foxborough, MA, US", "Gillette Stadium", "90"),
        "552177": ("kanye-west", "Off tour", "3,749,872", "0", "", "", "", "", ""),
        "181875": ("maroon-5", "On tour", "3,670,290", "8", "05–13", "SEP", "Rio de Janeiro, Brazil", "Rock In Rio", "783"),
        "974908": ("lady-gaga", "Off tour", "3,621,923", "0", "", "", "", "", ""),
    }
    theme, tour_status, fans, upcoming, event_day, event_month, event_city, event_venue, rsvps = source_profiles.get(
        artist_id,
        ("westside-cowboy", "On tour", "12,698", "24", "24", "SEP", "Dublin, Ireland", "Whelan's", "26"),
    )
    status_class = "on-tour" if tour_status == "On tour" else "off-tour"
    if upcoming == "0":
        events = '<article class="artist-empty-card">No upcoming concerts</article>'
    else:
        event_path = "/concerts/43372779-westside-cowboy-at-whelans" if artist_id == "10355080" else f"/concerts/{artist_id}-upcoming"
        # Source rows beyond the first are captured as link identities only: content.json
        # records their city/venue/href but no per-row date or RSVP count, so those cells
        # are omitted rather than invented. Full 24-row parity remains unreproduced.
        extra_rows = (
            [("Nijmegen, Netherlands", "Doornroosje", "/concerts/43130338-westside-cowboy-at-doornroosje")]
            if artist_id == "10355080"
            else []
        )
        events = f'''<article class="list-card artist-event-card"><div class="artist-event-thumb"><img src="{esc(photo)}" alt=""><b>{esc(event_day)}</b><span>{esc(event_month)}</span></div><div><h3><a href="{esc(event_path)}">{esc(event_city)} {esc(event_venue)}</a></h3><p>{esc(event_venue)}</p></div><strong>{esc(rsvps)} <small>RSVPs</small></strong><button aria-label="Mark as interested">♡</button><i aria-hidden="true">›</i></article>'''
        events += "".join(
            f'''<article class="list-card artist-event-card"><div class="artist-event-thumb"><img src="{esc(photo)}" alt=""></div><div><h3><a href="{esc(row_path)}">{esc(row_city)} {esc(row_venue)}</a></h3><p>{esc(row_venue)}</p></div><button aria-label="Mark as interested">♡</button><i aria-hidden="true">›</i></article>'''
            for row_city, row_venue, row_path in extra_rows
        )
    return f"""
      <div class="artist-top-gap"></div><main class="artist-page" data-wb-component="artist-profile" data-artist-theme="{esc(theme)}">
      <section class="artist-hero"><div><h1>{esc(name)}</h1><span class="{status_class}">{esc(tour_status)}</span><div class="artist-actions"><button class="outline-dark" id="track-artist" data-artist-id="{esc(artist_id)}" data-wb-capability="artist-tracking">☆ <span>Track artist</span></button><span class="pink-ribbon">Get notified when they play near you.</span></div><p>{esc(fans)} fans get concert alerts for this artist.</p></div><img data-wb-media="artist-header-image" src="{esc(photo)}" alt="{esc(name)}"></section>
      <section class="nearest"><h2>Nearest concerts to you <small>⌖ Montreal, QC, Canada</small></h2><div class="notice-card">☆ <strong>Track future tour dates</strong><span>We'll let you know when this artist is touring near you</span><button>Get notified</button></div></section>
      </main><section class="shell artist-events" id="coming-up"><div class="tabs"><a class="active" href="#coming-up">Coming up <b>{esc(upcoming)}</b></a><button>◷ Past events</button></div>
      {events}<div class="artist-related"><button type="button" aria-label="Next events">›</button><button type="button">The Wedding Present</button><button type="button" aria-label="Next artists">›</button><a href="/images/39448932" aria-label="Open artist image">View photo</a></div></section>"""


def event_content(page: dict[str, Any]) -> str:
    name = next((item["text"] for item in page["headings"] if item["level"] == 1), "Concert")
    event_id = numeric_id(page["requested_path"], "/concerts/")
    asset = image_asset_for(name, "large_avatar")
    photo = asset["local_url"]
    event_profiles = {
        "43365625": ("Tuesday 06 October 2026", "Place Bell", "Laval", "purple", "#1f1268", "#1a1156", "#8f89b4"),
        "43371713": ("14 November 2026", "MTELUS", "Montreal", "ochre", "#6f560b", "#5a470b", "#b7ab85"),
        "43381053": ("11 October 2026", "New City Gas", "Montreal", "umber", "#4c2e2e", "#3e2727", "#a69797"),
        "43383403": ("26 October 2026", "L'Olympia", "Montreal", "graphite", "#3d3d3d", "#323333", "#9e9e9e"),
        "43382897": ("18 October 2026", "Le Ministère", "Montreal", "graphite", "#3d3d3d", "#323333", "#9e9e9e"),
        "43390372": ("02 May 2027", "Place des Arts", "Montreal", "navy", "#2e2e4c", "#26273f", "#9797a6"),
        "43371714": ("06 November 2026", "L'Olympia", "Montreal", "umber", "#4c2e2e", "#3e2727", "#a69797"),
        "43390357": ("20 November 2026", "Théâtre Fairmount Theatre", "Montreal", "teal", "#2e4c4c", "#263f3f", "#97a6a6"),
        "43371710": ("14 November 2026", "Hall Est Du Stade Olympique", "Montreal", "crimson", "#601a1a", "#4e1717", "#b08d8d"),
        "43382670": ("06 November 2026", "MTELUS", "Montreal", "red", "#740606", "#5e0707", "#ba8383"),
    }
    date, venue, city, theme, hero_color, facts_color, ticket_color = event_profiles.get(
        event_id,
        ("06 October 2026", "Place Bell", "Laval", "purple", "#1f1268", "#1a1156", "#8f89b4"),
    )
    venue_paths = {
        "43365625": "/venues/3536914-place-bell",
        "43371713": "/venues/20838-mtelus",
        "43381053": "/venues/1449208-new-city-gas",
        "43383403": "/venues/61660-lolympia",
        "43382897": "/venues/4016319-le-ministere",
        "43390372": "/venues/35381-place-des-arts",
        "43371714": "/venues/61660-lolympia",
        "43390357": "/venues/1086866-theatre-fairmount-theatre",
        "43371710": "/venues/4661630-hall-est-du-stade-olympique",
        "43382670": "/venues/20838-mtelus",
    }
    venue_path = venue_paths.get(event_id, "/venues/3536914-place-bell")
    venue_site_ids = {
        "43382897": "external-002",
        "43390357": "external-013",
        "43371713": "external-016",
        "43383403": "external-017",
        "43390372": "external-018",
    }
    venue_site = (
        external_anchor(venue_site_ids[event_id], "Visit website", class_name="event-venue-site")
        if event_id in venue_site_ids else ""
    )
    problem_link = (
        external_anchor("external-031", "Flag a problem", class_name="event-flag")
        if event_id == "43365625"
        else '<a class="event-flag" href="/__external__?destination=Songkick%20support">Flag a problem</a>'
    )
    return f"""
      <div class="top-ad"></div><main class="shell event-page" data-wb-component="event-profile" data-event-theme="{esc(theme)}" style="--event-hero:{hero_color};--event-facts:{facts_color};--event-ticket:{ticket_color}">
      {problem_link}<section class="event-hero"><div class="event-summary"><h1>{esc(name)}</h1><button class="event-interest" id="event-interest" data-event-id="{esc(event_id)}" data-wb-capability="event-interest">♡ Interested</button><p><span class="rsvp-dots"><i></i><i></i><i></i></span> <strong>31</strong> RSVPs</p><div class="event-facts"><p><span class="fact-icon">□</span> {esc(date)}</p><p><span class="fact-icon">⌖</span> <a href="{esc(venue_path)}">{esc(venue)}</a>, {esc(city)}, QC, Canada</p></div></div><img data-wb-media="event-header-image" src="{esc(photo)}" data-source-asset="{esc(asset['source_url'])}" alt="{esc(name)} live"></section>
      <div class="event-columns"><section><div class="event-jumps"><button>Line-up</button><button>Venue</button><button>Details</button><button>Reviews</button><button>More events</button></div><div class="sale-bar"><span>On sale for 2 weeks</span><b>Event is in 1 month</b></div><h2>Line-up</h2><div class="white-card"><h3>{esc(name)}</h3>{venue_site}<button type="button" data-event-status="attended" data-event-id="{esc(event_id)}" data-wb-capability="event-was-there">I was there</button></div></section>
      <aside class="tickets" id="ticket-providers" data-wb-component="ticket-provider-dialog"><button type="button" class="ticket-toggle">Buy tickets</button><button type="button" class="ticket-close" aria-label="Close tickets">×</button><h2 data-wb-ticket-control="43365625" id="buy-tickets" role="button" tabindex="0" aria-controls="ticket-providers" aria-expanded="true">Buy tickets</h2><div class="ticket-item"><img src="{esc(photo)}" alt=""><div><strong>{esc(name)}</strong><span>{esc(date)} • {esc(venue)}</span></div></div><a data-wb-ticket-control="ticketmaster-ca" data-wb-ticket-link="ticketmaster-ca" href="/tickets/34252807?" target="_blank" rel="noopener"><strong>Ticketmaster CA</strong><small>On sale now</small><b aria-hidden="true">›</b></a><a data-wb-ticket-control="seatgeek" data-wb-ticket-link="seatgeek" href="/tickets/34247919?" target="_blank" rel="noopener"><strong>SeatGeek</strong><small>On sale now</small><b aria-hidden="true">›</b></a></aside></div>
      </main>"""


def auth_content(page: dict[str, Any], kind: str, visual_state: str = "") -> str:
    if kind == "sign-up":
        fields = '<input name="display_name" value="Concert Fan" type="hidden"><label>Email address<input name="email" type="email" required></label><label>Password<span class="auth-input"><input name="password" type="password" minlength="8" required><span>◉</span></span><small>8 characters or longer</small></label><label class="auth-verification-label">Security verification<textarea name="verification" aria-label="Security verification"></textarea></label>'
        button = "Continue with email"
        component = "signup-form"
        form_id = "signup-form"
        heading = "Sign up for free"
        subtitle = "Find your perfect concert wherever you are and never<br>miss out on tickets"
        providers = '<div class="auth-providers"><a href="/auth/google_oauth2?locale=en">Ⓖ <span>Continue with Google</span></a><a href="/auth/apple?locale=en">● <span>Continue with Apple</span></a></div><div class="auth-divider"><span>or</span></div>'
        extra = '<p class="auth-switch">Already have an account? <a href="/session/new">Log in</a></p><p class="auth-legal">Songkick\'s <a href="/info/terms">terms</a> and our <a href="/info/privacy">privacy policy</a></p>'
        card_kind = "signup"
    elif kind == "password-reset":
        fields = '<label>Email address<input name="email" type="text" placeholder="Your email address" required></label><label class="auth-verification-label">Security verification<textarea name="verification" aria-label="Security verification"></textarea></label>'
        button = "Send password reset email"
        component = "password-reset-form"
        form_id = "reset-form"
        heading = "Forgot your password?"
        subtitle = "Enter your email for a password reset link"
        providers = ""
        extra = '<div id="reset-next"></div><p class="auth-switch"><a href="/session/new">←&nbsp; Back to Login</a></p>'
        card_kind = "password-reset"
    else:
        fields = '<label>Email address or username<input name="email" type="email" required></label><label>Password<span class="auth-input"><input name="password" type="password" minlength="8" required><span>◉</span></span></label><p class="auth-forgot"><a href="/password_reset_requests/new">Forgot your password?</a></p>'
        button = "Log in"
        component = "login-form"
        form_id = "login-form"
        heading = "Log in to Songkick"
        subtitle = "Continue on your journey to concert greatness"
        providers = '<div class="auth-providers"><button class="unavailable" type="button" disabled>● <span>Continue with Spotify</span></button><a href="/auth/google_oauth2?locale=en">Ⓖ <span>Continue with Google</span></a><a href="/auth/apple?locale=en">● <span>Continue with Apple</span></a><a href="/facebook-password-reset">● <span>Continue with Facebook</span></a></div><div class="auth-divider"><span>or</span></div>'
        extra = '<p class="auth-switch">New here? <a href="/signup/new">Sign up</a></p>'
        card_kind = "login"
    if card_kind == "password-reset" and visual_state == "captcha-error":
        return """
          <main class="auth-page" data-auth-kind="password-reset" data-auth-state="captcha-error">
          <a class="auth-back" href="/session/new">←</a><a class="auth-help" href="http://support.songkick.com/" data-wb-external-id="external-011">Help</a><a class="auth-logo" href="/">Songkick</a>
          <section class="auth-card auth-card-password-reset auth-card-captcha" data-wb-component="password-reset-form"><h1>Forgot your password?</h1><p class="auth-subtitle">Enter your email for a password reset link</p><form id="reset-form"><label>Email address<input name="email" type="email" required></label><div class="captcha-widget" data-wb-component="captcha-widget"><span>□</span><small>I'm not a robot</small><b>↻<i>reCAPTCHA</i></b></div><p class="captcha-error" data-wb-component="password-reset-captcha-error">Please answer the “I’m not a robot” test.</p><button class="primary-button" type="submit">Send password reset email</button></form><p class="auth-switch"><a href="/session/new">←&nbsp; Back to Login</a></p></section></main>"""
    state_notice = ""
    prelude = ""
    if visual_state == "captcha-error":
        state_notice = '<div class="form-notice state-error" data-wb-component="password-reset-captcha-error">Please confirm you are not a robot and try again.</div>'
    elif visual_state == "reset-success":
        prelude = '<div class="auth-reset-banner" data-wb-component="password-reset-success-notice"><b>ⓘ</b><strong>If an account with this email exists, an email will be sent to reset<br>your password</strong></div>'
    back_path = "/session/new" if card_kind == "password-reset" else "/"
    return f"""
      {prelude}<main class="auth-page" data-auth-kind="{card_kind}"{' data-auth-state="reset-success"' if visual_state == 'reset-success' else ''}>
      <a class="auth-back" href="{back_path}">←</a><a class="auth-help" href="http://support.songkick.com/" data-wb-external-id="external-011">Help</a><a class="auth-logo" href="/">Songkick</a>
      <section class="auth-card auth-card-{card_kind}" data-wb-component="{component}"><h1>{heading}</h1><p class="auth-subtitle">{subtitle}</p>{providers}
      {state_notice}<div class="form-notice" id="form-notice" role="status"></div><form id="{form_id}">{fields}<input class="primary-button" type="submit" value="{button}"></form>{extra}</section></main>"""


def app_download_content() -> str:
    google_play = esc(EXTERNAL_LINK_BY_ID["external-029"])
    app_store = esc(EXTERNAL_LINK_BY_ID["external-027"])
    return f"""
      <main class="app-download" data-wb-component="app-download">
        <section class="app-download-copy">
          <img class="app-download-logo" src="/assets/source/a0084-songkick-logo-svg-47b1d1f992.svg" alt="Songkick">
          <p>Get the free app.</p>
          <div class="app-store-links">
            <a class="google-play-download" data-wb-external-id="external-029" href="{google_play}" aria-label="Get it on Google Play"><img src="/assets/source/a0087-google-play-png-9c613a86e1.png" alt="Get it on Google Play"></a>
            <a class="app-store-download" data-wb-external-id="external-027" href="{app_store}" aria-label="Download on the App Store"><img src="/assets/source/a0086-apple-app-store-png-685d346bd5.png" alt="Download on the App Store"></a>
          </div>
        </section>
        <section class="app-download-preview" aria-label="Songkick mobile app preview">
          <img src="/assets/source/a0088-mobile-device-new-png-5cdeb2f228.png" alt="Songkick app on a mobile device">
        </section>
      </main>"""


def about_content() -> str:
    gallery = [
        "a0097-top-row-left-jpg-88d7f00d96.jpg",
        "a0092-image-from-ios-jpg-f3acd944e0.jpg",
        "a0095-songkick-talk-jpg-da10c04542.jpg",
        "a0089-bottom-row-left-jpg-ddc2a16e02.jpg",
        "a0090-bottom-row-middle-jpg-29e733cb48.jpg",
        "a0091-bottom-row-right-jpg-290acab661.jpg",
    ]
    gallery_markup = "".join(
        f'<img src="/assets/source/{esc(filename)}" alt="Songkick team and live music">'
        for filename in gallery
    )
    reviews = "".join(
        external_anchor(external_id, label, class_name="about-review")
        for external_id, label in (
            ("external-019", "EmJoBrown, App Store"),
            ("external-020", "V. Gonzalez, Play Store"),
            ("external-021", "T. Wegner, Play Store"),
            ("external-022", "K. Mlynarczyk, Play Store"),
        )
    )
    return f"""
      <main class="about-page" data-wb-component="about-brief">
        <section class="about-brief-hero"><h1>Bringing the magic of live music to fans everywhere.</h1></section>
        <section class="about-brief-lower">
          <ul class="about-features">
            <li class="about-feature mic"><p>Track your favorite<br>artists</p></li>
            <li class="about-feature calendar"><p>Get personalized<br>concert alerts</p></li>
            <li class="about-feature ticket"><p>Never miss out on<br>tickets</p></li>
          </ul>
          <a class="about-signup" href="/signup/new">Sign up to Songkick</a>
        </section>
        <section class="about-story"><h2>Live music changes lives</h2><p>Songkick brings fans closer to the artists they love. Track artists, discover concerts and get the ticket information you need—all from this local frozen experience.</p></section>
        <section class="about-gallery">{gallery_markup}</section>
        <section class="about-reviews" aria-label="Fan reviews">{reviews}</section>
        <section class="about-contacts"><h2>Talk to us</h2><a href="/__external__?destination=http%3A%2F%2Fsupport.songkick.com%2F">Head to Songkick support</a><a href="/jobs">Work with us</a><a href="/info/values">Check out our values</a></section>
      </main>"""


def live_streams_content() -> str:
    streams = [
        ("Alvagarx", "Friday 4 September 2026", "2:30 PM EDT", "Coldplay", "/live-stream-concerts/43266436-alvagarx"),
        ("Hernán Casciari", "Saturday 5 September 2026", "3:00 PM EDT", "Eminem", "/live-stream-concerts/43356227-hernan-casciari"),
        ("Five Finger Death Punch", "Tuesday 8 September 2026", "11:00 PM EDT", "The Weeknd", "/live-stream-concerts/43385348-five-finger-death-punch"),
        ("David Cook", "Wednesday 9 September 2026", "8:00 PM EDT", "Drake", "/live-stream-concerts/43381546-david-cook"),
        ("Ruby Karp", "Thursday 10 September 2026", "8:00 PM EDT", "Rihanna", "/live-stream-concerts/43378881-ruby-karp"),
    ]
    rows = "".join(
        f'<a class="live-stream-row" href="{esc(path)}"><img src="{esc(image_asset_for(image_name, "huge_avatar")["local_url"])}" alt=""><span><strong>{esc(name)}</strong><small>{esc(date)}</small><small>{esc(time)}</small></span><b aria-hidden="true">›</b></a>'
        for name, date, time, image_name, path in streams
    )
    return f"""
      <main class="live-streams-page">
        <div class="live-stream-top-gap"></div>
        <section class="live-stream-brief"><div class="live-stream-brief-inner">
          <div class="live-stream-copy"><h1>Live stream<br>concerts</h1><p>The show must go on, right? Check out the best live stream<br>performances coming up around the globe, and show love, solidarity<br>and support for your favorite artists.</p></div>
          <img class="live-stream-art" src="/assets/source/a0071-live-streams-hero-image-webp-1700e00c90.webp" alt="Live stream performances">
        </div></section>
        <div class="live-stream-grid">
          <section class="live-stream-list" data-wb-component="live-stream-concert-list"><h2>All upcoming live streamed concerts</h2>{rows}</section>
          <aside class="popular-read"><h2>Popular Reads</h2><a href="/news/the-ultimate-guide-to-live-stream-concerts"><img src="/assets/source/a0041-the-ultimate-guide-to-live-stream-concerts-png-931bbc15e3.png" alt=""><span><small>LIST &amp; GUIDES</small><strong>The Ultimate Guide to<br>Live Stream Concerts</strong></span></a></aside>
        </div>
      </main>"""


def news_content() -> str:
    cards = [
        ("REVIEW", "Isaac Gracie: Songs from my bedroom", "a0037-isaac-gracie-png-eb4a9edf17.png", "/news/live-review-isaac-gracie"),
        ("LIST & GUIDES", "The Ultimate Guide to Live Stream Concerts", "a0041-the-ultimate-guide-to-live-stream-concerts-png-931bbc15e3.png", "/news/the-ultimate-guide-to-live-stream-concerts"),
        ("ARTIST INSIGHTS", "Five things to get you ready for Laura Mvula’s live stream concert", "a0038-laura-mvula-jpg-463d6d0284.jpg", "/news/five-things-on-laura-mvula"),
    ]
    card_markup = "".join(
        f'<a class="news-card" href="{esc(path)}"><img src="/assets/source/{esc(image)}" alt=""><small>{esc(category)}</small><strong>{esc(title)}</strong></a>'
        for category, title, image, path in cards
    )
    videos = "".join(
        external_anchor(external_id, label, class_name="news-video-link")
        for external_id, label in (
            ("external-043", "Songkick on YouTube"),
            ("external-044", "Watch artist interview"),
            ("external-045", "Watch live music story"),
            ("external-046", "Watch concert guide"),
        )
    )
    return f"""
      <main class="news-index" data-wb-component="news-index">
        <header class="news-masthead"><small>SONGKICK NEWS</small><h2>YOUR HOME FOR LIVE<br>MUSIC</h2></header>
        <article class="news-lead">
          <div class="news-lead-copy"><small>LISTS &amp; GUIDES</small><h1>Inside the World of<br>Video Game Music<br>Concerts</h1><p>Music is spreading its wings and some of the biggest<br>performances of the year happened in video games<br>- discover more about the biggest video game<br>concerts.</p><time>February 10 2021</time><a href="/news/video-game-music-concert">Read more&nbsp;&nbsp; →</a></div>
          <a class="news-lead-image" href="/news/video-game-music-concert"><img src="/assets/source/a0857-video-game-concert-content-header-jpg-3db1a3634c.jpg" alt="Video game music concert"></a>
        </article>
        <section class="news-card-grid">{card_markup}</section><nav class="news-video-links" aria-label="Songkick videos">{videos}</nav>
      </main>"""


def developer_content() -> str:
    inquiry = external_anchor("external-032", "CLICK HERE: Songkick API Paid Licensing - Inquiry Form", class_name="developer-inquiry")
    tourbox_faq = external_anchor("external-012", "FAQ about using Tourbox")
    discussion = external_anchor("external-001", "Discussion group")
    return f"""
      <main class="developer-index" data-wb-component="developer-api-index">
        <section class="developer-copy"><h1>The best API for live music</h1>
          <p>The Songkick API gives you easy access to the biggest live music database in the world: over 6 million upcoming and past concerts... and growing every day! Easily add concerts to your website or application.</p>
          <p>Use of the Songkick API will be subject to the standard terms of our partnership agreement and a license fee.</p>
          <p><u>We are currently not approving API requests for student projects, educational purposes or hobbyist purposes.</u></p>
          <p>Please fill in the below form if you’re willing to sign our partnership agreement and pay the standard license fee (details in form).</p>
          {inquiry}<p><a href="/design">Songkick brand guidelines</a></p>
          <h2>API features</h2><ul class="developer-features">
            <li class="event-search"><a href="#upcoming"><strong>Upcoming events</strong><span>Search for events by artist, date, venue, and location. Search for artists, venues, and metro areas.</span></a></li>
            <li class="events-for-user"><a href="#tracking"><strong>User’s events and trackings</strong><span>Search for any user’s upcoming and past events. Get a user’s trackings.</span></a></li>
            <li class="past-events"><a href="#past"><strong>Past events</strong><span>Get the complete concert history for artists (gigography).</span></a></li>
          </ul>
        </section>
        <aside class="developer-nav"><h2>Get started</h2><strong>API home</strong><a href="#start">Getting started</a><a href="#apply">Apply for an API key</a><a href="#terms">API terms of use</a><h2>API requests</h2><a href="#upcoming">Upcoming events</a><a href="#tracking">User’s events and trackings</a><a href="#past">Past events</a><a href="#venue">Venue details</a><a href="#similar">Similar artists</a><a href="#search">Search</a><h2>API responses</h2><a href="#objects">API object reference</a><h2>For artists</h2>{tourbox_faq}<h2>We love feedback</h2><a href="/__external__?destination=Songkick%20Help">Help &amp; FAQ</a>{discussion}</aside>
      </main>"""


def privacy_content() -> str:
    return """
      <main class="privacy-policy" data-wb-component="privacy-policy">
        <h1>Songkick Privacy Policy</h1><p class="privacy-updated">Last updated: July 9, 2026</p>
        <p>Songkick is operated by Suno Inc. (<strong>“Suno", "we", "our" or "us"</strong>). Suno takes privacy seriously when handling information that identifies you personally such as your name, contact details, order history, credit/debit card details, marketing preferences or data that can be linked with such information in order to identify you directly or indirectly (<strong>“Personal Information”</strong>). Under applicable data protection laws, Suno acts as the controller of your Personal Information.</p>
        <p>This Privacy Policy describes our practices in connection with Personal Information that we collect from you in relation to the Songkick service, including Personal Information we collect in person and through certain of our owned or controlled websites, online stores and web properties (e.g., widgets and applications) and mobile applications (<strong>“Mobile Apps”</strong>) in each case, that link to this Privacy Policy (each, a <strong>“Platform”</strong> or collectively our <strong>“Platforms”</strong>).</p>
        <p>This Privacy Policy applies to the Songkick service as a whole, and where there are local variations or additions concerning how we use your Personal Information collected from your home country, these are set out clearly in the <a href="#country-schedules">Country Specific Schedules</a> section of this Privacy Policy. Please treat these schedules as a part of this Privacy Policy. If you are a California resident, please note that we have a separate California Privacy Policy which applies to the collection and use of your Personal Information along with this Privacy Policy and also addresses your privacy rights. Please see our California Privacy Policy <a href="#california">here</a>.</p>
        <p>Please note that our Platforms are not directed to individuals under the age of sixteen (16), and we request that such individuals do not provide Personal Information through the Platforms.</p>
        <h2>QUICK GUIDE TO CONTENTS</h2><ol><li><a href="#how-we-use">HOW WE USE YOUR PERSONAL INFORMATION</a></li><li><a href="#how-we-share">HOW WE SHARE YOUR PERSONAL INFORMATION</a></li></ol>
        <h2 id="how-we-use">1. HOW WE USE YOUR PERSONAL INFORMATION</h2><p>We use information to provide and improve Songkick, deliver concert recommendations and communicate with you.</p>
      </main>"""


def popular_artist_leaderboard_content() -> str:
    artists = [
        (201, "PARTYNEXTDOOR", "1,095,880", "1 concert"),
        (202, "James Arthur", "1,095,044", "1 concert"),
        (203, "The Kooks", "1,094,861", "1 concert"),
        (204, "Playboi Carti", "1,093,953", "2 concerts"),
        (205, "Migos", "1,084,538", "0 concerts"),
        (206, "Swedish House Mafia", "1,084,139", "5 concerts"),
        (207, "M83", "1,080,280", "0 concerts"),
        (208, "Young Thug", "1,079,573", "24 concerts"),
        (209, "SZA", "1,078,944", "6 concerts"),
    ]
    rows = "".join(
        f'<article class="leaderboard-table-row"><img src="{esc(image_asset_for(name, "huge_avatar")["local_url"])}" alt=""><b>{rank}</b><a href="/artists">{esc(name)}</a><span>{esc(fans)}</span><span>{esc(tours)}</span><button type="button" data-artist-id="{rank}" data-wb-capability="artist-tracking">TRACK ARTIST</button></article>'
        for rank, name, fans, tours in artists
    )
    return f"""
      <main class="popular-artist-leaderboard" data-wb-component="popular-artist-leaderboard">
        <nav class="leaderboard-tabs"><a class="active" href="/leaderboards/popular_artists">Most popular artists worldwide</a><a href="/leaderboards/trending_artists">Trending artists this week</a></nav>
        <div class="leaderboard-table-head"><b>Popularity ranking</b><b>Artist</b><b>Fans tracking</b><b>Tour dates</b></div>
        <section>{rows}</section>
      </main>"""


def trending_artist_leaderboard_content() -> str:
    artists = [
        (1, "Westside Cowboy", "Non-mover", "12,698", "24 concerts"),
        (2, "OMD", "Non-mover", "5,547", "1 concert"),
        (3, "Mary In The Junkyard", "Up 1", "7,044", "26 concerts"),
        (4, "Man/Woman/Chainsaw", "Down 1", "7,080", "22 concerts"),
        (5, "Stardust", "Up 2", "10,636", "0 concerts"),
        (6, "Florence Black", "Up 48", "6,301", "17 concerts"),
        (7, "Mike D", "Up 180", "6,351", "1 concert"),
        (8, "Keo", "Up 73", "8,241", "13 concerts"),
    ]
    rows = "".join(
        f'<article class="leaderboard-table-row trending-row"><img src="{esc(image_asset_for(name, "huge_avatar")["local_url"])}" alt=""><b>{rank:02d}</b><a href="/artists">{esc(name)}</a><span>{esc(change)}</span><span>{esc(fans)}</span><span>{esc(tours)}</span><button type="button" data-artist-id="trend-{rank}" data-wb-capability="artist-tracking">TRACK ARTIST</button></article>'
        for rank, name, change, fans, tours in artists
    )
    return f"""
      <main class="popular-artist-leaderboard trending-leaderboard" data-wb-component="trending-artist-leaderboard">
        <nav class="leaderboard-tabs"><a href="/leaderboards/popular_artists">Most popular artists worldwide</a><a class="active" href="/leaderboards/trending_artists">Trending artists this week <small>Mon 31 Aug 2026</small></a></nav>
        <div class="leaderboard-table-head trending-head"><b>Popularity ranking</b><b>Artist</b><b>Weekly change</b><b>Fans tracking</b><b>Tour dates</b></div>
        <section>{rows}</section>
      </main>"""


def jobs_content() -> str:
    return """
      <main class="jobs-page" data-wb-component="jobs-page">
        <section class="jobs-hero"><strong class="jobs-logo">Songkick</strong><div><h1>WORK AT SONGKICK</h1><a href="#openings">VIEW OPEN POSITIONS</a></div></section>
        <section class="jobs-copy"><h2>About us</h2><p>We’re on a mission to bring the magic of live music to fans everywhere. We believe that a concert can change your life—but getting there is hard work. We want to make live music effortless, so that anyone can experience it.</p><p>Right now, more than 150 million music fans across the globe use Songkick to discover shows for their favorite artists and never ever miss out. With over 9 million event listings, we’re the biggest concert service on the planet. Across web, iPhone and Android, and through rich partnerships with Spotify, Pandora and Facebook, Songkick is the definitive and trusted home for live music online.</p><a data-wb-external-id="external-025" href="https://blog.songkick.com/how-we-fixed-culture-at-songkick-c853891ff7cf">Culture Club</a><img src="/assets/source/css-deps/d1055-22be5b1d33063430.jpg" alt="Life at Songkick"></section>
      </main>"""


def legal_content(page: dict[str, Any]) -> str:
    page_id = page["id"]
    copy: dict[str, tuple[str, list[str]]] = {
        "info-cookies": (
            "Last updated: July 9, 2026",
            [
                "This Cookies Policy describes how cookies and similar technologies are used on our websites and web properties (e.g., widgets and applications) that contain or link to this Cookies Policy (which are referred to in this policy collectively and individually as the “Site”). It is intended to operate with and be read together with the cookies banner and cookie preference center accessible through the ‘Cookies Settings’ link on any page of the Site.",
                "“We” (or “us” or “our”) means Suno Inc. (“Suno”), the operator of the Songkick service.",
                "We may change this Cookies Policy from time to time, so please check back periodically for updates.",
            ],
        ),
        "info-guidelines": (
            "",
            [
                "Songkick is a home for live music – a place for fans and artists to come together to help us create the best concert platform ever. The more people using Songkick, the better it gets – discovering new shows, contributing to our event listings and uploading photos, posters and reviews.",
                "We want Songkick to work for everyone, so along with our terms, your use of our service is subject to these community guidelines.",
            ],
        ),
        "info-security": (
            "",
            [
                "Songkick takes your online security seriously. If you have any questions about how we secure our websites or wish to report any website vulnerabilities you have discovered, please contact us at security@songkick.com and we will investigate promptly.",
            ],
        ),
        "info-terms": (
            "Last Updated: July 9, 2026",
            [
                "These Terms of Use (the “Terms”) govern your use of the website, https://songkick.com/ (“Website”), the related mobile application (“App”) as well as such products, features, content, and other services available on or through the Website and App (together the “Service(s)”), except where we expressly state that separate terms apply.",
                "The Services are provided to you by Suno Inc. (referred to as “Suno,” “we,” “us” or “our” in these Terms). When we refer to “you” or “your” in these Terms, we are referring to you as the user of our Services.",
                "ARBITRATION NOTICE FOR USERS RESIDING OUTSIDE OF THE UK/EEA: PLEASE READ THESE TERMS CAREFULLY, AS THEY CONTAIN AN AGREEMENT TO ARBITRATE AND OTHER IMPORTANT INFORMATION REGARDING YOUR LEGAL RIGHTS, REMEDIES, AND OBLIGATIONS.",
            ],
        ),
    }
    updated, paragraphs = copy[page_id]
    heading = next(item["text"] for item in page["headings"] if item["level"] == 1)
    first_section = next((item["text"] for item in page["headings"] if item["level"] == 2), "")
    extra = ""
    if page_id == "info-security":
        extra = '<h2>PGP key</h2><p>If you wish, you may use this key to encrypt email sent to security@songkick.com</p><pre>-----BEGIN PGP PUBLIC KEY BLOCK-----\nmQENBFtLWm0wBCACjmxsXFnHTiWdO4EM6ZXoGVHVsm1yInROJvoVkV+jgY/B7iwudT8osujnP\nAF6A1+NevFQAluwJByJYVGfkB64KlqHhlvPbmCp4zDFh8aRTkApxil3GXsPDCj1zHMbiN+Nx\nQcR2vLCsCcAVAUapDLfCgjicyqUQ9kj4+6bq36e6SvA3nlrQWkUrjT/kbH9UDZn8e8JVEMhg\nsJqb+Gk4bAD7Y5uiyHGfcQNeZj53vsYg1poAFcpLxiuzYEi3lpq8Eq96xMNG7FlJy9UTpRZf\nuUk3rJqy7GNQXs9VYH9l9otfywF8r8wmEiWEFjzwgM7sFbqAXBrn5SMgtjs/rg60lkUBABEB\n-----END PGP PUBLIC KEY BLOCK-----</pre>'
    elif page_id == "info-guidelines":
        extra = '<ol class="guideline-list"><li><strong>Quest for truth.</strong> Songkick is a place for accurate and bonafide concert information only. We work around the clock to make sure our listings are correct, timely and up-to-date.</li><li><strong>Upload responsibly.</strong> Please don’t upload copyrighted content without permission from the owner.</li></ol>'
    else:
        extra = f'<h2>{esc(first_section)}</h2><p>A cookie is a small piece of information that the Site’s server transfers to your browser. By using the Services, you agree to these terms and the additional guidelines referenced within them.</p>'
    if page_id == "info-cookies":
        extra += (
            '<p class="cookie-resources">Manage analytics with '
            + external_anchor("external-014", "Google Analytics opt-out")
            + ", read "
            + external_anchor("external-037", "www.aboutcookies.org")
            + ", or visit "
            + external_anchor("external-038", "www.allaboutcookies.org")
            + ".</p>"
        )
    updated_html = f'<p class="legal-updated">{esc(updated)}</p>' if updated else ""
    paragraphs_html = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in paragraphs)
    return f'<main class="legal-policy legal-{esc(page_id)}" data-wb-component="legal-document"><h1>{esc(heading)}</h1>{updated_html}{paragraphs_html}{extra}</main>'


def generic_content(page: dict[str, Any]) -> str:
    heading = next((item["text"] for item in page["headings"] if item["level"] == 1), page["title"].split("–")[0].split("|")[0])
    sections = "".join(f'<section class="white-card"><h2>{esc(item["text"])}</h2><p>Explore this source-grounded Songkick section offline. All actions and destinations remain local.</p></section>' for item in page["headings"] if item["level"] == 2 and "Privacy" not in item["text"])
    return f'<div class="top-ad"></div><main class="shell content-shell generic"><h1>{esc(heading)}</h1>{sections or "<p>Discover live music with Songkick.</p>"}</main>'


def not_found_content() -> str:
    return """
      <header class="legacy-not-found-header"><div class="shell"><a class="legacy-logo" href="/" aria-label="Songkick page"></a><a class="legacy-location" href="/session/filter_metro_area">●&nbsp; Change location</a><form action="/concerts"><input type="search" name="q" aria-label="Search for events or artists" placeholder="Find concerts for any artist or city 🔍"></form></div></header>
      <main class="legacy-not-found" data-wb-component="legacy-not-found"><div data-wb-component="branded-not-found"><h1>Hmmmm, we couldn't find that.</h1><p>The page you were trying to visit doesn't exist or has been deleted. If you got to this<br>page from a link on Songkick, we've logged that and will investigate the broken link.</p><p>Try a search?</p><form action="/concerts"><label>Search <input name="q"><button type="submit" id="not-found-search" data-wb-capability="hard-not-found-search">GO</button></label></form></div></main>"""


def data_boundary_content(path: str) -> str:
    slug = path.rstrip("/").split("/")[-1]
    numeric_identity = re.fullmatch(r"\d+-(.+)", slug)
    identity_slug = numeric_identity.group(1) if numeric_identity else slug
    known_labels = {"indie-alt": "Indie & Alt", "hip-hop": "Hip-Hop", "r-and-b": "R&B"}
    label = known_labels.get(identity_slug, identity_slug.replace("-", " ").strip().title())
    label = label or "Songkick listing"
    return f"""
      <div class="top-ad"></div><main class="shell content-shell data-boundary" data-wb-component="data-boundary" data-wb-capability="branded-data-boundary">
      <h1>{esc(label)}</h1><section class="white-card"><h2>Listing preserved offline</h2><p>This item keeps its source identity, but its complete detail is outside the frozen local dataset.</p><a class="primary-button" href="/concerts">Browse captured concerts</a></section></main>"""


def footer(page_id: str = "") -> str:
    if page_id.startswith("location-"):
        return """
          <footer class="site-footer legacy-source-footer" data-wb-component="global-footer"><div class="shell">
          <div><a href="/">Home</a><a href="/info/about">About us</a><a href="/app">Get the app</a><a href="/__external__?destination=https%3A%2F%2Fblog.songkick.com%2F">Blog</a><a href="/jobs">Jobs</a><a href="/__external__?destination=http%3A%2F%2Fsupport.songkick.com%2F">Support</a><a href="/leaderboards/popular_artists">Most popular charts</a><a href="/festivals">Festivals</a><a href="/news">News</a></div>
          <div><a href="/__external__?destination=https%3A%2F%2Ftourbox.songkick.com%2F">Tourbox for artists</a><a href="/__external__?destination=https%3A%2F%2Fcampaigns.songkick.com%2F">Campaigns for promoters</a><a href="/developer">API information</a><a href="/design">Brand guidelines</a><a href="/info/guidelines">Community guidelines</a><a href="/info/terms">Terms of use</a><a href="/info/privacy">Privacy policy</a><a href="/info/cookies">Cookies policy</a><a href="/info/security">Security</a><a href="/live-stream-concerts">Live streams</a></div>
          </div></footer>"""
    home_industry = ""
    home_social = ""
    home_store = ""
    if page_id == "home":
        home_industry = (
            external_anchor("external-034", "Tourbox for artists")
            + external_anchor("external-026", "Campaigns for promoters")
            + external_anchor("external-035", "Sign up as an artist")
        )
        home_social = (
            '<div class="footer-social"><h3>Find us on</h3>'
            + external_anchor("external-042", "Youtube")
            + external_anchor("external-039", "Instagram")
            + external_anchor("external-041", "TikTok")
            + external_anchor("external-036", "X")
            + external_anchor("external-015", "Facebook")
            + "</div>"
        )
        home_store = external_anchor("external-024", "Blog")
    consent_links = ""
    if page_id == "concerts":
        consent_links = (
            external_anchor("external-030", "More information")
            + external_anchor("external-040", "Powered by OneTrust")
        )
    help_link = (
        external_anchor("external-011", "Help & FAQ")
        if page_id == "home"
        else '<a href="/__external__?destination=http%3A%2F%2Fsupport.songkick.com%2F">Help &amp; FAQ</a>'
    )
    blog_link = home_store or '<a href="/__external__?destination=https%3A%2F%2Fblog.songkick.com%2F">Blog</a>'
    return f"""
      <footer class="site-footer" data-wb-component="global-footer"><div class="shell footer-grid">
      <div><strong class="footer-logo">Songkick</strong><p>Track your favorite artists and never miss them live.</p><a href="#home">Back to top</a><a href="/">Home</a><a href="/concerts">Concerts near you</a><a href="/artists">Popular Artists</a><a href="/festivals">Festivals</a><a href="/live-stream-concerts">Live streams</a></div>
      <div><h3>About Songkick</h3><a href="/info/about">About us</a><a href="/news">News</a>{blog_link}<a href="/jobs">Jobs</a><a href="/app">Get the app</a><a href="/developer">API information</a>{home_industry}</div>
      <div><h3>Get support</h3>{help_link}<a href="/info/guidelines">Community guidelines</a><a href="/info/privacy">Privacy policy</a><a href="/info/security">Security</a><a href="/info/terms">Terms of use</a><a href="/info/cookies">Cookies policy</a><a href="/design">Brand guidelines</a><a href="/genres/rock">Rock</a><a href="/metro-areas/nearby/genre/rock">Rock concerts near you</a>{consent_links}</div>
      <div data-wb-capability="locale-switch"><h3>Language</h3><a href="/">English</a><a href="/fr">Français</a><a href="/es">Español</a><a href="/de">Deutsch</a><a href="/pt">Português</a><button id="cookie-button" data-wb-component="cookie-preference-center" data-wb-capability="cookie-preferences">Cookie choices</button></div>
      {home_social}</div></footer><div class="cookie-center" id="cookie-center" hidden><button data-close-cookie>×</button><h2>Privacy Preference Center</h2><h3>Manage Consent Preferences</h3><label><input type="checkbox" checked disabled> Strictly Necessary Cookies</label><label><input type="checkbox" id="analytics-cookie"> Analytics Cookies</label><button class="primary-button" id="save-cookies">Save choices</button></div>"""


def render_page(page: dict[str, Any], status: int | None = None, query: dict[str, str] | None = None) -> HTMLResponse:
    query = query or {}
    state_page = {
        "today": "montreal-today",
        "next-7-days": "montreal-next-7-days",
        "next-30-days": "montreal-next-30-days",
        "search-toronto": "location-search-toronto",
        "search-empty": "location-search-empty",
    }.get(query.get("wb_state", ""))
    if state_page:
        page = PAGE_BY_ID[state_page]
    page_id = page["id"]
    path = urlsplit(page["requested_path"]).path
    if page_id == "home":
        body = home_content()
    elif page_id.startswith("locale-"):
        body = home_content(page.get("lang") or page_id.removeprefix("locale-"))
    elif page_id in {"not-found"}:
        body = not_found_content()
    elif page_id == "sign-in" or path == "/session/new":
        body = auth_content(page, "sign-in", "reset-success" if query.get("reset") == "success" else "")
    elif page_id == "sign-up" or path == "/signup/new" or page_id == "protected-home-logged-out":
        body = auth_content(page, "sign-up")
    elif page_id == "password-reset" or path == "/password_reset_requests/new":
        body = auth_content(page, "password-reset", query.get("state", ""))
    elif page_id.startswith("location-") or path == "/session/filter_metro_area":
        body = location_content(page, query.get("wb_state", ""))
    elif page_id == "festival-detail" or "/festivals/" in path:
        body = festival_content(page)
    elif page_id == "festivals":
        body = festivals_content(page)
    elif page_id == "venue-detail" or "/venues/" in path:
        body = venue_content(page)
    elif page_id == "artists":
        body = artists_content(page)
    elif "/artists/" in path:
        body = artist_content(page)
    elif "/concerts/" in path:
        body = event_content(page)
    elif page_id == "concerts":
        body = concerts_content(page)
    elif page_id == "app":
        body = app_download_content()
    elif page_id == "about":
        body = about_content()
    elif page_id == "live-streams":
        body = live_streams_content()
    elif page_id == "news":
        body = news_content()
    elif page_id == "developer":
        body = developer_content()
    elif page_id == "design":
        body = '<main class="blank-design-surface" data-wb-component="blank-design-surface" aria-label="Design"></main>'
    elif page_id == "jobs":
        body = jobs_content()
    elif page_id == "info-privacy":
        body = privacy_content()
    elif page_id in {"info-cookies", "info-guidelines", "info-security", "info-terms"}:
        body = legal_content(page)
    elif page_id == "popular-artists-page-2":
        body = popular_artist_leaderboard_content()
    elif page_id == "trending-artists":
        body = trending_artist_leaderboard_content()
    elif page_id == "genre-rock":
        body = genre_content()
    elif page_id in {"montreal-page-1", "montreal-page-2", "montreal-today", "montreal-next-7-days", "montreal-next-30-days", "nearby-genre-rock"} or page_id.startswith("region-"):
        page_number = 2 if page_id == "montreal-page-2" or query.get("page") == "2" else 1
        body = collection_content(page, page_number)
    else:
        body = generic_content(page)
    auth_shell = page_id in {"sign-in", "sign-up", "password-reset", "protected-home-logged-out"} or path in {"/session/new", "/signup/new", "/password_reset_requests/new"}
    standalone_shell = auth_shell or page_id in {"app", "design", "jobs", "info-guidelines", "info-terms", "not-found"}
    locale = page.get("lang") or "en"
    concerts_label = None
    if page_id == "live-streams":
        concerts_label = "Concerts near you"
    elif page_id.startswith("region-"):
        heading = next((item["text"] for item in page["headings"] if item["level"] == 1), "Concerts")
        concerts_label = heading.removeprefix("Concerts in ") + " concerts"
    page_nav = nav(locale, concerts_label, page_id)
    document = f"""<!doctype html><html lang="{esc(page.get('lang') or 'en')}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(page['title'])}</title><link rel="stylesheet" href="/assets/site.css"></head>
    <body data-page-id="{esc(page_id)}" data-wb-capability="offline-runtime"><div class="viewport-frame">{'' if standalone_shell else page_nav}{body}{'' if standalone_shell else footer(page_id)}{'' if standalone_shell else search_modal()}</div>
    <script>window.SONGKICK_PAGE={json.dumps({'id': page_id, 'path': path})};window.SONGKICK_CONTROLS={json.dumps(contract_control_payload(page))};</script><script src="/assets/site.js"></script></body></html>"""
    return HTMLResponse(document, status_code=page["http_status"] if status is None else status)


@app.get("/__external__", response_class=HTMLResponse)
def external_boundary(destination: str = "External destination") -> HTMLResponse:
    identity = urlsplit(destination).hostname or destination
    safe_identity = esc(identity[:180])
    page = {
        "id": "external-boundary",
        "title": "External destination – Songkick",
        "lang": "en",
        "requested_path": "/__external__",
        "http_status": 200,
        "headings": [],
        "controls": [],
    }
    body = f'<main class="not-found external-boundary" data-wb-component="external-boundary" data-wb-capability="branded-external-soft-404"><div class="error-mark">↗</div><h1>You’re leaving Songkick</h1><p><strong>{safe_identity}</strong> is an external destination. This offline clone does not contact it.</p><a class="primary-button" href="/">Back to Songkick</a></main>'
    document = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{page["title"]}</title><link rel="stylesheet" href="/assets/site.css"></head><body><div class="viewport-frame">{nav()}{body}{footer()}{search_modal()}</div><script src="/assets/site.js"></script></body></html>'
    return HTMLResponse(document, status_code=200, headers={"X-WebsiteBench-Boundary": "external-soft-404"})


@app.get("/blog", response_class=HTMLResponse)
def blog_boundary() -> HTMLResponse:
    return external_boundary("https://blog.songkick.com/")


@app.get("/{requested_path:path}", response_class=HTMLResponse)
def page(request: Request, requested_path: str) -> HTMLResponse:
    path = "/" + requested_path if requested_path else "/"
    page_value = PAGE_BY_PATH.get(path)
    if page_value is None:
        if path == "/en/artists/197928":
            return RedirectResponse("/artists/197928-coldplay", status_code=307)
        if path.startswith("/en/events/"):
            path = path.removeprefix("/en")
        if path.startswith("/auth/") or path == "/facebook-password-reset":
            return external_boundary(f"Songkick account provider ({path})")
        if path.startswith("/tickets/"):
            provider = "Ticketmaster CA" if path.startswith("/tickets/34252807") else "SeatGeek"
            return external_boundary(f"{provider} ({path})")
        if path.startswith(("/events/", "/concerts/", "/artists/", "/venues/", "/festivals/", "/metro-areas/", "/genres/")):
            page_stub = {
                "id": "data-boundary",
                "title": "Listing preserved offline – Songkick",
                "lang": "en",
                "requested_path": path,
                "http_status": 200,
                "headings": [],
                "controls": [],
            }
            document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{page_stub["title"]}</title><link rel="stylesheet" href="/assets/site.css"></head><body data-page-id="data-boundary" data-wb-capability="offline-runtime"><div class="viewport-frame">{nav()}{data_boundary_content(path)}{footer()}{search_modal()}</div><script>window.SONGKICK_PAGE={json.dumps({'id': 'data-boundary', 'path': path})};</script><script src="/assets/site.js"></script></body></html>'''
            return HTMLResponse(document, status_code=200, headers={"X-WebsiteBench-Boundary": "local-data-boundary"})
        fallback = PAGE_BY_PATH.get("/__websitebench_missing_songkick__")
        assert fallback is not None
        return render_page(fallback, status=404)
    return render_page(page_value, query=dict(request.query_params))
