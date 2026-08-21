from __future__ import annotations

import re
import urllib.error
import urllib.request


def fetch(base_url: str, path: str) -> tuple[int, dict[str, str], str]:
    try:
        response = urllib.request.urlopen(base_url + path, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        headers = {name.lower(): value for name, value in response.headers.items()}
        return response.status, headers, response.read().decode("utf-8")


def test_home_serves_the_archived_public_page_contract(live_server: str) -> None:
    """Catch the homepage losing a source-visible section or its English shell."""

    status, _, html = fetch(live_server, "/")

    assert status == 200
    assert 'lang="en"' in html
    assert "Coursera | Online Courses &amp; Credentials From Top Educators" in html
    for visible_copy in (
        "For Individuals",
        "What do you want to learn?",
        "New! Learn vibe coding with Google",
        "Start, switch, or advance your career",
        "New and popular",
        "Unlock 10,000+ courses with a subscription",
        "Learn from 350+ leading universities and companies",
        "Explore categories",
        "What brings you to Coursera today?",
        "Explore careers",
        "91% of learners achieved a positive career outcome",
        "Why people choose Coursera",
        "Frequently asked questions",
        "Coursera Footer",
        "Cookie preferences",
    ):
        assert visible_copy in html


def test_home_starts_with_two_of_three_promotional_cards_visible(live_server: str) -> None:
    """Catch the archive's two-card desktop state becoming one card or all cards."""

    _, _, html = fetch(live_server, "/")
    cards = re.findall(r'<article[^>]+data-promo-card="([^"]+)"[^>]*>', html)
    hidden_cards = re.findall(
        r'<article[^>]+data-promo-card="([^"]+)"[^>]*\shidden(?:\s|>)', html
    )

    assert cards == ["google-vibe", "join-free", "coursera-business"]
    assert hidden_cards == ["coursera-business"]
    assert html.count("data-promo-dot") == 3


def test_home_runtime_references_are_local(live_server: str) -> None:
    """Catch the reconstructed page reintroducing a remote runtime dependency."""

    _, headers, html = fetch(live_server, "/")
    runtime_urls = re.findall(r'(?:src|href)="([^"]+)"', html)

    assert runtime_urls
    assert all(not url.startswith(("http://", "https://", "//")) for url in runtime_urls)
    assert "default-src 'self'" in headers["content-security-policy"]


def test_health_and_uncaptured_route_boundaries_are_explicit(live_server: str) -> None:
    """Catch unsupported routes silently pretending to be archived content."""

    health_status, _, health_body = fetch(live_server, "/healthz")
    unsupported_status, _, unsupported_body = fetch(live_server, "/login")

    assert health_status == 200
    assert health_body == '{"status":"ok"}'
    assert unsupported_status == 404
    assert "This page was not included in the supplied archive." in unsupported_body
    assert 'href="/"' in unsupported_body
