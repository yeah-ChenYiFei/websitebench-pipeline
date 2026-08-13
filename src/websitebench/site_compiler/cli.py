"""Command line interface for declarative site compilation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .compile import (
    TARGETS,
    CompilerWorkspace,
    compile_profile,
    write_compilation,
)
from .diagnostics import SiteCompilerError
from .materialize import check_materialization, materialize_compilation


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _compile_args(
    parser: argparse.ArgumentParser,
    *,
    allow_profiles_root: bool = False,
) -> None:
    parser.add_argument("--inventory", type=Path, required=True)
    profiles = parser.add_mutually_exclusive_group(required=True)
    profiles.add_argument("--profile", type=Path)
    if allow_profiles_root:
        profiles.add_argument(
            "--profiles-root",
            type=Path,
            help="compile/check every */site.json profile with one loaded workspace",
        )
    parser.add_argument("--packs-root", type=Path, required=True)
    parser.add_argument("--target", choices=TARGETS, default="release")


def _profile_paths(args: argparse.Namespace) -> list[Path]:
    if args.profile is not None:
        return [args.profile]
    root = args.profiles_root.resolve()
    paths = sorted(root.glob("*/site.json"), key=lambda path: path.as_posix())
    if not paths:
        raise SiteCompilerError(f"no */site.json profiles found in {root}")
    return paths


def _workspace(args: argparse.Namespace) -> CompilerWorkspace:
    return CompilerWorkspace.load(
        inventory_path=args.inventory,
        packs_root=args.packs_root,
    )


def _validate_materialization_args(
    args: argparse.Namespace,
    *,
    command: str,
) -> None:
    site_dir = getattr(args, "site_dir", None)
    if site_dir is not None:
        if args.profile is None:
            raise SiteCompilerError(
                "--site-dir requires exactly one --profile; batch "
                "--profiles-root materialization is forbidden"
            )
        if args.target != "scope":
            raise SiteCompilerError(
                "--site-dir requires --target scope"
            )
    if command == "compile" and args.out is None and site_dir is None:
        raise SiteCompilerError("compile requires --out, --site-dir, or both")


def _compile(args: argparse.Namespace) -> int:
    _validate_materialization_args(args, command="compile")
    workspace = _workspace(args)
    profile_paths = _profile_paths(args)
    compiled = [
        workspace.compile(profile_path=path, target=args.target)
        for path in profile_paths
    ]
    materialized = (
        materialize_compilation(
            compiled[0],
            args.site_dir,
            stage="scope",
        )
        if args.site_dir is not None
        else None
    )
    # Materialization is the stricter operation: blockers, existing targets,
    # and packet boundaries must fail before an optional standalone --out tree
    # is written.
    results = (
        [write_compilation(result, output_dir=args.out) for result in compiled]
        if args.out is not None
        else []
    )
    if materialized is not None and not results:
        _emit(materialized)
        return 0
    if materialized is not None:
        _emit(
            {
                "status": "compiled-and-materialized",
                "compiled": results[0],
                "materialized": materialized,
            }
        )
        return 0
    _emit(
        results[0]
        if len(results) == 1
        else {
            "status": "written",
            "profile_count": len(results),
            "blocked_profile_count": sum(
                bool(result.plan["site_ir"]["blockers"]) for result in compiled
            ),
            "output_dir": str(args.out.resolve()),
        }
    )
    return 0


def _check(args: argparse.Namespace) -> int:
    _validate_materialization_args(args, command="check")
    workspace = _workspace(args)
    results = [
        workspace.compile(profile_path=path, target=args.target)
        for path in _profile_paths(args)
    ]
    if args.site_dir is not None:
        materialization = check_materialization(
            results[0],
            args.site_dir,
        )
        if args.out is None:
            _emit(materialization)
        else:
            compiled = write_compilation(
                results[0],
                output_dir=args.out,
                check=True,
            )
            _emit(
                {
                    "status": "current",
                    "compiled": compiled,
                    "materialization": materialization,
                }
            )
        return 0
    if args.out is None and len(results) == 1:
        result = results[0]
        _emit(
            {
                "status": "valid",
                "site_id": result.plan["site_ir"]["site"]["site_id"],
                "blockers": result.plan["site_ir"]["blockers"],
            }
        )
    elif args.out is None:
        _emit(
            {
                "status": "valid",
                "profile_count": len(results),
                "blocked_profile_count": sum(
                    bool(result.plan["site_ir"]["blockers"]) for result in results
                ),
                "unique_site_count": len(
                    {
                        result.plan["site_ir"]["site"]["site_id"]
                        for result in results
                    }
                ),
            }
        )
    else:
        emitted = [
            write_compilation(result, output_dir=args.out, check=True)
            for result in results
        ]
        _emit(
            emitted[0]
            if len(emitted) == 1
            else {
                "status": "current",
                "profile_count": len(emitted),
                "output_dir": str(args.out.resolve()),
            }
        )
    return 0


def _explain(args: argparse.Namespace) -> int:
    result = compile_profile(
        inventory_path=args.inventory,
        profile_path=args.profile,
        packs_root=args.packs_root,
        target=args.target,
    )
    _emit(result.explanation)
    return 0


def _materialize(args: argparse.Namespace) -> int:
    """Compile one profile at scope stage and create its workspace atomically."""

    args.target = "scope"
    args.profiles_root = None
    return _compile(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="websitebench-site")
    subparsers = parser.add_subparsers(dest="command", required=True)
    compile_command = subparsers.add_parser(
        "compile",
        help="compile one profile to deterministic plan and explanation files",
    )
    _compile_args(compile_command, allow_profiles_root=True)
    compile_command.add_argument("--out", type=Path)
    compile_command.add_argument(
        "--site-dir",
        type=Path,
        help="atomically create one machine-resolved scope workspace; target must not exist",
    )
    compile_command.set_defaults(function=_compile)

    check = subparsers.add_parser(
        "check",
        help="validate inventory/profile/packs and optionally assert emitted files",
    )
    _compile_args(check, allow_profiles_root=True)
    check.add_argument("--out", type=Path)
    check.add_argument(
        "--site-dir",
        type=Path,
        help=(
            "check one materialized scope draft against --profile; "
            "requires --target scope"
        ),
    )
    check.set_defaults(function=_check)

    explain = subparsers.add_parser(
        "explain",
        help="explain pack provenance, blockers, and machine invalidation stages",
    )
    _compile_args(explain)
    explain.set_defaults(function=_explain)

    materialize = subparsers.add_parser(
        "materialize",
        help="compile one profile and atomically create its scope workspace",
    )
    materialize.add_argument("--inventory", type=Path, required=True)
    materialize.add_argument("--profile", type=Path, required=True)
    materialize.add_argument("--packs-root", type=Path, required=True)
    materialize.add_argument("--site-dir", type=Path, required=True)
    materialize.add_argument(
        "--out",
        type=Path,
        help="also write the deterministic compiled plan and explanation",
    )
    materialize.set_defaults(function=_materialize)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.function(args))
    except (OSError, SiteCompilerError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
