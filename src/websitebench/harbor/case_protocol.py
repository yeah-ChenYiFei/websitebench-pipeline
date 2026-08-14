"""Harbor v2 200-case validation, scoring, and atomic publication.

The public JSON schemas describe syntax.  This module owns the score-bearing
semantic invariants: exact tier cardinalities, exact result closure, dual
browser agreement, area-weighted RGB SSIM, retry identity, and receipt-last
publication.  It deliberately contains no site-specific knowledge.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker


CASE_MANIFEST_SCHEMA = "websitebench.harbor.case-manifest.v1"
CASE_RESULT_SCHEMA = "websitebench.harbor.case-result.v1"
EVAL_SCHEMA = "websitebench.harbor.eval.v2"
RECEIPT_SCHEMA = "websitebench.harbor.receipt.v1"

CASE_SCHEMA_FILE = "harbor-case-manifest.schema.json"
CASE_RESULT_SCHEMA_FILE = "harbor-case-result.schema.json"
EVAL_SCHEMA_FILE = "harbor-eval-v2.schema.json"
RECEIPT_SCHEMA_FILE = "harbor-receipt.schema.json"

EXPECTED_COUNTS: Mapping[str, int] = {
    "total": 200,
    "T1": 20,
    "T2": 165,
    "T3": 15,
    "L1": 35,
    "L2": 50,
    "L3": 80,
}
T2_WEIGHTS: Mapping[str, float] = {"L1": 4.0, "L2": 6.0, "L3": 10.0}


class CaseProtocolError(ValueError):
    """A case declaration/result violates the deterministic scoring contract."""

    def __init__(self, problems: str | Sequence[str]):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class CaseManifestSummary:
    status: str
    scorable: bool
    counts: dict[str, int]
    missing: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scorable": self.scorable,
            "counts": dict(self.counts),
            "missing": dict(self.missing),
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_path(name: str) -> Path:
    repository = Path(__file__).resolve().parents[3] / "websitebench" / "schemas" / name
    if repository.is_file():
        return repository
    bundled = Path(__file__).resolve().parents[1] / "viewer" / "_schemas" / name
    if bundled.is_file():
        return bundled
    raise FileNotFoundError(f"Harbor schema is unavailable: {name}")


def _validate_schema(value: Any, schema_name: str, label: str) -> None:
    schema = json.loads(_schema_path(schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    problems = [
        f"{label}{'.' + '.'.join(str(item) for item in error.absolute_path) if error.absolute_path else ''}: {error.message}"
        for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
    ]
    if problems:
        raise CaseProtocolError(problems)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaseProtocolError(f"{label} is unreadable: {type(exc).__name__}:{exc}") from exc
    if not isinstance(value, dict):
        raise CaseProtocolError(f"{label} must contain a JSON object")
    return value


def _count_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in EXPECTED_COUNTS}
    counts["total"] = len(cases)
    for case in cases:
        tier = case.get("tier")
        if tier in {"T1", "T2", "T3"}:
            counts[str(tier)] += 1
        if tier == "T2" and case.get("level") in {"L1", "L2", "L3"}:
            counts[str(case["level"])] += 1
    return counts


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_case_manifest_payload(
    value: Mapping[str, Any],
    *,
    allow_draft: bool = True,
    allow_sealed: bool = False,
    expected_site_id: str | None = None,
) -> CaseManifestSummary:
    """Validate one authoring/bundle case manifest and return count diagnostics."""

    _validate_schema(value, CASE_SCHEMA_FILE, "case_manifest")
    status = str(value["status"])
    if status == "draft" and not allow_draft:
        raise CaseProtocolError("case_manifest.status: draft manifests are not scorable")
    if status == "sealed" and not allow_sealed:
        raise CaseProtocolError(
            "case_manifest.status: sealed is reserved for materialized bundles"
        )
    if expected_site_id is not None and value.get("site_id") != expected_site_id:
        raise CaseProtocolError(
            f"case_manifest.site_id: expected {expected_site_id!r}, got {value.get('site_id')!r}"
        )

    cases = value["cases"]
    assert isinstance(cases, list)
    identifiers = [str(case["id"]) for case in cases]
    duplicates = _duplicates(identifiers)
    problems: list[str] = []
    if duplicates:
        problems.append(f"case_manifest.cases: duplicate ids: {duplicates}")

    task_ids = [
        str(case["task_id"])
        for case in cases
        if isinstance(case, Mapping) and isinstance(case.get("task_id"), str)
    ]
    cicd_ids = [
        str(case["cicd_check_id"])
        for case in cases
        if isinstance(case, Mapping) and isinstance(case.get("cicd_check_id"), str)
    ]
    for label, values in (("task_id", task_ids), ("cicd_check_id", cicd_ids)):
        repeated = _duplicates(values)
        if repeated:
            problems.append(f"case_manifest.cases: duplicate {label} references: {repeated}")
    for case in cases:
        if case["tier"] == "T2" and case["kind"] != "journey":
            problems.append(
                f"case_manifest.cases.{case['id']}: T2 cases must be journeys"
            )
        if case["tier"] in {"T1", "T3"} and case["kind"] == "journey":
            problems.append(
                f"case_manifest.cases.{case['id']}: journeys belong only to T2"
            )

    counts = _count_cases(cases)
    missing = {
        name: max(0, expected - counts[name])
        for name, expected in EXPECTED_COUNTS.items()
    }
    excess = {
        name: max(0, counts[name] - expected)
        for name, expected in EXPECTED_COUNTS.items()
    }
    if status in {"complete", "sealed"}:
        for name, expected in EXPECTED_COUNTS.items():
            if counts[name] != expected:
                problems.append(
                    f"case_manifest.cases.{name}: expected {expected}, got {counts[name]}"
                )
    elif any(excess.values()):
        problems.append(f"case_manifest.cases: draft exceeds fixed cardinalities: {excess}")

    if problems:
        raise CaseProtocolError(problems)
    return CaseManifestSummary(
        status=status,
        scorable=status in {"complete", "sealed"},
        counts=counts,
        missing=missing,
    )


def load_case_manifest(
    path: Path | str,
    *,
    allow_draft: bool = True,
    allow_sealed: bool = False,
    expected_site_id: str | None = None,
) -> tuple[dict[str, Any], CaseManifestSummary]:
    resolved = Path(path).resolve(strict=True)
    value = _load_json(resolved, "case manifest")
    summary = validate_case_manifest_payload(
        value,
        allow_draft=allow_draft,
        allow_sealed=allow_sealed,
        expected_site_id=expected_site_id,
    )
    return value, summary


def validate_case_references(
    manifest: Mapping[str, Any],
    *,
    task_suite: Mapping[str, Any],
    visual_suite: Mapping[str, Any],
    cicd_suite: Mapping[str, Any],
) -> None:
    """Require every case reference to resolve into the three sealed suites."""

    task_ids = {
        item.get("id") for item in task_suite.get("tasks", []) if isinstance(item, Mapping)
    }
    visual_ids = {
        item.get("id")
        for item in visual_suite.get("checkpoints", [])
        if isinstance(item, Mapping)
    }
    cicd_ids = {
        item.get("id") for item in cicd_suite.get("checks", []) if isinstance(item, Mapping)
    }
    problems: list[str] = []
    referenced_tasks: set[str] = set()
    referenced_visuals: set[str] = set()
    referenced_cicd: set[str] = set()
    for case in manifest.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        identifier = str(case.get("id"))
        task_id = case.get("task_id")
        if isinstance(task_id, str):
            referenced_tasks.add(task_id)
            if task_id not in task_ids:
                problems.append(f"case {identifier!r} references missing task {task_id!r}")
        for checkpoint_id in case.get("visual_checkpoint_ids", []):
            if isinstance(checkpoint_id, str):
                referenced_visuals.add(checkpoint_id)
                if checkpoint_id not in visual_ids:
                    problems.append(
                        f"case {identifier!r} references missing visual checkpoint {checkpoint_id!r}"
                    )
        check_id = case.get("cicd_check_id")
        if isinstance(check_id, str):
            referenced_cicd.add(check_id)
            if check_id not in cicd_ids:
                problems.append(f"case {identifier!r} references missing CI/CD check {check_id!r}")
    unreferenced = {
        "tasks": sorted(task_ids - referenced_tasks),
        "visual_checkpoints": sorted(visual_ids - referenced_visuals),
        "cicd_checks": sorted(cicd_ids - referenced_cicd),
    }
    for label, identifiers in unreferenced.items():
        if identifiers:
            problems.append(f"case manifest leaves {label} unreferenced: {identifiers}")
    if problems:
        raise CaseProtocolError(problems)


def sealed_case_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bundle-only sealed projection of a complete manifest."""

    validate_case_manifest_payload(value, allow_draft=False, allow_sealed=False)
    sealed = json.loads(canonical_json(value))
    sealed["status"] = "sealed"
    validate_case_manifest_payload(sealed, allow_draft=False, allow_sealed=True)
    return sealed


def case_shard(case_id: str) -> int:
    """Map a case to one of eight stable logical shards."""

    return int.from_bytes(hashlib.sha256(case_id.encode("utf-8")).digest()[:8], "big") % 8


def case_seed(trial_seed: int, case_id: str) -> int:
    material = f"{trial_seed}:{case_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & ((1 << 63) - 1)


def synthesize_zero_results(
    manifest: Mapping[str, Any],
    *,
    trial_id: str,
    seed: int,
    reason: str,
) -> dict[str, Any]:
    """Turn an undeployable candidate into a valid, complete 200-case zero set."""

    validate_case_manifest_payload(manifest, allow_draft=False, allow_sealed=True)
    manifest_hash = sha256_bytes(canonical_json_bytes(manifest))
    results: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        kind = str(case["kind"])
        functional = {
            "direct": False if kind in {"http", "api", "cicd"} else None,
            "playwright": False if kind == "journey" else None,
            "browser_use": False if kind == "journey" else None,
        }
        item: dict[str, Any] = {
            "case_id": case["id"],
            "tier": case["tier"],
            "kind": kind,
            "status": "failed",
            "seed": case_seed(seed, str(case["id"])),
            "attempts": 1,
            "functional": functional,
            "visuals": [],
            "failure_kind": "candidate",
            "reason": reason,
        }
        if case.get("level") is not None:
            item["level"] = case["level"]
        results.append(item)
    return {
        "schema_version": CASE_RESULT_SCHEMA,
        "status": "VALID_RUN",
        "manifest_sha256": manifest_hash,
        "trial_id": trial_id,
        "seed": seed,
        "results": results,
    }


def _functional_value(case: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    kind = str(case["kind"])
    functional = result["functional"]
    direct = functional.get("direct")
    playwright = functional.get("playwright")
    browser_use = functional.get("browser_use")
    if kind in {"http", "api", "cicd"}:
        if playwright is not None or browser_use is not None or not isinstance(direct, bool):
            raise CaseProtocolError(
                f"case {case['id']!r}: direct cases must declare only functional.direct"
            )
        return direct
    if direct is not None or not isinstance(playwright, bool) or not isinstance(browser_use, bool):
        raise CaseProtocolError(
            f"case {case['id']!r}: journeys require independent playwright and browser_use verdicts"
        )
    return playwright and browser_use


def _visual_value(case: Mapping[str, Any], result: Mapping[str, Any]) -> float:
    declared = list(case.get("visual_checkpoint_ids", []))
    visuals = result.get("visuals")
    if not isinstance(visuals, list):
        raise CaseProtocolError(f"case {case['id']!r}: visuals must be an array")
    observed = [item.get("checkpoint_id") for item in visuals if isinstance(item, Mapping)]
    if len(observed) != len(set(observed)):
        raise CaseProtocolError(f"case {case['id']!r}: duplicate visual checkpoint results")
    if set(observed) != set(declared):
        # Candidate functional failures may omit screenshots: F=0 makes J=0.
        if result.get("status") == "failed" and not visuals:
            return 1.0 if not declared else 0.0
        raise CaseProtocolError(
            f"case {case['id']!r}: visual exact set mismatch: expected={sorted(declared)} observed={sorted(observed)}"
        )
    if not visuals:
        return 1.0
    weighted = 0.0
    total_area = 0
    for visual in visuals:
        if not isinstance(visual, Mapping):
            raise CaseProtocolError(f"case {case['id']!r}: malformed visual result")
        area = visual.get("area")
        ssim = visual.get("ssim")
        if (
            not isinstance(area, int)
            or isinstance(area, bool)
            or area <= 0
            or not isinstance(ssim, (int, float))
            or isinstance(ssim, bool)
            or not math.isfinite(float(ssim))
            or not 0 <= float(ssim) <= 1
        ):
            raise CaseProtocolError(f"case {case['id']!r}: invalid visual area/SSIM")
        total_area += area
        weighted += area * float(ssim)
    return weighted / total_area


def _validate_result_payload(
    manifest: Mapping[str, Any],
    result_set: Mapping[str, Any],
    *,
    expected_manifest_sha256: str,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], bool, float, float]]:
    _validate_schema(result_set, CASE_RESULT_SCHEMA_FILE, "case_results")
    if result_set.get("status") != "VALID_RUN":
        raise CaseProtocolError(
            f"case_results.status: {result_set.get('status')}; infrastructure did not produce a valid trial"
        )
    if result_set.get("manifest_sha256") != expected_manifest_sha256:
        raise CaseProtocolError("case_results.manifest_sha256 does not bind the supplied manifest")
    seed = result_set["seed"]
    declarations = {str(case["id"]): case for case in manifest["cases"]}
    results = result_set["results"]
    observed_ids = [str(item.get("case_id")) for item in results]
    duplicates = _duplicates(observed_ids)
    if duplicates:
        raise CaseProtocolError(f"case_results.results: duplicate ids: {duplicates}")
    if set(observed_ids) != set(declarations):
        raise CaseProtocolError(
            "case_results exact set mismatch: "
            f"missing={sorted(set(declarations) - set(observed_ids))}:"
            f"extra={sorted(set(observed_ids) - set(declarations))}"
        )
    indexed = {str(item["case_id"]): item for item in results}
    scored: list[tuple[Mapping[str, Any], Mapping[str, Any], bool, float, float]] = []
    for case in manifest["cases"]:
        item = indexed[str(case["id"])]
        for field in ("tier", "kind"):
            if item.get(field) != case.get(field):
                raise CaseProtocolError(f"case {case['id']!r}: result {field} differs from manifest")
        if item.get("level") != case.get("level"):
            raise CaseProtocolError(f"case {case['id']!r}: result level differs from manifest")
        expected_seed = case_seed(int(seed), str(case["id"]))
        if item.get("seed") != expected_seed:
            raise CaseProtocolError(f"case {case['id']!r}: retry/case seed changed")
        failure_kind = item.get("failure_kind")
        attempts = item.get("attempts")
        if failure_kind == "infrastructure":
            if attempts != 2:
                raise CaseProtocolError(
                    f"case {case['id']!r}: infrastructure failure must be retried exactly once"
                )
            raise CaseProtocolError(
                f"case {case['id']!r}: infrastructure retry failed; trial is INVALID_RUN"
            )
        if failure_kind == "candidate" and attempts != 1:
            raise CaseProtocolError(
                f"case {case['id']!r}: candidate failures are not retryable"
            )
        functional = _functional_value(case, item)
        expected_status = "passed" if functional else "failed"
        if item.get("status") != expected_status:
            raise CaseProtocolError(
                f"case {case['id']!r}: status does not match functional verdicts"
            )
        visual = _visual_value(case, item)
        journey = (1.0 if functional else 0.0) * visual
        scored.append((case, item, functional, visual, journey))
    return scored


def compute_case_evaluation(
    manifest: Mapping[str, Any],
    result_set: Mapping[str, Any],
    *,
    manifest_sha256: str | None = None,
    result_sha256: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate and compute Score20 plus the deterministic tie-break tuple."""

    validate_case_manifest_payload(manifest, allow_draft=False, allow_sealed=True)
    manifest_hash = manifest_sha256 or sha256_bytes(canonical_json_bytes(manifest))
    result_hash = result_sha256 or sha256_bytes(canonical_json_bytes(result_set))
    scored = _validate_result_payload(
        manifest, result_set, expected_manifest_sha256=manifest_hash
    )

    t1 = [entry for entry in scored if entry[0]["tier"] == "T1"]
    t3 = [entry for entry in scored if entry[0]["tier"] == "T3"]
    levels = {
        level: [
            entry
            for entry in scored
            if entry[0]["tier"] == "T2" and entry[0].get("level") == level
        ]
        for level in ("L1", "L2", "L3")
    }
    rates = {
        "T1": sum(entry[2] for entry in t1) / len(t1),
        "T3": sum(entry[2] for entry in t3) / len(t3),
        **{
            level: sum(entry[4] for entry in entries) / len(entries)
            for level, entries in levels.items()
        },
    }
    score20 = sum(T2_WEIGHTS[level] * rates[level] for level in T2_WEIGHTS)
    reward = score20 / 20.0
    rounded_rates = {name: round(value, 8) for name, value in rates.items()}
    rounded_score = round(score20, 8)
    evaluation = {
        "schema_version": EVAL_SCHEMA,
        "status": "VALID_RUN",
        "scorable": True,
        "score20": rounded_score,
        "reward": round(reward, 8),
        "rates": rounded_rates,
        "tie_break": [rounded_score, rounded_rates["T1"], rounded_rates["T3"]],
        "counts": {
            "total": 200,
            "T1": {"passed": sum(entry[2] for entry in t1), "total": len(t1)},
            "T2": {"total": sum(len(entries) for entries in levels.values())},
            "T3": {"passed": sum(entry[2] for entry in t3), "total": len(t3)},
            **{
                level: {
                    "functional_passed": sum(entry[2] for entry in entries),
                    "journey_sum": round(sum(entry[4] for entry in entries), 8),
                    "total": len(entries),
                }
                for level, entries in levels.items()
            },
        },
        "manifest_sha256": manifest_hash,
        "case_results_sha256": result_hash,
    }
    _validate_schema(evaluation, EVAL_SCHEMA_FILE, "eval")
    events = [
        {
            "case_id": case["id"],
            "tier": case["tier"],
            **({"level": case["level"]} if case.get("level") is not None else {}),
            "shard": case_shard(str(case["id"])),
            "status": result["status"],
            "functional": functional,
            "visual": round(visual, 12),
            "journey": round(journey, 12),
            "seed": result["seed"],
            "attempts": result["attempts"],
            "reason": result["reason"],
        }
        for case, result, functional, visual, journey in scored
    ]
    return evaluation, events


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _junit_bytes(events: Sequence[Mapping[str, Any]]) -> bytes:
    root = ET.Element("testsuites")
    by_tier = {tier: [item for item in events if item["tier"] == tier] for tier in ("T1", "T2", "T3")}
    for tier, items in by_tier.items():
        suite = ET.SubElement(
            root,
            "testsuite",
            name=tier,
            tests=str(len(items)),
            failures=str(sum(item["status"] != "passed" for item in items)),
        )
        for item in items:
            case = ET.SubElement(suite, "testcase", name=str(item["case_id"]), classname=tier)
            if item["status"] != "passed":
                failure = ET.SubElement(case, "failure", type="candidate")
                failure.text = str(item["reason"])
    return (ET.tostring(root, encoding="unicode") + "\n").encode("utf-8")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_directory(output: Path, artifacts: Mapping[str, bytes], receipt: Mapping[str, Any]) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.run-", dir=output.parent))
    try:
        for relative, payload in artifacts.items():
            _write_bytes(stage / relative, payload)
        # Receipt is intentionally the final write in the private run directory.
        _write_bytes(stage / "receipt.json", canonical_json_bytes(receipt))
        for directory in sorted(
            {path.parent for path in stage.rglob("*") if path.is_file()},
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            _fsync_directory(directory)
        _fsync_directory(stage)
        if output.exists():
            if not output.is_dir() or any(output.iterdir()):
                raise FileExistsError(
                    f"atomic Harbor output already exists and is not empty: {output}"
                )
            output.rmdir()
        os.replace(stage, output)
        _fsync_directory(output.parent)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def publish_case_evaluation(
    output: Path | str,
    *,
    manifest: Mapping[str, Any],
    result_set: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    extra_artifacts: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Fsync a private run and publish it only after a valid receipt exists."""

    trial_id = str(result_set["trial_id"])
    artifacts: dict[str, bytes] = {
        "case-manifest.json": canonical_json_bytes(manifest),
        "case-results.json": canonical_json_bytes(result_set),
        "eval.json": canonical_json_bytes(evaluation),
        "events.jsonl": b"".join(canonical_json_bytes(item) for item in events),
        "results.junit.xml": _junit_bytes(events),
        "build.log": b"",
        "runtime.log": b"",
        "reward.txt": f"{float(evaluation['reward']):.8f}\n".encode("ascii"),
    }
    for name, payload in (extra_artifacts or {}).items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or name == "receipt.json":
            raise CaseProtocolError(f"unsafe publication artifact path: {name!r}")
        artifacts[name] = bytes(payload)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "VALID_RUN",
        "valid": True,
        "trial_id": trial_id,
        "seed": int(result_set["seed"]),
        "manifest_sha256": str(evaluation["manifest_sha256"]),
        "artifacts": {
            name: sha256_bytes(payload) for name, payload in sorted(artifacts.items())
        },
    }
    _validate_schema(receipt, RECEIPT_SCHEMA_FILE, "receipt")
    _publish_directory(Path(output), artifacts, receipt)
    return receipt


def publish_invalid_run(
    output: Path | str,
    *,
    trial_id: str,
    seed: int,
    manifest_sha256: str,
    reason: str,
) -> dict[str, Any]:
    """Publish deterministic invalid evidence without any reward artifact."""

    evaluation = {
        "schema_version": EVAL_SCHEMA,
        "status": "INVALID_RUN",
        "scorable": False,
        "score20": None,
        "reward": None,
        "rates": {name: 0.0 for name in ("T1", "T3", "L1", "L2", "L3")},
        "tie_break": [0.0, 0.0, 0.0],
        "counts": {},
        "manifest_sha256": manifest_sha256,
        "case_results_sha256": "0" * 64,
        "reason": reason,
    }
    _validate_schema(evaluation, EVAL_SCHEMA_FILE, "eval")
    artifacts = {
        "eval.json": canonical_json_bytes(evaluation),
        "events.jsonl": b"",
        "build.log": b"",
        "runtime.log": b"",
    }
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "INVALID_RUN",
        "valid": False,
        "trial_id": trial_id,
        "seed": seed,
        "manifest_sha256": manifest_sha256,
        "reason": reason,
        "artifacts": {
            name: sha256_bytes(payload) for name, payload in sorted(artifacts.items())
        },
    }
    _validate_schema(receipt, RECEIPT_SCHEMA_FILE, "receipt")
    _publish_directory(Path(output), artifacts, receipt)
    return receipt


def score_case_result_files(
    *, case_manifest: Path, case_results: Path, output: Path
) -> int:
    """CLI boundary for the active v2 score protocol."""

    manifest_hash = file_sha256(case_manifest)
    trial_id = "invalid"
    seed = 0
    try:
        manifest, _ = load_case_manifest(
            case_manifest, allow_draft=False, allow_sealed=True
        )
        result_set = _load_json(case_results, "case results")
        trial_id = str(result_set.get("trial_id") or trial_id)
        candidate_seed = result_set.get("seed")
        if isinstance(candidate_seed, int) and not isinstance(candidate_seed, bool):
            seed = candidate_seed
        evaluation, events = compute_case_evaluation(
            manifest,
            result_set,
            manifest_sha256=manifest_hash,
            result_sha256=file_sha256(case_results),
        )
        publish_case_evaluation(
            output,
            manifest=manifest,
            result_set=result_set,
            evaluation=evaluation,
            events=events,
        )
    except (CaseProtocolError, OSError, ValueError) as exc:
        publish_invalid_run(
            output,
            trial_id=trial_id,
            seed=seed,
            manifest_sha256=manifest_hash,
            reason=f"INVALID_RUN:{type(exc).__name__}:{exc}",
        )
        return 2
    return 0


__all__ = [
    "CASE_MANIFEST_SCHEMA",
    "CASE_RESULT_SCHEMA",
    "EVAL_SCHEMA",
    "RECEIPT_SCHEMA",
    "EXPECTED_COUNTS",
    "CaseManifestSummary",
    "CaseProtocolError",
    "case_seed",
    "case_shard",
    "compute_case_evaluation",
    "load_case_manifest",
    "publish_case_evaluation",
    "publish_invalid_run",
    "score_case_result_files",
    "sealed_case_manifest",
    "synthesize_zero_results",
    "validate_case_manifest_payload",
    "validate_case_references",
]
