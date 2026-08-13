from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from websitebench.offline_clone.manifest import (
    ManifestValidationError,
    load_coverage_ledger,
    load_manifest,
    require_frozen_coverage,
)
from websitebench.offline_clone.report import full_report

from .helpers import initialized_site


def _write_dimensions(root: Path, dimensions: list[dict[str, object]]) -> None:
    (root / "scope/coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.coverage.v1",
                "status": "frozen",
                "dimensions": dimensions,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "scope/purpose.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.purpose.v1",
                "status": "frozen",
                "purpose_id": "coverage-test",
                "statement": "Verify independent frozen coverage dimensions.",
                "primary_actor_ids": ["tester"],
                "mainline_journey_ids": ["coverage-mainline"],
                "out_of_scope": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "scope/invariants.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.invariants.v1",
                "status": "frozen",
                "invariants": [
                    {
                        "id": "coverage-denominator-frozen",
                        "statement": "Frozen denominators remain explicit.",
                        "priority": "p0",
                        "journey_ids": ["coverage-mainline"],
                        "positive_test_refs": ["test.coverage.positive"],
                        "negative_test_refs": ["test.coverage.negative"],
                        "coverage_dimension_ids": [dimensions[0]["id"]] if dimensions else [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "scope/journeys.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.journeys.v1",
                "journeys": [
                    {
                        "id": "coverage-mainline",
                        "kind": "success",
                        "priority": "p0",
                        "status": "frozen",
                        "actor": "tester",
                        "steps": ["inspect the frozen denominator"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source_relative = "source-assets/checkpoints/coverage.png"
    source_path = root / source_relative
    source_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1, 1), "white").save(source_path)
    visual_ids = sorted(
        {
            item
            for dimension in dimensions
            if "visual" in dimension.get("required_evidence_kinds", [])
            for item in dimension.get("required_items", [])
            if isinstance(item, str)
        }
    ) or ["coverage-placeholder"]
    (root / "scope/checkpoints.json").write_text(
        json.dumps(
            {
                "schema_version": "offline-clone.checkpoints.v1",
                "status": "frozen",
                "viewports": {},
                "checkpoints": [
                    {
                        "id": checkpoint_id,
                        "visual_contract": {
                            "source_artifact_path": source_relative,
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
                    for checkpoint_id in visual_ids
                ],
            }
        ),
        encoding="utf-8",
    )


def _dimension(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "richly-rendered",
        "label": "Richly rendered entities",
        "unit": "entity",
        "category": "rendering",
        "rationale": "Keep rich rendering independent from reachability.",
        "required_evidence_kinds": ["visual"],
        "required_items": ["item.alpha", "item.beta", "item.gamma"],
        "satisfied_items": [],
    }
    value.update(overrides)
    if value["required_items"] == [] and "required_evidence_kinds" not in overrides:
        value["required_evidence_kinds"] = []
    return value


def test_r1_scope_extensions_and_future_acceptance_obligations_are_valid(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    _write_dimensions(root, [_dimension()])

    purpose_path = root / "scope/purpose.json"
    purpose = json.loads(purpose_path.read_text(encoding="utf-8"))
    purpose.update(
        {
            "secondary_actor_ids": ["reviewer.synthetic-local"],
            "actor_boundaries": [
                {
                    "actor_id": "tester",
                    "authority": "local read-only use",
                    "forbidden": "production mutation",
                }
            ],
            "simulations": ["synthetic local session"],
            "verification_authority": {
                "item": "redistribution rights",
                "status": "open",
            },
            "actors": [{"id": "tester", "label": "Tester"}],
        }
    )
    purpose_path.write_text(json.dumps(purpose), encoding="utf-8")

    invariants_path = root / "scope/invariants.json"
    invariants = json.loads(invariants_path.read_text(encoding="utf-8"))
    invariant = invariants["invariants"][0]
    invariant.pop("positive_test_refs")
    invariant.pop("negative_test_refs")
    invariant["acceptance_obligations"] = [
        "Later candidate evidence must demonstrate the positive behavior.",
        "Later candidate evidence must demonstrate refusal behavior.",
    ]
    invariants_path.write_text(json.dumps(invariants), encoding="utf-8")

    coverage_path = root / "scope/coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["entity_capability_rows"] = [
        {
            "id": "entity.alpha:known",
            "entity": "Alpha",
            "capability": "known",
            "applicability": "required",
            "evidence_tier": "direct",
            "disposition": "Present in the frozen source evidence.",
        }
    ]
    coverage["identity_boundary_rows"] = [
        {
            "id": "identity.tester",
            "identity_item": "tester",
            "boundary_class": "local-only",
            "applicability": "required",
            "evidence_tier": "structural-only",
            "disposition": "No production identity is available.",
        }
    ]
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")

    assert load_manifest(root).data["site_id"] == "example-shop"


def test_coverage_accepts_structured_probe_denominators_and_returns_item_ids(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    probe = {
        "id": "probe::control::save::1",
        "effect_id": "effect::control::save::1",
        "control_id": "control::save::1",
        "matrix_row_id": "save::ready::local::account::desktop",
        "tuple_binding": {
            "route_id": "save",
            "state_id": "ready",
            "variant_id": "local",
            "role_id": "account",
            "viewport_id": "desktop",
        },
        "effect_class": "local-save",
        "source_evidence_kind": "unavailable",
        "local_contract_evidence_kind": "structural-only",
        "action": "save.local",
        "assertion_kind": "atomic-save",
        "atomic_mutation_activation": True,
        "access_truth_row_id": "save.local::account::own",
        "expected_local_mutations": ["saved-item:insert"],
        "expected_local_mutation_count": 1,
        "expected_remote_request_count": 0,
        "expected_remote_effect_count": 0,
        "probe_basis": "Reset, activate once, and compare exact local state.",
        "runtime_disposition": "r1-planned-not-verified",
    }
    _write_dimensions(
        root,
        [
            _dimension(
                id="material-effect-atomic-probes",
                required_evidence_kinds=["network", "full-suite"],
                required_items=[probe],
                denominator_rows=[probe],
            )
        ],
    )
    coverage_path = root / "scope/coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["business_control_effect_probes"] = [probe]
    coverage["discovery_control_effect_probes"] = []
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")

    loaded = load_coverage_ledger(coverage_path)

    assert loaded["dimensions"][0]["required_items"] == [probe["id"]]
    assert loaded["dimensions"][0]["denominator_rows"] == [probe]


def test_p0_future_acceptance_obligations_cannot_be_empty(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    _write_dimensions(root, [_dimension()])
    invariants_path = root / "scope/invariants.json"
    invariants = json.loads(invariants_path.read_text(encoding="utf-8"))
    invariant = invariants["invariants"][0]
    invariant.pop("positive_test_refs")
    invariant.pop("negative_test_refs")
    invariant["acceptance_obligations"] = []
    invariants_path.write_text(json.dumps(invariants), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="not valid under any"):
        load_manifest(root)


def test_coverage_rejects_satisfied_items_outside_required_set(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    _write_dimensions(
        root,
        [_dimension(satisfied_items=["item.alpha", "item.not-required"])],
    )
    with pytest.raises(
        ManifestValidationError, match="satisfied item is not required: item.not-required"
    ):
        load_manifest(root)


def test_source_coverage_must_be_explicitly_frozen_and_nonempty(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    manifest = load_manifest(root)
    with pytest.raises(ManifestValidationError, match="status 'frozen'"):
        require_frozen_coverage(manifest)

    path = root / "scope/coverage.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["status"] = "frozen"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="non-empty"):
        load_manifest(root)


def test_empty_dimension_denominator_requires_explicit_na_rationale(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    _write_dimensions(
        root,
        [
            _dimension(
                id="not-applicable",
                required_items=[],
                satisfied_items=[],
                rationale=None,
            )
        ],
    )
    with pytest.raises(ManifestValidationError, match="N/A rationale"):
        load_manifest(root)


def test_frozen_coverage_cannot_consist_only_of_na_dimensions(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    _write_dimensions(
        root,
        [
            _dimension(
                id="not-applicable",
                required_items=[],
                satisfied_items=[],
                rationale="N/A: this optional capability is outside the frozen purpose.",
            )
        ],
    )
    with pytest.raises(ManifestValidationError, match="non-empty denominator"):
        load_manifest(root)


@pytest.mark.parametrize(
    "dimensions, message",
    [
        (
            [_dimension(required_items=["item.alpha", "item.alpha"])],
            "duplicate item id: item.alpha",
        ),
        (
            [_dimension(), _dimension(label="Another label")],
            "duplicate dimension id: richly-rendered",
        ),
    ],
)
def test_coverage_rejects_duplicate_item_or_dimension_ids(
    tmp_path: Path,
    dimensions: list[dict[str, object]],
    message: str,
) -> None:
    root = initialized_site(tmp_path)
    _write_dimensions(root, dimensions)
    with pytest.raises(ManifestValidationError, match=message):
        load_manifest(root)


def test_report_computes_each_coverage_denominator_independently(tmp_path: Path) -> None:
    """Each dimension counts against its own required set, never a shared total.

    The report states denominators only. A frozen ledger must leave
    `satisfied_items` empty -- per-kind acceptance evidence owned the
    numerators, and that layer is gone -- so a numerator here would be a metric
    that can never move.
    """

    root = initialized_site(tmp_path)
    _write_dimensions(
        root,
        [
            _dimension(),
            _dimension(
                id="durably-verified",
                label="Durably verified mutations",
                unit="mutation",
                category="durability",
                rationale="A separate denominator for restart-safe writes.",
                required_items=["save.success", "save.retry"],
                satisfied_items=[],
            ),
        ],
    )

    coverage = full_report(load_manifest(root))["coverage"]

    assert coverage["dimensions"][0] == {
        "id": "richly-rendered",
        "unit": "entity",
        "required_items": ["item.alpha", "item.beta", "item.gamma"],
        "denominator": 3,
    }
    assert coverage["dimensions"][1]["denominator"] == 2
    assert coverage["denominator_total"] == 5
    assert coverage["ledger_status"] == "frozen"
    assert require_frozen_coverage(load_manifest(root))["status"] == "frozen"
