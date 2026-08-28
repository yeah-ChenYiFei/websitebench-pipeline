"""Recompute AMC source/candidate visual evidence and report formal coverage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity


ROOT = Path(__file__).resolve().parents[1]
SESSION_PATH = ROOT / "scope" / "visual-sessions.json"
CHECKPOINT_PATH = ROOT / "scope" / "checkpoints.json"
DERIVED_PATH = ROOT / "evidence" / "source-vs-clone-playwright-2026-08-25.json"
ROUNDING_TOLERANCE = 0.000002
RAW_STORAGE_STATES = {
    "mac-private-not-transferred",
    "untracked-scratch-removed-before-delivery",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(source: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    difference = source - candidate
    return {
        "mae_similarity": 1 - float(np.abs(difference).mean()) / 255,
        "normalized_rmse_similarity": 1
        - float(np.sqrt(np.square(difference / 255).mean())),
        "ssim": float(
            structural_similarity(
                source, candidate, channel_axis=2, data_range=255
            )
        ),
    }


def verify_recorded(
    comparison_id: str,
    region_id: str,
    actual: dict[str, float],
    recorded: dict[str, float],
    threshold: float,
) -> None:
    for key, actual_value in actual.items():
        recorded_value = float(recorded[key])
        if abs(actual_value - recorded_value) > ROUNDING_TOLERANCE:
            raise AssertionError(
                f"{comparison_id}:{region_id}:{key} recorded "
                f"{recorded_value:.6f}, recomputed {actual_value:.6f}"
            )
        if actual_value < threshold:
            raise AssertionError(
                f"{comparison_id}:{region_id}:{key} is {actual_value:.6f}, "
                f"below {threshold:.2f}"
            )


def main() -> int:
    session = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    checkpoints = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    derived = json.loads(DERIVED_PATH.read_text(encoding="utf-8"))
    threshold = float(session["threshold"])
    assert derived["site_id"] == session["site_id"]
    assert float(derived["threshold"]) == threshold
    assert derived["summary"]["status"] == "accepted"
    assert derived["summary"]["comparisons"] == 14
    assert derived["summary"]["passed"] == 14
    assert derived["summary"]["failed"] == 0
    assert derived["summary"]["clone_remote_requests"] == 0
    derived_by_ref = {
        f"evidence/source-vs-clone-playwright-2026-08-25.json#/comparisons/{index}": item
        for index, item in enumerate(derived["comparisons"])
    }
    checkpoint_by_id = {item["id"]: item for item in checkpoints["checkpoints"]}
    eligible_count = 0
    for comparison in session["comparisons"]:
        comparison_id = comparison["id"]
        derived_ref = comparison.get("derived_metrics_ref")
        if derived_ref:
            item = derived_by_ref[derived_ref]
            assert item["accepted"] is True
            assert item["route"] == comparison["route"]
            assert item["viewport"] == comparison["viewport"]
            assert item["source_sha256"] == comparison["source_sha256"]
            assert item["clone_sha256"] == comparison["candidate_sha256"]
            assert "source_artifact_path" not in comparison
            assert "candidate_artifact_path" not in comparison
            assert comparison["source_artifact_storage"] in RAW_STORAGE_STATES
            assert comparison["candidate_artifact_storage"] in RAW_STORAGE_STATES
            expected = {
                key: item[key]
                for key in ("mae_similarity", "normalized_rmse_similarity", "ssim")
            }
            verify_recorded(
                comparison_id, "full", expected, comparison["full"], threshold
            )
            assert comparison["regions"] == []
        else:
            source_path = ROOT / comparison["source_artifact_path"]
            candidate_path = ROOT / comparison["candidate_artifact_path"]
            if "source_sha256" in comparison:
                assert sha256(source_path) == comparison["source_sha256"]
            if "candidate_sha256" in comparison:
                assert sha256(candidate_path) == comparison["candidate_sha256"]
            source = np.asarray(
                Image.open(source_path).convert("RGB"), dtype=np.float32
            )
            candidate = np.asarray(
                Image.open(candidate_path).convert("RGB"), dtype=np.float32
            )
            assert source.shape == candidate.shape
            viewport = comparison["viewport"]
            assert source.shape[:2] == (viewport["height"], viewport["width"])
            verify_recorded(
                comparison_id,
                "full",
                metrics(source, candidate),
                comparison["full"],
                threshold,
            )
            for region in comparison["regions"]:
                rect = region["rect"]
                y1, y2 = rect["y"], rect["y"] + rect["height"]
                x1, x2 = rect["x"], rect["x"] + rect["width"]
                verify_recorded(
                    comparison_id,
                    region["id"],
                    metrics(source[y1:y2, x1:x2], candidate[y1:y2, x1:x2]),
                    region,
                    threshold,
                )
        checkpoint = checkpoint_by_id[comparison_id]
        assert checkpoint["evidence_kind"] == (
            "current-direct-mac-headed-playwright"
            if comparison["evidence_kind"]
            == "directly-compared-mac-headed-playwright"
            else comparison["evidence_kind"]
        )
        if checkpoint["acceptance_eligible"]:
            assert (
                comparison["evidence_kind"]
                == "directly-compared-mac-headed-playwright"
            )
            eligible_count += 1
        else:
            assert comparison["evidence_kind"] == "supplementary-ego-not-acceptance"
        if "source_sha256" in comparison:
            assert checkpoint["source_sha256"] == comparison["source_sha256"]
        if "candidate_sha256" in comparison:
            assert checkpoint["candidate_sha256"] == comparison["candidate_sha256"]
        assert checkpoint["metric_results"] == comparison["full"]
        assert checkpoint["region_results"] == comparison["regions"]
        if derived_ref:
            assert checkpoint["derived_metrics_ref"] == derived_ref
            assert (
                checkpoint["source_artifact_storage"]
                in RAW_STORAGE_STATES
            )
            assert (
                checkpoint["candidate_artifact_storage"]
                in RAW_STORAGE_STATES
            )
            assert checkpoint["visual_contract"]["source_artifact_path"] == (
                "evidence/source-vs-clone-playwright-2026-08-25.json"
            )
    assert len(checkpoint_by_id) == len(session["comparisons"])
    comparison_count = len(session["comparisons"])
    print(
        f"visual evidence verified: {comparison_count} comparisons; "
        f"all full and region MAE/nRMSE/SSIM >= {threshold:.2f}"
    )
    if eligible_count != comparison_count:
        print(
            "EVIDENCE_INCOMPLETE: "
            f"{eligible_count}/{comparison_count} comparisons are backed by "
            "direct Mac headed Playwright source-versus-clone evidence"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
