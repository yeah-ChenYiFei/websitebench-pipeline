from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi.testclient import TestClient

from app import (
    CONTENT_INDEX,
    CONTENT_ROUTES,
    DATA,
    G3B_CONTENT_ASSETS,
    G3B_CONTENT_URL_MAP,
    PAGES,
    SITE_ROOT,
    app,
    family_body,
    home_course_records,
)


client = TestClient(app)
AGGREGATE = json.loads(
    (SITE_ROOT / "source-current" / "g3b-content" / "report.json").read_text(encoding="utf-8")
)
ASSET_ADDENDUM = json.loads(
    (SITE_ROOT / "source-assets" / "g3b-content-asset-addendum.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads((SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8"))
HOME_PROJECTION = json.loads(
    (SITE_ROOT / "source-current" / "g3b-home-content-projection-v2" / "report.json").read_text(encoding="utf-8")
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Balanced(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(tag)
        else:
            self.stack.pop()


class LinkIndex(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            self.links.append(dict(attrs))


def test_g3b_addendum_closes_all_732_routes_and_exact_family_denominators() -> None:
    expected = {
        "home": 1,
        "catalog-search": 1,
        "collection": 10,
        "course-overview": 34,
        "course-section-or-deep-link": 219,
        "resource-detail-or-index": 418,
        "course-download": 26,
        "story-index": 1,
        "story-detail": 13,
        "site-information-or-boundary": 8,
        "video-gallery": 1,
    }
    assert CONTENT_INDEX["phase"] == "closed"
    assert len(CONTENT_ROUTES) == len(PAGES) == 732
    assert set(CONTENT_ROUTES) == set(PAGES)
    assert Counter(row["family"] for row in CONTENT_ROUTES.values()) == expected
    assert AGGREGATE["closure"] == {
        "status": "closed",
        "routes_expected": 732,
        "routes_captured": 732,
        "route_failures": 0,
        "http_200": 732,
        "families": expected,
    }
    assert len(CONTENT_INDEX["batches"]) == 4
    assert all(row["routes"] == 183 and row["status"] == "closed" for row in CONTENT_INDEX["batches"])
    assert DATA["phase"] == "g4-semantics-closed"
    assert DATA["g3b_content"]["formal_acceptance_status"] == "not-run"
    assert DATA["g3b_content"]["visual_status"].startswith("deferred-except")


def test_all_runtime_files_are_canonical_hash_bound_balanced_and_portable() -> None:
    fallback_paths: list[str] = []
    for path, row in CONTENT_ROUTES.items():
        runtime = SITE_ROOT / row["runtime_path"]
        assert str(row["raw_path"]).startswith("source-current/g3b-content/batch-")
        assert str(row["runtime_path"]).startswith("runtime-content/")
        assert re.fullmatch(r"[0-9a-f]{64}", str(row["raw_sha256"])), path
        assert runtime.is_file(), path
        assert sha(runtime) == row["runtime_sha256"], path
        markup = runtime.read_text(encoding="utf-8")
        assert f'data-wb-g3b-content="{path}"' in markup
        assert not re.search(r"(?:src|srcset|action|poster)=[\"']https?://", markup, re.I), path
        assert not re.search(r"<(?:script|iframe|audio|video|source)\b", markup, re.I), path
        assert "<style" not in markup.lower(), path
        assert not any(token in markup for token in (".material-icons {", "@font-face {", "--bs-blue:")), path
        parsed = Balanced()
        parsed.feed(markup)
        assert not parsed.stack and not parsed.errors, path
        if row["selector_fallback"]:
            fallback_paths.append(path)
    assert sorted(fallback_paths) == ["/external-resources/", "/notifications/", "/staff/", "/websites/"]
    assert AGGREGATE["content"]["fallback_note"].startswith("The four frozen legacy boundary URLs")


def test_every_frozen_same_origin_href_alias_rewrites_locally_before_boundary() -> None:
    aliases: dict[str, str] = {}
    for path, page in PAGES.items():
        source_path = urlsplit(page["source_url"]).path.rstrip("/") or "/"
        aliases[source_path] = path
        aliases[source_path + "/" if source_path != "/" else "/"] = path
    for route, row in CONTENT_ROUTES.items():
        parsed = LinkIndex()
        parsed.feed((SITE_ROOT / row["runtime_path"]).read_text(encoding="utf-8"))
        for link in parsed.links:
            source = str(link.get("data-wb-source-href") or "")
            split = urlsplit(source)
            if split.hostname == "ocw.mit.edu" and split.path in aliases:
                href = unquote(str(link.get("href") or ""))
                if href.startswith("#"):
                    continue
                assert href.startswith(aliases[split.path]), (route, source, href)
                assert not href.startswith("/data-boundary/"), (route, source, href)
    home_source = (SITE_ROOT / CONTENT_ROUTES["/"]["runtime_path"]).read_text(encoding="utf-8")
    assert all(f'href="{path}"' in home_source for path in ("/about/", "/pages/get-started/", "/educator/"))
    ps1 = CONTENT_ROUTES["/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/"]
    assert DATA["pdf"]["path"] in (SITE_ROOT / ps1["runtime_path"]).read_text(encoding="utf-8")


def test_source_selector_and_text_bindings_cover_sample_20_10_and_every_family() -> None:
    overviews = sorted(path for path, row in CONTENT_ROUTES.items() if row["family"] == "course-overview")[:20]
    collections = sorted(path for path, row in CONTENT_ROUTES.items() if row["family"] == "collection")[:10]
    family_sample = [
        next(path for path, row in CONTENT_ROUTES.items() if row["family"] == family)
        for family in sorted({row["family"] for row in CONTENT_ROUTES.values()})
    ]
    paths = sorted(set([*overviews, *collections, *family_sample]))
    assert len(overviews) == 20 and len(collections) == 10 and len(paths) >= 30
    for path in paths:
        row = CONTENT_ROUTES[path]
        assert row["content_selector"], path
        assert isinstance(row["selector_fallback"], bool), path
        assert row["source_visible_text_bytes"] >= 0, path
        assert re.fullmatch(r"[0-9a-f]{64}", row["source_visible_text_sha256"]), path
        markup = (SITE_ROOT / row["runtime_path"]).read_text(encoding="utf-8")
        assert f'data-wb-g3b-content="{path}"' in markup, path


def test_route_families_render_their_own_full_source_fragments_without_generic_substitution() -> None:
    exceptions = {
        "/": "preserve-g3a-home-custom",
        "/search/": "preserve-frozen-search-state-renderer",
        "/courses/6-006-introduction-to-algorithms-fall-2011/": "preserve-g3a-authentic-6.006-overview",
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/video_galleries/video-lectures/": "render-sanitized-g3b-fragment",
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/resources/mit14_129s25_lec01_1080p_mp4/": "render-sanitized-g3b-fragment",
    }
    forbidden = (
        "Course materials, instructors, and topics from MIT OpenCourseWare.",
        "Download the captured course archive for offline use.",
        "Explore this collection</h2><ul class=\"evidence-links\"",
    )
    for path, row in CONTENT_ROUTES.items():
        assert row["render_policy"] == exceptions.get(path, "render-sanitized-g3b-fragment")
        if path in exceptions:
            continue
        body = family_body(PAGES[path])
        assert f'data-wb-g3b-content="{path}"' in body, path
        assert not any(value in body for value in forbidden), path
        if row["runtime_visible_text_bytes"] < 20:
            assert path == "/courses/22-081j-introduction-to-sustainable-energy-fall-2010/external-resources/"
            assert "This frozen source route returned an empty content area" in body
    home = client.get("/").text
    assert 'data-wb-g3b-content="/"' in home
    assert not any(value in home for value in forbidden)


def test_six006_full_facts_tables_attachments_and_expand_control_are_preserved() -> None:
    facts = {
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/": (
            "Lectures: 2 sessions / week, 1 hour / session",
            "analysis techniques for these problems",
        ),
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/calendar/": (
            "Algorithmic thinking, peak finding",
            "Problem set 1 due",
        ),
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/": (
            "Introduction to Algorithms",
            "Binary Search Trees",
        ),
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/": (
            "Gradetacular",
            "Problem Set 1 Code",
        ),
        "/courses/6-006-introduction-to-algorithms-fall-2011/pages/exams/": (
            "Quiz 1 solutions",
            "Final exam solutions",
        ),
        "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/": (
            "This resource contains information about ps1.",
            "170 kB",
        ),
    }
    for path, expected in facts.items():
        markup = client.get(path).text
        assert all(value in markup for value in expected), path
    ps1 = client.get(DATA["pdf"]["path"])
    assert ps1.status_code == 200
    assert hashlib.sha256(ps1.content).hexdigest() == ps1.headers["x-content-sha256"]

    overview = client.get("/courses/6-006-introduction-to-algorithms-fall-2011/").text
    assert 'data-wb-control="course-description-expand"' in overview
    assert 'aria-expanded="false"' in overview
    assert '<span id="course-description-more" hidden>analysis techniques for these problems.</span>' in overview
    assert (
        'data-wb-link="video-gallery" '
        'href="/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/'
        'video_galleries/video-lectures/"'
    ) in overview
    assert 'data-wb-link="course-recitation-videos" href="/data-boundary/"' in overview


def test_story_body_is_entity_specific_and_home_search_keep_their_frozen_renderers() -> None:
    adrian = client.get("/stories/adrian-pastor/").text
    assert "Independent Learner | Peru" in adrian
    assert "Recent high school graduate Adrian Pastor" in adrian
    assert "Gaining confidence and skill with MIT Open Learning" in adrian
    other = next(path for path, row in PAGES.items() if row["family"] == "story-detail" and path != "/stories/adrian-pastor/")
    assert CONTENT_ROUTES[other]["runtime_visible_text_sha256"] != CONTENT_ROUTES["/stories/adrian-pastor/"]["runtime_visible_text_sha256"]
    assert 'data-wb-component="home-hero"' in client.get("/").text
    assert 'data-wb-component="catalog-results"' in client.get("/search/").text


def test_home_default_and_second_batch_use_only_raw_projected_card_story_and_promo_facts() -> None:
    closure = HOME_PROJECTION["closure"]
    assert closure == {
        "status": "closed",
        "course_card_instances": 16,
        "distinct_course_identities": 16,
        "complete_course_archives": 15,
        "story_cards": 13,
        "promotions": 4,
    }
    assert HOME_PROJECTION["generic_substitution"] is False
    assert HOME_PROJECTION["source_raw_path"] == CONTENT_ROUTES["/"]["raw_path"]
    assert HOME_PROJECTION["source_raw_sha256"] == CONTENT_ROUTES["/"]["raw_sha256"]
    courses = HOME_PROJECTION["courses"]
    stories = HOME_PROJECTION["stories"]
    assert len(courses) == 16 and len(stories) == 13
    assert HOME_PROJECTION["story_batches"] == {
        "default": ["/stories/adrian-pastor/", "/stories/john-della-costa/", "/stories/freesia-gaul/"],
        "carousel-second-batches": ["/stories/omar-alshehri/", "/stories/gustavo-barboza/", "/stories/sok-danica/"],
    }
    assert HOME_PROJECTION["promotion_states"] == {"default": 0, "carousel-second-batches": 1}
    assert [row["title"] for row in HOME_PROJECTION["promotions"]] == [
        'MIT Learn: "a whole new front door to the Institute"',
        "MIT OpenCourseWare To Go",
        "Chalk Radio: a podcast about inspired teaching at MIT",
        "Come invent with us!",
    ]
    featured, new = home_course_records()
    shown = {
        "default": [*featured[:4], *new[:4]],
        "carousel-second-batches": [*featured[4:8], *new[4:8]],
    }
    for state, records in shown.items():
        markup = client.get("/" if state == "default" else "/?state=carousel-second-batches").text
        assert "Course materials, instructors, and topics from MIT OpenCourseWare." not in markup
        assert "Thank you to the organizations that sustain open education." not in markup
        for record in records:
            detail = courses[record["path"]]
            assert escape(detail["title"]) in markup
            assert escape(detail["level"]) in markup
            assert escape(detail["instructors"]) in markup
            assert escape(detail["topics"]) in markup
        story_grid_match = re.search(r'<div class="story-grid">(.*?)</div>', markup, re.S)
        assert story_grid_match
        story_grid = story_grid_match.group(1)
        expected_story_paths = HOME_PROJECTION["story_batches"][state]
        other_state = "default" if state == "carousel-second-batches" else "carousel-second-batches"
        for path in expected_story_paths:
            detail = stories[path]
            assert f'href="{path}"' in story_grid
            assert escape(detail["name"]) in markup
            assert escape(detail["occupation"]) in markup
            assert escape(detail["location"]) in markup
            assert escape(detail["teaser"]) in markup
        for path in HOME_PROJECTION["story_batches"][other_state]:
            assert f'href="{path}"' not in story_grid
        promo = HOME_PROJECTION["promotions"][HOME_PROJECTION["promotion_states"][state]]
        other_promo = HOME_PROJECTION["promotions"][HOME_PROJECTION["promotion_states"][other_state]]
        assert escape(promo["title"]) in markup
        assert escape(promo["subtitle"]) in markup
        assert f'href="{promo["source_url"]}"' in markup
        assert escape(promo["cta_text"]) in markup
        assert f'data-wb-asset-source="{promo["image_source_url"]}"' in markup
        assert escape(other_promo["title"]) not in markup
        assert f'data-wb-carousel-state="{state}"' in markup
        assert not re.search(r"(?:src|action|poster)=[\"']https?://", markup, re.I)


def test_40_new_content_assets_are_exact_distinct_schema_valid_local_copies() -> None:
    assets = ASSET_ADDENDUM["assets"]
    assert len(assets) == len(G3B_CONTENT_ASSETS) == len(G3B_CONTENT_URL_MAP) == 40
    manifest_by_id = {row["id"]: row for row in MANIFEST["assets"]}
    for row in assets:
        source = SITE_ROOT / row["source_path"]
        runtime = SITE_ROOT / row["runtime_path"]
        assert source.is_file() and runtime.is_file()
        assert not source.is_symlink() and not runtime.is_symlink()
        assert not os.path.samefile(source, runtime)
        assert source.stat().st_ino != runtime.stat().st_ino
        assert source.stat().st_nlink == runtime.stat().st_nlink == 1
        assert source.stat().st_size == runtime.stat().st_size == row["bytes"]
        assert sha(source) == sha(runtime) == row["sha256"]
        strict = manifest_by_id[row["id"]]
        assert strict["evidence_kind"] == "current-direct"
        assert not ({"captured_at", "final_url", "http_status"} & set(strict))
        response = client.get(G3B_CONTENT_URL_MAP[row["source_url"]])
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
        assert response.headers["x-content-sha256"] == row["sha256"]
    assert len(ASSET_ADDENDUM["unavailable"]) == 4
    assert all(row["status"] == "source-http-error" and row["http_status"] == 404 for row in ASSET_ADDENDUM["unavailable"].values())


def test_scope_is_frozen_with_truthful_visual_and_semantic_only_denominators() -> None:
    checkpoints = json.loads((SITE_ROOT / "scope" / "checkpoints.json").read_text(encoding="utf-8"))
    visual = {row["id"] for row in checkpoints["checkpoints"] if "visual_contract" in row}
    ineligible = {
        row["id"] for row in checkpoints["checkpoints"] if row["acceptance_eligible"] is False
    }
    assert checkpoints["status"] == "frozen"
    assert len(visual) == 35
    assert visual == {
        row["id"] for row in checkpoints["checkpoints"] if row["acceptance_eligible"] is True
    }
    assert ineligible == {
        "source-legacy-boundary.default",
        "external-boundary.default",
        "data-boundary.default",
        "not-found.default",
        "home.carousel-second-batches",
    }
    assert all(
        row.get("visual_unavailable_reason")
        for row in checkpoints["checkpoints"]
        if row["id"] in ineligible
    )
