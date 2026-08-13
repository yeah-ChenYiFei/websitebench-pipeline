"""Build replay and behavioral-diff artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import (
    DIFF_CATEGORIES,
    WebCloningError,
    artifact_ref,
    canonical_json_bytes,
    load_json,
    repository_path,
    require_valid,
    sha256_bytes,
)


def _load_contract(path: Path, version: str) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema_version") != version:
        raise WebCloningError(
            f"{path}: expected {version}, got {value.get('schema_version')!r}"
        )
    require_valid(value, location=str(path))
    return value


def _mapping_manifest(
    path: Path | None, *, repository_root: Path
) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    value = load_json(path)
    entries = value.get("mappings")
    if not isinstance(entries, list):
        raise WebCloningError(f"{path}: mappings must be an array")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(
            entry.get("source_step_id"), str
        ):
            raise WebCloningError(f"{path}: invalid mapping entry")
        if entry["source_step_id"] in result:
            raise WebCloningError(f"{path}: duplicate source_step_id")
        required = ("clone_step_id", "rationale", "approved_by", "approval")
        if any(not entry.get(key) for key in required):
            raise WebCloningError(f"{path}: incomplete equivalence approval")
        if not _ref_is_present(entry["approval"], repository_root=repository_root):
            raise WebCloningError(f"{path}: equivalence approval artifact is missing")
        result[entry["source_step_id"]] = entry
    return result


def build_replay(
    *,
    repository_root: Path,
    source_path: Path,
    clone_path: Path,
    candidate_path: Path,
    semantic_selection_path: Path,
    runtime_identity_path: Path,
    reset_evidence_path: Path,
    mapping_path: Path | None = None,
) -> dict[str, Any]:
    source = _load_contract(source_path, "webcloning.normalized-trace.v1")
    clone = _load_contract(clone_path, "webcloning.normalized-trace.v1")
    if source["environment"] != "source" or clone["environment"] != "clone":
        raise WebCloningError("replay requires source and clone normalized traces")
    if source["site_id"] != clone["site_id"]:
        raise WebCloningError("source/clone site_id mismatch")
    candidate = load_json(candidate_path)
    if (
        candidate.get("schema_version")
        not in {
            "offline-clone.fullstack-candidate.v3",
        }
        or candidate.get("site_id") != source["site_id"]
        or candidate.get("status") != "complete"
    ):
        raise WebCloningError(
            f"{candidate_path}: replay requires a complete exact-site fullstack candidate"
        )
    frontend = candidate.get("frontend", {})
    backend = candidate.get("backend", {})
    if (
        frontend.get("p0_region_failures") != 0
        or frontend.get("console_error_count") != 0
        or frontend.get("runtime_remote_request_count") != 0
        or backend.get("proof_obligation_failures") != 0
        or backend.get("applicable_capability_count")
        != backend.get("verified_capability_count")
    ):
        raise WebCloningError(f"{candidate_path}: fullstack precheck is not clean")
    semantic = load_json(semantic_selection_path)
    if (
        semantic.get("schema_version")
        not in {
            "offline-clone.semantic-selection.v3",
        }
        or semantic.get("site_id") != source["site_id"]
        or semantic.get("selection_policy") != "fidelity-first-automatic-v1"
    ):
        raise WebCloningError(
            f"{semantic_selection_path}: active automatic semantic selection is required"
        )
    runtime = load_json(runtime_identity_path)
    required_runtime = (
        "clone_url",
        "process_identity",
        "process_started_at",
        "version_marker",
        "reset_seed",
    )
    if any(runtime.get(key) in (None, "") for key in required_runtime):
        raise WebCloningError(f"{runtime_identity_path}: incomplete runtime identity")
    mappings = _mapping_manifest(mapping_path, repository_root=repository_root)
    clone_by_id = {step["step_id"]: step for step in clone["steps"]}
    clone_steps = clone["steps"]
    used_clone: set[str] = set()
    replay_steps: list[dict[str, Any]] = []
    for index, source_step in enumerate(source["steps"]):
        candidate = clone_steps[index] if index < len(clone_steps) else None
        mapping = "missing"
        equivalence = None
        if candidate and (
            source_step["action"]["family"] == candidate["action"]["family"]
            and source_step["action"]["target"] == candidate["action"]["target"]
        ):
            mapping = "exact"
        elif source_step["step_id"] in mappings:
            declared = mappings[source_step["step_id"]]
            candidate = clone_by_id.get(declared["clone_step_id"])
            if candidate is None:
                raise WebCloningError(
                    f"mapping references absent clone step {declared['clone_step_id']}"
                )
            mapping = "equivalent"
            equivalence = {
                key: declared[key]
                for key in ("rationale", "approved_by", "approval")
            }
        if candidate is not None and mapping != "missing":
            used_clone.add(candidate["step_id"])
        replay_steps.append(
            {
                "source_step_id": source_step["step_id"],
                "clone_step_id": (
                    candidate["step_id"] if candidate is not None and mapping != "missing" else None
                ),
                "mapping": mapping,
                "equivalence": equivalence,
                "action_family_match": (
                    candidate is not None
                    and source_step["action"]["family"]
                    == candidate["action"]["family"]
                ),
                "observable_state_match": (
                    candidate is not None
                    and source_step["after"]["observable_sha256"]
                    == candidate["after"]["observable_sha256"]
                ),
                "outcome_match": (
                    candidate is not None
                    and source_step["outcome"] == candidate["outcome"]
                ),
                "source_error": source_step["error"],
                "clone_error": candidate["error"] if candidate is not None else None,
            }
        )
    exact = sum(step["mapping"] == "exact" for step in replay_steps)
    equivalent = sum(step["mapping"] == "equivalent" for step in replay_steps)
    missing = len(replay_steps) - exact - equivalent
    denominator = len(replay_steps) or 1
    reset = load_json(reset_evidence_path)
    reset_status = reset.get("status")
    if reset_status not in {"passed", "failed"}:
        raise WebCloningError(f"{reset_evidence_path}: reset status must be passed/failed")
    status = (
        "complete"
        if source["status"] == clone["status"] == "complete"
        and missing == 0
        and reset_status == "passed"
        else "incomplete"
    )
    source_ref = artifact_ref(source_path, root=repository_root)
    clone_ref = artifact_ref(clone_path, root=repository_root)
    candidate_ref = artifact_ref(candidate_path, root=repository_root)
    semantic_ref = artifact_ref(semantic_selection_path, root=repository_root)
    runtime_ref = artifact_ref(runtime_identity_path, root=repository_root)
    reset_ref = artifact_ref(reset_evidence_path, root=repository_root)
    equivalence_ref = (
        artifact_ref(mapping_path, root=repository_root)
        if mapping_path is not None
        else None
    )
    analysis_id = sha256_bytes(
        canonical_json_bytes(
            {
                "site_id": source["site_id"],
                "source_trace_sha256": source_ref["sha256"],
                "clone_trace_sha256": clone_ref["sha256"],
                "candidate_sha256": candidate_ref["sha256"],
                "semantic_selection_sha256": semantic_ref["sha256"],
                "runtime_identity_sha256": runtime_ref["sha256"],
                "reset_sha256": reset_ref["sha256"],
                "equivalence_manifest_sha256": (
                    equivalence_ref["sha256"]
                    if equivalence_ref is not None
                    else None
                ),
            }
        )
    )
    return (
        {
            "schema_version": "webcloning.replay.v1",
            "analysis_id": analysis_id,
            "site_id": source["site_id"],
            "generator": "clawbench.webcloning.replay-materializer.v1",
            "source_trace": source_ref,
            "clone_trace": clone_ref,
            "candidate": candidate_ref,
            "semantic_selection": semantic_ref,
            "runtime_identity": runtime_ref,
            "reset": {
                **reset_ref,
                "status": reset_status,
            },
            "equivalence_manifest": equivalence_ref,
            "steps": replay_steps,
            "unmapped_clone_step_ids": sorted(
                set(clone_by_id).difference(used_clone)
            ),
            "coverage": {
                "source_step_count": len(replay_steps),
                "exact_step_count": exact,
                "equivalent_step_count": equivalent,
                "missing_step_count": missing,
                "exact_coverage": exact / denominator,
                "equivalent_coverage": equivalent / denominator,
                "total_coverage": (exact + equivalent) / denominator,
            },
            "status": status,
            "authority": (
                "replay-evidence-only-cannot-prove-corpus-validity-or-release"
            ),
        }
    )


def _finding(
    *,
    number: int,
    category: str,
    severity: str,
    summary: str,
    source_step_id: str | None,
    clone_step_id: str | None,
    status: str = "open",
    regression: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "finding_id": f"d{number:04d}",
        "category": category,
        "severity": severity,
        "summary": summary,
        "source_step_id": source_step_id,
        "clone_step_id": clone_step_id,
        "impact": (
            "may-change-solvability-or-ranking"
            if severity in {"P0", "P1"}
            else "trace-fidelity-only"
        ),
        "status": status,
        "regression": regression,
    }


def build_diff(
    *,
    repository_root: Path,
    replay_path: Path,
    findings_path: Path | None = None,
) -> dict[str, Any]:
    replay = _load_contract(replay_path, "webcloning.replay.v1")
    findings: list[dict[str, Any]] = []
    for step in replay["steps"]:
        if step["mapping"] == "missing":
            findings.append(
                _finding(
                    number=len(findings) + 1,
                    category="missing-element",
                    severity="P1",
                    summary="Source action has no replayable clone action.",
                    source_step_id=step["source_step_id"],
                    clone_step_id=None,
                )
            )
            continue
        if not step["action_family_match"]:
            findings.append(
                _finding(
                    number=len(findings) + 1,
                    category="operation-semantics",
                    severity="P1",
                    summary="Source and clone use different action families.",
                    source_step_id=step["source_step_id"],
                    clone_step_id=step["clone_step_id"],
                )
            )
        if not step["observable_state_match"]:
            findings.append(
                _finding(
                    number=len(findings) + 1,
                    category="state-transition",
                    severity="P1",
                    summary="Post-action observable state differs.",
                    source_step_id=step["source_step_id"],
                    clone_step_id=step["clone_step_id"],
                )
            )
        if not step["outcome_match"] or step["source_error"] != step["clone_error"]:
            findings.append(
                _finding(
                    number=len(findings) + 1,
                    category="error-behavior",
                    severity="P1",
                    summary="Outcome or error behavior differs.",
                    source_step_id=step["source_step_id"],
                    clone_step_id=step["clone_step_id"],
                )
            )
    for clone_step_id in replay["unmapped_clone_step_ids"]:
        findings.append(
            _finding(
                number=len(findings) + 1,
                category="clone-only-shortcut",
                severity="P1",
                summary="Clone executed an action absent from the source path.",
                source_step_id=None,
                clone_step_id=clone_step_id,
            )
        )
    supplemental_ref = None
    if findings_path is not None:
        supplemental = load_json(findings_path)
        values = supplemental.get("findings")
        if not isinstance(values, list):
            raise WebCloningError(f"{findings_path}: findings must be an array")
        for raw in values:
            if not isinstance(raw, dict):
                raise WebCloningError(f"{findings_path}: finding must be an object")
            category = raw.get("category")
            if category not in DIFF_CATEGORIES:
                raise WebCloningError(f"{findings_path}: unknown category {category!r}")
            regression = raw.get("regression")
            findings.append(
                _finding(
                    number=len(findings) + 1,
                    category=category,
                    severity=raw.get("severity", "P2"),
                    summary=str(raw.get("summary", "")),
                    source_step_id=raw.get("source_step_id"),
                    clone_step_id=raw.get("clone_step_id"),
                    status=raw.get("status", "open"),
                    regression=regression,
                )
            )
        supplemental_ref = artifact_ref(findings_path, root=repository_root)
    by_category = {category: 0 for category in DIFF_CATEGORIES}
    by_severity = {"P0": 0, "P1": 0, "P2": 0}
    by_status = {"open": 0, "closed": 0}
    for finding in findings:
        by_category[finding["category"]] += 1
        by_severity[finding["severity"]] += 1
        by_status[finding["status"]] += 1
    return (
        {
            "schema_version": "webcloning.behavior-diff.v1",
            "analysis_id": replay["analysis_id"],
            "site_id": replay["site_id"],
            "generator": "clawbench.webcloning.behavior-diff.v1",
            "replay": artifact_ref(replay_path, root=repository_root),
            "supplemental_findings": supplemental_ref,
            "findings": findings,
            "counts": {
                "total": len(findings),
                "by_category": by_category,
                "by_severity": by_severity,
                "by_status": by_status,
            },
            "status": "complete" if replay["status"] == "complete" else "incomplete",
            "authority": (
                "behavior-difference-evidence-only-cannot-accept-fidelity-or-release"
            ),
        }
    )


def _ref_is_present(ref: dict[str, Any], *, repository_root: Path) -> bool:
    try:
        path = repository_path(repository_root, ref["path"])
        return path.is_file()
    except (KeyError, TypeError, OSError, WebCloningError):
        return False
