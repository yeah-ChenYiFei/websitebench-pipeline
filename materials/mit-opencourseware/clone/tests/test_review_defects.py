from __future__ import annotations

import json
import runpy
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, sync_playwright

from app import SITE_ROOT, app


@pytest.fixture(scope="module")
def live_base_url() -> Iterator[str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    sockets = server.servers[0].sockets
    port = sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        device_scale_factor=1,
        locale="en-US",
        timezone_id="America/Toronto",
        color_scheme="light",
        reduced_motion="reduce",
    )
    current = context.new_page()
    try:
        yield current
    finally:
        context.close()


def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(base_url + path, wait_until="networkidle")


def component_text(page: Page, name: str) -> str:
    return page.locator(f'[data-wb-component="{name}"]').inner_text()


def test_about_president_message_does_not_collapse_to_min_content(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/about/")
    container = page.locator("#president-dean-messages .container").first
    assert container.evaluate("element => element.getBoundingClientRect().width") >= 1000
    assert page.evaluate(
        """[...document.querySelectorAll('body *')].filter(element => {
          const rect = element.getBoundingClientRect();
          return rect.height > 600 && rect.width > 0 && rect.width < 320
            && (element.innerText || '').trim().length > 80;
        }).length"""
    ) == 0
    assert 10_000 <= page.evaluate("document.documentElement.scrollHeight") <= 12_500


def test_stories_index_uses_three_columns_at_the_acceptance_viewport(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/stories/")
    items = page.locator(".stories-list-item")
    featured = [
        items.nth(index).evaluate(
            "element => ({width: element.getBoundingClientRect().width, top: element.offsetTop})"
        )
        for index in (0, 1)
    ]
    standard = [
        items.nth(index).evaluate(
            "element => ({width: element.getBoundingClientRect().width, top: element.offsetTop})"
        )
        for index in (2, 3, 4)
    ]
    assert all(600 <= item["width"] <= 640 for item in featured)
    assert len({item["top"] for item in featured}) == 1
    assert all(390 <= item["width"] <= 430 for item in standard)
    assert len({item["top"] for item in standard}) == 1
    container = page.locator(".stories-list-item-container").bounding_box()
    first_wrapper = page.locator(".stories-list-item > .item-wrapper").first.bounding_box()
    assert container is not None and first_wrapper is not None
    assert container["x"] == pytest.approx(95, abs=0.1)
    assert container["y"] == pytest.approx(341, abs=0.1)
    assert container["width"] == pytest.approx(1_266, abs=0.1)
    assert first_wrapper["y"] == pytest.approx(357, abs=0.1)
    assert first_wrapper["height"] == pytest.approx(627.3, abs=0.2)
    assert page.evaluate("document.documentElement.scrollHeight") == 5_380


def test_long_course_content_scrolls_with_the_document(
    page: Page, live_base_url: str
) -> None:
    goto(
        page,
        live_base_url,
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/",
    )
    section = page.locator("section.course-section")
    metrics = section.evaluate(
        """element => ({
          maxHeight: getComputedStyle(element).maxHeight,
          overflowY: getComputedStyle(element).overflowY,
          clientHeight: element.clientHeight,
          scrollHeight: element.scrollHeight,
        })"""
    )
    assert metrics["maxHeight"] == "none"
    assert metrics["overflowY"] == "visible"
    assert metrics["clientHeight"] == metrics["scrollHeight"]
    assert page.evaluate("document.documentElement.scrollHeight") > 3_000


def test_resource_index_uses_its_existing_first_item_without_nested_main_spacer(
    page: Page, live_base_url: str
) -> None:
    goto(
        page,
        live_base_url,
        "/courses/6-006-introduction-to-algorithms-fall-2011/resources/problem-sets/",
    )
    first_detail = page.locator('[data-wb-link="problem-set-detail"]')
    assert first_detail.count() == 1
    assert first_detail.evaluate("node => node.matches('.resource-list-title')")
    nested_main = page.locator("#course-content-section")
    assert nested_main.evaluate("node => node.getBoundingClientRect().height") == 0
    content = page.locator("#main-course-section").bounding_box()
    assert content is not None and content["width"] >= 790
    assert page.evaluate("document.documentElement.scrollHeight") == 2_400


@pytest.mark.parametrize(
    ("path", "breadcrumb", "title"),
    [
        (
            "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_final/",
            "Exams",
            "Final Exam",
        ),
        (
            "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec01/",
            "Lecture Notes",
            "Lecture 01: Algorithmic thinking, peak finding",
        ),
        (
            "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/",
            "Assignments",
            "Problem Set 1",
        ),
    ],
)
def test_resource_details_share_the_frozen_title_metadata_download_and_preview_layout(
    page: Page, live_base_url: str, path: str, breadcrumb: str, title: str
) -> None:
    goto(page, live_base_url, path)
    assert page.locator('[data-wb-component="resource-breadcrumb"]').inner_text() == breadcrumb
    assert page.locator(".course-page-title").inner_text() == title
    assert page.locator('[data-wb-component="resource-metadata"]').count() == 1
    assert page.locator('[data-wb-control="resource-download"]').count() == 1
    preview = page.locator('[data-wb-component="resource-preview"]').bounding_box()
    assert preview is not None
    assert 300 <= preview["width"] <= 305
    assert 150 <= preview["height"] <= 155
    assert page.evaluate("document.documentElement.scrollHeight") == 1_298


def test_educator_uses_one_footer_and_matches_the_frozen_page_length(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/educator/")
    assert page.locator("#footer-container").count() == 1
    assert page.locator(".generic-footer").count() == 0
    chalk_radio = page.locator(".section-chalk-radio")
    chalk_box = chalk_radio.bounding_box()
    assert chalk_box is not None
    assert 700 <= chalk_box["height"] <= 740
    assert 4_600 <= chalk_box["y"] <= 4_670
    assert page.locator(".educator-media-reservation").count() == 1
    assert page.evaluate("document.documentElement.scrollHeight") == 6_931


def test_collection_renders_every_frozen_course_group(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/collections/introductory-programming/")
    groups = page.locator('[data-wb-component="collection-course-cards"]')
    assert groups.count() == 3
    assert [groups.nth(index).locator(".collection-course-card").count() for index in range(3)] == [4, 3, 5]
    assert page.locator(".collection-course-card").count() == 12
    assert page.get_by_text("Software Construction", exact=True).count() == 1
    assert page.get_by_text("Introduction to MATLAB", exact=True).count() == 1
    assert page.get_by_text(
        "Introduction to R and Geographic Information Systems (GIS)", exact=True
    ).count() == 1
    assert page.evaluate("document.documentElement.scrollHeight") == 2_486

    page.get_by_text("Software Construction", exact=True).click()
    page.wait_for_load_state("networkidle")
    assert "/data-boundary/" in page.url


def test_catalog_course_overview_does_not_collapse_its_card_body(
    page: Page, live_base_url: str
) -> None:
    goto(
        page,
        live_base_url,
        "/courses/11-233-research-design-for-policy-analysis-and-planning-fall-2007/",
    )
    card_body = page.locator(".course-home-grid .card-body")
    box = card_body.bounding_box()
    assert box is not None
    assert box["width"] >= 700
    assert box["height"] < 500
    assert page.evaluate(
        """[...document.querySelectorAll('body *')].filter(element => {
          const rect = element.getBoundingClientRect();
          return rect.height > 600 && rect.width > 0 && rect.width < 320
            && (element.innerText || '').trim().length > 80;
        }).length"""
    ) == 0
    assert page.evaluate("document.documentElement.scrollHeight") == 900


def test_about_lower_sections_match_the_frozen_vertical_geometry(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/about/")
    president = page.locator("#president-dean-messages").bounding_box()
    staff = page.locator("#staff-desktop .staff-picture").first.bounding_box()
    assert president is not None and staff is not None
    assert 4_430 <= president["y"] <= 4_480
    assert 1_300 <= president["height"] <= 1_350
    assert 8_760 <= staff["y"] <= 8_840
    staff_image = page.locator("#staff-desktop .staff-picture img").first
    assert staff_image.evaluate("node => getComputedStyle(node).visibility") == "visible"
    assert staff_image.evaluate("node => node.complete && node.naturalWidth > 0")
    assert page.evaluate("document.documentElement.scrollHeight") == 11_793


def test_catalog_filters_preserve_the_users_actual_selection(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/search/")
    page.get_by_text("Physics", exact=True).click()
    page.wait_for_load_state("networkidle")
    assert "/data-boundary/" in page.url
    assert "Physics" in page.locator("main").inner_text()
    assert page.locator('[data-wb-control="data-boundary-return"]').get_attribute("href") == "/search/"

    goto(page, live_base_url, "/search/")
    page.locator('[data-wb-control="catalog-undergraduate-filter"]').click()
    page.wait_for_load_state("networkidle")
    assert "/data-boundary/" in page.url
    assert "Undergraduate" in page.locator("main").inner_text()

    goto(page, live_base_url, "/search/?state=math")
    assert page.locator('[data-wb-control="catalog-math-filter"]').is_checked()
    assert not page.locator('[data-wb-control="catalog-undergraduate-filter"]').is_checked()
    page.locator('[data-wb-control="catalog-undergraduate-filter"]').check()
    page.wait_for_load_state("networkidle")
    assert page.url.endswith("/search/?state=math-undergraduate")
    assert page.locator('[data-wb-control="catalog-math-filter"]').is_checked()
    assert page.locator('[data-wb-control="catalog-undergraduate-filter"]').is_checked()


@pytest.mark.parametrize(
    ("path", "expected_height"),
    [
        ("/search/", 2_625),
        ("/search/?state=math", 2_611),
        ("/search/?state=math-undergraduate", 2_611),
        ("/search/?state=course-number", 2_611),
        ("/search/?state=reload-recovered", 2_625),
        ("/search/?state=second-batch", 4_647),
        ("/search/?state=resources", 2_202),
    ],
)
def test_catalog_states_follow_their_frozen_component_geometry(
    page: Page, live_base_url: str, path: str, expected_height: int
) -> None:
    goto(page, live_base_url, path)
    assert abs(page.evaluate("document.documentElement.scrollHeight") - expected_height) <= 3
    assert page.locator("body > .generic-footer").evaluate(
        "node => getComputedStyle(node).display"
    ) == "none"
    assert page.locator(".catalog-search-footer").count() == 1


def test_catalog_resource_state_uses_resource_filters_and_ready_file_media(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/search/?state=resources")
    filters = page.locator('[data-wb-component="catalog-filters"]')
    assert filters.get_by_text("Resource Types", exact=False).count() >= 1
    assert filters.get_by_text("Lecture Notes", exact=True).count() == 1
    assert filters.get_by_text("Programming Assignments", exact=True).count() == 1
    media = page.locator('[data-wb-media="resource-file-icons"]')
    assert media.count() == 10
    assert all(
        media.nth(index).evaluate("element => element.complete && element.naturalWidth > 0")
        for index in range(media.count())
    )
    assert page.get_by_role("heading", name="Exam IV", exact=True).count() == 1
    assert page.get_by_role(
        "heading", name="Module II: Production of Energy in the Cell", exact=True
    ).count() == 1


@pytest.mark.parametrize(
    ("path", "source_height"),
    [
        ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/", 3_305),
        ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/calendar/", 1_988),
        ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/", 1_939),
        (
            "/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/binary-search-trees/",
            1_899,
        ),
        ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-notes/", 2_681),
        ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/", 1_792),
        ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/exams/", 1_298),
        ("/courses/6-006-introduction-to-algorithms-fall-2011/download/", 2_476),
    ],
)
def test_six006_course_sections_follow_live_source_full_page_geometry(
    page: Page, live_base_url: str, path: str, source_height: int
) -> None:
    goto(page, live_base_url, path)
    actual_height = page.evaluate("document.documentElement.scrollHeight")
    assert abs(actual_height - source_height) <= 25
    center = page.locator(".course-center").bounding_box()
    footer = page.locator(".course-footer").bounding_box()
    assert center is not None
    assert center["width"] == pytest.approx(860, abs=0.2)
    if footer is None:
        assert path in {
            "/courses/6-006-introduction-to-algorithms-fall-2011/pages/calendar/",
            "/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/",
            "/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-notes/",
            "/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/",
        }
        assert page.locator(".course-footer").evaluate(
            "node => getComputedStyle(node).display"
        ) == "none"
    else:
        assert center["y"] + center["height"] < footer["y"]


def test_assignments_restores_source_table_flow_and_fair_use_context(
    page: Page, live_base_url: str
) -> None:
    goto(
        page,
        live_base_url,
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/",
    )
    table = page.locator('[data-wb-component="assignments-table"]')
    assert table.locator("tr").count() == 8
    widths = table.locator("thead th").evaluate_all(
        "nodes => nodes.map(node => node.getBoundingClientRect().width)"
    )
    assert widths == pytest.approx([73, 167.2, 440.9, 143.9], abs=0.2)
    assert table.locator("tbody tr").evaluate_all(
        "nodes => nodes.map(node => node.getBoundingClientRect().height)"
    ) == pytest.approx([98, 147, 147, 147, 147, 147, 252], abs=0.2)
    fair_use = table.locator('[data-wb-source-href="https://ocw.mit.edu/help/faq-fair-use/"]')
    assert fair_use.count() == 1
    assert fair_use.get_attribute("href").startswith("/data-boundary/")


def test_download_archive_uses_natural_source_rows_without_footer_overlap(
    page: Page, live_base_url: str
) -> None:
    goto(
        page,
        live_base_url,
        "/courses/6-006-introduction-to-algorithms-fall-2011/download/",
    )
    visible_rows = page.locator(".resource-list-page:visible")
    assert visible_rows.count() == 20
    for index in range(visible_rows.count()):
        box = visible_rows.nth(index).bounding_box()
        assert box is not None and 62 <= box["height"] <= 63
    toggles = page.locator(".resource-list-toggle:visible")
    assert toggles.count() == 8
    for index in range(toggles.count()):
        box = toggles.nth(index).bounding_box()
        assert box is not None and 56 <= box["height"] <= 57
    content = page.locator("#main-course-section").bounding_box()
    footer = page.locator(".course-footer").bounding_box()
    assert content is not None and footer is not None
    assert content["y"] + content["height"] < footer["y"]


def test_video_gallery_grows_with_all_frozen_cards_without_footer_overlap(
    page: Page, live_base_url: str
) -> None:
    goto(
        page,
        live_base_url,
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
        "video_galleries/video-lectures/",
    )
    cards = page.locator(".video-list-card")
    assert cards.count() == 11
    last = cards.last.bounding_box()
    footer = page.locator(".course-footer").bounding_box()
    assert last is not None and footer is not None
    assert last["y"] + last["height"] < footer["y"]
    assert page.evaluate("document.documentElement.scrollHeight") == 1_708


def test_video_resource_retains_the_player_geometry_and_source_panel_height(
    page: Page, live_base_url: str
) -> None:
    goto(
        page,
        live_base_url,
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
        "resources/mit14_129s25_lec01_1080p_mp4/",
    )
    player = page.locator(".offline-video-player").bounding_box()
    assert player is not None
    assert player["width"] == 804 and player["height"] == 488
    poster = page.locator('[data-wb-media="disabled-video-poster"]')
    assert poster.count() == 1
    assert poster.evaluate("element => element.complete && element.naturalWidth > 0")
    assert page.evaluate("document.documentElement.scrollHeight") == 1_077


def test_get_started_uses_the_source_content_and_footer_boundaries(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/pages/get-started/")
    fragment = page.locator(".g3c-get-started .g3b-source-fragment").bounding_box()
    footer = page.locator(".generic-footer").bounding_box()
    assert fragment is not None and footer is not None
    assert fragment["y"] == pytest.approx(240, abs=0.1)
    assert fragment["height"] == pytest.approx(1_760, abs=0.1)
    assert footer["y"] == pytest.approx(2_016, abs=0.1)
    assert footer["height"] == pytest.approx(247, abs=0.1)
    assert page.evaluate("document.documentElement.scrollHeight") == 2_263


def test_newsletter_form_contains_all_fields_before_the_source_footer(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/newsletter/")
    form_container = page.locator("#mc_embed_signup").bounding_box()
    submit = page.locator('[data-wb-control="newsletter-submit"]').bounding_box()
    footer = page.locator(".generic-footer").bounding_box()
    assert form_container is not None and submit is not None and footer is not None
    assert form_container["y"] == pytest.approx(320, abs=0.1)
    assert form_container["height"] == pytest.approx(799, abs=0.1)
    assert submit["y"] + submit["height"] < footer["y"]
    assert footer["y"] == pytest.approx(1_119, abs=0.1)
    assert footer["height"] == pytest.approx(247, abs=0.1)
    assert page.evaluate("document.documentElement.scrollHeight") == 1_366


def test_adrian_story_more_cards_use_the_source_box_model_and_footer(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/stories/adrian-pastor/")
    cards = page.locator(".more-stories .item-wrapper")
    assert cards.count() == 4
    first = cards.first.bounding_box()
    last = cards.last.bounding_box()
    view_all = page.locator(".view-all-stories").bounding_box()
    footer = page.locator(".generic-footer").bounding_box()
    assert first is not None and last is not None and view_all is not None and footer is not None
    assert first["y"] == pytest.approx(451, abs=0.2)
    assert first["height"] == pytest.approx(507.7, abs=0.2)
    assert last["y"] == pytest.approx(2_022.2, abs=0.2)
    assert view_all["y"] == pytest.approx(2_545.9, abs=0.2)
    assert footer["y"] == pytest.approx(2_640.9, abs=0.2)
    assert page.evaluate("document.documentElement.scrollHeight") == 2_888


def test_home_carousels_advance_independently_and_previous_is_inverse(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/")
    initial = {
        name: component_text(page, name)
        for name in ("featured-courses", "new-courses", "stories")
    }
    page.locator('[data-wb-control="featured-next"]').click()
    page.wait_for_load_state("networkidle")
    assert "featured=second" in page.url
    featured_second = component_text(page, "featured-courses")
    assert featured_second != initial["featured-courses"]
    assert component_text(page, "new-courses") == initial["new-courses"]
    assert component_text(page, "stories") == initial["stories"]

    page.go_back(wait_until="networkidle")
    assert page.url == live_base_url + "/"
    assert component_text(page, "featured-courses") == initial["featured-courses"]
    page.go_forward(wait_until="networkidle")
    assert "featured=second" in page.url
    assert component_text(page, "featured-courses") == featured_second
    page.reload(wait_until="networkidle")
    assert component_text(page, "featured-courses") == featured_second

    page.locator('[data-wb-control="new-next"]').click()
    page.wait_for_load_state("networkidle")
    assert "featured=second" in page.url and "new=second" in page.url
    assert component_text(page, "featured-courses") == featured_second
    assert component_text(page, "new-courses") != initial["new-courses"]
    assert component_text(page, "stories") == initial["stories"]

    page.locator('[data-wb-control="featured-previous"]').click()
    page.wait_for_load_state("networkidle")
    assert component_text(page, "featured-courses") == initial["featured-courses"]
    assert component_text(page, "new-courses") != initial["new-courses"]

    goto(page, live_base_url, "/")
    page.locator('[data-wb-control="new-next"]').click()
    page.wait_for_load_state("networkidle")
    assert "new=second" in page.url
    assert component_text(page, "featured-courses") == initial["featured-courses"]
    assert component_text(page, "new-courses") != initial["new-courses"]
    assert component_text(page, "stories") == initial["stories"]

    goto(page, live_base_url, "/")
    page.locator('[data-wb-control="stories-next"]').click()
    page.wait_for_load_state("networkidle")
    assert "stories=second" in page.url
    assert component_text(page, "featured-courses") == initial["featured-courses"]
    assert component_text(page, "new-courses") == initial["new-courses"]
    assert component_text(page, "stories") != initial["stories"]

    goto(page, live_base_url, "/")
    page.locator('[data-wb-control="promo-previous"]').click()
    page.wait_for_load_state("networkidle")
    previous_title = page.locator(".home-promo-copy h2").inner_text()
    previous_url = page.url
    goto(page, live_base_url, "/")
    page.locator('[data-wb-control="promo-next"]').click()
    page.wait_for_load_state("networkidle")
    assert page.locator(".home-promo-copy h2").inner_text() != previous_title
    assert page.url != previous_url


def test_feedback_audit_derives_every_frozen_journey_from_observed_proofs() -> None:
    namespace = runpy.run_path(str(SITE_ROOT / "tools" / "audit_g4_interactions.py"))
    definitions = namespace["JOURNEY_PROOFS"]
    derive = namespace["derive_journey_results"]
    frozen = json.loads((SITE_ROOT / "scope" / "journeys.json").read_text(encoding="utf-8"))[
        "journeys"
    ]
    assert [row["journey_id"] for row in definitions] == [row["id"] for row in frozen]

    all_proofs = {proof for row in definitions for proof in row["proofs"]}
    passing = derive({proof: "pass" for proof in all_proofs})
    assert len(passing) == 10
    assert all(row["status"] == "pass" for row in passing)
    assert all(set(row["proofs"]) == set(row["proof_status"]) for row in passing)

    failing = derive({proof: "pass" for proof in all_proofs} | {"route-identity-closure": "fail"})
    affected = {row["journey_id"] for row in failing if row["status"] == "fail"}
    assert affected == {
        "course-material-navigation",
        "collection-story-information",
        "route-identity-closure",
    }

    incomplete = derive(
        {proof: "pass" for proof in all_proofs if proof != "presentation-asset-closure"}
    )
    assert next(
        row for row in incomplete if row["journey_id"] == "presentation-asset-closure"
    )["status"] == "not-executed-with-reason"


def test_home_default_stories_use_bounded_source_cards(
    page: Page, live_base_url: str
) -> None:
    goto(page, live_base_url, "/")
    stories = page.locator('[data-wb-component="stories"]')
    cards = stories.locator(".story-card")
    assert cards.count() == 3
    assert stories.locator(".read-full-story").count() == 3
    assert stories.locator('[data-wb-link="stories-index"]').count() == 1
    clipped_summaries = 0
    for index in range(cards.count()):
        box = cards.nth(index).bounding_box()
        assert box is not None
        assert 510 <= box["height"] <= 525
        summary = cards.nth(index).locator(".story-summary")
        assert summary.evaluate("node => node.clientHeight <= 120")
        clipped_summaries += int(
            summary.evaluate("node => node.scrollHeight > node.clientHeight")
        )
    assert clipped_summaries >= 1
    assert 4_450 <= page.evaluate("document.documentElement.scrollHeight") <= 4_650
