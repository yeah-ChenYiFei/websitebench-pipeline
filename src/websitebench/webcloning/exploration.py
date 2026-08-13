"""Import ClawBench runs and build trace-guided exploration contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .contracts import (
    WebCloningError,
    artifact_ref,
    canonical_json_bytes,
    load_json,
    load_jsonl,
    repository_path,
    require_valid,
    seal_document,
    sha256_bytes,
    sha256_file,
    write_json_atomic,
)
from .trace import normalize_trace

EMAIL = re.compile(r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|cookie|authorization|otp|cvv|cvc)"
    r"\b\s*[:=]\s*[^\s,;]+"
)
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
SENSITIVE_TARGET = re.compile(
    r"(?i)(password|passwd|pwd|email|username|address|card|cvv|cvc|otp|token|secret)"
)
RUN_TIMESTAMP = re.compile(r"(\d{8}[-_]\d{4,6})$")


def _safe_text(value: Any, *, limit: int = 2000) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True
    )
    text = EMAIL.sub("[REDACTED:email]", text)
    text = BEARER.sub("Bearer [REDACTED]", text)
    text = SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", text)
    text = CARD.sub("[REDACTED:payment]", text)
    return text[:limit]


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _safe_text(value)
    if not parsed.scheme:
        return parsed.path or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _target_summary(record: dict[str, Any]) -> str | None:
    target = record.get("target")
    if not isinstance(target, dict):
        return _safe_text(target) or None
    selected = {
        key: target.get(key)
        for key in ("tagName", "id", "name", "type", "role", "textContent", "xpath")
        if target.get(key) not in (None, "")
    }
    return _safe_text(selected) or None


def _target_is_sensitive(record: dict[str, Any]) -> bool:
    target = record.get("target")
    if not isinstance(target, dict):
        return bool(SENSITIVE_TARGET.search(str(target or "")))
    markers = " ".join(
        str(target.get(key, ""))
        for key in ("id", "name", "type", "autocomplete", "ariaLabel", "xpath")
    )
    return bool(SENSITIVE_TARGET.search(markers))


def sanitize_clawbench_actions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert real ClawBench browser events to the normalizer's safe shape."""

    result: list[dict[str, Any]] = []
    previous = {"url": None, "title": None, "markers": []}
    for raw in records:
        action = str(raw.get("type") or raw.get("action") or "unknown")
        route = _safe_url(raw.get("url")) or previous["url"]
        title = _safe_text(raw.get("title")) or previous["title"]
        target = _target_summary(raw)
        markers = [target] if target else []
        after = {"url": route, "title": title, "markers": markers}
        observations: list[dict[str, str]] = []
        if target:
            observations.append({"kind": "browser-target", "summary": target})
        if "value" in raw:
            observations.append(
                {
                    "kind": "input-value",
                    "summary": (
                        "[REDACTED:sensitive-input]"
                        if _target_is_sensitive(raw)
                        else "[REDACTED:input]"
                    ),
                }
            )
        result.append(
            {
                "actor": "clawbench-agent",
                "action": action,
                "target": target or route,
                "before": previous,
                "after": after,
                "observations": observations,
                "outcome": "ok",
                "tokens": 0,
            }
        )
        previous = after
    return result


def _run_result(run_dir: Path) -> str:
    interception_path = run_dir / "data" / "interception.json"
    judge_path = run_dir / "data" / "judge.json"
    intercepted = False
    if interception_path.is_file():
        intercepted = bool(load_json(interception_path).get("intercepted"))
    if not intercepted:
        return "failure"
    if not judge_path.is_file():
        return "success"
    judge = load_json(judge_path)
    values: list[Any] = [
        judge.get("match"),
        judge.get("passed"),
        judge.get("final_pass"),
        judge.get("judge_match"),
        judge.get("verdict"),
    ]
    for value in list(values):
        if isinstance(value, dict):
            values.extend(value.values())
    if any(
        value is True
        or str(value).casefold() in {"pass", "passed", "match", "true"}
        for value in values
    ):
        return "success"
    return "failure"


def _run_sort_key(path: Path) -> tuple[str, str]:
    meta_path = path / "run-meta.json"
    timestamp = ""
    if meta_path.is_file():
        timestamp = str(load_json(meta_path).get("timestamp") or "")
    if not timestamp:
        match = RUN_TIMESTAMP.search(path.name)
        timestamp = match.group(1) if match else path.name
    return timestamp, path.as_posix()


def select_clawbench_runs(*, runs_root: Path, task_id: int) -> dict[str, Any]:
    """Select the latest successful and latest representative failed run."""

    markers = (f"-{task_id}-", f"-{task_id:03d}-", f"-{task_id:04d}-")
    candidates = [
        path
        for path in runs_root.rglob("*")
        if path.is_dir()
        and (path / "data" / "actions.jsonl").is_file()
        and any(marker in f"-{path.name}-" for marker in markers)
    ]
    classified = {
        "success": sorted(
            (path for path in candidates if _run_result(path) == "success"),
            key=_run_sort_key,
        ),
        "failure": sorted(
            (path for path in candidates if _run_result(path) == "failure"),
            key=_run_sort_key,
        ),
    }
    return {
        "task_id": task_id,
        "policy": "latest-success-and-representative-failure-v1",
        "success": str(classified["success"][-1]) if classified["success"] else None,
        "failure": str(classified["failure"][-1]) if classified["failure"] else None,
        "candidate_count": len(candidates),
        "status": "complete" if all(classified.values()) else "incomplete",
    }


def _interaction_summary(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    if path.stat().st_size == 0:
        return []
    records = load_jsonl(path)
    summaries: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        role = _safe_text(record.get("role") or record.get("type") or "unknown", limit=80)
        tool = record.get("tool_name") or record.get("name")
        content = record.get("content")
        summaries.append(
            {
                "index": index,
                "role": role,
                "kind": "tool" if tool else "message",
                "tool_name": _safe_text(tool, limit=200) if tool else None,
                "content_present": content not in (None, "", []),
                "content_retained": False,
            }
        )
    return summaries


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
        for record in records
    )
    path.write_text(rendered, encoding="utf-8")


def import_clawbench_run(
    *,
    run_dir: Path,
    task_path: Path,
    artifact_root: Path,
    output_dir: Path,
    site_id: str,
    suite: str,
    dataset_id: str | None = None,
    dataset_revision: str = "main",
) -> dict[str, Any]:
    """Import one controlled raw run and retain only sanitized derivatives."""

    run_dir = run_dir.resolve()
    artifact_root = artifact_root.resolve()
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(artifact_root)
    except ValueError as exc:
        raise WebCloningError("output_dir must stay under artifact_root") from exc
    actions_path = run_dir / "data" / "actions.jsonl"
    if not actions_path.is_file():
        raise WebCloningError(f"{run_dir}: data/actions.jsonl is missing")
    task = load_json(task_path)
    metadata = task.get("metadata", {})
    task_snapshot = {
        "metadata": {
            "task_id": metadata.get("task_id"),
            "platform": metadata.get("platform"),
        },
        # The task identity is retained by task_id/platform and the snapshot
        # artifact hash. Free-form instructions may contain personal details.
        "instruction": "[REDACTED:task-instruction]",
    }
    meta_path = run_dir / "run-meta.json"
    meta = load_json(meta_path) if meta_path.is_file() else {}
    result = _run_result(run_dir)
    run_snapshot = {
        "agent": _safe_text(meta.get("harness") or "clawbench", limit=200),
        "model": _safe_text(meta.get("model") or "unknown", limit=200),
        "provider": _safe_text(meta.get("provider") or "clawbench", limit=200),
        "config_sha256": sha256_bytes(
            canonical_json_bytes(
                {
                    "harness": meta.get("harness"),
                    "model": meta.get("model"),
                    "time_limit_minutes": meta.get("time_limit_minutes"),
                }
            )
        ),
        "seed": meta.get("seed", "unavailable"),
        "run_id": run_dir.name,
        "task_result": result,
        "raw_trace_access": "repository-redacted",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    task_snapshot_path = output_dir / "task-snapshot.json"
    run_snapshot_path = output_dir / "run-snapshot.json"
    sanitized_actions_path = output_dir / "sanitized-actions.jsonl"
    transcript_path = output_dir / "interaction-summary.jsonl"
    provenance_path = output_dir / "import-provenance.json"
    write_json_atomic(task_snapshot_path, task_snapshot)
    write_json_atomic(run_snapshot_path, run_snapshot)
    _write_jsonl(
        sanitized_actions_path,
        sanitize_clawbench_actions(load_jsonl(actions_path)),
    )
    _write_jsonl(
        transcript_path,
        _interaction_summary(run_dir / "data" / "agent-messages.jsonl"),
    )
    controlled_files: list[dict[str, Any]] = []
    for path in (
        actions_path,
        run_dir / "data" / "agent-messages.jsonl",
        run_dir / "data" / "recording.mp4",
        run_dir / "data" / "interception.json",
        run_dir / "data" / "judge.json",
    ):
        if path.is_file():
            controlled_files.append(
                {
                    "name": path.relative_to(run_dir).as_posix(),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "retention": "controlled-cache-only-not-candidate-or-git",
                }
            )
    write_json_atomic(
        provenance_path,
        {
            "schema_version": "webcloning.clawbench-import-provenance.v1",
            "run_id": run_dir.name,
            "task_id": metadata.get("task_id"),
            "suite": suite,
            "site_id": site_id,
            "dataset_id": dataset_id
            or (
                "NAIL-Group/ClawBenchV1Trace"
                if suite.casefold() == "v1"
                else "TIGER-Lab/ClawBenchV2Trace"
            ),
            "dataset_revision": dataset_revision,
            "task_sha256": sha256_file(task_path),
            "selection_class": result,
            "source_files": controlled_files,
            "raw_content_retained": False,
        },
    )
    trace = normalize_trace(
        raw_path=sanitized_actions_path,
        task_path=task_snapshot_path,
        run_manifest_path=run_snapshot_path,
        artifact_root=artifact_root,
        site_id=site_id,
        environment="source",
        suite=suite,
    )
    require_valid(trace, location="<imported-clawbench-trace>", root=artifact_root)
    return {
        "trace": trace,
        "transcript_path": transcript_path,
        "sanitized_actions_path": sanitized_actions_path,
        "provenance_path": provenance_path,
        "selection_class": result,
    }


def _artifact_paths(
    spec: dict[str, Any], key: str, *, root: Path
) -> list[Path]:
    values = spec.get(key, [])
    if not isinstance(values, list):
        raise WebCloningError(f"{key}: must be an array")
    return [repository_path(root, str(value)) for value in values]


def build_exploration_bundle(
    *, repository_root: Path, spec_path: Path
) -> dict[str, Any]:
    spec = load_json(spec_path)
    strategy = spec.get("strategy")
    if strategy not in {"clawbench-historical", "dfs", "bfs"}:
        raise WebCloningError("strategy must be clawbench-historical, dfs, or bfs")
    trace_paths = _artifact_paths(spec, "traces", root=repository_root)
    if not trace_paths:
        raise WebCloningError("traces: at least one normalized trace is required")
    traces = [load_json(path) for path in trace_paths]
    site_id = spec.get("site_id")
    if any(
        trace.get("schema_version") != "webcloning.normalized-trace.v1"
        or trace.get("site_id") != site_id
        or trace.get("environment") != "source"
        for trace in traces
    ):
        raise WebCloningError("traces must be source traces for the declared site")
    trace_refs = [artifact_ref(path, root=repository_root) for path in trace_paths]
    transcript_paths = _artifact_paths(
        spec, "interaction_transcripts", root=repository_root
    )
    import_paths = _artifact_paths(spec, "imports", root=repository_root)
    media_paths = _artifact_paths(spec, "media", root=repository_root)
    rows: list[dict[str, Any]] = []
    evidence_kind = "historical" if strategy == "clawbench-historical" else "current-direct"
    for trace_ref, trace in zip(trace_refs, traces, strict=True):
        for step in trace["steps"]:
            subject = {
                "trace_sha256": trace_ref["sha256"],
                "step_id": step["step_id"],
                "route": step["after"]["route"],
                "observable_sha256": step["after"]["observable_sha256"],
                "action_family": step["action"]["family"],
                "target": step["action"]["target"],
            }
            observation_kinds = sorted(
                {observation["kind"] for observation in step["observations"]}
            )
            structure_observations = [
                observation
                for observation in step["observations"]
                if any(
                    marker in observation["kind"].casefold()
                    for marker in ("dom", "accessibility", "structure", "browser-target")
                )
            ]
            request_observations = [
                observation
                for observation in step["observations"]
                if any(
                    marker in observation["kind"].casefold()
                    for marker in ("request", "network", "api")
                )
            ]
            rows.append(
                {
                    "row_id": sha256_bytes(canonical_json_bytes(subject)),
                    **subject,
                    "observation_kinds": observation_kinds,
                    "structure_sha256": (
                        sha256_bytes(canonical_json_bytes(structure_observations))
                        if structure_observations
                        else None
                    ),
                    "request_semantics_sha256": (
                        sha256_bytes(canonical_json_bytes(request_observations))
                        if request_observations
                        else None
                    ),
                    "evidence_kind": evidence_kind,
                }
            )
    hypotheses = spec.get("architecture_hypotheses", [])
    if not isinstance(hypotheses, list):
        raise WebCloningError("architecture_hypotheses must be an array")
    normalized_hypotheses: list[dict[str, Any]] = []
    for index, hypothesis in enumerate(hypotheses, start=1):
        if not isinstance(hypothesis, dict):
            raise WebCloningError("architecture hypothesis must be an object")
        normalized_hypotheses.append(
            {
                "id": str(hypothesis.get("id") or f"architecture-{index}"),
                "layer": str(hypothesis.get("layer") or "unknown"),
                "summary": _safe_text(hypothesis.get("summary")),
                "evidence_kind": "inferred",
                "status": str(hypothesis.get("status") or "supported"),
            }
        )
    source_context = spec.get("source_context", {})
    subjects = {
        "site_id": site_id,
        "strategy": strategy,
        "trace_sha256": sorted(ref["sha256"] for ref in trace_refs),
        "transcript_sha256": sorted(
            artifact_ref(path, root=repository_root)["sha256"]
            for path in transcript_paths
        ),
        "import_sha256": sorted(
            artifact_ref(path, root=repository_root)["sha256"]
            for path in import_paths
        ),
        "media_sha256": sorted(
            artifact_ref(path, root=repository_root)["sha256"]
            for path in media_paths
        ),
        "source_context": source_context,
    }
    return seal_document(
        {
            "schema_version": "webcloning.exploration-bundle.v1",
            "bundle_id": sha256_bytes(canonical_json_bytes(subjects)),
            "site_id": site_id,
            "strategy": strategy,
            "source_context": source_context,
            "traces": trace_refs,
            "interaction_transcripts": [
                artifact_ref(path, root=repository_root)
                for path in transcript_paths
            ],
            "imports": [
                artifact_ref(path, root=repository_root) for path in import_paths
            ],
            "media": [
                artifact_ref(path, root=repository_root) for path in media_paths
            ],
            "visit_order": rows,
            "frontier": spec.get("frontier", []),
            "architecture_hypotheses": normalized_hypotheses,
            "status": str(spec.get("status") or "complete"),
            "authority": (
                "exploration-evidence-only-cannot-prove-fidelity-or-release"
            ),
        }
    )


def build_exploration_coverage(
    *, repository_root: Path, spec_path: Path
) -> dict[str, Any]:
    spec = load_json(spec_path)
    bundle_paths = _artifact_paths(spec, "bundles", root=repository_root)
    clone_paths = _artifact_paths(spec, "clone_traces", root=repository_root)
    if not bundle_paths or not clone_paths:
        raise WebCloningError("bundles and clone_traces must both be non-empty")
    bundles = [load_json(path) for path in bundle_paths]
    clones = [load_json(path) for path in clone_paths]
    site_id = spec.get("site_id")
    for bundle in bundles:
        require_valid(bundle, location="<exploration-bundle>", root=repository_root)
        if bundle.get("site_id") != site_id:
            raise WebCloningError("exploration bundle site mismatch")
    for clone in clones:
        require_valid(clone, location="<clone-trace>", root=repository_root)
        if clone.get("site_id") != site_id or clone.get("environment") != "clone":
            raise WebCloningError("clone trace subject mismatch")
    clone_signatures = {
        (
            step["after"]["route"],
            step["action"]["family"],
            step["action"]["target"],
            step["after"]["observable_sha256"],
            (
                sha256_bytes(
                    canonical_json_bytes(
                        [
                            observation
                            for observation in step["observations"]
                            if any(
                                marker in observation["kind"].casefold()
                                for marker in (
                                    "dom",
                                    "accessibility",
                                    "structure",
                                    "browser-target",
                                )
                            )
                        ]
                    )
                )
                if any(
                    any(
                        marker in observation["kind"].casefold()
                        for marker in (
                            "dom",
                            "accessibility",
                            "structure",
                            "browser-target",
                        )
                    )
                    for observation in step["observations"]
                )
                else None
            ),
            (
                sha256_bytes(
                    canonical_json_bytes(
                        [
                            observation
                            for observation in step["observations"]
                            if any(
                                marker in observation["kind"].casefold()
                                for marker in ("request", "network", "api")
                            )
                        ]
                    )
                )
                if any(
                    any(
                        marker in observation["kind"].casefold()
                        for marker in ("request", "network", "api")
                    )
                    for observation in step["observations"]
                )
                else None
            ),
        )
        for clone in clones
        for step in clone["steps"]
    }
    source_groups: dict[tuple[Any, ...], set[str]] = {}
    all_rows = [row for bundle in bundles for row in bundle["visit_order"]]
    for row in all_rows:
        key = (row["route"], row["action_family"], row["target"])
        source_groups.setdefault(key, set()).add(row["observable_sha256"])
    rows: list[dict[str, Any]] = []
    for row in all_rows:
        key = (row["route"], row["action_family"], row["target"])
        signature = (
            *key,
            row["observable_sha256"],
            row["structure_sha256"],
            row["request_semantics_sha256"],
        )
        if row["route"] is None:
            disposition = "unavailable"
        elif len(source_groups[key]) > 1:
            disposition = "conflicting"
        elif signature in clone_signatures:
            disposition = "matched"
        else:
            disposition = "missing"
        rows.append({**row, "disposition": disposition})
    counts = {
        disposition: sum(row["disposition"] == disposition for row in rows)
        for disposition in ("matched", "missing", "conflicting", "unavailable")
    }
    hypotheses = [
        hypothesis
        for bundle in bundles
        for hypothesis in bundle["architecture_hypotheses"]
    ]
    architecture = {
        "inferred": len(hypotheses),
        "conflicting": sum(
            hypothesis["status"] == "conflicting" for hypothesis in hypotheses
        ),
        "unavailable": sum(
            hypothesis["status"] == "unavailable" for hypothesis in hypotheses
        ),
    }
    subjects = {
        "site_id": site_id,
        "bundle_sha256": sorted(
            artifact_ref(path, root=repository_root)["sha256"]
            for path in bundle_paths
        ),
        "clone_trace_sha256": sorted(
            artifact_ref(path, root=repository_root)["sha256"]
            for path in clone_paths
        ),
    }
    return seal_document(
        {
            "schema_version": "webcloning.exploration-coverage.v1",
            "coverage_id": sha256_bytes(canonical_json_bytes(subjects)),
            "site_id": site_id,
            "bundles": [
                artifact_ref(path, root=repository_root) for path in bundle_paths
            ],
            "clone_traces": [
                artifact_ref(path, root=repository_root) for path in clone_paths
            ],
            "rows": rows,
            "counts": counts,
            "architecture": architecture,
            "status": (
                "complete"
                if counts["missing"] == counts["conflicting"] == 0
                and counts["matched"] > 0
                else "incomplete"
            ),
            "authority": (
                "mechanical-exploration-coverage-only-cannot-accept-fidelity-or-release"
            ),
        }
    )
