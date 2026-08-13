#!/usr/bin/env python3
"""Load a sealed evaluation contract and run the deterministic v2 Judge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from websitebench.harbor.evaluate import evaluate_candidate
from websitebench.harbor.judge_v2 import _invalidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        if (
            contract.get("schema_version")
            != "websitebench.harbor.evaluation-contract.v2"
        ):
            raise ValueError("unexpected evaluation contract schema")
        paths = contract["paths"]
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
        return _invalidate(args.output, f"VERIFIER_CRASH:{type(exc).__name__}:{exc}")


if __name__ == "__main__":
    raise SystemExit(main())
