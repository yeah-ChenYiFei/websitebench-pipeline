"""Visual evidence and capture-policy tests."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from websitebench.viewer.capture import (
    classify_blocked_request,
    classify_network_failure,
    classify_page_error,
    comparison_readiness,
    decide_capture_status as decide_side_capture_status,
    detect_access_gate,
    detect_soft_error,
    reviewability_for_status,
)
from websitebench.viewer.evidence import EvidenceStore, decide_capture_status
from websitebench.viewer.metrics import _imports, compare_images
from websitebench.viewer.policy import request_decision


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_capture_status_keeps_partial_and_diagnostic_states_explicit() -> None:
    assert decide_capture_status(source_available=True, candidate_available=True) == (
        "captured",
        "reliable",
    )
    assert decide_capture_status(source_available=False, candidate_available=True) == (
        "partial",
        "caution",
    )
    assert decide_capture_status(
        source_available=True, candidate_available=True, comparable=False
    ) == ("not_comparable", "unavailable")


def test_evidence_resolver_rejects_unregistered_and_parent_paths(tmp_path: Path) -> None:
    pil = pytest.importorskip("PIL.Image")
    source = tmp_path / "source.png"
    pil.new("RGB", (20, 20), "white").save(source)
    store = EvidenceStore(tmp_path / "artifacts", REPO_ROOT)
    manifest = store.upsert(
        "offlineclone--amazon-shopping-mainline",
        "home",
        "desktop",
        source_image=source,
    )
    relative = manifest["captures"][0]["source_image"]
    resolved = store.resolve("offlineclone--amazon-shopping-mainline", relative)
    assert resolved.is_file()
    assert "source_sha256" not in manifest["captures"][0]
    with pytest.raises(FileNotFoundError):
        store.resolve("offlineclone--amazon-shopping-mainline", "../../source.png")


def test_visual_evidence_can_be_isolated_per_model_run(tmp_path: Path) -> None:
    pil = pytest.importorskip("PIL.Image")
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    pil.new("RGB", (20, 20), "white").save(first)
    pil.new("RGB", (20, 20), "black").save(second)
    store = EvidenceStore(tmp_path / "artifacts", REPO_ROOT)
    one = store.upsert(
        "offlineclone--amazon-shopping-mainline", "home", "desktop",
        run_id="model-one", source_image=first,
    )
    two = store.upsert(
        "offlineclone--amazon-shopping-mainline", "home", "desktop",
        run_id="model-two", source_image=second,
    )
    assert one["run_id"] == "model-one"
    assert two["run_id"] == "model-two"
    assert store.manifest_path("offlineclone--amazon-shopping-mainline", "model-one") != store.manifest_path(
        "offlineclone--amazon-shopping-mainline", "model-two"
    )
    assert store.resolve(
        "offlineclone--amazon-shopping-mainline",
        one["captures"][0]["source_image"],
        "model-one",
    ).is_file()


def test_image_diagnostics_are_not_named_as_official_score(tmp_path: Path) -> None:
    pil = pytest.importorskip("PIL.Image")
    pytest.importorskip("skimage")
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    heatmap = tmp_path / "heat.webp"
    pil.new("RGB", (40, 30), "white").save(first)
    pil.new("RGB", (40, 30), "white").save(second)
    metrics = compare_images(first, second, heatmap)
    assert metrics["ssim"] == 1.0
    assert "score" not in metrics
    assert heatmap.is_file()


def test_missing_image_dependencies_use_current_product_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def reject_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("simulated missing image dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_numpy)
    with pytest.raises(
        RuntimeError,
        match="WebsiteBench image dependencies",
    ):
        _imports()


def test_request_policy_rejects_mutating_source_requests() -> None:
    assert not request_decision("POST", "https://example.com/write", {"example.com"}).allow


def test_capture_integrity_classifies_request_impact_and_error_shells() -> None:
    assert classify_blocked_request(
        "GET", "https://cdn.example.test/main.css", "stylesheet", "blocked_unlisted_host"
    ) == "visual"
    assert classify_blocked_request(
        "POST", "https://example.test/api", "other", "blocked_mutating_method"
    ) == "behavioral"
    assert classify_network_failure(
        "https://www.google-analytics.com/g/collect", "fetch"
    ) == "nonvisual"
    blocked = [{"url": "https://cdn.test/app.js", "impact": "behavioral"}]
    assert classify_page_error("Failed https://cdn.test/app.js", blocked) == "behavioral"
    assert detect_soft_error("Page not found", None) == "page not found"
    assert detect_access_gate("Just a moment", None, "Cloudflare") == (
        "cloudflare verification"
    )


def test_capture_integrity_distinguishes_blocked_failed_and_degraded() -> None:
    defaults = {
        "image_available": True,
        "soft_error": None,
        "access_gate": None,
        "blank_viewport": False,
        "screenshot_error": None,
        "navigation_error": None,
        "status_code": 200,
        "has_quality_issue": False,
    }
    assert decide_side_capture_status(side="source", **defaults) == "captured"
    assert decide_side_capture_status(
        side="source", **{**defaults, "access_gate": "access denied"}
    ) == "blocked"
    assert decide_side_capture_status(
        side="candidate", **{**defaults, "access_gate": "access denied"}
    ) == "failed"
    assert decide_side_capture_status(
        side="candidate", **{**defaults, "navigation_error": "timeout"}
    ) == "degraded"


def test_comparison_readiness_requires_two_usable_images() -> None:
    captured = {"status": "captured", "image": "capture.webp"}
    assert comparison_readiness(captured, captured) == ("captured", None)
    assert comparison_readiness(
        {"status": "blocked", "image": None, "http_status": 403}, captured
    ) == ("blocked", "source capture blocked: HTTP 403")
    assert comparison_readiness(captured, {"status": "failed", "image": None})[0] == (
        "failed"
    )
    assert reviewability_for_status("captured") == "reliable"
    assert reviewability_for_status("degraded") == "caution"
