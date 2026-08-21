"""CLI for the manifest-driven offline-clone harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .backend_scaffold import scaffold_site_backend
from .browser_tools import run_browser_exploration
from .comparison_tools import compare_functional_reports, compare_visual_spec
from .contribution import contribution_report, initialize_contribution
from .diagnostics import DIAGNOSTIC_SECTIONS, verify as run_diagnostics
from .frontend_spec import extract_frontend_spec
from .manifest import (
    ManifestValidationError,
    initialize_site,
    load_manifest,
)
from .report import full_report, status_report
from .semantic_tools import run_backend_semantic_suite
from .toolbox import ToolboxError, tool_catalog


def _emit(value: dict[str, Any], output: Path | None = None) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if output is None:
        print(payload, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    print(output)


def _init(args: argparse.Namespace) -> int:
    manifest = initialize_site(
        args.site_dir,
        site_id=args.site_id,
        display_name=args.display_name,
        source_url=args.source_url,
    )
    _emit(
        {
            "status": "initialized",
            "site_id": manifest.data["site_id"],
            "manifest": str(manifest.path),
            "source_origins": manifest.data["source"]["origins"],
        }
    )
    return 0


def _status(args: argparse.Namespace) -> int:
    _emit(status_report(load_manifest(args.site)))
    return 0


def _verify(args: argparse.Namespace) -> int:
    sections = tuple(args.section) if args.section else DIAGNOSTIC_SECTIONS
    report = run_diagnostics(args.site, sections)
    _emit(report, args.out)
    return 2 if report["diagnostic_status"] == "incomplete" else 0


def _report(args: argparse.Namespace) -> int:
    _emit(full_report(load_manifest(args.site)), args.out)
    return 0


def _backend_scaffold(args: argparse.Namespace) -> int:
    _emit(scaffold_site_backend(args.site))
    return 0


def _contribution_init(args: argparse.Namespace) -> int:
    _emit(
        initialize_contribution(
            args.repo,
            site_id=args.site_id,
            display_name=args.display_name,
            source_urls=args.source_url,
            backend_profile=args.backend_profile,
        )
    )
    return 0


def _contribution_report(args: argparse.Namespace) -> int:
    report = contribution_report(
        args.site,
        output=args.out,
        bundle_output=args.bundle_out,
    )
    _emit(
        {
            "schema_version": report["schema_version"],
            "site_id": report["site_id"],
            "diagnostic_status": report["diagnostic"]["diagnostic_status"],
            "report": str(args.out),
            "bundle": str(args.bundle_out),
        }
    )
    return 2 if report["diagnostic"]["diagnostic_status"] == "incomplete" else 0


def _harbor_scaffold(args: argparse.Namespace) -> int:
    """Alias for `websitebench-harbor derive-from-clone`.

    The import is function-local on purpose: the package dependency already runs
    harbor -> offline_clone, so importing harbor at module scope here would
    close a cycle.
    """

    from ..harbor.derive import run_derive

    site = args.site if args.site.is_file() else args.site / "clone.yaml"
    _emit(
        run_derive(
            clone_manifest=site,
            force=args.force,
        )
    )
    return 0


def _tool_list(args: argparse.Namespace) -> int:
    _emit(tool_catalog(), args.out)
    return 0


def _tool_explore(args: argparse.Namespace) -> int:
    result = run_browser_exploration(
        spec_path=args.spec,
        base_url=args.base_url,
        environment=args.environment,
        output_path=args.out,
        artifacts_dir=args.artifacts_dir,
        storage_state=args.storage_state,
        headed=args.headed,
        allow_source_mutations=args.allow_source_mutations,
    )
    _emit(
        {
            "status": result["status"],
            "schema_version": result["schema_version"],
            "output": str(args.out),
            "summary": result["summary"],
        }
    )
    return 0 if result["status"] == "passed" else 1


def _tool_compare_functional(args: argparse.Namespace) -> int:
    result = compare_functional_reports(
        source_path=args.source,
        candidate_path=args.candidate,
        output_path=args.out,
    )
    _emit(
        {
            "status": result["status"],
            "schema_version": result["schema_version"],
            "output": str(args.out),
            "counts": result["counts"],
        }
    )
    return 0 if result["status"] == "passed" else 1


def _tool_compare_visual(args: argparse.Namespace) -> int:
    result = compare_visual_spec(
        spec_path=args.spec,
        output_path=args.out,
        heatmap_dir=args.heatmap_dir,
    )
    _emit(
        {
            "status": result["status"],
            "schema_version": result["schema_version"],
            "output": str(args.out),
            "counts": result["counts"],
        }
    )
    return 0 if result["status"] == "passed" else 1


def _tool_test_backend(args: argparse.Namespace) -> int:
    result = run_backend_semantic_suite(
        spec_path=args.spec,
        base_url=args.base_url,
        output_path=args.out,
        allow_non_loopback=args.allow_non_loopback,
    )
    _emit(
        {
            "status": result["status"],
            "schema_version": result["schema_version"],
            "output": str(args.out),
            "counts": result["counts"],
        }
    )
    return 0 if result["status"] == "passed" else 1


def _tool_frontend_spec(args: argparse.Namespace) -> int:
    try:
        raw_width, raw_height = (part.strip() for part in args.viewport.split(","))
        viewport = (int(raw_width), int(raw_height))
    except (TypeError, ValueError) as exc:
        raise ToolboxError(f"invalid --viewport {args.viewport!r}") from exc
    result = extract_frontend_spec(
        target_url=args.url,
        allowed_origins=args.allowed_origin,
        viewport=viewport,
        environment=args.environment,
        output_path=args.out,
        timeout_ms=args.timeout_ms,
    )
    _emit(
        {
            "status": "passed",
            "schema_version": result["schema_version"],
            "output": str(args.out),
            "summary": result["summary"],
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="websitebench-offline-clone")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init", help="create a new offline-clone site skeleton"
    )
    init.add_argument("--site-dir", type=Path, required=True)
    init.add_argument("--site-id", required=True)
    init.add_argument("--display-name", required=True)
    init.add_argument(
        "--source-url",
        action="append",
        required=True,
        help="source origin URL; repeat for one platform spanning multiple first-party origins",
    )
    init.set_defaults(function=_init)

    for name, function in (("status", _status), ("report", _report)):
        command = subparsers.add_parser(name)
        command.add_argument("--site", type=Path, required=True)
        if name == "report":
            command.add_argument("--out", type=Path)
        command.set_defaults(function=function)

    verify = subparsers.add_parser(
        "verify",
        help="run diagnostic-only static and live sections against one clone",
    )
    verify.add_argument("--site", type=Path, required=True)
    verify.add_argument(
        "--section",
        choices=DIAGNOSTIC_SECTIONS,
        action="append",
        help="run only this diagnostic section; repeatable. Default: both.",
    )
    verify.add_argument("--out", type=Path)
    verify.set_defaults(function=_verify)

    contribution = subparsers.add_parser(
        "contribution", help="initialize and package an offline-clone contribution"
    )
    contribution_commands = contribution.add_subparsers(
        dest="contribution_command", required=True
    )
    contribution_init = contribution_commands.add_parser(
        "init", help="create one conservative, non-deployable contribution scaffold"
    )
    contribution_init.add_argument("--repo", type=Path, required=True)
    contribution_init.add_argument("--site-id", required=True)
    contribution_init.add_argument("--display-name", required=True)
    contribution_init.add_argument("--source-url", action="append", required=True)
    contribution_init.add_argument(
        "--backend-profile", choices=("full", "none"), default="full"
    )
    contribution_init.set_defaults(function=_contribution_init)
    contribution_report_parser = contribution_commands.add_parser(
        "report", help="write a diagnostic summary and stable handoff bundle"
    )
    contribution_report_parser.add_argument("--site", type=Path, required=True)
    contribution_report_parser.add_argument("--out", type=Path, required=True)
    contribution_report_parser.add_argument("--bundle-out", type=Path, required=True)
    contribution_report_parser.set_defaults(function=_contribution_report)

    backend = subparsers.add_parser(
        "backend", help="attach the shared backend runtime to one clone"
    )
    backend_commands = backend.add_subparsers(dest="backend_command", required=True)
    scaffold = backend_commands.add_parser(
        "scaffold", help="vendor the generic site backend and create runtime.json"
    )
    scaffold.add_argument("--site", type=Path, required=True)
    scaffold.set_defaults(function=_backend_scaffold)

    harbor = subparsers.add_parser(
        "harbor",
        help="derive the Harbor interaction contract from this clone's captured "
        "artifacts",
    )
    harbor_commands = harbor.add_subparsers(dest="harbor_command", required=True)
    harbor_scaffold = harbor_commands.add_parser(
        "scaffold",
        help="alias for `websitebench-harbor derive-from-clone`",
    )
    harbor_scaffold.add_argument("--site", type=Path, required=True)
    harbor_scaffold.add_argument("--force", action="store_true")
    harbor_scaffold.set_defaults(function=_harbor_scaffold)

    tools = subparsers.add_parser(
        "tools",
        help="discover and run shared cross-site clone diagnostics",
    )
    tool_commands = tools.add_subparsers(dest="tool_command", required=True)

    tool_list = tool_commands.add_parser(
        "list", help="print the machine-readable shared tool catalog"
    )
    tool_list.add_argument("--out", type=Path)
    tool_list.set_defaults(function=_tool_list)

    explore = tool_commands.add_parser(
        "explore", help="run one approved declarative browser interaction scenario"
    )
    explore.add_argument("--spec", type=Path, required=True)
    explore.add_argument("--base-url", required=True)
    explore.add_argument("--environment", choices=("source", "clone"), required=True)
    explore.add_argument("--out", type=Path, required=True)
    explore.add_argument("--artifacts-dir", type=Path, required=True)
    explore.add_argument(
        "--storage-state",
        type=Path,
        help="Playwright storage state consumed in memory and never copied to output",
    )
    explore.add_argument("--headed", action="store_true")
    explore.add_argument(
        "--allow-source-mutations",
        action="store_true",
        help=(
            "allow source non-GET requests only when the scenario also records "
            "source_mutations_authorized=true"
        ),
    )
    explore.set_defaults(function=_tool_explore)

    functional = tool_commands.add_parser(
        "compare-functional",
        help="compare source and clone browser exploration reports",
    )
    functional.add_argument("--source", type=Path, required=True)
    functional.add_argument("--candidate", type=Path, required=True)
    functional.add_argument("--out", type=Path, required=True)
    functional.set_defaults(function=_tool_compare_functional)

    visual = tool_commands.add_parser(
        "compare-visual",
        help="compare source and candidate screenshot regions",
    )
    visual.add_argument("--spec", type=Path, required=True)
    visual.add_argument("--out", type=Path, required=True)
    visual.add_argument("--heatmap-dir", type=Path, required=True)
    visual.set_defaults(function=_tool_compare_visual)

    semantic = tool_commands.add_parser(
        "test-backend",
        help="run actor-isolated black-box HTTP semantic cases",
    )
    semantic.add_argument("--spec", type=Path, required=True)
    semantic.add_argument("--base-url", required=True)
    semantic.add_argument("--out", type=Path, required=True)
    semantic.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="explicitly allow an isolated clone target outside loopback",
    )
    semantic.set_defaults(function=_tool_test_backend)

    spec_tool = tool_commands.add_parser(
        "frontend-spec",
        help=(
            "extract a sanitized frontend spec (structure, controls, forms, "
            "data points, style references) from one approved-origin page"
        ),
    )
    spec_tool.add_argument("--url", required=True)
    spec_tool.add_argument(
        "--allowed-origin", action="append", required=True, dest="allowed_origin"
    )
    spec_tool.add_argument(
        "--viewport",
        default="1692,979",
        help="comma-separated width,height (default 1692,979)",
    )
    spec_tool.add_argument(
        "--environment", choices=("source", "clone"), default="source"
    )
    spec_tool.add_argument("--out", type=Path, required=True)
    spec_tool.add_argument("--timeout-ms", type=int, default=30000)
    spec_tool.set_defaults(function=_tool_frontend_spec)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.function(args))
    except (
        FileExistsError,
        ManifestValidationError,
        OSError,
        ToolboxError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
