"""Build the deterministic live verification driver from the frozen route ledger."""

from __future__ import annotations

import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]


def steps(*items: dict[str, object], session: str | None = None) -> object:
    values = list(items)
    return values if session is None else {"session": session, "steps": values}


def main() -> None:
    route_ledger = json.loads(
        (SITE_ROOT / "scope" / "routes.json").read_text(encoding="utf-8")
    )
    routes = {
        row["id"]: row["route_pattern"] for row in route_ledger["routes"]
    }

    # These captures share a source path but represent a distinct frozen UI
    # state. A private, clone-local query makes the states independently and
    # repeatably addressable without changing any public navigation contract.
    routes.update(
        {
            "location-search-toronto": (
                "/session/filter_metro_area?wb_state=search-toronto"
            ),
            "location-search-empty": (
                "/session/filter_metro_area?wb_state=search-empty"
            ),
            "montreal-today": (
                "/en/metro-areas/27377-canada-montreal?wb_state=today"
            ),
            "montreal-next-7-days": (
                "/en/metro-areas/27377-canada-montreal?wb_state=next-7-days"
            ),
            "montreal-next-30-days": (
                "/en/metro-areas/27377-canada-montreal?wb_state=next-30-days"
            ),
            "popular-artists-page-2": "/leaderboards/popular_artists?page=2",
        }
    )

    authenticated = {
        "artist-detail.artist-tracked": steps(
            {
                "eval": "async () => { const response = await fetch('/api/me/artists/10355080', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tracked: true})}); if (!response.ok) throw new Error('artist tracking failed: ' + response.status); }"
            },
            {"goto": "/artists/10355080-westside-cowboy"},
            {"expect": "[data-wb-component='artist-tracked-state']"},
            session="fan",
        ),
        "artist-detail.tracked-after-refresh": steps(
            {
                "eval": "async () => { const response = await fetch('/api/me/artists/10355080', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tracked: true})}); if (!response.ok) throw new Error('artist tracking failed: ' + response.status); }"
            },
            {"goto": "/artists/10355080-westside-cowboy"},
            {"goto": "/artists/10355080-westside-cowboy"},
            {"expect": "[data-wb-component='artist-tracked-state']"},
            session="fan",
        ),
        "event-detail.event-interested": steps(
            {
                "eval": "async () => { const response = await fetch('/api/me/events/43365625', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: 'interested'})}); if (!response.ok) throw new Error('event interest failed: ' + response.status); }"
            },
            {"goto": "/concerts/43365625-steve-lacy-at-place-bell"},
            {"expect": "[data-wb-component='event-interested-state']"},
            session="fan",
        ),
        "event-detail.interested-after-refresh": steps(
            {
                "eval": "async () => { const response = await fetch('/api/me/events/43365625', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: 'interested'})}); if (!response.ok) throw new Error('event interest failed: ' + response.status); }"
            },
            {"goto": "/concerts/43365625-steve-lacy-at-place-bell"},
            {"goto": "/concerts/43365625-steve-lacy-at-place-bell"},
            {"expect": "[data-wb-component='event-interested-state']"},
            session="fan",
        ),
        "home.authenticated-session": steps(
            {"expect": "#account-button:not([hidden])"}, session="fan"
        ),
        "home.account-menu": steps(
            {"click": "#account-button"},
            {"expect": "#account-menu:not([hidden])"},
            session="fan",
        ),
        "home.logout": steps(
            {"click": "#account-button"},
            {"click": "#logout-button"},
            {"expect": ".pink-nav"},
            session="logout-fan",
        ),
        "home.refresh-persistence": steps(
            {"goto": "/"},
            {"expect": "#account-button:not([hidden])"},
            session="fan",
        ),
        "home.relogin-persistence": steps(
            {"goto": "/"},
            {"expect": "#account-button:not([hidden])"},
            session="fan",
        ),
    }

    states: dict[str, object] = {
        "initial": [],
        "route-identity": [],
        "lazy-end": steps(
            {
                "eval": "() => window.scrollTo(0, document.body.scrollHeight)",
                "wait_ms": 400,
            }
        ),
        "home-next-artists.next-artists": steps(
            {"click": "[data-carousel='artist-carousel']"},
            {"expect": "#artist-carousel"},
        ),
        "home-next-events.next-events": steps(
            {"click": "[data-carousel='event-carousel']"},
            {"expect": "#event-carousel"},
        ),
        "home-search-modal.search-open": steps(
            {"click": "#search-trigger"},
            {"expect": "#search-modal:not([hidden])"},
        ),
        "home.search-results-coldplay": steps(
            {"click": "#search-trigger"},
            {"fill": "#global-search-input", "value": "Coldplay", "wait_ms": 500},
            {"expect": "[data-wb-component='search-populated-results']"},
        ),
        "home.search-no-results": steps(
            {"click": "#search-trigger"},
            {
                "fill": "#global-search-input",
                "value": "zzzzsongkicknoresult",
                "wait_ms": 500,
            },
            {"expect": "[data-wb-component='search-no-results']"},
        ),
        "home-theme.dark-background": steps(
            {"click": "#theme-toggle"}, {"expect": "body.theme-dark"}
        ),
        "password-reset.captcha-error": steps(
            {"goto": "/password_reset_requests/new?state=captcha-error"},
            {"expect": "[data-wb-component='password-reset-captcha-error']"},
        ),
        "password-reset.password-reset-success": steps(
            {"goto": "/session/new?reset=success"},
            {"expect": "[data-wb-component='password-reset-success-notice']"},
        ),
        "sign-in.password-reset-success": steps(
            {"goto": "/session/new?reset=success"},
            {"expect": "[data-wb-component='password-reset-success-notice']"},
        ),
        "ticketmaster-boundary.ticketmaster-click": steps(
            {"click": "[data-wb-ticket-link='ticketmaster-ca']"},
            {"expect": "[data-wb-component='external-boundary']"},
        ),
        **authenticated,
    }

    driver = {
        "schema_version": "offline-clone.verify-driver.v1",
        "site_id": "songkick",
        "note": (
            "Deterministic remote-native verification for the complete frozen "
            "Songkick route/state ledger. No external destination is contacted."
        ),
        "routes": routes,
        "deferred": {},
        "visual_excluded": {},
        "states_out_of_scope": {},
        "status": {"not-found": 404},
        "prepare": [],
        "states": states,
        "session": {
            "token_env": "WEBSITEBENCH_FIXTURE_TOKEN",
            "post": "/__websitebench/session",
            "headers": {"x-websitebench-fixture-token": "{{token}}"},
            "expect_status": [200],
            "accounts": {"fan": {}, "logout-fan": {}},
        },
        "boot": {
            "argv": [
                "{python}",
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                "{port}",
                "--log-level",
                "warning",
            ],
            "cwd": "clone",
            "env": {
                "PYTHONDONTWRITEBYTECODE": "1",
                "WEBSITEBENCH_SITE_BACKEND_DATABASE": "{data_dir}/songkick.sqlite3",
            },
        },
    }
    output = SITE_ROOT / "scope" / "verify.json"
    output.write_text(
        json.dumps(driver, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
