from __future__ import annotations

import hashlib
import json
import os
import re

from fastapi.testclient import TestClient

from app import G3C_CATALOG_ASSETS, G3C_CATALOG_URL_MAP, SITE_ROOT, app


client = TestClient(app)
ADDENDUM = json.loads(
    (SITE_ROOT / "source-assets" / "g3c-catalog-asset-addendum.json").read_text(encoding="utf-8")
)
MATH_ADDENDUM = json.loads(
    (SITE_ROOT / "source-assets" / "g3c-catalog-math-asset-addendum.json").read_text(
        encoding="utf-8"
    )
)
MANIFEST = json.loads((SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8"))


def sha(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_g3c_catalog_addendum_preserves_278_and_adds_six_exact_distinct_copies() -> None:
    assert ADDENDUM["schema_version"] == "mit-ocw.g3c-catalog-asset-addendum.v1"
    assert ADDENDUM["does_not_modify_prior_278_manifest_records"] is True
    assert ADDENDUM["request_policy"]["other_requests"] == 0
    assert len(ADDENDUM["request_policy"]["allowed_urls"]) == 6
    assert len(ADDENDUM["assets"]) == 6
    assert len(G3C_CATALOG_ASSETS) == len(G3C_CATALOG_URL_MAP) == 10
    assert sum(int(row["bytes"]) for row in ADDENDUM["assets"]) == 77_723
    assert len(MANIFEST["assets"]) == 288
    historical_prior = json.loads(json.dumps(MANIFEST["assets"][:278]))
    for row in historical_prior[274:278]:
        assert row["evidence_kind"] == "current-direct"
        row["evidence_kind"] = "current-direct-g3c-addendum"
    assert canonical_sha(historical_prior) == ADDENDUM["prior_manifest_assets_sha256"]
    assert {row["source_url"] for row in ADDENDUM["assets"]} <= set(G3C_CATALOG_URL_MAP)

    manifest_by_url = {row["source_url"]: row for row in MANIFEST["assets"]}
    addendum_only = {
        "state", "card_index", "course_title", "requested_url", "final_url", "http_status",
        "response_content_type", "observed_in", "observation_sha256",
    }
    for row in ADDENDUM["assets"]:
        assert row["requested_url"] == row["source_url"] == row["final_url"]
        assert row["http_status"] == 200
        assert row["response_content_type"] == row["mime_type"] == "image/jpeg"
        assert row["dimensions"]["width"] == 320
        source = SITE_ROOT / row["source_path"]
        runtime = SITE_ROOT / row["runtime_path"]
        assert source.is_file() and runtime.is_file()
        assert not source.is_symlink() and not runtime.is_symlink()
        assert not os.path.samefile(source, runtime)
        assert source.stat().st_ino != runtime.stat().st_ino
        assert source.stat().st_nlink == runtime.stat().st_nlink == 1
        assert source.stat().st_size == runtime.stat().st_size == row["bytes"]
        assert sha(source) == sha(runtime) == row["sha256"]
        strict = {key: value for key, value in row.items() if key not in addendum_only}
        assert strict["evidence_kind"] == "current-direct-g3c-catalog-addendum"
        strict["evidence_kind"] = "current-direct"
        assert manifest_by_url[row["source_url"]] == strict


def test_catalog_special_states_render_the_six_exact_images_with_identity() -> None:
    by_state: dict[str, list[dict[str, object]]] = {"math-undergraduate": [], "course-number": []}
    for row in ADDENDUM["assets"]:
        by_state[str(row["state"])].append(row)

    for state, rows in by_state.items():
        rows.sort(key=lambda row: int(row["card_index"]))
        response = client.get(f"/search/?state={state}")
        assert response.status_code == 200
        cards = re.findall(r'<article class="card">(.*?)</article>', response.text, re.S)
        assert len(cards) == 10
        for card, row in zip(cards[:3], rows, strict=True):
            assert 'class="placeholder"' not in card
            assert 'data-wb-media="course-card-images"' in card
            assert f'data-wb-asset-source="{row["source_url"]}"' in card
            local_url = G3C_CATALOG_URL_MAP[row["source_url"]]
            assert f'src="{local_url}"' in card
            assert f'alt="{row["course_title"]}"' in card
            asset = client.get(local_url)
            assert asset.status_code == 200
            assert asset.headers["content-type"].startswith("image/jpeg")
            assert asset.headers["x-content-sha256"] == row["sha256"]
            assert len(asset.content) == row["bytes"]
            assert hashlib.sha256(asset.content).hexdigest() == row["sha256"]

    assert client.get("/g3c-catalog-assets/not-declared.jpg").status_code == 404


def test_current_math_addendum_preserves_284_and_adds_four_identity_bound_images() -> None:
    assert MATH_ADDENDUM["schema_version"] == "mit-ocw.g3c-catalog-math-asset-addendum.v1"
    assert MATH_ADDENDUM["capture_id"] == "mit-opencourseware-20260905T070619Z"
    assert MATH_ADDENDUM["does_not_modify_prior_284_manifest_records"] is True
    assert MATH_ADDENDUM["request_policy"]["other_requests"] == 0
    assert len(MATH_ADDENDUM["request_policy"]["allowed_urls"]) == 4
    assert len(MATH_ADDENDUM["assets"]) == 4
    assert canonical_sha(MANIFEST["assets"][:284]) == MATH_ADDENDUM[
        "prior_manifest_assets_sha256"
    ]
    manifest_by_url = {row["source_url"]: row for row in MANIFEST["assets"]}
    assert {row["source_url"] for row in MATH_ADDENDUM["assets"]} <= set(
        G3C_CATALOG_URL_MAP
    )
    assert [row["card_index"] for row in MATH_ADDENDUM["assets"]] == [0, 1, 2, 3]
    assert [row["source_card_index"] for row in MATH_ADDENDUM["assets"]] == [7, 6, 8, 9]
    addendum_only = {
        "state",
        "card_index",
        "source_card_index",
        "course_title",
        "requested_url",
        "final_url",
        "http_status",
        "response_content_type",
        "observed_in",
        "observation_sha256",
    }
    for row in MATH_ADDENDUM["assets"]:
        assert row["requested_url"] == row["source_url"] == row["final_url"]
        assert row["http_status"] == 200
        assert row["response_content_type"] == row["mime_type"] == "image/jpeg"
        source = SITE_ROOT / row["source_path"]
        runtime = SITE_ROOT / row["runtime_path"]
        assert source.is_file() and runtime.is_file()
        assert not source.is_symlink() and not runtime.is_symlink()
        assert source.stat().st_ino != runtime.stat().st_ino
        assert source.stat().st_nlink == runtime.stat().st_nlink == 1
        assert source.stat().st_size == runtime.stat().st_size == row["bytes"]
        assert sha(source) == sha(runtime) == row["sha256"]
        strict = {key: value for key, value in row.items() if key not in addendum_only}
        assert strict["evidence_kind"] == "current-direct-g3c-catalog-math-addendum"
        strict["evidence_kind"] = "current-direct"
        assert manifest_by_url[row["source_url"]] == strict


def test_math_state_renders_four_current_images_on_the_same_frozen_course_identities() -> None:
    response = client.get("/search/?state=math")
    assert response.status_code == 200
    cards = re.findall(r'<article class="card">(.*?)</article>', response.text, re.S)
    assert len(cards) == 10
    for card, row in zip(cards[:4], MATH_ADDENDUM["assets"], strict=True):
        assert 'class="placeholder"' not in card
        assert f'data-wb-asset-source="{row["source_url"]}"' in card
        local_url = G3C_CATALOG_URL_MAP[row["source_url"]]
        assert f'src="{local_url}"' in card
        assert f'alt="{row["course_title"]}"' in card
        asset = client.get(local_url)
        assert asset.status_code == 200
        assert asset.headers["x-content-sha256"] == row["sha256"]
        assert hashlib.sha256(asset.content).hexdigest() == row["sha256"]
