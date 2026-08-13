"""Machine validation for complete offline-clone backend domain models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


BACKEND_MODEL_SCHEMA = "offline-clone-backend-model.schema.json"
BACKEND_MODEL_VERSION = "offline-clone.backend-model.v1"
BACKEND_MODEL_V2_SCHEMA = "offline-clone-backend-model-v2.schema.json"
BACKEND_MODEL_V2_VERSION = "offline-clone.backend-model.v2"
COMMON_CAPABILITY_FIELDS = (
    "account_registration",
    "account_sign_in",
    "session_lifecycle",
    "password_recovery",
    "email_delivery",
)
DATABASE_OBLIGATIONS = frozenset(
    {
        "data-location",
        "schema-migration",
        "deterministic-reset",
        "restart-persistence",
        "backup-restore",
        "concurrency",
    }
)
CAPABILITY_OBLIGATIONS = frozenset(
    {
        "valid",
        "invalid",
        "duplicate",
        "stale",
        "foreign-owner",
        "unauthorized-role",
        "restart",
        "migration",
        "concurrency",
    }
)
MAIL_STATUSES = frozenset(
    {"LOCAL_ONLY", "SMTP_PENDING", "SMTP_SENT", "SMTP_FAILED"}
)
COMMON_SEMANTIC_PROFILES = {
    "account_registration": "local-account-registration-v1",
    "account_sign_in": "local-account-sign-in-v1",
    "session_lifecycle": "local-session-lifecycle-v1",
    "password_recovery": "local-password-recovery-v1",
    "email_delivery": "local-mail-delivery-v1",
}
MAX_BACKEND_MODEL_BYTES = 4 * 1024 * 1024


class BackendModelError(ValueError):
    """Raised when a backend model is structurally or semantically incomplete."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(
            "offline clone backend model validation failed:\n"
            + "\n".join(f"- {problem}" for problem in problems)
        )


def _schema_path(schema_name: str = BACKEND_MODEL_SCHEMA) -> Path:
    source_root = Path(__file__).resolve().parents[3]
    source = source_root / "websitebench" / "schemas" / schema_name
    if source.is_file():
        return source
    bundled = Path(__file__).resolve().parents[1] / "viewer" / "_schemas"
    installed = bundled / schema_name
    if installed.is_file():
        return installed
    raise FileNotFoundError(
        f"offline clone backend model schema is unavailable: {schema_name}"
    )


def _strict_mapping(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) > MAX_BACKEND_MODEL_BYTES:
        raise BackendModelError(
            [f"{path}: exceeds {MAX_BACKEND_MODEL_BYTES} bytes"]
        )

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BackendModelError([f"{path}: {exc}"]) from exc
    if not isinstance(value, dict):
        raise BackendModelError([f"{path}: top-level JSON value must be an object"])
    return value


def _schema_problems(value: dict[str, Any]) -> list[str]:
    version = value.get("schema_version")
    schema_name = (
        BACKEND_MODEL_V2_SCHEMA
        if version == BACKEND_MODEL_V2_VERSION
        else BACKEND_MODEL_SCHEMA
    )
    schema_path = _schema_path(schema_name)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    from referencing import Registry, Resource
    v1_path = _schema_path(BACKEND_MODEL_SCHEMA)
    v1_schema = json.loads(v1_path.read_text(encoding="utf-8"))
    registry = Registry().with_resource(
        "https://clawbench.local/schemas/offline-clone.backend-model.v1.json",
        Resource.from_contents(v1_schema),
    ).with_resource(
        "https://clawbench.local/schemas/offline-clone-backend-model.schema.json",
        Resource.from_contents(v1_schema),
    ).with_resource(
        v1_path.name,
        Resource.from_contents(v1_schema),
    )
    validator = Draft202012Validator(schema, registry=registry)
    problems: list[str] = []
    for error in sorted(
        validator.iter_errors(value), key=lambda item: list(item.absolute_path)
    ):
        suffix = ".".join(str(part) for part in error.absolute_path)
        problems.append(f"backend_model.{suffix or '$'}: {error.message}")
    return problems


def _duplicate_problem(
    problems: list[str], seen: set[str], value: object, location: str
) -> None:
    if not isinstance(value, str):
        return
    if value in seen:
        problems.append(f"{location}: duplicate value {value!r}")
    else:
        seen.add(value)


def validate_backend_model(
    value: dict[str, Any],
    *,
    expected_site_id: str | None = None,
    require_verified: bool = False,
) -> list[str]:
    """Return every structural and semantic backend-model problem."""

    problems = _schema_problems(value)
    if expected_site_id is not None and value.get("site_id") != expected_site_id:
        problems.append(
            "backend_model.site_id: must equal manifest.site_id "
            f"{expected_site_id!r}"
        )

    database = value.get("database")
    if isinstance(database, dict):
        proofs = database.get("proofs")
        seen_database: set[str] = set()
        if isinstance(proofs, list):
            for index, proof in enumerate(proofs):
                if not isinstance(proof, dict):
                    continue
                _duplicate_problem(
                    problems,
                    seen_database,
                    proof.get("obligation"),
                    f"backend_model.database.proofs.{index}.obligation",
                )
            missing = sorted(DATABASE_OBLIGATIONS - seen_database)
            extra = sorted(seen_database - DATABASE_OBLIGATIONS)
            if missing:
                problems.append(
                    "backend_model.database.proofs: missing obligations: "
                    + ", ".join(missing)
                )
            if extra:
                problems.append(
                    "backend_model.database.proofs: unknown obligations: "
                    + ", ".join(extra)
                )
            if require_verified:
                for index, proof in enumerate(proofs):
                    if not isinstance(proof, dict):
                        continue
                    if proof.get("status") != "verified":
                        problems.append(
                            f"backend_model.database.proofs.{index}.status: "
                            "backend readiness requires verified"
                        )
                    if not proof.get("evidence"):
                        problems.append(
                            f"backend_model.database.proofs.{index}.evidence: "
                            "backend readiness requires evidence"
                        )

    if set(value.get("auth_semantics", {}).get("mail_statuses", [])) != MAIL_STATUSES:
        problems.append(
            "backend_model.auth_semantics.mail_statuses: must contain exactly "
            "LOCAL_ONLY, SMTP_PENDING, SMTP_SENT, SMTP_FAILED"
        )

    capabilities = value.get("capabilities")
    capabilities_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(capabilities, list):
        for index, capability in enumerate(capabilities):
            if not isinstance(capability, dict):
                continue
            capability_id = capability.get("id")
            if isinstance(capability_id, str):
                if capability_id in capabilities_by_id:
                    problems.append(
                        f"backend_model.capabilities.{index}.id: "
                        f"duplicate capability id {capability_id!r}"
                    )
                else:
                    capabilities_by_id[capability_id] = capability

            entity_names: set[str] = set()
            for entity_index, entity in enumerate(capability.get("entities", [])):
                if not isinstance(entity, dict):
                    continue
                _duplicate_problem(
                    problems,
                    entity_names,
                    entity.get("name"),
                    "backend_model.capabilities."
                    f"{index}.entities.{entity_index}.name",
                )

            machine = capability.get("state_machine")
            if isinstance(machine, dict):
                states = {
                    state for state in machine.get("states", []) if isinstance(state, str)
                }
                for transition_index, transition in enumerate(
                    machine.get("transitions", [])
                ):
                    if not isinstance(transition, dict):
                        continue
                    for end in ("from", "to"):
                        state = transition.get(end)
                        if isinstance(state, str) and state not in states:
                            problems.append(
                                "backend_model.capabilities."
                                f"{index}.state_machine.transitions."
                                f"{transition_index}.{end}: unknown state {state!r}"
                            )

            proof_value = capability.get("proofs")
            if isinstance(proof_value, dict):
                evidence = proof_value.get("evidence")
                planned_value = proof_value.get("planned")
                not_applicable = proof_value.get("not_applicable")
                evidenced = (
                    set(evidence)
                    if isinstance(evidence, dict)
                    else set()
                )
                planned = (
                    {
                        obligation
                        for obligation in planned_value
                        if isinstance(obligation, str)
                    }
                    if isinstance(planned_value, list)
                    else set()
                )
                excepted: set[str] = set()
                if isinstance(not_applicable, list):
                    for exception_index, exception in enumerate(not_applicable):
                        if not isinstance(exception, dict):
                            continue
                        obligation = exception.get("obligation")
                        _duplicate_problem(
                            problems,
                            excepted,
                            obligation,
                            "backend_model.capabilities."
                            f"{index}.proofs.not_applicable."
                            f"{exception_index}.obligation",
                        )
                overlap = sorted(
                    (evidenced & excepted)
                    | (evidenced & planned)
                    | (excepted & planned)
                )
                if overlap:
                    problems.append(
                        f"backend_model.capabilities.{index}.proofs: obligations "
                        "cannot be classified more than once across evidence, "
                        "planned, and not_applicable: "
                        + ", ".join(overlap)
                    )
                classified = evidenced | planned | excepted
                unclassified = sorted(CAPABILITY_OBLIGATIONS - classified)
                unknown = sorted(classified - CAPABILITY_OBLIGATIONS)
                if unclassified:
                    problems.append(
                        f"backend_model.capabilities.{index}.proofs: "
                        "every obligation must be classified as evidence, "
                        "planned, or not_applicable; missing: "
                        + ", ".join(unclassified)
                    )
                if unknown:
                    problems.append(
                        f"backend_model.capabilities.{index}.proofs: "
                        "unknown obligations: "
                        + ", ".join(unknown)
                    )
                if require_verified:
                    missing = sorted(
                        CAPABILITY_OBLIGATIONS - evidenced - excepted
                    )
                    if missing:
                        problems.append(
                            f"backend_model.capabilities.{index}.proofs: "
                            "backend readiness requires evidence or an explicit "
                            "N/A rationale for: "
                            + ", ".join(missing)
                        )

            if require_verified:
                if capability.get("implementation_status") != "verified":
                    problems.append(
                        f"backend_model.capabilities.{index}.implementation_status: "
                        "backend readiness requires verified"
                    )
                if capability.get("priority") in {"p0", "p1"}:
                    if not capability.get("journey_ids"):
                        problems.append(
                            f"backend_model.capabilities.{index}.journey_ids: "
                            "verified p0/p1 capability must bind a frozen journey"
                        )
                    if not capability.get("invariant_ids"):
                        problems.append(
                            f"backend_model.capabilities.{index}.invariant_ids: "
                            "verified p0/p1 capability must bind a backend invariant"
                        )

    common = value.get("common_capabilities")
    if isinstance(common, dict):
        resolved: set[str] = set()
        for field in COMMON_CAPABILITY_FIELDS:
            capability_id = common.get(field)
            if not isinstance(capability_id, str):
                continue
            if capability_id in resolved:
                problems.append(
                    f"backend_model.common_capabilities.{field}: each common "
                    "surface must map to a distinct capability"
                )
            resolved.add(capability_id)
            capability = capabilities_by_id.get(capability_id)
            if capability is None:
                problems.append(
                    f"backend_model.common_capabilities.{field}: unknown "
                    f"capability {capability_id!r}"
                )
            elif capability.get("category") not in {
                "authentication",
                "communication",
            }:
                problems.append(
                    f"backend_model.common_capabilities.{field}: common auth/mail "
                    "surface must use authentication or communication category"
                )
            elif (
                capability.get("semantic_profile") is not None
                and capability.get("semantic_profile")
                not in (
                    {COMMON_SEMANTIC_PROFILES[field], "not-applicable-v1"}
                    if field in {"password_recovery", "email_delivery"}
                    else {COMMON_SEMANTIC_PROFILES[field]}
                )
            ):
                problems.append(
                    f"backend_model.common_capabilities.{field}: expected "
                    f"semantic_profile {COMMON_SEMANTIC_PROFILES[field]!r}"
                )

            if capability is not None and capability.get("semantic_profile") == "not-applicable-v1":
                if field not in {"password_recovery", "email_delivery"}:
                    problems.append(
                        f"backend_model.common_capabilities.{field}: "
                        "not-applicable-v1 is only valid for password recovery or mail"
                    )
                if capability.get("implementation_status") != "not-applicable":
                    problems.append(
                        f"backend_model.common_capabilities.{field}: "
                        "not-applicable-v1 requires implementation_status 'not-applicable'"
                    )
                proofs = capability.get("proofs")
                exceptions = proofs.get("not_applicable", []) if isinstance(proofs, dict) else []
                excepted = {
                    item.get("obligation")
                    for item in exceptions
                    if isinstance(item, dict)
                }
                if excepted != CAPABILITY_OBLIGATIONS:
                    problems.append(
                        f"backend_model.common_capabilities.{field}: "
                        "not-applicable-v1 must classify all proof obligations as not_applicable"
                    )

    if value.get("schema_version") == BACKEND_MODEL_V2_VERSION:
        assessments = value.get("parity_assessments")
        by_capability: dict[str, dict[str, Any]] = {}
        if isinstance(assessments, list):
            for index, assessment in enumerate(assessments):
                if not isinstance(assessment, dict):
                    continue
                capability_id = assessment.get("capability_id")
                if isinstance(capability_id, str):
                    if capability_id in by_capability:
                        problems.append(
                            f"backend_model.parity_assessments.{index}.capability_id: duplicate value {capability_id!r}"
                        )
                    by_capability[capability_id] = assessment
        missing = sorted(set(capabilities_by_id) - set(by_capability))
        unknown = sorted(set(by_capability) - set(capabilities_by_id))
        if missing:
            problems.append("backend_model.parity_assessments: missing capabilities: " + ", ".join(missing))
        if unknown:
            problems.append("backend_model.parity_assessments: unknown capabilities: " + ", ".join(unknown))
        if require_verified:
            for capability_id, assessment in by_capability.items():
                for dimension in ("functional", "behavioral", "data_model"):
                    value_dimension = assessment.get(dimension)
                    if not isinstance(value_dimension, dict) or value_dimension.get("status") != "complete":
                        problems.append(
                            f"backend_model.parity_assessments.{capability_id}.{dimension}: verified v2 requires complete"
                        )
                if not assessment.get("journey_frozen") or not assessment.get("invariant_frozen"):
                    problems.append(
                        f"backend_model.parity_assessments.{capability_id}: verified v2 requires frozen journey and invariant"
                    )
                refs = set()
                for dimension in ("functional", "behavioral", "data_model"):
                    item = assessment.get(dimension)
                    if isinstance(item, dict):
                        refs.update(item.get("evidence_refs", []))
                hashes = assessment.get("evidence_hashes")
                if refs and (not isinstance(hashes, dict) or not refs.issubset(hashes)):
                    problems.append(
                        f"backend_model.parity_assessments.{capability_id}.evidence_hashes: verified v2 requires a hash for every evidence ref"
                    )

    if require_verified and value.get("status") != "verified":
        problems.append(
            "backend_model.status: backend readiness requires status 'verified'"
        )
    return problems


def validate_backend_scope_references(
    value: dict[str, Any],
    *,
    journey_ids: set[str],
    invariant_ids: set[str],
    require_bindings: bool = True,
) -> list[str]:
    """Validate backend capability bindings against the R1 scope documents."""

    problems: list[str] = []
    common = value.get("common_capabilities")
    common_ids = (
        {
            capability_id
            for capability_id in common.values()
            if isinstance(capability_id, str)
        }
        if isinstance(common, dict)
        else set()
    )
    for index, capability in enumerate(value.get("capabilities", [])):
        if not isinstance(capability, dict):
            continue
        capability_id = capability.get("id")
        location = f"backend_model.capabilities.{index}"
        bound_journeys = capability.get("journey_ids")
        bound_invariants = capability.get("invariant_ids")
        entity_owner_scopes = {
            entity.get("name"): entity.get("owner_scope")
            for entity in capability.get("entities", [])
            if isinstance(entity, dict) and isinstance(entity.get("name"), str)
        }
        if require_bindings and capability.get("priority") in {"p0", "p1"}:
            if not isinstance(bound_journeys, list) or not bound_journeys:
                problems.append(
                    f"{location}.journey_ids: p0/p1 capability "
                    f"{capability_id!r} must bind at least one R1 journey"
                )
            if not isinstance(bound_invariants, list) or not bound_invariants:
                problems.append(
                    f"{location}.invariant_ids: p0/p1 capability "
                    f"{capability_id!r} must bind at least one R1 invariant"
                )
        if require_bindings and capability_id in common_ids:
            if not bound_journeys:
                problems.append(
                    f"{location}.journey_ids: common auth/mail capability "
                    f"{capability_id!r} cannot remain an unscoped placeholder"
                )
            if not bound_invariants:
                problems.append(
                    f"{location}.invariant_ids: common auth/mail capability "
                    f"{capability_id!r} cannot remain an unscoped placeholder"
                )
        for reference in bound_journeys or []:
            if reference not in journey_ids:
                problems.append(
                    f"{location}.journey_ids: unknown R1 journey {reference!r}"
                )
        for reference in bound_invariants or []:
            if reference not in invariant_ids:
                problems.append(
                    f"{location}.invariant_ids: unknown R1 invariant {reference!r}"
                )

        requires_exact_proof_bindings = (
            require_bindings
            and capability.get("priority") in {"p0", "p1"}
            and capability.get("semantic_profile") is None
            and isinstance(value.get("database"), dict)
            and bool(value["database"].get("entity_inventory"))
        )
        proof_bindings = capability.get("proof_bindings")
        if requires_exact_proof_bindings and not isinstance(proof_bindings, list):
            problems.append(
                f"{location}.proof_bindings: deep p0/p1 capability "
                f"{capability_id!r} must bind all nine proof obligations"
            )
            continue
        if not isinstance(proof_bindings, list):
            continue

        seen_obligations: set[str] = set()
        for binding_index, binding in enumerate(proof_bindings):
            if not isinstance(binding, dict):
                continue
            binding_location = f"{location}.proof_bindings.{binding_index}"
            obligation = binding.get("obligation")
            _duplicate_problem(
                problems,
                seen_obligations,
                obligation,
                f"{binding_location}.obligation",
            )

            binding_journeys = binding.get("journey_ids")
            if isinstance(binding_journeys, list):
                for reference in binding_journeys:
                    if reference not in (bound_journeys or []):
                        problems.append(
                            f"{binding_location}.journey_ids: {reference!r} "
                            "must also be bound by the capability"
                        )
                    if reference not in journey_ids:
                        problems.append(
                            f"{binding_location}.journey_ids: unknown R1 "
                            f"journey {reference!r}"
                        )

            binding_invariants = binding.get("invariant_ids")
            if isinstance(binding_invariants, list):
                for reference in binding_invariants:
                    if reference not in (bound_invariants or []):
                        problems.append(
                            f"{binding_location}.invariant_ids: {reference!r} "
                            "must also be bound by the capability"
                        )
                    if reference not in invariant_ids:
                        problems.append(
                            f"{binding_location}.invariant_ids: unknown R1 "
                            f"invariant {reference!r}"
                        )

            binding_entities = binding.get("entity_names")
            if isinstance(binding_entities, list):
                for entity_name in binding_entities:
                    if entity_name not in entity_owner_scopes:
                        problems.append(
                            f"{binding_location}.entity_names: unknown capability "
                            f"entity {entity_name!r}"
                        )
                owner_scope = binding.get("owner_scope")
                if owner_scope not in {
                    entity_owner_scopes.get(entity_name)
                    for entity_name in binding_entities
                }:
                    problems.append(
                        f"{binding_location}.owner_scope: must match at least "
                        "one bound entity"
                    )

        if requires_exact_proof_bindings:
            missing = sorted(CAPABILITY_OBLIGATIONS - seen_obligations)
            unknown = sorted(seen_obligations - CAPABILITY_OBLIGATIONS)
            if missing:
                problems.append(
                    f"{location}.proof_bindings: missing obligations: "
                    + ", ".join(missing)
                )
            if unknown:
                problems.append(
                    f"{location}.proof_bindings: unknown obligations: "
                    + ", ".join(unknown)
                )
    return problems


def load_backend_model(
    path: Path,
    *,
    expected_site_id: str | None = None,
    require_verified: bool = False,
) -> dict[str, Any]:
    value = _strict_mapping(path)
    problems = validate_backend_model(
        value,
        expected_site_id=expected_site_id,
        require_verified=require_verified,
    )
    if problems:
        raise BackendModelError(problems)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(prog="websitebench-backend-model")
    parser.add_argument("model", type=Path)
    parser.add_argument("--site-id")
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args()
    value = load_backend_model(
        args.model,
        expected_site_id=args.site_id,
        require_verified=args.require_verified,
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "site_id": value["site_id"],
                "backend_model_status": value["status"],
                "capabilities": len(value["capabilities"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
