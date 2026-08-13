from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.site_compiler.canonical import canonical_json_bytes, sha256_file
from websitebench.workflow.cli import main as workflow_main
from websitebench.workflow.errors import WorkflowError
from websitebench.workflow.payment_scope import (
    payment_scope_subject_sha256,
    validate_payment_scope,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _proposal(root: Path) -> Path:
    inputs = [
        "websitebench/site-profiles/alpha/site.json",
        "materials/alpha/scope/purpose.json",
        "materials/alpha/backend/runtime.json",
        "materials/alpha/backend/model.json",
        "websitebench/capability-packs/payment/pack.json",
    ]
    for path in inputs:
        value: object = {"path": path}
        if path.endswith("site.json"):
            value = {
                "site_id": "alpha",
                "blockers": [{"id": "ALPHA-PAYMENT-R1"}, {"id": "ALPHA-R1"}],
                "classification": {"overlay_pack_ids": ["auth"]},
            }
        elif path.endswith("runtime.json"):
            value = {
                "site": {"id": "alpha"},
                "payments": {
                    "default_adapter": "local-sandbox",
                    "currency": "USD",
                    "local_sandbox": {
                        "scenarios": [
                            {"id": "approve", "outcome": "approved"},
                            {"id": "decline", "outcome": "declined"},
                            {"id": "retry", "outcome": "retryable"},
                        ]
                    },
                    "stripe_test": None,
                },
                "deployment": {
                    "profiles": {
                        "offline": {"payment_adapter": "local-sandbox"}
                    }
                },
                "mail": {
                    "sender": {"display_name": "Alpha Learning"},
                    "purposes": {
                        "registration": {},
                        "order-confirmation": {},
                    },
                },
            }
        elif path.endswith("model.json"):
            value = {
                "site_id": "alpha",
                "capabilities": [
                    {
                        "id": "course-payment",
                        "entities": [
                            {"name": "learner"},
                            {"name": "course-run"},
                            {"name": "order"},
                        ],
                    }
                ],
            }
        elif path.endswith("payment/pack.json"):
            value = {"pack_id": "payment"}
        _write(root / path, value)
    value = {
        "schema_version": "websitebench.payment-scope.v2",
        "proposal_id": "alpha-payment-scope-1",
        "site_id": "alpha",
        "display_name": "Alpha Learning",
        "current_inputs": [
            {"path": path, "sha256": sha256_file(root / path)} for path in inputs
        ],
        "profile_change": {
            "overlay_pack_id": "payment",
            "candidate_blocker_id": "ALPHA-PAYMENT-R1",
            "retained_blocker_ids": ["ALPHA-R1"],
        },
        "frozen_journeys": [
            {"id": "verified-checkout", "description": "Buy a course run."}
        ],
        "frozen_entities": ["learner", "course-run", "order"],
        "payment_contract": {
            "default_adapter": "local-sandbox",
            "optional_adapter": "stripe-test",
            "live_payments_allowed": False,
            "accepted_client_payment_input": "opaque-scenario-id-only",
            "credential_fields_allowed": False,
            "currency": "USD",
            "amount_source": "server price snapshot",
            "owner": "authenticated learner",
            "fingerprint": "canonical checkout snapshot",
            "final_commit": "commit payment result and order atomically",
        },
        "mail_brand": {
            "shared_bare_sender_domain_allowed": True,
            "sender_display_name": "Alpha Learning",
            "purposes": ["registration", "order-confirmation"],
            "must_differ_from": [
                {
                    "site_id": "amazon",
                    "fields": ["sender_display_name", "subject", "body"],
                }
            ],
        },
        "site_isolation": {
            "database_scope": "site-exclusive",
            "site_binding_required": True,
            "session_cookie_name": "__Host-websitebench-alpha-session",
            "redis_namespace": "site/alpha",
            "webhook_secret_scope": "site-exclusive",
            "cross_site_account_sharing": False,
        },
        "proof_obligations": ["Reject cross-site account and payment reuse."],
        "scope_subject_sha256": "0" * 64,
    }
    value["scope_subject_sha256"] = payment_scope_subject_sha256(value)
    path = root / "materials/alpha/scope/payment-scope.json"
    _write(path, value)
    return path


def test_machine_scope_passes_and_cli_has_only_new_command(tmp_path: Path) -> None:
    path = _proposal(tmp_path)
    result = validate_payment_scope(tmp_path, path.relative_to(tmp_path))
    assert result["status"] == "passed"
    assert result["payment_overlay_candidate"] == "payment"
    assert workflow_main([
        "check-payment-scope",
        "--repo-root", str(tmp_path),
        "--proposal", str(path.relative_to(tmp_path)),
    ]) == 0
    with pytest.raises(SystemExit):
        workflow_main(["payment-scope-gate"])


def test_existing_payment_overlay_can_be_reaudited_without_fake_blocker(
    tmp_path: Path,
) -> None:
    path = _proposal(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    profile_path = tmp_path / "websitebench/site-profiles/alpha/site.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["blockers"] = []
    profile["classification"]["overlay_pack_ids"].append("payment")
    _write(profile_path, profile)
    for item in value["current_inputs"]:
        if item["path"] == "websitebench/site-profiles/alpha/site.json":
            item["sha256"] = sha256_file(profile_path)
    value["profile_change"] = {
        "audit_mode": "existing-overlay-audit",
        "overlay_pack_id": "payment",
        "candidate_blocker_id": None,
        "retained_blocker_ids": [],
    }
    value["scope_subject_sha256"] = payment_scope_subject_sha256(value)
    _write(path, value)

    result = validate_payment_scope(tmp_path, path.relative_to(tmp_path))
    assert result["status"] == "passed"
    assert result["payment_scope_mode"] == "existing-overlay-audit"

    profile["classification"]["overlay_pack_ids"].remove("payment")
    _write(profile_path, profile)
    for item in value["current_inputs"]:
        if item["path"] == "websitebench/site-profiles/alpha/site.json":
            item["sha256"] = sha256_file(profile_path)
    value["scope_subject_sha256"] = payment_scope_subject_sha256(value)
    _write(path, value)
    with pytest.raises(WorkflowError, match="requires the current profile"):
        validate_payment_scope(tmp_path, path.relative_to(tmp_path))


def test_manifest_native_payment_scope_does_not_require_legacy_profile(
    tmp_path: Path,
) -> None:
    path = _proposal(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    profile_path = "websitebench/site-profiles/alpha/site.json"
    manifest_path = "materials/alpha/clone.yaml"
    manifest = {
        "schema_version": "offline-clone.manifest.v2",
        "site_id": "alpha",
        "display_name": "Alpha Learning",
        "state_model": "stateful",
        "source": {
            "origins": ["https://alpha.example.test"],
            "baseline": {
                "locale": "en-US",
                "currency": "USD",
                "delivery_region": None,
                "timezone": None,
                "auth_state": "anonymous",
                "tenant": None,
                "workspace": None,
                "role": None,
                "capabilities": [],
                "feature_flags": [],
                "user_agent": None,
                "viewport": None,
                "capture_id": None,
            },
            "capture_policy": {
                "safe_methods": ["GET", "HEAD"],
                "runtime_remote_requests": "forbidden",
            },
        },
        "scope": {
            name: f"scope/{name}.json" + ("l" if name == "claims" else "")
            for name in (
                "purpose",
                "invariants",
                "routes",
                "journeys",
                "checkpoints",
                "claims",
                "coverage",
            )
        },
        "paths": {
            "candidate_root": "clone",
            "candidate_excludes": [],
            "asset_manifest": "source-assets/manifest.json",
            "backend_model": "backend/model.json",
            "artifact_root": "artifacts/offline-clone",
            "state_file": ".clone-harness/state.json",
            "trajectory_file": ".clone-harness/trajectory.jsonl",
        },
    }
    _write(tmp_path / manifest_path, manifest)
    for item in value["current_inputs"]:
        if item["path"] == profile_path:
            item["path"] = manifest_path
            item["sha256"] = sha256_file(tmp_path / manifest_path)
    value["profile_change"] = {
        "audit_mode": "manifest-native-audit",
        "overlay_pack_id": "payment",
        "candidate_blocker_id": None,
        "retained_blocker_ids": [],
    }
    value["scope_subject_sha256"] = payment_scope_subject_sha256(value)
    _write(path, value)

    result = validate_payment_scope(tmp_path, path.relative_to(tmp_path))
    assert result["payment_scope_mode"] == "manifest-native-audit"


def test_scope_is_hash_bound_and_live_payment_is_rejected(tmp_path: Path) -> None:
    path = _proposal(tmp_path)
    purpose = tmp_path / "materials/alpha/scope/purpose.json"
    _write(purpose, {"changed": True})
    with pytest.raises(WorkflowError, match="current input sha256 mismatch"):
        validate_payment_scope(tmp_path, path.relative_to(tmp_path))


def test_scope_cross_checks_runtime_payment_and_mail_contract(
    tmp_path: Path,
) -> None:
    path = _proposal(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    runtime_path = tmp_path / "materials/alpha/backend/runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["payments"]["currency"] = "EUR"
    runtime["mail"]["sender"]["display_name"] = "Other Brand"
    _write(runtime_path, runtime)
    for item in value["current_inputs"]:
        if item["path"] == "materials/alpha/backend/runtime.json":
            item["sha256"] = sha256_file(runtime_path)
    value["scope_subject_sha256"] = payment_scope_subject_sha256(value)
    _write(path, value)
    with pytest.raises(
        WorkflowError, match="currency does not match|sender does not match"
    ):
        validate_payment_scope(tmp_path, path.relative_to(tmp_path))

    path = _proposal(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["payment_contract"]["live_payments_allowed"] = True
    _write(path, value)
    with pytest.raises(ValueError, match="False was expected"):
        validate_payment_scope(tmp_path, path.relative_to(tmp_path))


def test_scope_rejects_cross_site_cookie_and_mail_identity(tmp_path: Path) -> None:
    path = _proposal(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["site_isolation"]["session_cookie_name"] = (
        "__Host-websitebench-other-session"
    )
    value["scope_subject_sha256"] = payment_scope_subject_sha256(value)
    _write(path, value)
    with pytest.raises(WorkflowError, match="site-derived"):
        validate_payment_scope(tmp_path, path.relative_to(tmp_path))

    path = _proposal(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["mail_brand"]["must_differ_from"][0]["site_id"] = "alpha"
    value["scope_subject_sha256"] = payment_scope_subject_sha256(value)
    _write(path, value)
    with pytest.raises(WorkflowError, match="same site"):
        validate_payment_scope(tmp_path, path.relative_to(tmp_path))


def test_canonical_and_bundled_payment_scope_schemas_are_identical() -> None:
    repository = Path(__file__).resolve().parents[2]
    name = "websitebench-payment-scope-v2.schema.json"
    assert (repository / "websitebench/schemas" / name).read_bytes() == (
        repository / "src/websitebench/viewer/_schemas" / name
    ).read_bytes()
