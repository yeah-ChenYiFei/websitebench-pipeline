"""Strict JSON contracts and cross-artifact validation for WebCloning traces."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
SCHEMA_FILES = {
    "webcloning.normalized-trace.v1": "webcloning-normalized-trace.schema.json",
    "webcloning.replay.v1": "webcloning-replay.schema.json",
    "webcloning.behavior-diff.v1": "webcloning-behavior-diff.schema.json",
    "webcloning.exploration-bundle.v1": "webcloning-exploration-bundle.schema.json",
    "webcloning.exploration-coverage.v1": "webcloning-exploration-coverage.schema.json",
}
# Explicit historical parser only. This record never satisfies an active
# workflow or technical-verification stage.
LEGACY_ACCEPTANCE_SCHEMA = "offline-clone-human-fidelity-acceptance.schema.json"
DIFF_CATEGORIES = (
    "visual-fidelity",
    "missing-element",
    "operation-semantics",
    "state-transition",
    "data-content",
    "error-behavior",
    "clone-only-shortcut",
    "trace-only-difference",
    "critical-impact",
)


class WebCloningError(ValueError):
    """Raised when an analysis artifact is malformed, stale, or unsafe."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Retained only for the frozen clawbench compatibility copies, which still
# stamp content_sha256 into their documents. Canonical producers no longer
# seal documents and validators no longer check the field; git history is the
# integrity ledger.
def content_sha256(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("content_sha256", None)
    return sha256_bytes(canonical_json_bytes(payload))


def seal_document(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["content_sha256"] = content_sha256(result)
    return result


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WebCloningError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    size = resolved.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        raise WebCloningError(
            f"{resolved}: document exceeds {MAX_DOCUMENT_BYTES} bytes"
        )
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise WebCloningError(f"{resolved}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise WebCloningError(f"{resolved}: top-level JSON value must be an object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise WebCloningError(f"{path}: JSONL document exceeds size limit")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line, object_pairs_hook=_reject_duplicate_pairs)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise WebCloningError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise WebCloningError(f"{path}:{line_number}: record must be an object")
        records.append(value)
    if not records:
        raise WebCloningError(f"{path}: no JSONL records")
    return records


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def schema_path(filename: str) -> Path:
    repository = Path(__file__).resolve().parents[3] / "websitebench" / "schemas"
    source = repository / filename
    if source.is_file():
        return source
    bundled = Path(__file__).resolve().parents[1] / "viewer" / "_schemas" / filename
    if bundled.is_file():
        return bundled
    raise WebCloningError(f"schema is unavailable: {filename}")


@lru_cache(maxsize=None)
def load_schema(filename: str) -> dict[str, Any]:
    value = json.loads(schema_path(filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def schema_problems(value: dict[str, Any], *, location: str) -> list[str]:
    version = value.get("schema_version")
    filename = SCHEMA_FILES.get(version)
    if filename is None:
        return [f"{location}: unsupported schema_version {version!r}"]
    validator = Draft202012Validator(
        load_schema(filename), format_checker=FormatChecker()
    )
    problems: list[str] = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
        suffix = ".".join(str(part) for part in error.absolute_path)
        where = f"{location}:{suffix}" if suffix else location
        problems.append(f"{where}: {error.message}")
    return problems


def repository_path(root: Path, logical_path: str) -> Path:
    root = root.resolve()
    candidate = (root / logical_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WebCloningError(f"path escapes declared root: {logical_path}") from exc
    return candidate


def artifact_ref(path: Path, *, root: Path) -> dict[str, str]:
    resolved = path.resolve()
    try:
        logical = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise WebCloningError(f"{resolved}: artifact is outside {root.resolve()}") from exc
    return {"path": logical, "sha256": sha256_file(resolved)}


def _verify_ref(root: Path, ref: dict[str, Any], label: str) -> list[str]:
    try:
        path = repository_path(root, ref["path"])
    except (KeyError, TypeError, WebCloningError) as exc:
        return [f"{label}: {exc}"]
    if not path.is_file():
        return [f"{label}: missing artifact {ref['path']}"]
    return []


def legacy_acceptance_record_problems(
    value: dict[str, Any],
    *,
    site_id: str,
) -> list[str]:
    """Validate an explicitly requested historical v1 acceptance record."""

    validator = Draft202012Validator(
        load_schema(LEGACY_ACCEPTANCE_SCHEMA),
        format_checker=FormatChecker(),
    )
    problems = [
        f"human acceptance {'.'.join(str(part) for part in error.absolute_path)}: "
        f"{error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    ]
    if problems:
        return problems
    if value["site_id"] != site_id:
        problems.append("human acceptance site_id does not match")
    if value["release_profile"] != "websitebench-300-public-v1":
        problems.append("human acceptance release_profile does not match")
    if value["disposition"] != "accepted":
        problems.append("human acceptance disposition is not accepted")
    if value["open_p0"] or value["open_p1"]:
        problems.append("human acceptance has open P0/P1 findings")
    coverage = value["coverage"]
    if coverage["p0_journeys_inspected"] != coverage["p0_journeys_total"]:
        problems.append("human acceptance does not cover every P0 journey")
    return problems


def _duplicates(values: Iterable[Any]) -> set[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _validate_trace(value: dict[str, Any], *, root: Path | None) -> list[str]:
    problems: list[str] = []
    steps = value["steps"]
    if [step["index"] for step in steps] != list(range(1, len(steps) + 1)):
        problems.append("steps: indices must be contiguous and one-based")
    duplicate = _duplicates(step["step_id"] for step in steps)
    if duplicate:
        problems.append(f"steps: duplicate step_id: {sorted(duplicate)!r}")
    summary = value["summary"]
    actual_unknown = sum(step["action"]["family"] == "other" for step in steps)
    actual_errors = sum(step["error"] is not None for step in steps)
    if summary["step_count"] != len(steps):
        problems.append("summary.step_count: does not match steps")
    if summary["unknown_action_count"] != actual_unknown:
        problems.append("summary.unknown_action_count: does not match steps")
    if summary["error_step_count"] != actual_errors:
        problems.append("summary.error_step_count: does not match steps")
    if value["status"] == "complete" and actual_unknown:
        problems.append("status: complete trace cannot contain unknown action families")
    if root is not None:
        problems.extend(_verify_ref(root, value["task"], "task"))
        problems.extend(_verify_ref(root, value["raw_trace"], "raw_trace"))
        raw_path = repository_path(root, value["raw_trace"]["path"])
        if (
            raw_path.is_file()
            and value["raw_trace"]["bytes"] != raw_path.stat().st_size
        ):
            problems.append("raw_trace.bytes: does not match artifact size")
        task_path = repository_path(root, value["task"]["path"])
        if task_path.is_file():
            task = load_json(task_path)
            if task.get("metadata", {}).get("task_id") != value["task"]["task_id"]:
                problems.append("task.task_id: does not match task artifact")
    return problems


def _validate_exploration_bundle(
    value: dict[str, Any], *, root: Path | None
) -> list[str]:
    problems: list[str] = []
    rows = value["visit_order"]
    duplicate = _duplicates(row["row_id"] for row in rows)
    if duplicate:
        problems.append(f"visit_order: duplicate row_id: {sorted(duplicate)!r}")
    if any(
        hypothesis["evidence_kind"] != "inferred"
        for hypothesis in value["architecture_hypotheses"]
    ):
        problems.append("architecture_hypotheses: private architecture must stay inferred")
    if root is not None:
        for field in ("traces", "interaction_transcripts", "imports", "media"):
            for index, ref in enumerate(value[field]):
                problems.extend(_verify_ref(root, ref, f"{field}[{index}]"))
        for index, ref in enumerate(value["traces"]):
            path = repository_path(root, ref["path"])
            if path.is_file():
                trace = load_json(path)
                nested = validate_document(trace, location=str(path), root=root)
                problems.extend(nested)
                if (
                    trace.get("schema_version")
                    != "webcloning.normalized-trace.v1"
                    or trace.get("site_id") != value["site_id"]
                    or trace.get("environment") != "source"
                ):
                    problems.append(f"traces[{index}]: source trace subject mismatch")
    return problems


def _validate_exploration_coverage(
    value: dict[str, Any], *, root: Path | None
) -> list[str]:
    problems: list[str] = []
    rows = value["rows"]
    actual = {
        disposition: sum(row["disposition"] == disposition for row in rows)
        for disposition in ("matched", "missing", "conflicting", "unavailable")
    }
    if value["counts"] != actual:
        problems.append("counts: exploration row dispositions do not reconcile")
    if value["status"] == "complete" and (
        actual["missing"] or actual["conflicting"] or not actual["matched"]
    ):
        problems.append("status: complete coverage requires matched rows and no gaps")
    if root is not None:
        for field in ("bundles", "clone_traces"):
            for index, ref in enumerate(value[field]):
                problems.extend(_verify_ref(root, ref, f"{field}[{index}]"))
                path = repository_path(root, ref["path"])
                if path.is_file():
                    nested = load_json(path)
                    problems.extend(
                        validate_document(nested, location=str(path), root=root)
                    )
                    expected_version = (
                        "webcloning.exploration-bundle.v1"
                        if field == "bundles"
                        else "webcloning.normalized-trace.v1"
                    )
                    if (
                        nested.get("schema_version") != expected_version
                        or nested.get("site_id") != value["site_id"]
                    ):
                        problems.append(f"{field}[{index}]: subject mismatch")
                    if (
                        field == "clone_traces"
                        and nested.get("environment") != "clone"
                    ):
                        problems.append(f"{field}[{index}]: clone environment required")
    return problems


def _validate_replay(value: dict[str, Any], *, root: Path | None) -> list[str]:
    problems: list[str] = []
    steps = value["steps"]
    classes = {"exact": 0, "equivalent": 0, "missing": 0}
    for step in steps:
        classes[step["mapping"]] += 1
        if step["mapping"] == "equivalent" and not step.get("equivalence"):
            problems.append(
                f"{step['source_step_id']}: equivalent mapping lacks approval record"
            )
        if step["mapping"] != "equivalent" and step.get("equivalence") is not None:
            problems.append(
                f"{step['source_step_id']}: equivalence is only legal for equivalent mapping"
            )
    coverage = value["coverage"]
    if coverage["source_step_count"] != len(steps):
        problems.append("coverage.source_step_count: does not match replay steps")
    for key in ("exact", "equivalent", "missing"):
        if coverage[f"{key}_step_count"] != classes[key]:
            problems.append(f"coverage.{key}_step_count: does not match replay steps")
    denominator = len(steps) or 1
    expected = {
        "exact_coverage": classes["exact"] / denominator,
        "equivalent_coverage": classes["equivalent"] / denominator,
        "total_coverage": (classes["exact"] + classes["equivalent"]) / denominator,
    }
    for key, actual in expected.items():
        if abs(coverage[key] - actual) > 1e-9:
            problems.append(f"coverage.{key}: declared value does not reconcile")
    if value["status"] == "complete" and (
        classes["missing"]
        or coverage["total_coverage"] != 1
        or value["reset"]["status"] != "passed"
    ):
        problems.append("status: complete replay requires reset and full mapped coverage")
    if root is not None:
        for field in (
            "source_trace",
            "clone_trace",
            "candidate",
            "semantic_selection",
            "runtime_identity",
            "reset",
        ):
            problems.extend(_verify_ref(root, value[field], field))
        if value["equivalence_manifest"] is not None:
            problems.extend(
                _verify_ref(root, value["equivalence_manifest"], "equivalence_manifest")
            )
        for step in steps:
            if step["equivalence"] is not None:
                problems.extend(
                    _verify_ref(
                        root,
                        step["equivalence"]["approval"],
                        f"{step['source_step_id']}.equivalence.approval",
                    )
                )
        for field, environment in (("source_trace", "source"), ("clone_trace", "clone")):
            path = repository_path(root, value[field]["path"])
            if path.is_file():
                trace = load_json(path)
                nested = validate_document(trace, location=str(path), root=root)
                problems.extend(nested)
                if (
                    trace.get("schema_version")
                    != "webcloning.normalized-trace.v1"
                    or trace.get("site_id") != value["site_id"]
                    or trace.get("environment") != environment
                ):
                    problems.append(f"{field}: trace subject mismatch")
        candidate_path = repository_path(root, value["candidate"]["path"])
        semantic_path = repository_path(root, value["semantic_selection"]["path"])
        if candidate_path.is_file():
            candidate = load_json(candidate_path)
            if (
                candidate.get("schema_version")
                not in {
                    "offline-clone.fullstack-candidate.v3",
                }
                or candidate.get("site_id") != value["site_id"]
                or candidate.get("status") != "complete"
            ):
                problems.append("candidate: complete exact-site candidate is required")
        if semantic_path.is_file():
            semantic = load_json(semantic_path)
            if (
                semantic.get("schema_version")
                not in {
                    "offline-clone.semantic-selection.v3",
                }
                or semantic.get("site_id") != value["site_id"]
                or semantic.get("selection_policy")
                != "fidelity-first-automatic-v1"
            ):
                problems.append(
                    "semantic_selection: current semantic selection is required"
                )
    return problems


def _validate_diff(value: dict[str, Any], *, root: Path | None) -> list[str]:
    problems: list[str] = []
    findings = value["findings"]
    counts = value["counts"]
    actual_category = {category: 0 for category in DIFF_CATEGORIES}
    actual_severity = {"P0": 0, "P1": 0, "P2": 0}
    actual_status = {"open": 0, "closed": 0}
    for finding in findings:
        actual_category[finding["category"]] += 1
        actual_severity[finding["severity"]] += 1
        actual_status[finding["status"]] += 1
        if finding["status"] == "closed" and finding.get("regression") is None:
            problems.append(
                f"{finding['finding_id']}: closed finding requires regression/probe evidence"
            )
    if counts["total"] != len(findings):
        problems.append("counts.total: does not match findings")
    if counts["by_category"] != actual_category:
        problems.append("counts.by_category: does not match findings")
    if counts["by_severity"] != actual_severity:
        problems.append("counts.by_severity: does not match findings")
    if counts["by_status"] != actual_status:
        problems.append("counts.by_status: does not match findings")
    if root is not None:
        problems.extend(_verify_ref(root, value["replay"], "replay"))
        replay_path = repository_path(root, value["replay"]["path"])
        if replay_path.is_file():
            replay = load_json(replay_path)
            problems.extend(
                validate_document(replay, location=str(replay_path), root=root)
            )
            if (
                replay.get("schema_version") != "webcloning.replay.v1"
                or replay.get("site_id") != value["site_id"]
            ):
                problems.append("replay: subject mismatch")
            if replay.get("analysis_id") != value["analysis_id"]:
                problems.append("analysis_id: does not match replay")
        if value["supplemental_findings"] is not None:
            problems.extend(
                _verify_ref(
                    root,
                    value["supplemental_findings"],
                    "supplemental_findings",
                )
            )
        for finding in findings:
            if finding["regression"] is not None:
                problems.extend(
                    _verify_ref(
                        root,
                        finding["regression"],
                        f"{finding['finding_id']}.regression",
                    )
                )
    return problems


def validate_document(
    value: dict[str, Any],
    *,
    location: str = "<document>",
    root: Path | None = None,
) -> list[str]:
    problems = schema_problems(value, location=location)
    if problems:
        return problems
    version = value["schema_version"]
    if version == "webcloning.normalized-trace.v1":
        problems.extend(_validate_trace(value, root=root))
    elif version == "webcloning.replay.v1":
        problems.extend(_validate_replay(value, root=root))
    elif version == "webcloning.behavior-diff.v1":
        problems.extend(_validate_diff(value, root=root))
    elif version == "webcloning.exploration-bundle.v1":
        problems.extend(_validate_exploration_bundle(value, root=root))
    elif version == "webcloning.exploration-coverage.v1":
        problems.extend(_validate_exploration_coverage(value, root=root))
    return problems


def require_valid(
    value: dict[str, Any],
    *,
    location: str,
    root: Path | None = None,
) -> None:
    problems = validate_document(
        value,
        location=location,
        root=root,
    )
    if problems:
        raise WebCloningError("\n".join(problems))
