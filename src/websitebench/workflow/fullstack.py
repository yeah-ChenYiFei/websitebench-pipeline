"""Machine-verifiable full-stack checks for the offline-clone inner loop."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import Any

from websitebench.site_compiler.schema import load_json_document
from websitebench.viewer.metrics import compare_images

from .errors import WorkflowError
from .io import load_json, relative_path, resolve_relative, write_json

SOURCE_ACQUISITION_SCHEMAS = {
    "offline-clone.source-acquisition-report.v1": (
        "offline-clone-source-acquisition-report.schema.json"
    ),
    "offline-clone.source-acquisition-report.v2": (
        "offline-clone-source-acquisition-report-v2.schema.json"
    ),
    "offline-clone.source-acquisition-report.v3": (
        "offline-clone-source-acquisition-report-v3.schema.json"
    ),
}
SEMANTIC_SELECTION_SCHEMAS = {
    "offline-clone.semantic-selection.v1": (
        "offline-clone-semantic-selection.schema.json"
    ),
    "offline-clone.semantic-selection.v2": (
        "offline-clone-semantic-selection-v2.schema.json"
    ),
    "offline-clone.semantic-selection.v3": (
        "offline-clone-semantic-selection-v3.schema.json"
    ),
}
VISUAL_CALIBRATION_SCHEMA = (
    "offline-clone-visual-stability-calibration.schema.json"
)
FULLSTACK_CANDIDATE_SCHEMAS = {
    "offline-clone.fullstack-candidate.v1": (
        "offline-clone-fullstack-candidate.schema.json"
    ),
    "offline-clone.fullstack-candidate.v2": (
        "offline-clone-fullstack-candidate-v2.schema.json"
    ),
    "offline-clone.fullstack-candidate.v3": (
        "offline-clone-fullstack-candidate-v3.schema.json"
    ),
}

MANDATORY_CAPABILITY_PREFIXES = (
    "auth.registration",
    "auth.sign-in",
    "auth.sign-out",
    "auth.session",
    "auth.recovery",
    "mail.",
    "social.like",
    "social.favorite",
    "social.watchlist",
    "social.comment",
    "social.review",
    "commerce.cart",
    "commerce.checkout",
    "commerce.order",
    "account-registration",
    "account-sign-in",
    "session-lifecycle",
    "password-recovery",
    "email-delivery",
    "favorites",
    "software-favorites",
    "watchlist",
    "rating",
    "review-submission",
    "petition-signature-comment",
    "cart-lifecycle",
    "commerce-order-lifecycle",
)
FULL_LOCAL_CAPABILITY_PREFIXES = MANDATORY_CAPABILITY_PREFIXES

REGION_FLOORS = {
    "header": 0.99,
    "action": 0.99,
    "overlay": 0.99,
    "main": 0.98,
    "footer": 0.98,
}
FRONTEND_EVIDENCE_KINDS = frozenset(
    {"visual-calibration", "browser-audit", "focused-regression"}
)
BACKEND_EVIDENCE_KINDS = frozenset(
    {"backend-model", "proof-matrix", "focused-regression", "reset-audit"}
)


def _inside_site(site_id: str, path: str) -> bool:
    normalized = PurePosixPath(path).as_posix()
    root = f"materials/{site_id}"
    return normalized == root or normalized.startswith(f"{root}/")


def _artifact_problems(
    root: Path,
    *,
    site_id: str,
    artifact: dict[str, Any],
) -> list[str]:
    path = artifact["path"]
    problems: list[str] = []
    if not _inside_site(site_id, path):
        return [f"artifact is outside materials/{site_id}: {path}"]
    try:
        resolved = resolve_relative(root, path, must_exist=True)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    if not resolved.is_file():
        return [f"artifact is not a file: {path}"]
    actual_size = resolved.stat().st_size
    if actual_size != artifact["bytes"]:
        problems.append(
            f"artifact byte count mismatch for {path}: "
            f"declared={artifact['bytes']} actual={actual_size}"
        )
    return problems


def validate_source_acquisition_report(
    repository_root: Path | str,
    report_path: Path | str,
) -> dict[str, Any]:
    """Validate one capture-provider-neutral resource closure report."""

    root = Path(repository_root).resolve()
    report_file = resolve_relative(
        root,
        Path(report_path).as_posix(),
        must_exist=True,
    )
    raw_report = load_json(report_file)
    schema_version = raw_report.get("schema_version")
    schema = SOURCE_ACQUISITION_SCHEMAS.get(str(schema_version))
    if schema is None:
        raise WorkflowError(
            f"unsupported source acquisition schema_version: {schema_version}"
        )
    report = load_json_document(report_file, schema)
    site_id = report["site_id"]
    active = schema_version == "offline-clone.source-acquisition-report.v3"
    if not active:
        return {
            "status": "historical",
            "active": False,
            "site_id": site_id,
            "capture_provider": report["capture_provider"],
            "report": relative_path(root, report_file),
            "logical_required": report["resources"]["logical_required"],
            "physical_file_count": report["resources"]["physical_file_count"],
            "blockers": report["blockers"],
        }
    problems: list[str] = []
    problems.extend(
        _artifact_problems(
            root,
            site_id=site_id,
            artifact={"kind": "source-scope", **report["source_scope"]},
        )
    )
    seen_paths: set[str] = set()
    for page in report["pages"]:
        for artifact in page["artifacts"]:
            path = artifact["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            problems.extend(
                _artifact_problems(
                    root,
                    site_id=site_id,
                    artifact=artifact,
                )
            )
    resources = report["resources"]
    closure = report["closure"]
    complete = closure["status"] == "complete"
    if complete:
        if report["blockers"]:
            problems.append("complete acquisition report cannot retain blockers")
        if resources["missing_required_ids"]:
            problems.append(
                "complete acquisition report cannot retain missing required resources"
            )
        required = resources["logical_required"]
        for field in (
            "downloaded",
            "verified",
            "referenced",
            "browser_requested",
        ):
            if resources[field] < required:
                problems.append(
                    f"complete resource closure requires {field} >= "
                    f"logical_required ({resources[field]} < {required})"
                )
        closure_zero_fields = (
            (
                "runtime_remote_request_count",
                "broken_asset_count",
                "unresolved_css_reference_count",
            )
            if schema_version == "offline-clone.source-acquisition-report.v1"
            else (
                "failed_request_count",
                "broken_resource_count",
                "unresolved_css_reference_count",
                "blocked_mutation_request_count",
            )
        )
        for field in closure_zero_fields:
            if closure[field] != 0:
                problems.append(
                    f"complete resource closure requires {field}=0"
                )
        incomplete_pages = [
            page["row_id"]
            for page in report["pages"]
            if page["priority"] in {"p0", "p1"}
            and page["status"] not in {"captured", "source-limited"}
        ]
        if incomplete_pages:
            problems.append(
                "complete acquisition report has incomplete P0/P1 rows: "
                + ", ".join(incomplete_pages)
            )
    if problems:
        raise WorkflowError(problems)
    return {
        "status": "passed" if complete else "blocked",
        "active": True,
        "site_id": site_id,
        "capture_provider": report["capture_provider"],
        "report": relative_path(root, report_file),
        "logical_required": resources["logical_required"],
        "physical_file_count": resources["physical_file_count"],
        "blockers": report["blockers"],
    }


def _known_mandatory(capability: dict[str, Any]) -> bool:
    capability_id = capability["id"]
    return capability["mandatory_when_applicable"] or any(
        capability_id == prefix or capability_id.startswith(prefix)
        for prefix in MANDATORY_CAPABILITY_PREFIXES
    )


def _has_complete_semantic_contract(capability: dict[str, Any]) -> bool:
    state_machine = capability.get("state_machine")
    return (
        bool(capability.get("journey_ids"))
        and bool(capability.get("invariant_ids"))
        and bool(capability.get("server_authorities"))
        and isinstance(state_machine, dict)
        and bool(state_machine.get("states"))
        and bool(state_machine.get("transitions"))
    )


def validate_semantic_selection(
    repository_root: Path | str,
    selection_path: Path | str,
) -> dict[str, Any]:
    """Validate an automatically resolved semantic selection."""

    root = Path(repository_root).resolve()
    selection_file = resolve_relative(
        root,
        Path(selection_path).as_posix(),
        must_exist=True,
    )
    raw_selection = load_json(selection_file)
    schema = SEMANTIC_SELECTION_SCHEMAS.get(raw_selection.get("schema_version"))
    if schema is None:
        raise WorkflowError(
            f"unsupported semantic selection schema: "
            f"{raw_selection.get('schema_version')!r}"
        )
    selection = load_json_document(selection_file, schema)
    active = raw_selection.get("schema_version") == "offline-clone.semantic-selection.v3"
    if not active:
        return {
            "status": "historical",
            "active": False,
            "site_id": selection["site_id"],
            "selection": relative_path(root, selection_file),
            "selected_capability_ids": [],
            "external_blocked_capability_ids": [],
            "persistent_backend_ready": False,
        }
    problems: list[str] = []
    frontend_problems = _validate_subject(
        root,
        site_id=selection["site_id"],
        subject=selection["frontend_subject"],
        label="frontend subject",
    )
    source_problems = _validate_subject(
        root,
        site_id=selection["site_id"],
        subject=selection["source_scope_subject"],
        label="source scope subject",
    )
    problems.extend(frontend_problems)
    problems.extend(source_problems)
    backend_model = f"materials/{selection['site_id']}/backend/model.json"
    if (root / backend_model).is_file() and backend_model not in {
        artifact["path"]
        for artifact in selection["source_scope_subject"]["artifacts"]
    }:
        problems.append(
            "source scope subject must bind the current backend semantic contract"
        )
    external_blocked: list[str] = []
    selected: list[str] = []
    seen_capabilities: set[str] = set()
    for capability in selection["capabilities"]:
        capability_id = capability["id"]
        if capability_id in seen_capabilities:
            problems.append(f"duplicate capability id: {capability_id}")
        seen_capabilities.add(capability_id)
        applicable = capability["applicable"]
        disposition = capability["disposition"]
        mandatory = applicable and _known_mandatory(capability)
        if mandatory and disposition in {
            "excluded-with-rationale",
            "truthful-simulation",
        }:
            problems.append(
                f"{capability_id}: applicable mandatory capability cannot be "
                f"{disposition}"
            )
        if (
            applicable
            and disposition == "truthful-simulation"
            and any(
                capability_id == prefix or capability_id.startswith(prefix)
                for prefix in FULL_LOCAL_CAPABILITY_PREFIXES
            )
        ):
            problems.append(
                f"{capability_id}: applicable account/social state must use "
                "full-local-model or an evidence-backed external blocker"
            )
        if not applicable and disposition != "excluded-with-rationale":
            problems.append(
                f"{capability_id}: inapplicable capability must be "
                "excluded-with-rationale"
            )
        if (
            applicable
            and capability["priority"] in {"p0", "p1"}
            and disposition == "external-blocked"
        ):
            external_blocked.append(capability_id)
        if applicable and disposition == "unresolved":
            problems.append(f"{capability_id}: active selection cannot be unresolved")
        if capability["decision_source"] != "mechanical":
            problems.append(f"{capability_id}: decision_source must be mechanical")
        if applicable and disposition in {
            "full-local-model",
            "truthful-simulation",
        }:
            selected.append(capability_id)
    expected_status = "blocked" if external_blocked else "passed"
    if problems:
        raise WorkflowError(problems)
    return {
        "status": expected_status,
        "active": True,
        "site_id": selection["site_id"],
        "selection": relative_path(root, selection_file),
        "selected_capability_ids": sorted(selected),
        "external_blocked_capability_ids": sorted(external_blocked),
        "persistent_backend_ready": expected_status == "passed",
    }


def _validate_subject(
    root: Path,
    *,
    site_id: str,
    subject: dict[str, Any],
    label: str,
) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for artifact in subject["artifacts"]:
        path = artifact["path"]
        if path in seen:
            problems.append(f"{label} repeats artifact path: {path}")
            continue
        seen.add(path)
        if not _inside_site(site_id, path) and not path.startswith(
            f"websitebench/site-profiles/{site_id}/"
        ):
            problems.append(f"{label} artifact is outside site inputs: {path}")
            continue
        resolved = resolve_relative(root, path)
        kind = artifact["kind"]
        if kind == "file" and not resolved.is_file():
            problems.append(f"{label} artifact is not a file: {path}")
            continue
        if kind == "tree" and not resolved.is_dir():
            problems.append(f"{label} artifact is not a directory: {path}")
            continue
        if kind == "file" and resolved.stat().st_size != artifact.get("bytes"):
            problems.append(
                f"{label} artifact byte count mismatch for {path}: "
                f"declared={artifact.get('bytes')} actual={resolved.stat().st_size}"
            )
    return problems


def _validate_candidate_evidence(
    root: Path,
    *,
    site_id: str,
    evidence: list[dict[str, Any]],
    label: str,
    required_kinds: frozenset[str],
) -> list[str]:
    problems: list[str] = []
    seen_kinds: set[str] = set()
    seen_paths: set[str] = set()
    for artifact in evidence:
        kind = artifact["kind"]
        path = artifact["path"]
        if kind in seen_kinds:
            problems.append(f"{label} repeats evidence kind: {kind}")
        seen_kinds.add(kind)
        if path in seen_paths:
            problems.append(f"{label} repeats evidence path: {path}")
        seen_paths.add(path)
        if not _inside_site(site_id, path):
            problems.append(
                f"{label} evidence is outside materials/{site_id}: {path}"
            )
            continue
        resolved = resolve_relative(root, path)
        if not resolved.is_file():
            problems.append(f"{label} evidence is not a file: {path}")
            continue
        actual_size = resolved.stat().st_size
        if actual_size != artifact["bytes"]:
            problems.append(
                f"{label} evidence byte count mismatch for {path}: "
                f"declared={artifact['bytes']} actual={actual_size}"
            )
    missing = sorted(required_kinds - seen_kinds)
    if missing:
        problems.append(f"{label} lacks required evidence kinds: {', '.join(missing)}")
    return problems


def validate_fullstack_candidate(
    repository_root: Path | str,
    candidate_path: Path | str,
) -> dict[str, Any]:
    """Require a complete machine-verifiable candidate."""

    root = Path(repository_root).resolve()
    candidate_file = resolve_relative(
        root,
        Path(candidate_path).as_posix(),
        must_exist=True,
    )
    raw_candidate = load_json(candidate_file)
    schema = FULLSTACK_CANDIDATE_SCHEMAS.get(raw_candidate.get("schema_version"))
    if schema is None:
        raise WorkflowError(
            f"unsupported fullstack candidate schema: "
            f"{raw_candidate.get('schema_version')!r}"
        )
    candidate = load_json_document(candidate_file, schema)
    if candidate["schema_version"] != "offline-clone.fullstack-candidate.v3":
        raise WorkflowError(
            "legacy fullstack candidates are historical and cannot pass active checks"
        )
    site_id = candidate["site_id"]
    problems: list[str] = []
    clone_ref = candidate["candidate_tree"]
    if not _inside_site(site_id, clone_ref["path"]):
        problems.append(
            f"candidate tree is outside materials/{site_id}: {clone_ref['path']}"
        )
    clone_root = resolve_relative(root, clone_ref["path"])
    if not clone_root.is_dir():
        problems.append(f"candidate tree is not a directory: {clone_ref['path']}")
    acquisition_ref = candidate["source_acquisition"]
    semantic_ref = candidate["semantic_selection"]
    for label, reference in (
        ("source acquisition", acquisition_ref),
        ("semantic selection", semantic_ref),
    ):
        if not _inside_site(site_id, reference["path"]):
            problems.append(
                f"{label} is outside materials/{site_id}: {reference['path']}"
            )
    acquisition_file = resolve_relative(
        root,
        acquisition_ref["path"],
        must_exist=True,
    )
    selection_file = resolve_relative(
        root,
        semantic_ref["path"],
        must_exist=True,
    )
    for label, path, reference in (
        ("source acquisition", acquisition_file, acquisition_ref),
        ("semantic selection", selection_file, semantic_ref),
    ):
        actual_size = path.stat().st_size
        if actual_size != reference["bytes"]:
            problems.append(
                f"{label} byte count mismatch: declared={reference['bytes']} "
                f"actual={actual_size}"
            )
    frontend = candidate["frontend"]
    backend = candidate["backend"]
    problems.extend(
        _validate_candidate_evidence(
            root,
            site_id=site_id,
            evidence=frontend["evidence"],
            label="frontend",
            required_kinds=FRONTEND_EVIDENCE_KINDS,
        )
    )
    problems.extend(
        _validate_candidate_evidence(
            root,
            site_id=site_id,
            evidence=backend["evidence"],
            label="backend",
            required_kinds=BACKEND_EVIDENCE_KINDS,
        )
    )
    expected_backend_path = f"materials/{site_id}/backend/model.json"
    backend_model_refs = [
        item["path"]
        for item in backend["evidence"]
        if item["kind"] == "backend-model"
    ]
    if backend_model_refs != [expected_backend_path]:
        problems.append(
            "backend-model evidence must bind the exact site model: "
            f"{expected_backend_path}"
        )
    semantic_result: dict[str, Any] | None = None
    if not problems:
        acquisition = validate_source_acquisition_report(
            root,
            acquisition_ref["path"],
        )
        semantic_result = validate_semantic_selection(
            root,
            semantic_ref["path"],
        )
        if acquisition["site_id"] != site_id:
            problems.append("source acquisition site_id does not match candidate")
        if semantic_result["site_id"] != site_id:
            problems.append("semantic selection site_id does not match candidate")
        if acquisition["status"] != "passed":
            problems.append("source acquisition is not complete")
        if semantic_result["status"] != "passed":
            problems.append("semantic selection is not machine-valid")
    if frontend["runtime_remote_request_count"] != 0:
        problems.append("frontend runtime remote request count must be zero")
    if frontend["console_error_count"] != 0:
        problems.append("frontend console error count must be zero")
    if frontend["candidate_stability_runs"] < 2:
        problems.append("frontend requires at least two stable candidate runs")
    if frontend["p0_region_failures"] != 0:
        problems.append("frontend cannot retain P0 visual region failures")
    if (
        backend["verified_capability_count"]
        != backend["applicable_capability_count"]
    ):
        problems.append(
            "backend verified capability count must equal applicable count"
        )
    if (
        semantic_result is not None
        and backend["applicable_capability_count"]
        != len(semantic_result["selected_capability_ids"])
    ):
        problems.append(
            "backend applicable capability count does not match semantic selection"
        )
    if backend["proof_obligation_failures"] != 0:
        problems.append("backend proof obligations must be complete")
    if candidate["status"] != "complete":
        problems.append("full-stack candidate status must be complete")
    if problems:
        raise WorkflowError(problems)
    return {
        "status": "passed",
        "site_id": site_id,
        "candidate": relative_path(root, candidate_file),
    }


def calibrate_visual_stability(
    repository_root: Path | str,
    spec_path: Path | str,
    output_path: Path | str,
) -> dict[str, Any]:
    """Recommend pixel-MAE similarity thresholds from source stability."""

    root = Path(repository_root).resolve()
    spec_file = resolve_relative(
        root,
        Path(spec_path).as_posix(),
        must_exist=True,
    )
    spec = load_json_document(spec_file, VISUAL_CALIBRATION_SCHEMA)
    rows: list[dict[str, Any]] = []
    for row in spec["rows"]:
        region = row["region"]
        samples = [
            resolve_relative(root, sample["path"], must_exist=True)
            for sample in row["source_samples"]
        ]
        similarities: list[float] = []
        metrics: list[dict[str, float]] = []
        heatmap_root = resolve_relative(
            root,
            f".clone-harness/visual-calibration/{spec['site_id']}/{row['id']}",
        )
        for index, (left, right) in enumerate(combinations(samples, 2), start=1):
            result = compare_images(
                left,
                right,
                heatmap_root / f"source-pair-{index}.webp",
                ignore_regions=row["ignore_regions"],
            )
            metrics.append(result)
            similarities.append(round(1.0 - result["normalized_mae"], 4))
        source_self_similarity = min(similarities)
        floor = REGION_FLOORS[region]
        recommended = round(
            max(floor, min(1.0, source_self_similarity - 0.005)),
            4,
        )
        source_limited = source_self_similarity < floor
        rows.append(
            {
                "id": row["id"],
                "region": region,
                "source_self_similarity": source_self_similarity,
                "region_floor": floor,
                "recommended_threshold": recommended,
                "source_limited": source_limited,
                "pair_metrics": metrics,
            }
        )
    report = {
        "schema_version": "offline-clone.visual-stability-calibration.v1",
        "site_id": spec["site_id"],
        "spec": {"path": relative_path(root, spec_file)},
        "metric": "pixel-mae-similarity-v1",
        "formula": "max(region-floor,min-source-self-similarity-minus-0.005)",
        "rows": rows,
        "status": (
            "source-limited"
            if any(row["source_limited"] for row in rows)
            else "calibrated"
        ),
    }
    output = resolve_relative(root, Path(output_path).as_posix())
    write_json(output, report)
    return {
        **report,
        "path": relative_path(root, output),
    }


def _subject_artifact(root: Path, path: Path) -> dict[str, str]:
    artifact = {
        "kind": "file" if path.is_file() else "tree",
        "path": relative_path(root, path),
    }
    if path.is_file():
        artifact["bytes"] = path.stat().st_size
    return artifact


def scaffold_semantic_selection(
    repository_root: Path | str,
    site_id: str,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create a conservative, create-only semantic decision queue."""

    root = Path(repository_root).resolve()
    material = root / "materials" / site_id
    backend_path = material / "backend" / "model.json"
    if not backend_path.is_file():
        raise WorkflowError(
            f"backend model does not exist: materials/{site_id}/backend/model.json"
        )
    backend = load_json_document(
        backend_path,
        "offline-clone-backend-model.schema.json",
    )
    capabilities = [
        capability
        for capability in backend.get("capabilities", [])
        if isinstance(capability, dict)
        and isinstance(capability.get("id"), str)
    ]
    if not capabilities:
        raise WorkflowError(f"{site_id} backend model has no capabilities")
    frontend_paths = [
        path
        for path in (
            material / "clone" / "frontend",
            material / "clone" / "static",
            material / "clone" / "templates",
        )
        if path.exists()
    ]
    if not frontend_paths:
        clone = material / "clone"
        if not clone.is_dir():
            raise WorkflowError(f"{site_id} clone tree does not exist")
        frontend_paths = [clone]
    source_paths: list[Path] = []
    source_paths.append(backend_path)
    profile = root / "websitebench" / "site-profiles" / site_id / "site.json"
    if profile.is_file():
        source_paths.append(profile)
    scope = material / "scope"
    if scope.is_dir():
        source_paths.extend(
            path
            for path in sorted(scope.iterdir())
            if path.is_file()
            and path.name
            not in {"semantic-selection.json", "review-obligations.json"}
        )
    source_current = material / "source-current"
    if source_current.is_dir():
        source_paths.append(source_current)
    if not source_paths:
        raise WorkflowError(f"{site_id} has no source/scope subject artifacts")
    frontend_artifacts = sorted(
        (_subject_artifact(root, path) for path in frontend_paths),
        key=lambda item: item["path"],
    )
    source_artifacts = sorted(
        (_subject_artifact(root, path) for path in source_paths),
        key=lambda item: item["path"],
    )
    rows = []
    automatically_resolved: list[str] = []
    seen: set[str] = set()
    for capability in capabilities:
        capability_id = capability["id"]
        if capability_id in seen:
            raise WorkflowError(f"duplicate backend capability id: {capability_id}")
        seen.add(capability_id)
        priority = str(capability.get("priority", "p1")).lower()
        if priority not in {"p0", "p1", "p2"}:
            priority = "p1"
        probe = {
            "id": capability_id,
            "mandatory_when_applicable": False,
        }
        mandatory = _known_mandatory(probe)
        compiled_contract = _has_complete_semantic_contract(capability)
        determinate = mandatory or compiled_contract
        certainty = "determinate" if determinate else "ambiguous"
        disposition = (
            "full-local-model"
            if determinate or priority in {"p0", "p1"}
            else "truthful-simulation"
        )
        if not determinate:
            automatically_resolved.append(capability_id)
        evidence_refs = [
            f"materials/{site_id}/backend/model.json#capability:{capability_id}"
        ]
        evidence_refs.extend(
            f"materials/{site_id}/scope/journeys.json#journey:{journey_id}"
            for journey_id in capability.get("journey_ids", [])
            if isinstance(journey_id, str)
        )
        evidence_refs.extend(
            f"materials/{site_id}/scope/invariants.json#invariant:{invariant_id}"
            for invariant_id in capability.get("invariant_ids", [])
            if isinstance(invariant_id, str)
        )
        rows.append(
            {
                "id": capability_id,
                "priority": priority,
                "applicable": True,
                "certainty": certainty,
                "mandatory_when_applicable": mandatory,
                "trigger": (
                    "common-stateful-core"
                    if mandatory
                    else (
                        "core-purpose"
                        if compiled_contract
                        else "inferred-ambiguous"
                    )
                ),
                "evidence_refs": evidence_refs,
                "disposition": disposition,
                "decision_source": "mechanical",
                "rationale": (
                    "Applicable common stateful capability; full local modeling "
                    "is mandatory."
                    if mandatory
                    else (
                        "The compiled P0/P1 journey, invariant, server-authority, "
                        "and state-machine contract determine full local depth."
                        if compiled_contract
                        else
                        "Ambiguous P0/P1 capabilities default to full local "
                        "modeling; ambiguous P2 capabilities use truthful simulation."
                    )
                ),
            }
        )
    value = {
        "schema_version": "offline-clone.semantic-selection.v3",
        "site_id": site_id,
        "selection_id": f"{site_id}.semantic-selection.auto",
        "frontend_subject": {"artifacts": frontend_artifacts},
        "source_scope_subject": {"artifacts": source_artifacts},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_policy": "fidelity-first-automatic-v1",
        "capabilities": rows,
    }
    output = (
        resolve_relative(root, Path(output_path).as_posix())
        if output_path is not None
        else material / "scope" / "semantic-selection.json"
    )
    write_json(output, value, create_only=True)
    return {
        "status": "passed",
        "site_id": site_id,
        "path": relative_path(root, output),
        "automatically_resolved_capability_ids": sorted(automatically_resolved),
    }
