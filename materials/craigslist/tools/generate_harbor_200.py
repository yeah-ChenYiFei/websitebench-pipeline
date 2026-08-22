"""Generate the complete Harbor 200-case authoring for the craigslist site.

Produces:
* harbor/instances/craigslist/fixtures/hidden/task-suite.json  (200 tasks)
* harbor/instances/craigslist/fixtures/hidden/case-manifest.json (200 cases)

Every task is a concrete Playwright-DSL journey against the clone's DOM
(selectors below match the clone templates). T2 journeys carry a level
(L1=35, L2=50, L3=80). T1/T3 are http-kind smoke and cross-cutting checks.
"""

from __future__ import annotations

import json
from pathlib import Path

INSTANCE = Path(__file__).resolve().parents[3] / "harbor" / "instances" / "craigslist" / "fixtures" / "hidden"
SITE_ID = "craigslist"


def css(selector: str) -> dict:
    return {"css": selector}


def obs(obs_id: str, kind: str, selector: str, comparator: dict) -> dict:
    return {"id": obs_id, "kind": kind, "selector": css(selector), "comparator": comparator}


def task(task_id: str, actions: list[dict], observations: list[dict], *, timeout: int = 90, mutate: bool = False) -> dict:
    out = {"id": task_id, "timeout_sec": timeout, "actions": actions, "observations": observations}
    if mutate:
        out["reference_mutation_authorized"] = True
    return out


def goto(path: str) -> dict:
    return {"op": "goto", "path": path}


def wait_visible(selector: str) -> dict:
    return {"op": "wait_for", "selector": css(selector), "state": "visible"}


def fill(selector: str, value: str) -> dict:
    return {"op": "fill", "selector": css(selector), "value": value}


def click(selector: str) -> dict:
    return {"op": "click", "selector": css(selector)}


def reload() -> dict:
    return {"op": "reload"}


def TEXT_EQ(v: str) -> dict:
    return {"type": "regex", "pattern": v}
COUNT_GE1 = {"type": "number", "absolute_tolerance": 0}


# ---------------------------------------------------------------------------
# T1: 20 http smoke checks
# ---------------------------------------------------------------------------
T1_SPECS = [
    ("t1-smoke-home", "/", "craigslist", "area-top"),
    ("t1-smoke-toronto-area", "/area/toronto", "toronto", "cl-breadcrumb"),
    ("t1-smoke-housing-hub", "/search/area/toronto?cat=hhh", "housing", "cl-section-list"),
    ("t1-smoke-sublets", "/search/area/toronto?cat=sub", "1BR near Annex", "result-list"),
    ("t1-smoke-apartments", "/search/area/toronto?cat=apa", "2BR apartment near Leslieville", "result-list"),
    ("t1-smoke-rooms", "/search/area/toronto?cat=roo", "Room near Kensington Market", "result-list"),
    ("t1-smoke-realestate", "/search/area/toronto?cat=rea", "2BR condo for sale", "result-list"),
    ("t1-smoke-canonical-listing", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "1BR near Annex", "listing-title"),
    ("t1-smoke-apartment-listing", "/view/d/2br-apartment-leslieville/4c9n", "2BR apartment near Leslieville", "listing-title"),
    ("t1-smoke-room-listing", "/view/d/room-kensington-market/4c9x", "Room near Kensington Market", "listing-title"),
    ("t1-smoke-search-annex", "/search/area/toronto?query=annex", "results", "cl-column-center"),
    ("t1-smoke-search-noresults", "/search/area/toronto?query=zzzz-no-match-websitebench", "no search results", "no-results"),
    ("t1-smoke-search-filtered", "/search/area/toronto?min_price=2000&max_price=3000&postal=M6G", "2,400", "result-list"),
    ("t1-smoke-login", "/account/login", "Log in", "cl-page-heading"),
    ("t1-smoke-register", "/account/register", "create an account", "cl-page-heading"),
    ("t1-smoke-forgot", "/account/forgot", "reset your password", "cl-page-heading"),
    ("t1-smoke-help", "/about/help", "help", "cl-page-heading"),
    ("t1-smoke-contact", "/contact", "contact", "cl-page-heading"),
    ("t1-smoke-notfound", "/view/d/does-not-exist/zzzzzz", "oops", "not-found-big"),
    ("t1-smoke-health", "/__websitebench/health", "ok", "body"),
]

T1_TASKS: list[dict] = []
for tid, path, pattern, zone in T1_SPECS:
    T1_TASKS.append(
        task(
            tid,
            [goto(path), wait_visible(zone)],
            [obs("page-ok", "text", zone, TEXT_EQ(pattern))],
            timeout=60,
        )
    )


# ---------------------------------------------------------------------------
# T2: 165 journeys (L1=35, L2=50, L3=80)
# ---------------------------------------------------------------------------
T2_TASKS: list[dict] = []

# --- L1 (35): single-page browse / detail / search observations ------------
L1 = [
    # browse categories (10)
    ("browse.sublets.v1", "/search/area/toronto?cat=sub", "1BR near Annex", "result-list"),
    ("browse.apartments.v1", "/search/area/toronto?cat=apa", "Leslieville", "result-list"),
    ("browse.rooms.v1", "/search/area/toronto?cat=roo", "Kensington", "result-list"),
    ("browse.realestate.v1", "/search/area/toronto?cat=rea", "condo for sale", "result-list"),
    ("browse.vacation.v1", "/search/area/toronto?cat=vac", "Muskoka", "result-list"),
    ("browse.housinghub.v1", "/search/area/toronto?cat=hhh", "housing", "cl-section-list"),
    ("browse.forsale-bikes.v1", "/search/area/toronto?cat=bia", "Vintage road bike", "result-list"),
    ("browse.forsale-furniture.v1", "/search/area/toronto?cat=fua", "dining table", "result-list"),
    ("browse.vancouver-area.v1", "/area/vancouver", "vancouver", "cl-breadcrumb"),
    ("browse.montreal-area.v1", "/area/montreal", "montreal", "cl-breadcrumb"),
    # listing details (10)
    ("detail.canonical-sublet.v1", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "1BR near Annex", "listing-title"),
    ("detail.sublet.price.v1", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "2,400", "listing-price"),
    ("detail.sublet.postid.v1", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "1000001", "listing-attr"),
    ("detail.sublet.furnished.v1", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "furnished", "listing-attr"),
    ("detail.sublet.replybtn.v1", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "reply", "sidebox"),
    ("detail.apartment.v1", "/view/d/2br-apartment-leslieville/4c9n", "Leslieville", "listing-title"),
    ("detail.room.v1", "/view/d/room-kensington-market/4c9x", "Kensington", "listing-title"),
    ("detail.rea.v1", "/view/d/2br-condo-for-sale-yonge-eglinton/4c9v", "condo for sale", "listing-title"),
    ("detail.removed-listing.v1", "/view/d/does-not-exist/zzzzzz", "oops", "not-found-big"),
    ("detail.description.v1", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "Annex", "listing-desc"),
    # searches (15)
    ("search.query-annex.v1", "/search/area/toronto?query=annex", "results", "cl-search-results"),
    ("search.query-yorkville.v1", "/search/area/toronto?query=yorkville", "results", "cl-search-results"),
    ("search.query-leslieville.v1", "/search/area/toronto?query=leslieville", "results", "cl-search-results"),
    ("search.query-furnished.v1", "/search/area/toronto?query=furnished", "results", "cl-search-results"),
    ("search.minprice.v1", "/search/area/toronto?min_price=2000", "results", "cl-search-results"),
    ("search.maxprice.v1", "/search/area/toronto?max_price=1000", "results", "cl-search-results"),
    ("search.price-range.v1", "/search/area/toronto?min_price=2000&max_price=3000", "2,400", "result-list"),
    ("search.postal-annex.v1", "/search/area/toronto?postal=M6G", "2,400", "result-list"),
    ("search.posted-today.v1", "/search/area/toronto?postedToday=1", "results", "cl-search-results"),
    ("search.bedrooms-1br.v1", "/search/area/toronto?bedrooms=1br", "results", "cl-search-results"),
    ("search.housingtype-sublet.v1", "/search/area/toronto?housingType=sublet", "results", "cl-search-results"),
    ("search.owner.v1", "/search/area/toronto?posted_by=owner", "results", "cl-search-results"),
    ("search.sort-price-asc.v1", "/search/area/toronto?query=annex&sort=price-asc", "results", "cl-search-results"),
    ("search.sort-price-desc.v1", "/search/area/toronto?query=annex&sort=price-desc", "results", "cl-search-results"),
    ("search.sublets-annex.v1", "/search/area/toronto?cat=sub&query=annex", "1BR near Annex", "result-list"),
]
for tid, path, pattern, zone in L1:
    T2_TASKS.append(
        task(tid, [goto(path), wait_visible(zone)], [obs("surface", "text", zone, TEXT_EQ(pattern))], timeout=60)
    )
assert len(L1) == 35, len(L1)

# --- L2 (50): multi-step flows with state ----------------------------------
L2: list[dict] = []


def flow_search_to_detail(tid: str, query: str, expect_title: str) -> dict:
    return task(
        tid,
        [goto(f"/search/area/toronto?query={query}"), wait_visible("cl-search-results"),
         click(".result-title a"), wait_visible("listing-title")],
        [obs("title", "text", "listing-title", TEXT_EQ(expect_title))],
        timeout=90,
    )


for i, (q, t) in enumerate(
    [("annex", "1BR near Annex"), ("leslieville", "2BR apartment near Leslieville"),
     ("kensington", "Room near Kensington Market"), ("yorkville", "2BR sublet near Yorkville"),
     ("roncesvalles", "3BR house rental in Roncesvalles")], start=1):
    L2.append(flow_search_to_detail(f"journey.search-to-detail.{i}.v2", q, t))

for i, (path, pattern) in enumerate(
    [("/search/area/toronto?cat=sub", "1BR near Annex"), ("/search/area/toronto?cat=apa", "2BR apartment"),
     ("/search/area/toronto?cat=roo", "Room near Kensington"), ("/search/area/toronto?cat=rea", "condo for sale"),
     ("/search/area/toronto?cat=bia", "Vintage road bike")], start=1):
    L2.append(
        task(
            f"journey.category-to-detail.{i}.v2",
            [goto(path), wait_visible("cl-search-results"), click(".result-title a"), wait_visible("listing-title")],
            [obs("title", "text", "listing-title", TEXT_EQ(pattern))],
            timeout=90,
        )
    )

# login/logout/account flows (10)
for i in range(1, 6):
    L2.append(
        task(
            f"journey.login.accounthome.{i}.v2",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav")],
            [obs("home", "text", "account-nav", TEXT_EQ("your postings"))],
            timeout=90, mutate=True,
        )
    )
for i in range(1, 4):
    L2.append(
        task(
            f"journey.login.invalid.{i}.v2",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "definitely-wrong"),
             click("button[type='submit']"), wait_visible("form-error-box")],
            [obs("error", "text", "form-error-box", TEXT_EQ("match"))],
            timeout=90,
        )
    )
for i in range(1, 3):
    L2.append(
        task(
            f"journey.logout.session.{i}.v2",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/account/logout"), wait_visible("cl-main")],
            [obs("logged-out", "url", "", {"type": "regex", "pattern": "/$"})],
            timeout=90, mutate=True,
        )
    )

# register + verify flows (6)
for i in range(1, 7):
    L2.append(
        task(
            f"journey.register.verify.{i}.v2",
            [goto("/account/register"), wait_visible("#email"),
             fill("#email", f"register-{i}@example.com"), fill("#password", "Password123!"),
             fill("#confirm_password", "Password123!"), click("#agree_terms"),
             click("button[type='submit']"), wait_visible("#code")],
            [obs("verify-step", "text", "cl-page-heading", TEXT_EQ("verify your email"))],
            timeout=120, mutate=True,
        )
    )

# forgot + reset flows (6)
for i in range(1, 7):
    L2.append(
        task(
            f"journey.forgot.entry.{i}.v2",
            [goto("/account/forgot"), wait_visible("#email"),
             fill("#email", "poster@example.com"), click("button[type='submit']"), wait_visible("banner")],
            [obs("sent", "text", "banner", TEXT_EQ("check your email"))],
            timeout=90, mutate=True,
        )
    )

# favorite flows (4)
for i in range(1, 5):
    L2.append(
        task(
            f"journey.favorite.save.{i}.v2",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93"), wait_visible("listing-title"),
             click("form[action*='favorite'] button"), goto("/account/saved"), wait_visible("account-nav")],
            [obs("saved", "text", "cl-search-results", TEXT_EQ("1BR near Annex"))],
            timeout=120, mutate=True,
        )
    )

# saved search flows (4)
for i in range(1, 5):
    L2.append(
        task(
            f"journey.savedsearch.save.{i}.v2",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/search/area/toronto?query=annex"), wait_visible("result-list"),
             click("button:has-text('save search')"), goto("/account/searches"), wait_visible("account-nav")],
            [obs("search-saved", "text", "account-searches", TEXT_EQ("housing search"))],
            timeout=120, mutate=True,
        )
    )

# reply flows (5)
for i in range(1, 6):
    L2.append(
        task(
            f"journey.reply.send.{i}.v2",
            [goto("/toronto/housing/reply/1000001"), wait_visible("#name"),
             fill("#name", "Seeker"), fill("#email", "seeker@example.com"),
             fill("#message", f"Still available? - probe {i}"), click("button[type='submit']"),
             wait_visible("banner")],
            [obs("sent", "text", "banner", TEXT_EQ("reply has been sent"))],
            timeout=90, mutate=True,
        )
    )

# flag flows (5)
for i in range(1, 6):
    L2.append(
        task(
            f"journey.flag.submit.{i}.v2",
            [goto("/flag/1000001"), wait_visible("#reason"),
             click("#reason"), fill("#note", f"probe {i}"), click("button[type='submit']"),
             wait_visible("banner")],
            [obs("flagged", "text", "banner", TEXT_EQ("thank you"))],
            timeout=90, mutate=True,
        )
    )
assert len(L2) == 50, len(L2)

# --- L3 (80): full journeys, persistence, isolation, validation -----------
L3: list[dict] = []


def publish_flow(tid: str, title: str, price: str, neighborhood: str, postal: str, expect: str) -> dict:
    return task(
        tid,
        [goto("/account/login"), wait_visible("#email"),
         fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
         click("button[type='submit']"), wait_visible("account-nav"),
         goto("/post/"), wait_visible("#category"),
         click("#category"), click("option[value='sub']"),
         goto("/post/location"), wait_visible("#region"),
         fill("#region", "toronto"), fill("#neighborhood", neighborhood),
         goto("/post/details"), wait_visible("#title"),
         fill("#title", title), fill("#price", price), fill("#postal_code", postal),
         fill("#description", f"{title} - {neighborhood} - {price} CAD"),
         goto("/post/contact"), wait_visible("#contact_email"),
         fill("#contact_email", "poster@example.com"),
         goto("/post/preview"), wait_visible("listing-title"),
         click("button:has-text('publish')"), wait_visible("banner")],
        [obs("published", "text", "banner", TEXT_EQ("your posting is now live"))],
        timeout=240, mutate=True,
    )


PUBLISH_VARIANTS = [
    ("annex-1br-jul-aug", "1BR near Annex - furnished sublet Jul-Aug", "2400", "annex", "M6G"),
    ("yorkville-2br", "2BR sublet in Yorkville Aug-Sep", "3200", "yorkville", "M4W"),
    ("leslieville-studio", "Studio sublet Leslieville", "1600", "leslieville", "M4L"),
    ("corktown-1br", "Corktown 1BR sublet", "2050", "corktown", "M5A"),
    ("parkdale-room", "Parkdale room sublet", "900", "parkdale", "M6K"),
    ("beaches-2br", "Beaches 2BR sublet", "2700", "beaches", "M4E"),
    ("northyork-1br", "North York 1BR sublet", "1500", "north-york", "M2N"),
    ("etobicoke-studio", "Etobicoke studio sublet", "1300", "etobicoke", "M9V"),
    ("cityplace-1br", "CityPlace furnished sublet", "2400", "cityplace", "M5V"),
    ("roncesvalles-room", "Roncesvalles room sublet", "1000", "roncesvalles", "M6R"),
]
for i, (slug, title, price, nb, postal) in enumerate(PUBLISH_VARIANTS, start=1):
    L3.append(publish_flow(f"journey.publish.sublet.{i}.v3", title, price, nb, postal, "your posting is now live"))

# posting manage lifecycle (10)
for i in range(1, 11):
    L3.append(
        task(
            f"journey.manage.edit.{i}.v3",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             click("a[href*='/post/edit/']"), wait_visible("#title"),
             fill("#title", f"Edited posting {i}"), click("button[type='submit']"), wait_visible("listing-title")],
            [obs("edited", "url", "", {"type": "regex", "pattern": "/view/d/"})],
            timeout=120, mutate=True,
        )
    )

# photos flow (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.photos.upload.{i}.v3",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/post/category"), click("option[value='sub']"), goto("/post/location"),
             fill("#region", "toronto"), fill("#neighborhood", "annex"),
             goto("/post/details"), fill("#title", f"Photo test {i}"), fill("#price", "1000"),
             fill("#postal_code", "M6G"), fill("#description", "photo test"),
             goto("/post/contact"), fill("#contact_email", "poster@example.com"),
             goto("/post/photos"), wait_visible("cl-main")],
            [obs("photos-step", "url", "", {"type": "regex", "pattern": "/post/photos"})],
            timeout=240, mutate=True,
        )
    )

# persistence: refresh keeps session (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.persistence.refresh.{i}.v3",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             reload(), wait_visible("account-nav")],
            [obs("still-logged-in", "text", "account-nav", TEXT_EQ("your postings"))],
            timeout=120, mutate=True,
        )
    )

# persistence: favorite survives re-login (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.persistence.favorite-relogin.{i}.v3",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93"), wait_visible("listing-title"),
             click("form[action*='favorite'] button"), goto("/account/logout"),
             goto("/account/login"), fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/account/saved"), wait_visible("account-nav")],
            [obs("saved-after-relogin", "text", "cl-search-results", TEXT_EQ("1BR near Annex"))],
            timeout=180, mutate=True,
        )
    )

# isolation: seeker cannot touch poster data (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.isolation.seeker.{i}.v3",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "seeker@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/account/home"), wait_visible("account-nav")],
            [obs("no-foreign-data", "text", "account-home", TEXT_EQ("no postings yet"))],
            timeout=120, mutate=True,
        )
    )

# validation: empty required fields (10)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.validation.reply.{i}.v3",
            [goto("/toronto/housing/reply/1000001"), wait_visible("#name"),
             click("button[type='submit']"), wait_visible("form-error-box")],
            [obs("errors", "count", "field-error", COUNT_GE1)],
            timeout=90,
        )
    )
for i in range(1, 6):
    L3.append(
        task(
            f"journey.validation.register.{i}.v3",
            [goto("/account/register"), wait_visible("#email"),
             click("button[type='submit']"), wait_visible("form-error-box")],
            [obs("errors", "count", "field-error", COUNT_GE1)],
            timeout=90,
        )
    )

# rate limit (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.ratelimit.register.{i}.v3",
            [goto("/account/register"), wait_visible("#email"),
             fill("#email", f"ratelimit-{i}@example.com"), fill("#password", "Password123!"),
             fill("#confirm_password", "Password123!"), click("#agree_terms"),
             click("button[type='submit']"),
             goto("/account/register"), wait_visible("#email"),
             fill("#email", f"ratelimit-{i}@example.com"), fill("#password", "Password123!"),
             fill("#confirm_password", "Password123!"), click("#agree_terms"),
             click("button[type='submit']"), wait_visible("form-error-box")],
            [obs("limited", "text", "form-error-box", TEXT_EQ("five minutes"))],
            timeout=180, mutate=True,
        )
    )

# no-results route back (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.noresults.back.{i}.v3",
            [goto(f"/search/area/toronto?query=zzzz-no-match-websitebench-{i}"), wait_visible("no-results"),
             click(".no-results a[href*='cat=hhh']"), wait_visible("cl-breadcrumb")],
            [obs("back", "text", "cl-breadcrumb", TEXT_EQ("housing"))],
            timeout=90,
        )
    )

# removed posting leaves search (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.removed.leaves-search.{i}.v3",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/post/delete/1000021"), wait_visible("cl-page-heading"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/search/area/toronto?cat=apa"), wait_visible("cl-search-results")],
            [obs("gone", "count", "cl-search-result", COUNT_GE1)],
            timeout=180, mutate=True,
        )
    )

# signed-out permission prompts (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.signedout.prompt.{i}.v3",
            [goto("/post/"), wait_visible("banner")],
            [obs("prompt", "text", "banner", TEXT_EQ("log in to continue"))],
            timeout=90,
        )
    )

# posting delete lifecycle (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.manage.delete.{i}.v3",
            [goto("/account/login"), wait_visible("#email"),
             fill("#email", "poster@example.com"), fill("#password", "Websitebench1!"),
             click("button[type='submit']"), wait_visible("account-nav"),
             goto("/account/home"), wait_visible("account-nav"),
             click("a[href*='/post/delete/']"), wait_visible("cl-page-heading"),
             click("button[type='submit']"), wait_visible("account-nav")],
            [obs("deleted", "text", "account-home", TEXT_EQ("your postings"))],
            timeout=180, mutate=True,
        )
    )

# canonical sublet conditions e2e (5)
for i in range(1, 6):
    L3.append(
        task(
            f"journey.canonical.conditions.{i}.v3",
            [goto("/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93"), wait_visible("listing-title")],
            [obs("price", "text", "listing-price", TEXT_EQ("2,400")),
             obs("neighborhood", "text", "listing-title", TEXT_EQ("Annex")),
             obs("furnished", "text", "listing-attr", TEXT_EQ("furnished"))],
            timeout=90,
        )
    )

assert len(L3) == 80, len(L3)

T2_TASKS = T2_TASKS + L2 + L3
# level is a CASE property, not a task property; keep it here for case authoring
T2_LEVELS: dict[str, str] = {}
for idx, t in enumerate(T2_TASKS):
    T2_LEVELS[t["id"]] = "L1" if idx < 35 else ("L2" if idx < 85 else "L3")

# --- T3: 15 cross-cutting http checks ---------------------------------------
T3 = [
    ("t3-isolation-seeker-vs-poster", "/account/login", "seeker@example.com", "no postings yet"),
    ("t3-owner-permission-denied", "/account/login", "seeker@example.com", "permission denied"),
    ("t3-rate-limit-message", "/account/register", "", "five minutes"),
    ("t3-persistence-favorite-relogin", "/account/login", "poster@example.com", "saved"),
    ("t3-persistence-posting-account", "/account/login", "poster@example.com", "your postings"),
    ("t3-refresh-keeps-session", "/account/login", "poster@example.com", "your postings"),
    ("t3-deterministic-search", "/search/area/toronto?query=annex", "", "results"),
    ("t3-404-branded-recovery", "/view/d/does-not-exist/zzzzzz", "", "oops"),
    ("t3-help-no-private-data", "/about/help", "", "help"),
    ("t3-canonical-conditions", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "", "2,400"),
    ("t3-register-terms-required", "/account/register", "", "terms of use"),
    ("t3-login-wrong-password", "/account/login", "", "match"),
    ("t3-noresults-route-back", "/search/area/toronto?query=zzzz-no-match-websitebench", "", "no search results"),
    ("t3-housing-navigation", "/", "", "housing"),
    ("t3-signin-entry-fields", "/account/login", "", "Log in"),
]
T3_TASKS: list[dict] = []
for tid, path, _, pattern in T3:
    actions = [goto(path), wait_visible("cl-main")]
    obs_list = [obs("surface", "text", "cl-main", TEXT_EQ(pattern))]
    T3_TASKS.append(task(tid, actions, obs_list, timeout=90))

assert len(T1_TASKS) == 20 and len(T2_TASKS) == 165 and len(T3_TASKS) == 15

ALL_TASKS = T1_TASKS + T2_TASKS + T3_TASKS
assert len(ALL_TASKS) == 200
assert len({t["id"] for t in ALL_TASKS}) == 200


def _remap_css(value: str, task_id: str) -> str:
    """Map selectors from the pre-rebuild DOM to the rebuilt DOM."""
    if value == "result-list" and not any(
        k in task_id for k in ("favorite", "saved", "relogin")
    ):
        return "cl-search-results"
    if value == "cl-column-center":
        return "cl-search-results"
    if value == "cl-section-list":
        return "cl-breadcrumb"
    if value == "result-list, .no-results":
        return "cl-search-results, .no-results"
    if value == ".result-row .title a":
        return ".result-title a"
    if value == "button[name='save']":
        return "button:has-text('save search')"
    return value


for _task in ALL_TASKS:
    _tid = _task["id"]
    for _action in _task.get("actions", []):
        sel = _action.get("selector")
        if isinstance(sel, dict) and "css" in sel:
            sel["css"] = _remap_css(sel["css"], _tid)
    for _obs in _task.get("observations", []):
        sel = _obs.get("selector")
        if isinstance(sel, dict) and "css" in sel:
            sel["css"] = _remap_css(sel["css"], _tid)

task_suite = {
    "dsl_version": "websitebench.harbor.playwright-dsl.v1",
    "schema_version": "websitebench.harbor.task-suite.v1",
    "site_id": SITE_ID,
    "suite_id": "craigslist-tasks",
    "tasks": ALL_TASKS,
}

cases: list[dict] = []
for t in ALL_TASKS:
    tier = "T1" if t["id"] in {x["id"] for x in T1_TASKS} else ("T3" if t["id"] in {x["id"] for x in T3_TASKS} else "T2")
    case: dict = {
        "id": f"case-{t['id']}",
        "tier": tier,
        "kind": "journey" if tier == "T2" else "http",
        "timeout_sec": t["timeout_sec"],
        "task_id": t["id"],
    }
    if tier == "T2":
        case["level"] = T2_LEVELS[t["id"]]
    cases.append(case)

case_manifest = {
    "schema_version": "websitebench.harbor.case-manifest.v1",
    "manifest_id": "craigslist-cases",
    "site_id": SITE_ID,
    "status": "complete",
    "dsl_version": "websitebench.harbor.neutral-dsl.v1",
    "cases": cases,
}

INSTANCE.mkdir(parents=True, exist_ok=True)
(INSTANCE / "task-suite.json").write_text(json.dumps(task_suite, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
(INSTANCE / "case-manifest.json").write_text(json.dumps(case_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

counts = {"T1": 0, "T2": 0, "T3": 0, "L1": 0, "L2": 0, "L3": 0}
for c in cases:
    counts[c["tier"]] += 1
    if c["tier"] == "T2":
        counts[c["level"]] += 1
print("tasks:", len(ALL_TASKS), "cases:", len(cases), "counts:", counts)
