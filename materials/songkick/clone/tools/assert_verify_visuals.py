#!/usr/bin/env python3
"""Fail closed when a diagnostic verify contains visual, live or static failures.

The shared Pipeline leaves below-threshold visual observations out of
``sections.live.findings``, and its live section emits no observation at all for
the non-visual recipe kinds.  This site-local guard prevents a clean diagnostic
label from masking either gap without changing shared Pipeline code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


BELOW_THRESHOLD = "below the frozen reference threshold"


def assess(report: dict[str, Any]) -> dict[str, Any]:
    live = report.get("sections", {}).get("live")
    if not isinstance(live, dict):
        return {"ok": False, "errors": ["missing sections.live"]}

    execution = live.get("execution")
    findings = live.get("findings")
    observations = live.get("observations")
    errors: list[str] = []

    if not isinstance(execution, dict) or execution.get("complete") is not True:
        errors.append("live execution is incomplete")
    if not isinstance(findings, list):
        errors.append("sections.live.findings is not a list")
        findings = []
    elif findings:
        errors.append(f"{len(findings)} live finding(s) remain")
    if not isinstance(observations, list):
        errors.append("sections.live.observations is not a list")
        observations = []

    below = [
        item
        for item in observations
        if isinstance(item, dict)
        and BELOW_THRESHOLD in str(item.get("message", "")).casefold()
    ]
    if below:
        errors.append(f"{len(below)} below-threshold visual observation(s) remain")

    static = report.get("sections", {}).get("static")
    if not isinstance(static, dict):
        errors.append("missing sections.static")
        static_findings: list[Any] = []
    else:
        static_execution = static.get("execution")
        static_findings = static.get("findings") or []
        if not isinstance(static_execution, dict) or static_execution.get("complete") is not True:
            errors.append("static execution is incomplete")
        if not isinstance(static_findings, list):
            errors.append("sections.static.findings is not a list")
            static_findings = []
        elif static_findings:
            errors.append(f"{len(static_findings)} static finding(s) remain")

    return {
        "ok": not errors,
        "diagnostic_status": report.get("diagnostic_status"),
        "static_findings": len(static_findings),
        "execution_complete": isinstance(execution, dict)
        and execution.get("complete") is True,
        "live_findings": len(findings),
        "below_threshold_observations": len(below),
        "below_threshold_subjects": sorted(
            {str(item.get("subject", "")) for item in below}
        ),
        "errors": errors,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} DIAGNOSTIC_REPORT.json", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "errors": [str(error)]}))
        return 2
    if not isinstance(report, dict):
        print(json.dumps({"ok": False, "errors": ["report root is not an object"]}))
        return 2
    result = assess(report)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
