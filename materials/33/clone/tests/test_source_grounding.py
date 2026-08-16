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
    task3_assets = [
        item for item in manifest["assets"] if item["id"].startswith("task3-")
    ]
    runtime_assets = {item["runtime_path"] for item in task3_assets}
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


def test_checkout_verify_recipes_use_named_login_and_reach_distinct_states() -> None:
    """Catch authenticated checkout checkpoints that stop at the plan page."""

    driver = json.loads(
        (SITE_ROOT / "scope" / "verify.json").read_text(encoding="utf-8")
    )
    session = driver["session"]
    assert session["post"] == "/auth/login"
    assert session["expect_status"] == [303]
    assert session["accounts"] == {
        "empty-learner": {
            "form": {
                "email": "empty@coursera.test",
                "password": "Empty-Learner-33",
            },
            "routes": ["checkout"],
        }
    }

    validation = driver["states"]["checkout.validation"]
    review = driver["states"]["checkout.review"]
    assert validation["session"] == review["session"] == "empty-learner"
    assert all("fixture=" not in str(step) for step in validation["steps"])
    assert all("fixture=" not in str(step) for step in review["steps"])

    validation_actions = {next(iter(step)) for step in validation["steps"]}
    assert {"eval", "click", "expect"} <= validation_actions
    assert any(
        step.get("expect") == 'h1:has-text("Checkout could not continue")'
        for step in validation["steps"]
    )
    assert sum("click" in step for step in review["steps"]) >= 2
    assert any(
        step.get("expect") == 'h1:has-text("Review inferred total")'
        for step in review["steps"]
    )
    assert any(
        step.get("expect")
        == 'input[name="scenario_id"][value="sandbox-approved"]'
        for step in review["steps"]
    )


def test_task3_css_identity_is_unchanged_and_checkout_css_is_task5_owned() -> None:
    """Catch checkout styling being folded into the historical Task 3 asset."""

    manifest = json.loads(
        (SITE_ROOT / "source-assets" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assets = {item["id"]: item for item in manifest["assets"]}
    task3 = assets["task3-components-css"]
    assert task3["source_path"] == "source-assets/task3/components.css"
    assert task3["runtime_path"] == "clone/static/components.css"
    assert task3["bytes"] == 3181
    task3_source = (SITE_ROOT / task3["source_path"]).read_bytes()
    task3_runtime = (SITE_ROOT / task3["runtime_path"]).read_bytes()
    assert task3_source == task3_runtime
    assert len(task3_source) == 3181
    assert b"checkout-shell" not in task3_source

    task5 = assets["task5-checkout-css"]
    assert task5["source_path"] == "source-assets/task5/checkout.css"
    assert task5["runtime_path"] == "clone/static/checkout.css"
    task5_source = (SITE_ROOT / task5["source_path"]).read_bytes()
    task5_runtime = (SITE_ROOT / task5["runtime_path"]).read_bytes()
    assert task5_source == task5_runtime
    assert len(task5_source) == task5["bytes"]
    assert b"checkout-shell" in task5_source

    provenance = json.loads(
        (SITE_ROOT / "source-evidence" / "task5-provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["runtime_assets"] == [
        {
            "asset_id": "task5-checkout-css",
            "runtime_path": "clone/static/checkout.css",
            "reconstruction_kind": "synthetic-reconstruction",
            "grounded_by": ["task5-safe-local-checkout-design"],
            "source_material_status": "task5-owned-synthetic-offline-style",
        }
    ]
