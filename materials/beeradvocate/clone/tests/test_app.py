from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="websitebench-beeradvocate-test-")
os.environ["WEBSITEBENCH_ENABLE_TEST_LOGIN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as candidate
from fastapi.testclient import TestClient


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and href.startswith("/"):
            self.links.add(href)


def client() -> TestClient:
    return TestClient(candidate.app, base_url="https://beeradvocate.test")


def register_local_member(test_client: TestClient, username: str, email: str) -> None:
    response = test_client.post(
        "/community/register/start",
        data={
            "username": username,
            "email": email,
            "password": "LocalPassphrase!2026",
            "confirm_password": "LocalPassphrase!2026",
            "terms": "accepted",
            "redirect": "/",
        },
    )
    assert response.status_code == 200
    assert "Your verification request is ready" in response.text
    response = test_client.post(
        "/community/register/complete",
        data={"redirect": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_homepage_all_local_links_resolve() -> None:
    test_client = client()
    response = test_client.get("/")
    assert response.status_code == 200
    parser = LinkParser()
    parser.feed(response.text)
    assert len(parser.links) >= 25
    assert {
        "/about/",
        "/contact/",
        "/follow",
        "/society/",
        "/data/?action=add_beer",
        "/data/?action=add_place",
        "/community/forums/the-bar.68/",
        "/community/find-new/posts",
        "/beer/profile/140/",
        "/beer/top-styles/235/",
        "/community/threads/683623/unread",
    } <= parser.links
    failures = []
    for href in sorted(parser.links):
        result = test_client.get(href, follow_redirects=False)
        if result.status_code >= 400:
            failures.append((href, result.status_code))
    assert failures == []


def test_source_homepage_route_families_have_local_interactive_destinations() -> None:
    test_client = client()
    direct_pages = {
        "/about/": "About BeerAdvocate",
            "/contact/": "Contact actions are currently unavailable",
            "/follow": "Social actions are currently unavailable",
        "/society/": "Society Milestones",
        "/trading/": "Beer Trading",
        "/place/directory/": "12 places found",
        "/place/visits/": "Place Visits",
        "/community/forums/68/": "The Bar",
        "/community/find-new/posts": "Recent community activity",
        "/beer/profile/140/": "Sierra Nevada Brewing Co.",
        "/beer/top-styles/235/": "Festbier / Wiesnbier",
    }
    for path, visible_text in direct_pages.items():
        result = test_client.get(path)
        assert result.status_code == 200, path
        assert visible_text in result.text, path

    thread = test_client.get(
        "/community/threads/683974/unread", follow_redirects=False
    )
    assert thread.status_code == 302
    assert thread.headers["location"].startswith("/community/thread/")

    for action in ("add_beer", "add_place"):
        result = test_client.get(f"/data/?action={action}", follow_redirects=False)
        assert result.status_code == 303
        assert result.headers["location"].startswith("/community/login/")
    assert test_client.get("/data/?action=unknown").status_code == 404


def test_source_aliases_and_detail_evidence_markers() -> None:
    test_client = client()
    expected_pages = {
        "/terms/": "Terms of Service",
        "/privacy/": "Privacy",
        "/code/": "Code of Conduct",
        "/beer/trending/": "240 beers found",
        "/community/members/beeradvocate/": "BeerAdvocate community member",
    }
    for path, visible_text in expected_pages.items():
        response = test_client.get(path)
        assert response.status_code == 200, path
        assert visible_text in response.text, path

    detail = test_client.get("/beer/profile/147/1160/")
    assert detail.status_code == 200
    for marker in (
        "Beer Geek Stats",
        "Formerly known as Imperial Russian Stout",
        "Recent ratings and reviews.",
        "Add Beer",
        "Top Rated",
    ):
        assert marker in detail.text
    assert "class='active' href='/beer/'" in detail.text


def test_r18_source_evidence_route_contracts() -> None:
    test_client = client()
    routes = {
        "/community/forums/the-bar.68/": "The Bar",
        "/community/forums/beer-talk.39/": "Beer Talk",
        "/community/forums/18/": "BeerAdvocate Talk",
        "/community/forums/the-bar.68/page-2": "page 2",
        "/community/threads/683979/": "What beer are you drinking now? #5053",
        "/community/threads/what-beer-are-you-drinking-now-5053.683979/": "What beer are you drinking now? #5053",
        "/community/threads/what-beer-are-you-drinking-now-5053.683979/page-2": "What beer are you drinking now? #5053",
        "/community/posts/8421924/": "Post #8421924",
        "/beer/styles/116/": "American IPA",
        "/beer/top-styles/84/": "Russian Imperial Stout",
        "/place/city/28/": "San Diego Beer Guide",
        "/place/directory/9/US/CA/": "California Beer Guide",
            "/community/lost-password/": "Account recovery is handled securely",
        "/community/search/?type=post": "Search Forums",
        "/community/misc/quick-navigation-menu": "Quick Navigation",
    }
    for path, marker in routes.items():
        response = test_client.get(path, follow_redirects=True)
        assert response.status_code == 200, path
        assert marker in response.text, path


def test_r18_style_and_stone_brewery_source_counts() -> None:
    test_client = client()
    styles_response = test_client.get("/beer/styles/")
    assert styles_response.status_code == 200
    parser = LinkParser()
    parser.feed(styles_response.text)
    source_style_links = {
        href for href in parser.links
        if href.startswith("/beer/styles/") and href != "/beer/styles/"
    }
    assert len(source_style_links) == 131
    exact_styles = {
        12: "Rye Beer",
        29: "Märzen",
        35: "Doppelbock",
        84: "Russian Imperial Stout",
        116: "American IPA",
        245: "Hazy Imperial IPA",
    }
    for style_id, style in exact_styles.items():
        response = test_client.get(f"/beer/styles/{style_id}/")
        assert response.status_code == 200
        assert style in response.text

    brewery = test_client.get("/beer/profile/147/")
    assert brewery.status_code == 200
    assert "Active Beers (193)" in brewery.text
    assert brewery.text.count("href='/beer/profile/147/") >= 193
    assert "class='active' href='/place/'" in brewery.text
    observed_beer = test_client.get("/beer/profile/147/88/")
    assert observed_beer.status_code == 200
    assert "Stone IPA" in observed_beer.text


def test_r18_page_family_semantics() -> None:
    test_client = client()
    recent = test_client.get("/beer/")
    assert "Beer Ratings: Recent" in recent.text
    assert recent.text.count("class='source-review'") == 50

    search = test_client.get("/search/?q=Imperial+Stout")
    assert "Search: Imperial Stout" in search.text
    assert "Forums" in search.text
    assert "Places" in search.text
    assert "Articles" in search.text
    assert "Anonymous results are limited to the first 10" in search.text

    top = test_client.get("/beer/top-rated/")
    assert "Top 250 Rated Beers" in top.text
    assert top.text.count("<tr>") == 241
    for marker in ("Styles", "Trending", "New", "Fame", "Popular", "Worst"):
        assert marker in top.text

    places = test_client.get("/place/")
    for control in ("name='name'", "name='city'", "name='c_id'", "name='s_id'"):
        assert control in places.text


def test_general_information_pages_keep_home_navigation_active() -> None:
    test_client = client()
    for path in ("/about/", "/contact/", "/community/privacy/"):
        response = test_client.get(path)
        assert response.status_code == 200
        assert "class='active' href='/'" in response.text


def test_packaged_runtime_matches_authoring_contract() -> None:
    clone_root = Path(__file__).resolve().parents[1]
    packaged = (clone_root / "backend" / "runtime.json").read_bytes()
    authoring = (clone_root.parent / "backend" / "runtime.json").read_bytes()
    assert packaged == authoring


def test_localized_assets_are_served_and_byte_closed() -> None:
    test_client = client()
    home = test_client.get("/")
    assert "/static/assets/brand/beeradvocate-nav-logo.webp" in home.text
    assert "/static/assets/beers/806254.jpg" in home.text
    assert home.text.count("source-slice") >= 2
    assert "/static/assets/evidence/home-desktop.png" in home.text

    logo = test_client.get("/static/assets/brand/beeradvocate-nav-logo.webp")
    beer = test_client.get("/static/assets/beers/806254.jpg")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/webp"
    assert beer.status_code == 200
    assert beer.headers["content-type"] == "image/jpeg"

    clone_root = Path(__file__).resolve().parents[1]
    site_root = clone_root.parent
    manifest = json.loads(
        (site_root / "source-assets" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["closure_status"] == "declared"
    assert len(manifest["assets"]) == 34
    assert sum(asset["required"] for asset in manifest["assets"]) == 14
    capture_report = json.loads(
        (
            site_root
            / "source-assets"
            / "2026-08-20.edge-r1"
            / "capture-report.json"
        ).read_text(encoding="utf-8")
    )
    assert capture_report["closure_ready"] is True
    assert capture_report["missing_required_paths"] == []
    for asset in manifest["assets"]:
        source = site_root / asset["source_path"]
        runtime = site_root / asset["runtime_path"]
        assert source.read_bytes() == runtime.read_bytes()


def test_open_database_does_not_start_a_write_transaction() -> None:
    first = candidate.open_database()
    second = candidate.open_database()
    try:
        assert first.in_transaction is False
        assert second.in_transaction is False
        assert second.execute("SELECT COUNT(*) FROM reviews").fetchone() is not None
    finally:
        first.close()
        second.close()


def test_query_and_mutation_security_boundaries() -> None:
    test_client = client()
    injection = "' autofocus onfocus='alert(1337)"
    response = test_client.get("/beer/", params={"sort": injection})
    assert response.status_code == 200
    assert injection not in response.text
    assert "sort=score" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"

    register_local_member(test_client, "Origin Guard", "origin-guard@example.test")
    rejected = test_client.post(
        "/community/new-thread/",
        data={"title": "Blocked cross origin", "body": "Must not persist.", "category": "Beer Talk"},
        headers={"Origin": "https://other-origin.example"},
        follow_redirects=False,
    )
    assert rejected.status_code == 403
    assert "Blocked cross origin" not in test_client.get("/community/").text
    fetch_metadata_rejected = test_client.post(
        "/community/new-thread/",
        data={"title": "Blocked metadata", "body": "Must not persist.", "category": "Beer Talk"},
        headers={"Sec-Fetch-Site": "cross-site"},
        follow_redirects=False,
    )
    assert fetch_metadata_rejected.status_code == 403

    previous = os.environ.pop("WEBSITEBENCH_ENABLE_TEST_LOGIN", None)
    try:
        disabled = test_client.post(
            "/community/login/local-test", follow_redirects=False
        )
        assert disabled.status_code == 404
    finally:
        if previous is not None:
            os.environ["WEBSITEBENCH_ENABLE_TEST_LOGIN"] = previous


def test_register_login_logout_and_member_identity() -> None:
    test_client = client()
    register_local_member(test_client, "Tasting Scholar", "tasting-scholar@example.test")
    assert "Tasting Scholar" in test_client.get("/").text

    logout_form = test_client.get("/community/logout/", follow_redirects=False)
    assert logout_form.status_code == 200
    assert "Tasting Scholar" in test_client.get("/").text
    logout = test_client.post("/community/logout/", follow_redirects=False)
    assert logout.status_code == 303
    assert "Tasting Scholar" not in test_client.get("/").text

    rejected = test_client.post(
        "/community/login/login",
        data={
            "login": "Tasting Scholar",
            "password": "not-the-local-password",
            "redirect": "/community/",
        },
    )
    assert rejected.status_code == 401
    assert "username/email or password is incorrect" in rejected.text

    login = test_client.post(
        "/community/login/login",
        data={
            "login": "Tasting Scholar",
            "password": "LocalPassphrase!2026",
            "redirect": "/community/",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/community/"
    assert "Tasting Scholar" in test_client.get("/community/").text


def test_duplicate_display_name_registration_is_rejected() -> None:
    test_client = client()
    review_data = {
        "look": 4,
        "smell": 4,
        "taste": 4,
        "feel": 4,
        "overall": 4,
    }

    register_local_member(test_client, "Shared Taster", "shared-taster-one@example.test")
    first = test_client.post(
        "/beer/rate/1160",
        data={**review_data, "comment": "First account review."},
        follow_redirects=False,
    )
    assert first.status_code == 303
    test_client.post("/community/logout/", follow_redirects=False)

    duplicate = test_client.post(
        "/community/register/start",
        data={
            "username": "Shared Taster",
            "email": "shared-taster-two@example.test",
            "password": "LocalPassphrase!2026",
            "confirm_password": "LocalPassphrase!2026",
            "terms": "accepted",
            "redirect": "/",
        },
    )
    assert duplicate.status_code == 409
    assert "Username is already in use" in duplicate.text

    with sqlite3.connect(candidate.database_path()) as connection:
        rows = connection.execute(
            "SELECT account_id, comment FROM reviews "
            "WHERE beer_id = ? AND member = ? ORDER BY comment",
            (1160, "Shared Taster"),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0]
    assert rows[0][1] == "First account review."


def test_forum_thread_reply_and_local_contributions() -> None:
    test_client = client()
    register_local_member(test_client, "Forum Member", "forum-member@example.test")
    new_thread = test_client.post(
        "/community/new-thread/",
        data={
            "title": "Cellared Imperial Stout Notes",
            "body": "Comparing roast, body, and age across several vintages.",
            "category": "Beer Talk",
        },
        follow_redirects=False,
    )
    assert new_thread.status_code == 303
    thread_path = new_thread.headers["location"]
    assert "Cellared Imperial Stout Notes" in test_client.get(thread_path).text
    reply = test_client.post(
        f"{thread_path}reply",
        data={"body": "The oldest bottle showed softer roast and more dark fruit."},
        follow_redirects=False,
    )
    assert reply.status_code == 303
    assert "softer roast" in test_client.get(thread_path).text

    contribution = test_client.post(
        "/place/add/",
        data={"title": "Local Bottle Room", "details": "Bottle Shop, Denver, CO"},
    )
    assert contribution.status_code == 200
    assert "Contribution saved" in contribution.text
    history = test_client.get("/community/account/")
    assert "Cellared Imperial Stout Notes" in history.text
    assert "The oldest bottle showed softer roast" in history.text
    assert "Local Bottle Room" in history.text


def test_beer_directory_places_and_review_journey() -> None:
    test_client = client()
    directory = test_client.get("/beer/?page=10&sort=name")
    assert directory.status_code == 200
    assert "240 beers found" in directory.text
    assert "page 10 of 10" in directory.text
    assert "40 beers found" in test_client.get("/search/?q=Imperial+Stout").text
    empty = test_client.get("/search/?q=definitely-no-such-local-beer")
    assert "0 beers found" in empty.text
    assert "No beers found" in empty.text
    assert test_client.get("/beer/styles/150/").status_code == 200
    assert test_client.get("/beer/styles/999/").status_code == 404

    places = test_client.get("/place/?kind=Brewery")
    assert places.status_code == 200
    assert "4 places found" in places.text
    assert test_client.get("/place/1/").status_code == 200
    assert test_client.get("/place/999/").status_code == 404

    login = test_client.post(
        "/community/login/local-test",
        data={"redirect": "/beer/rate/1160/"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    member_detail = test_client.get("/beer/profile/147/1160/")
    assert "href='#review-form'" in member_detail.text
    assert "id='review-form'" in member_detail.text
    assert member_detail.text.count("<option value='1.25'>1.25</option>") == 5
    assert member_detail.text.count("<option value='4.75'>4.75</option>") == 5
    assert test_client.get("/beer/rate/1160/").status_code == 200
    review = test_client.post(
        "/beer/rate/1160",
        data={
            "look": 4.75,
            "smell": 4.5,
            "taste": 4.25,
            "feel": 4,
            "overall": 4.75,
            "comment": "Rich malt, roasty aroma, full body.",
        },
        follow_redirects=False,
    )
    assert review.status_code == 303
    detail = test_client.get("/beer/profile/147/1160/")
    assert "Rich malt, roasty aroma, full body." in detail.text
    with sqlite3.connect(candidate.database_path()) as connection:
        first_review = connection.execute(
            "SELECT look, smell, taste, feel, overall FROM reviews "
            "WHERE beer_id = ? AND member = ?",
            (1160, "Local Test Member"),
        ).fetchone()
    assert first_review == (4.75, 4.5, 4.25, 4, 4.75)

    invalid_increment = test_client.post(
        "/beer/rate/1160",
        data={
            "look": 4.1,
            "smell": 4.5,
            "taste": 4.25,
            "feel": 4,
            "overall": 4.75,
            "comment": "This score increment is not available on the source form.",
        },
    )
    assert invalid_increment.status_code == 422
    assert "0.25 increments" in invalid_increment.text

    updated_review = test_client.post(
        "/beer/rate/1160",
        data={
            "look": 4,
            "smell": 5,
            "taste": 4,
            "feel": 4,
            "overall": 4,
            "comment": "Updated local tasting note.",
        },
        follow_redirects=False,
    )
    assert updated_review.status_code == 303

    with sqlite3.connect(candidate.database_path()) as connection:
        reviews = connection.execute(
            "SELECT look, smell, taste, feel, overall, comment FROM reviews "
            "WHERE beer_id = ? AND member = ?",
            (1160, "Local Test Member"),
        ).fetchall()
        assert reviews == [(4, 5, 4, 4, 4, "Updated local tasting note.")]
        binding = connection.execute(
            "SELECT site_id FROM websitebench_site_binding WHERE singleton = 1"
        ).fetchone()
        assert binding == ("beeradvocate",)


def test_review_management_media_helpful_and_ownership() -> None:
    owner = client()
    register_local_member(owner, "Review Owner", "review-owner@example.test")
    created = owner.post(
        "/beer/rate/1160",
        data={
            "look": "4.75",
            "smell": "4.5",
            "taste": "4.25",
            "feel": "4",
            "overall": "4.75",
            "comment": "Original managed review.",
            "media_asset": "beers/1160.jpg",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    with sqlite3.connect(candidate.database_path()) as connection:
        review_id = connection.execute(
            "SELECT id FROM reviews WHERE beer_id = 1160 AND member = ?",
            ("Review Owner",),
        ).fetchone()[0]

    edit_page = owner.get(f"/beer/review/{review_id}/edit/")
    assert edit_page.status_code == 200
    assert "Original managed review." in edit_page.text
    assert "beers/1160.jpg" in edit_page.text
    edited = owner.post(
        f"/beer/review/{review_id}/edit/",
        data={
            "look": "4.5",
            "smell": "4.25",
            "taste": "4.75",
            "feel": "4.5",
            "overall": "4.5",
            "comment": "Edited managed review.",
            "media_asset": "beers/806254.jpg",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    edited_detail = owner.get("/beer/profile/147/1160/")
    assert "Edited managed review." in edited_detail.text
    assert (
        "<img class='review-media' src='/static/assets/beers/806254.jpg'"
        in edited_detail.text
    )
    with sqlite3.connect(candidate.database_path()) as connection:
        assert connection.execute(
            "SELECT media_asset FROM reviews WHERE id=?", (review_id,)
        ).fetchone() == ("beers/806254.jpg",)

    other = client()
    register_local_member(other, "Helpful Reader", "helpful-reader@example.test")
    forbidden = other.post(
        f"/beer/review/{review_id}/edit/",
        data={
            "look": "1",
            "smell": "1",
            "taste": "1",
            "feel": "1",
            "overall": "1",
            "comment": "Must not overwrite.",
            "media_asset": "",
        },
    )
    assert forbidden.status_code == 403
    helpful = other.post(
        f"/beer/review/{review_id}/helpful/", follow_redirects=False
    )
    assert helpful.status_code == 303
    detail = other.get("/beer/profile/147/1160/")
    assert "Helpful (1)" in detail.text
    toggled_off = other.post(
        f"/beer/review/{review_id}/helpful/", follow_redirects=False
    )
    assert toggled_off.status_code == 303
    assert "Helpful (0)" in other.get("/beer/profile/147/1160/").text

    deleted = owner.post(
        f"/beer/review/{review_id}/delete/", follow_redirects=False
    )
    assert deleted.status_code == 303
    assert "Edited managed review." not in owner.get("/beer/profile/147/1160/").text


def test_save_follow_profile_share_compare_and_history() -> None:
    test_client = client()
    register_local_member(test_client, "Activity Member", "activity@example.test")
    review = test_client.post(
        "/beer/rate/1160",
        data={
            "look": "4",
            "smell": "4",
            "taste": "4",
            "feel": "4",
            "overall": "4",
            "comment": "Profile activity review.",
            "media_asset": "",
        },
        follow_redirects=False,
    )
    assert review.status_code == 303
    assert test_client.post("/beer/1160/save/", follow_redirects=False).status_code == 303
    assert test_client.post(
        "/community/members/alex-green/follow/", follow_redirects=False
    ).status_code == 303
    assert test_client.post(
        "/community/members/not-a-real-observed-member/follow/",
        follow_redirects=False,
    ).status_code == 404

    profile = test_client.get("/community/account/")
    assert profile.status_code == 200
    for marker in (
        "Activity Member",
        "Profile activity review.",
        "Stone Imperial Stout",
        "alex-green",
        "Saved beers",
        "Following",
    ):
        assert marker in profile.text
    public_profile = test_client.get("/community/members/alex-green/")
    assert "Following" in public_profile.text

    share = test_client.get("/beer/share/1160/")
    assert share.status_code == 200
    assert "/beer/profile/147/1160/" in share.text
    compare = test_client.get("/beer/compare/?beer=1160&beer=806254")
    assert compare.status_code == 200
    assert "id='compare-results'" in compare.text
    assert "href='/beer/profile/147/1160/'" in compare.text
    assert "href='/beer/profile/140/806254/'" in compare.text
    invalid_compare = test_client.get("/beer/compare/?beer=1160&beer=999999")
    assert invalid_compare.status_code == 404


def test_local_password_recovery_never_bypasses_account_control() -> None:
    test_client = client()
    register_local_member(test_client, "Recovery Member", "recovery@example.test")
    test_client.post("/community/logout/", follow_redirects=False)

    start = test_client.post(
        "/community/lost-password/start/",
        data={"email": "recovery@example.test"},
    )
    assert start.status_code == 200
    assert "Recovery request received" in start.text or "challenge is ready" in start.text
    assert "verification_code" not in start.text
    assert "Automatic completion is disabled" in start.text
    complete = test_client.post(
        "/community/lost-password/complete/",
        data={
            "new_password": "NewLocalPassphrase!2026",
            "confirm_password": "NewLocalPassphrase!2026",
        },
        follow_redirects=False,
    )
    assert complete.status_code == 403
    assert "verification_code" not in complete.text

    original_login = test_client.post(
        "/community/login/login",
        data={
            "login": "recovery@example.test",
            "password": "LocalPassphrase!2026",
            "redirect": "/",
        },
    )
    assert original_login.status_code == 200

    unknown = client()
    unknown_result = unknown.post(
        "/community/lost-password/start/",
        data={"email": "absent@example.test"},
    )
    assert unknown_result.status_code == 200
    assert "challenge is ready" in unknown_result.text
    unknown_complete = unknown.post(
        "/community/lost-password/complete/",
        data={
            "new_password": "AnotherLocalPassphrase!2026",
            "confirm_password": "AnotherLocalPassphrase!2026",
        },
    )
    assert unknown_complete.status_code == 403
    assert unknown_complete.json() == complete.json()


def test_help_and_recovery_entry_points_are_actionable() -> None:
    test_client = client()
    help_page = test_client.get("/help/")
    assert help_page.status_code == 200
    for marker in (
        "/community/lost-password/",
        "/community/login/",
        "/community/register/",
        "/community/contact/",
    ):
        assert marker in help_page.text
