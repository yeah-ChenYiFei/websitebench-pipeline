from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from html import escape
from html.parser import HTMLParser
from fastapi.testclient import TestClient

from app import (
    ASSET_REPORTS,
    ASSET_URL_MAP,
    DATA,
    G3_VISUAL_URL_MAP,
    PAGES,
    SITE_ROOT,
    UNAVAILABLE_ASSETS,
    app,
)


client = TestClient(app)
CONTRACT = json.loads(
    (SITE_ROOT / "scope" / "business-contracts" / "route-state-contract.json").read_text(encoding="utf-8")
)


class AttributeIndex(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def attributes(markup: str) -> list[tuple[str, dict[str, str | None]]]:
    result = AttributeIndex()
    result.feed(markup)
    return result.tags


def test_all_732_frozen_routes_have_exact_status_title_family_and_identity() -> None:
    assert len(PAGES) == 732
    expected_families = CONTRACT["route_family_counts"]
    assert Counter(row["family"] for row in PAGES.values()) == expected_families
    for path, row in PAGES.items():
        response = client.get(path)
        assert response.status_code == row["status"], path
        assert f"<title>{escape(str(row['title']))}</title>" in response.text, path
        assert f'data-wb-route-family="{row["family"]}"' in response.text, path
        assert f'data-wb-page-id="{row["page_id"]}"' in response.text, path
        if path == "/":
            assert "Unlocking knowledge" in response.text
        else:
            heading = next(
                (str(item["text"]) for item in row["headings"] if str(item.get("text", "")).strip()),
                "",
            )
            assert heading and escape(heading) in response.text, path


def test_29_representative_routes_preserve_frozen_title_and_boundaries() -> None:
    representatives = CONTRACT["representative_acceptance_routes"]
    assert len(representatives) == 29
    for row in representatives:
        response = client.get(row["path"])
        assert response.status_code == 200, row["route_id"]
        assert f"<title>{escape(row['title'])}</title>" in response.text, row["route_id"]


def test_all_eleven_route_families_have_distinct_real_structures() -> None:
    expected = {
        "home": ("/", 'data-wb-component="home-hero"'),
        "catalog-search": ("/search/", 'data-wb-component="catalog-results"'),
        "collection": (
            "/collections/introductory-programming/",
            'data-wb-g3b-content="/collections/introductory-programming/"',
        ),
        "course-overview": (
            "/courses/6-006-introduction-to-algorithms-fall-2011/",
            'class="course-overview"',
        ),
        "course-section-or-deep-link": (
            "/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/",
            'class="course-section"',
        ),
        "resource-detail-or-index": (
            "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/",
            'class="resource-page"',
        ),
        "course-download": (
            "/courses/6-006-introduction-to-algorithms-fall-2011/download/",
            'class="download-panel"',
        ),
        "story-index": ("/stories/", 'class="stories-index"'),
        "story-detail": (
            "/stories/adrian-pastor/",
            'data-wb-g3b-content="/stories/adrian-pastor/"',
        ),
        "site-information-or-boundary": ("/about/", 'class="site-information"'),
        "video-gallery": (
            "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
            "video_galleries/video-lectures/",
            'data-wb-component="video-gallery"',
        ),
    }
    assert set(expected) == set(CONTRACT["route_family_counts"])
    for family, (path, marker) in expected.items():
        markup = client.get(path).text
        assert f'data-wb-route-family="{family}"' in markup
        if marker.startswith('class="'):
            class_token = marker.removeprefix('class="').removesuffix('"')
            assert re.search(rf'class="[^"]*\b{re.escape(class_token)}\b', markup)
        else:
            assert marker in markup


def test_all_231_presentation_asset_urls_are_local_and_exact() -> None:
    assert len(ASSET_URL_MAP) == len(DATA["presentation_assets"]) == 231
    logical_bytes = 0
    for source_url, local_url in ASSET_URL_MAP.items():
        assert local_url.startswith("/presentation-assets/")
        response = client.get(local_url)
        assert response.status_code == 200, source_url
        name = local_url.rsplit("/", 1)[-1]
        record = DATA["presentation_assets"][name]
        logical_bytes += int(record["bytes"])
        assert len(response.content) == int(record["bytes"])
        assert hashlib.sha256(response.content).hexdigest() == record["sha256"]
        assert response.headers["x-content-sha256"] == record["sha256"]
    assert logical_bytes == 35_298_609


def test_five_source_404_assets_remain_explicitly_unavailable() -> None:
    assert len(UNAVAILABLE_ASSETS) == 5
    for source_url in UNAVAILABLE_ASSETS:
        assert source_url not in ASSET_URL_MAP
        response = client.get("/unavailable-asset/", params={"url": source_url})
        assert response.status_code == 404
        assert response.json()["status"] == "source-unavailable"
        assert response.json()["source_status"] == 404
        assert response.json()["url"] == source_url


def test_page_media_sources_are_retained_report_evidence_not_slug_guesses() -> None:
    known_report_sources = {
        str(ref["url"])
        for refs in ASSET_REPORTS.values()
        for ref in refs
        if ref.get("status") == 200
    } | set(G3_VISUAL_URL_MAP)
    for path in (
        "/",
        "/search/?state=resources",
        "/courses/6-006-introduction-to-algorithms-fall-2011/",
        "/stories/adrian-pastor/",
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/video_galleries/video-lectures/",
    ):
        for tag, attrs in attributes(client.get(path).text):
            source = attrs.get("data-wb-asset-source")
            if source:
                assert source in known_report_sources, (path, source)
                assert source in ASSET_URL_MAP or source in G3_VISUAL_URL_MAP, (path, source)
                assert tag == "img"
    video_path = (
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
        "resources/mit14_129s25_lec01_1080p_mp4/"
    )
    poster_surface = next(
        attrs
        for tag, attrs in attributes(client.get(video_path).text)
        if tag == "img" and attrs.get("data-wb-media") == "disabled-video-poster"
    )
    assert poster_surface["class"] == "offline-video-poster"
    assert poster_surface["src"].startswith("data:image/svg+xml,")
    assert "data-wb-asset-source" not in poster_surface
    video_markup = client.get(video_path).text
    assert 'data-wb-control="video-play" disabled' in video_markup
    assert "img.youtube.com" not in video_markup


def test_every_page_and_state_is_free_of_remote_runtime_fetch_surfaces() -> None:
    state_routes = [
        "/?state=carousel-second-batches",
        *[
            f"/search/?state={state}"
            for state in (
                "second-batch",
                "math",
                "math-undergraduate",
                "course-number",
                "loading",
                "empty",
                "error",
                "retry-stale",
                "reload-recovered",
                "resources",
            )
        ],
    ]
    for path in [*PAGES, *state_routes]:
        markup = client.get(path).text
        assert not re.search(r"(?:src|action|poster)=[\"']https?://", markup), path
        assert not re.search(r"<(?:iframe|video|audio|source)\b", markup, flags=re.I), path
        assert not re.search(r"url\(\s*[\"']?https?://", markup, flags=re.I), path
        assert "connect-src 'self'" in markup, path


def test_static_video_and_newsletter_are_real_local_boundaries() -> None:
    video_path = (
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
        "resources/mit14_129s25_lec01_1080p_mp4/"
    )
    video_tags = attributes(client.get(video_path).text)
    play = next(attrs for _tag, attrs in video_tags if attrs.get("data-wb-control") == "video-play")
    assert "disabled" in play
    newsletter = client.get("/newsletter/").text
    newsletter_tags = attributes(newsletter)
    form = next(
        attrs
        for tag, attrs in newsletter_tags
        if tag == "form" and attrs.get("data-wb-component") == "newsletter-form"
    )
    assert form["action"] == "/external-boundary/"
    assert form["method"] == "get"
    assert "<video" not in client.get(video_path).text
