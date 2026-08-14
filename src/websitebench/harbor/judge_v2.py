"""Deterministic scoring and black-box helpers for Harbor v2.

This module is intentionally free of model SDKs and natural-language verdicts.
Every public verdict is derived from an explicit comparator, RGB SSIM value, or
trusted check exit status.
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:  # pragma: no cover - unavailable on Windows authoring hosts
    import pwd
    import resource
except ImportError:  # pragma: no cover
    pwd = None  # type: ignore[assignment]
    resource = None  # type: ignore[assignment]


TASK_RESULTS_SCHEMA = "websitebench.harbor.task-results.v1"
VISUAL_RESULTS_SCHEMA = "websitebench.harbor.visual-results.v1"
CICD_RESULTS_SCHEMA = "websitebench.harbor.cicd-results.v1"
SCORE_SCHEMA = "websitebench.harbor.score.v2"
VERDICT_SCHEMA = "websitebench.harbor.verdict.v2"
MAX_CANDIDATE_AUDIT_BYTES = 256 * 1024 * 1024
DETERMINISTIC_CHROMIUM_ARGS = ("--disable-partial-raster",)

RESULT_STATUSES = {"passed", "failed", "skipped", "flaky"}
COMPARATORS = {
    "exact",
    "normalized_exact",
    "regex",
    "ordered_list",
    "set",
    "number",
    "sha256",
}

PLATFORM_CICD_CHECKS = (
    "platform::artifact/complete",
    "platform::artifact/deploy-path-safe",
    "platform::deploy/offline-clean",
    "platform::deploy/healthz",
    "platform::deploy/foreground-lifecycle",
    "platform::deploy/graceful-sigterm",
    "platform::deploy/restart-persistence",
    "platform::deploy/concurrent-isolation",
    "platform::artifact/code-tree-unchanged",
    "platform::network/external-closed",
    "platform::security/secret-reference-verifier-scan",
    "platform::browser/chromium-smoke",
    "platform::accessibility/basic",
    "platform::performance/startup-budget",
    "platform::performance/resource-budget",
)

class InvalidRun(ValueError):
    """The verifier inputs or execution are invalid, so no reward may exist."""


def launch_deterministic_chromium(playwright: Any) -> Any:
    """Launch the fixed full-raster Chromium profile used by capture and score."""

    return playwright.chromium.launch(
        headless=True,
        args=list(DETERMINISTIC_CHROMIUM_ARGS),
    )


_ISOLATION_UID_LOCK = threading.Lock()
_ALLOCATED_ISOLATION_UIDS: set[int] = set()


def opaque_isolation_uid() -> int:
    """Allocate a phase-independent random UID without reuse in this run."""

    with _ISOLATION_UID_LOCK:
        while True:
            value = 20000 + secrets.randbelow(45535)
            if value not in _ALLOCATED_ISOLATION_UIDS:
                _ALLOCATED_ISOLATION_UIDS.add(value)
                return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def urlopen_no_redirect(request: Any, *, timeout: float) -> Any:
    """Open one HTTP request without following a scope-changing redirect."""

    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def font_manifest_text() -> str:
    """Return path-independent font bytes plus fixed generic-family resolution."""

    try:
        completed = subprocess.run(
            ["fc-list", "--format", "%{file}\n"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InvalidRun("fixed font profile is unavailable") from exc
    entries: set[str] = set()
    for raw in completed.stdout.splitlines():
        path = Path(raw)
        try:
            if path.is_file():
                entries.add(f"FILE\t{path.name}\t{path.stat().st_size}")
        except OSError:
            continue
    if not entries:
        raise InvalidRun("fixed font profile contains no readable fonts")
    for family in ("sans-serif", "serif", "monospace", "system-ui", "emoji"):
        try:
            matched = subprocess.run(
                [
                    "fc-match",
                    "--format",
                    "%{family}\t%{style}\t%{file}\n",
                    family,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            ).stdout.strip()
            resolved_family, style, raw_path = matched.split("\t", 2)
            path = Path(raw_path)
            if not path.is_file():
                raise OSError("fontconfig selected an unreadable file")
            entries.add(
                f"MATCH\t{family}\t{resolved_family}\t{style}\t{path.name}\t"
                f"{path.stat().st_size}"
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise InvalidRun("fixed fontconfig profile is unavailable") from exc
    return "".join(line + "\n" for line in sorted(entries))


def render_environment_fingerprint(
    browser_settings: Mapping[str, Any], browser_version: str
) -> dict[str, Any]:
    return {
        "schema_version": "websitebench.harbor.render-environment.v1",
        "engine": "chromium",
        "playwright_version": importlib.metadata.version("playwright"),
        "chromium_version": browser_version,
        "font_profile": browser_settings["font_profile"],
    }


def normalize_text(value: str) -> str:
    """Apply the only v2 text normalization: NFC plus collapsed whitespace."""

    return " ".join(unicodedata.normalize("NFC", value).split())


def normalize_url(value: str) -> str:
    """Canonicalize an observed absolute or route-only URL deterministically."""

    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme and not parsed.netloc:
        path = parsed.path or "/"
        query = f"?{parsed.query}" if parsed.query else ""
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        return path + query + fragment
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    rendered_host = f"[{host}]" if ":" in host else host
    authority = rendered_host if port is None or default else f"{rendered_host}:{port}"
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{scheme}://{authority}{path}{query}{fragment}"


def normalize_observed_url(value: str, base_url: str) -> str:
    """Normalize a browser URL and remove only the configured target origin."""

    observed = urllib.parse.urlsplit(normalize_url(value))
    base = urllib.parse.urlsplit(normalize_url(base_url))
    if (observed.scheme, observed.netloc) == (base.scheme, base.netloc):
        return (
            (observed.path or "/")
            + (f"?{observed.query}" if observed.query else "")
            + (f"#{observed.fragment}" if observed.fragment else "")
        )
    return urllib.parse.urlunsplit(observed)


def _canonical_set_member(value: Any) -> str:
    try:
        return canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"set member is not canonical JSON: {exc}") from exc


def accessibility_role_name(locator: Any) -> tuple[str, str]:
    """Return Chromium's computed accessibility role and accessible name."""

    snapshot = locator.aria_snapshot()
    first = next((line.strip() for line in snapshot.splitlines() if line.strip()), "")
    match = re.fullmatch(
        r'-\s+([a-z][a-z0-9-]*)(?:\s+("(?:\\.|[^"\\])*"))?(?:\s+.*|:.*)?',
        first,
    )
    if match is None:
        raise ValueError("selected element has no parseable accessibility node")
    quoted_name = match.group(2)
    name = json.loads(quoted_name) if quoted_name is not None else ""
    if not isinstance(name, str):
        raise ValueError("computed accessible name is not text")
    return match.group(1), name


def compare_values(
    actual: Any, expected: Any, comparator: Mapping[str, Any]
) -> dict[str, Any]:
    """Run one declared comparator and return an auditable boolean verdict."""

    kind = comparator.get("type")
    if kind not in COMPARATORS:
        raise ValueError(f"unsupported comparator: {kind!r}")

    if kind == "exact":
        passed = type(actual) is type(expected) and actual == expected
    elif kind == "normalized_exact":
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise ValueError("normalized_exact requires string values")
        passed = normalize_text(actual) == normalize_text(expected)
    elif kind == "regex":
        if not isinstance(actual, str):
            raise ValueError("regex requires a string observation")
        pattern = comparator.get("pattern")
        if not isinstance(pattern, str):
            raise ValueError("regex requires a string pattern")
        passed = re.fullmatch(pattern, actual) is not None
    elif kind == "ordered_list":
        if not isinstance(actual, list) or not isinstance(expected, list):
            raise ValueError("ordered_list requires list values")
        passed = actual == expected
    elif kind == "set":
        if not isinstance(actual, list) or not isinstance(expected, list):
            raise ValueError("set requires JSON array values")
        actual_members = [_canonical_set_member(item) for item in actual]
        expected_members = [_canonical_set_member(item) for item in expected]
        if len(actual_members) != len(set(actual_members)):
            raise ValueError("actual set observation contains duplicates")
        if len(expected_members) != len(set(expected_members)):
            raise ValueError("frozen set expectation contains duplicates")
        passed = set(actual_members) == set(expected_members)
    elif kind == "number":
        if (
            not isinstance(actual, (int, float))
            or isinstance(actual, bool)
            or not isinstance(expected, (int, float))
            or isinstance(expected, bool)
            or not math.isfinite(float(actual))
            or not math.isfinite(float(expected))
        ):
            raise ValueError("number comparator requires finite numbers")
        absolute = comparator.get("absolute_tolerance", 0.0)
        relative = comparator.get("relative_tolerance", 0.0)
        if (
            not isinstance(absolute, (int, float))
            or isinstance(absolute, bool)
            or not isinstance(relative, (int, float))
            or isinstance(relative, bool)
            or absolute < 0
            or relative < 0
        ):
            raise ValueError("numeric tolerances must be non-negative numbers")
        passed = math.isclose(
            float(actual),
            float(expected),
            rel_tol=float(relative),
            abs_tol=float(absolute),
        )
    else:  # sha256
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise ValueError("sha256 comparator requires string digests")
        valid = re.fullmatch(r"[0-9a-f]{64}", actual) and re.fullmatch(
            r"[0-9a-f]{64}", expected
        )
        if not valid:
            raise ValueError("sha256 values must be lowercase hexadecimal digests")
        passed = actual == expected

    return {
        "comparator": kind,
        "passed": bool(passed),
    }


def json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or start with '/'")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit():
                raise KeyError(pointer)
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def evaluate_observations(
    actual: Mapping[str, Any],
    declarations: Sequence[Mapping[str, Any]],
    frozen: Mapping[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    """Compare one task's canonical observations with its frozen reference."""

    declared_ids = [item.get("id") for item in declarations]
    if len(declared_ids) != len(set(declared_ids)) or not all(
        isinstance(item, str) and item for item in declared_ids
    ):
        raise ValueError("observation ids must be unique non-empty strings")
    if set(actual) != set(declared_ids):
        raise ValueError("candidate observation set differs from declarations")
    if set(frozen) != set(declared_ids):
        raise ValueError("frozen observation set differs from declarations")
    results: list[dict[str, Any]] = []
    for declaration in declarations:
        observation_id = str(declaration["id"])
        verdict = compare_values(
            actual[observation_id],
            frozen[observation_id],
            declaration["comparator"],
        )
        results.append({"id": observation_id, **verdict})
    return all(item["passed"] for item in results), results


def _validate_unique_ids(items: Sequence[Mapping[str, Any]], label: str) -> list[str]:
    ids = [item.get("id") for item in items]
    if not ids or not all(isinstance(item, str) and item for item in ids):
        raise InvalidRun(f"{label} contains an empty or invalid id")
    if len(ids) != len(set(ids)):
        raise InvalidRun(f"{label} contains duplicate ids")
    return [str(item) for item in ids]


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidRun(f"{label} is unreadable: {type(exc).__name__}:{exc}") from exc
    if not isinstance(value, dict):
        raise InvalidRun(f"{label} must contain a JSON object")
    return value


def _validate_result_set(
    suite_path: Path,
    result_path: Path,
    *,
    suite_schema: str,
    result_schema: str,
    suite_key: str,
    result_key: str,
    result_id_key: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    suite = _load_json_object(suite_path, f"{suite_key} suite")
    result = _load_json_object(result_path, f"{result_key} results")
    if suite.get("schema_version") != suite_schema:
        raise InvalidRun(f"unexpected {suite_key} suite schema")
    if result.get("schema_version") != result_schema:
        raise InvalidRun(f"unexpected {result_key} result schema")
    suite_items = suite.get(suite_key)
    result_items = result.get(result_key)
    if not isinstance(suite_items, list) or not isinstance(result_items, list):
        raise InvalidRun(f"{suite_key}/{result_key} must be arrays")
    expected_ids = _validate_unique_ids(suite_items, f"{suite_key} suite")
    observed_ids: list[str] = []
    for item in result_items:
        if not isinstance(item, dict):
            raise InvalidRun(f"{result_key} entry must be an object")
        identifier = item.get(result_id_key)
        status = item.get("status")
        if not isinstance(identifier, str) or not identifier:
            raise InvalidRun(f"{result_key} entry has invalid id")
        if status not in RESULT_STATUSES:
            raise InvalidRun(f"{result_key} entry has invalid status: {identifier}")
        observed_ids.append(identifier)
    if len(observed_ids) != len(set(observed_ids)):
        raise InvalidRun(f"{result_key} contains duplicate ids")
    if set(expected_ids) != set(observed_ids):
        raise InvalidRun(
            f"{result_key} exact set mismatch: "
            f"missing={sorted(set(expected_ids) - set(observed_ids))}:"
            f"extra={sorted(set(observed_ids) - set(expected_ids))}"
        )
    order = {identifier: index for index, identifier in enumerate(expected_ids)}
    ordered = sorted(result_items, key=lambda item: order[item[result_id_key]])
    return suite, result, ordered


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(
        path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    _atomic_text(path, "".join(canonical_json(value) + "\n" for value in values))


def _write_junit(
    path: Path,
    groups: Sequence[tuple[str, Sequence[Mapping[str, Any]], str]],
) -> None:
    root = ET.Element("testsuites")
    for name, items, id_key in groups:
        suite = ET.SubElement(
            root,
            "testsuite",
            name=name,
            tests=str(len(items)),
            failures=str(
                sum(
                    item["status"] != "passed" or item.get("attempts", 1) != 1
                    for item in items
                )
            ),
        )
        for item in items:
            case = ET.SubElement(
                suite, "testcase", name=str(item[id_key]), classname=name
            )
            effective_status = (
                item["status"] if item.get("attempts", 1) == 1 else "failed_after_retry"
            )
            if effective_status != "passed":
                failure = ET.SubElement(case, "failure", type=str(effective_status))
                failure.text = str(item.get("reason", effective_status))
    _atomic_text(path, ET.tostring(root, encoding="unicode") + "\n")


def _invalidate(output: Path, reason: str) -> int:
    for name in ("reward.txt", "scorecard.json"):
        (output / name).unlink(missing_ok=True)
    _atomic_json(
        output / "verdict.json",
        {
            "schema_version": VERDICT_SCHEMA,
            "status": "INVALID_RUN",
            "valid": False,
            "reason": reason,
        },
    )
    return 2


def score_results(
    *,
    task_suite: Path,
    task_results: Path,
    visual_suite: Path,
    visual_results: Path,
    cicd_suite: Path,
    cicd_results: Path,
    output: Path,
) -> int:
    """Validate exact result sets and emit the sole task-completion reward."""

    output.mkdir(parents=True, exist_ok=True)
    try:
        task_declaration, _, tasks = _validate_result_set(
            task_suite,
            task_results,
            suite_schema="websitebench.harbor.task-suite.v1",
            result_schema=TASK_RESULTS_SCHEMA,
            suite_key="tasks",
            result_key="tasks",
            result_id_key="task_id",
        )
        visual_declaration, _, checkpoints = _validate_result_set(
            visual_suite,
            visual_results,
            suite_schema="websitebench.harbor.visual-suite.v1",
            result_schema=VISUAL_RESULTS_SCHEMA,
            suite_key="checkpoints",
            result_key="checkpoints",
            result_id_key="checkpoint_id",
        )
        cicd_declaration, _, checks = _validate_result_set(
            cicd_suite,
            cicd_results,
            suite_schema="websitebench.harbor.cicd-suite.v1",
            result_schema=CICD_RESULTS_SCHEMA,
            suite_key="checks",
            result_key="checks",
            result_id_key="check_id",
        )
        platform_ids = {
            item.get("id")
            for item in cicd_declaration["checks"]
            if isinstance(item, dict) and item.get("kind") == "platform"
        }
        if platform_ids != set(PLATFORM_CICD_CHECKS):
            raise InvalidRun(
                "CI/CD exact platform check set mismatch: "
                f"missing={sorted(set(PLATFORM_CICD_CHECKS) - platform_ids)}:"
                f"extra={sorted(platform_ids - set(PLATFORM_CICD_CHECKS))}"
            )
        task_specs = {item["id"]: item for item in task_declaration["tasks"]}
        for item in tasks:
            observations = item.get("observations")
            if not isinstance(item.get("reason"), str) or not isinstance(
                observations, list
            ):
                raise InvalidRun(
                    f"task verdict lacks traceable reason/observations: {item['task_id']}"
                )
            declared = task_specs[item["task_id"]].get("observations", [])
            declared_types = {
                observation["id"]: observation["comparator"]["type"]
                for observation in declared
            }
            observed_ids: list[str] = []
            for observation in observations:
                if not isinstance(observation, dict):
                    raise InvalidRun(
                        f"task comparator verdict is malformed: {item['task_id']}"
                    )
                observation_id = observation.get("id")
                if (
                    not isinstance(observation_id, str)
                    or observation.get("comparator")
                    != declared_types.get(observation_id)
                    or not isinstance(observation.get("passed"), bool)
                ):
                    raise InvalidRun(
                        f"task comparator verdict is not declared: {item['task_id']}"
                    )
                observed_ids.append(observation_id)
            if len(observed_ids) != len(set(observed_ids)):
                raise InvalidRun(
                    f"task comparator verdict ids repeat: {item['task_id']}"
                )
            if item["status"] == "passed" and (
                set(observed_ids) != set(declared_types)
                or not all(observation["passed"] for observation in observations)
            ):
                raise InvalidRun(
                    f"passed task lacks all comparator verdicts: {item['task_id']}"
                )

        visual_specs = {item["id"]: item for item in visual_declaration["checkpoints"]}
        for checkpoint in checkpoints:
            value = checkpoint.get("ssim")
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                raise InvalidRun(
                    f"visual checkpoint has invalid SSIM: {checkpoint['checkpoint_id']}"
                )
            if checkpoint["status"] != "passed" and float(value) != 0:
                raise InvalidRun(
                    "unreachable or invalid-size visual checkpoints must score zero"
                )
            regions = checkpoint.get("regions")
            if not isinstance(checkpoint.get("reason"), str) or not isinstance(
                regions, list
            ):
                raise InvalidRun(
                    "visual verdict lacks traceable reason/regions: "
                    f"{checkpoint['checkpoint_id']}"
                )
            if checkpoint["status"] == "passed":
                expected_regions = {
                    region["id"]
                    for region in visual_specs[checkpoint["checkpoint_id"]].get(
                        "regions", []
                    )
                }
                actual_regions = {
                    region.get("region_id")
                    for region in regions
                    if isinstance(region, dict)
                    and isinstance(region.get("ssim"), (int, float))
                    and isinstance(region.get("area"), int)
                    and region.get("area", 0) > 0
                }
                if actual_regions != expected_regions or len(regions) != len(
                    expected_regions
                ):
                    raise InvalidRun(
                        "passed visual checkpoint lacks region SSIM verdicts: "
                        f"{checkpoint['checkpoint_id']}"
                    )

        for check in checks:
            if not isinstance(check.get("reason"), str) or check.get("source") not in {
                "trusted_platform_assertion",
                "trusted_check_exit_status",
            }:
                raise InvalidRun(
                    f"CI/CD verdict lacks trusted provenance: {check['check_id']}"
                )

        for item in tasks:
            attempts = item.get("attempts", 1)
            if (
                not isinstance(attempts, int)
                or isinstance(attempts, bool)
                or attempts < 1
            ):
                raise InvalidRun(f"task has invalid attempt count: {item['task_id']}")
        task_passed = sum(
            item["status"] == "passed" and item.get("attempts", 1) == 1
            for item in tasks
        )
        visual_passed = sum(item["status"] == "passed" for item in checkpoints)
        cicd_passed = sum(item["status"] == "passed" for item in checks)
        task_score = task_passed / len(tasks) * 100.0
        visual_score = (
            sum(float(item["ssim"]) for item in checkpoints) / len(checkpoints) * 100.0
        )
        cicd_score = cicd_passed / len(checks) * 100.0
        reward = round(task_score / 100.0, 8)
        scorecard = {
            "schema_version": SCORE_SCHEMA,
            "status": "VALID_RUN",
            "task_score": round(task_score, 8),
            "visual_score": round(visual_score, 8),
            "cicd_score": round(cicd_score, 8),
            "reward": reward,
            "reward_source": "task_completion",
            "counts": {
                "tasks": {"passed": task_passed, "total": len(tasks)},
                "visual_checkpoints": {
                    "passed": visual_passed,
                    "total": len(checkpoints),
                },
                "cicd_checks": {"passed": cicd_passed, "total": len(checks)},
            },
        }
    except InvalidRun as exc:
        return _invalidate(output, str(exc))

    _atomic_json(output / "scorecard.json", scorecard)
    for source, name in (
        (task_results, "task-results.json"),
        (visual_results, "visual-results.json"),
        (cicd_results, "cicd-results.json"),
    ):
        destination = output / name
        if source.resolve() != destination.resolve():
            temporary = destination.with_name(f".{destination.name}.scoring")
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
    _atomic_text(output / "reward.txt", f"{reward:.8f}\n")
    _atomic_json(
        output / "verdict.json",
        {"schema_version": VERDICT_SCHEMA, "status": "VALID_RUN", "valid": True},
    )
    _write_jsonl(output / "task-results.jsonl", tasks)
    _write_jsonl(output / "visual-results.jsonl", checkpoints)
    _write_jsonl(output / "cicd-results.jsonl", checks)
    _write_junit(
        output / "results.junit.xml",
        (
            ("tasks", tasks, "task_id"),
            ("visual", checkpoints, "checkpoint_id"),
            ("cicd", checks, "check_id"),
        ),
    )
    return 0


def _rect(value: Mapping[str, Any]) -> tuple[int, int, int, int]:
    return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])


def _overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return lx < rx + rw and rx < lx + lw and ly < ry + rh and ry < ly + lh


def _small_rgb_ssim(reference: Any, candidate: Any) -> tuple[float, Any]:
    """Global RGB SSIM fallback for regions smaller than skimage's 3x3 window."""

    import numpy as np

    first = reference.astype(np.float64)
    second = candidate.astype(np.float64)
    scores: list[float] = []
    for channel in range(3):
        x = first[..., channel].reshape(-1)
        y = second[..., channel].reshape(-1)
        ux, uy = float(x.mean()), float(y.mean())
        vx, vy = float(x.var()), float(y.var())
        covariance = float(((x - ux) * (y - uy)).mean())
        c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
        scores.append(
            ((2 * ux * uy + c1) * (2 * covariance + c2))
            / ((ux * ux + uy * uy + c1) * (vx + vy + c2))
        )
    score = max(0.0, min(1.0, sum(scores) / 3.0))
    return score, np.full(reference.shape[:2], score, dtype=np.float64)


def compute_visual_checkpoint(
    reference_path: Path,
    candidate_path: Path,
    checkpoint: Mapping[str, Any],
    *,
    heatmap_path: Path | None = None,
) -> dict[str, Any]:
    """Compute one checkpoint using fixed-size, region-area-weighted RGB SSIM."""

    import numpy as np
    from PIL import Image
    from skimage.metrics import structural_similarity

    identifier = str(checkpoint["id"])
    base = {"checkpoint_id": identifier}
    try:
        with Image.open(reference_path) as image:
            reference = np.asarray(image.convert("RGB"))
        with Image.open(candidate_path) as image:
            candidate = np.asarray(image.convert("RGB"))
    except (OSError, ValueError):
        return {
            **base,
            "status": "failed",
            "reason": "SCREENSHOT_UNREACHABLE",
            "ssim": 0.0,
            "regions": [],
        }

    viewport = checkpoint["viewport"]
    expected_shape = (int(viewport["height"]), int(viewport["width"]), 3)
    if reference.shape != expected_shape or candidate.shape != expected_shape:
        return {
            **base,
            "status": "failed",
            "reason": "SCREENSHOT_SIZE_MISMATCH",
            "ssim": 0.0,
            "reference_size": [int(reference.shape[1]), int(reference.shape[0])],
            "candidate_size": [int(candidate.shape[1]), int(candidate.shape[0])],
            "regions": [],
        }

    # A masked pixel must have no influence on any neighbouring SSIM window.
    # Excluding it only from the final mean is insufficient because SSIM is a
    # local-window metric.  Make the candidate identical to the reference in
    # every mask before computing the similarity map, then also exclude those
    # pixels from the declared region area below.
    candidate = candidate.copy()
    for region in checkpoint["regions"]:
        for mask in region.get("masks", []):
            mx, my, mw, mh = _rect(mask)
            left, top = max(0, mx), max(0, my)
            right = min(expected_shape[1], mx + mw)
            bottom = min(expected_shape[0], my + mh)
            if left < right and top < bottom:
                candidate[top:bottom, left:right] = reference[top:bottom, left:right]

    rectangles: list[tuple[int, int, int, int]] = []
    for region in checkpoint["regions"]:
        rectangle = _rect(region["rect"])
        x, y, width, height = rectangle
        if x + width > expected_shape[1] or y + height > expected_shape[0]:
            raise ValueError(f"visual region leaves viewport: {region['id']}")
        if any(_overlap(rectangle, prior) for prior in rectangles):
            raise ValueError("visual checkpoint regions must not overlap")
        rectangles.append(rectangle)

    heatmap = np.zeros(reference.shape[:2], dtype=np.float64)
    region_results: list[dict[str, Any]] = []
    weighted = 0.0
    total_area = 0
    for region, (x, y, width, height) in zip(checkpoint["regions"], rectangles):
        first = reference[y : y + height, x : x + width]
        second = candidate[y : y + height, x : x + width]
        active = np.ones((height, width), dtype=bool)
        for mask in region.get("masks", []):
            mx, my, mw, mh = _rect(mask)
            left, top = max(x, mx), max(y, my)
            right, bottom = min(x + width, mx + mw), min(y + height, my + mh)
            if left < right and top < bottom:
                active[top - y : bottom - y, left - x : right - x] = False
        area = int(active.sum())
        if area <= 0:
            raise ValueError(f"visual region is fully masked: {region['id']}")
        minimum = min(height, width)
        if minimum >= 3:
            window = min(7, minimum if minimum % 2 == 1 else minimum - 1)
            _score, similarity_map = structural_similarity(
                first,
                second,
                channel_axis=2,
                data_range=255,
                full=True,
                win_size=window,
            )
            if similarity_map.ndim == 3:
                similarity_map = similarity_map.mean(axis=2)
        else:
            score, _small_map = _small_rgb_ssim(first[active], second[active])
            similarity_map = np.full((height, width), score, dtype=np.float64)
        masked_score = float(np.clip(similarity_map[active].mean(), 0.0, 1.0))
        heatmap[y : y + height, x : x + width][active] = 1.0 - similarity_map[active]
        weighted += masked_score * area
        total_area += area
        region_results.append(
            {"region_id": region["id"], "area": area, "ssim": round(masked_score, 10)}
        )

    checkpoint_score = weighted / total_area
    if heatmap_path is not None:
        rendered = np.clip(heatmap * 255.0, 0, 255).astype(np.uint8)
        heatmap_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rendered, mode="L").save(
            heatmap_path, format="PNG", optimize=False
        )
    return {
        **base,
        "status": "passed",
        "reason": "SSIM_COMPUTED",
        "ssim": round(checkpoint_score, 10),
        "minimum_region_ssim": min(item["ssim"] for item in region_results),
        "area_weighted_mean_ssim": round(checkpoint_score, 10),
        "regions": region_results,
    }


def redact_visual_masks(path: Path, checkpoint: Mapping[str, Any]) -> None:
    """Black out every declared dynamic/sensitive mask before retaining a raster."""

    from PIL import Image, ImageDraw

    with Image.open(path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for region in checkpoint.get("regions", []):
        for mask in region.get("masks", []):
            x, y, width, height = _rect(mask)
            draw.rectangle((x, y, x + width - 1, y + height - 1), fill=(0, 0, 0))
    image.save(path, format="PNG", optimize=False)


def score_visual_suite(
    suite: Mapping[str, Any],
    *,
    reference_root: Path,
    candidate_root: Path,
    heatmap_root: Path,
) -> dict[str, Any]:
    checkpoints: list[dict[str, Any]] = []
    for item in suite["checkpoints"]:
        identifier = item["id"]
        checkpoints.append(
            compute_visual_checkpoint(
                reference_root / item["reference_image"],
                candidate_root / f"{identifier}.png",
                item,
                heatmap_path=heatmap_root / f"{identifier}.png",
            )
        )
    values = [float(item["ssim"]) for item in checkpoints]
    return {
        "schema_version": VISUAL_RESULTS_SCHEMA,
        "checkpoints": checkpoints,
        "summary": {
            "minimum_ssim": min(values),
            "mean_ssim": sum(values) / len(values),
            "total": len(values),
        },
    }


def tree_snapshot(root: Path, *, exclude: Iterable[Path] = ()) -> tuple[Any, ...]:
    excluded = {path.resolve() for path in exclude}
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if any(resolved == item or item in resolved.parents for item in excluded):
            continue
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            entries.append(
                {"path": relative, "type": "symlink", "target": os.readlink(path)}
            )
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "content": path.read_bytes(),
                }
            )
        elif path.is_dir():
            entries.append(
                {
                    "path": relative,
                    "type": "directory",
                    "mode": stat.S_IMODE(metadata.st_mode),
                }
            )
        else:
            entries.append({"path": relative, "type": "other"})
    return tuple(
        tuple(sorted(entry.items(), key=lambda item: item[0])) for entry in entries
    )


def _free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class CandidateProcess:
    root: Path
    port: int
    data_dir: Path
    mailbox_namespace: str
    mailbox_capability: str | None = None
    audit_prefix: Path | None = None
    cpu_limit: int | None = None
    memory_limit_mb: int | None = None
    storage_limit_mb: int | None = None
    isolation_uid: int | None = None
    allowed_connect_ports: tuple[int, ...] = ()
    stdout_path: Path | None = None
    process: subprocess.Popen[bytes] | None = None
    _sentinel_initialized: bool = False
    _audit_failed: bool = False
    _broker_tid_fd: int | None = None
    _control_write_fd: int | None = None
    _broker_tid_buffer: bytes = b""
    _broker_tid: int | None = None
    _audit_generation: int = 0
    _active_audit_prefix: Path | None = None
    _trusted_audit_logs: tuple[Path, ...] = ()
    _stdout_handle: Any | None = None
    _audit_watchdog: threading.Thread | None = None
    _audit_watchdog_stop: threading.Event | None = None
    _lifecycle_clean: bool = True

    def start(self) -> None:
        if not self._lifecycle_clean:
            raise RuntimeError("candidate lifecycle cleanup is incomplete")
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("candidate process is already running")
        self._stop_audit_watchdog()
        self._close_stdout_handle()
        if self._broker_tid_fd is not None:
            self._audit_failed = True
            self._close_broker_tid_fd()
        self._close_control_fd()
        deploy = self.root / "deploy.sh"
        # Start from an explicit public contract. In particular, verifier,
        # source-reference, CI and provider credentials can never reach an
        # untrusted candidate merely because the platform added a new secret.
        environment = {
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "TZ": "Etc/UTC",
                "PORT": str(self.port),
                "WEBSITEBENCH_DATA_DIR": str(self.data_dir),
                "WEBSITEBENCH_MAILBOX_NAMESPACE": self.mailbox_namespace,
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "NO_PROXY": "127.0.0.1,localhost",
                "PYTHONDONTWRITEBYTECODE": "1",
                "HOME": str(self.data_dir),
                "TMPDIR": str(self.data_dir / "tmp"),
                "XDG_CACHE_HOME": str(self.data_dir / "cache"),
                "XDG_CONFIG_HOME": str(self.data_dir / "config"),
                "XDG_STATE_HOME": str(self.data_dir / "state"),
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
        for name in ("WEBSITEBENCH_SMTP_HOST", "WEBSITEBENCH_SMTP_PORT"):
            value = os.environ.get(name)
            if value is not None:
                environment[name] = value
        if self.mailbox_capability is not None:
            environment["WEBSITEBENCH_MAILBOX_CAPABILITY"] = self.mailbox_capability
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for child in ("tmp", "cache", "config", "state"):
            (self.data_dir / child).mkdir(exist_ok=True)
        if not self._sentinel_initialized:
            _write_isolation_sentinel(self.data_dir, self.mailbox_namespace)
            self._sentinel_initialized = True
        preexec = None
        account = None
        run_uid: int | None = None
        run_gid: int | None = None
        if pwd is not None and hasattr(os, "geteuid") and os.geteuid() == 0:
            if self.isolation_uid is not None:
                run_uid = self.isolation_uid
                run_gid = self.isolation_uid
            else:
                try:
                    account = pwd.getpwuid(10001)
                except KeyError:
                    account = None
                if account is not None:
                    run_uid, run_gid = account.pw_uid, account.pw_gid
            if run_uid is not None and run_gid is not None:
                os.chmod(self.data_dir, 0o700)
                os.chown(self.data_dir, run_uid, run_gid)
                for child in ("tmp", "cache", "config", "state"):
                    os.chmod(self.data_dir / child, 0o700)
                    os.chown(
                        self.data_dir / child,
                        run_uid,
                        run_gid,
                    )

        def apply_limits() -> None:
            if self.cpu_limit is not None and hasattr(os, "sched_getaffinity"):
                allowed = sorted(os.sched_getaffinity(0))
                os.sched_setaffinity(0, allowed[: self.cpu_limit])
            if resource is not None and self.memory_limit_mb is not None:
                memory_bytes = self.memory_limit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            if resource is not None and run_uid is not None:
                resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))

        if any(
            limit is not None
            for limit in (
                self.cpu_limit,
                self.memory_limit_mb,
            )
            or run_uid is not None
        ):
            preexec = apply_limits

        sandbox = Path(__file__).with_name("sandbox_v2.py").resolve(strict=True)
        command = [
            sys.executable,
            str(sandbox),
            "--root",
            str(self.root.resolve(strict=True)),
            "--data",
            str(self.data_dir.resolve(strict=True)),
            "--bind-port",
            str(self.port),
        ]
        allowed_connect_ports = set(self.allowed_connect_ports) | {self.port}
        smtp_host = environment.get("WEBSITEBENCH_SMTP_HOST", "").lower()
        smtp_port = environment.get("WEBSITEBENCH_SMTP_PORT", "")
        if smtp_host in {"127.0.0.1", "localhost", "::1"} and smtp_port.isdigit():
            allowed_connect_ports.add(int(smtp_port))
        for allowed_port in sorted(allowed_connect_ports):
            command.extend(["--connect-port", str(allowed_port)])
        if run_uid is not None and run_gid is not None:
            command.extend(["--uid", str(run_uid), "--gid", str(run_gid)])
        if self.storage_limit_mb is not None:
            command.extend(
                [
                    "--file-size-limit-bytes",
                    str(self.storage_limit_mb * 1024 * 1024),
                ]
            )
        control_read_fd, control_write_fd = os.pipe()
        self._control_write_fd = control_write_fd
        command.extend(["--control-fd", str(control_read_fd), "--", str(deploy)])
        if self.audit_prefix is not None:
            tracer = shutil.which("strace")
            if tracer is None:
                os.close(control_read_fd)
                self._close_control_fd()
                raise OSError("strace is required for candidate write auditing")
            self.audit_prefix.parent.mkdir(parents=True, exist_ok=True)
            self._audit_generation += 1
            self._active_audit_prefix = self.audit_prefix.with_name(
                f"{self.audit_prefix.name}.generation-{self._audit_generation}"
            )
            self._broker_tid_buffer = b""
            self._broker_tid = None
            broker_read_fd, broker_write_fd = os.pipe()
            os.set_blocking(broker_read_fd, False)
            self._broker_tid_fd = broker_read_fd
            command[-2:-2] = ["--broker-tid-fd", str(broker_write_fd)]
            command = [
                tracer,
                "--follow-forks",
                "--decode-fds=path",
                "--output-separately",
                "--output",
                str(self._active_audit_prefix),
                "--trace=%file,%memory,%network,%ipc,ftruncate",
                *command,
            ]
        else:
            broker_write_fd = None
        try:
            if self.stdout_path is not None:
                stdout_path = self.stdout_path.resolve()
                data_root = self.data_dir.resolve()
                if data_root not in stdout_path.parents:
                    raise ValueError("candidate stdout path must be inside data dir")
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                self._stdout_handle = stdout_path.open("ab")
            self.process = subprocess.Popen(
                command,
                cwd=self.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout_handle or subprocess.DEVNULL,
                stderr=self._stdout_handle or subprocess.DEVNULL,
                start_new_session=True,
                preexec_fn=preexec,
                pass_fds=(
                    (control_read_fd,)
                    if broker_write_fd is None
                    else (broker_write_fd, control_read_fd)
                ),
            )
            self._lifecycle_clean = False
        except BaseException:
            self._close_stdout_handle()
            if broker_write_fd is not None:
                os.close(broker_write_fd)
            self._close_broker_tid_fd()
            self._close_control_fd()
            raise
        finally:
            os.close(control_read_fd)
        if broker_write_fd is not None:
            os.close(broker_write_fd)
        if self.audit_prefix is not None:
            self._start_audit_watchdog()

    def ready(self, path: str = "/healthz", timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}{path}"
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                return False
            try:
                with urlopen_no_redirect(url, timeout=0.5) as response:
                    if response.status == 200:
                        return True
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.05)
        return False

    def stop(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout

        def group_exited(group: int) -> bool:
            while _process_group_alive(group):
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.02)
            return True

        if self.process is None:
            self._finish_broker_attestation()
            self._stop_audit_watchdog()
            self._close_stdout_handle()
            self._close_control_fd()
            self._lifecycle_clean = True
            return True
        process = self.process
        group = process.pid
        if process.poll() is not None:
            if not group_exited(group):
                self._audit_failed = self.audit_prefix is not None
                _kill_process_group(group, signal.SIGKILL)
                self._finish_broker_attestation()
                self._stop_audit_watchdog()
                self._close_stdout_handle()
                self._close_control_fd()
                self._lifecycle_clean = False
                return False
            if (
                self.audit_prefix is not None
                and process.returncode is not None
                and process.returncode != 0
            ):
                self._audit_failed = self.audit_prefix is not None
            self._finish_broker_attestation()
            self._stop_audit_watchdog()
            self._close_stdout_handle()
            self._close_control_fd()
            self._lifecycle_clean = True
            return not self._audit_failed
        if not self._request_candidate_signal(signal.SIGTERM):
            _kill_process_group(group, signal.SIGTERM, process=process)
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _kill_process_group(group, signal.SIGKILL, process=process)
            process.wait(timeout=5)
            self._audit_failed = self.audit_prefix is not None
            self._finish_broker_attestation()
            self._stop_audit_watchdog()
            self._close_stdout_handle()
            self._close_control_fd()
            self._lifecycle_clean = False
            return False
        if not group_exited(group):
            _kill_process_group(group, signal.SIGKILL, process=process)
            self._audit_failed = self.audit_prefix is not None
            self._finish_broker_attestation()
            self._stop_audit_watchdog()
            self._close_stdout_handle()
            self._close_control_fd()
            self._lifecycle_clean = False
            return False
        self._finish_broker_attestation()
        self._stop_audit_watchdog()
        self._close_stdout_handle()
        self._close_control_fd()
        self._lifecycle_clean = True
        return not self._audit_failed

    def _request_candidate_signal(self, requested_signal: signal.Signals) -> bool:
        if self._control_write_fd is None:
            return False
        payload = {
            signal.SIGTERM: b"T",
            signal.SIGKILL: b"K",
        }.get(requested_signal)
        if payload is None:
            return False
        try:
            os.write(self._control_write_fd, payload)
        except OSError:
            return False
        return True

    def _close_control_fd(self) -> None:
        if self._control_write_fd is None:
            return
        try:
            os.close(self._control_write_fd)
        except OSError:
            pass
        self._control_write_fd = None

    def write_violations(self) -> list[str]:
        """Return audited write paths outside WEBSITEBENCH_DATA_DIR."""

        if self.audit_prefix is None:
            return ["WRITE_AUDIT_NOT_CONFIGURED"]
        self._finish_broker_attestation()
        if self._broker_tid_fd is not None:
            return ["WRITE_AUDIT_INCOMPLETE"]
        if self._audit_failed:
            return ["WRITE_AUDIT_TERMINATED_EARLY"]
        allowed_root = self.data_dir.resolve()
        violations: set[str] = set()
        write_calls = re.compile(
            r"^(?:open|openat|openat2|creat|truncate|ftruncate|mmap|mmap2|rename|renameat|renameat2|unlink|"
            r"unlinkat|mkdir|mkdirat|rmdir|link|linkat|symlink|symlinkat|mknod|"
            r"mknodat|chmod|fchmod|fchmodat|chown|fchown|fchownat|lchown|utime|"
            r"utimes|futimesat|utimensat|setxattr|lsetxattr|fsetxattr|removexattr|"
            r"lremovexattr|fremovexattr)\("
        )
        write_flags = re.compile(r"O_(?:WRONLY|RDWR|CREAT|TRUNC|APPEND)")
        quoted = re.compile(r'"(?:\\.|[^"\\])*"')
        proc_fd_path = re.compile(r"^/proc/\d+/fd/\d+$")
        proc_mem_path = re.compile(r"^/proc/\d+/mem$")
        decoded_return_path = re.compile(r"\)\s+=\s+\d+<([^>]+)>")
        logs = sorted(self.audit_prefix.parent.glob(self.audit_prefix.name + "*"))
        if not logs:
            return ["WRITE_AUDIT_EMPTY"]
        for log in logs:
            if log in self._trusted_audit_logs:
                continue
            try:
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                violations.add("WRITE_AUDIT_UNREADABLE")
                continue
            cwd = self.root.resolve()
            for line in lines:
                if line.startswith("chdir(") and " = 0" in line:
                    match = quoted.search(line)
                    if match:
                        value = ast.literal_eval(match.group(0))
                        target = Path(value)
                        cwd = (
                            (cwd / target).resolve()
                            if not target.is_absolute()
                            else target.resolve()
                        )
                    continue
                if not write_calls.search(line):
                    continue
                if line.startswith(
                    ("open(", "openat(", "openat2(")
                ) and not write_flags.search(line):
                    continue
                if line.startswith(("mmap(", "mmap2(")) and not (
                    "PROT_WRITE" in line and "MAP_SHARED" in line
                ):
                    continue
                decoded_base = re.search(r"(?:AT_FDCWD|\d+)<([^>]+)>", line)
                line_base = (
                    Path(decoded_base.group(1)).resolve()
                    if decoded_base is not None
                    else cwd
                )
                raw_paths = quoted.findall(line)
                if line.startswith(("open(", "openat(", "openat2(")) and raw_paths:
                    try:
                        opened_path = ast.literal_eval(raw_paths[0])
                    except (SyntaxError, ValueError):
                        opened_path = None
                    if isinstance(opened_path, str) and proc_mem_path.fullmatch(
                        opened_path
                    ):
                        # The trusted seccomp broker writes syscall results through
                        # tracee memory. This is process state, not candidate file
                        # persistence, and strace follows the broker as a child.
                        continue
                    if isinstance(opened_path, str) and proc_fd_path.fullmatch(
                        opened_path
                    ):
                        decoded_return = decoded_return_path.search(line)
                        if decoded_return is not None:
                            # The broker reopens a tracee descriptor through procfs.
                            # Audit its decoded target rather than the transport path.
                            raw_paths = [json.dumps(decoded_return.group(1))]
                if line.startswith(("symlink(", "symlinkat(")):
                    raw_paths = raw_paths[-1:]
                if not raw_paths and decoded_base is not None:
                    decoded_target = Path(decoded_base.group(1)).resolve()
                    if (
                        decoded_target != allowed_root
                        and allowed_root not in decoded_target.parents
                    ):
                        violations.add(str(decoded_target))
                for raw in raw_paths:
                    try:
                        value = ast.literal_eval(raw)
                    except (SyntaxError, ValueError):
                        violations.add("WRITE_AUDIT_PATH_UNPARSEABLE")
                        continue
                    target = Path(value)
                    resolved = (
                        (line_base / target).resolve()
                        if not target.is_absolute()
                        else target.resolve()
                    )
                    if resolved in {
                        Path("/dev/null"),
                        Path("/dev/zero"),
                        Path("/dev/random"),
                        Path("/dev/urandom"),
                        Path("/dev/full"),
                        Path("/dev/tty"),
                    }:
                        continue
                    if (
                        resolved != allowed_root
                        and allowed_root not in resolved.parents
                    ):
                        violations.add(str(resolved))
        return sorted(violations)

    def _consume_broker_tid(self) -> None:
        descriptor = self._broker_tid_fd
        if descriptor is None:
            return
        while True:
            try:
                chunk = os.read(descriptor, 64)
            except BlockingIOError:
                break
            except OSError:
                chunk = b""
            if not chunk:
                self._close_broker_tid_fd()
                break
            self._broker_tid_buffer += chunk
        lines = self._broker_tid_buffer.split(b"\n")
        pending = lines.pop()
        for line in lines:
            if re.fullmatch(rb"[1-9][0-9]*", line) is None:
                self._audit_failed = True
                continue
            value = int(line)
            if value <= 0 or self._broker_tid is not None:
                self._audit_failed = True
                continue
            self._broker_tid = value
        self._broker_tid_buffer = pending

    def _close_broker_tid_fd(self) -> None:
        if self._broker_tid_fd is not None:
            try:
                os.close(self._broker_tid_fd)
            except OSError:
                pass
            self._broker_tid_fd = None

    def _close_stdout_handle(self) -> None:
        if self._stdout_handle is not None:
            self._stdout_handle.close()
            self._stdout_handle = None

    def _start_audit_watchdog(self) -> None:
        if self.audit_prefix is None or self.process is None:
            return
        stop = threading.Event()
        self._audit_watchdog_stop = stop
        base = self.audit_prefix
        process = self.process

        def watch() -> None:
            while not stop.wait(0.05):
                total = 0
                try:
                    for log in base.parent.glob(base.name + "*"):
                        if log.is_file():
                            total += log.stat().st_size
                            if total > MAX_CANDIDATE_AUDIT_BYTES:
                                self._audit_failed = True
                                _kill_process_group(
                                    process.pid, signal.SIGKILL, process=process
                                )
                                return
                except OSError:
                    self._audit_failed = True
                    _kill_process_group(process.pid, signal.SIGKILL, process=process)
                    return

        watchdog = threading.Thread(
            target=watch,
            name=f"candidate-audit-watchdog-{self._audit_generation}",
            daemon=True,
        )
        self._audit_watchdog = watchdog
        watchdog.start()

    def _stop_audit_watchdog(self) -> None:
        stop = self._audit_watchdog_stop
        watchdog = self._audit_watchdog
        if stop is not None:
            stop.set()
        if watchdog is not None and watchdog is not threading.current_thread():
            watchdog.join(timeout=1)
        self._audit_watchdog = None
        self._audit_watchdog_stop = None

    def _finish_broker_attestation(self) -> None:
        if self.audit_prefix is None or self._active_audit_prefix is None:
            return
        self._consume_broker_tid()
        if self._broker_tid_fd is not None:
            return
        if self._broker_tid_buffer or self._broker_tid is None:
            self._audit_failed = True
            return
        expected = self._active_audit_prefix.with_name(
            f"{self._active_audit_prefix.name}.{self._broker_tid}"
        )
        if not expected.is_file():
            self._audit_failed = True
            return
        if expected not in self._trusted_audit_logs:
            self._trusted_audit_logs = (*self._trusted_audit_logs, expected)

    def network_violations(self) -> list[str]:
        """Return destinations outside this worker's declared TCP surface."""

        if self.audit_prefix is None:
            return ["NETWORK_AUDIT_NOT_CONFIGURED"]
        self._finish_broker_attestation()
        if self._broker_tid_fd is not None:
            return ["NETWORK_AUDIT_INCOMPLETE"]
        if self._audit_failed:
            return ["NETWORK_AUDIT_TERMINATED_EARLY"]
        logs = sorted(self.audit_prefix.parent.glob(self.audit_prefix.name + "*"))
        if not logs:
            return ["NETWORK_AUDIT_EMPTY"]
        violations: set[str] = set()
        ipv4 = re.compile(r'inet_addr\("([^"\\]+)"\)')
        ipv6 = re.compile(r'inet_pton\(AF_INET6,\s*"([^"\\]+)"')
        port_pattern = re.compile(r"sin6?_port=htons\((\d+)\)")
        unix_path = re.compile(r'sun_path=(@?)"([^"\\]+)"')
        allowed_ports = set(self.allowed_connect_ports) | {self.port}
        smtp_host = os.environ.get("WEBSITEBENCH_SMTP_HOST", "").lower()
        smtp_port = os.environ.get("WEBSITEBENCH_SMTP_PORT", "")
        if smtp_host in {"127.0.0.1", "localhost", "::1"} and smtp_port.isdigit():
            allowed_ports.add(int(smtp_port))
        for log in logs:
            try:
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                violations.add("NETWORK_AUDIT_UNREADABLE")
                continue
            for line in lines:
                if not line.startswith(("bind(", "connect(", "sendto(", "sendmsg(")):
                    continue
                unix = unix_path.search(line)
                if unix is not None:
                    raw = unix.group(2)
                    if unix.group(1) or raw.startswith("/"):
                        target = Path(raw)
                        if unix.group(1) or (
                            target.resolve() != self.data_dir.resolve()
                            and self.data_dir.resolve() not in target.resolve().parents
                        ):
                            violations.add("UNIX_SOCKET_OUTSIDE_DATA_DIR")
                    continue
                port_match = port_pattern.search(line)
                port = int(port_match.group(1)) if port_match is not None else None
                if line.startswith("bind("):
                    if (ipv4.search(line) or ipv6.search(line)) and port != self.port:
                        violations.add("TCP_BIND_OUTSIDE_ASSIGNED_PORT")
                    continue
                for match in ipv4.finditer(line):
                    address = match.group(1)
                    if address.startswith("127.") or address == "0.0.0.0":
                        if port not in allowed_ports:
                            violations.add("LOOPBACK_CONNECT_OUTSIDE_ALLOWED_PORTS")
                    else:
                        violations.add(address)
                for match in ipv6.finditer(line):
                    address = match.group(1).lower()
                    if address in {"::", "::1", "0:0:0:0:0:0:0:1"}:
                        if port not in allowed_ports:
                            violations.add("LOOPBACK_CONNECT_OUTSIDE_ALLOWED_PORTS")
                    else:
                        violations.add(address)
        return sorted(violations)

    def ipc_violations(self) -> list[str]:
        """Return attempted kernel-global IPC operations from the audit trace."""

        if self.audit_prefix is None:
            return ["IPC_AUDIT_NOT_CONFIGURED"]
        self._finish_broker_attestation()
        if self._broker_tid_fd is not None:
            return ["IPC_AUDIT_INCOMPLETE"]
        if self._audit_failed:
            return ["IPC_AUDIT_TERMINATED_EARLY"]
        logs = sorted(self.audit_prefix.parent.glob(self.audit_prefix.name + "*"))
        if not logs:
            return ["IPC_AUDIT_EMPTY"]
        calls = re.compile(
            r"^(?:shmget|shmat|shmdt|shmctl|msgget|msgsnd|msgrcv|msgctl|"
            r"semget|semop|semtimedop|semctl|mq_open|mq_unlink|mq_timedsend|"
            r"mq_timedreceive|mq_notify|mq_getsetattr|add_key|request_key|keyctl)\("
        )
        violations: set[str] = set()
        for log in logs:
            try:
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                violations.add("IPC_AUDIT_UNREADABLE")
                continue
            if any(calls.search(line) for line in lines):
                violations.add("SHARED_IPC_ATTEMPT")
        return sorted(violations)


def _kill_process_group(
    group: int,
    requested_signal: signal.Signals,
    *,
    process: subprocess.Popen[bytes] | None = None,
) -> None:
    try:
        if os.name == "posix":
            os.killpg(group, requested_signal)
        elif process is not None:
            process.send_signal(requested_signal)
    except (OSError, ProcessLookupError):
        pass


def _process_group_alive(group: int) -> bool:
    if os.name != "posix":
        return False
    proc = Path("/proc")
    if proc.is_dir():
        found_non_zombie = False
        for status_path in proc.glob("[0-9]*/stat"):
            try:
                raw = status_path.read_text(encoding="ascii")
                fields = raw[raw.rfind(")") + 2 :].split()
                state = fields[0]
                process_group = int(fields[2])
            except (OSError, UnicodeError, ValueError, IndexError):
                continue
            if process_group == group and state != "Z":
                found_non_zombie = True
                break
        if not found_non_zombie:
            return False
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def synthesize_deploy_failure(
    task_suite: Mapping[str, Any], reason: str
) -> dict[str, Any]:
    tasks = [
        {
            "task_id": task["id"],
            "status": "failed",
            "reason": reason,
            "attempts": 1,
            "observations": [],
        }
        for task in task_suite["tasks"]
    ]
    return {
        "schema_version": TASK_RESULTS_SCHEMA,
        "tasks": tasks,
        "summary": {"passed": 0, "total": len(tasks)},
    }


def _safe_candidate_root(root: Path) -> tuple[bool, str]:
    try:
        root_metadata = root.lstat()
        resolved = root.resolve(strict=True)
        deploy = resolved / "deploy.sh"
        metadata = deploy.lstat()
    except (OSError, RuntimeError) as exc:
        return False, f"CANDIDATE_ARTIFACT_MISSING:{exc}"
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not resolved.is_dir()
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        return False, "DEPLOY_NOT_REGULAR"
    if not metadata.st_mode & stat.S_IXUSR:
        return False, "DEPLOY_NOT_EXECUTABLE"
    if deploy.resolve().parent != resolved:
        return False, "DEPLOY_PATH_ESCAPE"
    return True, "ARTIFACT_OK"


def _artifact_path_scan(root: Path) -> tuple[bool, str]:
    """Reject special files and links that can escape the submitted artifact."""

    try:
        resolved_root = root.resolve(strict=True)
        files = 0
        for path in root.rglob("*"):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                target = path.resolve(strict=True)
                if target != resolved_root and resolved_root not in target.parents:
                    return False, "ARTIFACT_SYMLINK_ESCAPE"
            elif stat.S_ISREG(metadata.st_mode):
                if metadata.st_nlink != 1:
                    return False, "ARTIFACT_HARDLINK_FORBIDDEN"
                files += 1
            elif not stat.S_ISDIR(metadata.st_mode):
                return False, "ARTIFACT_SPECIAL_FILE"
        if files == 0:
            return False, "ARTIFACT_EMPTY"
    except (OSError, RuntimeError):
        return False, "ARTIFACT_PATH_SCAN_FAILED"
    return True, f"ARTIFACT_FILES:{files}"


def _static_deploy_scan(root: Path) -> tuple[bool, str]:
    forbidden = re.compile(
        r"(?:\bcurl\b|\bwget\b|\bnpm\s+(?:i|install|ci)\b|\bpnpm\s+install\b|"
        r"\byarn\s+install\b|\bpip(?:3)?\s+install\b|\bapt(?:-get)?\b|https?://)",
        re.IGNORECASE,
    )
    try:
        text = (root / "deploy.sh").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return False, f"DEPLOY_UNREADABLE:{exc}"
    return (
        (False, "DEPLOY_NETWORK_OR_INSTALL_COMMAND")
        if forbidden.search(text)
        else (True, "OFFLINE_DEPLOY_STATIC_OK")
    )


def _secret_reference_scan(root: Path) -> tuple[bool, str]:
    name_pattern = re.compile(
        r"(?:^|[-_.])(reference|verifier|scorecard|reward|hidden-suite)(?:[-_.]|$)",
        re.I,
    )
    secret_pattern = re.compile(
        r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
        r"\b(?:OPENAI|ANTHROPIC|GEMINI|GOOGLE_API|AWS_SECRET_ACCESS)_?[A-Z_]*\s*=)",
        re.I,
    )
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if name_pattern.search(path.relative_to(root).as_posix()):
            return False, "FORBIDDEN_VERIFIER_OR_REFERENCE_ARTIFACT"
        if path.stat().st_size <= 1024 * 1024:
            try:
                if secret_pattern.search(path.read_text(encoding="utf-8")):
                    return False, "SECRET_PATTERN_FOUND"
            except UnicodeError:
                continue
    return True, "SCAN_CLEAN"


def _network_policy_closed(policy: Mapping[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(policy, Mapping):
        return False, "VERIFIER_NETWORK_POLICY_MISSING"
    allowlist = policy.get("mailbox_external_allowlist", [])
    closed = (
        policy.get("default") == "deny"
        and policy.get("public_internet") is False
        and policy.get("model_services") is False
        and isinstance(allowlist, list)
        and all(isinstance(item, str) and item for item in allowlist)
    )
    return (
        (True, "VERIFIER_NETWORK_DEFAULT_DENY")
        if closed
        else (False, "VERIFIER_NETWORK_POLICY_OPEN")
    )


def verifier_network_policy_enforced(
    policy: Mapping[str, Any],
    *,
    default_route_present: bool,
    platform_attested: bool,
) -> bool:
    """Derive runtime closure from sealed policy and observable platform state."""

    closed, _reason = _network_policy_closed(policy)
    return closed and (platform_attested or not default_route_present)


def _write_isolation_sentinel(data_dir: Path, identity: str) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    sentinel = data_dir / ".websitebench-isolation-sentinel"
    sentinel.write_text(identity + "\n", encoding="utf-8", newline="\n")
    return sentinel


def _sentinel_matches(path: Path, identity: str) -> bool:
    try:
        return path.read_text(encoding="utf-8") == identity + "\n"
    except (OSError, UnicodeError):
        return False


def _process_group_rss_kb(process: subprocess.Popen[bytes] | None) -> int | None:
    """Return Linux RSS for all members of the candidate process group."""

    if process is None or os.name != "posix" or not Path("/proc").is_dir():
        return None
    group = process.pid
    total = 0
    found = False
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat_text = (entry / "stat").read_text(encoding="utf-8")
            fields = stat_text[stat_text.rfind(")") + 2 :].split()
            if len(fields) < 3 or int(fields[2]) != group:
                continue
            status = (entry / "status").read_text(encoding="utf-8")
            match = re.search(r"^VmRSS:\s+(\d+)\s+kB$", status, re.MULTILINE)
            if match:
                total += int(match.group(1))
                found = True
        except (OSError, UnicodeError, ValueError):
            continue
    return total if found else None


def _has_process_descendant(process: subprocess.Popen[bytes] | None) -> bool:
    if process is None or not Path("/proc").is_dir():
        return process is not None and process.poll() is None
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            value = (entry / "stat").read_text(encoding="utf-8")
            fields = value[value.rfind(")") + 2 :].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, UnicodeError, ValueError, IndexError):
            continue
    for pid in parents:
        current = pid
        visited: set[int] = set()
        while current in parents and current not in visited:
            visited.add(current)
            current = parents[current]
            if current == process.pid:
                return True
    return False


def _directory_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _cgroup_cpu_limit() -> float | None:
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota == "max":
            return None
        return int(quota) / int(period)
    except (OSError, ValueError, ZeroDivisionError):
        try:
            quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            return None if quota < 0 else quota / period
        except (OSError, ValueError, ZeroDivisionError):
            return None


def _process_affinity_count(process: subprocess.Popen[bytes] | None) -> int | None:
    if process is None or not hasattr(os, "sched_getaffinity"):
        return None
    try:
        return len(os.sched_getaffinity(process.pid))
    except (OSError, ProcessLookupError):
        return None


def run_platform_cicd(
    candidate_root: Path,
    suite: Mapping[str, Any],
    *,
    ready_path: str = "/healthz",
    startup_timeout: float = 30.0,
    memory_limit_mb: int | None = None,
    storage_limit_mb: int | None = None,
    cpu_limit: int | None = None,
    network_policy: Mapping[str, Any] | None = None,
    trusted_runner_root: Path | None = None,
    output_root: Path | None = None,
    mailbox_sidecar: Any | None = None,
) -> dict[str, Any]:
    """Run fixed, boolean platform checks; custom verifier checks remain separate."""

    checks_by_id = {item["id"]: item for item in suite["checks"]}
    missing = sorted(set(PLATFORM_CICD_CHECKS) - set(checks_by_id))
    if missing:
        raise ValueError(f"CI/CD suite is missing fixed platform checks: {missing}")
    results: dict[str, dict[str, Any]] = {}

    def record(identifier: str, passed: bool, reason: str) -> None:
        results[identifier] = {
            "check_id": identifier,
            "status": "passed" if passed else "failed",
            "reason": reason,
            "source": "trusted_platform_assertion",
        }

    safe, reason = _safe_candidate_root(candidate_root)
    complete, complete_reason = (
        _artifact_path_scan(candidate_root) if safe else (False, reason)
    )
    record("platform::artifact/complete", safe and complete, complete_reason)
    record("platform::artifact/deploy-path-safe", safe, reason)
    offline, offline_reason = (
        _static_deploy_scan(candidate_root) if safe else (False, reason)
    )
    record("platform::deploy/offline-clean", offline, offline_reason)
    clean, clean_reason = (
        _secret_reference_scan(candidate_root)
        if safe and complete
        else (False, complete_reason if safe else reason)
    )
    record("platform::security/secret-reference-verifier-scan", clean, clean_reason)
    network_closed, network_reason = _network_policy_closed(network_policy)
    record("platform::network/external-closed", network_closed, network_reason)

    lifecycle_ids = (
        "platform::deploy/healthz",
        "platform::deploy/foreground-lifecycle",
        "platform::deploy/graceful-sigterm",
        "platform::deploy/restart-persistence",
        "platform::deploy/concurrent-isolation",
        "platform::artifact/code-tree-unchanged",
        "platform::browser/chromium-smoke",
        "platform::accessibility/basic",
        "platform::performance/startup-budget",
        "platform::performance/resource-budget",
    )
    if not safe or not complete:
        for identifier in lifecycle_ids:
            record(identifier, False, "CANDIDATE_ARTIFACT_INVALID")
    else:
        before = tree_snapshot(candidate_root)
        with tempfile.TemporaryDirectory(
            prefix="websitebench-v2-evaluate-"
        ) as temporary:
            temp = Path(temporary)
            temp.chmod(0o711)
            first_identity = secrets.token_hex(16)
            second_identity = secrets.token_hex(16)
            first_uid = opaque_isolation_uid()
            second_uid = opaque_isolation_uid()
            first_capability = (
                secrets.token_hex(32) if mailbox_sidecar is not None else None
            )
            second_capability = (
                secrets.token_hex(32) if mailbox_sidecar is not None else None
            )
            if mailbox_sidecar is not None:
                mailbox_sidecar.register_namespace(
                    f"worker-{first_identity}", first_capability
                )
                mailbox_sidecar.register_namespace(
                    f"worker-{second_identity}", second_capability
                )
            first = CandidateProcess(
                candidate_root,
                _free_loopback_port(),
                temp / "workers" / f"worker-{first_identity}" / "data",
                f"worker-{first_identity}",
                mailbox_capability=first_capability,
                audit_prefix=temp / "audit" / "first",
                cpu_limit=cpu_limit,
                memory_limit_mb=memory_limit_mb,
                storage_limit_mb=storage_limit_mb,
                isolation_uid=first_uid,
            )
            second = CandidateProcess(
                candidate_root,
                _free_loopback_port(),
                temp / "workers" / f"worker-{second_identity}" / "data",
                f"worker-{second_identity}",
                mailbox_capability=second_capability,
                audit_prefix=temp / "audit" / "second",
                cpu_limit=cpu_limit,
                memory_limit_mb=memory_limit_mb,
                storage_limit_mb=storage_limit_mb,
                isolation_uid=second_uid,
            )
            first_sentinel = first.data_dir / ".websitebench-isolation-sentinel"
            second_sentinel = second.data_dir / ".websitebench-isolation-sentinel"
            started = time.monotonic()
            try:
                first.start()
                healthy = first.ready(ready_path, startup_timeout)
                foreground = (
                    healthy
                    and first.process is not None
                    and first.process.poll() is None
                    and _has_process_descendant(first.process)
                )
                startup_elapsed = time.monotonic() - started
                record(
                    "platform::deploy/foreground-lifecycle",
                    foreground,
                    "FOREGROUND_PROCESS" if foreground else "DEPLOY_EXITED_EARLY",
                )
                record(
                    "platform::deploy/healthz",
                    healthy,
                    "HEALTHZ_200" if healthy else "HEALTHZ_FAILED",
                )
                record(
                    "platform::performance/startup-budget",
                    healthy and startup_elapsed <= startup_timeout,
                    f"STARTUP_SECONDS:{startup_elapsed:.6f}",
                )
                browser_smoke = False
                accessibility = False
                accessibility_violations = -1
                if healthy:
                    try:
                        from playwright.sync_api import sync_playwright

                        with sync_playwright() as playwright:
                            browser = launch_deterministic_chromium(playwright)
                            context = browser.new_context()
                            external_attempts: list[str] = []

                            def block_external(route: Any) -> None:
                                target = urllib.parse.urlsplit(route.request.url)
                                if target.scheme in {"about", "blob", "data"} or (
                                    target.hostname in {"127.0.0.1", "localhost"}
                                    and target.port == first.port
                                ):
                                    route.continue_()
                                else:
                                    external_attempts.append(
                                        target.hostname or target.scheme
                                    )
                                    route.abort("blockedbyclient")

                            context.route("**/*", block_external)
                            page = context.new_page()
                            response = page.goto(
                                f"http://127.0.0.1:{first.port}/",
                                wait_until="domcontentloaded",
                                timeout=30000,
                            )
                            browser_smoke = (
                                response is not None
                                and response.status < 500
                                and not external_attempts
                            )
                            accessibility_violations = int(
                                page.evaluate(
                                    """() => {
                                      const images = [...document.querySelectorAll('img:not([alt])')];
                                      const controls = [...document.querySelectorAll('input:not([type=hidden]),select,textarea')]
                                        .filter((node) => !node.labels?.length && !node.getAttribute('aria-label') && !node.getAttribute('aria-labelledby'));
                                      return images.length + controls.length;
                                    }"""
                                )
                            )
                            accessibility = (
                                browser_smoke and accessibility_violations == 0
                            )
                            context.close()
                            browser.close()
                    except Exception:
                        browser_smoke = False
                        accessibility = False
                record(
                    "platform::browser/chromium-smoke",
                    browser_smoke,
                    "CHROMIUM_PAGE_LOADED"
                    if browser_smoke
                    else "CHROMIUM_SMOKE_FAILED",
                )
                record(
                    "platform::accessibility/basic",
                    accessibility,
                    f"BASIC_ACCESSIBILITY_VIOLATIONS:{accessibility_violations}",
                )
                rss_kb = _process_group_rss_kb(first.process) if healthy else None
                data_bytes = _directory_bytes(first.data_dir) if healthy else 0
                cgroup_cpus = _cgroup_cpu_limit()
                affinity_cpus = _process_affinity_count(first.process)
                resource_ok = healthy
                if memory_limit_mb is not None:
                    resource_ok = (
                        resource_ok
                        and rss_kb is not None
                        and (rss_kb <= memory_limit_mb * 1024)
                    )
                if storage_limit_mb is not None:
                    resource_ok = resource_ok and (
                        data_bytes <= storage_limit_mb * 1024 * 1024
                    )
                if cpu_limit is not None:
                    resource_ok = (
                        resource_ok
                        and affinity_cpus is not None
                        and affinity_cpus <= cpu_limit
                    )
                record(
                    "platform::performance/resource-budget",
                    resource_ok,
                    f"RSS_KB:{rss_kb}:DATA_BYTES:{data_bytes}:"
                    f"AFFINITY_CPUS:{affinity_cpus}:CGROUP_CPUS:{cgroup_cpus}",
                )
                graceful = first.stop()
                record(
                    "platform::deploy/graceful-sigterm",
                    graceful,
                    "SIGTERM_EXITED" if graceful else "SIGTERM_REQUIRED_KILL",
                )
                if graceful:
                    first.start()
                restarted = graceful and first.ready(ready_path, startup_timeout)
                persisted = restarted and _sentinel_matches(
                    first_sentinel, first.mailbox_namespace
                )
                record(
                    "platform::deploy/restart-persistence",
                    persisted,
                    "SAME_DATA_DIR_RESTARTED_AND_PRESERVED"
                    if persisted
                    else "RESTART_OR_DATA_PRESERVATION_FAILED",
                )
                second.start()
                second_ready = second.ready(ready_path, startup_timeout)
                isolated = (
                    persisted
                    and second_ready
                    and first.port != second.port
                    and first.data_dir != second.data_dir
                    and first.mailbox_namespace != second.mailbox_namespace
                    and _sentinel_matches(first_sentinel, first.mailbox_namespace)
                    and _sentinel_matches(second_sentinel, second.mailbox_namespace)
                )
                record(
                    "platform::deploy/concurrent-isolation",
                    isolated,
                    "DISTINCT_PORT_DATA_NAMESPACE_RUNNING"
                    if isolated
                    else "CONCURRENT_START_FAILED",
                )
            except (OSError, subprocess.SubprocessError) as exc:
                for identifier in lifecycle_ids:
                    if identifier not in results:
                        record(
                            identifier, False, f"DEPLOY_EXCEPTION:{type(exc).__name__}"
                        )
            finally:
                first.stop()
                second.stop()
            after = tree_snapshot(candidate_root)
            first_write_violations = first.write_violations()
            second_write_violations = second.write_violations()
            write_violations = first_write_violations + second_write_violations
            network_violations = (
                first.network_violations() + second.network_violations()
            )
            first_ipc_violations = first.ipc_violations()
            second_ipc_violations = second.ipc_violations()
            ipc_violations = first_ipc_violations + second_ipc_violations
            if ipc_violations:
                record(
                    "platform::deploy/concurrent-isolation",
                    False,
                    "SHARED_IPC_ATTEMPT:"
                    f"FIRST={','.join(first_ipc_violations) or 'none'}:"
                    f"SECOND={','.join(second_ipc_violations) or 'none'}",
                )
            record(
                "platform::artifact/code-tree-unchanged",
                before == after and not write_violations,
                "TREE_HASH_STABLE_AND_WRITES_DATA_ONLY"
                if before == after and not write_violations
                else (
                    "CODE_TREE_MUTATED_OR_WRITE_OUTSIDE_DATA_DIR:"
                    f"FIRST_AUDIT={'empty' if first_write_violations == ['WRITE_AUDIT_EMPTY'] else 'present'}:"
                    f"SECOND_AUDIT={'empty' if second_write_violations == ['WRITE_AUDIT_EMPTY'] else 'present'}"
                ),
            )
            record(
                "platform::network/external-closed",
                network_closed and not network_violations and not ipc_violations,
                "RUNTIME_NETWORK_AUDIT_CLEAN"
                if network_closed and not network_violations and not ipc_violations
                else "NETWORK_POLICY_RUNTIME_EGRESS_OR_IPC_FAILED",
            )

    ordered: list[dict[str, Any]] = []
    for declaration in suite["checks"]:
        identifier = declaration["id"]
        if identifier in results:
            ordered.append(results[identifier])
        else:
            runner = declaration.get("runner")
            if trusted_runner_root is None or not isinstance(runner, str):
                ordered.append(
                    {
                        "check_id": identifier,
                        "status": "skipped",
                        "reason": "SITE_SPECIFIC_TRUSTED_RUNNER_NOT_EXECUTED",
                        "source": "trusted_check_exit_status",
                    }
                )
                continue
            try:
                runner_root = trusted_runner_root.resolve(strict=True)
                runner_path = (runner_root / runner).resolve(strict=True)
                if (
                    runner_root not in runner_path.parents
                    or not runner_path.is_file()
                    or runner_path.is_symlink()
                ):
                    raise ValueError("runner path is not a safe verifier-only file")
                command = (
                    [sys.executable, str(runner_path)]
                    if runner_path.suffix == ".py"
                    else [str(runner_path)]
                )
                environment = os.environ.copy()
                environment.update(
                    {
                        "WEBSITEBENCH_CANDIDATE_ROOT": str(candidate_root),
                        "WEBSITEBENCH_CHECK_ID": identifier,
                        "WEBSITEBENCH_CHECK_OUTPUT_DIR": str(output_root or ""),
                    }
                )
                completed = subprocess.run(
                    command,
                    cwd=runner_path.parent,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=float(declaration["timeout_sec"]),
                    check=False,
                )
                status = {0: "passed", 75: "skipped", 76: "flaky"}.get(
                    completed.returncode, "failed"
                )
                reason = f"TRUSTED_RUNNER_EXIT:{completed.returncode}"
            except subprocess.TimeoutExpired:
                status, reason = "failed", "TRUSTED_RUNNER_TIMEOUT"
            except (OSError, RuntimeError, ValueError) as exc:
                status, reason = (
                    "failed",
                    f"TRUSTED_RUNNER_INVALID:{type(exc).__name__}",
                )
            ordered.append(
                {
                    "check_id": identifier,
                    "status": status,
                    "reason": reason,
                    "source": "trusted_check_exit_status",
                }
            )
    return {
        "schema_version": CICD_RESULTS_SCHEMA,
        "checks": ordered,
        "summary": {
            "passed": sum(item["status"] == "passed" for item in ordered),
            "total": len(ordered),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="websitebench-harbor-judge-v2")
    subparsers = parser.add_subparsers(dest="command", required=True)
    score = subparsers.add_parser("score")
    score.add_argument("--task-suite", type=Path, required=True)
    score.add_argument("--task-results", type=Path, required=True)
    score.add_argument("--visual-suite", type=Path, required=True)
    score.add_argument("--visual-results", type=Path, required=True)
    score.add_argument("--cicd-suite", type=Path, required=True)
    score.add_argument("--cicd-results", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    return score_results(
        task_suite=args.task_suite,
        task_results=args.task_results,
        visual_suite=args.visual_suite,
        visual_results=args.visual_results,
        cicd_suite=args.cicd_suite,
        cicd_results=args.cicd_results,
        output=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
