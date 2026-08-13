from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from websitebench.viewer import discovery as discovery_module
from websitebench.viewer.discovery import (
    _repo_root,
    _safe_resolve,
    discover_corpus,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest_item_keys() -> list[str]:
    rows = []
    for path in (REPO_ROOT / "materials").glob("*/clone.yaml"):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") == "offline-clone.manifest.v2":
            rows.append(
                (
                    manifest.get("display_name", manifest["site_id"]).lower(),
                    f"offlineclone--{manifest['site_id']}",
                )
            )
    return [key for _, key in sorted(rows)]


def test_discovers_only_canonical_benchmark_items() -> None:
    index = discover_corpus(REPO_ROOT)
    assert [item["key"] for item in index.items] == _manifest_item_keys()
    assert all(item["source_type"] != "legacy" for item in index.items)


def test_amazon_adapter_keeps_dataset_calibration_separate_from_agent_results() -> None:
    amazon = discover_corpus(REPO_ROOT).by_key("offlineclone--amazon-shopping-mainline")
    assert amazon is not None
    assert amazon["source_type"] == "offline_clone"
    assert amazon["lifecycle_stage"] == "building"
    assert amazon["construction_status"] == "building"
    assert amazon["experiment_status"] == "not_started"
    assert {
        key: value for key, value in amazon["counts"].items() if key != "assets"
    } == {
        "routes": 15,
        "journeys": 3,
        "checkpoints": 16,
        "seeds": None,
        "public_seeds": None,
        "hidden_test_families": None,
        "states": 80,
    }
    assert amazon["counts"]["assets"] >= 726
    assert amazon["official_runs"] == []
    assert amazon["latest_official_result"] is None
    assert amazon["showcase"]["visual_pairs"] == []
    assert amazon["showcase"]["calibration"]["stage"] is None
    assert amazon["internal"]["viewer_public_summary_error"] is None


def test_amazon_adapter_uses_sanitized_summary_without_generated_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = (
        REPO_ROOT / "materials" / "amazon" / "artifacts" / "offline-clone"
    ).resolve()
    read_json = discovery_module._read_json

    def without_generated_artifacts(path: Path) -> tuple[object | None, str | None]:
        resolved = path.resolve()
        if resolved == artifact_root or artifact_root in resolved.parents:
            return None, "simulated clean checkout without ignored artifacts"
        return read_json(path)

    monkeypatch.setattr(discovery_module, "_read_json", without_generated_artifacts)
    amazon = discover_corpus(REPO_ROOT).by_key("offlineclone--amazon-shopping-mainline")
    assert amazon is not None
    assert amazon["lifecycle_stage"] == "building"
    assert amazon["visual_evidence"] is None
    assert amazon["showcase"]["calibration"]["metrics"] == {}
    assert amazon["internal"]["acceptance_source"] == "viewer-public-summary"
    assert amazon["internal"]["viewer_public_summary_error"] is None


def test_public_index_contains_only_sanitized_amazon_showcase() -> None:
    value = discover_corpus(REPO_ROOT, profile="public").as_dict()
    assert [item["key"] for item in value["items"]] == [
        "offlineclone--amazon-shopping-mainline"
    ]
    assert value["summary"]["benchmark_site_count"] == 1
    assert value["summary"]["official_run_count"] == 0
    assert "legacy_count" not in value["summary"]
    amazon = value["items"][0]
    assert amazon["visual_evidence"] is None
    assert amazon["lifecycle_stage"] == "building"
    assert amazon["showcase"]["experiment_status"] == "not_started"
    assert "internal" not in amazon


def test_path_resolver_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        _safe_resolve(tmp_path, tmp_path / ".." / "outside")


def test_repository_root_error_uses_current_product_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a WebsiteBench repository root"):
        _repo_root(tmp_path)


def test_machine_verification_uses_generic_offline_clone_report() -> None:
    report = {
        "schema_version": "offline-clone.report.v2",
        "site_id": "alpha",
        "manifest_current": True,
        "verification_complete": True,
        "gates": {"verification": {"status": "passed"}},
    }
    assert discovery_module._machine_verification_is_current(
        report,
        site_id="alpha",
    )
    assert not discovery_module._machine_verification_is_current(
        {**report, "site_id": "beta"},
        site_id="alpha",
    )


@pytest.mark.parametrize("status", ["clean", "findings", "incomplete"])
def test_viewer_reads_current_diagnostic_status(status: str) -> None:
    report = {
        "schema_version": "offline-clone.diagnostic-report.v1",
        "authority": "diagnostic-only",
        "qualification": "maintainer-judgment-required",
        "site_id": "alpha",
        "diagnostic_status": status,
    }

    assert (
        discovery_module._diagnostic_report_status(
            report,
            site_id="alpha",
        )
        == status
    )
    assert not discovery_module._machine_verification_is_current(
        {
            **report,
            "schema_version": "webcloning.analysis-summary.v2",
        },
        site_id="alpha",
    )
