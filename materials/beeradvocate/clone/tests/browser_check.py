from __future__ import annotations

import json
import sys
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def origin(url: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if not parsed.scheme or not parsed.hostname:
        return None
    scheme = parsed.scheme.lower()
    if port is None:
        port = {"http": 80, "https": 443}.get(scheme)
    return scheme, parsed.hostname.lower().rstrip("."), port


def is_same_origin(url: str, base_url: str) -> bool:
    request_origin = origin(url)
    return request_origin is not None and request_origin == origin(base_url)


def validate_loopback_base_url(base_url: str) -> str:
    """Reject targets that could turn this local-only E2E into a source write."""
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("base_url must be a valid loopback URL") from error
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() != "http"
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an http loopback origin with an explicit port")
    if hostname != "localhost":
        try:
            if not ip_address(hostname).is_loopback:
                raise ValueError("base_url host must be loopback")
        except ValueError as error:
            raise ValueError("base_url host must be loopback") from error
    return base_url.rstrip("/")


def main() -> int:
    base_url = validate_loopback_base_url(
        sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4173"
    )
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("browser-output")
    output_dir.mkdir(parents=True, exist_ok=True)
    external_requests: list[str] = []
    checkpoints: list[dict[str, object]] = []
    identity = uuid4().hex[:10]

    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        if EDGE.is_file():
            launch_options["executable_path"] = str(EDGE)
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on(
            "request",
            lambda request: external_requests.append(request.url)
            if not is_same_origin(request.url, base_url)
            else None,
        )

        page.goto(f"{base_url}/", wait_until="networkidle")
        local_link_count = page.locator("a[href^='/']").count()
        local_hrefs = page.locator("a[href^='/']").evaluate_all(
            "links => [...new Set(links.map(link => link.getAttribute('href')))]"
        )
        page.screenshot(path=output_dir / "home-desktop.png", full_page=True)
        link_click_failures: list[dict[str, object]] = []
        for href in local_hrefs:
            page.goto(f"{base_url}/", wait_until="networkidle")
            link = page.locator(f"a[href={json.dumps(href)}]:visible").first
            if link.count() != 1:
                link_click_failures.append(
                    {"href": href, "reason": "visible link missing on home reload"}
                )
                continue
            try:
                link.click(timeout=5_000)
                page.wait_for_load_state("networkidle")
            except PlaywrightError as error:
                link_click_failures.append(
                    {"href": href, "reason": str(error).splitlines()[0]}
                )
                continue
            status = page.request.get(page.url).status
            if status >= 400 or not is_same_origin(page.url, base_url):
                link_click_failures.append(
                    {
                        "href": href,
                        "status": status,
                        "destination": page.url,
                    }
                )
        page.goto(f"{base_url}/", wait_until="networkidle")
        checkpoints.append(
            {
                "name": "home-desktop",
                "title": page.title(),
                "horizontal_overflow": page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                ),
                "local_links": local_link_count,
                "unique_local_hrefs": len(local_hrefs),
                "link_clicks_attempted": len(local_hrefs),
                "link_clicks_completed": len(local_hrefs) - len(link_click_failures),
                "link_click_failures": link_click_failures,
            }
        )

        visual_routes = {
            "beer-recent": ("/beer/", "Beer Ratings: Recent"),
            "search-imperial-stout": (
                "/search/?q=Imperial+Stout",
                "Search: Imperial Stout",
            ),
            "styles": ("/beer/styles/", "Beer Styles"),
            "top-rated": ("/beer/top-rated/", "Top 250 Rated Beers"),
            "forums": ("/community/", "Beer Forums"),
            "the-bar": ("/community/forums/the-bar.68/", "The Bar"),
            "places": ("/place/", "Places"),
            "login": ("/community/login/", "Log in"),
            "register": ("/community/register/", "Join BeerAdvocate"),
            "stone-brewery": ("/beer/profile/147/", "Stone Brewing"),
        }
        for route_name, (path, marker) in visual_routes.items():
            response = page.goto(f"{base_url}{path}", wait_until="networkidle")
            checkpoints.append(
                {
                    "name": f"visual-{route_name}",
                    "status": response.status if response else None,
                    "marker": marker,
                    "marker_visible": (
                        page.get_by_text(marker, exact=False).first.is_visible()
                        if page.get_by_text(marker, exact=False).count() > 0
                        else False
                    ),
                    "horizontal_overflow": page.evaluate(
                        "document.documentElement.scrollWidth > "
                        "document.documentElement.clientWidth"
                    ),
                }
            )
            page.screenshot(
                path=output_dir / f"{route_name}-desktop.png", full_page=True
            )

        mobile = browser.new_context(viewport={"width": 390, "height": 844})
        mobile_page = mobile.new_page()
        mobile_page.on(
            "request",
            lambda request: external_requests.append(request.url)
            if not is_same_origin(request.url, base_url)
            else None,
        )
        mobile_page.goto(f"{base_url}/", wait_until="networkidle")
        checkpoints.append(
            {
                "name": "home-mobile",
                "horizontal_overflow": mobile_page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                ),
                "menu_visible": (
                    mobile_page.get_by_text("MENU").first.is_visible()
                    if mobile_page.get_by_text("MENU").count() > 0
                    else False
                ),
            }
        )
        mobile_page.screenshot(path=output_dir / "home-mobile-390x844.png", full_page=True)
        mobile.close()

        member_email = f"browser-{identity}@example.test"
        page.goto(f"{base_url}/community/register/?redirect=/community/", wait_until="networkidle")
        page.get_by_label("Username").fill(f"Browser Member {identity}")
        page.get_by_label("Email").fill(member_email)
        page.get_by_label("Password", exact=True).fill("LocalBrowserPass!2026")
        page.get_by_label("Confirm password").fill("LocalBrowserPass!2026")
        page.get_by_label("I agree to the community rules.").check()
        page.get_by_role("button", name="Create account").click()
        page.get_by_text("No message was sent").wait_for()
        page.get_by_role("button", name="Verify and activate account").click()
        page.get_by_text(f"Browser Member {identity}").first.wait_for()

        page.goto(f"{base_url}/community/new-thread/", wait_until="networkidle")
        page.get_by_label("Forum").select_option(label="Beer Talk")
        page.get_by_label("Title").fill("Browser Journey Imperial Stout Thread")
        page.get_by_label("Message").fill("Tracking roast, malt, and body through a local-only discussion.")
        page.get_by_role("button", name="Post Thread").click()
        page.get_by_role("heading", name="Browser Journey Imperial Stout Thread").wait_for()
        page.get_by_label("Reply").fill("A second interaction proves the thread remains writable after navigation.")
        page.get_by_role("button", name="Post Reply").click()
        page.get_by_text("A second interaction proves").wait_for()

        page.goto(f"{base_url}/beer/profile/147/1160/", wait_until="networkidle")
        page.get_by_role("link", name="Rate It").click()
        inline_review_form = page.locator("#review-form")
        inline_review_form.wait_for()
        inline_review_form_visible = inline_review_form.is_visible()
        score_option_values = {
            label.lower(): page.get_by_label(label).locator("option").evaluate_all(
                "options => options.map(option => option.value)"
            )
            for label in ("Look", "Smell", "Taste", "Feel", "Overall")
        }
        score_option_count = len(score_option_values["look"])
        for label, value in (
            ("Look", "4.75"),
            ("Smell", "4.5"),
            ("Taste", "4.25"),
            ("Feel", "4"),
            ("Overall", "4.75"),
        ):
            page.get_by_label(label).select_option(value)
        page.get_by_label("Review").fill("Rich malt, roasty aroma, full body.")
        page.get_by_role("button", name="Submit Review").click()
        member_name = f"Browser Member {identity}"
        expected_comment = "Rich malt, roasty aroma, full body."
        matching_comments = page.get_by_text(
            expected_comment, exact=True
        )
        current_member_review = (
            page.locator("article.panel")
            .filter(has_text=expected_comment)
            .filter(has_text=f"{member_name} · local clone review")
        )
        current_member_review.wait_for()
        initial_comment_visible = matching_comments.count() > 0
        initial_matching_comment_count = matching_comments.count()
        initial_member_visible = page.get_by_text(member_name).count() > 0
        initial_current_member_review_visible = current_member_review.count() == 1
        current_member_review.get_by_role("link", name="Edit review").click()
        page.get_by_label("Photo").select_option("beers/1160.jpg")
        edited_comment = f"Edited browser-managed review {identity}."
        page.get_by_label("Review").fill(edited_comment)
        page.get_by_role("button", name="Submit Review").click()
        page.get_by_text(edited_comment, exact=True).wait_for()
        edited_review = page.locator("article.local-review").filter(
            has_text=edited_comment
        )
        media_visible = edited_review.locator(
            "img.review-media[src='/static/assets/beers/1160.jpg']"
        ).is_visible()
        page.get_by_role("button", name="Save beer").click()
        page.get_by_role("button", name="Unsave").wait_for()
        page.goto(f"{base_url}/community/members/alex-green/", wait_until="networkidle")
        page.get_by_role("button", name="Follow", exact=True).click()
        page.get_by_text("Following", exact=True).wait_for()
        page.goto(f"{base_url}/community/account/", wait_until="networkidle")
        activity_markers = {
            "review": page.get_by_text(edited_comment, exact=True).count() == 1,
            "saved": page.get_by_text("Stone Imperial Stout", exact=True).count() > 0,
            "following": page.get_by_text("alex-green", exact=True).count() > 0,
        }
        page.goto(
            f"{base_url}/beer/compare/?beer=1160&beer=806254",
            wait_until="networkidle",
        )
        compare_results = page.locator("#compare-results tbody")
        compare_visible = (
            compare_results.get_by_role("link", name="Stone Imperial Stout").count() == 1
            and compare_results.get_by_role("link", name="Oktoberfest (2026)").count() == 1
        )
        page.goto(f"{base_url}/beer/share/1160/", wait_until="networkidle")
        share_local = page.get_by_label("Permalink").input_value() == "/beer/profile/147/1160/"

        reader = browser.new_context(viewport={"width": 1200, "height": 900})
        reader_page = reader.new_page()
        reader_page.on(
            "request",
            lambda request: external_requests.append(request.url)
            if not is_same_origin(request.url, base_url)
            else None,
        )
        reader_page.goto(f"{base_url}/community/register/", wait_until="networkidle")
        reader_page.get_by_label("Username").fill(f"Helpful Reader {identity}")
        reader_page.get_by_label("Email").fill(f"reader-{identity}@example.test")
        reader_page.get_by_label("Password", exact=True).fill("LocalReaderPass!2026")
        reader_page.get_by_label("Confirm password").fill("LocalReaderPass!2026")
        reader_page.get_by_label("I agree to the community rules.").check()
        reader_page.get_by_role("button", name="Create account").click()
        reader_page.get_by_role("button", name="Verify and activate account").click()
        reader_page.goto(f"{base_url}/beer/profile/147/1160/", wait_until="networkidle")
        reader_review = reader_page.locator("article.local-review").filter(
            has_text=edited_comment
        )
        reader_review.get_by_role("button", name="Helpful (0)").click()
        reader_review.get_by_role("button", name="Helpful (1)").wait_for()
        helpful_visible = True
        reader.close()

        page.goto(f"{base_url}/community/logout/", wait_until="networkidle")
        page.get_by_role("button", name="Log out").click()
        page.goto(f"{base_url}/community/lost-password/", wait_until="networkidle")
        page.get_by_label("Email").fill(member_email)
        page.get_by_role("button", name="Start recovery").click()
        page.get_by_text("Automatic completion is disabled", exact=False).wait_for()
        page.get_by_role("link", name="Return to login").click()
        page.get_by_label("Username or email").fill(member_email)
        page.get_by_label("Password", exact=True).fill("LocalBrowserPass!2026")
        page.get_by_role("button", name="Log in").click()
        page.goto(f"{base_url}/community/account/", wait_until="networkidle")
        recovery_history_visible = page.get_by_text(
            edited_comment, exact=True
        ).count() == 1
        checkpoints.append(
            {
                "name": "member-review-success",
                "url": page.url,
                "comment_visible": initial_comment_visible,
                "matching_comment_count": initial_matching_comment_count,
                "member_visible": initial_member_visible,
                "current_member_review_visible": initial_current_member_review_visible,
                "inline_review_form_visible": inline_review_form_visible,
                "score_option_count": score_option_count,
                "score_option_values": score_option_values,
                "activity_markers": activity_markers,
                "media_visible": media_visible,
                "compare_visible": compare_visible,
                "share_local": share_local,
                "helpful_visible": helpful_visible,
                "recovery_history_visible": recovery_history_visible,
            }
        )
        page.screenshot(path=output_dir / "review-success-desktop.png", full_page=True)
        context.close()
        browser.close()

    checkpoints_by_name = {item["name"]: item for item in checkpoints}
    required_checkpoints_passed = (
        checkpoints_by_name["home-desktop"]["title"] == "BeerAdvocate"
        and checkpoints_by_name["home-desktop"]["local_links"] > 0
        and checkpoints_by_name["home-desktop"]["link_click_failures"] == []
        and all(
            item.get("marker_visible") is True and item.get("status") == 200
            for item in checkpoints
            if str(item["name"]).startswith("visual-")
        )
        and checkpoints_by_name["home-mobile"]["menu_visible"] is True
        and checkpoints_by_name["member-review-success"]["comment_visible"] is True
        and checkpoints_by_name["member-review-success"]["member_visible"] is True
        and checkpoints_by_name["member-review-success"][
            "current_member_review_visible"
        ]
        is True
        and checkpoints_by_name["member-review-success"][
            "inline_review_form_visible"
        ]
        is True
        and checkpoints_by_name["member-review-success"]["score_option_count"] == 18
        and all(
            values
            == [
                "",
                "1",
                "1.25",
                "1.5",
                "1.75",
                "2",
                "2.25",
                "2.5",
                "2.75",
                "3",
                "3.25",
                "3.5",
                "3.75",
                "4",
                "4.25",
                "4.5",
                "4.75",
                "5",
            ]
            for values in checkpoints_by_name["member-review-success"][
                "score_option_values"
            ].values()
        )
        and all(
            checkpoints_by_name["member-review-success"]["activity_markers"].values()
        )
        and checkpoints_by_name["member-review-success"]["compare_visible"] is True
        and checkpoints_by_name["member-review-success"]["media_visible"] is True
        and checkpoints_by_name["member-review-success"]["share_local"] is True
        and checkpoints_by_name["member-review-success"]["helpful_visible"] is True
        and checkpoints_by_name["member-review-success"]["recovery_history_visible"] is True
    )
    result = {
        "schema_version": "beeradvocate.browser-check.v1",
        "base_url": base_url,
        "checkpoints": checkpoints,
        "external_requests": sorted(set(external_requests)),
        "passed": not external_requests
        and all(not item.get("horizontal_overflow", False) for item in checkpoints),
        "required_checkpoints_passed": required_checkpoints_passed,
    }
    result["passed"] = result["passed"] and required_checkpoints_passed
    (output_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
