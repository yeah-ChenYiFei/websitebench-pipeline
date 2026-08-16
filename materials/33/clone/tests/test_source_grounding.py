from __future__ import annotations

import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[2]


def test_task3_reconstruction_maps_assets_layout_and_copy_to_current_ea_evidence() -> None:
    observations_path = SITE_ROOT / "source-evidence" / "task3-ea-observations.json"
    provenance_path = SITE_ROOT / "source-evidence" / "task3-provenance.json"
    assert observations_path.is_file()
    assert provenance_path.is_file()

    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    evidence_ids = {item["id"] for item in observations["observations"]}
    assert {item["explorer"] for item in observations["observations"]} == {
        "EA1",
        "EA2",
    }
    assert all(item["sanitized"] is True for item in observations["observations"])

    manifest = json.loads(
        (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
    )
    runtime_assets = {item["runtime_path"] for item in manifest["assets"]}
    assert {item["evidence_kind"] for item in manifest["assets"]} == {"synthetic"}
    asset_provenance = {
        item["runtime_path"]: item for item in provenance["runtime_assets"]
    }
    assert asset_provenance.keys() == runtime_assets
    for mapping in asset_provenance.values():
        assert mapping["reconstruction_kind"] == "synthetic-reconstruction"
        assert mapping["grounded_by"]
        assert set(mapping["grounded_by"]) <= evidence_ids
        assert mapping["source_material_status"] in {
            "reconstructed-from-current-observation",
            "source-asset-unavailable-synthetic-stand-in",
        }

    expected_choices = {
        "layout-shared-chrome",
        "layout-home-hero-cards",
        "layout-browse-categories",
        "layout-search-filter-results",
        "layout-specialization-series",
        "layout-course-detail",
        "layout-auth-entry",
        "layout-support-contact",
        "layout-not-found-recovery",
        "copy-source-observed-labels",
        "copy-offline-disclosures",
    }
    choices = {item["id"]: item for item in provenance["choices"]}
    assert choices.keys() == expected_choices
    for mapping in choices.values():
        assert mapping["grounded_by"]
        assert set(mapping["grounded_by"]) <= evidence_ids

    unavailable = provenance["unavailable_source_material"]
    assert {item["kind"] for item in unavailable} == {
        "third-party-fonts-and-css",
        "third-party-images-and-media",
    }
    assert all(item["status"] == "unavailable" for item in unavailable)
