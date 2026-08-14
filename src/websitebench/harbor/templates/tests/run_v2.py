#!/usr/bin/env python3
"""Load a sealed evaluation contract and run the deterministic v2 Judge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from websitebench.harbor.case_protocol import file_sha256, publish_invalid_run
from websitebench.harbor.evaluate import evaluate_candidate
from websitebench.harbor.formal_v2 import evaluate_case_candidate
from websitebench.harbor.judge_v2 import _invalidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    active_case_manifest: Path | None = None
    try:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        if (
            contract.get("schema_version")
            != "websitebench.harbor.evaluation-contract.v2"
        ):
            raise ValueError("unexpected evaluation contract schema")
        paths = contract["paths"]
        if (
            contract.get("deployment_abi")
            == "websitebench.harbor.compile-executable.v1"
        ):
            active_case_manifest = Path(paths["case_manifest"])
            if contract.get("logical_shards") != 8 or contract.get(
                "formal_browsers"
            ) != ["playwright", "browser-use"]:
                raise ValueError("active case contract has invalid shard/browser ABI")
            return evaluate_case_candidate(
                candidate_root=args.candidate,
                case_manifest_path=Path(paths["case_manifest"]),
                task_suite_path=Path(paths["task_suite"]),
                visual_suite_path=Path(paths["visual_suite"]),
                cicd_suite_path=Path(paths["cicd_suite"]),
                reference_observations_path=Path(paths["reference_observations"]),
                fixture_root=Path(paths["fixtures"]),
                output=args.output,
                browser_settings=contract["browser"],
                browser_use_settings=contract["browser_use"],
                build_timeout_sec=float(
                    contract["budgets"].get("build_timeout_sec", 900)
                ),
                timezone=str(contract["browser"].get("timezone", "UTC")),
                seed=int(os.environ.get("SEED", "0")),
            )
        return evaluate_candidate(
            candidate_root=args.candidate,
            task_suite_path=Path(paths["task_suite"]),
            visual_suite_path=Path(paths["visual_suite"]),
            cicd_suite_path=Path(paths["cicd_suite"]),
            reference_observations_path=Path(paths["reference_observations"]),
            fixture_root=Path(paths["fixtures"]),
            output=args.output,
            browser_settings=contract["browser"],
            ready_path=contract["ready_path"],
            workers=contract["workers"],
            mailbox=contract["mailbox"],
            network_policy_path=Path(paths["network_policy"]),
            budgets=contract["budgets"],
            reference_render_environment=contract["reference_render_environment"],
        )
    except Exception as exc:
        if active_case_manifest is not None:
            try:
                manifest_hash = file_sha256(active_case_manifest)
            except OSError:
                manifest_hash = "0" * 64
            seed = int(os.environ.get("SEED", "0"))
            publish_invalid_run(
                args.output,
                trial_id=hashlib.sha256(
                    f"{manifest_hash}:{seed}".encode("ascii")
                ).hexdigest()[:24],
                seed=seed,
                manifest_sha256=manifest_hash,
                reason=f"VERIFIER_CRASH:{type(exc).__name__}:{exc}",
            )
            return 2
        return _invalidate(args.output, f"VERIFIER_CRASH:{type(exc).__name__}:{exc}")


if __name__ == "__main__":
    raise SystemExit(main())
