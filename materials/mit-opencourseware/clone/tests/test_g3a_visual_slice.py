from __future__ import annotations

import hashlib
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import ASSET_URL_MAP, G3_VISUAL_URL_MAP, SITE_ROOT, app


client = TestClient(app)
ADDENDUM = json.loads(
    (SITE_ROOT / "source-assets" / "g3-visual-asset-addendum.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads(
    (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
)
EXPECTED = {
    "https://ocw.mit.edu/images/homepage_hero.jpg": (
        "2709ed33a5dc304c789d339774bc24745d423459e624b95d654276684953181f",
        129_494,
        (1440, 500),
    ),
    "https://ocw.mit.edu/images/homepage_bg.png": (
        "c27dd71e2d43b3aa5badb85339718fb5f5caa50e9c5c68628456bb93c483f6d2",
        408_270,
        (1442, 4044),
    ),
    (
        "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/"
        "1075c5ac06ae4c2cea8c89e9772da78a_6-006f11.jpg"
    ): (
        "d8807e078b8b1a4ad53d395409cf40462434c130809436941957d4cd74c3bc37",
        10_147,
        (320, 240),
    ),
}


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.rows.append((tag, dict(attrs)))


def tags(markup: str) -> list[tuple[str, dict[str, str | None]]]:
    parsed = Tags()
    parsed.feed(markup)
    return parsed.rows


def test_three_g3a_assets_are_provenance_rich_distinct_exact_copies() -> None:
    assert ADDENDUM["schema_version"] == "mit-ocw.g3-visual-asset-addendum.v1"
    assert ADDENDUM["does_not_modify_g1_evidence"] is True
    assert len(ADDENDUM["assets"]) == 3
    assert len(MANIFEST["assets"]) >= 234
    assert len([row for row in MANIFEST["assets"] if row["id"].startswith("g3a-")]) == 3
    addendum_by_url = {row["source_url"]: row for row in ADDENDUM["assets"]}
    manifest_g3a = {row["source_url"]: row for row in MANIFEST["assets"] if row["id"].startswith("g3a-")}
    assert set(addendum_by_url) == set(manifest_g3a) == set(EXPECTED)
    assert sum(row["bytes"] for row in addendum_by_url.values()) == 547_911

    for source_url, (expected_sha, expected_bytes, expected_dimensions) in EXPECTED.items():
        row = addendum_by_url[source_url]
        source = SITE_ROOT / row["source_path"]
        runtime = SITE_ROOT / row["runtime_path"]
        assert source.is_file() and runtime.is_file()
        assert not source.is_symlink() and not runtime.is_symlink()
        assert not os.path.samefile(source, runtime)
        assert source.stat().st_ino != runtime.stat().st_ino
        assert source.stat().st_nlink == runtime.stat().st_nlink == 1
        assert source.stat().st_size == runtime.stat().st_size == expected_bytes
        assert sha256(source) == sha256(runtime) == row["sha256"] == expected_sha
        with Image.open(source) as image:
            assert image.size == expected_dimensions
        assert manifest_g3a[source_url] == {
            key: value
            for key, value in row.items()
            if key not in {"input_path", "source_html_sha256", "source_html_sha256_prefix"}
        }

    assert addendum_by_url["https://ocw.mit.edu/images/homepage_hero.jpg"][
        "source_html_sha256_prefix"
    ] == "71c63a"
    course = addendum_by_url[next(url for url in EXPECTED if "6-006f11.jpg" in url)]
    assert course["source_html_sha256"] == (
        "35cb2acd33505d5bbdea39837ee0348971dc5f68af74d21daa895eea944f1c74"
    )
    assert course["referenced_by"] == ["course-overview.default"]


def test_g3a_assets_are_served_locally_with_exact_hashes() -> None:
    assert set(G3_VISUAL_URL_MAP) == set(EXPECTED)
    assert not (set(G3_VISUAL_URL_MAP) & set(ASSET_URL_MAP))
    for source_url, local_url in G3_VISUAL_URL_MAP.items():
        expected_sha, expected_bytes, _dimensions = EXPECTED[source_url]
        assert local_url.startswith("/g3a-visual-assets/")
        response = client.get(local_url)
        assert response.status_code == 200
        assert len(response.content) == expected_bytes
        assert hashlib.sha256(response.content).hexdigest() == expected_sha
        assert response.headers["x-content-sha256"] == expected_sha


def test_home_and_course_shells_use_exact_local_visual_assets() -> None:
    home = client.get("/").text
    assert 'class="home home-default home-shell-page"' in home
    assert 'data-wb-component="home-hero"' in home
    assert G3_VISUAL_URL_MAP["https://ocw.mit.edu/images/homepage_hero.jpg"] in home
    assert G3_VISUAL_URL_MAP["https://ocw.mit.edu/images/homepage_bg.png"] in home
    assert ".home-shell-page #desktop-header .search-icon{display:none!important}" in home
    assert ".home-mission h1{font:700 22.4px/40px Helvetica,Arial,sans-serif!important}" in home
    assert "color:#fff!important" in home

    course_url = next(url for url in EXPECTED if "6-006f11.jpg" in url)
    course = client.get("/courses/6-006-introduction-to-algorithms-fall-2011/").text
    assert 'class="frozen course-overview course-root course-shell-page"' in course
    assert 'class="course-banner"' in course
    assert 'class="course-stage"' in course
    assert 'class="course-panel course-side"' in course
    assert 'class="course-panel course-center"' in course
    assert 'class="course-panel course-right"' in course
    assert G3_VISUAL_URL_MAP[course_url] in course
    assert f'data-wb-asset-source="{course_url}"' in course
    assert "grid-template-columns:214px minmax(0,798px) 332px" in course
    assert "height:80px!important;background:#000" in course
    assert "height:120px;background:#126f9a" in course


def test_two_source_current_rasters_are_content_addressed_portable_viewports() -> None:
    rows = {row["checkpoint_id"]: row for row in ADDENDUM["source_current_rasters"]}
    assert set(rows) == {"home.default", "course-overview.default"}
    names = {
        "home.default": "home-default-1440x900.png",
        "course-overview.default": "course-overview-default-1440x900.png",
    }
    for checkpoint_id, filename in names.items():
        source_current = SITE_ROOT / rows[checkpoint_id]["source_current"]
        assert source_current.is_file()
        assert not source_current.is_symlink()
        assert source_current.stat().st_nlink == 1
        assert sha256(source_current) == rows[checkpoint_id]["sha256"]
        assert rows[checkpoint_id]["source_capture"].startswith(
            "artifacts/mit-opencourseware/mit-opencourseware-20260903T032020Z/"
        )
        with Image.open(source_current) as source_image:
            assert source_image.size == (1440, 900)


def test_historical_g3a_viewports_are_superseded_by_current_capture_viewports() -> None:
    checkpoints = json.loads(
        (SITE_ROOT / "scope" / "checkpoints.json").read_text(encoding="utf-8")
    )
    by_id = {row["id"]: row for row in checkpoints["checkpoints"]}
    for row in ADDENDUM["source_current_rasters"]:
        visual = by_id[row["checkpoint_id"]]["visual_contract"]
        assert visual["source_artifact_path"] != row["source_current"]
        assert visual["source_artifact_path"].startswith("source-current/g3c/fullpage-v")
        assert visual["source_artifact_path"].endswith("-1440xfull.png")
        assert visual["viewport"] == {"width": 1440, "height": 900}
        assert visual["comparison_region"]["x"] == 0
        assert visual["comparison_region"]["y"] == 0
        assert visual["comparison_region"]["width"] == 1440
        assert visual["comparison_region"]["height"] == 900
        assert visual["metric"] == "pixel-mae-similarity-v1"
        assert visual["threshold"] == visual["full_page_threshold"] == 0.94


def test_g3a_pages_and_local_stylesheets_have_no_remote_fetch_surfaces() -> None:
    for path in ("/", "/courses/6-006-introduction-to-algorithms-fall-2011/"):
        markup = client.get(path).text
        assert not re.search(r"(?:src|action|poster)=[\"']https?://", markup, flags=re.I)
        assert not re.search(r"<link\b[^>]*href=[\"']https?://", markup, flags=re.I)
        assert not re.search(r"<(?:iframe|video|audio|source)\b", markup, flags=re.I)
        stylesheet_urls = [
            str(attrs["href"])
            for tag, attrs in tags(markup)
            if tag == "link" and attrs.get("rel") == "stylesheet"
        ]
        assert stylesheet_urls and all(url.startswith("/presentation-assets/") for url in stylesheet_urls)
        for stylesheet_url in stylesheet_urls:
            css = client.get(stylesheet_url)
            assert css.status_code == 200
            assert not re.search(rb"url\(\s*[\"']?https?://", css.content, flags=re.I)
