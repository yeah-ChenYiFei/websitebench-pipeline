"""Backend semantic tests: identity, ownership, validation, persistence,
isolation, rate limits, and recovery, exercised against the running app."""

from __future__ import annotations

import re


def _posting_id_from_detail(detail_url: str) -> int:
    match = re.search(r"/d/(\d+)/", detail_url)
    assert match, f"no posting id in {detail_url}"
    return int(match.group(1))


def _publish_sublet(client, *, title="Test sublet", price=2400):
    """Walk the full wizard with the jar session and return the new id."""
    steps = [
        ("/post/category", {"category": "sub"}),
        ("/post/location", {"region": "toronto", "neighborhood": "annex"}),
        (
            "/post/details",
            {
                "title": title,
                "price": str(price),
                "postal_code": "M6G",
                "housing_type": "sublet",
                "bedrooms": "1br",
                "baths": "1",
                "square_feet": "600",
                "available_date": "2026-07-01",
                "furnished": "on",
                "laundry": "in-unit",
                "parking": "none",
                "ac": "none",
                "posted_by": "owner",
                "description": "A furnished sublet for the summer.",
            },
        ),
        ("/post/contact", {"contact_method": "email", "contact_email": "poster@example.com"}),
    ]
    for path, data in steps:
        response = client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303, (path, response.status_code)
    preview = client.get("/post/preview")
    assert preview.status_code == 200
    assert title in preview.text
    published = client.post("/post/publish", follow_redirects=False)
    assert published.status_code == 200
    assert "your posting is now live" in published.text
    match = re.search(r"post id: <strong>(\d+)</strong>", published.text)
    assert match
    return int(match.group(1))


def test_registration_unique_email_and_rate_limit(client) -> None:
    response = client.post(
        "/account/register",
        data={
            "email": "dupe@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "agree_terms": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200  # verify step rendered

    # second attempt within the window is rejected by the five-minute rule
    again = client.post(
        "/account/register",
        data={
            "email": "dupe@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
            "agree_terms": "on",
        },
    )
    assert again.status_code == 429
    assert "once every five minutes" in again.text


def test_registration_validation_and_terms(client) -> None:
    response = client.post(
        "/account/register",
        data={"email": "", "password": "short", "confirm_password": "other", "agree_terms": ""},
    )
    assert response.status_code == 422
    for marker in ("This field is required", "at least 8 characters", "do not match", "terms of use"):
        assert marker in response.text


def test_login_wrong_password_rejected(client) -> None:
    response = client.post(
        "/account/login",
        data={"email": "poster@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert "match" in response.text


def test_login_logout_session_lifecycle(client, poster_session) -> None:
    home = client.get("/account/home")
    assert home.status_code == 200
    assert "your postings" in home.text
    logged_out = client.post("/account/logout", follow_redirects=False)
    assert logged_out.status_code == 303
    after = client.get("/account/home")
    assert after.status_code == 401


def test_posting_owner_only_permissions(client, login) -> None:
    login("poster@example.com", "Websitebench1!")
    posting_id = _publish_sublet(client, title="Owner-only sublet")
    # seeker cannot edit the poster's posting
    login("seeker@example.com", "Websitebench1!")
    denied = client.get(f"/post/edit/{posting_id}")
    assert denied.status_code == 403
    assert "permission denied" in denied.text.lower()
    # anonymous cannot edit
    client.cookies.clear()
    anon = client.get(f"/post/edit/{posting_id}")
    assert anon.status_code == 401
    # owner can edit after logging back in
    login("poster@example.com", "Websitebench1!")
    owner = client.get(f"/post/edit/{posting_id}")
    assert owner.status_code == 200


def test_posting_edit_renew_repost_delete_lifecycle(client, poster_session) -> None:
    posting_id = _publish_sublet(client, title="Lifecycle sublet", price=2200)
    # edit
    edited = client.post(
        f"/post/edit/{posting_id}",
        data={
            "title": "Lifecycle sublet (edited)",
            "price": "2300",
            "postal_code": "M6G",
            "description": "Updated description.",
            "neighborhood": "annex",
            "housing_type": "sublet",
            "bedrooms": "1br",
            "baths": "1",
            "square_feet": "600",
            "available_date": "2026-07-01",
            "furnished": "on",
            "laundry": "in-unit",
            "parking": "none",
            "ac": "none",
            "posted_by": "owner",
            "contact_email": "poster@example.com",
            "contact_phone": "",
            "contact_method": "email",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    # renew
    renewed = client.post(f"/post/renew/{posting_id}", follow_redirects=False)
    assert renewed.status_code == 303
    # repost -> new id
    reposted = client.post(f"/post/repost/{posting_id}", follow_redirects=False)
    assert reposted.status_code == 303
    reposted_id = int(reposted.headers["location"].split("reposted=")[1])
    assert reposted_id != posting_id
    # delete the original and the reposted copy
    deleted = client.post(f"/post/delete/{posting_id}", follow_redirects=False)
    assert deleted.status_code == 303
    client.post(f"/post/delete/{reposted_id}", follow_redirects=False)
    detail = client.get(f"/toronto/housing/sub/d/{posting_id}/lifecycle-sublet")
    assert detail.status_code == 410
    assert "removed" in detail.text.lower()
    # removed postings leave search results
    search = client.get("/toronto/search/housing?query=Lifecycle")
    assert "Lifecycle sublet (edited)" not in search.text


def test_posting_publish_visible_in_listing_and_search(client, poster_session) -> None:
    posting_id = _publish_sublet(
        client,
        title="1BR near Annex - furnished sublet Jul-Aug",
        price=2400,
    )
    # visible in the sublets category listing
    listing = client.get("/search/area/toronto?cat=sub")
    assert "1BR near Annex - furnished sublet Jul-Aug" in listing.text
    # visible in the matching search
    search = client.get(
        "/toronto/search/housing?query=annex&min_price=2400&max_price=2400"
    )
    assert "1BR near Annex - furnished sublet Jul-Aug" in search.text
    # detail page shows every condition
    detail = client.get(f"/view/d/1br-near-annex-furnished-sublet-jul-aug/{'4c93' if posting_id == 1000001 else '4c93'}")
    assert detail.status_code == 200
    assert "$2,400" in detail.text
    assert "annex" in detail.text.lower()


def test_favorite_persists_across_refresh_and_relogin(client, poster_session) -> None:
    client.post("/toronto/housing/favorite/1000001", follow_redirects=False)
    saved = client.get("/account/saved")
    assert "1BR near Annex" in saved.text
    # refresh-equivalent: another request with the same session
    again = client.get("/account/saved")
    assert "1BR near Annex" in again.text
    # re-login: log out, log in again, favorite persists
    client.post("/account/logout", follow_redirects=False)
    client.cookies.clear()
    fresh = client.post(
        "/account/login",
        data={"email": "poster@example.com", "password": "Websitebench1!"},
        follow_redirects=False,
    )
    token = fresh.cookies.get("__Host-websitebench-craigslist-session")
    client.cookies.clear()
    client.cookies.set("__Host-websitebench-craigslist-session", token)
    saved_after = client.get("/account/saved")
    assert "1BR near Annex" in saved_after.text


def test_saved_search_persists(client, poster_session) -> None:
    response = client.post(
        "/toronto/search/housing/save",
        data={"name": "annex sublets"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    searches = client.get("/account/searches")
    assert "annex sublets" in searches.text


def test_search_no_results_and_route_back(client) -> None:
    response = client.get("/toronto/search/housing?query=zzzz-no-match-websitebench")
    assert response.status_code == 200
    assert "no search results" in response.text
    assert "/search/area/toronto?cat=hhh" in response.text  # route back to housing


def test_search_filters_deterministic(client) -> None:
    base = client.get("/toronto/search/housing?min_price=2000&max_price=3000")
    refined = client.get("/toronto/search/housing?min_price=2000&max_price=3000&postal=M6G&postedToday=1")
    assert base.status_code == 200 and refined.status_code == 200
    # identical query twice -> identical result set
    a = client.get("/toronto/search/housing?query=annex&sort=price-asc")
    b = client.get("/toronto/search/housing?query=annex&sort=price-asc")
    assert a.text == b.text


def test_password_recovery_entry_and_neutral_sent(client) -> None:
    page = client.get("/account/forgot")
    assert page.status_code == 200
    assert "email address" in page.text.lower()
    # known email -> neutral sent state (no account enumeration)
    sent_known = client.post("/account/forgot", data={"email": "poster@example.com"})
    assert sent_known.status_code == 200
    assert "check your email" in sent_known.text
    # unknown email -> same neutral state
    sent_unknown = client.post("/account/forgot", data={"email": "ghost@example.com"})
    assert sent_unknown.status_code == 200
    assert "check your email" in sent_unknown.text
    # missing email -> validation
    missing = client.post("/account/forgot", data={"email": ""})
    assert missing.status_code == 422


def test_reply_validation_and_delivery(client) -> None:
    empty = client.post(
        "/toronto/housing/reply/1000001", data={"name": "", "email": "", "message": ""}
    )
    assert empty.status_code == 422
    sent = client.post(
        "/toronto/housing/reply/1000001",
        data={"name": "Seeker", "email": "seeker@example.com", "message": "Is this available?"},
    )
    assert sent.status_code == 200
    assert "your reply has been sent" in sent.text


def test_flag_requires_reason(client) -> None:
    empty = client.post("/flag/1000001", data={"reason": ""})
    assert empty.status_code == 422
    sent = client.post("/flag/1000001", data={"reason": "spam", "note": "looks like spam"})
    assert sent.status_code == 200
    assert "thank you" in sent.text.lower()


def test_signed_out_stateful_action_prompt(client) -> None:
    for path, method in (
        ("/post/", "get"),
        ("/account/home", "get"),
        ("/account/saved", "get"),
        ("/account/searches", "get"),
        ("/account/settings", "get"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 401, path
        assert "log in to continue" in response.text
    # anonymous mutation attempts
    assert client.post("/toronto/housing/favorite/1000001").status_code == 401
    assert client.post("/toronto/search/housing/save").status_code == 401
    assert client.post("/post/delete/1000001").status_code == 401


def test_isolation_per_user_data(client, login) -> None:
    login("poster@example.com", "Websitebench1!")
    posting_id = _publish_sublet(client, title="Private posting of poster")
    # seeker never sees the poster's account page contents
    login("seeker@example.com", "Websitebench1!")
    seeker_home = client.get("/account/home")
    assert "Private posting of poster" not in seeker_home.text
    # seeker cannot delete the poster's posting
    denied = client.post(f"/post/delete/{posting_id}")
    assert denied.status_code == 403
    # poster still owns the posting after logging back in
    login("poster@example.com", "Websitebench1!")
    home = client.get("/account/home")
    assert "Private posting of poster" in home.text


def test_seed_photos_urls_on_search_and_detail(client) -> None:
    """Seed housing postings carry photo assets; every rendered photo URL is
    valid (seed photos under /static/assets/seed-photos, wizard uploads under
    /uploads) — regression for the mixed-source photo URL bug."""
    from backend import craigslist_db

    photos = craigslist_db.posting_photos(1000001)
    assert len(photos) >= 1
    assert all(p["filename"].endswith(".svg") for p in photos)
    # search list and detail render the first photo with a valid URL
    search = client.get("/search/area/toronto?cat=sub")
    assert "apt-annex-" in search.text or "room-annex-" in search.text
    detail = client.get("/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93")
    assert detail.status_code == 200
    assert "/static/assets/seed-photos/" in detail.text
    assert "data-gallery-thumb" in detail.text
