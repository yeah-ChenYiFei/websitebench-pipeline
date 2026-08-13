"""Command-line entrypoint for WebsiteBench local task replay adapters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .edx import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_API_TYPE,
    DEFAULT_BASE_URL,
    DEFAULT_GATEWAY_IMAGE,
    DEFAULT_MODEL,
    DEFAULT_TASK_IDS,
    ModelSettings,
    ReplayError,
    default_clone_root,
    replay_edx_tasks,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="websitebench-task-replay",
        description=(
            "Run immutable external browser tasks against an isolated WebsiteBench "
            "offline clone. This is a local compatibility check, not a benchmark score."
        ),
    )
    subparsers = parser.add_subparsers(dest="site", required=True)
    edx = subparsers.add_parser("edx", help="replay the retained edX enrollment tasks")
    edx.add_argument("--upstream-root", type=Path, required=True)
    edx.add_argument("--task-specs-root", type=Path, required=True)
    edx.add_argument("--clone-root", type=Path, default=default_clone_root())
    edx.add_argument(
        "--task-id",
        action="append",
        choices=DEFAULT_TASK_IDS,
        help="repeat to select a subset; defaults to all retained edX tasks",
    )
    edx.add_argument("--model", default=DEFAULT_MODEL)
    edx.add_argument("--base-url", default=DEFAULT_BASE_URL)
    edx.add_argument("--api-type", default=DEFAULT_API_TYPE)
    edx.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    edx.add_argument("--docker-bin")
    edx.add_argument("--gateway-image", default=DEFAULT_GATEWAY_IMAGE)
    edx.add_argument("--no-build", action="store_true")
    edx.add_argument("--dry-run", action="store_true")
    edx.add_argument(
        "--retain-artifacts",
        action="store_true",
        help="retain ephemeral raw agent output outside the repository for human inspection",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.site != "edx":  # pragma: no cover - argparse owns this branch.
        raise AssertionError(f"unsupported site: {args.site}")
    settings = ModelSettings(
        model=args.model,
        base_url=args.base_url,
        api_type=args.api_type,
        api_key_env=args.api_key_env,
    )
    try:
        summary = replay_edx_tasks(
            upstream_root=args.upstream_root,
            task_specs_root=args.task_specs_root,
            clone_root=args.clone_root,
            task_ids=tuple(args.task_id or DEFAULT_TASK_IDS),
            settings=settings,
            docker_binary=args.docker_bin,
            gateway_image=args.gateway_image,
            no_build=args.no_build,
            dry_run=args.dry_run,
            retain_artifacts=args.retain_artifacts,
        )
    except ReplayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if args.dry_run or summary.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
