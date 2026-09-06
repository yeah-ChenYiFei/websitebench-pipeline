from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from app import DATA, DOWNLOADS, SITE_ROOT, app


client = TestClient(app)


class TagIndex(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[dict[str, str | None]] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(dict(attrs))


def index(html: str) -> TagIndex:
    result = TagIndex()
    result.feed(html)
    return result


def real_control(html: str, value: str) -> dict[str, str | None]:
    matches = [tag for tag in index(html).tags if tag.get("data-wb-control") == value and tag.get("class") != "recipe-proof"]
    assert matches, f"missing real control {value}"
    return matches[0]


ROUTE_CONTRACT = json.loads(
    (SITE_ROOT / "scope" / "business-contracts" / "route-state-contract.json").read_text(encoding="utf-8")
)
CHECKPOINT_PATHS = {
    row["checkpoint_id"]: row["path"]
    for row in ROUTE_CONTRACT["representative_acceptance_routes"]
}
CATALOG_STATES = {
    "catalog.second-batch": "second-batch",
    "catalog.math": "math",
    "catalog.math-undergraduate": "math-undergraduate",
    "catalog.course-number": "course-number",
    "catalog.empty": "empty",
    "catalog.error": "error",
    "catalog.retry-stale": "retry-stale",
    "catalog.reload-recovered": "reload-recovered",
    "catalog.resources": "resources",
}
CHECKPOINT_PATHS.update({
    checkpoint: f"/search/?state={state}"
    for checkpoint, state in CATALOG_STATES.items()
})
CHECKPOINT_PATHS["home.carousel-second-batches"] = "/?state=carousel-second-batches"
CHECKPOINT_PATHS["video.static-disabled"] = (
    "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
    "resources/mit14_129s25_lec01_1080p_mp4/"
)


def test_health_and_zero_remote_runtime_policy() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "site_id": "mit-opencourseware",
        "capture_id": "mit-opencourseware-20260905T070619Z",
        "remote_requests": 0,
    }
    for path in ("/", "/search/", "/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/"):
        html = client.get(path).text
        assert not re.search(r"(?:src|action)=[\"']https?://", html)
        assert "connect-src 'self'" in html


def test_home_and_carousel_are_real_local_states() -> None:
    default = client.get("/").text
    carousel = client.get("/?state=carousel-second-batches").text
    assert "Unlocking knowledge" in default
    assert "--red:#a31f34" in default
    assert 'data-wb-component="featured-courses"' in default
    assert 'data-wb-component="new-courses"' in default
    assert 'data-wb-component="stories"' in default
    assert "Introduction to Sustainable Energy" in default
    assert "Comedy" in carousel
    assert real_control(default, "featured-next")["href"] == "/?state=carousel-second-batches"
    assert real_control(carousel, "featured-previous")["href"] == "/?state=default"


def test_catalog_first_two_batches_and_local_data_boundary() -> None:
    first = client.get("/search/").text
    second = client.get("/search/?state=second-batch").text
    assert "2584 results" in first
    assert first.count('<article class="card">') == 10
    assert second.count('<article class="card">') == 20
    for course in DATA["catalog"]["courses"][:10]:
        assert course["title_link_text"] in first
    for course in DATA["catalog"]["courses"]:
        assert course["title_link_text"] in second
    assert second.count('href="/data-boundary/"') == 10
    assert real_control(second, "catalog-load-more")["href"] == "/search/?state=second-batch"


def test_catalog_filters_sort_tabs_and_checked_semantics() -> None:
    cases = {
        "math": ("199 results", ("catalog-math-filter",)),
        "math-undergraduate": ("110 results", ("catalog-math-filter", "catalog-undergraduate-filter")),
        "course-number": ("110 results", ("catalog-math-filter", "catalog-undergraduate-filter")),
    }
    for state, (total, checked) in cases.items():
        html = client.get(f"/search/?state={state}").text
        assert total in html
        for control in checked:
            assert "checked" in real_control(html, control)
    default = client.get("/search/").text
    resources = client.get("/search/?state=resources").text
    assert "checked" in real_control(default, "catalog-course-tab")
    assert "checked" not in real_control(default, "catalog-resource-tab")
    assert "10000 results" in resources
    assert "checked" in real_control(resources, "catalog-resource-tab")
    assert "checked" not in real_control(resources, "catalog-course-tab")
    assert "selected" in client.get("/search/?state=course-number").text


def test_catalog_loading_empty_error_stale_retry_and_reload_recovery() -> None:
    loading = client.get("/search/?state=loading").text
    empty = client.get("/search/?state=empty").text
    recovered = client.get("/search/?state=clear-recovered").text
    error = client.get("/search/?state=error").text
    stale = client.get("/search/?state=retry-stale").text
    reload_recovered = client.get("/search/?state=reload-recovered").text
    assert 'data-wb-component="catalog-loading"' in loading
    assert "No results match your search" in empty and "0 results" in empty
    assert real_control(empty, "catalog-empty-clear")["href"] == "/search/?state=clear-recovered"
    assert "2584 results" in recovered
    assert "Oops! Something went wrong." in error
    assert real_control(error, "catalog-retry")["href"] == "/search/?state=retry-stale"
    assert "Oops! Something went wrong." in stale
    assert real_control(stale, "catalog-retry")["href"] == "/search/?state=reload-recovered"
    assert "2584 results" in reload_recovered
    assert "0 results" in client.get("/search/?q=__no_results__&state=unknown").text
    assert "Oops! Something went wrong." in client.get("/search/?q=__force_error__&state=unknown").text


def test_all_g2a_6006_pages_are_local_and_identity_preserving() -> None:
    six006 = {path: record for path, record in DATA["pages"].items() if path.startswith("/courses/6-006-")}
    assert len(six006) == 15
    required = (
        "/courses/6-006-introduction-to-algorithms-fall-2011/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/calendar/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/binary-search-trees/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-notes/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/exams/",
        "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/",
    )
    assert set(required) <= set(six006)
    for path, record in six006.items():
        response = client.get(path)
        assert response.status_code == record["status"] == 200
        assert "MIT OpenCourseWare" in response.text
        assert str(record["title"]).split(" | ", 1)[0] in response.text
    assert 'data-wb-link="reading-deep"' in client.get(required[3]).text
    assert 'data-wb-component="resource-metadata"' in client.get(required[-1]).text


def test_exact_pdf_is_repeatable_and_source_runtime_are_ordinary_copies() -> None:
    record = min(DOWNLOADS.values(), key=lambda row: int(row["bytes"]))
    first = client.get(record["path"])
    second = client.get(record["path"])
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert len(first.content) == int(record["bytes"])
    assert hashlib.sha256(first.content).hexdigest() == record["sha256"]
    assert record["filename"] in first.headers["content-disposition"]
    head = client.head(record["path"])
    assert head.status_code == 200 and head.headers["content-length"] == str(record["bytes"])
    assert head.headers["x-content-sha256"] == record["sha256"]
    chunks = [SITE_ROOT / row["path"] for row in record["chunks"]]
    assert chunks
    assert sum(path.stat().st_size for path in chunks) == int(record["bytes"])
    assert all(not path.is_symlink() and path.stat().st_nlink == 1 for path in chunks)


def test_frozen_recipe_selector_and_expected_state_index_is_complete() -> None:
    assertions = DATA["assertions"]
    assert len(assertions) == 128
    cache: dict[str, list[dict[str, str | None]]] = {}
    parsed = 0
    for assertion in assertions:
        selector = assertion.get("selector")
        if not selector:
            continue
        checkpoint = assertion["checkpoint_id"]
        route = CHECKPOINT_PATHS[checkpoint]
        tags = cache.setdefault(route, index(client.get(route).text).tags)
        match = re.fullmatch(r"\[([a-z0-9-]+)=['\"]([^'\"]+)['\"]\]", selector)
        assert match, selector
        attribute, value = match.groups()
        candidates = [tag for tag in tags if tag.get(attribute) == value]
        assert candidates, f"{checkpoint}: {selector}"
        if assertion.get("expected_state") == "checked":
            assert any("checked" in tag for tag in candidates)
        if assertion.get("expected_state") == "disabled":
            assert any("disabled" in tag for tag in candidates)
        if assertion.get("expected_state") == "enabled":
            assert any("disabled" not in tag for tag in candidates)
        if assertion.get("expected_href"):
            assert any(tag.get("href") == assertion["expected_href"] for tag in candidates)
        parsed += 1
    assert parsed == sum(bool(assertion.get("selector")) for assertion in assertions) == 83
    assert sum(bool(assertion.get("expected_href")) for assertion in assertions) == 28


def test_boundaries_and_hard_404_recovery_are_local() -> None:
    external = client.get("/external-boundary/?url=https://accessibility.mit.edu/")
    data = client.get("/data-boundary/")
    missing = client.get("/not-in-scope")
    assert external.status_code == data.status_code == 200
    assert 'data-wb-component="external-boundary"' in external.text
    assert 'data-wb-capability="data-boundary"' in data.text
    assert missing.status_code == 404
    assert "Page Not Found | MIT OpenCourseWare" in missing.text
    assert 'href="/"' in missing.text


def test_functional_data_scope_denominators_are_closed_without_acceptance_claim() -> None:
    assert DATA["phase"] in {
        "g2c2-functional-data-scope-closed",
        "g3a-two-p0-visual-slices-active",
        "g3b-content-addendum-732-of-732",
        "g3b-route-content-closed",
        "g4-semantics-closed",
    }
    assert "final_denominator_todo" not in DATA
    status = DATA["final_denominator_status"]
    assert status == {
        "status": "g4-candidate-frozen-for-g5",
        "route_instances": 732,
        "route_families": 11,
        "representative_routes": 29,
        "diagnostic_checkpoints": 40,
        "logical_downloads": 480,
        "unique_download_hashes": 478,
        "download_bytes": 1551223348,
        "presentation_assets": 288,
        "presentation_asset_bytes": 50418009,
        "unavailable_assets": 9,
        "formal_visual_checkpoints": 35,
        "semantic_only_visual_input_gaps": 5,
        "controls": 30,
        "local_capabilities": 7,
        "p0_p1_journeys": 10,
        "supplementary_course_archives": 1,
        "supplementary_course_archive_bytes": 173887153,
        "runtime_remote_requests": 0,
        "deferred": [
            "five-semantic-only-visual-input-gaps",
            "blind-evaluation",
            "formal-acceptance",
        ],
    }
