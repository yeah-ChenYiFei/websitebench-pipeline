"""Command-line entry point for the standalone browser trajectory recorder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .diff import TrajectoryDiffError, diff_trajectories
from .recorder import BrowserTrajectoryError, RecorderConfig, TrajectoryRecorder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="websitebench-browser-trajectory")
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser(
        "record",
        help="attach to an approved Chrome CDP endpoint and retain a redacted ledger",
    )
    record.add_argument("--output", type=Path, required=True)
    record.add_argument(
        "--allowed-origin",
        action="append",
        dest="allowed_origins",
        required=True,
        help="approved HTTP(S) origin; repeat for each in-scope origin",
    )
    record.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    record.add_argument(
        "--screenshots",
        action="store_true",
        help="also save event-triggered screenshots; use only on non-sensitive surfaces",
    )
    record.add_argument("--screenshot-interval-ms", type=int, default=500, metavar="MS")
    record.add_argument(
        "--duration-seconds",
        type=float,
        help="stop automatically after this duration instead of waiting for Ctrl-C",
    )
    compare = sub.add_parser(
        "diff",
        help="structurally compare two recorded trajectories (diagnostic only)",
        description=(
            "Align a source-side and a candidate-side ledger over a normalized "
            "projection of event type, route path, and element identity. "
            "Reports divergence; adjudicates nothing. This is diagnostic "
            "evidence about structure and order -- it establishes nothing about "
            "pixels, copy, network closure, or cross-origin iframes, and there "
            "is deliberately no fail-on-divergence mode."
        ),
    )
    compare.add_argument(
        "--source",
        type=Path,
        required=True,
        help="source-side recorder output directory, or an actions.jsonl",
    )
    compare.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="candidate-side recorder output directory, or an actions.jsonl",
    )
    compare.add_argument(
        "--output",
        type=Path,
        help="write the JSON report here instead of stdout",
    )
    compare.add_argument(
        "--strict",
        action="store_true",
        help="also compare class_name and xpath; both diverge on details a user "
        "cannot perceive, so this over-reports for an offline clone",
    )
    compare.add_argument(
        "--include-input",
        action="store_true",
        help="also compare throttled input events (values stay omitted)",
    )
    compare.add_argument(
        "--collapse-repeats",
        action="store_true",
        help="collapse consecutive identical steps of every type; this hides "
        "genuine repeats such as a double submit",
    )
    return parser


def _record(args: argparse.Namespace) -> int:
    if args.duration_seconds is not None and args.duration_seconds < 0:
        raise BrowserTrajectoryError("duration_seconds must be non-negative")
    recorder = TrajectoryRecorder(
        RecorderConfig(
            output_dir=args.output,
            allowed_origins=tuple(args.allowed_origins),
            cdp_url=args.cdp_url,
            screenshots=args.screenshots,
            screenshot_interval_ms=args.screenshot_interval_ms,
        )
    )
    try:
        recorder.start()
        print(
            json.dumps(
                {
                    "status": "recording",
                    "output": str(recorder.output_dir),
                    "allowed_origins": list(recorder.config.allowed_origins),
                },
                ensure_ascii=False,
            )
        )
        recorder.wait(duration_seconds=args.duration_seconds)
    except KeyboardInterrupt:
        recorder.close(status="stopped")
        return 0
    except Exception:
        recorder.close(status="failed")
        raise
    recorder.close(status="complete")
    return 0


def _diff(args: argparse.Namespace) -> int:
    report = diff_trajectories(
        args.source,
        args.candidate,
        strict=args.strict,
        include_input=args.include_input,
        collapse_repeats=args.collapse_repeats,
    )
    document = json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "compared",
                    "output": str(args.output),
                    "similarity": report.similarity,
                    "findings": len(report.findings),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(document)
    # Divergence is a finding, not a failure: this comparison has diagnostic
    # authority only, so a clean exit never asserts that a candidate is faithful.
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "record":
            return _record(args)
        if args.command == "diff":
            return _diff(args)
        raise AssertionError(f"unsupported command: {args.command}")
    except (BrowserTrajectoryError, TrajectoryDiffError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
