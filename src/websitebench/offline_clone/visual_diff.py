"""Shared visual-difference diagnosis tool.

Given a source raster and a candidate raster of the same size, this tool
locates *where* they differ and classifies each difference region, so a
clone engineer can iterate on "make it look more like the source" with
exact bounding boxes instead of eyeballing heatmaps.

Outputs: overall metrics (ssim, normalized mae, edge f1, changed-pixel
ratio), a list of difference regions (bbox, mean intensity, area share,
and a coarse kind: layout / color / content / texture), the heatmap raster,
and an annotated overlay with the regions outlined on the candidate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .toolbox import ToolboxError

VISUAL_DIFF_SCHEMA = "websitebench.offline-clone.visual-diff.v1"

_DIFF_THRESHOLD = 32  # per-pixel max-channel change counted as different
_MIN_REGION_PIXELS = 180  # ignore specks smaller than this


def _load_rgb(path: Path) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency declared
        raise ToolboxError("visual diff requires Pillow") from exc
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _classify_region(
    source: np.ndarray,
    candidate: np.ndarray,
    bbox: tuple[int, int, int, int],
    y0: int,
    x0: int,
) -> str:
    x, y, w, h = bbox
    rs = source[y0 + y : y0 + y + h, x0 + x : x0 + x + w]
    rc = candidate[y0 + y : y0 + y + h, x0 + x : x0 + x + w]
    if rs.size == 0:
        return "unknown"
    mean_diff = float(np.abs(rs.astype(np.int16) - rc.astype(np.int16)).mean())
    # A structural shift shows up as strong edge disagreement.
    def edges(block: np.ndarray) -> float:
        lum = block.mean(axis=2).astype(np.float32)
        gx = np.abs(np.diff(lum, axis=1)).mean()
        gy = np.abs(np.diff(lum, axis=0)).mean()
        return float(gx + gy)

    edge_delta = abs(edges(rs) - edges(rc))
    # A near-uniform change across many pixels is a color/background shift.
    local_std = float(np.abs(rs.astype(np.int16) - rc.astype(np.int16)).std())
    if mean_diff > 90 and local_std < 40:
        return "color"
    if edge_delta > 14:
        return "layout"
    if mean_diff > 45:
        return "content"
    return "texture"


@dataclass(frozen=True)
class DiffRegion:
    bbox: tuple[int, int, int, int]
    mean_intensity: float
    area_pixels: int
    kind: str


def diagnose_visual_diff(
    *,
    source_path: Path,
    candidate_path: Path,
    output_path: Path,
    heatmap_path: Path | None = None,
    overlay_path: Path | None = None,
) -> dict[str, Any]:
    """Locate and classify difference regions between two rasters."""

    if output_path.exists():
        raise ToolboxError(f"refusing to overwrite existing report: {output_path}")
    source = _load_rgb(source_path)
    candidate = _load_rgb(candidate_path)
    if source.shape != candidate.shape:
        raise ToolboxError(
            f"raster dimensions differ: source={source.shape}, candidate={candidate.shape}"
        )

    difference = np.abs(source.astype(np.int16) - candidate.astype(np.int16)).astype(
        np.uint8
    )
    intensity = difference.max(axis=2).astype(np.float32) / 255.0
    mask = (difference.max(axis=2) > _DIFF_THRESHOLD).astype(np.uint8)

    try:
        from skimage import measure
    except ImportError as exc:  # pragma: no cover - dependency declared
        raise ToolboxError("visual diff requires scikit-image") from exc

    labeled, count = measure.label(mask, connectivity=2, return_num=True)
    regions: list[DiffRegion] = []
    for region_id in range(1, count + 1):
        ys, xs = np.where(labeled == region_id)
        if len(ys) < _MIN_REGION_PIXELS:
            continue
        area = int(len(ys))
        bbox = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min()), int(ys.max() - ys.min()))
        mean_intensity = float(intensity[ys, xs].mean())
        kind = _classify_region(source, candidate, bbox, 0, 0)
        regions.append(DiffRegion(bbox=bbox, mean_intensity=round(mean_intensity, 3), area_pixels=area, kind=kind))
    regions.sort(key=lambda item: -item.area_pixels)

    changed_pixels = int(mask.sum())
    total_pixels = int(mask.size)
    metrics = {
        "changed_pixel_ratio": round(changed_pixels / total_pixels, 4),
        "normalized_mae": round(float(difference.mean() / 255.0), 4),
        "region_count": len(regions),
    }
    try:
        from skimage.metrics import structural_similarity as ssim_fn
    except ImportError:  # pragma: no cover - fall back to None
        ssim_fn = None
    if ssim_fn is not None:
        metrics["ssim"] = round(
            float(ssim_fn(source, candidate, channel_axis=2, data_range=255)), 4
        )

    report: dict[str, Any] = {
        "schema_version": VISUAL_DIFF_SCHEMA,
        "authority": "diagnostic-only",
        "source": str(source_path),
        "candidate": str(candidate_path),
        "metrics": metrics,
        "regions": [
            {
                "bbox": {
                    "x": r.bbox[0],
                    "y": r.bbox[1],
                    "width": r.bbox[2],
                    "height": r.bbox[3],
                },
                "mean_intensity": r.mean_intensity,
                "area_pixels": r.area_pixels,
                "kind": r.kind,
            }
            for r in regions
        ],
    }

    if heatmap_path is not None:
        heat = np.zeros_like(source)
        heat[..., 0] = np.clip(intensity * 255 * 1.5, 0, 255).astype(np.uint8)
        heat[..., 1] = np.clip((intensity - 0.35) * 255 * 1.5, 0, 255).astype(np.uint8)
        rendered = np.maximum((source.astype(np.float32) * 0.25).astype(np.uint8), heat)
        _save_png(rendered, heatmap_path)

    if overlay_path is not None:
        overlay = candidate.copy()
        for r in regions:
            x, y, w, h = r.bbox
            overlay[y : y + h, x : x + 4, :] = [255, 64, 32]
            overlay[y : y + 4, x : x + w, :] = [255, 64, 32]
            overlay[y + h - 4 : y + h, x : x + w, :] = [255, 64, 32]
            overlay[y : y + h, x + w - 4 : x + w, :] = [255, 64, 32]
        _save_png(overlay, overlay_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _save_png(raster: np.ndarray, path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(raster, mode="RGB").save(path, "PNG")
