from __future__ import annotations

import re
from html import unescape

from fastapi.testclient import TestClient

from app import PAGES, app


client = TestClient(app)
SIX006 = "/courses/6-006-introduction-to-algorithms-fall-2011/"
VIDEO_GALLERY = (
    "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
    "video_galleries/video-lectures/"
)


def test_every_frozen_route_exposes_its_first_captured_heading() -> None:
    missing: list[tuple[str, str]] = []
    for path, record in PAGES.items():
        headings = record.get("headings", [])
        if not headings:
            continue
        expected = " ".join(str(headings[0]["text"]).split())
        text = unescape(re.sub(r"<[^>]+>", " ", client.get(path).text))
        text = " ".join(text.split())
        if expected not in text:
            missing.append((path, expected))
    assert missing == []


def test_course_overview_video_gallery_edge_matches_frozen_link_contract() -> None:
    html = client.get(SIX006).text
    assert f'data-wb-link="video-gallery" href="{VIDEO_GALLERY}"' in html


def test_catalog_error_and_reload_recovery_keep_distinct_frozen_states() -> None:
    error = client.get("/search/?state=error").text
    assert 'data-wb-control="catalog-retry"' in error
    assert '<a class="cta" data-wb-control="catalog-load-more"' not in error

    recovered = client.get("/search/?state=reload-recovered").text
    for title in ("The American Novel", "Springfield Studio", "Economic History"):
        assert title in recovered
    assert "Research Design for Policy Analysis and Planning" not in recovered


def test_syllabus_and_problem_set_have_specific_headings_sidebars_and_preview() -> None:
    syllabus = client.get(SIX006 + "pages/syllabus/").text
    assert '<h2 class="course-page-title">Syllabus</h2>' in syllabus
    assert 'data-wb-component="course-info-sidebar"' in syllabus
    assert "Prerequisites" in syllabus

    problem = client.get(SIX006 + "resources/mit6_006f11_ps1/").text
    assert 'data-wb-component="resource-breadcrumb">Assignments' in problem
    assert '<h2 class="course-page-title">Problem Set 1</h2>' in problem
    assert 'data-wb-component="resource-preview"' in problem
    assert 'data-wb-component="course-info-sidebar"' in problem
    assert "Resource metadata and attachment" not in problem
    assert 'data-wb-control="resource-download"' in problem


def test_download_keeps_six_source_rows_and_detailed_course_info() -> None:
    html = client.get(SIX006 + "download/").text
    for number in range(1, 7):
        assert f"Lecture {number}:" in html
    assert 'data-wb-component="course-info-sidebar"' in html
    assert "Learning Resource Types" in html


def test_newsletter_keeps_one_complete_form_and_non_overlapping_shell_contract() -> None:
    html = client.get("/newsletter/").text
    assert len(re.findall(r'<form\b[^>]*data-wb-component="newsletter-form"', html)) == 1
    assert "Educational Role" in html
    assert 'class="right" id="global-navigation"' in html
    assert "ABOUT OCW" in html and "HELP &amp; FAQS" in html and "CONTACT US" in html
    assert ".newsletter-authorized-stylesheet.general-shell-page main" in html


def test_assignments_preserves_the_complete_four_column_source_table() -> None:
    html = client.get(SIX006 + "pages/assignments/").text
    table = html.split('data-wb-component="assignments-table">', 1)[1].split("</table>", 1)[0]
    assert table.count("<tr>") == 8
    assert table.count("<td>") == 28
    for topic in (
        "Asymptotic complexity, recurrence relations, peak finding",
        "Fractal rendering, digital circuit simulation",
        "Range queries, digital circuit layout",
        "Hash functions, Python dictionaries, matching DNA sequences",
        "The Knight’s Shield, RSA public key encryption, image decryption",
        "Social networks, Rubik’s Cube, Dijkstra",
        "Seam carving, stock purchasing and knapsack",
    ):
        assert topic in table
    assert 'href="/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/"' in table
    assert 'href="/external-boundary/?url=https%3A%2F%2Fdx.doi.org%2F10.1145%2F1276377.1276390"' in table
