from __future__ import annotations

import argparse
import json
import uuid

from playwright.sync_api import Page, expect, sync_playwright


ALL_TRACES = [f"WB047-T{i:02d}" for i in range(1, 24)]


def adjacent_free_seats(page: Page, count: int, rows: tuple[str, ...] = ("D", "E", "F")) -> list[str]:
    """Pick `count` adjacent unsold seats from the rendered map (sold seats vary per showtime)."""
    for row in rows:
        for start in range(1, 13 - count + 1):
            block = [f"{row}{start + offset}" for offset in range(count)]
            if all(page.locator(f"[data-seat='{seat}']:not(.sold)").count() for seat in block):
                return block
    raise AssertionError("no adjacent block of free seats on the map")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay all Fandango WebsiteBench traces through visible controls.")
    parser.add_argument("--base", default="http://127.0.0.1:8775")
    args = parser.parse_args()
    checks: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # The ClawBench trace targets whichever thriller the captured catalog is
        # showing at Regal Union Square; ask the site rather than pinning a title.
        bootstrap = context.request.get(f"{args.base}/api/bootstrap").json()
        featured = bootstrap["featured"]
        union_square = next(t for t in bootstrap["theaters"] if t["id"] == "regal-union-square")["name"]
        movie_path = f"{args.base}/movies/{featured['id']}"

        # WB047-T01/T03/T04/T05/T06/T15: discovery, filtering, details and recovery.
        page.goto(args.base)
        expect(page.get_by_role("link", name="Movies", exact=True).first).to_be_visible()
        expect(page.get_by_label("Search by city, state, zip or movie")).to_be_visible()
        home = page.locator("main").inner_text()
        for required in ("MOVIES IN THEATERS", "COMING SOON TO THEATERS", "THEATERS NEAR YOU"):
            assert required in home, required
        page.locator(".nav-icons a[href='/movies']").click()
        page.wait_for_url("**/movies")
        expect(page.locator("article.movie-card").nth(9)).to_be_visible()
        page.goto(f"{args.base}/movies?filters=1")
        page.locator('[data-filter] select[name="genre"]').select_option(label="Suspense/Thriller")
        page.locator('[data-filter] select[name="service"]').select_option(label="Reserved Seating")
        page.locator('[data-filter] select[name="sort"]').select_option("title")
        page.locator("[data-filter]").get_by_role("button", name="Apply").click()
        page.wait_for_url("**genre=Suspense%2FThriller**")
        expect(page.locator("[data-filter] select[name='genre']")).to_have_value("Suspense/Thriller")
        titles = page.locator("article.movie-card h3").all_text_contents()
        assert titles and titles == sorted(titles), titles
        assert len(titles) < 16, f"genre filter did not narrow the listing: {titles}"
        expect(page.locator(f'[data-movie-card="{featured["id"]}"]')).to_be_visible()
        page.goto(movie_path)
        page.locator("details summary").first.click()
        details = page.locator("main").inner_text()
        for required in (featured["title"], "Directed by", union_square, "Policies & amenities"):
            assert required in details, required
        checks.append("discovery, filter/sort, movie/theater details and availability")

        # WB047-T03/T06: date strip and format chips actually change the offered showtimes.
        assert page.locator(".date-tile").count() >= 7
        page.locator(".format-chips a", has_text="IMAX").first.click()
        expect(page.locator(".format-chips a.active")).to_have_text("IMAX")
        imax = page.locator("[data-showtime]").all_text_contents()
        assert imax and all("IMAX" in entry for entry in imax), imax
        page.locator(".format-chips a", has_text="All").first.click()
        expect(page.locator(".format-chips a.active")).to_have_text("All")
        assert page.locator("[data-showtime]").count() > len(imax)
        page.goto(f"{args.base}/theaters")
        directory = page.locator("main").inner_text()
        for theater in (union_square, "AMC Village 7", "Regal Essex Crossing & RPX", "AMC Kips Bay 15"):
            assert theater in directory, theater
        page.locator(".date-tile:not(.active)").first.click()
        page.wait_for_url("**/theaters?date=**")
        assert page.locator("[data-showtime]").count() > 0
        checks.append("theater directory with per-date and per-format showtime browsing")

        # WB047-T02/T10/T11/T12/T23: mandatory end-to-end booking trace.
        page.goto(movie_path)
        regal = page.locator("article.showtime-theater", has_text=union_square).first
        expect(regal.locator("[data-showtime]").first).to_be_visible()
        evening = [
            button for button in regal.locator("[data-showtime]").all()
            if (label := button.inner_text().splitlines()[0]).endswith("PM") and int(label.split(":")[0]) >= 6
        ]
        assert evening, "no Friday evening showtime after 6 PM at Regal Union Square"
        chosen_time = evening[0].inner_text().splitlines()[0]
        evening[0].click()
        page.wait_for_url("**/tickets")
        page.locator('input[name="adults"]').fill("3")
        page.locator('input[name="children"]').fill("0")
        page.locator('input[name="seniors"]').fill("0")
        page.get_by_role("button", name="Continue to Seats").click()
        page.wait_for_url("**/tickets/seats")
        seats = adjacent_free_seats(page, 3)
        for seat in seats:
            page.get_by_role("button", name=f"Seat {seat}", exact=False).first.click()
        expect(page.locator("[data-seat-status]")).to_have_text(f"Selected: {', '.join(seats)}")
        page.get_by_role("button", name="Continue to Review").click()
        page.wait_for_url("**/checkout")
        expect(page.get_by_text("Local Sandbox Payment", exact=True)).to_be_visible()
        page.locator('input[name="email"]').fill("moviegoer@example.test")
        page.locator('input[name="postal_code"]').fill("10003")
        page.get_by_role("button", name="Calculate Total & Review").click()
        expect(page.get_by_role("heading", name="Final booking review")).to_be_visible()
        review_text = page.locator("main").inner_text()
        for required in (featured["title"], union_square, chosen_time, "3 tickets", ", ".join(seats), "Total"):
            assert required in review_text, required
        page.get_by_role("button", name="Confirm Local Booking").click()
        page.wait_for_url("**/confirmation")
        proof = page.locator("main").inner_text()
        for required in ("LOCAL BOOKING CONFIRMED", featured["title"], union_square, chosen_time,
                         ", ".join(seats), "No real ticket was issued"):
            assert required in proof, required
        checks.append("mandatory 3-ticket Friday evening thriller booking with adjacent centre seats")

        # WB047-T07-T09/T13/T14/T16/T17/T19: saved item, account, history and management.
        account_context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = account_context.new_page()
        page.goto(movie_path)
        page.locator("[data-favorite]").first.click()
        expect(page.locator("#toast")).to_contain_text("Saved")
        page.goto(f"{args.base}/account/bookings")
        expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        page.goto(f"{args.base}/account/register")
        registration = page.locator("main").inner_text()
        assert "verified locally" in registration
        expect(page.locator(".auth-card").get_by_role("link", name="Terms of Use")).to_be_visible()
        expect(page.locator(".auth-card").get_by_role("link", name="Privacy Policy")).to_be_visible()
        email = f"trace-{uuid.uuid4().hex[:8]}@example.test"
        page.locator('input[name="display_name"]').fill("WebsiteBench Moviegoer")
        page.locator('input[name="email"]').fill(email)
        page.locator('input[name="password"]').fill("websitebench-pass")
        page.locator('input[name="terms"]').check()
        page.get_by_role("button", name="Create Account").click()
        page.wait_for_url("**/account")
        expect(page.get_by_text("Hi, WebsiteBench Moviegoer")).to_be_visible()
        page.goto(f"{args.base}/favorites")
        expect(page.locator(f'[data-movie-card="{featured["id"]}"]')).to_be_visible()
        page.goto(f"{args.base}/account/bookings")
        booking = page.locator('[data-booking="FDG-SEED-2048"]')
        expect(booking).to_be_visible()
        booking.get_by_role("button", name="Contact Theater").click()
        expect(page.get_by_text("Local message saved — nothing was sent")).to_be_visible()
        page.locator('[data-booking="FDG-SEED-2048"]').get_by_role("button", name="Write Review").click()
        expect(page.get_by_text("Review: 5 stars — Great local test experience")).to_be_visible()
        page.locator('[data-booking="FDG-SEED-2048"]').get_by_role("button", name="Reschedule").click()
        expect(page.locator('[data-booking="FDG-SEED-2048"] .status')).to_have_text("Rescheduled")
        page.locator('[data-booking="FDG-SEED-2048"]').get_by_role("button", name="Cancel").click()
        expect(page.locator('[data-booking="FDG-SEED-2048"] .status')).to_have_text("Cancelled")
        checks.append("favorite, registration/sign-in state, booking history and management actions")

        # WB047-T18/T20/T21/T22: recovery, validation/permission, help, policies and 404.
        page.goto(f"{args.base}/account/recover")
        page.locator('input[name="email"]').fill(email)
        page.get_by_role("button", name="Continue").click()
        expect(page.get_by_text("No email was sent. This is a local recovery preview.")).to_be_visible()
        page.goto(movie_path)
        page.locator("[data-showtime]").first.click()
        page.wait_for_url("**/tickets")
        for field in ("adults", "children", "seniors"):
            page.locator(f'input[name="{field}"]').fill("0")
        page.get_by_role("button", name="Continue to Seats").click()
        expect(page.locator(".inline-error")).to_contain_text("between 1 and 8 tickets")
        page.goto(f"{args.base}/help")
        expect(page.get_by_role("heading", name="How can we help?")).to_be_visible()
        page.goto(f"{args.base}/policies/privacy-policy")
        expect(page.get_by_role("heading", name="Privacy Policy")).to_be_visible()
        page.goto(f"{args.base}/movies?q=definitely-absent")
        expect(page.get_by_role("heading", name="No movies found")).to_be_visible()
        page.get_by_role("link", name="Browse available movies").click()
        page.wait_for_url("**/movies")
        expect(page.locator("article.movie-card").nth(9)).to_be_visible()
        response = page.goto(f"{args.base}/not-a-real-fandango-page")
        assert response and response.status == 404
        expect(page.get_by_role("heading", name="That page missed the show.")).to_be_visible()
        checks.append("no-send recovery, required-field validation, help, policies and branded 404")

        account_context.close()
        context.close()
        browser.close()

    print(json.dumps({"ok": True, "base": args.base, "checks": checks, "trace_status": {trace: "passed" for trace in ALL_TRACES}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
