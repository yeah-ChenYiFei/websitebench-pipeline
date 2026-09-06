"""Materialize the narrow G3-A visual assets and source-current rasters.

This builder appends a provenance-rich addendum without rewriting the frozen
G1 asset reports. Inputs are the three explicitly authorized temporary files
and two immutable EA1 source screenshots.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from websitebench.offline_clone.assets import inspect_asset


SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parents[1]
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
CAPTURE = REPO / "artifacts" / "mit-opencourseware" / CAPTURE_ID
EA1 = CAPTURE / "ea1"

ASSETS = [
    {
        "key": "homepage_hero",
        "source_url": "https://ocw.mit.edu/images/homepage_hero.jpg",
        "input": Path("/tmp/mit-ocw-homepage-hero.jpg"),
        "sha256": "2709ed33a5dc304c789d339774bc24745d423459e624b95d654276684953181f",
        "mime_type": "image/jpeg",
        "dimensions": {"width": 1440, "height": 500},
        "source_html_sha256_prefix": "71c63a",
        "referenced_by": ["home.default", "home.carousel-second-batches"],
    },
    {
        "key": "homepage_bg",
        "source_url": "https://ocw.mit.edu/images/homepage_bg.png",
        "input": Path("/tmp/mit-ocw-homepage-bg.png"),
        "sha256": "c27dd71e2d43b3aa5badb85339718fb5f5caa50e9c5c68628456bb93c483f6d2",
        "mime_type": "image/png",
        "dimensions": {"width": 1442, "height": 4044},
        "source_html_sha256_prefix": "71c63a",
        "referenced_by": ["home.default", "home.carousel-second-batches"],
    },
    {
        "key": "course_6_006_image",
        "source_url": (
            "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/"
            "1075c5ac06ae4c2cea8c89e9772da78a_6-006f11.jpg"
        ),
        "input": Path("/tmp/mit-ocw-6-006-course-image.jpg"),
        "sha256": "d8807e078b8b1a4ad53d395409cf40462434c130809436941957d4cd74c3bc37",
        "mime_type": "image/jpeg",
        "dimensions": {"width": 320, "height": 240},
        "source_html_sha256": "35cb2acd33505d5bbdea39837ee0348971dc5f68af74d21daa895eea944f1c74",
        "referenced_by": ["course-overview.default"],
    },
]

SOURCE_RASTERS = [
    {
        "checkpoint_id": "home.default",
        "source": EA1 / "playwright-depth-screenshots" / "01-home-viewport.png",
        "destination": SITE / "source-current" / "g3a" / "home-default-1440x900.png",
    },
    {
        "checkpoint_id": "course-overview.default",
        "source": EA1 / "playwright-depth-screenshots" / "03-course-root-viewport.png",
        "destination": SITE / "source-current" / "g3a" / "course-overview-default-1440x900.png",
    },
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: object, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    separators = (",", ":") if compact else None
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=None if compact else 2, separators=separators) + "\n",
        encoding="utf-8",
    )


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def copy_distinct(source: Path, destination: Path) -> None:
    assert source.is_file() and not source.is_symlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    assert destination.is_file() and not destination.is_symlink()
    assert source.stat().st_ino != destination.stat().st_ino
    assert digest(source) == digest(destination)


def main() -> None:
    manifest_path = SITE / "source-assets" / "manifest.json"
    data_path = SITE / "clone" / "site-data.json"
    addendum_path = SITE / "source-assets" / "g3-visual-asset-addendum.json"
    manifest = load(manifest_path)
    data = load(data_path)
    assert len(manifest["assets"]) >= 231
    assert data["presentation_asset_denominator"] == {
        "status": "closed", "retained": 231, "bytes": 35_298_609, "source_404": 5
    }

    stale_course_raster = (
        SITE / "source-current" / "g3a" / "course-overview-6-006-default-1440x900.png"
    )
    if stale_course_raster.exists():
        assert stale_course_raster.is_file() and not stale_course_raster.is_symlink()
        stale_course_raster.unlink()

    addendum_assets: list[dict[str, object]] = []
    runtime_assets: dict[str, dict[str, object]] = {}
    url_map: dict[str, str] = {}
    addendum_ids: set[str] = set()
    for item in ASSETS:
        source = item["input"]
        assert digest(source) == item["sha256"], item["key"]
        inspected = inspect_asset(source)
        assert inspected["mime_type"] == item["mime_type"]
        assert inspected["dimensions"] == item["dimensions"]
        suffix = source.suffix.lower()
        logical_name = f'{item["sha256"]}{suffix}'
        source_copy = SITE / "source-assets" / "g3a-visual" / logical_name
        runtime_copy = SITE / "runtime-assets" / "g3a-visual" / logical_name
        copy_distinct(source, source_copy)
        copy_distinct(source, runtime_copy)
        assert source_copy.stat().st_ino != runtime_copy.stat().st_ino
        assert digest(source_copy) == digest(runtime_copy) == item["sha256"]
        local_url = f"/g3a-visual-assets/{logical_name}"
        asset_id = f'g3a-{item["key"]}-{str(item["sha256"])[:12]}'
        addendum_ids.add(asset_id)
        record = {
            "id": asset_id,
            "priority": "p0",
            "required": True,
            "source_path": source_copy.relative_to(SITE).as_posix(),
            "runtime_path": runtime_copy.relative_to(SITE).as_posix(),
            "bytes": source_copy.stat().st_size,
            "sha256": item["sha256"],
            "mime_type": item["mime_type"],
            "dimensions": item["dimensions"],
            "referenced_by": item["referenced_by"],
            "evidence_kind": "current-direct",
            "source_url": item["source_url"],
            "capture_id": CAPTURE_ID,
        }
        addendum_assets.append({
            **record,
            "input_path": str(source),
            **(
                {"source_html_sha256": item["source_html_sha256"]}
                if item.get("source_html_sha256") else {}
            ),
            **(
                {"source_html_sha256_prefix": item["source_html_sha256_prefix"]}
                if item.get("source_html_sha256_prefix") else {}
            ),
        })
        runtime_assets[logical_name] = {
            "runtime_path": runtime_copy.relative_to(SITE).as_posix(),
            "mime_type": item["mime_type"],
            "bytes": source_copy.stat().st_size,
            "sha256": item["sha256"],
        }
        url_map[str(item["source_url"])] = local_url

    raster_rows: list[dict[str, object]] = []
    for raster in SOURCE_RASTERS:
        copy_distinct(raster["source"], raster["destination"])
        info = inspect_asset(raster["destination"])
        assert info["mime_type"] == "image/png"
        assert info["dimensions"] == {"width": 1440, "height": 900}
        raster_rows.append({
            "checkpoint_id": raster["checkpoint_id"],
            "source_capture": raster["source"].relative_to(REPO).as_posix(),
            "source_current": raster["destination"].relative_to(SITE).as_posix(),
            "bytes": raster["destination"].stat().st_size,
            "sha256": digest(raster["destination"]),
            "dimensions": info["dimensions"],
        })

    manifest["assets"] = [asset for asset in manifest["assets"] if asset["id"] not in addendum_ids]
    manifest["assets"].extend(
        {key: value for key, value in asset.items() if key not in {"input_path", "source_html_sha256", "source_html_sha256_prefix"}}
        for asset in addendum_assets
    )
    assert len({asset["id"] for asset in manifest["assets"]}) == len(manifest["assets"])
    data["g3_visual_assets"] = runtime_assets
    data["g3_visual_url_map"] = url_map
    data["g3_visual_asset_addendum"] = {
        "status": "g3a-narrow-visual-assets-imported",
        "assets": 3,
        "bytes": sum(int(asset["bytes"]) for asset in addendum_assets),
        "source_current_rasters": 2,
        "provenance": "source-assets/g3-visual-asset-addendum.json",
    }
    data["phase"] = "g3a-two-p0-visual-slices-active"

    addendum = {
        "schema_version": "mit-ocw.g3-visual-asset-addendum.v1",
        "capture_id": CAPTURE_ID,
        "authority": "target-lock-current-direct-narrow-addendum",
        "created_at": "2026-09-03T08:00:00Z",
        "does_not_modify_g1_evidence": True,
        "target_lock": "artifacts/mit-opencourseware/mit-opencourseware-20260903T032020Z/ea1/target-lock.json",
        "assets": addendum_assets,
        "source_current_rasters": raster_rows,
    }
    dump(addendum_path, addendum)
    dump(manifest_path, manifest)
    dump(data_path, data, compact=True)
    print(json.dumps({
        "status": "g3a-visual-assets-materialized",
        "manifest_assets": len(manifest["assets"]),
        "g1_presentation_assets": 231,
        "g3a_visual_assets": 3,
        "g3a_visual_asset_bytes": sum(int(asset["bytes"]) for asset in addendum_assets),
        "source_current_rasters": 2,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
