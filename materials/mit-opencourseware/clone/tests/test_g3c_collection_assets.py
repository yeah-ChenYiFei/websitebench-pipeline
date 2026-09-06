from __future__ import annotations

import hashlib
import json
import os

from fastapi.testclient import TestClient

from app import G3C_COLLECTION_URL_MAP, SITE_ROOT, app


client = TestClient(app)
ADDENDUM = json.loads(
    (SITE_ROOT / "source-assets" / "g3c-collection-asset-addendum.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads(
    (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
)


def test_g3c_collection_assets_are_exact_distinct_local_copies() -> None:
    assert ADDENDUM["schema_version"] == "mit-ocw.g3c-collection-asset-addendum.v1"
    assert ADDENDUM["does_not_modify_g1_or_g3b_evidence"] is True
    assert len(ADDENDUM["assets"]) == len(G3C_COLLECTION_URL_MAP) == 4
    assert sum(int(row["bytes"]) for row in ADDENDUM["assets"]) == 96_130
    manifest_by_url = {row["source_url"]: row for row in MANIFEST["assets"]}
    assert set(G3C_COLLECTION_URL_MAP) == {row["source_url"] for row in ADDENDUM["assets"]}
    for row in ADDENDUM["assets"]:
        source = SITE_ROOT / row["source_path"]
        runtime = SITE_ROOT / row["runtime_path"]
        assert source.is_file() and runtime.is_file()
        assert not source.is_symlink() and not runtime.is_symlink()
        assert not os.path.samefile(source, runtime)
        assert source.stat().st_ino != runtime.stat().st_ino
        assert source.stat().st_nlink == runtime.stat().st_nlink == 1
        assert source.read_bytes() == runtime.read_bytes()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == row["sha256"]
        strict = {
            key: value
            for key, value in row.items()
            if key not in {
                "course_code", "requested_url", "final_url", "http_status",
                "response_content_type", "declared_by_raw_path", "declared_by_raw_sha256",
            }
        }
        assert strict["evidence_kind"] == "current-direct-g3c-addendum"
        strict["evidence_kind"] = "current-direct"
        assert manifest_by_url[row["source_url"]] == strict


def test_collection_uses_only_the_four_exact_local_images() -> None:
    html = client.get("/collections/introductory-programming/").text
    assert html.count('data-wb-media="collection-course-image"') == 4
    assert "Image not retained" not in html
    for source_url, local_url in G3C_COLLECTION_URL_MAP.items():
        assert source_url not in html
        assert f'src="{local_url}"' in html
        response = client.get(local_url)
        row = next(item for item in ADDENDUM["assets"] if item["source_url"] == source_url)
        assert response.status_code == 200
        assert len(response.content) == row["bytes"]
        assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
        assert response.headers["x-content-sha256"] == row["sha256"]
