from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.site_compiler.cli import build_parser, main
from websitebench.site_compiler.compile import CompilerWorkspace, write_compilation
from websitebench.site_compiler.diagnostics import SiteCompilerError

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "generic-v2"
INVENTORY = FIXTURE_ROOT / "platform-inventory.json"
PROFILES = FIXTURE_ROOT / "profiles"
PACKS = REPO_ROOT / "websitebench" / "capability-packs"


def _workspace() -> CompilerWorkspace:
    return CompilerWorkspace.load(inventory_path=INVENTORY, packs_root=PACKS)


def test_generic_profile_compiles_complete_frontend_backend_and_invalidation_plan() -> None:
    result = _workspace().compile(
        profile_path=PROFILES / "alpha-market" / "site.json",
        target="release",
    )
    ir = result.plan["site_ir"]
    assert ir["site"]["site_id"] == "alpha-market"
    assert ir["site"]["inventory_id"] == 1001
    assert ir["classification"]["evidence_tier"] == "inferred"
    assert set(result.__dataclass_fields__) == {"plan", "explanation", "inputs"}
    assert result.plan["evidence_boundary"] == {
        "inventory_metadata": "structural-provenance-only",
        "pack_classification": "machine-inferred",
        "generated_source_claims": "forbidden",
        "candidate_as_source_truth": "forbidden",
    }
    backend = ir["backend_model_seed"]
    assert backend["database"]["site_isolation"] == "one-database-per-site"
    assert backend["auth_semantics"]["smtp_delivery_ceiling"] == 3
    capability_ids = {item["id"] for item in backend["capabilities"]}
    assert {
        "account-registration",
        "account-sign-in",
        "session-lifecycle",
        "password-recovery",
        "email-delivery",
        "payment-lifecycle",
        "reviews-reputation-lifecycle",
    } <= capability_ids
    assert any(item.startswith("retail-commerce-ordering") for item in capability_ids)
    for capability in backend["capabilities"]:
        assert capability["implementation_status"] == "planned"
        assert capability.get("semantic_profile") or (
            capability["entities"]
            and capability["state_machine"]["states"]
            and capability["server_authorities"]
        )

    assert ir["frontend_contract"]["route_families"]
    invalidation = {
        item["node_id"]: item["invalidates_from"]
        for item in result.plan["artifact_graph"]
    }
    assert invalidation["scope-contract-plan"] == "scope-validation"
    assert invalidation["frontend-plan"] == "frontend-validation"
    assert invalidation["backend-plan"] == "semantic-validation"
    assert invalidation["release-plan"] == "release-validation"


def test_generic_v2_inventory_compiles_two_sparse_high_ids() -> None:
    workspace = _workspace()
    paths = sorted(PROFILES.glob("*/site.json"))
    results = [
        workspace.compile(profile_path=path, target="release") for path in paths
    ]

    assert workspace.inventory.data["schema_version"] == (
        "offline-clone.platform-inventory.v2"
    )
    assert set(workspace.inventory.by_id) == {1001, 9007}
    assert {source["source_id"] for source in workspace.inventory.data["provenance"]["sources"]} == {
        "fixture-catalog",
        "fixture-overrides",
    }
    assert {result.plan["site_ir"]["site"]["site_id"] for result in results} == {
        "alpha-market",
        "beta-learning",
    }
    assert {
        result.plan["site_ir"]["classification"]["batch_family_id"]
        for result in results
    } == {"commerce-marketplace", "learning-community-content"}
    assert sum(bool(result.plan["site_ir"]["blockers"]) for result in results) == 1


def test_inventory_summary_counts_are_checked_semantically(tmp_path: Path) -> None:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    inventory["summary"]["category_counts"]["Retail"] = 2
    path = tmp_path / "platform-inventory.json"
    path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(SiteCompilerError, match="category_counts"):
        CompilerWorkspace.load(inventory_path=path, packs_root=PACKS)


def test_invalid_source_origin_is_preserved_as_a_blocker_not_guessed() -> None:
    result = _workspace().compile(
        profile_path=PROFILES / "beta-learning" / "site.json",
        target="scope",
    )
    site = result.plan["site_ir"]["site"]
    assert site["official_url"] == "https://beta.example.test/"
    assert site["source_origin_status"] == "invalid-in-inventory"
    assert site["source_origins"] == []
    assert {blocker["kind"] for blocker in result.plan["site_ir"]["blockers"]} == {
        "source-data-quality"
    }


def test_compilation_is_byte_deterministic_and_check_detects_drift(
    tmp_path: Path,
) -> None:
    result = _workspace().compile(
        profile_path=PROFILES / "alpha-market" / "site.json",
        target="backend",
    )
    first = write_compilation(result, output_dir=tmp_path)
    assert first["status"] == "written"
    assert write_compilation(result, output_dir=tmp_path, check=True)["status"] == (
        "current"
    )

    plan = tmp_path / "alpha-market.compiled.json"
    plan.write_bytes(plan.read_bytes() + b" ")
    with pytest.raises(SiteCompilerError, match="plan"):
        write_compilation(result, output_dir=tmp_path, check=True)


def test_typed_override_applies_to_current_structured_content(tmp_path: Path) -> None:
    profile = json.loads(
        (PROFILES / "alpha-market" / "site.json").read_text(encoding="utf-8")
    )
    profile["overrides"] = [
        {
            "op": "remove-item-with-rationale",
            "target": "backend.capabilities",
            "selector": {"id": "payment-lifecycle"},
            "rationale": "payment is out of scope for this profile",
        }
    ]
    profile_path = tmp_path / "site.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    result = _workspace().compile(profile_path=profile_path, target="backend")
    capability_ids = {
        item["id"] for item in result.plan["site_ir"]["backend_model_seed"]["capabilities"]
    }
    assert "payment-lifecycle" not in capability_ids
    assert all(
        "sha256" not in key
        for override in result.plan["site_ir"]["applied_overrides"]
        for key in override
    )


def test_cli_check_and_explain_one_generic_profile(
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = [
        "--inventory",
        str(INVENTORY),
        "--profile",
        str(PROFILES / "alpha-market" / "site.json"),
        "--packs-root",
        str(PACKS),
    ]
    assert main(["check", *common]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "valid"
    assert report["site_id"] == "alpha-market"
    assert report["blockers"] == []
    assert "compiled_plan_sha256" not in report

    assert main(["explain", *common]) == 0
    explanation = json.loads(capsys.readouterr().out)
    assert explanation["site_id"] == "alpha-market"
    assert explanation["blockers"] == []


def test_dispatch_command_is_retired(capsys: pytest.CaptureFixture[str]) -> None:
    assert "materialize" in build_parser().format_help()
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["dispatch"])
    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
