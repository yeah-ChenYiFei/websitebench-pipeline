"""CLI for deterministic offline-clone workflow checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .acquisition import acquire_source
from .errors import WorkflowError
from .fullstack import (
    calibrate_visual_stability,
    scaffold_semantic_selection,
    validate_fullstack_candidate,
    validate_semantic_selection,
    validate_source_acquisition_report,
)
from .payment_scope import validate_payment_scope
from .rights import validate_rights_metadata


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _add_repository_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=Path("."))


def _check_acquisition(args: argparse.Namespace) -> int:
    result = validate_source_acquisition_report(args.repo_root, args.report)
    _emit(result)
    return 0 if result["status"] == "passed" else 4


def _acquire_source(args: argparse.Namespace) -> int:
    result = acquire_source(
        args.repo_root,
        args.spec,
        args.out_dir,
        args.report,
        browser_channel=args.browser_channel,
        executable_path=args.executable_path,
        headed=args.headed,
    )
    _emit(result)
    return 0 if result["status"] == "complete" else 4


def _check_semantics(args: argparse.Namespace) -> int:
    result = validate_semantic_selection(args.repo_root, args.selection)
    _emit(result)
    return 0 if result["status"] == "passed" else 4


def _scaffold_semantics(args: argparse.Namespace) -> int:
    result = scaffold_semantic_selection(args.repo_root, args.site, args.out)
    _emit(result)
    return 0


def _check_payment_scope(args: argparse.Namespace) -> int:
    result = validate_payment_scope(args.repo_root, args.proposal)
    _emit(result)
    return 0 if result["status"] == "passed" else 4


def _check_fullstack(args: argparse.Namespace) -> int:
    _emit(validate_fullstack_candidate(args.repo_root, args.candidate))
    return 0


def _calibrate_visual(args: argparse.Namespace) -> int:
    _emit(calibrate_visual_stability(args.repo_root, args.spec, args.out))
    return 0


def _check_rights_metadata(args: argparse.Namespace) -> int:
    result = validate_rights_metadata(
        args.disposition,
        repository_root=args.repo_root,
        expected_site_id=args.site,
    )
    _emit(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="websitebench-workflow",
        description="Run deterministic evidence checks for an offline clone.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire = subparsers.add_parser(
        "acquire-source",
        help="capture one configuration-scoped anonymous GET-only source matrix",
    )
    _add_repository_root(acquire)
    acquire.add_argument("--spec", type=Path, required=True)
    acquire.add_argument("--out-dir", type=Path, required=True)
    acquire.add_argument("--report", type=Path, required=True)
    acquire.add_argument("--browser-channel", default="chrome")
    acquire.add_argument("--executable-path")
    acquire.add_argument("--headed", action="store_true")
    acquire.set_defaults(function=_acquire_source)

    acquisition = subparsers.add_parser(
        "check-acquisition",
        help="validate one provider-neutral source/media closure report",
    )
    _add_repository_root(acquisition)
    acquisition.add_argument("--report", type=Path, required=True)
    acquisition.set_defaults(function=_check_acquisition)

    semantic = subparsers.add_parser(
        "check-semantics",
        help="validate an automatically resolved semantic selection",
    )
    _add_repository_root(semantic)
    semantic.add_argument("--selection", type=Path, required=True)
    semantic.set_defaults(function=_check_semantics)

    semantic_scaffold = subparsers.add_parser(
        "scaffold-semantics",
        help="create a fidelity-first automatic selection from the backend plan",
    )
    _add_repository_root(semantic_scaffold)
    semantic_scaffold.add_argument("--site", required=True)
    semantic_scaffold.add_argument("--out", type=Path)
    semantic_scaffold.set_defaults(function=_scaffold_semantics)

    payment_scope = subparsers.add_parser(
        "check-payment-scope",
        help="validate a hash-bound machine payment scope",
    )
    _add_repository_root(payment_scope)
    payment_scope.add_argument("--proposal", type=Path, required=True)
    payment_scope.set_defaults(function=_check_payment_scope)

    fullstack = subparsers.add_parser(
        "check-fullstack",
        help="validate a full-stack candidate",
    )
    _add_repository_root(fullstack)
    fullstack.add_argument("--candidate", type=Path, required=True)
    fullstack.set_defaults(function=_check_fullstack)

    calibration = subparsers.add_parser(
        "calibrate-visual",
        help="derive region thresholds from three stable source captures",
    )
    _add_repository_root(calibration)
    calibration.add_argument("--spec", type=Path, required=True)
    calibration.add_argument("--out", type=Path, required=True)
    calibration.set_defaults(function=_calibrate_visual)

    rights = subparsers.add_parser(
        "check-rights-metadata",
        help="validate optional redistribution-rights metadata",
    )
    _add_repository_root(rights)
    rights.add_argument("--disposition", type=Path, required=True)
    rights.add_argument("--site")
    rights.set_defaults(function=_check_rights_metadata)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.function(args))
    except (OSError, ValueError, WorkflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
