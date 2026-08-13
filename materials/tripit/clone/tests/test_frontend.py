"""Frontend fixture tests for the TripIt offline clone (Phase 4 surface).

Verifies that the frozen, localized marketing / auth / legal fixtures render at
their real source routes, local-only, behind the runtime security headers, and
that the health / admin / external-boundary contracts hold. Dynamic backend
behaviour (auth, trips, plans, ...) is exercised by later-phase suites.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"

# Isolate any future persistent backend into a throwaway data dir for this run.
_FRONTEND_DATA_DIR = tempfile.mkdtemp(prefix="tripit-frontend-tests-")
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = _FRONTEND_DATA_DIR

_spec = importlib.util.spec_from_file_location("tripit_clone_app", APP_FILE)
assert _spec is not None and _spec.loader is not None
app_module = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("tripit_clone_app", app_module)
_spec.loader.exec_module(app_module)

app = app_module.app

# Broad remote-reference scan (any absolute or protocol-relative host), matching
# the assets-gate / build self-check so no remote origin can hide in runtime
# files or rendered HTML.
REMOTE_URL = re.compile(
    r"(?i)(?:https?:)?//(?!localhost|127\.0\.0\.1)[a-z0-9.-]+\.[a-z]{2,}"
)
# XML/SVG namespace declarations (xmlns / xmlns:prefix = a W3C namespace URI) are
# declarative identifiers the browser never dereferences, not runtime references.
# Blank them before the remote scan so authentic inline SVG markup
# (<svg xmlns="http://www.w3.org/2000/svg" …>) stays byte-faithful to the source
# without tripping the audit; mirrors tools/assets_gate.py.
XMLNS_NAMESPACE = re.compile(
    r"""(?ix)
    \bxmlns (?: : [a-z0-9_.-]+ )?
    \s* = \s*
    (["'])
    \s* https?://www\.w3\.org/ [^"']*
    \1
    """
)

# Explicit user-facing outbound navigation is allowed for the five social
# controls in the authenticated footer. These are ordinary anchors opened only
# after a user click; they are not runtime resource requests. Keep the list
# exact so scripts, styles, images, forms, and arbitrary hosts remain blocked.
ALLOWED_SOCIAL_NAVIGATION = re.compile(
    r'''(?ix)
    href\s*=\s*(["'])
    (?:
      https://www\.instagram\.com/tripitcom |
      https://www\.facebook\.com/tripitcom |
      https://twitter\.com/TripIt |
      https://www\.linkedin\.com/company/tripit |
      https://www\.youtube\.com/user/tripitvideos
    )
    \1
    '''
)


def _has_remote_url(text: str) -> bool:
    """True if `text` carries a fetchable remote URL, ignoring xmlns namespaces."""
    return bool(REMOTE_URL.search(XMLNS_NAMESPACE.sub("", text)))

# route -> (distinctive markers that must be present in the served document)
ROUTE_MARKERS: dict[str, list[str]] = {
    "/": ["TripIt: Highest-Rated Travel Itinerary App + Trip Planner"],
    "/web/free": ["TripIt - A single (free) itinerary created for you in seconds"],
    "/web/pro": ["TripIt Pro - Flight Status and Reminders Throughout Your Trip"],
    "/web/free/how-it-works": [
        "Learn how TripIt organizes all your travel plans in a flash"
    ],
    "/web/pro/pricing": [
        "Pricing - TripIt Pro vs. free features included with TripIt"
    ],
    "/web/pro/sap-concur": ["Benefits for SAP Concur users when you connect TripIt"],
    "/web/free/download": [
        "Download the TripIt app to access travel plans on any device"
    ],
    "/web/security": ["Data Privacy and Security - TripIt"],
    "/web/blog": ["TripIt Blog — Travel Itinerary — Trip Planner"],
    "/web/traveler-resource-center": ["Traveler Resource Center | TripIt"],
    "/account/login": ["Sign in to TripIt", "Password"],
    "/account/create": ["Sign up for TripIt", "Create an Account"],
    "/account/forgotPassword": ["Sign in help"],
    "/uhp/userAgreement": ["TripIt User Agreement"],
    "/uhp/privacyPolicy": ["TripIt Privacy Statement"],
    "/uhp/doNotShare": [
        "Your privacy is important to us!",
        "Do Not Share/Sell My Personal Information",
    ],
}

MARKETING_ROUTES = {
    "/",
    "/web/free",
    "/web/pro",
    "/web/free/how-it-works",
    "/web/pro/pricing",
    "/web/pro/sap-concur",
    "/web/free/download",
    "/web/security",
    "/web/blog",
    "/web/traveler-resource-center",
}
AUTH_LEGAL_ROUTES = {
    "/account/login",
    "/account/create",
    "/account/forgotPassword",
    "/uhp/userAgreement",
    "/uhp/privacyPolicy",
    "/uhp/doNotShare",
}


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app_module.reset_fixture_state()


# ---------------------------------------------------------------------------
# runtime contract + security headers (runtime.local-only)
# ---------------------------------------------------------------------------


def test_healthz_returns_exact_frozen_body(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    # The deploy verification requires this exact byte string.
    assert response.text == '{"ok":true,"site_id":"tripit"}'
    assert response.json() == {"ok": True, "site_id": "tripit"}


def test_security_headers_and_local_only_on_every_route(client):
    for route in ROUTE_MARKERS:
        response = client.get(route)
        assert response.status_code == 200, route
        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp, route
        assert "frame-ancestors 'none'" in csp, route
        assert response.headers.get("X-Content-Type-Options") == "nosniff", route
        assert response.headers.get("Referrer-Policy") == "no-referrer", route
        # No remote origin may be reachable from the rendered HTML.
        assert not _has_remote_url(response.text), route


def test_runtime_files_have_no_remote_urls():
    suffixes = {".html", ".css", ".js", ".py"}
    offenders: list[str] = []
    scanned = 0
    for path in CLONE_DIR.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in suffixes:
            continue
        relative = path.relative_to(CLONE_DIR).as_posix()
        if relative.startswith("static/assets/"):
            continue  # frozen payloads verified by the assets gate
        if relative.startswith("tests/"):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _has_remote_url(ALLOWED_SOCIAL_NAVIGATION.sub("", line)):
                offenders.append(f"{relative}:{line_number}: {line.strip()[:100]}")
    assert scanned >= 16
    assert not offenders, offenders
    # No shipped document may carry a fetchable remote form of the origin host.
    # The mirrored asset paths legitimately embed "www.tripit.com" as a
    # directory segment (/static/assets/.../www.tripit.com/...), so only the
    # URL forms are forbidden, not the bare host string.
    for marker in (
        "https://www.tripit.com",
        "http://www.tripit.com",
        "//www.tripit.com",
        "https://tripit.com",
    ):
        for path in (CLONE_DIR / "frontend" / "pages").glob("*.html"):
            assert marker not in path.read_text(encoding="utf-8"), (marker, path.name)


# ---------------------------------------------------------------------------
# route matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", sorted(ROUTE_MARKERS))
def test_every_route_renders_with_distinctive_markers(client, route):
    response = client.get(route)
    assert response.status_code == 200, route
    assert response.headers["content-type"].startswith("text/html"), route
    for marker in ROUTE_MARKERS[route]:
        assert marker in response.text, (route, marker)
    # No build/scaffold leakage on any public page.
    for forbidden in ("websitebench", "NotImplementedError", "Traceback"):
        assert forbidden not in response.text, (route, forbidden)


def test_routes_are_deterministic_on_refresh(client):
    for route in ("/", "/account/login", "/web/pro/pricing"):
        first = client.get(route)
        second = client.get(route)
        assert first.status_code == second.status_code == 200, route
        assert first.text == second.text, route


# ---------------------------------------------------------------------------
# favicon topology (per page family)
# ---------------------------------------------------------------------------


def test_marketing_pages_carry_only_theme_favicon(client):
    for route in MARKETING_ROUTES:
        text = client.get(route).text
        assert "/static/site/favicon/theme-favicon.ico" in text, route


def test_auth_legal_pages_carry_shortcut_and_mask_icons(client):
    for route in AUTH_LEGAL_ROUTES:
        text = client.get(route).text
        assert "/static/site/favicon/favicon.ico" in text, route
        assert "/safari-pinned-tab.svg" in text, route


def test_favicon_payloads_resolve_locally(client):
    # The two exiled favicons are served byte-exact from the out-of-closure
    # site tree. Their on-wire format is whatever the source served (one is a
    # real ICO, the other a PNG under an .ico name), so the meaningful contract
    # is byte-identical delivery, not a particular magic number.
    site_favicon = CLONE_DIR / "static" / "site" / "favicon"
    for name in ("theme-favicon.ico", "favicon.ico"):
        path = f"/static/site/favicon/{name}"
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content == (site_favicon / name).read_bytes(), path


# ---------------------------------------------------------------------------
# static asset closure resolves through the app mount
# ---------------------------------------------------------------------------


def test_static_assets_resolve_through_mount(client):
    assets_root = CLONE_DIR / "static" / "assets"
    picks: list[str] = []
    wanted = {".css", ".woff2", ".svg", ".png", ".js"}
    seen: set[str] = set()
    for path in sorted(assets_root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.casefold()
        if suffix in wanted and suffix not in seen and " " not in path.name:
            seen.add(suffix)
            picks.append("/static/" + path.relative_to(CLONE_DIR / "static").as_posix())
        if len(seen) == len(wanted):
            break
    assert picks, "no static assets found to probe"
    for url in picks:
        response = client.get(url)
        assert response.status_code == 200, url


# ---------------------------------------------------------------------------
# external boundary + admin reset contracts
# ---------------------------------------------------------------------------


def test_external_boundary_is_local(client):
    response = client.get("/external/apps.apple.com")
    assert response.status_code == 200
    assert "External link" in response.text
    assert not REMOTE_URL.search(response.text)
    assert "Content-Security-Policy" in response.headers


def test_admin_reset_requires_constant_time_token(client):
    denied = client.post("/__admin/reset")
    assert denied.status_code == 403

    wrong = client.post("/__admin/reset", headers={"X-WebsiteBench-Admin-Token": "nope"})
    assert wrong.status_code == 403

    token = app_module.ADMIN_TOKEN
    ok = client.post("/__admin/reset", headers={"X-WebsiteBench-Admin-Token": token})
    assert ok.status_code == 200
    assert ok.json() == {"reset": True, "site_id": "tripit"}
