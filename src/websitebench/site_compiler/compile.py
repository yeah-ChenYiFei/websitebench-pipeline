"""Pure orchestration and atomic plan emission for the site compiler."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from websitebench.offline_clone.backend_model import validate_backend_model

from .canonical import canonical_json_bytes
from .compose import MANDATORY_PACK_IDS, compose_site_ir
from .diagnostics import SiteCompilerError
from .graph import ArtifactGraph
from .inventory import load_inventory
from .model import load_profile
from .packs import load_pack_directory, resolve_packs
from .schema import validate_value

COMPILER_VERSION = "websitebench.site-compiler.v3"
COMPILED_PLAN_SCHEMA = "offline-clone.compiled-site-plan.v3"
TARGETS = ("scope", "frontend", "backend", "release")


@dataclass(frozen=True)
class CompilationResult:
    plan: dict[str, Any]
    explanation: dict[str, Any]
    inputs: dict[str, Any]


@dataclass(frozen=True)
class CompilerWorkspace:
    """Loaded, reusable inventory and pack registry for high-volume batches."""

    inventory: Any
    available_packs: dict[str, Any]

    @classmethod
    def load(cls, *, inventory_path: Path, packs_root: Path) -> "CompilerWorkspace":
        return cls(
            inventory=load_inventory(inventory_path),
            available_packs=load_pack_directory(packs_root),
        )

    def compile(
        self,
        *,
        profile_path: Path,
        target: str = "release",
    ) -> CompilationResult:
        if target not in TARGETS:
            raise SiteCompilerError(
                f"unknown compilation target {target!r}; choose one of "
                f"{', '.join(TARGETS)}"
            )
        profile = load_profile(profile_path, self.inventory)
        packs = resolve_packs(
            self.available_packs,
            _requested_pack_ids(profile.data),
        )
        return _compile_loaded(
            inventory=self.inventory,
            profile=profile,
            packs=packs,
            target=target,
        )


def _requested_pack_ids(profile_data: dict[str, Any]) -> list[str]:
    classification = profile_data["classification"]
    requested = [
        *MANDATORY_PACK_IDS,
        classification["archetype_pack_id"],
        *classification["overlay_pack_ids"],
        *profile_data["additional_pack_ids"],
    ]
    return list(dict.fromkeys(requested))


def compile_profile(
    *,
    inventory_path: Path,
    profile_path: Path,
    packs_root: Path,
    target: str = "release",
) -> CompilationResult:
    workspace = CompilerWorkspace.load(
        inventory_path=inventory_path,
        packs_root=packs_root,
    )
    return workspace.compile(profile_path=profile_path, target=target)


def _compile_loaded(
    *,
    inventory: Any,
    profile: Any,
    packs: list[Any],
    target: str,
) -> CompilationResult:
    ir = compose_site_ir(profile, packs)
    backend_problems = validate_backend_model(
        ir["backend_model_seed"],
        expected_site_id=profile.data["site_id"],
        require_verified=False,
    )
    if backend_problems:
        raise SiteCompilerError(
            [f"compiled backend model: {problem}" for problem in backend_problems]
        )

    pack_identity = [
        {
            "pack_id": pack.pack_id,
            "version": pack.data["version"],
        }
        for pack in packs
    ]
    graph = ArtifactGraph()
    graph.add(
        "inventory",
        kind="platform-inventory",
        invalidates_from="scope-validation",
        payload={"inventory_id": profile.data["inventory_id"]},
    )
    graph.add(
        "profile",
        kind="site-profile",
        invalidates_from="scope-validation",
        inputs=("inventory",),
        payload={"site_id": profile.data["site_id"]},
    )
    graph.add(
        "packs",
        kind="resolved-capability-packs",
        invalidates_from="scope-validation",
        payload=pack_identity,
    )
    graph.add(
        "site-ir",
        kind="immutable-site-ir",
        invalidates_from="scope-validation",
        inputs=("profile", "packs"),
        payload=ir,
    )
    graph.add(
        "scope-contract-plan",
        kind="scope-evidence-plan",
        invalidates_from="scope-validation",
        inputs=("site-ir",),
        payload={
            "classification": ir["classification"],
            "coverage": ir["verification_contract"]["coverage_dimensions"],
        },
    )
    graph.add(
        "frontend-plan",
        kind="frontend-contract-plan",
        invalidates_from="frontend-validation",
        inputs=("scope-contract-plan",),
        payload=ir["frontend_contract"],
    )
    graph.add(
        "backend-plan",
        kind="backend-model-plan",
        invalidates_from="semantic-validation",
        inputs=("scope-contract-plan",),
        payload={
            "backend_model_seed": ir["backend_model_seed"],
            "runtime": ir["backend_runtime_contract"],
        },
    )
    graph.add(
        "release-plan",
        kind="release-evidence-plan",
        invalidates_from="release-validation",
        inputs=("frontend-plan", "backend-plan"),
        payload=ir["verification_contract"],
    )

    plan = {
        "schema_version": COMPILED_PLAN_SCHEMA,
        "compiler_version": COMPILER_VERSION,
        "target": target,
        "site_ir": ir,
        "evidence_boundary": {
            "inventory_metadata": "structural-provenance-only",
            "pack_classification": "machine-inferred",
            "generated_source_claims": "forbidden",
            "candidate_as_source_truth": "forbidden",
        },
        "workflow": {
            "ordered_stages": [
                "inventory-normalization",
                "profile-and-pack-resolution",
                "scope-validation",
                "source-capture-and-asset-closure",
                "frontend-convergence",
                "frontend-validation",
                "persistent-backend",
                "semantic-validation",
                "harbor-machine-evidence",
                "release-validation",
            ],
            "target": target,
            "automation_policy": (
                "scope, fidelity, semantic depth and diagnostics are resolved from "
                "current structured inputs and observed behavior"
            ),
            "backend_policy": (
                "every meaningful capability, including local auth, mail, "
                "business state, persistence, reset, migration, retry, "
                "ownership and concurrency, must reach verified"
            ),
        },
        "artifact_graph": graph.as_list(),
    }
    plan_problems = validate_value(
        plan,
        "offline-clone-compiled-site-plan-v3.schema.json",
        location="compiled plan",
    )
    if plan_problems:
        raise SiteCompilerError(plan_problems)
    explanation = {
        "schema_version": "offline-clone.site-explanation.v1",
        "site_id": profile.data["site_id"],
        "classification": ir["classification"],
        "resolved_packs": pack_identity,
        "capability_provenance": ir["capability_provenance"],
        "blockers": ir["blockers"],
        "evidence_boundary": plan["evidence_boundary"],
        "invalidation": [
            {
                "node_id": node["node_id"],
                "invalidates_from": node["invalidates_from"],
            }
            for node in plan["artifact_graph"]
        ],
    }
    inputs = {
        "site-profile.json": profile.data,
        "inventory-row.json": profile.inventory_row,
        "resolved-packs.json": {
            "schema_version": "offline-clone.resolved-packs.v1",
            "site_id": profile.data["site_id"],
            "packs": pack_identity,
        },
    }
    return CompilationResult(
        plan=plan,
        explanation=explanation,
        inputs=inputs,
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_compilation(
    result: CompilationResult,
    *,
    output_dir: Path,
    check: bool = False,
) -> dict[str, Any]:
    resolved = output_dir.resolve()
    site_id = result.plan["site_ir"]["site"]["site_id"]
    files = {
        "plan": resolved / f"{site_id}.compiled.json",
        "explanation": resolved / f"{site_id}.explain.json",
    }
    payloads = {
        "plan": canonical_json_bytes(result.plan),
        "explanation": canonical_json_bytes(result.explanation),
    }
    drift: list[str] = []
    for kind, path in files.items():
        if not path.is_file() or path.read_bytes() != payloads[kind]:
            drift.append(kind)
    expected_names = {path.name for path in files.values()}
    actual_names = {
        path.name for path in resolved.glob(f"{site_id}.*.json") if path.is_file()
    }
    extra = sorted(actual_names - expected_names)
    if extra:
        drift.extend(f"extra:{name}" for name in extra)
    if check:
        if drift:
            raise SiteCompilerError(
                f"compiled outputs for {site_id!r} have drift: " + ", ".join(drift)
            )
    else:
        (resolved / f"{site_id}.lock.json").unlink(missing_ok=True)
        for kind, path in files.items():
            _atomic_write(path, payloads[kind])
    return {
        "status": "current" if not drift else ("drift" if check else "written"),
        "site_id": site_id,
        "files": {kind: str(path) for kind, path in files.items()},
    }
