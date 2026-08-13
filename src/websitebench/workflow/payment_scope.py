"""Fail-closed, hash-bound machine validation for a site's payment scope."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from websitebench.site_compiler.canonical import sha256_file, sha256_value
from websitebench.site_compiler.schema import load_json_document

from .errors import WorkflowError
from .io import load_json, relative_path, resolve_relative


PAYMENT_SCOPE_SCHEMA = "websitebench-payment-scope-v2.schema.json"
_SCOPE_INPUT_PREFIXES = ("materials/{site_id}/", "websitebench/capability-packs/")


def payment_scope_subject(proposal: dict[str, Any]) -> dict[str, Any]:
    """Return the hash-bound part of a payment-scope document."""

    inputs = sorted(
        (
            {"path": item["path"], "sha256": item["sha256"]}
            for item in proposal["current_inputs"]
        ),
        key=lambda item: item["path"],
    )
    journeys = sorted(
        (
            {"id": item["id"], "description": item["description"]}
            for item in proposal["frozen_journeys"]
        ),
        key=lambda item: item["id"],
    )
    mail_differences = sorted(
        (
            {"site_id": item["site_id"], "fields": sorted(item["fields"])}
            for item in proposal["mail_brand"]["must_differ_from"]
        ),
        key=lambda item: item["site_id"],
    )
    profile_change = {
        "overlay_pack_id": proposal["profile_change"]["overlay_pack_id"],
        "candidate_blocker_id": proposal["profile_change"]["candidate_blocker_id"],
        "retained_blocker_ids": sorted(
            proposal["profile_change"]["retained_blocker_ids"]
        ),
    }
    if "audit_mode" in proposal["profile_change"]:
        profile_change["audit_mode"] = proposal["profile_change"]["audit_mode"]
    return {
        "schema_version": proposal["schema_version"],
        "proposal_id": proposal["proposal_id"],
        "site_id": proposal["site_id"],
        "display_name": proposal["display_name"],
        "current_inputs": inputs,
        "profile_change": profile_change,
        "frozen_journeys": journeys,
        "frozen_entities": sorted(proposal["frozen_entities"]),
        "payment_contract": proposal["payment_contract"],
        "mail_brand": {
            "shared_bare_sender_domain_allowed": proposal["mail_brand"][
                "shared_bare_sender_domain_allowed"
            ],
            "sender_display_name": proposal["mail_brand"]["sender_display_name"],
            "purposes": sorted(proposal["mail_brand"]["purposes"]),
            "must_differ_from": mail_differences,
        },
        "site_isolation": proposal["site_isolation"],
        "proof_obligations": sorted(proposal["proof_obligations"]),
    }


def payment_scope_subject_sha256(proposal: dict[str, Any]) -> str:
    """Hash the exact machine-validated payment scope."""

    return sha256_value(payment_scope_subject(proposal))


def _allowed_input_path(site_id: str, value: str) -> bool:
    profile = f"websitebench/site-profiles/{site_id}/site.json"
    if value == profile:
        return True
    return any(
        value.startswith(prefix.format(site_id=site_id))
        for prefix in _SCOPE_INPUT_PREFIXES
    )


def _required_input_paths(proposal: dict[str, Any]) -> set[str]:
    site_id = proposal["site_id"]
    subject_path = (
        f"materials/{site_id}/clone.yaml"
        if proposal["profile_change"].get("audit_mode") == "manifest-native-audit"
        else f"websitebench/site-profiles/{site_id}/site.json"
    )
    return {
        subject_path,
        f"materials/{site_id}/backend/runtime.json",
        f"materials/{site_id}/backend/model.json",
        "websitebench/capability-packs/payment/pack.json",
    }


def _validate_current_inputs(root: Path, proposal: dict[str, Any]) -> list[str]:
    site_id = proposal["site_id"]
    profile = f"websitebench/site-profiles/{site_id}/site.json"
    seen: set[str] = set()
    paths: set[str] = set()
    input_files: dict[str, Path] = {}
    problems: list[str] = []
    for item in proposal["current_inputs"]:
        path = item["path"]
        if path != PurePosixPath(path).as_posix() or "\\" in path:
            problems.append(f"input path must use canonical POSIX separators: {path}")
            continue
        if path in seen:
            problems.append(f"duplicate current input path: {path}")
            continue
        seen.add(path)
        paths.add(path)
        if not _allowed_input_path(site_id, path):
            problems.append(
                f"payment scope input is outside {site_id}'s scope/profile/pack: {path}"
            )
            continue
        try:
            input_file = resolve_relative(root, path, must_exist=True)
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
            continue
        input_files[path] = input_file
        actual = sha256_file(input_file)
        if actual != item["sha256"]:
            problems.append(
                f"current input sha256 mismatch for {path}: "
                f"declared={item['sha256']} actual={actual}"
            )
    for required in sorted(_required_input_paths(proposal)):
        if required not in paths:
            problems.append(f"current inputs must bind: {required}")
    if not any(path.startswith(f"materials/{site_id}/scope/") for path in paths):
        problems.append("current inputs must bind at least one site scope document")
    manifest_path = f"materials/{site_id}/clone.yaml"
    audit_mode = proposal["profile_change"].get(
        "audit_mode", "pre-change-proposal"
    )
    if audit_mode == "manifest-native-audit":
        profile_change = proposal["profile_change"]
        if profile_change["candidate_blocker_id"] is not None:
            problems.append(
                "manifest-native audit must not invent a profile blocker"
            )
        if profile_change["retained_blocker_ids"]:
            problems.append(
                "manifest-native audit cannot retain blockers from an absent profile"
            )
        if profile in paths:
            problems.append(
                "manifest-native audit must not depend on a legacy site profile"
            )
        if manifest_path in input_files:
            try:
                manifest = yaml.safe_load(
                    input_files[manifest_path].read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                problems.append(str(exc))
            else:
                if not isinstance(manifest, dict):
                    problems.append("clone manifest must be an object")
                elif manifest.get("schema_version") != "offline-clone.manifest.v2":
                    problems.append(
                        "manifest-native payment scope requires manifest v2"
                    )
                elif manifest.get("site_id") != site_id:
                    problems.append(
                        "clone manifest site_id does not match payment scope"
                    )
    elif profile in input_files:
        try:
            profile_value = load_json(input_files[profile])
        except WorkflowError as exc:
            problems.append(str(exc))
        else:
            if profile_value.get("site_id") != site_id:
                problems.append("site profile site_id does not match payment scope")
            raw_blockers = profile_value.get("blockers", [])
            if not isinstance(raw_blockers, list):
                problems.append("site profile blockers must be an array")
                raw_blockers = []
            blocker_ids = {
                item.get("id") for item in raw_blockers if isinstance(item, dict)
            }
            profile_change = proposal["profile_change"]
            audit_mode = profile_change.get(
                "audit_mode", "pre-change-proposal"
            )
            candidate_blocker = profile_change["candidate_blocker_id"]
            if audit_mode == "pre-change-proposal":
                if candidate_blocker is None:
                    problems.append(
                        "pre-change payment scope requires a candidate blocker"
                    )
                elif candidate_blocker not in blocker_ids:
                    problems.append(
                        "candidate payment blocker is not present in the current site profile: "
                        f"{candidate_blocker}"
                    )
            elif candidate_blocker is not None:
                problems.append(
                    "existing-overlay audit must not invent a candidate blocker"
                )
            missing_retained = sorted(
                set(profile_change["retained_blocker_ids"]) - blocker_ids
            )
            if missing_retained:
                problems.append(
                    "retained blockers are not present in the current site profile: "
                    + ", ".join(missing_retained)
                )
            classification = profile_value.get("classification", {})
            if not isinstance(classification, dict):
                problems.append("site profile classification must be an object")
                classification = {}
            overlays = classification.get("overlay_pack_ids", [])
            if not isinstance(overlays, list):
                problems.append("site profile overlay_pack_ids must be an array")
                overlays = []
            if audit_mode == "pre-change-proposal" and "payment" in overlays:
                problems.append(
                    "payment overlay is already selected; this pre-change scope proposal is stale"
                )
            if audit_mode == "existing-overlay-audit" and "payment" not in overlays:
                problems.append(
                    "existing-overlay audit requires the current profile to select payment"
                )
    runtime_path = f"materials/{site_id}/backend/runtime.json"
    if runtime_path in input_files:
        try:
            runtime_value = load_json(input_files[runtime_path])
        except WorkflowError as exc:
            problems.append(str(exc))
        else:
            runtime_site = runtime_value.get("site", {})
            if not isinstance(runtime_site, dict) or runtime_site.get("id") != site_id:
                problems.append("backend runtime site.id does not match payment scope")
            payments = runtime_value.get("payments", {})
            contract = proposal["payment_contract"]
            if not isinstance(payments, dict):
                problems.append("backend runtime payments must be an object")
                payments = {}
            if payments.get("default_adapter") != contract["default_adapter"]:
                problems.append(
                    "backend runtime default payment adapter does not match payment scope"
                )
            if payments.get("currency") != contract["currency"]:
                problems.append(
                    "backend runtime payment currency does not match payment scope"
                )
            optional_adapter = contract["optional_adapter"]
            if optional_adapter is None and payments.get("stripe_test") is not None:
                problems.append(
                    "backend runtime configures stripe_test outside the payment scope"
                )
            scenarios = payments.get("local_sandbox", {}).get("scenarios", [])
            outcomes = {
                item.get("outcome")
                for item in scenarios
                if isinstance(item, dict)
            }
            missing_outcomes = sorted(
                {"approved", "declined", "retryable"} - outcomes
            )
            if missing_outcomes:
                problems.append(
                    "backend runtime local sandbox is missing outcomes: "
                    + ", ".join(missing_outcomes)
                )
            allowed_deployment_adapters = {
                contract["default_adapter"],
                *([optional_adapter] if optional_adapter is not None else []),
            }
            deployment_profiles = runtime_value.get("deployment", {}).get(
                "profiles", {}
            )
            for name, profile_value in (
                deployment_profiles.items()
                if isinstance(deployment_profiles, dict)
                else []
            ):
                if not isinstance(profile_value, dict) or profile_value.get(
                    "payment_adapter"
                ) not in allowed_deployment_adapters:
                    problems.append(
                        "backend deployment profile uses an out-of-scope payment adapter: "
                        f"{name}"
                    )
            mail = runtime_value.get("mail", {})
            sender = mail.get("sender", {}) if isinstance(mail, dict) else {}
            if not isinstance(sender, dict) or sender.get(
                "display_name"
            ) != proposal["mail_brand"]["sender_display_name"]:
                problems.append(
                    "backend runtime mail sender does not match payment scope"
                )
            runtime_purposes = (
                set(mail.get("purposes", {})) if isinstance(mail, dict) else set()
            )
            missing_purposes = sorted(
                set(proposal["mail_brand"]["purposes"]) - runtime_purposes
            )
            if missing_purposes:
                problems.append(
                    "backend runtime is missing payment-scope mail purposes: "
                    + ", ".join(missing_purposes)
                )
    model_path = f"materials/{site_id}/backend/model.json"
    if model_path in input_files:
        try:
            model_value = load_json(input_files[model_path])
        except WorkflowError as exc:
            problems.append(str(exc))
        else:
            if model_value.get("site_id") != site_id:
                problems.append("backend model site_id does not match payment scope")
            if proposal["profile_change"].get("audit_mode") == "existing-overlay-audit":
                entity_names = {
                    entity.get("name")
                    for capability in model_value.get("capabilities", [])
                    if isinstance(capability, dict)
                    for entity in capability.get("entities", [])
                    if isinstance(entity, dict)
                }
                missing_entities = sorted(
                    set(proposal["frozen_entities"]) - entity_names
                )
                if missing_entities:
                    problems.append(
                        "existing payment model is missing frozen entities: "
                        + ", ".join(missing_entities)
                    )
    payment_pack = "websitebench/capability-packs/payment/pack.json"
    if payment_pack in input_files:
        try:
            payment_pack_value = load_json(input_files[payment_pack])
        except WorkflowError as exc:
            problems.append(str(exc))
        else:
            if payment_pack_value.get("pack_id") != "payment":
                problems.append("payment pack input must declare pack_id='payment'")
    return problems


def _validate_site_isolation(proposal: dict[str, Any]) -> list[str]:
    site_id = proposal["site_id"]
    isolation = proposal["site_isolation"]
    problems: list[str] = []
    expected_cookie = f"__Host-websitebench-{site_id}-session"
    if isolation["session_cookie_name"] != expected_cookie:
        problems.append(
            "session_cookie_name must be site-derived: "
            f"declared={isolation['session_cookie_name']} expected={expected_cookie}"
        )
    expected_namespace = f"site/{site_id}"
    if isolation["redis_namespace"] != expected_namespace:
        problems.append(
            "redis_namespace must be site-derived: "
            f"declared={isolation['redis_namespace']} expected={expected_namespace}"
        )
    return problems


def _validate_mail_brand(proposal: dict[str, Any]) -> list[str]:
    site_id = proposal["site_id"]
    compared_sites: set[str] = set()
    problems: list[str] = []
    for comparison in proposal["mail_brand"]["must_differ_from"]:
        comparison_site = comparison["site_id"]
        if comparison_site == site_id:
            problems.append("mail brand cannot be compared against the same site")
        if comparison_site in compared_sites:
            problems.append(
                f"duplicate mail brand comparison site: {comparison_site}"
            )
        compared_sites.add(comparison_site)
    return problems


def validate_payment_scope(
    repository_root: Path | str,
    proposal_path: Path | str,
) -> dict[str, Any]:
    """Validate a site-local payment scope and its safety invariants."""

    root = Path(repository_root).resolve()
    proposal_file = resolve_relative(
        root,
        Path(proposal_path).as_posix(),
        must_exist=True,
    )
    raw_proposal = load_json(proposal_file)
    if raw_proposal.get("schema_version") != "websitebench.payment-scope.v2":
        raise WorkflowError(
            "unsupported payment scope schema_version: "
            f"{raw_proposal.get('schema_version')!r}"
        )
    proposal = load_json_document(proposal_file, PAYMENT_SCOPE_SCHEMA)
    problems = _validate_current_inputs(root, proposal)
    if not proposal["proposal_id"].startswith(f"{proposal['site_id']}-"):
        problems.append("proposal_id must start with the site_id")
    actual_subject_sha = payment_scope_subject_sha256(proposal)
    if proposal["scope_subject_sha256"] != actual_subject_sha:
        problems.append(
            "scope_subject_sha256 does not match the current payment scope: "
            f"declared={proposal['scope_subject_sha256']} actual={actual_subject_sha}"
        )
    problems.extend(_validate_site_isolation(proposal))
    problems.extend(_validate_mail_brand(proposal))
    if problems:
        raise WorkflowError(problems)
    return {
        "status": "passed",
        "site_id": proposal["site_id"],
        "proposal": relative_path(root, proposal_file),
        "proposal_sha256": sha256_file(proposal_file),
        "scope_subject_sha256": proposal["scope_subject_sha256"],
        "payment_overlay_candidate": proposal["profile_change"]["overlay_pack_id"],
        "payment_scope_mode": proposal["profile_change"].get(
            "audit_mode", "pre-change-proposal"
        ),
    }
