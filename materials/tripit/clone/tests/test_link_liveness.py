"""AS-1: no surface may offer a control that goes nowhere.

Ported from the reference implementation in materials/amazon. A link whose
destination is ``#``, or whose destination does not answer, is indistinguishable
to a visitor from a broken site. Where a subject genuinely is not modelled here,
the link must point at a local page that says so — which this test accepts,
because such a page answers.

The crawl walks every internal link reachable from the anonymous entry points
and, separately, from the signed-in dashboard, so a dead control anywhere in the
persistent chrome is caught wherever it appears.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-link-liveness-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_link_liveness_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}
TRAVELER = "traveler@example.com"

ANONYMOUS_SEEDS = ("/", "/account/login", "/account/create", "/account/forgotPassword")
SIGNED_IN_SEEDS = ("/app/trips", "/trips", "/account", "/app")

# Off-site and non-navigational schemes are out of scope: the boundary that
# keeps them local is asserted elsewhere.
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "javascript:", "data:")

# Mirrored source-asset trees, not pages.
SKIP_PREFIXES = ("/static/", "/app/assets/", "/themes/", "/images/", "/sites/", "/core/")

# In-page anchors that are navigation aids rather than destinations.
ALLOWED_FRAGMENTS = {"#main", "#main-content", "#fw-main-content", "#top", "#products", "#partners",
                     "#news-and-resources"}

# The frozen marketing captures carry the source's own consent widget, whose
# trigger is a scripted `href="#"` in the source too (verified against
# source-current/2026-08-03.tripit-r1). Those documents are byte-stable evidence
# and pixel-locked, so they are crawled for liveness but not rewritten; the
# equivalent control in the app shell, which this build does own, is a real
# link and is asserted below.
FROZEN_CAPTURE_PATHS = {
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
    "/uhp/userAgreement",
    "/uhp/privacyPolicy",
    "/uhp/doNotShare",
}


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.actions: list[str] = []

    def handle_starttag(self, tag, attrs):
        mapping = {key: value for key, value in attrs if value is not None}
        if tag == "a" and mapping.get("href"):
            self.hrefs.append(mapping["href"])
        if tag == "form" and mapping.get("action"):
            self.actions.append(mapping["action"])


def crawl(client: TestClient, seeds) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Walk internal links breadth-first. Returns (status by path, dead hrefs)."""

    statuses: dict[str, int] = {}
    dead_fragments: list[tuple[str, str]] = []
    queue = list(seeds)
    while queue:
        path = queue.pop(0)
        base = path.split("?", 1)[0]
        if path in statuses:
            continue
        response = client.get(path, follow_redirects=False)
        statuses[path] = response.status_code
        if response.status_code != 200:
            continue
        if "text/html" not in response.headers.get("content-type", ""):
            continue
        parser = _Anchors()
        parser.feed(response.text)
        for href in parser.hrefs:
            if href.startswith(SKIP_SCHEMES) or href.startswith(SKIP_PREFIXES):
                continue
            if href.startswith("#"):
                if href not in ALLOWED_FRAGMENTS and base not in FROZEN_CAPTURE_PATHS:
                    dead_fragments.append((path, href))
                continue
            if href.startswith("/"):
                queue.append(href)
    return statuses, dead_fragments


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


@pytest.fixture(scope="module")
def anonymous_crawl():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as client:
        yield crawl(client, ANONYMOUS_SEEDS)


@pytest.fixture(scope="module")
def signed_in_crawl():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/account/login",
            data={
                "login_email_address": TRAVELER,
                "login_password": PASSWORDS[TRAVELER],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        yield crawl(client, SIGNED_IN_SEEDS)


def dead(statuses: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(
        (path, code) for path, code in statuses.items() if code not in (200, 303, 307)
    )


def test_the_anonymous_crawl_actually_covers_the_site(anonymous_crawl):
    statuses, _ = anonymous_crawl
    assert len(statuses) >= 60, len(statuses)


def test_every_anonymous_destination_answers(anonymous_crawl):
    statuses, _ = anonymous_crawl
    assert dead(statuses) == []


def test_no_anonymous_surface_this_build_owns_offers_a_dead_fragment(anonymous_crawl):
    _, fragments = anonymous_crawl
    assert fragments == []


def test_the_signed_in_crawl_actually_covers_the_app(signed_in_crawl):
    statuses, _ = signed_in_crawl
    assert len(statuses) >= 150, len(statuses)
    assert any(path.startswith("/app/trips/") for path in statuses)


def test_every_signed_in_destination_answers(signed_in_crawl):
    statuses, _ = signed_in_crawl
    assert dead(statuses) == []


def test_no_signed_in_surface_offers_a_dead_fragment(signed_in_crawl):
    _, fragments = signed_in_crawl
    assert fragments == []


def test_the_app_shells_own_templates_carry_no_dead_href():
    """The persistent chrome this build authors is checked at the source, not
    only through a crawl, so a control that is merely unreachable today still
    cannot be shipped pointing at nothing."""

    templates = CLONE_DIR / "frontend" / "templates"
    offenders = [
        path.relative_to(templates).as_posix()
        for path in templates.rglob("*.html")
        if 'href="#"' in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_app_footers_cookie_control_is_a_real_destination():
    shell = (CLONE_DIR / "frontend" / "templates" / "app" / "base.html").read_text(
        encoding="utf-8"
    )
    assert 'href="/app/cookie-preferences"' in shell
    assert 'id="footer-link-cookie_preferences"' in shell
