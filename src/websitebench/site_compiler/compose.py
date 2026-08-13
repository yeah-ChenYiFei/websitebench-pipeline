"""Compose inventory, profile, and capability packs into an immutable Site IR."""

from __future__ import annotations

import copy
from typing import Any

from websitebench.offline_clone.manifest import initial_backend_model

from .diagnostics import SiteCompilerError
from .model import LoadedProfile
from .packs import LoadedPack

MANDATORY_PACK_IDS = ("common-stateful-core",)
PROOF_OBLIGATIONS = (
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


def _append_unique_strings(target: list[str], values: list[str]) -> None:
    seen = set(target)
    for value in values:
        if value not in seen:
            seen.add(value)
            target.append(value)


def _append_unique_records(
    target: list[dict[str, Any]],
    values: list[dict[str, Any]],
    *,
    owner: str,
) -> None:
    by_id = {item["id"]: item for item in target}
    for value in values:
        item_id = value["id"]
        if item_id in by_id:
            if by_id[item_id] != value:
                raise SiteCompilerError(
                    f"capability pack {owner!r} conflicts on frontend item {item_id!r}"
                )
            continue
        copied = copy.deepcopy(value)
        by_id[item_id] = copied
        target.append(copied)


def _planned_capability(template: dict[str, Any]) -> dict[str, Any]:
    capability = copy.deepcopy(template)
    capability.update(
        {
            "implementation_status": "planned",
            "journey_ids": [],
            "invariant_ids": [],
            "proofs": {
                "evidence": {},
                "planned": list(PROOF_OBLIGATIONS),
                "not_applicable": [],
            },
        }
    )
    return capability


def _apply_overrides(
    ir: dict[str, Any],
    profile: LoadedProfile,
    packs: list[LoadedPack],
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    extension_points = {
        point
        for pack in packs
        for point in pack.data["extension_points"]
    }
    capabilities = ir["backend_model_seed"]["capabilities"]
    for index, operation in enumerate(profile.data["overrides"]):
        op = operation["op"]
        target = operation["target"]
        selector = operation["selector"]
        location = f"{profile.path}:overrides.{index}"
        if target not in extension_points:
            raise SiteCompilerError(
                f"{location}: target {target!r} is not a declared pack extension point"
            )
        if op != "remove-item-with-rationale":
            raise SiteCompilerError(
                f"{location}: compiler ABI currently supports only "
                "remove-item-with-rationale; unsupported typed op "
                f"{op!r} cannot be guessed"
            )
        if target != "backend.capabilities":
            raise SiteCompilerError(
                f"{location}: remove-item-with-rationale currently requires "
                "target 'backend.capabilities'"
            )
        matches = [
            item
            for item in capabilities
            if item.get("id") == selector["id"]
        ]
        if len(matches) != 1:
            raise SiteCompilerError(
                f"{location}: selector must resolve exactly one capability; "
                f"resolved {len(matches)}"
            )
        selected = matches[0]
        capabilities.remove(selected)
        applied.append(
            {
                "op": op,
                "target": target,
                "selector": selector,
                "rationale": operation["rationale"],
            }
        )
    return applied


def compose_site_ir(
    profile: LoadedProfile,
    packs: list[LoadedPack],
) -> dict[str, Any]:
    pack_ids = [pack.pack_id for pack in packs]
    missing_mandatory = sorted(set(MANDATORY_PACK_IDS) - set(pack_ids))
    if missing_mandatory:
        raise SiteCompilerError(
            "every stateful site must resolve the shared auth/mail backend baseline; "
            "missing packs: " + ", ".join(missing_mandatory)
        )
    primary = profile.data["classification"]["archetype_pack_id"]
    primary_matches = [
        pack for pack in packs if pack.pack_id == primary and pack.data["kind"] == "archetype"
    ]
    if len(primary_matches) != 1:
        raise SiteCompilerError(
            f"profile archetype {primary!r} must resolve exactly one archetype pack"
        )
    declared_batch = profile.data["classification"]["batch_family_id"]
    pack_batch = primary_matches[0].data["batch_family_id"]
    if declared_batch != pack_batch:
        raise SiteCompilerError(
            f"profile batch family {declared_batch!r} does not match archetype "
            f"{primary!r} family {pack_batch!r}"
        )

    frontend: dict[str, Any] = {
        "shell_regions": [],
        "route_families": [],
        "state_families": [],
        "interaction_families": [],
        "required_viewports": [],
    }
    backend_model = initial_backend_model(profile.data["site_id"])
    capability_sources: dict[str, str] = {
        capability["id"]: "common-stateful-core"
        for capability in backend_model["capabilities"]
    }
    local_adapters: list[str] = []
    coverage_dimensions: list[str] = []
    verification_focus: list[str] = []

    for pack in packs:
        pack_frontend = pack.data["frontend"]
        _append_unique_strings(frontend["shell_regions"], pack_frontend["shell_regions"])
        _append_unique_records(
            frontend["route_families"],
            pack_frontend["route_families"],
            owner=pack.pack_id,
        )
        _append_unique_strings(
            frontend["state_families"],
            pack_frontend["state_families"],
        )
        _append_unique_strings(
            frontend["interaction_families"],
            pack_frontend["interaction_families"],
        )
        _append_unique_strings(
            frontend["required_viewports"],
            pack_frontend["required_viewports"],
        )

        for template in pack.data["backend"]["capability_templates"]:
            capability_id = template["id"]
            if capability_id in capability_sources:
                raise SiteCompilerError(
                    f"capability {capability_id!r} is declared by both "
                    f"{capability_sources[capability_id]!r} and {pack.pack_id!r}"
                )
            backend_model["capabilities"].append(_planned_capability(template))
            capability_sources[capability_id] = pack.pack_id
        _append_unique_strings(
            local_adapters,
            pack.data["backend"]["local_external_adapters"],
        )
        _append_unique_strings(
            coverage_dimensions,
            pack.data["verification"]["coverage_dimensions"],
        )
        _append_unique_strings(
            verification_focus,
            pack.data["verification"]["verification_focus"],
        )

    ir = {
        "schema_version": "offline-clone.site-ir.v1",
        "site": {
            "inventory_id": profile.data["inventory_id"],
            "site_id": profile.data["site_id"],
            "display_name": profile.data["display_name"],
            "official_url": profile.data["official_url"],
            "source_origins": profile.data["source_origins"],
            "source_origin_status": profile.data["source_origin_status"],
            "locale_defaults": profile.data["locale_defaults"],
        },
        "classification": copy.deepcopy(profile.data["classification"]),
        "resolved_pack_ids": pack_ids,
        "frontend_contract": frontend,
        "backend_model_seed": backend_model,
        "backend_runtime_contract": {
            "database_scope": "one permanent site-isolated database per clone",
            "shared_runtime_payload": "websitebench.site_backend",
            "authentication_runtime_payload": "websitebench.local_clone_auth",
            "runtime_contract_path": "backend/runtime.json",
            "shared_semantics_not_shared_data": True,
            "local_external_adapters": local_adapters,
            "all_meaningful_capabilities_must_be_verified": True,
        },
        "verification_contract": {
            "coverage_dimensions": coverage_dimensions,
            "verification_focus": verification_focus,
            "required_checkpoints": [
                "scope-validation",
                "frontend-validation",
                "semantic-validation",
                "release-validation",
            ],
        },
        "blockers": copy.deepcopy(profile.data["blockers"]),
        "capability_provenance": capability_sources,
        "applied_overrides": [],
    }
    ir["applied_overrides"] = _apply_overrides(ir, profile, packs)
    return ir
