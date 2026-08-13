"""Honest boundaries in the persistent chrome.

The captured marketing chrome links to more of the source than the capture
covers: legacy nav aliases on the legal pages, a five-locale language menu, and
every blog post the index lists. Those controls are in the header and footer, so
a dead one is visible from every page.

Two rules are pinned here. An alias whose destination *is* built redirects to
it. Everything else answers with a page that says the content was not built —
and, for the locale menu, without ever serving the en-US copy under a foreign
locale, which would present one region's prices and legal text as another's.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"
SITE_CONFIG = SITE_DIR / "clone.yaml"

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-boundary-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_boundary_tests")
app = app_module.app

FORBIDDEN_TOKENS = ("clone", "offline", "harness", "website-bench")


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# aliases reach the page they name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/uhp/features", "/web/free"),
        ("/pro/features", "/web/pro"),
        ("/uhp/pricing", "/web/pro/pricing"),
        ("/web/download", "/web/free/download"),
        ("/pro", "/pro/upgrade"),
    ],
)
def test_legacy_nav_aliases_redirect_to_a_built_page(client, path, expected):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == expected


def test_every_alias_destination_is_itself_reachable(client):
    for destination in app_module._MARKETING_ALIASES.values():
        response = client.get(destination, follow_redirects=False)
        assert response.status_code in (200, 303), destination


# ---------------------------------------------------------------------------
# the language menu
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("locale", sorted(app_module._FROZEN_LOCALES))
def test_each_locale_in_the_menu_answers(client, locale):
    response = client.get(f"/{locale}/web", follow_redirects=False)
    assert response.status_code == 200
    assert "English (United States)" in response.text


@pytest.mark.parametrize("locale", sorted(app_module._FROZEN_LOCALES))
def test_a_locale_path_never_serves_the_en_us_page_body(client, locale):
    en_us = client.get("/web/free").text
    localized = client.get(f"/{locale}/web/free").text
    assert localized != en_us
    assert "A single (free) itinerary created for you in seconds" not in localized


def test_the_declared_regional_baseline_is_the_one_the_boundary_names():
    config = SITE_CONFIG.read_text(encoding="utf-8")
    assert "en-US" in config or "en_US" in config


def test_an_unlisted_locale_is_still_a_404(client):
    for locale in ("zz", "it", "ja"):
        assert client.get(f"/{locale}/web/free", follow_redirects=False).status_code == 404


# ---------------------------------------------------------------------------
# blog posts and unbuilt marketing pages
# ---------------------------------------------------------------------------


def test_a_blog_post_answers_with_a_boundary_and_a_way_back(client):
    response = client.get("/web/blog/travel-tips/what-is-step", follow_redirects=False)
    assert response.status_code == 200
    assert "not part of this build" in response.text
    assert 'href="/web/blog"' in response.text


def test_the_blog_index_itself_is_still_the_captured_page(client):
    body = client.get("/web/blog").text
    assert "TripIt Blog" in body
    assert "not part of this build" not in body


@pytest.mark.parametrize("path", sorted(app_module._UNBUILT_MARKETING))
def test_each_unbuilt_chrome_destination_answers(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert "not part of this build" in response.text


def test_a_path_nothing_links_to_is_still_a_404(client):
    assert client.get("/web/not-a-real-page", follow_redirects=False).status_code == 404
    assert client.get("/uhp/invented", follow_redirects=False).status_code == 404


# ---------------------------------------------------------------------------
# every boundary page keeps the blind-test surface clean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/de/web",
        "/web/blog/travel-tips/what-is-step",
        "/uhp/supportedVendors",
        "/account/signInGoogle",
        "/account/signUpGoogle",
    ],
)
def test_boundary_pages_disclose_no_build_identity(client, path):
    body = client.get(path).text.casefold()
    for token in FORBIDDEN_TOKENS:
        assert token not in body, (path, token)


@pytest.mark.parametrize(
    "path",
    ["/de/web", "/web/blog/travel-tips/what-is-step", "/uhp/supportedVendors"],
)
def test_boundary_pages_are_navigable_rather_than_dead_ends(client, path):
    body = client.get(path).text
    assert 'href="/"' in body
    assert 'href="/web/free"' in body
