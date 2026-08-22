from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from websitebench.offline_clone.toolbox import ToolboxError
from websitebench.offline_clone.visual_diff import diagnose_visual_diff


def _raster(path: Path, color: tuple[int, int, int]) -> None:
    img = Image.fromarray(
        np.full((120, 160, 3), color, dtype=np.uint8), mode="RGB"
    )
    img.save(path)


def test_visual_diff_lists_regions_with_kind(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    _raster(source, (200, 200, 200))
    _raster(candidate, (200, 200, 200))
    # paint a distinct block in the candidate: a shifted content block
    img = np.asarray(Image.open(candidate).convert("RGB")).copy()
    img[40:80, 30:90] = (30, 90, 200)
    Image.fromarray(img, mode="RGB").save(candidate)

    report = diagnose_visual_diff(
        source_path=source,
        candidate_path=candidate,
        output_path=tmp_path / "diff.json",
        heatmap_path=tmp_path / "heat.png",
        overlay_path=tmp_path / "overlay.png",
    )
    assert report["schema_version"] == "websitebench.offline-clone.visual-diff.v1"
    assert report["metrics"]["region_count"] >= 1
    assert report["metrics"]["changed_pixel_ratio"] > 0.05
    assert tmp_path.joinpath("heat.png").is_file()
    assert tmp_path.joinpath("overlay.png").is_file()
    largest = report["regions"][0]
    assert largest["bbox"]["width"] >= 55
    assert largest["kind"] in {"color", "content", "layout", "texture"}


def test_visual_diff_identical_rasters(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _raster(source, (120, 120, 120))
    report = diagnose_visual_diff(
        source_path=source,
        candidate_path=source,
        output_path=tmp_path / "diff.json",
    )
    assert report["metrics"]["changed_pixel_ratio"] == 0.0
    assert report["metrics"]["region_count"] == 0


def test_visual_diff_rejects_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _raster(source, (10, 10, 10))
    output = tmp_path / "diff.json"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(ToolboxError, match="refusing to overwrite"):
        diagnose_visual_diff(
            source_path=source,
            candidate_path=source,
            output_path=output,
        )
