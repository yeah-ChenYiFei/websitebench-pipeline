"""Normalize raw Agent/browser action JSONL into a replay-safe trace."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .contracts import (
    WebCloningError,
    artifact_ref,
    canonical_json_bytes,
    load_json,
    load_jsonl,
    seal_document,
    sha256_bytes,
)

GENERATOR = "clawbench.webcloning.trace-normalizer.v1"
SENSITIVE = re.compile(
    r"(?i)(authorization|cookie|password|passwd|secret|access[_-]?token|"
    r"refresh[_-]?token|api[_-]?key|credit[_-]?card|cvv|otp)"
)
ACTION_FAMILIES = {
    "navigate": "navigation",
    "pageload": "navigation",
    "goto": "navigation",
    "open": "navigation",
    "search": "query",
    "query": "query",
    "click": "click",
    "tap": "click",
    "type": "type",
    "fill": "type",
    "input": "type",
    "change": "type",
    "select": "select",
    "submit": "submit",
    "upload": "upload",
    "scroll": "scroll",
    "wheel": "scroll",
    "keydown": "keyboard",
    "keyup": "keyboard",
    "keypress": "keyboard",
    "wait": "wait",
    "refresh": "refresh",
    "reload": "refresh",
    "back": "back-forward",
    "forward": "back-forward",
    "request": "api-visible-mutation",
    "api": "api-visible-mutation",
    "mutation": "api-visible-mutation",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]" if SENSITIVE.search(str(key)) else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(
            r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", value
        )
        value = re.sub(
            r"(?i)((?:password|token|secret|otp)\s*[:=]\s*)\S+",
            r"\1[REDACTED]",
            value,
        )
        return value[:2000]
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    redacted = _redact(value)
    if isinstance(redacted, str):
        return redacted
    return str(redacted)[:2000]


def _action_name(record: dict[str, Any]) -> str:
    action = record.get("action")
    if isinstance(action, dict):
        action = action.get("name") or action.get("type") or action.get("method")
    value = action or record.get("type") or record.get("name") or record.get("method")
    return str(value or "unknown")


def _action_family(name: str) -> str:
    lowered = name.lower()
    for marker, family in ACTION_FAMILIES.items():
        if marker in lowered:
            return family
    return "other"


def _state(record: dict[str, Any], prefix: str) -> dict[str, Any]:
    raw = record.get(prefix)
    if not isinstance(raw, dict):
        raw = {}
    route = raw.get("route") or raw.get("url") or record.get(f"{prefix}_url")
    title = raw.get("title") or record.get(f"{prefix}_title")
    markers = raw.get("markers") or raw.get("visible") or []
    if not isinstance(markers, list):
        markers = [markers]
    safe_markers = [_text(item) for item in markers if item is not None][:64]
    observable = {
        "route": _text(route),
        "title": _text(title),
        "markers": safe_markers,
    }
    return {
        **observable,
        "observable_sha256": sha256_bytes(
            str(sorted(observable.items())).encode("utf-8")
        ),
    }


def _observations(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("observations", record.get("observation"))
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    result: list[dict[str, Any]] = []
    for item in raw[:64]:
        if isinstance(item, dict):
            kind = str(item.get("kind") or item.get("type") or "browser")
            summary = _text(item.get("summary") or item.get("message") or item)
            status_code = item.get("status_code")
        else:
            kind = "browser"
            summary = _text(item)
            status_code = None
        observation: dict[str, Any] = {"kind": kind[:80], "summary": summary or ""}
        if isinstance(status_code, int):
            observation["status_code"] = status_code
        result.append(observation)
    return result


def normalize_trace(
    *,
    raw_path: Path,
    task_path: Path,
    run_manifest_path: Path,
    artifact_root: Path,
    site_id: str,
    environment: str,
    suite: str,
) -> dict[str, Any]:
    records = load_jsonl(raw_path)
    task = load_json(task_path)
    run = load_json(run_manifest_path)
    metadata = task.get("metadata", {})
    required_run = ("agent", "model", "provider", "config_sha256", "seed", "run_id")
    missing = [key for key in required_run if key not in run]
    if missing:
        raise WebCloningError(
            f"{run_manifest_path}: missing run identity fields {missing!r}"
        )
    steps: list[dict[str, Any]] = []
    total_tokens = 0
    for index, record in enumerate(records, start=1):
        name = _action_name(record)
        tokens = record.get("tokens", 0)
        tokens = tokens if isinstance(tokens, int) and tokens >= 0 else 0
        total_tokens += tokens
        error = record.get("error")
        effects = record.get("external_effects", [])
        if not isinstance(effects, list):
            effects = [effects]
        steps.append(
            {
                "step_id": f"s{index:04d}",
                "index": index,
                "actor": str(record.get("actor") or run["agent"])[:200],
                "action": {
                    "family": _action_family(name),
                    "name": name[:200],
                    "target": _text(
                        record.get("target")
                        or record.get("selector")
                        or record.get("url")
                    ),
                },
                "before": _state(record, "before"),
                "after": _state(record, "after"),
                "observations": _observations(record),
                "external_effects": [
                    _text(item) or "" for item in _redact(effects)[:64]
                ],
                "error": _text(error),
                "outcome": str(record.get("outcome") or ("error" if error else "ok"))[
                    :80
                ],
                "tokens": tokens,
                # Hash the already-redacted representation. Hashing a raw password,
                # OTP, or other low-entropy secret would itself retain unsafe data.
                "raw_record_sha256": sha256_bytes(
                    (
                        __import__("json").dumps(
                            _redact(record),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode()
                ),
            }
        )
    unknown = sum(step["action"]["family"] == "other" for step in steps)
    errors = sum(step["error"] is not None for step in steps)
    status = "complete" if unknown == 0 else "incomplete"
    task_ref = artifact_ref(task_path, root=artifact_root)
    raw_ref = artifact_ref(raw_path, root=artifact_root)
    run_identity = {key: run[key] for key in required_run}
    trace_id = sha256_bytes(
        canonical_json_bytes(
            {
                "site_id": site_id,
                "environment": environment,
                "generator": GENERATOR,
                "task_sha256": task_ref["sha256"],
                "raw_trace_sha256": raw_ref["sha256"],
                "run": run_identity,
            }
        )
    )
    return seal_document(
        {
            "schema_version": "webcloning.normalized-trace.v1",
            "trace_id": trace_id,
            "site_id": site_id,
            "environment": environment,
            "generator": GENERATOR,
            "task": {
                **task_ref,
                "suite": suite,
                "task_id": metadata.get("task_id"),
                "instruction_sha256": sha256_bytes(
                    str(task.get("instruction", "")).encode()
                ),
            },
            "run": run_identity,
            "raw_trace": {
                **raw_ref,
                "bytes": raw_path.stat().st_size,
                "access_level": run.get("raw_trace_access", "controlled"),
            },
            "redaction": {
                "status": "applied",
                "ruleset": "webcloning-secrets-and-personal-data.v1",
            },
            "steps": steps,
            "summary": {
                "step_count": len(steps),
                "token_count": total_tokens,
                "unknown_action_count": unknown,
                "error_step_count": errors,
                "task_result": str(run.get("task_result", "unknown"))[:80],
            },
            "status": status,
            "authority": (
                "normalized-behavior-evidence-only-cannot-prove-clone-validity-or-release"
            ),
        }
    )
