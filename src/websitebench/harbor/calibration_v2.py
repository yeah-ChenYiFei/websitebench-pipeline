"""Execute deterministic NOP/oracle calibration for a materialized Harbor v2 bundle."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .bundle_v2 import validate_bundle
from .evaluate import evaluate_candidate
from .formal_v2 import evaluate_case_candidate


CALIBRATION_SCHEMA = "websitebench.harbor.local-calibration.v2"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"calibration input is not an object: {path}")
    return value


def _candidate_copy(seed: Path, destination: Path) -> Path:
    shutil.copytree(seed, destination, symlinks=False)
    return destination


def _apply_oracle(bundle: Path, candidate: Path, timeout: float) -> None:
    solve = bundle / "solution/solve.sh"
    environment = os.environ.copy()
    environment.update(
        {
            "WEBSITEBENCH_BUNDLE_ROOT": str(bundle),
            "WEBSITEBENCH_CANDIDATE_ROOT": str(candidate),
            "WEBSITEBENCH_SOLUTION_SITE_ROOT": str(bundle / "solution/site"),
        }
    )
    completed = subprocess.run(
        [str(solve)],
        cwd=candidate,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"oracle solve.sh exited {completed.returncode}")


def _discrete_projection(output: Path) -> dict[str, Any]:
    scorecard = _load(output / "scorecard.json")
    tasks = _load(output / "task-results.json")["tasks"]
    visuals = _load(output / "visual-results.json")["checkpoints"]
    checks = _load(output / "cicd-results.json")["checks"]
    return {
        "scorecard": scorecard,
        "tasks": [
            {
                "id": item["task_id"],
                "status": item["status"],
                "attempts": item.get("attempts"),
                "observations": item.get("observations", []),
            }
            for item in tasks
        ],
        "visual": [
            {
                "id": item["checkpoint_id"],
                "status": item["status"],
                "ssim": item["ssim"],
                "regions": item.get("regions", []),
            }
            for item in visuals
        ],
        "cicd": [{"id": item["check_id"], "status": item["status"]} for item in checks],
    }


def calibration_assertions(
    nop: Mapping[str, Any],
    oracle_first: Mapping[str, Any],
    oracle_second: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    *,
    first_projection: Mapping[str, Any],
    second_projection: Mapping[str, Any],
) -> dict[str, bool]:
    """Evaluate the exact v2 calibration thresholds without partial credit."""

    return {
        "nop_task_score_at_most_threshold": float(nop["task_score"])
        <= float(thresholds["nop_max_task_score"]),
        "oracle_task_score_100": float(oracle_first["task_score"]) == 100.0
        and float(oracle_second["task_score"]) == 100.0,
        "oracle_visual_score_at_least_threshold": float(oracle_first["visual_score"])
        >= float(thresholds["oracle_min_visual_score"])
        and float(oracle_second["visual_score"])
        >= float(thresholds["oracle_min_visual_score"]),
        "oracle_cicd_score_100": float(oracle_first["cicd_score"]) == 100.0
        and float(oracle_second["cicd_score"]) == 100.0,
        "oracle_discrete_results_repeat_exactly": first_projection
        == second_projection,
    }


def _run_candidate(
    bundle: Path,
    candidate: Path,
    output: Path,
    contract: Mapping[str, Any],
) -> int:
    tests = bundle / "tests"
    fixtures = tests / "fixtures"
    paths = contract["paths"]
    return evaluate_candidate(
        candidate_root=candidate,
        task_suite_path=tests / "fixtures/task-suite.json",
        visual_suite_path=tests / "fixtures/visual-suite.json",
        cicd_suite_path=tests / "fixtures/cicd-suite.json",
        reference_observations_path=tests / "fixtures/reference-observations.json",
        fixture_root=fixtures,
        output=output,
        browser_settings=contract["browser"],
        ready_path=contract["ready_path"],
        workers=contract["workers"],
        mailbox=contract["mailbox"],
        network_policy_path=tests / Path(paths["network_policy"]).name,
        budgets=contract["budgets"],
        reference_render_environment=contract["reference_render_environment"],
    )


def _case_projection(output: Path) -> dict[str, Any]:
    return {
        "eval": _load(output / "eval.json"),
        "results": _load(output / "case-results.json"),
        "receipt_sha256": __import__("hashlib").sha256(
            (output / "receipt.json").read_bytes()
        ).hexdigest(),
    }


def _calibrate_case_bundle(
    bundle: Path, output: Path, contract: Mapping[str, Any], calibration: Mapping[str, Any]
) -> int:
    report: dict[str, Any] = {
        "schema_version": CALIBRATION_SCHEMA,
        "status": "failed",
        "protocol": "websitebench.harbor.case-manifest.v1",
        "thresholds": calibration["thresholds"],
    }
    output.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="websitebench-case-v2-calibration-"
        ) as temporary:
            root = Path(temporary)
            candidates = {
                name: _candidate_copy(
                    bundle / "environment/seed", root / f"candidate-{name}"
                )
                for name in ("nop", "oracle-first", "oracle-second")
            }
            timeout = float(calibration["oracle_solve_timeout_sec"])
            _apply_oracle(bundle, candidates["oracle-first"], timeout)
            _apply_oracle(bundle, candidates["oracle-second"], timeout)
            run_codes = {
                name: evaluate_case_candidate(
                    candidate_root=candidate,
                    case_manifest_path=bundle / "tests/fixtures/case-manifest.json",
                    task_suite_path=bundle / "tests/fixtures/task-suite.json",
                    visual_suite_path=bundle / "tests/fixtures/visual-suite.json",
                    cicd_suite_path=bundle / "tests/fixtures/cicd-suite.json",
                    reference_observations_path=bundle
                    / "tests/fixtures/reference-observations.json",
                    fixture_root=bundle / "tests/fixtures",
                    output=output / name,
                    browser_settings=contract["browser"],
                    browser_use_settings=contract["browser_use"],
                    build_timeout_sec=float(contract["budgets"]["build_timeout_sec"]),
                    timezone=str(contract["browser"].get("timezone", "UTC")),
                    seed=0,
                )
                for name, candidate in candidates.items()
            }
        if any(code != 0 for code in run_codes.values()):
            raise RuntimeError(f"calibration evaluator invalid: {run_codes}")
        projections = {name: _case_projection(output / name) for name in run_codes}
        evals = {name: value["eval"] for name, value in projections.items()}
        thresholds = calibration["thresholds"]
        assertions = {
            "nop_score20_at_most_threshold": float(evals["nop"]["score20"])
            <= float(thresholds["nop_max_score20"]),
            "oracle_score20_20": all(
                float(evals[name]["score20"]) == float(thresholds["oracle_score20"])
                for name in ("oracle-first", "oracle-second")
            ),
            "oracle_t1_pass_rate_1": all(
                float(evals[name]["rates"]["T1"])
                == float(thresholds["oracle_t1_pass_rate"])
                for name in ("oracle-first", "oracle-second")
            ),
            "oracle_t3_pass_rate_1": all(
                float(evals[name]["rates"]["T3"])
                == float(thresholds["oracle_t3_pass_rate"])
                for name in ("oracle-first", "oracle-second")
            ),
            "oracle_results_repeat_exactly": projections["oracle-first"]["results"]
            == projections["oracle-second"]["results"],
            "oracle_eval_repeat_exactly": projections["oracle-first"]["eval"]
            == projections["oracle-second"]["eval"],
            "oracle_receipt_hash_repeat_exactly": projections["oracle-first"][
                "receipt_sha256"
            ]
            == projections["oracle-second"]["receipt_sha256"],
        }
        report.update(
            {
                "runs": {
                    name: {
                        "score20": value["score20"],
                        "reward": value["reward"],
                        "t1_pass_rate": value["rates"]["T1"],
                        "t3_pass_rate": value["rates"]["T3"],
                    }
                    for name, value in evals.items()
                },
                "assertions": assertions,
                "status": "passed" if all(assertions.values()) else "failed",
            }
        )
    except Exception as exc:
        report["reason"] = f"CALIBRATION_FAILED:{type(exc).__name__}:{exc}"
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0 if report["status"] == "passed" else 2


def calibrate_bundle(
    bundle_path: Path | str,
    output_path: Path | str,
    *,
    allow_legacy_deploy_v2: bool = False,
) -> int:
    """Run NOP once and a fresh oracle twice, then write calibration evidence."""

    bundle = Path(bundle_path).resolve(strict=True)
    output = Path(output_path).resolve()
    if output.exists():
        raise FileExistsError(f"calibration output already exists: {output}")
    validation = validate_bundle(
        bundle, allow_legacy_deploy_v2=allow_legacy_deploy_v2
    )
    contract = _load(bundle / "tests/evaluation-contract.json")
    calibration = _load(bundle / "tests/calibration-contract.json")
    if validation.get("reward_source") == "weighted_t2_journey":
        return _calibrate_case_bundle(bundle, output, contract, calibration)
    output.mkdir(parents=True)
    report: dict[str, Any] = {
        "schema_version": CALIBRATION_SCHEMA,
        "status": "failed",
        "thresholds": calibration["thresholds"],
    }
    try:
        with tempfile.TemporaryDirectory(
            prefix="websitebench-v2-calibration-"
        ) as temporary:
            root = Path(temporary)
            root.chmod(0o711)
            candidates = {
                name: _candidate_copy(
                    bundle / "environment/seed", root / f"candidate-{name}"
                )
                for name in ("nop", "oracle-first", "oracle-second")
            }
            timeout = float(calibration["oracle_solve_timeout_sec"])
            _apply_oracle(bundle, candidates["oracle-first"], timeout)
            _apply_oracle(bundle, candidates["oracle-second"], timeout)
            run_codes = {
                name: _run_candidate(bundle, candidate, output / name, contract)
                for name, candidate in candidates.items()
            }
        if any(code != 0 for code in run_codes.values()):
            raise RuntimeError(f"calibration evaluator invalid: {run_codes}")
        scorecards = {
            name: _load(output / name / "scorecard.json") for name in run_codes
        }
        first_projection = _discrete_projection(output / "oracle-first")
        second_projection = _discrete_projection(output / "oracle-second")
        assertions = calibration_assertions(
            scorecards["nop"],
            scorecards["oracle-first"],
            scorecards["oracle-second"],
            calibration["thresholds"],
            first_projection=first_projection,
            second_projection=second_projection,
        )
        report.update(
            {
                "runs": {
                    name: {
                        "task_score": value["task_score"],
                        "visual_score": value["visual_score"],
                        "cicd_score": value["cicd_score"],
                        "reward": value["reward"],
                    }
                    for name, value in scorecards.items()
                },
                "assertions": assertions,
                "status": "passed" if all(assertions.values()) else "failed",
            }
        )
    except Exception as exc:
        report["reason"] = f"CALIBRATION_FAILED:{type(exc).__name__}:{exc}"
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0 if report["status"] == "passed" else 2
