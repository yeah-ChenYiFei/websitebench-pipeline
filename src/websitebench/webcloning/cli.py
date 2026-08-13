"""CLI for WebCloning trace, exploration, replay, and diff artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .analysis import build_diff, build_replay
from .contracts import WebCloningError, load_json, require_valid, write_json_atomic
from .exploration import (
    build_exploration_bundle,
    build_exploration_coverage,
    import_clawbench_run,
    select_clawbench_runs,
)
from .trace import normalize_trace


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _build(args: argparse.Namespace, builder: Callable[..., dict[str, Any]], **kwargs: Any) -> int:
    value = builder(**kwargs)
    validation_root = getattr(args, "repository_root", None) or getattr(
        args, "artifact_root", None
    )
    require_valid(value, location="<generated>", root=validation_root)
    write_json_atomic(args.output, value)
    _emit(
        {
            "status": value.get("status", "written"),
            "schema_version": value["schema_version"],
            "output": str(args.output),
        }
    )
    return 0


def _normalize(args: argparse.Namespace) -> int:
    return _build(
        args,
        normalize_trace,
        raw_path=args.raw,
        task_path=args.task,
        run_manifest_path=args.run,
        artifact_root=args.artifact_root,
        site_id=args.site_id,
        environment=args.environment,
        suite=args.suite,
    )


def _select_clawbench_runs(args: argparse.Namespace) -> int:
    value = select_clawbench_runs(runs_root=args.runs_root, task_id=args.task_id)
    if args.output is not None:
        write_json_atomic(args.output, value)
    _emit(value)
    return 0


def _import_clawbench_run(args: argparse.Namespace) -> int:
    imported = import_clawbench_run(
        run_dir=args.run_dir,
        task_path=args.task,
        artifact_root=args.artifact_root,
        output_dir=args.output_dir,
        site_id=args.site_id,
        suite=args.suite,
        dataset_id=args.dataset_id,
        dataset_revision=args.dataset_revision,
    )
    trace = imported["trace"]
    write_json_atomic(args.output, trace)
    _emit(
        {
            "status": trace["status"],
            "schema_version": trace["schema_version"],
            "output": str(args.output),
            "selection_class": imported["selection_class"],
            "interaction_transcript": str(imported["transcript_path"]),
            "import_provenance": str(imported["provenance_path"]),
            "raw_retained": False,
        }
    )
    return 0


def _exploration_bundle(args: argparse.Namespace) -> int:
    return _build(
        args,
        build_exploration_bundle,
        repository_root=args.repository_root,
        spec_path=args.spec,
    )


def _exploration_coverage(args: argparse.Namespace) -> int:
    return _build(
        args,
        build_exploration_coverage,
        repository_root=args.repository_root,
        spec_path=args.spec,
    )


def _replay(args: argparse.Namespace) -> int:
    return _build(
        args,
        build_replay,
        repository_root=args.repository_root,
        source_path=args.source,
        clone_path=args.clone,
        candidate_path=args.candidate,
        semantic_selection_path=args.semantic_selection,
        runtime_identity_path=args.runtime_identity,
        reset_evidence_path=args.reset_evidence,
        mapping_path=args.mapping,
    )


def _diff(args: argparse.Namespace) -> int:
    return _build(
        args,
        build_diff,
        repository_root=args.repository_root,
        replay_path=args.replay,
        findings_path=args.findings,
    )


def _validate(args: argparse.Namespace) -> int:
    value = load_json(args.path)
    require_valid(
        value,
        location=str(args.path),
        root=args.repository_root if args.verify_repository_artifacts else None,
    )
    _emit(
        {
            "status": "valid",
            "schema_version": value["schema_version"],
            "path": str(args.path),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="websitebench-webcloning")
    sub = parser.add_subparsers(dest="command", required=True)

    normalize = sub.add_parser("normalize-trace")
    normalize.add_argument("--raw", type=Path, required=True)
    normalize.add_argument("--task", type=Path, required=True)
    normalize.add_argument("--run", type=Path, required=True)
    normalize.add_argument("--artifact-root", type=Path, required=True)
    normalize.add_argument("--site-id", required=True)
    normalize.add_argument("--environment", choices=("source", "clone"), required=True)
    normalize.add_argument("--suite", required=True)
    normalize.add_argument("--output", type=Path, required=True)
    normalize.set_defaults(function=_normalize)

    select_runs = sub.add_parser("select-clawbench-runs")
    select_runs.add_argument("--runs-root", type=Path, required=True)
    select_runs.add_argument("--task-id", type=int, required=True)
    select_runs.add_argument("--output", type=Path)
    select_runs.set_defaults(function=_select_clawbench_runs)

    import_run = sub.add_parser("import-clawbench-run")
    import_run.add_argument("--run-dir", type=Path, required=True)
    import_run.add_argument("--task", type=Path, required=True)
    import_run.add_argument("--artifact-root", type=Path, required=True)
    import_run.add_argument("--output-dir", type=Path, required=True)
    import_run.add_argument("--site-id", required=True)
    import_run.add_argument("--suite", required=True)
    import_run.add_argument("--dataset-id")
    import_run.add_argument("--dataset-revision", default="main")
    import_run.add_argument("--output", type=Path, required=True)
    import_run.set_defaults(function=_import_clawbench_run)

    bundle = sub.add_parser("build-exploration-bundle")
    bundle.add_argument("--repository-root", type=Path, default=Path("."))
    bundle.add_argument("--spec", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    bundle.set_defaults(function=_exploration_bundle)

    coverage = sub.add_parser("build-exploration-coverage")
    coverage.add_argument("--repository-root", type=Path, default=Path("."))
    coverage.add_argument("--spec", type=Path, required=True)
    coverage.add_argument("--output", type=Path, required=True)
    coverage.set_defaults(function=_exploration_coverage)

    replay = sub.add_parser("build-replay")
    replay.add_argument("--repository-root", type=Path, default=Path("."))
    replay.add_argument("--source", type=Path, required=True)
    replay.add_argument("--clone", type=Path, required=True)
    replay.add_argument("--candidate", type=Path, required=True)
    replay.add_argument("--semantic-selection", type=Path, required=True)
    replay.add_argument("--runtime-identity", type=Path, required=True)
    replay.add_argument("--reset-evidence", type=Path, required=True)
    replay.add_argument("--mapping", type=Path)
    replay.add_argument("--output", type=Path, required=True)
    replay.set_defaults(function=_replay)

    diff = sub.add_parser("build-diff")
    diff.add_argument("--repository-root", type=Path, default=Path("."))
    diff.add_argument("--replay", type=Path, required=True)
    diff.add_argument("--findings", type=Path)
    diff.add_argument("--output", type=Path, required=True)
    diff.set_defaults(function=_diff)

    validate = sub.add_parser("validate")
    validate.add_argument("path", type=Path)
    validate.add_argument("--repository-root", type=Path, default=Path("."))
    validate.add_argument("--verify-repository-artifacts", action="store_true")
    validate.set_defaults(function=_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.function(args))
    except (FileNotFoundError, OSError, WebCloningError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
