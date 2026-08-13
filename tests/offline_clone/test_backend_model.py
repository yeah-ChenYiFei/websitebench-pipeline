from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.offline_clone.backend_model import (
    BackendModelError,
    load_backend_model,
    validate_backend_scope_references,
)
from websitebench.offline_clone.manifest import (
    load_manifest,
)

from .helpers import add_closed_png_asset, configure_passing_diagnostics, initialized_site


def _model(root: Path) -> tuple[Path, dict[str, object]]:
    path = root / "backend/model.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_initialized_backend_model_is_fail_closed_and_common(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    manifest = load_manifest(root)
    model = load_backend_model(
        manifest.backend_model_path,
        expected_site_id="example-shop",
    )

    assert model["status"] == "draft"
    assert set(model["common_capabilities"]) == {
        "account_registration",
        "account_sign_in",
        "session_lifecycle",
        "password_recovery",
        "email_delivery",
    }
    assert set(model["auth_semantics"]["mail_statuses"]) == {
        "LOCAL_ONLY",
        "SMTP_PENDING",
        "SMTP_SENT",
        "SMTP_FAILED",
    }
    with pytest.raises(BackendModelError, match="requires verified"):
        load_backend_model(
            manifest.backend_model_path,
            expected_site_id="example-shop",
            require_verified=True,
        )


def test_a_draft_backend_model_is_refused_where_verification_is_required(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    model_path, model = _model(root)
    model["status"] = "draft"
    model_path.write_text(json.dumps(model), encoding="utf-8")

    with pytest.raises(BackendModelError, match="verified"):
        load_backend_model(
            model_path, expected_site_id="example-shop", require_verified=True
        )


def test_backend_model_requires_complete_proof_matrix(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    model_path, model = _model(root)
    model["capabilities"][0]["proofs"]["evidence"].pop("foreign-owner")
    model_path.write_text(json.dumps(model), encoding="utf-8")

    with pytest.raises(BackendModelError, match="foreign-owner"):
        load_backend_model(
            model_path,
            expected_site_id="example-shop",
            require_verified=True,
        )


def test_draft_backend_model_accepts_exact_planned_proof_classification(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    model_path, _ = _model(root)

    loaded = load_backend_model(
        model_path,
        expected_site_id="example-shop",
    )
    assert all(
        len(capability["proofs"]["planned"]) == 9
        for capability in loaded["capabilities"]
    )


def test_backend_model_accepts_a_hash_bound_deterministic_seed_manifest(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    model_path, model = _model(root)
    model["database"]["deterministic_seed_manifest"] = {
        "path": "scope/deterministic-seed.json",
        "sha256": "a" * 64,
        "seed_id": "example-seed-v1",
        "authoritative_entity_count": 1,
        "reset_probe_ids": ["seed-reset.exact-reseed"],
        "migration_log_representation": "physical-sqlite-rows",
    }
    model_path.write_text(json.dumps(model), encoding="utf-8")

    assert load_backend_model(model_path)["database"][
        "deterministic_seed_manifest"
    ]["sha256"] == "a" * 64

    model["database"]["deterministic_seed_manifest"]["sha256"] = "not-a-digest"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    with pytest.raises(BackendModelError, match="does not match"):
        load_backend_model(model_path)


def test_backend_model_v2_requires_one_three_dimensional_assessment_per_capability(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    model_path, model = _model(root)
    model["schema_version"] = "offline-clone.backend-model.v2"
    model["parity_assessments"] = [
        {
            "capability_id": capability["id"],
            "functional": {"status": "partial", "source_tier": "local-fixture", "evidence_refs": [], "known_differences": ["machine verification pending"]},
            "behavioral": {"status": "unavailable", "source_tier": "configured-unavailable", "evidence_refs": [], "known_differences": ["source journey unavailable"]},
            "data_model": {"status": "complete", "source_tier": "local-fixture", "evidence_refs": [], "known_differences": []},
            "journey_frozen": False,
            "invariant_frozen": False,
            "evidence_hashes": {},
        }
        for capability in model["capabilities"]
    ]
    model_path.write_text(json.dumps(model), encoding="utf-8")
    assert load_backend_model(model_path)["schema_version"].endswith(".v2")
    model["parity_assessments"].pop()
    model_path.write_text(json.dumps(model), encoding="utf-8")
    with pytest.raises(BackendModelError, match="missing capabilities"):
        load_backend_model(model_path)


def test_backend_model_rejects_overlapping_proof_classifications(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    model_path, model = _model(root)
    capability = model["capabilities"][0]
    capability["proofs"]["evidence"]["valid"] = ["full-suite"]
    model_path.write_text(json.dumps(model), encoding="utf-8")

    with pytest.raises(
        BackendModelError,
        match="cannot be classified more than once",
    ):
        load_backend_model(model_path, expected_site_id="example-shop")


def test_backend_model_rejects_duplicate_common_capability_mapping(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    model_path, model = _model(root)
    model["common_capabilities"]["password_recovery"] = model[
        "common_capabilities"
    ]["account_registration"]
    model_path.write_text(json.dumps(model), encoding="utf-8")

    with pytest.raises(BackendModelError, match="distinct capability"):
        load_backend_model(model_path, expected_site_id="example-shop")


def test_backend_model_accepts_direct_registration_and_not_applicable_mail(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    model_path, model = _model(root)
    model["auth_semantics"]["registration_account_creation"] = "direct-password"
    model["auth_semantics"]["verification_challenge_storage"] = "not-applicable"
    model["auth_semantics"]["password_reset_enumeration"] = "not-applicable"
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
    common = model["common_capabilities"]
    for field in ("password_recovery", "email_delivery"):
        capability = next(
            item for item in model["capabilities"] if item["id"] == common[field]
        )
        capability["semantic_profile"] = "not-applicable-v1"
        capability["implementation_status"] = "not-applicable"
        capability.pop("entities", None)
        capability.pop("state_machine", None)
        capability.pop("server_authorities", None)
        capability["proofs"] = {
            "evidence": {},
            "planned": [],
            "not_applicable": [
                {
                    "obligation": obligation,
                    "rationale": "The capability is explicitly outside this site's frozen scope.",
                }
                for obligation in obligations
            ],
        }
    model_path.write_text(json.dumps(model), encoding="utf-8")

    loaded = load_backend_model(model_path, expected_site_id="example-shop")
    assert loaded["auth_semantics"]["registration_account_creation"] == "direct-password"


def test_not_applicable_semantic_profile_requires_complete_classification(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    model_path, model = _model(root)
    capability = next(
        item
        for item in model["capabilities"]
        if item["id"] == model["common_capabilities"]["password_recovery"]
    )
    capability["semantic_profile"] = "not-applicable-v1"
    capability["implementation_status"] = "not-applicable"
    model_path.write_text(json.dumps(model), encoding="utf-8")

    with pytest.raises(BackendModelError, match="classify all proof obligations"):
        load_backend_model(model_path, expected_site_id="example-shop")


def test_backend_scope_references_fail_closed_for_unbound_or_unknown_ids(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    _, model = _model(root)

    unbound = validate_backend_scope_references(
        model,
        journey_ids=set(),
        invariant_ids=set(),
    )
    assert any("must bind at least one R1 journey" in item for item in unbound)
    assert any("must bind at least one R1 invariant" in item for item in unbound)

    for capability in model["capabilities"]:
        capability["journey_ids"] = ["auth.registration.success"]
        capability["invariant_ids"] = ["identity.local-account-authority"]
    unknown = validate_backend_scope_references(
        model,
        journey_ids={"another.journey"},
        invariant_ids={"another.invariant"},
    )
    assert any("unknown R1 journey 'auth.registration.success'" in item for item in unknown)
    assert any(
        "unknown R1 invariant 'identity.local-account-authority'" in item
        for item in unknown
    )


def test_deep_backend_scope_requires_exact_proof_bindings(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    _, model = _model(root)
    capability = model["capabilities"][0]
    capability.pop("semantic_profile", None)
    model["database"]["entity_inventory"] = [
        {
            "name": "local-account",
            "storage_name": "local_accounts",
            "owner_scope": "account",
            "reset_disposition": "delete",
            "backup_restore": True,
            "lifecycle_obligations": [
                "data-location",
                "schema-migration",
                "deterministic-reset",
                "restart-persistence",
                "backup-restore",
                "concurrency",
            ],
        }
    ]
    capability["entities"] = [
        {
            "name": "local-account",
            "identity": "normalized email plus immutable account id",
            "owner_scope": "account",
            "persistence": "durable",
        }
    ]
    capability["state_machine"] = {
        "kind": "entity-lifecycle",
        "states": ["pending", "active"],
        "transitions": [
            {"from": "pending", "to": "active", "trigger": "verify"}
        ],
    }
    capability["server_authorities"] = ["server resolves account ownership"]
    capability["journey_ids"] = ["auth.registration.success"]
    capability["invariant_ids"] = ["identity.local-account-authority"]
    model["capabilities"] = [capability]

    missing = validate_backend_scope_references(
        model,
        journey_ids={"auth.registration.success"},
        invariant_ids={"identity.local-account-authority"},
    )
    assert any("must bind all nine proof obligations" in item for item in missing)

    binding = {
        "applicability": "required",
        "journey_ids": ["auth.registration.success"],
        "invariant_ids": ["identity.local-account-authority"],
        "entity_names": ["local-account"],
        "owner_scope": "account",
        "identity_tuple": "account plus command and expected version",
        "expected_server_result": "one durable mutation or a stable refusal",
    }
    capability["proof_bindings"] = [
        {"obligation": obligation, **binding}
        for obligation in (
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
    ]
    assert not validate_backend_scope_references(
        model,
        journey_ids={"auth.registration.success"},
        invariant_ids={"identity.local-account-authority"},
    )

    capability["proof_bindings"][1]["journey_ids"] = ["unknown.journey"]
    capability["proof_bindings"][2]["entity_names"] = ["unknown-entity"]
    invalid = validate_backend_scope_references(
        model,
        journey_ids={"auth.registration.success"},
        invariant_ids={"identity.local-account-authority"},
    )
    assert any("must also be bound by the capability" in item for item in invalid)
    assert any("unknown capability entity 'unknown-entity'" in item for item in invalid)
