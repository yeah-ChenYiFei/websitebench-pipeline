from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app import CONTENT, app


ROOT = Path(__file__).resolve().parents[2]
client = TestClient(app, base_url="https://songkick.local")


def test_health_exposes_frozen_identity() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "site_id": "songkick",
        "capture_id": "songkick-20260904T132056Z-g1-remediation",
    }


def test_every_frozen_route_keeps_status_and_title_identity() -> None:
    seen: set[str] = set()
    for page in CONTENT["pages"]:
        path = page["requested_path"]
        if path in seen:
            continue
        seen.add(path)
        response = client.get(path, follow_redirects=True)
        assert response.status_code == page["http_status"], page["id"]
        assert f"<title>{page['title']}</title>" in html.unescape(response.text), page["id"]


def test_contract_evidence_is_not_supplied_by_a_hidden_roster() -> None:
    document = client.get("/").text
    css = client.get("/assets/site.css").text
    assert "contract-roster" not in document
    assert ".contract-roster" not in css


def test_external_destination_is_local_http_200_soft_404() -> None:
    response = client.get("/__external__", params={"destination": "https://blog.songkick.com/"})
    assert response.status_code == 200
    assert response.headers["x-websitebench-boundary"] == "external-soft-404"
    assert "blog.songkick.com" in response.text
    assert 'href="https://blog.songkick.com/' not in response.text


def test_every_external_contract_identity_is_on_its_real_visible_page() -> None:
    pages = {page["id"]: page["requested_path"] for page in CONTENT["pages"]}
    for recipe_path in sorted((ROOT / "scope/recipes").glob("*external-link*.json")):
        recipe = json.loads(recipe_path.read_text())
        page_id = recipe["checkpoint_id"].split(":")[1]
        document = client.get(pages[page_id]).text
        assert f'data-wb-external-id="{recipe["selector"].split(chr(34))[1]}"' in document
        assert f'href="{html.escape(recipe["expected_href"], quote=True)}"' in document


def test_ticket_provider_opens_the_local_soft_404_in_a_new_tab() -> None:
    response = client.get("/concerts/43365625-steve-lacy-at-place-bell")
    assert 'data-wb-ticket-link="ticketmaster-ca"' in response.text
    assert 'target="_blank"' in response.text
    assert 'id="external-boundary-status"' not in response.text
    assert "Flag a problem" in response.text
    assert 'data-wb-external-id="external-031"' in response.text
    assert 'href="https://support.songkick.com/hc/en-us/requests/new"' in response.text
    assert client.get("/tickets/34252807").status_code == 200
    assert 'data-wb-component="external-boundary"' in client.get("/tickets/34252807").text
    assert client.get("/tickets/34247919").status_code == 200


def test_unknown_first_party_route_is_a_branded_hard_404() -> None:
    response = client.get("/__websitebench_missing_songkick__")
    assert response.status_code == 404
    assert "Hmmmm, we couldn't find that." in html.unescape(response.text)
    assert "Search for events or artists" in response.text


def test_declared_runtime_assets_are_local_and_present() -> None:
    manifest = json.loads((ROOT / "source-assets/manifest.json").read_text())
    content = json.loads((ROOT / "clone/content.json").read_text())
    assert manifest["closure_status"] == "declared"
    assert len(manifest["assets"]) == content["scope_counts"]["runtime_assets"] == 118
    for asset in manifest["assets"]:
        runtime = ROOT / asset["runtime_path"]
        assert runtime.is_file(), runtime
        assert not urlsplit(asset["runtime_path"]).scheme


def test_every_candidate_source_asset_reference_resolves_locally() -> None:
    candidate = ROOT / "clone"
    references: set[str] = set()
    for relative in ("app.py", "content.json", "assets/site.css", "assets/site.js"):
        text = (candidate / relative).read_text(encoding="utf-8")
        references.update(re.findall(r"/assets/source/[A-Za-z0-9._/-]+", text))
    missing = [
        reference
        for reference in sorted(references)
        if not (candidate / reference.removeprefix("/")).is_file()
    ]
    assert missing == []


def test_search_is_deterministic_and_source_api_free() -> None:
    hit = client.get("/api/search", params={"q": "Coldplay"})
    miss = client.get("/api/search", params={"q": "zzzzsongkicknoresult"})
    assert hit.status_code == miss.status_code == 200
    assert hit.json()["state"] == "search-results-coldplay"
    assert hit.json()["result_link_count"] == 1
    assert miss.json()["state"] == "search-no-results"
    assert miss.json()["result_link_count"] == 0
    assert hit.headers["x-songkick-data-source"] == "local-frozen"
    result_links = [item for item in hit.json()["controls"] if item["tag"] == "a"]
    assert all(item["local_path"].startswith(("/artists/", "/events/", "/en/artists/", "/en/events/")) for item in result_links)
    assert all(client.get(item["local_path"]).status_code == 200 for item in result_links)


def test_listing_cards_keep_the_entity_they_name() -> None:
    home = client.get("/").text
    artists = client.get("/artists").text
    concerts = client.get("/concerts").text
    expected_artists = {
        "Coldplay": "/artists/197928-coldplay",
        "Rihanna": "/artists/139648-rihanna",
        "The Weeknd": "/artists/4363463-weeknd",
        "Eminem": "/artists/182968-eminem",
        "Drake": "/artists/556955-drake",
        "Taylor Swift": "/artists/217815-taylor-swift",
        "Bruno Mars": "/artists/941964-bruno-mars",
        "Kanye West": "/artists/552177-kanye-west",
        "Maroon 5": "/artists/181875-maroon-5",
        "Lady Gaga": "/artists/974908-lady-gaga",
    }
    for name, path in expected_artists.items():
        assert f'href="{path}"' in home, name
        assert f'href="{path}"' in artists, name
    for path in (
        "/concerts/43203206-louisjean-cormier-at-bieres-et-saveurs",
        "/concerts/43216570-greenwoodz-at-place-bourget",
        "/concerts/43234983-andreanne-a-malette-at-festival-belle-banlieue",
        "/concerts/43308709-julyan-at-laval-en-folie",
        "/concerts/43316120-la-grandmesse-at-laval-en-folie",
    ):
        assert f'href="{path}"' in concerts
        assert client.get(path).status_code == 200


def test_collection_page_two_is_a_distinct_real_batch() -> None:
    first = client.get("/metro-areas/27377-canada-montreal").text
    query_second = client.get("/metro-areas/27377-canada-montreal?page=2").text
    route_second = client.get("/en/metro-areas/27377-canada-montreal").text
    card_pattern = re.compile(r'<article class="list-card">.*?<h3><a[^>]*>(.*?)</a>', re.S)
    first_titles = card_pattern.findall(first)
    query_titles = card_pattern.findall(query_second)
    route_titles = card_pattern.findall(route_second)
    assert first_titles
    assert query_titles == route_titles
    assert first_titles != query_titles


def test_specialized_page_families_expose_their_frozen_components() -> None:
    expectations = {
        "/": "location-banner",
        "/artists": "artist-list",
        "/venues/3536914-place-bell": "venue-profile",
        "/festivals": "festival-list",
        "/festivals/3556859-music4cancer/id/43273560-music4cancer-2026": "festival-profile",
        "/session/filter_metro_area": "location-picker",
    }
    for path, component in expectations.items():
        response = client.get(path)
        assert response.status_code == 200
        assert f'data-wb-component="{component}"' in response.text, path


def test_event_hero_uses_the_matching_artist_image() -> None:
    response = client.get("/concerts/43365625-steve-lacy-at-place-bell")
    assert response.status_code == 200
    assert "/artists/8538309/large_avatar" in response.text
    assert "back-button" not in response.text


def test_reset_visual_states_are_addressable_without_source_requests() -> None:
    error = client.get("/password_reset_requests/new?state=captcha-error")
    success = client.get("/session/new?reset=success")
    assert 'data-wb-component="password-reset-captcha-error"' in error.text
    assert 'data-wb-component="password-reset-success-notice"' in success.text


def test_home_exposes_both_source_carousel_transitions() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="event-carousel"' in response.text
    assert 'data-carousel="event-carousel"' in response.text
    assert 'id="artist-carousel"' in response.text
    assert 'data-carousel="artist-carousel"' in response.text
    assert response.text.count('class="poster-card"') >= 8
    assert response.text.count('class="round-card"') >= 8


def test_carousels_restore_the_page_viewport_after_playwright_scrolls_the_control() -> None:
    script = client.get("/assets/site.js").text
    assert "frame.scrollTop = 0" in script


def test_concerts_route_uses_its_source_marketing_landing() -> None:
    response = client.get("/concerts")
    assert response.status_code == 200
    assert 'data-wb-component="concerts-landing"' in response.text
    assert "/assets/source/css-deps/d0987-cbbe3bf9d5124117.webp" in client.get("/assets/site.css").text
    assert "The hottest tickets in Montreal" in response.text


def test_auth_routes_use_the_source_account_shell_without_public_chrome() -> None:
    expectations = {
        "/session/new": "login",
        "/signup/new": "signup",
        "/password_reset_requests/new": "password-reset",
    }
    for path, kind in expectations.items():
        response = client.get(path)
        assert response.status_code == 200
        assert f'data-auth-kind="{kind}"' in response.text
        assert 'data-wb-component="global-header"' not in response.text
        assert 'data-wb-component="global-footer"' not in response.text
    assert "/assets/source/css-deps/d0873-892328a6ed7dbb85.webp" in client.get("/assets/site.css").text


def test_auth_provider_controls_keep_their_exact_source_identity() -> None:
    sign_in = client.get("/session/new").text
    sign_up = client.get("/signup/new").text
    assert 'href="/auth/google_oauth2?locale=en"' in sign_in
    assert 'href="/auth/apple?locale=en"' in sign_in
    assert 'href="/facebook-password-reset"' in sign_in
    assert "Facebook%20accountaccount" not in sign_in
    assert 'href="/auth/google_oauth2?locale=en"' in sign_up
    assert 'href="/auth/apple?locale=en"' in sign_up
    for path in ("/auth/google_oauth2?locale=en", "/auth/apple?locale=en", "/facebook-password-reset"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["x-websitebench-boundary"] == "external-soft-404"


def test_all_page_shells_use_a_fixed_viewport_with_internal_scrolling() -> None:
    for path in ("/", "/info/about", "/session/new", "/__websitebench_missing_songkick__"):
        response = client.get(path)
        assert 'class="viewport-frame"' in response.text, path

    boundary = client.get(
        "/__external__", params={"destination": "https://blog.songkick.com/"}
    )
    assert 'class="viewport-frame"' in boundary.text

    css = client.get("/assets/site.css").text
    assert "html,body{height:100%;max-height:100%;overflow:hidden}" in css
    assert ".viewport-frame{height:100%;overflow:auto;position:relative}" in css


def test_app_route_uses_the_standalone_source_download_landing() -> None:
    response = client.get("/app")
    assert response.status_code == 200
    assert 'data-wb-component="app-download"' in response.text
    assert 'data-wb-component="global-header"' not in response.text
    assert 'data-wb-component="global-footer"' not in response.text
    assert "a0084-songkick-logo-svg-47b1d1f992.svg" in response.text
    assert "a0088-mobile-device-new-png-5cdeb2f228.png" in response.text
    app_download = response.text.split('<main class="app-download"', 1)[1].split("</main>", 1)[0]
    assert 'data-wb-external-id="external-027"' in app_download
    assert 'data-wb-external-id="external-029"' in app_download
    assert 'href="https://play.google.com' in app_download
    assert 'href="https://itunes.apple.com' in app_download


def test_home_carousels_use_source_entity_artwork_without_generic_placeholders() -> None:
    document = client.get("/").text
    carousel = document.split('<main class="home-main">', 1)[1].split("</main>", 1)[0]
    assert "d0916-169e94a8b274d996.png" not in carousel
    for artist_id, label in (
        ("68043", "Gorillaz"),
        ("276130", "AC/DC"),
        ("8030683", "Doja Cat"),
        ("108359", "The Black Keys"),
        ("544909", "Weezer"),
        ("233074", "The Smashing Pumpkins"),
        ("10112623", "Olivia Rodrigo"),
        ("732760", "Naughty Boy"),
        ("292712", "Kenny Chesney"),
    ):
        assert artist_id in carousel, label
        assert f'alt="{label}"' in carousel
    assert 'data-wb-media=""' not in document


def test_data_boundaries_preserve_the_full_entity_identity() -> None:
    expectations = {
        "/genres/indie-alt": "Indie &amp; Alt",
        "/genres/hip-hop": "Hip-Hop",
        "/festivals/999-music4cancer-2026": "Music4Cancer 2026",
    }
    for path, heading in expectations.items():
        response = client.get(path)
        assert response.status_code == 200
        assert f"<h1>{heading}</h1>" in response.text


def test_removed_boundary_marker_has_no_dead_css_rule() -> None:
    assert ".boundary-status" not in client.get("/assets/site.css").text


def test_about_route_uses_the_source_brief_and_local_frozen_artwork() -> None:
    response = client.get("/info/about")
    assert response.status_code == 200
    assert 'data-wb-component="about-brief"' in response.text
    assert "Bringing the magic of live music to fans everywhere." in response.text
    assert "/assets/source/css-deps/d1044-b2189535ff5fd4a0.webp" in client.get("/assets/site.css").text
    assert 'href="https://accounts.songkick.com' not in response.text


def test_live_streams_route_uses_source_hero_and_local_event_list() -> None:
    response = client.get("/live-stream-concerts")
    assert response.status_code == 200
    assert 'data-wb-component="live-stream-concert-list"' in response.text
    assert "a0071-live-streams-hero-image-webp-1700e00c90.webp" in response.text
    assert "All upcoming live streamed concerts" in response.text
    assert 'href="https://www.songkick.com/live-stream-concerts' not in response.text


def test_news_and_information_routes_use_source_specific_layouts() -> None:
    news = client.get("/news")
    developer = client.get("/developer")
    design = client.get("/design")
    assert 'data-wb-component="news-index"' in news.text
    assert "a0857-video-game-concert-content-header-jpg-3db1a3634c.jpg" in news.text
    assert 'data-wb-component="developer-api-index"' in developer.text
    assert "d1052-83fd5c15691a1f14.png" in client.get("/assets/site.css").text
    assert 'data-wb-component="blank-design-surface"' in design.text
    assert 'data-wb-component="global-header"' not in design.text


def test_privacy_and_popular_artist_routes_keep_their_source_document_models() -> None:
    privacy = client.get("/info/privacy")
    leaderboard = client.get("/leaderboards/popular_artists?page=2")
    assert 'data-wb-component="privacy-policy"' in privacy.text
    assert "Last updated: July 9, 2026" in privacy.text
    assert 'data-wb-component="popular-artist-leaderboard"' in leaderboard.text
    assert "PARTYNEXTDOOR" in leaderboard.text
    assert 'data-artist-id="201"' in leaderboard.text


def test_query_addressable_location_and_date_capture_states() -> None:
    toronto = client.get("/session/filter_metro_area?wb_state=search-toronto")
    empty = client.get("/session/filter_metro_area?wb_state=search-empty")
    assert 'value="Toronto"' in toronto.text
    assert toronto.text.count('class="location-result-row"') == 6
    assert "Sorry, we found no results" in html.unescape(empty.text)
    assert 'data-page-id="location-search-empty"' in empty.text

    for state, count in (("today", "16"), ("next-7-days", "75"), ("next-30-days", "309")):
        response = client.get(
            "/en/metro-areas/27377-canada-montreal",
            params={"wb_state": state},
        )
        assert f"<strong>{count}</strong> upcoming events" in response.text
        assert f'data-page-id="montreal-{state}"' in response.text


def test_region_pages_keep_their_frozen_location_identity_and_legacy_canvas() -> None:
    regions = {
        "/metro-areas/26330-us-sf-bay-area": "SF Bay Area concerts",
        "/metro-areas/17835-us-los-angeles-la": "Los Angeles (LA) concerts",
        "/metro-areas/7644-us-new-york-nyc": "New York (NYC) concerts",
    }
    for path, nav_label in regions.items():
        response = client.get(path)
        assert response.status_code == 200
        assert nav_label in response.text

    css = client.get("/assets/site.css").text
    assert 'body[data-page-id^="region-"] .top-ad' in css


def test_event_profiles_use_event_specific_frozen_dates_venues_and_themes() -> None:
    events = {
        "/concerts/43365625-steve-lacy-at-place-bell": ("06 October 2026", "Place Bell"),
        "/concerts/43371713-gipsy-kings-at-mtelus": ("14 November 2026", "MTELUS"),
        "/concerts/43381053-gorgon-city-at-new-city-gas": ("11 October 2026", "New City Gas"),
        "/concerts/43383403-yebba-at-lolympia": ("26 October 2026", "L'Olympia"),
        "/concerts/43382897-donavon-frankenreiter-at-le-ministere": ("18 October 2026", "Le Ministère"),
        "/concerts/43390372-salif-keita-at-place-des-arts": ("02 May 2027", "Place des Arts"),
        "/concerts/43371714-clara-la-san-at-lolympia": ("06 November 2026", "L'Olympia"),
        "/concerts/43390357-too-many-zooz-at-theatre-fairmount-theatre": ("20 November 2026", "Théâtre Fairmount Theatre"),
        "/concerts/43371710-i-hate-models-at-hall-est-du-stade-olympique": ("14 November 2026", "Hall Est Du Stade Olympique"),
        "/concerts/43382670-sullivan-king-at-mtelus": ("06 November 2026", "MTELUS"),
    }
    themes: set[str] = set()
    for path, (date, venue) in events.items():
        response = client.get(path)
        document = html.unescape(response.text)
        assert response.status_code == 200
        assert date in document, path
        assert venue in document, path
        marker = 'data-event-theme="'
        assert marker in response.text, path
        themes.add(response.text.split(marker, 1)[1].split('"', 1)[0])
    assert len(themes) >= 7


def test_venue_profiles_use_source_specific_location_counts_and_empty_image_state() -> None:
    mtelus = client.get("/venues/20838-mtelus")
    assert "Montreal, QC, Canada" in mtelus.text
    assert "<b>62</b>" in mtelus.text
    assert "<b>2,324</b>" in mtelus.text

    hall = client.get("/venues/4661630-hall-est-du-stade-olympique")
    assert "Montreal, QC, Canada" in hall.text
    assert "1" in hall.text
    assert "0" in hall.text
    hero = hall.text.split("venue-grid", 1)[1].split("</section>", 1)[0]
    assert "<img" not in hero
    assert 'data-venue-theme="empty"' in hall.text


def test_photo_venues_use_their_frozen_logos_palette_and_dates() -> None:
    expectations = {
        "/venues/3536914-place-bell": (
            "a0845-col2-ca10008dfd.jpg",
            "Wednesday 09 September 2026",
        ),
        "/venues/4016319-le-ministere": (
            "a0849-col2-6dad6dd689.jpg",
            "Thursday 10 September 2026",
        ),
        "/venues/1086866-theatre-fairmount-theatre": (
            "a0838-col2-5c70c07551.jpg",
            "Saturday 05 September 2026",
        ),
    }
    for path, (image_name, date) in expectations.items():
        response = client.get(path)
        assert image_name in response.text, path
        assert date in response.text, path
    css = client.get("/assets/site.css").text
    assert '.venue-hero[data-venue-theme="photo"] .venue-grid>img{display:block}' in css


def test_all_frozen_artist_profiles_keep_source_status_counts_and_palette() -> None:
    profiles = {
        "/artists/10355080-westside-cowboy": ("westside-cowboy", "On tour", "12,698", "24"),
        "/artists/197928-coldplay": ("coldplay", "Off tour", "4,588,396", "0"),
        "/artists/139648-rihanna": ("rihanna", "Off tour", "4,545,791", "0"),
        "/artists/4363463-weeknd": ("the-weeknd", "On tour", "4,345,205", "10"),
        "/artists/182968-eminem": ("eminem", "Off tour", "4,226,051", "0"),
        "/artists/556955-drake": ("drake", "Off tour", "4,094,616", "0"),
        "/artists/217815-taylor-swift": ("taylor-swift", "Off tour", "4,073,840", "0"),
        "/artists/941964-bruno-mars": ("bruno-mars", "On tour", "3,913,689", "31"),
        "/artists/552177-kanye-west": ("kanye-west", "Off tour", "3,749,872", "0"),
        "/artists/181875-maroon-5": ("maroon-5", "On tour", "3,670,290", "8"),
        "/artists/974908-lady-gaga": ("lady-gaga", "Off tour", "3,621,923", "0"),
    }
    for path, (theme, status, fans, upcoming) in profiles.items():
        response = client.get(path)
        assert response.status_code == 200
        assert f'data-artist-theme="{theme}"' in response.text
        assert f'>{status}</span>' in response.text
        assert f"{fans} fans" in response.text
        assert f"Coming up <b>{upcoming}</b>" in response.text
        if upcoming == "0":
            assert "No upcoming concerts" in response.text
            assert "artist-event-card" not in response.text
        else:
            assert "artist-event-card" in response.text


def test_bruno_lazy_layout_tracks_the_frozen_scroll_transition() -> None:
    script = client.get("/assets/site.js").text
    css = client.get("/assets/site.css").text
    assert "document.body.dataset.lazyLayout = 'settled'" in script
    assert 'body[data-page-id="artist-07-bruno-mars"][data-lazy-layout="settled"] .artist-top-gap{height:115px}' in css


def test_rock_genre_route_uses_its_source_editorial_landing() -> None:
    response = client.get("/genres/rock")
    assert response.status_code == 200
    assert 'data-wb-component="genre-landing"' in response.text
    for heading in (
        "Your ultimate Rock concert guide",
        "Top Rock Concerts in Montreal",
        "Trending concerts near you",
        "Top rock venues worldwide",
        "Top cities for Rock events worldwide",
        "Trending Rock Artists",
    ):
        assert heading in html.unescape(response.text)
    assert "a0875-genre-rock-brief-6726a0ae21.webp" in response.text


def test_search_modal_has_source_sized_empty_and_no_result_states() -> None:
    response = client.get("/")
    assert 'data-search-state="empty"' in response.text
    css = client.get("/assets/site.css").text
    assert '#search-modal[data-search-state="empty"] .search-dialog' in css
    assert '#search-modal[data-search-state="no-results"] .search-dialog' in css
    script = client.get("/assets/site.js").text
    assert "searchModal.dataset.searchState = 'no-results'" in script


def test_home_theme_and_only_empty_search_use_the_source_light_visual_variant() -> None:
    css = client.get("/assets/site.css").text
    assert "/assets/source/css-deps/d0996-e269e2cb72a2a2e9.jpg" in css
    assert 'body[data-page-id="home"].theme-dark .home-hero{height:605px;color:#1a1a1a;background:#fff}' in css
    assert 'body[data-page-id="home"].home-search-variant .home-hero' in css
    assert 'body[data-page-id="home"].theme-dark .home-hero' in css
    assert 'body[data-page-id="home"]:has(#search-modal[data-search-state="empty"]:not([hidden])) .home-hero' in css
    script = client.get("/assets/site.js").text
    assert "classList.add('home-search-variant')" not in script


def test_german_and_spanish_home_routes_use_the_frozen_event_artwork() -> None:
    for locale in ("de", "es"):
        response = client.get(f"/{locale}")
        assert response.status_code == 200
        assert "Gorillaz" in response.text
        assert "AC/DC" in response.text
        assert "Doja Cat" in response.text


def test_not_found_uses_the_frozen_legacy_hard_404_shell() -> None:
    response = client.get("/__websitebench_missing_songkick__")
    assert response.status_code == 404
    assert 'data-wb-component="legacy-not-found"' in response.text
    assert 'data-wb-component="global-footer"' not in response.text
    assert 'data-wb-component="global-header"' not in response.text
    assert "The page you were trying to visit doesn't exist or has been deleted." in response.text


def test_password_reset_visual_states_keep_source_specific_structures() -> None:
    initial = client.get("/password_reset_requests/new")
    assert 'class="auth-back" href="/session/new"' in initial.text
    assert 'class="auth-help"' in initial.text
    captcha = client.get("/password_reset_requests/new?state=captcha-error")
    assert 'data-wb-component="captcha-widget"' in captcha.text
    assert 'data-wb-component="password-reset-captcha-error"' in captcha.text

    success = client.get("/session/new?reset=success")
    assert 'class="auth-reset-banner"' in success.text
    assert 'data-wb-component="password-reset-success-notice"' in success.text


def test_public_pages_include_the_authenticated_shell_without_exposing_it_by_default() -> None:
    response = client.get("/")
    assert 'data-wb-component="authenticated-navigation"' in response.text
    assert 'data-wb-component="authenticated-dashboard"' in response.text
    css = client.get("/assets/site.css").text
    assert 'body[data-session="authenticated-user"]' in css


def test_authenticated_dashboard_uses_source_grounded_artist_images() -> None:
    response = client.get("/")
    expected_assets = {
        "a0595-large-avatar-5b543e354d.jpg",
        "a0264-large-avatar-ff0798384f.jpg",
        "a0871-dashboard-dinosaur-jr-45f76aee46.jpg",
        "a0872-dashboard-whipped-cream-af3c0b0fdb.jpg",
        "a0873-dashboard-oso-oso-3668d164fa.jpg",
        "a0874-dashboard-katy-nichole-10211128.jpg",
    }
    for asset in expected_assets:
        assert f'/assets/source/{asset}' in response.text


def test_localized_home_routes_and_remaining_editorial_families_are_specific() -> None:
    localized = {
        "/de": "Deine Stadt",
        "/es": "Tu ciudad",
        "/fr": "Ta ville",
        "/pt": "Sua cidade",
    }
    for path, headline in localized.items():
        response = client.get(path)
        assert 'data-wb-component="home-hero"' in response.text
        assert headline in response.text

    spanish = client.get("/es")
    for artist_id, label in (
        ("68043", "Gorillaz"),
        ("276130", "AC/DC"),
        ("8030683", "Doja Cat"),
        ("108359", "The Black Keys"),
        ("544909", "Weezer"),
        ("428874", "The Smashing Pumpkins"),
    ):
        assert f"/assets/source/locale-es/{artist_id}-large-avatar." in spanish.text
        assert label in html.unescape(spanish.text)

    jobs = client.get("/jobs")
    trending = client.get("/leaderboards/trending_artists")
    assert 'data-wb-component="jobs-page"' in jobs.text
    assert 'data-wb-component="global-header"' not in jobs.text
    assert 'data-wb-component="trending-artist-leaderboard"' in trending.text
    assert "Westside Cowboy" in trending.text

    for path in ("/info/cookies", "/info/guidelines", "/info/security", "/info/terms"):
        assert 'data-wb-component="legal-document"' in client.get(path).text
