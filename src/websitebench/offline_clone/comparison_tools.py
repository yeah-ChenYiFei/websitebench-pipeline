"""Functional and visual comparison tools shared by every clone adapter."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .toolbox import (
    ToolboxError,
    load_json_object,
    resolve_relative,
    safe_component,
    write_json_atomic,
)


EXPLORATION_REPORT_SCHEMA = "websitebench.offline-clone.browser-exploration.v1"
VISUAL_SPEC_SCHEMA = "websitebench.offline-clone.visual-comparison-spec.v1"


def _artifact_ref(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
    }


def _observation_map(step: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    observations = step.get("observations", [])
    if not isinstance(observations, list):
        raise ToolboxError("browser exploration step observations must be an array")
    for observation in observations:
        if not isinstance(observation, dict) or not isinstance(
            observation.get("id"), str
        ):
            raise ToolboxError("browser exploration observation must have a string id")
        if observation["id"] in result:
            raise ToolboxError(f"duplicate observation id {observation['id']!r}")
        result[observation["id"]] = observation
    return result


def compare_functional_reports(
    *,
    source_path: Path,
    candidate_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Compare sanitized browser reports by stable scenario/step/observation IDs."""

    if output_path.exists():
        raise ToolboxError(f"refusing to overwrite existing report: {output_path}")
    source = load_json_object(source_path, schema_version=EXPLORATION_REPORT_SCHEMA)
    candidate = load_json_object(
        candidate_path, schema_version=EXPLORATION_REPORT_SCHEMA
    )
    if source.get("scenario_id") != candidate.get("scenario_id"):
        raise ToolboxError("source and candidate scenario_id values differ")
    if source.get("environment") != "source":
        raise ToolboxError("source report environment must be 'source'")
    if candidate.get("environment") != "clone":
        raise ToolboxError("candidate report environment must be 'clone'")

    source_steps = source.get("steps")
    candidate_steps = candidate.get("steps")
    if not isinstance(source_steps, list) or not isinstance(candidate_steps, list):
        raise ToolboxError("browser exploration reports must contain steps arrays")
    source_by_id = {step.get("id"): step for step in source_steps}
    candidate_by_id = {step.get("id"): step for step in candidate_steps}
    if None in source_by_id or None in candidate_by_id:
        raise ToolboxError("every browser exploration step must have an id")
    if len(source_by_id) != len(source_steps) or len(candidate_by_id) != len(
        candidate_steps
    ):
        raise ToolboxError("browser exploration reports contain duplicate step ids")

    differences: list[dict[str, Any]] = []
    step_results: list[dict[str, Any]] = []
    ordered_ids = list(source_by_id)
    for step_id in ordered_ids:
        left = source_by_id[step_id]
        right = candidate_by_id.get(step_id)
        if right is None:
            differences.append(
                {
                    "category": "missing-step",
                    "step_id": step_id,
                    "summary": "candidate report has no matching step",
                }
            )
            step_results.append({"id": step_id, "status": "missing"})
            continue

        local: list[dict[str, Any]] = []
        for field, category in (
            ("action", "action"),
            ("outcome", "outcome"),
            ("route", "route"),
        ):
            if left.get(field) != right.get(field):
                local.append(
                    {
                        "category": category,
                        "step_id": step_id,
                        "summary": f"{field} differs",
                        "source": left.get(field),
                        "candidate": right.get(field),
                    }
                )
        left_observations = _observation_map(left)
        right_observations = _observation_map(right)
        for observation_id, left_observation in left_observations.items():
            right_observation = right_observations.get(observation_id)
            if right_observation is None:
                local.append(
                    {
                        "category": "missing-observation",
                        "step_id": step_id,
                        "observation_id": observation_id,
                        "summary": "candidate report has no matching observation",
                    }
                )
                continue
            left_value = {
                key: left_observation.get(key)
                for key in ("kind", "actual", "passed")
            }
            right_value = {
                key: right_observation.get(key)
                for key in ("kind", "actual", "passed")
            }
            if left_value != right_value:
                local.append(
                    {
                        "category": "observable-state",
                        "step_id": step_id,
                        "observation_id": observation_id,
                        "summary": "observable value or assertion outcome differs",
                        "source": left_value,
                        "candidate": right_value,
                    }
                )
        for observation_id in sorted(
            set(right_observations).difference(left_observations)
        ):
            local.append(
                {
                    "category": "extra-observation",
                    "step_id": step_id,
                    "observation_id": observation_id,
                    "summary": "candidate report has an unmatched observation",
                }
            )
        differences.extend(local)
        step_results.append(
            {
                "id": step_id,
                "status": "matched" if not local else "different",
                "difference_count": len(local),
            }
        )

    for step_id in sorted(set(candidate_by_id).difference(source_by_id)):
        differences.append(
            {
                "category": "extra-step",
                "step_id": step_id,
                "summary": "candidate report has an unmatched step",
            }
        )
    for field in (
        "console_error_count",
        "failed_request_count",
        "blocked_request_count",
    ):
        candidate_count = candidate.get("summary", {}).get(field)
        if not isinstance(candidate_count, int):
            raise ToolboxError(f"candidate summary.{field} must be an integer")
        if candidate_count:
            differences.append(
                {
                    "category": "runtime-error-behavior",
                    "step_id": None,
                    "summary": f"candidate summary.{field} is non-zero",
                    "candidate": candidate_count,
                }
            )

    result = {
            "schema_version": "websitebench.offline-clone.functional-comparison.v1",
            "scenario_id": source["scenario_id"],
            "source_report": _artifact_ref(source_path),
            "candidate_report": _artifact_ref(candidate_path),
            "steps": step_results,
            "differences": differences,
            "counts": {
                "source_steps": len(source_steps),
                "candidate_steps": len(candidate_steps),
                "differences": len(differences),
            },
            "status": "passed" if not differences else "failed",
            "authority": "diagnostic-only",
    }
    write_json_atomic(output_path, result)
    return result


def _load_image_dependencies() -> tuple[Any, Any]:
    try:
        from PIL import Image

        from websitebench.viewer.metrics import compare_images
    except ImportError as exc:  # pragma: no cover - declared dependencies
        raise ToolboxError(
            "visual comparison requires Pillow and scikit-image"
        ) from exc
    return Image, compare_images


def _resolve_raster(
    value: dict[str, Any], *, anchor: Path, label: str
) -> Path:
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ToolboxError(f"{label}.path must be a non-empty string")
    path = resolve_relative(raw_path, anchor=anchor)
    if not path.is_file():
        raise ToolboxError(f"{label} does not exist: {path}")
    return path


def _region_box(
    region: dict[str, Any], *, image_width: int, image_height: int
) -> tuple[int, int, int, int]:
    if region.get("box") == "full":
        return 0, 0, image_width, image_height
    try:
        x = int(region["x"])
        y = int(region["y"])
        width = int(region["width"])
        height = int(region["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolboxError(
            "visual region requires integer x, y, width, and height or box='full'"
        ) from exc
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ToolboxError("visual region coordinates and dimensions are invalid")
    if x + width > image_width or y + height > image_height:
        raise ToolboxError("visual region escapes the screenshot bounds")
    return x, y, x + width, y + height


def compare_visual_spec(
    *,
    spec_path: Path,
    output_path: Path,
    heatmap_dir: Path,
) -> dict[str, Any]:
    """Compute region-level visual metrics from declared raster pairs."""

    if output_path.exists():
        raise ToolboxError(f"refusing to overwrite existing report: {output_path}")
    if heatmap_dir.exists() and any(heatmap_dir.iterdir()):
        raise ToolboxError(f"refusing non-empty heatmap directory: {heatmap_dir}")
    spec = load_json_object(spec_path, schema_version=VISUAL_SPEC_SCHEMA)
    checkpoints = spec.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise ToolboxError("visual comparison spec requires non-empty checkpoints")
    Image, compare_images = _load_image_dependencies()
    heatmap_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="websitebench-visual-") as temporary_name:
        temporary = Path(temporary_name)
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict):
                raise ToolboxError("visual checkpoint must be an object")
            checkpoint_id = safe_component(
                checkpoint.get("id"), field="visual checkpoint id"
            )
            if checkpoint_id in checkpoint_ids:
                raise ToolboxError(f"duplicate visual checkpoint id {checkpoint_id!r}")
            checkpoint_ids.add(checkpoint_id)
            source_path = _resolve_raster(
                checkpoint.get("source", {}),
                anchor=spec_path.parent,
                label=f"{checkpoint_id}.source",
            )
            candidate_path = _resolve_raster(
                checkpoint.get("candidate", {}),
                anchor=spec_path.parent,
                label=f"{checkpoint_id}.candidate",
            )
            with Image.open(source_path) as source_image:
                source_size = source_image.size
            with Image.open(candidate_path) as candidate_image:
                candidate_size = candidate_image.size
            if source_size != candidate_size:
                raise ToolboxError(
                    f"{checkpoint_id}: screenshot dimensions differ: "
                    f"source={source_size}, candidate={candidate_size}"
                )
            viewport = checkpoint.get("viewport")
            if not isinstance(viewport, dict):
                raise ToolboxError(f"{checkpoint_id}.viewport must be an object")
            try:
                viewport_width = int(viewport["width"])
                viewport_height = int(viewport["height"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ToolboxError(
                    f"{checkpoint_id}.viewport requires integer width and height"
                ) from exc
            capture_mode = checkpoint.get("capture_mode", "viewport")
            if capture_mode == "viewport" and source_size != (
                viewport_width,
                viewport_height,
            ):
                raise ToolboxError(
                    f"{checkpoint_id}: viewport capture dimensions do not match "
                    f"{viewport_width}x{viewport_height}"
                )
            if capture_mode == "full_page" and (
                source_size[0] != viewport_width or source_size[1] < viewport_height
            ):
                raise ToolboxError(
                    f"{checkpoint_id}: full-page capture is inconsistent with viewport"
                )
            if capture_mode not in {"viewport", "full_page"}:
                raise ToolboxError(
                    f"{checkpoint_id}.capture_mode must be viewport or full_page"
                )

            regions = checkpoint.get("regions")
            if not isinstance(regions, list) or not regions:
                raise ToolboxError(f"{checkpoint_id}.regions must be non-empty")
            region_results: list[dict[str, Any]] = []
            for region in regions:
                if not isinstance(region, dict):
                    raise ToolboxError("visual region must be an object")
                region_id = safe_component(region.get("id"), field="visual region id")
                metric = region.get("metric")
                if metric not in {
                    "ssim",
                    "edge_f1",
                    "color_histogram",
                    "normalized_mae",
                }:
                    raise ToolboxError(f"{checkpoint_id}/{region_id}: invalid metric")
                try:
                    threshold = float(region["threshold"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ToolboxError(
                        f"{checkpoint_id}/{region_id}: threshold must be numeric"
                    ) from exc
                if threshold <= 0 or threshold > 1:
                    raise ToolboxError(
                        f"{checkpoint_id}/{region_id}: threshold must be > 0 and <= 1"
                    )
                box = _region_box(
                    region,
                    image_width=source_size[0],
                    image_height=source_size[1],
                )
                with Image.open(source_path) as source_image:
                    source_crop = source_image.convert("RGB").crop(box)
                    source_crop_path = (
                        temporary / f"{checkpoint_id}-{region_id}-source.png"
                    )
                    source_crop.save(source_crop_path)
                with Image.open(candidate_path) as candidate_image:
                    candidate_crop = candidate_image.convert("RGB").crop(box)
                    candidate_crop_path = (
                        temporary / f"{checkpoint_id}-{region_id}-candidate.png"
                    )
                    candidate_crop.save(candidate_crop_path)
                heatmap_path = (
                    heatmap_dir / f"{checkpoint_id}-{region_id}-heatmap.webp"
                ).resolve()
                metrics = compare_images(
                    source_crop_path,
                    candidate_crop_path,
                    heatmap_path,
                    ignore_regions=region.get("ignore_regions", []),
                )
                score = metrics[metric]
                passed = (
                    score <= threshold
                    if metric == "normalized_mae"
                    else score >= threshold
                )
                region_results.append(
                    {
                        "id": region_id,
                        "box": {
                            "x": box[0],
                            "y": box[1],
                            "width": box[2] - box[0],
                            "height": box[3] - box[1],
                        },
                        "metric": metric,
                        "threshold": threshold,
                        "operator": "<=" if metric == "normalized_mae" else ">=",
                        "score": score,
                        "metrics": metrics,
                        "passed": passed,
                        "heatmap": _artifact_ref(heatmap_path),
                    }
                )
            results.append(
                {
                    "id": checkpoint_id,
                    "viewport": {
                        "width": viewport_width,
                        "height": viewport_height,
                    },
                    "capture_mode": capture_mode,
                    "source": _artifact_ref(source_path),
                    "candidate": _artifact_ref(candidate_path),
                    "regions": region_results,
                    "passed": all(item["passed"] for item in region_results),
                }
            )

    result = {
            "schema_version": "websitebench.offline-clone.visual-comparison.v1",
            "spec": _artifact_ref(spec_path),
            "checkpoints": results,
            "counts": {
                "checkpoints_total": len(results),
                "checkpoints_passed": sum(item["passed"] for item in results),
                "regions_total": sum(len(item["regions"]) for item in results),
                "regions_passed": sum(
                    region["passed"]
                    for item in results
                    for region in item["regions"]
                ),
            },
            "status": "passed" if all(item["passed"] for item in results) else "failed",
            "authority": "diagnostic-only",
    }
    write_json_atomic(output_path, result)
    return result
