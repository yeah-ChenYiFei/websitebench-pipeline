#!/usr/bin/env python3
"""Create the immutable G3-C source-raster mapping inventory.

This builder deliberately does not invent source evidence.  It copies exact G1
authority rasters, records component-only evidence separately, and leaves
checkpoints with no matching raster explicitly missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[3]
SITE = Path(__file__).resolve().parents[1]
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
CAPTURE = REPO / "artifacts" / "mit-opencourseware" / CAPTURE_ID
SOURCE_CURRENT = SITE / "source-current"
G3C = SOURCE_CURRENT / "g3c"

EA1_DEPTH = "artifacts/mit-opencourseware/{}/ea1/playwright-depth-screenshots".format(CAPTURE_ID)
EA1_REPORT = "artifacts/mit-opencourseware/{}/ea1/playwright-depth-observations.json".format(CAPTURE_ID)
SEARCH = "artifacts/mit-opencourseware/{}/g1/search-authorized-matrix".format(CAPTURE_ID)
SEARCH_REPORT = f"{SEARCH}/report.json"
SAFE = "artifacts/mit-opencourseware/{}/g1/safe-breadth".format(CAPTURE_ID)
SAFE_REPORT = "artifacts/mit-opencourseware/{}/g1/safe-breadth-report.json".format(CAPTURE_ID)
STORIES = "artifacts/mit-opencourseware/{}/g1/story-details".format(CAPTURE_ID)
STORIES_REPORT = "artifacts/mit-opencourseware/{}/g1/story-details-report.json".format(CAPTURE_ID)
STATIC = "artifacts/mit-opencourseware/{}/g1/capture-static-visuals".format(CAPTURE_ID)
STATIC_REPORT = "artifacts/mit-opencourseware/{}/g1/capture-static-visuals-report.json".format(CAPTURE_ID)
GALLERY = "artifacts/mit-opencourseware/{}/g1/capture-video-gallery-static".format(CAPTURE_ID)
GALLERY_REPORT = "artifacts/mit-opencourseware/{}/g1/capture-video-gallery-static-report.json".format(CAPTURE_ID)
CATALOG_COURSES = "artifacts/mit-opencourseware/{}/g1/catalog-course-overviews".format(CAPTURE_ID)
CATALOG_COURSES_REPORT = "artifacts/mit-opencourseware/{}/g1/catalog-course-overviews-report.json".format(CAPTURE_ID)
EA2 = "artifacts/mit-opencourseware/{}/ea2".format(CAPTURE_ID)
EA2_BREADTH_REPORT = f"{EA2}/capture-breadth-01-report.json"
EA2_CAROUSEL_REPORT = f"{EA2}/carousel-batches.json"


def source(path: str, report: str, raster_kind: str = "full-page") -> dict[str, str]:
    return {"original_path": path, "evidence_report": report, "raster_kind": raster_kind}


# Exact route/state-matched source rasters.  Viewport means the evidence itself
# is exactly 1440x900.  Full-page rasters are not stretched: their future visual
# comparison uses only their native top-left 1440x900 viewport crop.
EXACT = {
    "home.default": source(f"{EA1_DEPTH}/01-home-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "catalog.default": source(f"{SEARCH}/default-batch-1.png", SEARCH_REPORT),
    "collection.default": source(f"{SAFE}/collection-introductory-programming-initial.png", SAFE_REPORT),
    "stories.default": source(f"{EA2}/capture-breadth-01/stories-index-initial.png", EA2_BREADTH_REPORT),
    "story-adrian.default": source(f"{STORIES}/story-01-adrian-pastor-initial.png", STORIES_REPORT),
    "about.default": source(f"{EA2}/capture-breadth-01/about-initial.png", EA2_BREADTH_REPORT),
    "get-started.default": source(f"{EA2}/capture-breadth-01/get-started-initial.png", EA2_BREADTH_REPORT),
    "educator.default": source(f"{SAFE}/educator-initial.png", SAFE_REPORT),
    "newsletter.default": source(f"{STATIC}/newsletter-authorized-stylesheet-initial.png", STATIC_REPORT),
    "course-overview.default": source(f"{EA1_DEPTH}/03-course-root-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "catalog-course-overview.default": source(f"{CATALOG_COURSES}/catalog-course-01-initial.png", CATALOG_COURSES_REPORT),
    "course-syllabus.default": source(f"{EA1_DEPTH}/04-syllabus-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "course-calendar.default": source(f"{EA1_DEPTH}/06-calendar-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "course-readings.default": source(f"{EA1_DEPTH}/07-readings-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "course-reading-deep.default": source(f"{EA1_DEPTH}/09-reading-binary-search-trees-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "course-lecture-notes.default": source(f"{EA1_DEPTH}/10-lecture-notes-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "course-assignments.default": source(f"{EA1_DEPTH}/12-assignments-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "course-exams.default": source(f"{EA1_DEPTH}/15-exams-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "resource-index.default": source(f"{EA1_DEPTH}/13-problem-sets-resource-index-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "resource-problem-set.default": source(f"{EA1_DEPTH}/14-problem-set-1-resource-detail-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "resource-lecture-note.default": source(f"{EA1_DEPTH}/11-lecture-note-1-resource-detail-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "resource-final-exam.default": source(f"{EA1_DEPTH}/16-final-exam-resource-detail-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "course-download.default": source(f"{EA1_DEPTH}/17-download-course-viewport.png", EA1_REPORT, "viewport-1440x900"),
    "video-gallery.default": source(f"{GALLERY}/video-gallery-static-thumbnails-initial.png", GALLERY_REPORT),
    "video-resource.default": source(f"{STATIC}/video-resource-static-thumbnail-initial.png", STATIC_REPORT),
    "source-legacy-boundary.default": source(f"{SAFE}/external-resources-initial.png", SAFE_REPORT),
    "catalog.second-batch": source(f"{SEARCH}/default-batch-2.png", SEARCH_REPORT),
    "catalog.math": source(f"{SEARCH}/filters-sort-department-mathematics.png", SEARCH_REPORT),
    "catalog.math-undergraduate": source(f"{SEARCH}/filters-sort-combined-mathematics-undergraduate.png", SEARCH_REPORT),
    "catalog.course-number": source(f"{SEARCH}/filters-sort-combined-filter-course-number-sort.png", SEARCH_REPORT),
    "catalog.empty": source(f"{SEARCH}/empty-recovery-true-empty.png", SEARCH_REPORT),
    "catalog.error": source(f"{SEARCH}/error-retry-controlled-api-error.png", SEARCH_REPORT),
    "catalog.retry-stale": source(f"{SEARCH}/error-retry-retry-response.png", SEARCH_REPORT),
    "catalog.reload-recovered": source(f"{SEARCH}/error-retry-reload-recovered-default.png", SEARCH_REPORT),
    "catalog.resources": source(f"{SEARCH}/resources-batch-1.png", SEARCH_REPORT),
    "video.static-disabled": source(f"{STATIC}/video-resource-static-thumbnail-initial.png", STATIC_REPORT),
}

COMPONENTS = {
    "home.carousel-second-batches": [
        f"{EA2}/carousel-promo-batch2.png",
        f"{EA2}/carousel-featured-courses-batch2.png",
        f"{EA2}/carousel-new-courses-batch2.png",
        f"{EA2}/carousel-stories-batch2.png",
    ]
}

MISSING = {
    "external-boundary.default": (
        "No exact branded local soft-404 source raster exists. G1 external navigation rasters are blank/failed "
        "and external-boundary reports record modal_visible_after=false."
    ),
    "data-boundary.default": "No route/state-matched source raster exists anywhere in the locked capture.",
    "not-found.default": "No route/state-matched source raster exists anywhere in the locked capture.",
}

G3A_EXISTING = {
    "home.default": "source-current/g3a/home-default-1440x900.png",
    "course-overview.default": "source-current/g3a/course-overview-default-1440x900.png",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def describe(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        width, height = image.size
        image_format = image.format
    return {
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "image_format": image_format,
    }


def copy_independent(original: Path, destination: Path) -> None:
    assert original.is_file() and not original.is_symlink(), original
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, destination)
    assert destination.is_file() and not destination.is_symlink(), destination
    assert original.stat().st_ino != destination.stat().st_ino, (original, destination)
    assert destination.stat().st_nlink == 1, destination
    assert sha256(original) == sha256(destination), destination


def load_checkpoints() -> dict[str, dict[str, object]]:
    payload = json.loads((SITE / "scope" / "checkpoints.json").read_text())
    rows = {row["id"]: row for row in payload["checkpoints"]}
    assert len(rows) == 40
    expected = set(EXACT) | set(COMPONENTS) | set(MISSING)
    assert set(rows) == expected, sorted(set(rows) ^ expected)
    return rows


def visual_regions(checkpoint_id: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return substantial, identity-bearing regions without masks."""

    course_like = checkpoint_id.startswith(("course-", "resource-", "catalog-course-", "video.")) or checkpoint_id in {
        "video-gallery.default",
        "video-resource.default",
    }
    header_height = 80 if course_like else 116
    semantic = [
        {"id": "header", "x": 0, "y": 0, "width": 1440, "height": header_height, "threshold": 0.94},
        {"id": "main", "x": 0, "y": header_height, "width": 1440, "height": 900 - header_height, "threshold": 0.94},
    ]
    media: list[dict[str, object]] = []
    if checkpoint_id.startswith("catalog."):
        media.append({"id": "state-results", "x": 360, "y": 280, "width": 1040, "height": 620, "threshold": 0.94})
    elif checkpoint_id == "home.default":
        media.append({"id": "promo-media", "x": 0, "y": 500, "width": 1440, "height": 230, "threshold": 0.94})
    elif checkpoint_id in {"collection.default", "stories.default", "story-adrian.default"}:
        media.append({"id": "content-media", "x": 80, "y": 240, "width": 1280, "height": 660, "threshold": 0.94})
    elif checkpoint_id == "newsletter.default":
        media.append({"id": "newsletter-form", "x": 100, "y": 220, "width": 1240, "height": 600, "threshold": 0.94})
    elif course_like:
        media.append({"id": "course-content", "x": 250, "y": 200, "width": 1160, "height": 600, "threshold": 0.94})
    return semantic, media


def materialize_contracts() -> None:
    """Create native viewport derivatives and bind only the 36 exact contracts."""

    contract_dir = G3C / "contracts-v1"
    viewport_dir = G3C / "viewports-v1"
    spec_path = SITE / "scope" / "visual-g3c-v1-spec.json"
    assert G3C.is_dir(), "run --materialize-source-map first"
    assert not contract_dir.exists(), f"create-only destination exists: {contract_dir}"
    assert not viewport_dir.exists(), f"create-only destination exists: {viewport_dir}"
    assert not spec_path.exists(), f"create-only destination exists: {spec_path}"

    mapping_path = G3C / "mapping-report.json"
    mapping = json.loads(mapping_path.read_text())
    mapping_rows = {row["checkpoint_id"]: row for row in mapping["rows"]}
    checkpoints_path = SITE / "scope" / "checkpoints.json"
    checkpoint_payload = json.loads(checkpoints_path.read_text())

    viewport_staging = Path(tempfile.mkdtemp(prefix=".g3c-viewports-v1-", dir=G3C))
    contract_staging = Path(tempfile.mkdtemp(prefix=".g3c-contracts-v1-", dir=G3C))
    try:
        derivations = []
        spec_rows = []
        contract_ids = []
        for checkpoint in checkpoint_payload["checkpoints"]:
            checkpoint_id = checkpoint["id"]
            row = mapping_rows[checkpoint_id]
            if row["evidence_class"] != "exact-full-or-viewport":
                checkpoint.pop("visual_contract", None)
                checkpoint["verification_kind"] = "g3c-source-evidence-gap"
                continue

            copied = SITE / row["copied_path"]
            assert describe(copied)["sha256"] == row["copied"]["sha256"]
            safe_id = checkpoint_id.replace(".", "-")
            viewport_rel = f"source-current/g3c/viewports-v1/{safe_id}-1440x900.png"
            viewport_output = viewport_staging / f"{safe_id}-1440x900.png"
            with Image.open(copied) as image:
                assert image.width >= 1440 and image.height >= 900
                viewport = image.convert("RGB").crop((0, 0, 1440, 900))
                viewport.save(viewport_output, format="PNG", optimize=False)
            viewport_meta = describe(viewport_output)
            assert (viewport_meta["width"], viewport_meta["height"]) == (1440, 900)

            semantic, media = visual_regions(checkpoint_id)
            contract: dict[str, object] = {
                "source_artifact_path": row["copied_path"],
                "viewport": {"width": 1440, "height": 900},
                "comparison_region": {"x": 0, "y": 0, "width": 1440, "height": 900},
                "full_page_threshold": 0.94,
                "semantic_regions": semantic,
                "metric": "pixel-mae-similarity-v1",
                "threshold": 0.94,
            }
            if row["raster_kind"] == "full-page":
                contract["source_crop"] = {"x": 0, "y": 0, "width": 1440, "height": 900}
            if media:
                contract["media_regions"] = media
            checkpoint["visual_contract"] = contract
            checkpoint["verification_kind"] = "g3c-exact-visual-diagnostic"
            contract_ids.append(checkpoint_id)

            compare_regions = [
                {"id": "full", "box": "full", "metric": "normalized_mae", "threshold": 0.06},
                *[
                    {
                        "id": item["id"],
                        "x": item["x"], "y": item["y"], "width": item["width"], "height": item["height"],
                        "metric": "normalized_mae", "threshold": 0.06,
                    }
                    for item in semantic
                ],
                *[
                    {
                        "id": item["id"],
                        "x": item["x"], "y": item["y"], "width": item["width"], "height": item["height"],
                        "metric": "normalized_mae", "threshold": 0.06,
                    }
                    for item in media
                ],
            ]
            candidate_rel = f"../artifacts/offline-clone/g3c/v1/candidate/{safe_id}-1440x900.png"
            spec_rows.append({
                "id": safe_id,
                "source": {"path": f"../{viewport_rel}"},
                "candidate": {"path": candidate_rel},
                "viewport": {"width": 1440, "height": 900},
                "capture_mode": "viewport",
                "regions": compare_regions,
            })
            derivations.append({
                "checkpoint_id": checkpoint_id,
                "source_path": row["copied_path"],
                "source_sha256": row["copied"]["sha256"],
                "source_crop": {"x": 0, "y": 0, "width": 1440, "height": 900},
                "viewport_path": viewport_rel,
                "viewport": viewport_meta,
                "operation": "native top-left crop; no resize, composite, or mask",
            })

        assert len(contract_ids) == len(spec_rows) == len(derivations) == 36
        assert not (set(COMPONENTS) | set(MISSING)) & set(contract_ids)
        contract_report = {
            "schema_version": 1,
            "phase": "g3c-exact-contracts-v1",
            "capture_id": CAPTURE_ID,
            "mapping_report": "source-current/g3c/mapping-report.json",
            "mapping_report_sha256": sha256(mapping_path),
            "contract_count": 36,
            "excluded_component_only": sorted(COMPONENTS),
            "excluded_missing": sorted(MISSING),
            "viewport_policy": "1440x900 DPR1, native crop only, no resize/composite/mask",
            "derivations": derivations,
        }
        (contract_staging / "report.json").write_text(json.dumps(contract_report, indent=2) + "\n")

        spec = {
            "schema_version": "websitebench.offline-clone.visual-comparison-spec.v1",
            "checkpoints": spec_rows,
        }
        spec_path.write_text(json.dumps(spec, indent=2) + "\n")
        checkpoints_path.write_text(json.dumps(checkpoint_payload, indent=2, ensure_ascii=False) + "\n")
        os.rename(viewport_staging, viewport_dir)
        os.rename(contract_staging, contract_dir)
        print(json.dumps({
            "contracts": len(contract_ids),
            "viewport_derivatives": len(derivations),
            "component_only_unbound": len(COMPONENTS),
            "missing_unbound": len(MISSING),
            "spec": str(spec_path.relative_to(SITE)),
        }, sort_keys=True))
    except BaseException:
        shutil.rmtree(viewport_staging, ignore_errors=True)
        shutil.rmtree(contract_staging, ignore_errors=True)
        raise


def prepare_v2_after_bad_source_audit() -> None:
    """Create an additive correction and exclude the solid legacy raster."""

    correction_dir = G3C / "mapping-correction-v1"
    spec_path = SITE / "scope" / "visual-g3c-v2-spec.json"
    assert not correction_dir.exists(), f"create-only destination exists: {correction_dir}"
    assert not spec_path.exists(), f"create-only destination exists: {spec_path}"
    mapping_path = G3C / "mapping-report.json"
    v1_result = SITE / "artifacts" / "offline-clone" / "g3c" / "v1" / "visual-comparison.json"
    assert v1_result.is_file(), v1_result
    mapping = json.loads(mapping_path.read_text())
    bad = next(row for row in mapping["rows"] if row["checkpoint_id"] == "source-legacy-boundary.default")
    bad_viewport = SITE / "source-current" / "g3c" / "viewports-v1" / "source-legacy-boundary-default-1440x900.png"
    with Image.open(bad_viewport) as image:
        colors = image.convert("RGBA").getcolors(maxcolors=2)
    assert colors is not None and len(colors) == 1, "legacy source raster is expected to be solid"

    checkpoints_path = SITE / "scope" / "checkpoints.json"
    payload = json.loads(checkpoints_path.read_text())
    simple_course_sections = {
        "course-syllabus.default", "course-calendar.default", "course-readings.default",
        "course-reading-deep.default", "course-lecture-notes.default",
        "course-assignments.default", "course-exams.default",
    }
    for checkpoint in payload["checkpoints"]:
        checkpoint_id = checkpoint["id"]
        if checkpoint_id == "source-legacy-boundary.default":
            checkpoint.pop("visual_contract", None)
            checkpoint["verification_kind"] = "g3c-visual-excluded-bad-source"
        elif checkpoint_id in simple_course_sections:
            checkpoint["visual_contract"].pop("media_regions", None)
        elif checkpoint_id == "course-download.default":
            checkpoint["visual_contract"]["media_regions"] = [
                {"id": "download-panel", "x": 281, "y": 243, "width": 824, "height": 220, "threshold": 0.94}
            ]
        elif checkpoint_id in {"video-resource.default", "video.static-disabled"}:
            checkpoint["visual_contract"]["media_regions"] = [
                {"id": "static-video-player", "x": 281, "y": 325, "width": 804, "height": 516, "threshold": 0.94}
            ]
        elif checkpoint_id == "video-gallery.default":
            checkpoint["visual_contract"]["media_regions"] = [
                {"id": "static-video-list", "x": 281, "y": 325, "width": 824, "height": 575, "threshold": 0.94}
            ]
    visual = [row for row in payload["checkpoints"] if "visual_contract" in row]
    assert len(visual) == 35

    spec_rows = []
    for checkpoint in visual:
        checkpoint_id = checkpoint["id"]
        safe_id = checkpoint_id.replace(".", "-")
        contract = checkpoint["visual_contract"]
        regions = [
            {"id": "full", "box": "full", "metric": "normalized_mae", "threshold": 0.06},
            *[
                {
                    "id": item["id"], "x": item["x"], "y": item["y"],
                    "width": item["width"], "height": item["height"],
                    "metric": "normalized_mae", "threshold": 0.06,
                }
                for item in contract.get("semantic_regions", [])
            ],
            *[
                {
                    "id": item["id"], "x": item["x"], "y": item["y"],
                    "width": item["width"], "height": item["height"],
                    "metric": "normalized_mae", "threshold": 0.06,
                }
                for item in contract.get("media_regions", [])
            ],
        ]
        spec_rows.append({
            "id": safe_id,
            "source": {"path": f"../source-current/g3c/viewports-v1/{safe_id}-1440x900.png"},
            "candidate": {"path": f"../artifacts/offline-clone/g3c/v2/candidate/{safe_id}-1440x900.png"},
            "viewport": {"width": 1440, "height": 900},
            "capture_mode": "viewport",
            "regions": regions,
        })
    spec = {"schema_version": "websitebench.offline-clone.visual-comparison-spec.v1", "checkpoints": spec_rows}
    correction = {
        "schema_version": 1,
        "phase": "g3c-source-raster-classification-correction-v1",
        "create_only_correction_to": "source-current/g3c/mapping-report.json",
        "original_mapping_report_sha256": sha256(mapping_path),
        "v1_visual_result": "artifacts/offline-clone/g3c/v1/visual-comparison.json",
        "v1_visual_result_sha256": sha256(v1_result),
        "corrected_counts": {
            "good_exact_source": 35,
            "bad_source_excluded": 1,
            "component_only": 1,
            "missing_local_only": 3,
            "total": 40,
        },
        "correction": {
            "checkpoint_id": "source-legacy-boundary.default",
            "prior_class": "exact-full-or-viewport",
            "corrected_class": "visual-excluded-by-bad-source",
            "source_path": bad["copied_path"],
            "source_sha256": bad["copied"]["sha256"],
            "viewport_path": str(bad_viewport.relative_to(SITE)),
            "viewport_sha256": sha256(bad_viewport),
            "observed_unique_rgba_colors": 1,
            "reason": "The locked source SSR main is empty and its source raster is solid white. The local clone must retain the semantic boundary identity, so pixel matching this bad raster would be invalid.",
        },
    }
    correction_dir.mkdir(parents=True)
    (correction_dir / "report.json").write_text(json.dumps(correction, indent=2) + "\n")
    checkpoints_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"formal_contracts": 35, "bad_source_excluded": 1, "component_only": 1, "missing": 3, "spec": str(spec_path.relative_to(SITE))}, sort_keys=True))


def prepare_iteration_spec(iteration: str) -> None:
    """Create a new immutable comparison spec from the current 35 contracts."""

    assert iteration.startswith("v") and iteration[1:].isdigit(), iteration
    spec_path = SITE / "scope" / f"visual-g3c-{iteration}-spec.json"
    assert not spec_path.exists(), f"create-only destination exists: {spec_path}"
    payload = json.loads((SITE / "scope" / "checkpoints.json").read_text())
    visual = [row for row in payload["checkpoints"] if "visual_contract" in row]
    assert len(visual) == 35
    spec_rows = []
    for checkpoint in visual:
        checkpoint_id = checkpoint["id"]
        safe_id = checkpoint_id.replace(".", "-")
        contract = checkpoint["visual_contract"]
        regions = [
            {"id": "full", "box": "full", "metric": "normalized_mae", "threshold": 0.06},
            *[
                {
                    "id": item["id"], "x": item["x"], "y": item["y"],
                    "width": item["width"], "height": item["height"],
                    "metric": "normalized_mae", "threshold": 0.06,
                }
                for item in contract.get("semantic_regions", [])
            ],
            *[
                {
                    "id": item["id"], "x": item["x"], "y": item["y"],
                    "width": item["width"], "height": item["height"],
                    "metric": "normalized_mae", "threshold": 0.06,
                }
                for item in contract.get("media_regions", [])
            ],
        ]
        spec_rows.append({
            "id": safe_id,
            "source": {"path": f"../source-current/g3c/viewports-v1/{safe_id}-1440x900.png"},
            "candidate": {"path": f"../artifacts/offline-clone/g3c/{iteration}/candidate/{safe_id}-1440x900.png"},
            "viewport": {"width": 1440, "height": 900},
            "capture_mode": "viewport",
            "regions": regions,
        })
    spec = {"schema_version": "websitebench.offline-clone.visual-comparison-spec.v1", "checkpoints": spec_rows}
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")
    print(json.dumps({"formal_contracts": len(spec_rows), "iteration": iteration, "spec": str(spec_path.relative_to(SITE))}, sort_keys=True))


def materialize_source_map() -> None:
    lock = json.loads((CAPTURE / "TARGET_LOCK.json").read_text())
    assert lock["capture_id"] == CAPTURE_ID
    assert lock["status"] == "locked-g1-complete-g2-complete-g3b-complete-g3c-active"
    assert not G3C.exists(), f"create-only destination already exists: {G3C}"
    checkpoints = load_checkpoints()

    staging = Path(tempfile.mkdtemp(prefix=".g3c-source-map-", dir=SOURCE_CURRENT))
    try:
        rows: list[dict[str, object]] = []
        for checkpoint_id in checkpoints:
            checkpoint = checkpoints[checkpoint_id]
            base = {
                "checkpoint_id": checkpoint_id,
                "clone_path": checkpoint["clone_path"],
                "route_id": checkpoint["route_id"],
                "state": checkpoint["state"],
            }
            if checkpoint_id in EXACT:
                item = EXACT[checkpoint_id]
                original = REPO / item["original_path"]
                report = REPO / item["evidence_report"]
                assert report.is_file(), report
                original_meta = describe(original)
                if item["raster_kind"] == "viewport-1440x900":
                    assert (original_meta["width"], original_meta["height"]) == (1440, 900)
                else:
                    assert original_meta["width"] >= 1440 and original_meta["height"] >= 900

                if checkpoint_id in G3A_EXISTING:
                    copied_rel = G3A_EXISTING[checkpoint_id]
                    copied = SITE / copied_rel
                    assert copied.is_file() and not copied.is_symlink(), copied
                    copied_meta = describe(copied)
                    assert copied_meta["sha256"] == original_meta["sha256"]
                    copy_disposition = "preexisting-create-only-g3a"
                else:
                    filename = checkpoint_id.replace(".", "--") + original.suffix.lower()
                    copied_rel = f"source-current/g3c/exact/{filename}"
                    copied = staging / "exact" / filename
                    copy_independent(original, copied)
                    copied_meta = describe(copied)
                    copy_disposition = "new-independent-copy"

                rows.append({
                    **base,
                    "evidence_class": "exact-full-or-viewport",
                    "raster_kind": item["raster_kind"],
                    "original_path": item["original_path"],
                    "evidence_report": item["evidence_report"],
                    "original": original_meta,
                    "copied_path": copied_rel,
                    "copied": copied_meta,
                    "copy_disposition": copy_disposition,
                    "future_viewport_policy": (
                        "native-1440x900" if item["raster_kind"] == "viewport-1440x900"
                        else "top-left-native-crop-0-0-1440-900-no-resize"
                    ),
                })
            elif checkpoint_id in COMPONENTS:
                component_rows = []
                for original_rel in COMPONENTS[checkpoint_id]:
                    original = REPO / original_rel
                    filename = original.name
                    copied_rel = f"source-current/g3c/components/{filename}"
                    copied = staging / "components" / filename
                    copy_independent(original, copied)
                    component_rows.append({
                        "original_path": original_rel,
                        "evidence_report": EA2_CAROUSEL_REPORT,
                        "original": describe(original),
                        "copied_path": copied_rel,
                        "copied": describe(copied),
                    })
                rows.append({
                    **base,
                    "evidence_class": "component-only",
                    "full_or_viewport_source_absent": True,
                    "components": component_rows,
                    "constraint": "Components may be directly compared one-by-one; they must not be stretched or assembled into a synthetic full-page source.",
                })
            else:
                rows.append({
                    **base,
                    "evidence_class": "missing",
                    "reason": MISSING[checkpoint_id],
                    "visual_contract_allowed_from_locked_capture": False,
                })

        counts = {
            "total_checkpoints": len(rows),
            "exact_full_or_viewport": sum(row["evidence_class"] == "exact-full-or-viewport" for row in rows),
            "exact_native_viewport": sum(row.get("raster_kind") == "viewport-1440x900" for row in rows),
            "exact_full_page": sum(row.get("raster_kind") == "full-page" for row in rows),
            "component_only": sum(row["evidence_class"] == "component-only" for row in rows),
            "missing": sum(row["evidence_class"] == "missing" for row in rows),
            "new_exact_files_copied": sum(row.get("copy_disposition") == "new-independent-copy" for row in rows),
            "preexisting_g3a_exact_files": sum(row.get("copy_disposition") == "preexisting-create-only-g3a" for row in rows),
            "component_files_copied": sum(len(row.get("components", [])) for row in rows),
        }
        assert counts == {
            "total_checkpoints": 40,
            "exact_full_or_viewport": 36,
            "exact_native_viewport": 14,
            "exact_full_page": 22,
            "component_only": 1,
            "missing": 3,
            "new_exact_files_copied": 34,
            "preexisting_g3a_exact_files": 2,
            "component_files_copied": 4,
        }
        report = {
            "schema_version": 1,
            "phase": "g3c-source-raster-mapping",
            "capture_id": CAPTURE_ID,
            "target_lock_status": lock["status"],
            "source_policy": {
                "recapture_performed": False,
                "candidate_used_as_source": False,
                "fuzzy_mapping_used": False,
                "component_stretch_or_composite_used": False,
                "copy_mode": "ordinary-independent-files",
            },
            "counts": counts,
            "rows": rows,
        }
        report_path = staging / "mapping-report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        os.rename(staging, G3C)
        print(json.dumps({"output": str(G3C.relative_to(SITE)), **counts}, sort_keys=True))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialize-source-map", action="store_true")
    parser.add_argument("--materialize-contracts", action="store_true")
    parser.add_argument("--prepare-v2", action="store_true")
    parser.add_argument("--prepare-iteration")
    args = parser.parse_args()
    if sum((args.materialize_source_map, args.materialize_contracts, args.prepare_v2, bool(args.prepare_iteration))) != 1:
        parser.error("choose exactly one materialization mode")
    if args.materialize_source_map:
        materialize_source_map()
    elif args.materialize_contracts:
        materialize_contracts()
    elif args.prepare_v2:
        prepare_v2_after_bad_source_audit()
    else:
        prepare_iteration_spec(args.prepare_iteration)


if __name__ == "__main__":
    main()
