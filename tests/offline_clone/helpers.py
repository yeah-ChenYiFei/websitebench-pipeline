from __future__ import annotations

import json
from pathlib import Path

import yaml
from PIL import Image

from websitebench.offline_clone.manifest import initialize_site, load_manifest


def initialized_site(tmp_path: Path) -> Path:
    root = tmp_path / "example-site"
    initialize_site(
        root,
        site_id="example-shop",
        display_name="Example Shop",
        source_url="https://example.test/",
    )
    return root


def configure_passing_diagnostics(root: Path) -> None:
    path = root / "clone.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    source_checkpoint_relative = "source-assets/checkpoints/home.default.png"
    source_checkpoint = root / source_checkpoint_relative
    source_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1, 1), "white").save(source_checkpoint)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    coverage = {
        "schema_version": "offline-clone.coverage.v1",
        "status": "frozen",
        "dimensions": [
            {
                "id": "reachable",
                "label": "Reachable states",
                "unit": "route-state",
                "category": "reachability",
                "required_evidence_kinds": ["visual"],
                "required_items": ["home.default"],
                "satisfied_items": [],
            }
        ],
    }
    (root / "scope/coverage.json").write_text(
        json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
    )
    (root / "scope/purpose.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.purpose.v1",
                "status": "frozen",
                "purpose_id": "primary-purpose",
                "statement": "Let a visitor complete the representative mainline journey.",
                "primary_actor_ids": ["visitor"],
                "mainline_journey_ids": ["home-mainline"],
                "out_of_scope": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "scope/invariants.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.invariants.v1",
                "status": "frozen",
                "invariants": [
                    {
                        "id": "mainline-reachable",
                        "statement": "The representative mainline remains reachable.",
                        "priority": "p0",
                        "journey_ids": ["home-mainline"],
                        "positive_test_refs": ["test.example"],
                        "negative_test_refs": ["test.failure.example"],
                        "coverage_dimension_ids": ["reachable"],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "scope/journeys.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.journeys.v1",
                "journeys": [
                    {
                        "id": "home-mainline",
                        "kind": "success",
                        "priority": "p0",
                        "status": "frozen",
                        "actor": "visitor",
                        "steps": ["open the representative home state"],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    backend_model_path = root / "backend/model.json"
    backend_model = json.loads(backend_model_path.read_text(encoding="utf-8"))
    backend_model["status"] = "verified"
    for proof in backend_model["database"]["proofs"]:
        proof["status"] = "verified"
        proof["evidence"] = ["test.example"]
    obligations = (
        "valid",
        "invalid",
        "duplicate",
        "stale",
        "foreign-owner",
        "unauthorized-role",
        "restart",
        "migration",
        "concurrency",
    )
    for capability in backend_model["capabilities"]:
        capability["implementation_status"] = "verified"
        capability["journey_ids"] = ["home-mainline"]
        capability["invariant_ids"] = ["mainline-reachable"]
        capability["proofs"]["evidence"] = {
            obligation: ["test.example"] for obligation in obligations
        }
        capability["proofs"].pop("planned", None)
    backend_model_path.write_text(
        json.dumps(backend_model, indent=2) + "\n", encoding="utf-8"
    )
    (root / "scope/checkpoints.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.checkpoints.v1",
                "status": "frozen",
                "viewports": {},
                "checkpoints": [
                    {
                        "id": "home.default",
                        "visual_contract": {
                            "source_artifact_path": source_checkpoint_relative,
                            "viewport": {"width": 1, "height": 1},
                            "comparison_region": {
                                "x": 0,
                                "y": 0,
                                "width": 1,
                                "height": 1,
                            },
                            "metric": "pixel-mae-similarity-v1",
                            "threshold": 0.9,
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def add_closed_png_asset(root: Path) -> None:
    source = root / "source-assets/images/logo.png"
    runtime = root / "clone/static/assets/logo.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6), "#ff9900").save(source)
    runtime.write_bytes(source.read_bytes())
    data = source.read_bytes()
    manifest = {
        "schema_version": "offline-clone.assets.v1",
        "snapshot_id": "example-shop-20260722",
        "created_at": "2026-07-22T00:00:00Z",
        "remote_runtime_policy": "forbidden",
        "closure_status": "declared",
        "no_assets_reason": None,
        "assets": [
            {
                "id": "logo",
                "priority": "p0",
                "required": True,
                "source_path": "source-assets/images/logo.png",
                "runtime_path": "clone/static/assets/logo.png",
                "bytes": len(data),
                "mime_type": "image/png",
                "dimensions": {"width": 8, "height": 6},
                "referenced_by": ["route:home/header"],
                "evidence_kind": "current-direct",
                "source_url": "https://example.test/logo.png",
                "capture_id": "home-desktop",
            }
        ],
    }
    (root / "source-assets/manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    load_manifest(root)
