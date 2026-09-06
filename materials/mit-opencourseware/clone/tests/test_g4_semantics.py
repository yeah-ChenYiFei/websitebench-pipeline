from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from fastapi.testclient import TestClient

from app import DATA, SITE_ROOT, app


client = TestClient(app)
SCOPE = SITE_ROOT / "scope"
COURSE_ROOT = "/courses/6-006-introduction-to-algorithms-fall-2011/"
VIDEO = (
    "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
    "resources/mit14_129s25_lec01_1080p_mp4/"
)
NEWSLETTER_DESTINATION = (
    "https://mit.us6.list-manage.com/subscribe/post?"
    "u=ad81d725159c1f322a0c54837&id=4c04dfddc5&f_id=00e734e1f0"
)


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.rows.append((tag, dict(attrs)))


def tags(html: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = Tags()
    parser.feed(html)
    return parser.rows


def tagged(html: str, attribute: str, value: str) -> dict[str, str | None]:
    matches = [attrs for _tag, attrs in tags(html) if attrs.get(attribute) == value]
    assert len(matches) >= 1, (attribute, value)
    return matches[0]


def test_frozen_semantic_denominators_are_exact_and_locally_rendered() -> None:
    controls = json.loads((SCOPE / "all-controls-inventory.json").read_text(encoding="utf-8"))["controls"]
    capabilities = json.loads((SCOPE / "component-state-matrix.json").read_text(encoding="utf-8"))[
        "local_capabilities"
    ]
    assert len(controls) == len({row["id"] for row in controls}) == 30
    assert len(capabilities) == len({row["id"] for row in capabilities}) == 7
    assert len(DATA["assertions"]) == 128


def test_home_search_and_all_contracted_carousel_directions_are_real() -> None:
    default = client.get("/").text
    second = client.get("/?state=carousel-second-batches").text
    assert tagged(default, "data-wb-control", "global-search-input")["name"] == "q"
    assert tagged(default, "data-wb-control", "global-search-submit")["type"] == "submit"
    for control in ("promo-previous", "promo-next", "featured-next", "new-next", "stories-next"):
        assert tagged(default, "data-wb-control", control)["href"] == "/?state=carousel-second-batches"
    for control in ("promo-previous", "promo-next", "featured-previous", "new-previous", "stories-previous"):
        assert tagged(second, "data-wb-control", control)["href"] == "/?state=default"


def test_catalog_query_filters_complete_twenty_course_snapshot_case_insensitively() -> None:
    software = client.get("/search/?q=SOFTWARE").text
    assert "1 results" in software
    assert "The Software Business" in software
    assert "Research Design for Policy Analysis and Planning" not in software
    assert 'value="SOFTWARE"' in software

    science = client.get("/search/?q=science").text
    expected = [course for course in DATA["catalog"]["courses"] if "science" in course["card_text"].casefold()]
    assert f"{len(expected)} results" in science
    assert all(course["title_link_text"] in science for course in expected)

    missing = client.get("/search/?q=no-such-frozen-course").text
    assert "0 results" in missing and "No results match your search" in missing
    assert 'action="/search/"' in missing
    assert not re.search(r"(?:action|src)=[\"']https?://", missing)


def test_catalog_departments_and_shell_menus_expose_observable_aria_targets() -> None:
    catalog = client.get("/search/").text
    departments = tagged(catalog, "data-wb-control", "catalog-departments")
    assert departments["aria-controls"] == "catalog-department-list"
    assert departments["aria-expanded"] == "true"
    assert tagged(catalog, "id", "catalog-department-list")["data-menu-open"] == "true"

    home = client.get("/").text
    nav = tagged(home, "data-wb-control", "nav-toggle")
    assert nav["aria-controls"] == "global-navigation" and nav["aria-expanded"] == "false"
    assert tagged(home, "id", "global-navigation")["data-menu-open"] == "false"

    course = client.get(COURSE_ROOT).text
    menu = tagged(course, "data-wb-control", "course-menu")
    assert menu["aria-controls"] == "course-material-navigation" and menu["aria-expanded"] == "false"
    assert tagged(course, "id", "course-material-navigation")["data-menu-open"] == "false"


def test_newsletter_video_downloads_and_boundaries_are_network_closed() -> None:
    newsletter = client.get("/newsletter/").text
    form = tagged(newsletter, "data-wb-component", "newsletter-form")
    assert form["method"] == "get" and form["action"] == "/external-boundary/"
    assert form["data-wb-external-destination"] == NEWSLETTER_DESTINATION
    assert "preventDefault()" in newsletter
    assert tagged(newsletter, "data-wb-control", "newsletter-email")["type"] == "email"
    assert "disabled" not in tagged(newsletter, "data-wb-control", "newsletter-submit")

    video = client.get(VIDEO).text
    assert tagged(video, "data-wb-media", "disabled-video-poster")
    assert "disabled" in tagged(video, "data-wb-control", "video-play")
    assert not re.search(r"<(?:audio|video|source|iframe)\b", video, re.I)

    course_download = client.get(COURSE_ROOT + "download/").text
    archive = tagged(course_download, "data-wb-control", "course-download")
    assert archive["data-wb-capability"] == "local-course-archive"
    assert archive["href"] == COURSE_ROOT + "6.006-fall-2011.zip"

    resource = client.get(COURSE_ROOT + "resources/mit6_006f11_ps1/").text
    attachment = tagged(resource, "data-wb-control", "resource-download")
    assert attachment["data-wb-capability"] == "local-attachment-download"
    assert str(attachment["href"]).startswith(COURSE_ROOT)

    assert tagged(client.get("/external-boundary/").text, "data-wb-control", "external-return")["href"] == "/"
    assert tagged(client.get("/data-boundary/").text, "data-wb-control", "data-boundary-return")["href"] == "/search/"
    malicious = client.get("/external-boundary/", params={"url": "<script>window.pwned=true</script>"}).text
    assert "<script>window.pwned=true</script>" not in malicious
    assert "&lt;script&gt;window.pwned=true&lt;/script&gt;" in malicious
    assert client.get("/healthz").json()["remote_requests"] == 0
