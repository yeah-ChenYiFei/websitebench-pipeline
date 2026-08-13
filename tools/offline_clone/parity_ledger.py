#!/usr/bin/env python3
"""Derive the clone-parity gap ledger and scorecard.

Diagnostic transformation only.  It reads `tools compare-functional` reports
plus a static scan of the clone's own sources, and writes under
``materials/<site>/artifacts/parity/``.  It drives no browser, computes no
acceptance metric, and carries no gate authority: nothing it emits can satisfy
a source, assets, frontend, backend or release gate.  The gate metric family is
``pixel-mae-similarity-v1``; nothing here produces a number in that family.

Subcommands::

    scan   --site <name>            static dead-affordance + interaction census
    build  --site <name>            merge scans + compare-functional into a ledger
    score  --site <name>            recompute the AS-1..AS-6 scorecard
    status --site <name> [...]      one line per site, ledger + score summary
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_SCHEMA = "websitebench.clone-parity-gap.v1"
SCORECARD_SCHEMA = "websitebench.clone-parity-scorecard.v1"

OPEN_STATES = {"open", "patched", "reopened"}
TERMINAL_STATES = {"closed", "blocked-needs-phase-2", "blocked"}

# `compare-functional` difference categories -> ledger kinds.  Mapping is fixed
# so a ledger row can always be traced back to a specific reported difference.
DIFFERENCE_KINDS: dict[str, str] = {
    "missing-step": "missing-interaction",
    "action": "missing-interaction",
    "route": "divergent-navigation",
    "outcome": "divergent-navigation",
    "observable-state": "divergent-state",
    "missing-observation": "divergent-state",
    "extra-step": "extra-affordance",
    "extra-observation": "extra-affordance",
    "runtime-error-behavior": "runtime-error",
}

# Persistent chrome: a dead control here is an AS-1 level-0 finding, because it
# is on every page rather than one surface.
CHROME_HINTS = ("header", "footer", "nav", "base.html", "layout")

DEAD_HREF = re.compile(r'href\s*=\s*"(#|javascript:void\(0\)|)"', re.IGNORECASE)
# `disabled` only counts as a control state when it is written as markup — as an
# attribute inside a tag, or inside a quoted attribute fragment that gets
# interpolated into one.  Without this the word matches ordinary prose in
# comments and docstrings ("degrades with JavaScript disabled").
DISABLED = re.compile(
    r"""(?:<[^>]*\bdisabled\b[^>]*>)"""      # attribute inside a literal tag
    r"""|(?:["'][^"'<>]*\s\bdisabled\b(?:\s[^"'<>]*)?["'])""",  # quoted fragment
    re.IGNORECASE,
)
DATA_HOOK = re.compile(r"data-[a-z][a-z0-9-]*")


def site_root(site: str) -> Path:
    root = REPO_ROOT / "materials" / site
    if not root.is_dir():
        raise SystemExit(f"unknown site: {site}")
    return root


def parity_dir(site: str) -> Path:
    directory = site_root(site) / "artifacts" / "parity"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def markup_files(site: str) -> list[Path]:
    """Every authored file that can emit an affordance, for either family."""

    root = site_root(site) / "clone"
    found: list[Path] = []
    for pattern in ("frontend/templates/**/*.html", "render.py", "*_views.py"):
        found.extend(sorted(root.glob(pattern)))
    return [path for path in found if path.is_file()]


def javascript_files(site: str) -> list[Path]:
    root = site_root(site) / "clone"
    return [
        path
        for pattern in ("static/**/*.js", "frontend/static/**/*.js")
        for path in sorted(root.glob(pattern))
        # Mirrored source assets are not authored interaction code.
        if path.is_file() and "assets" not in path.parts
    ]


def test_files(site: str) -> list[Path]:
    return sorted((site_root(site) / "clone" / "tests").glob("test_*.py"))


def scan(site: str) -> dict[str, Any]:
    """Static census of affordances the clone renders."""

    dead: list[dict[str, Any]] = []
    hooks: Counter[str] = Counter()
    forms = 0
    for path in markup_files(site):
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = str(path.relative_to(REPO_ROOT))
        in_chrome = any(hint in relative.lower() for hint in CHROME_HINTS)
        forms += len(re.findall(r"<form", text, re.IGNORECASE))
        for name in DATA_HOOK.findall(text):
            hooks[name] += 1
        for index, line in enumerate(text.splitlines(), start=1):
            for pattern, reason in ((DEAD_HREF, "dead-href"), (DISABLED, "disabled")):
                if pattern.search(line):
                    dead.append(
                        {
                            "file": relative,
                            "line": index,
                            "reason": reason,
                            "in_persistent_chrome": in_chrome,
                            "excerpt": line.strip()[:200],
                        }
                    )
    javascript_bytes = sum(path.stat().st_size for path in javascript_files(site))
    return {
        "dead_affordances": dead,
        "distinct_data_hooks": len(hooks),
        "form_count": forms,
        "authored_javascript_bytes": javascript_bytes,
        "template_count": len(markup_files(site)),
        "test_file_count": len(test_files(site)),
    }


def gaps_from_scan(site: str, census: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in census["dead_affordances"]:
        chrome = item["in_persistent_chrome"]
        # Anchor the id on the offending text, not the line number: editing the
        # file above a finding would otherwise mint a fresh row and silently
        # discard the decision already recorded against it.
        fingerprint = hashlib.sha256(
            f"{item['file']}::{item['excerpt']}".encode()
        ).hexdigest()[:10]
        anchor = f"{Path(item['file']).stem}.{fingerprint}"
        rows.append(
            {
                "id": f"{site}.dead-affordance.{anchor}",
                "route_family": None,
                "as_dimension": "AS-1",
                "severity": "p0" if chrome else "p1",
                "kind": "dead-affordance",
                # A static finding is self-evidencing: the defect is that the
                # clone renders a control that goes nowhere, which needs no
                # source capture to establish.
                "source_evidence": {"kind": "static-scan", "path": item["file"]},
                "clone_state": {
                    "file": item["file"],
                    "line": item["line"],
                    "observed": f"{item['reason']}: {item['excerpt']}",
                },
                "diff_refs": [],
                "status": "open",
            }
        )
    return rows


def gaps_from_comparisons(site: str) -> list[dict[str, Any]]:
    """Convert every `compare-functional` report in artifacts/parity."""

    rows: list[dict[str, Any]] = []
    for report_path in sorted(parity_dir(site).glob("*.diff.json")):
        report = read_json(report_path)
        if not isinstance(report, dict):
            continue
        family = report_path.name[: -len(".diff.json")]
        relative = str(report_path.relative_to(REPO_ROOT))
        for index, difference in enumerate(report.get("differences", []) or []):
            category = str(difference.get("category") or difference.get("kind") or "")
            rows.append(
                {
                    "id": f"{site}.{family}.{category or 'difference'}.{index}",
                    "route_family": family,
                    "as_dimension": "AS-2",
                    "severity": str(difference.get("severity") or "p1"),
                    "kind": DIFFERENCE_KINDS.get(category, "divergent-state"),
                    "source_evidence": {
                        "kind": "browser-exploration",
                        "path": relative,
                        "step_id": difference.get("step_id"),
                    },
                    "clone_state": {
                        "observed": str(
                            difference.get("candidate")
                            or difference.get("detail")
                            or ""
                        )[:400]
                    },
                    "diff_refs": [f"{relative}#/differences/{index}"],
                    "status": "open",
                }
            )
    return rows


def build(site: str) -> dict[str, Any]:
    """Merge fresh findings into the ledger, preserving human/agent decisions."""

    path = parity_dir(site) / "gap-ledger.json"
    previous = read_json(path) or {}
    kept = {
        str(row.get("id")): row
        for row in previous.get("gaps", [])
        if row.get("status") in TERMINAL_STATES
    }
    in_flight = {
        str(row.get("id")): row
        for row in previous.get("gaps", [])
        if row.get("status") not in TERMINAL_STATES
    }

    census = scan(site)
    discovered = gaps_from_scan(site, census) + gaps_from_comparisons(site)

    merged: dict[str, dict[str, Any]] = {}
    for row in discovered:
        identifier = row["id"]
        if identifier in kept:
            # Already decided.  Re-discovery does not silently reopen it; the
            # aligner's re-diff is what reopens a row.
            merged[identifier] = kept[identifier]
        elif identifier in in_flight:
            existing = dict(in_flight[identifier])
            existing.update(
                {k: v for k, v in row.items() if k not in {"status", "patch_refs"}}
            )
            merged[identifier] = existing
        else:
            merged[identifier] = row
    # A decided row whose finding disappeared stays in the ledger as history.
    for identifier, row in kept.items():
        merged.setdefault(identifier, row)

    ledger = {
        "schema_version": LEDGER_SCHEMA,
        "site_id": site,
        "authority": "diagnostic-tools-only-do-not-satisfy-release-gates",
        "source_evidence_mode": previous.get("source_evidence_mode", "static-scan"),
        "census": {k: v for k, v in census.items() if k != "dead_affordances"},
        "gaps": sorted(merged.values(), key=lambda row: str(row["id"])),
    }
    write_json(path, ledger)
    return ledger


AS_LABELS = {
    "AS-1": "surface breadth and liveness",
    "AS-2": "interaction depth",
    "AS-3": "backend semantics",
    "AS-4": "visual parity",
    "AS-5": "evidence closure",
    "AS-6": "test depth",
}


def score(site: str) -> dict[str, Any]:
    """Score AS-1, AS-2 and AS-6 from measurable signals.

    AS-3, AS-4 and AS-5 depend on gate artifacts and human scope decisions that
    this tool deliberately does not infer; they are carried forward from the
    existing scorecard, or reported as null when never assessed.
    """

    census = scan(site)
    ledger = read_json(parity_dir(site) / "gap-ledger.json") or {}
    rows = ledger.get("gaps", [])
    chrome_dead = [item for item in census["dead_affordances"] if item["in_persistent_chrome"]]
    open_rows = [row for row in rows if row.get("status") in OPEN_STATES]

    # AS-1 level 3 means "no dead affordance is unaccounted for" — not "none
    # exist".  A `disabled` that is a real empty state or pagination boundary is
    # correct behaviour, so a finding with a recorded rationale counts as
    # accounted for; one still sitting open does not.
    #
    # IMPORTANT: this is a *static* scan of the clone's sources. It greps for
    # href="#" and disabled; it never requests a page. A link that 404s, and a
    # link that answers 200 with an empty result set, are both invisible here
    # and both score as live. Three sites scored AS-1=3 with zero open rows
    # while large parts of their home pages were dead at runtime. Treat AS-1 as
    # a lower bound and pair it with the per-site tests/test_link_liveness.py
    # crawl, which does request every reachable page.
    undecided = [
        row
        for row in rows
        if row.get("as_dimension") == "AS-1"
        and (row.get("status") in OPEN_STATES or not row.get("rationale"))
    ]
    undecided_in_chrome = [
        row
        for row in undecided
        if any(hint in str(row.get("clone_state", {}).get("file", "")).lower()
               for hint in CHROME_HINTS)
    ]
    if undecided_in_chrome or (chrome_dead and undecided):
        as1 = 0
    elif undecided:
        as1 = 2
    else:
        as1 = 3

    # Amazon's calibration: 93 distinct hooks over 42.8 KB of authored JS.
    kb = census["authored_javascript_bytes"] / 1024
    density = census["distinct_data_hooks"] / kb if kb else 0.0
    if census["distinct_data_hooks"] == 0:
        as2 = 0
    elif kb < 4:
        as2 = 1
    elif density < 1.0:
        as2 = 2
    else:
        as2 = 3 if not any(r["as_dimension"] == "AS-2" for r in open_rows) else 2

    templates = max(census["template_count"], 1)
    ratio = census["test_file_count"] / templates
    as6 = 0 if census["test_file_count"] == 0 else (3 if ratio >= 0.5 else 2 if ratio >= 0.25 else 1)

    previous = (read_json(parity_dir(site) / "scorecard.json") or {}).get("scores", {})
    scores = {
        "AS-1": as1,
        "AS-2": as2,
        "AS-3": previous.get("AS-3"),
        "AS-4": previous.get("AS-4"),
        "AS-5": previous.get("AS-5"),
        "AS-6": as6,
    }
    card = {
        "schema_version": SCORECARD_SCHEMA,
        "site_id": site,
        "authority": "diagnostic-tools-only-do-not-satisfy-release-gates",
        "labels": AS_LABELS,
        "scores": scores,
        "derived": {
            "data_hooks_per_js_kb": round(density, 2),
            "authored_javascript_kb": round(kb, 1),
            "distinct_data_hooks": census["distinct_data_hooks"],
            "template_count": census["template_count"],
            "test_file_count": census["test_file_count"],
            "dead_affordances": len(census["dead_affordances"]),
            "dead_affordances_in_chrome": len(chrome_dead),
            "open_gap_rows": len(open_rows),
        },
        "manually_scored": ["AS-3", "AS-4", "AS-5"],
        "as1_evidence_mode": "static-scan-only",
        "as1_caveat": (
            "AS-1 is scored by grepping sources for dead affordances; no page is "
            "requested, so 404s and 200-but-empty results are not visible to it. "
            "Runtime liveness is covered by tests/test_link_liveness.py."
        ),
    }
    write_json(parity_dir(site) / "scorecard.json", card)
    return card


def status_line(site: str) -> str:
    ledger = read_json(parity_dir(site) / "gap-ledger.json") or {}
    card = read_json(parity_dir(site) / "scorecard.json") or {}
    rows = ledger.get("gaps", [])
    counts = Counter(str(row.get("status")) for row in rows)
    scores = card.get("scores", {})
    rendered = " ".join(
        # "1*" marks AS-1 as static-only: it cannot see a 404 or an empty
        # result set. See score() and tests/test_link_liveness.py.
        f"{key.split('-')[1]}{'*' if key == 'AS-1' else ''}:"
        f"{'-' if scores.get(key) is None else scores[key]}"
        for key in sorted(AS_LABELS)
    )
    return (
        f"{site:11s} gaps={len(rows):<4d} "
        f"open={counts.get('open', 0):<4d} patched={counts.get('patched', 0):<3d} "
        f"closed={counts.get('closed', 0):<4d} "
        f"blocked={sum(v for k, v in counts.items() if k.startswith('blocked')):<3d} "
        f"AS[{rendered}]"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "build", "score"):
        child = sub.add_parser(name)
        child.add_argument("--site", required=True)
    add = sub.add_parser(
        "add", help="record a finding the static scan and differ cannot see"
    )
    add.add_argument("--site", required=True)
    add.add_argument("--id", required=True)
    add.add_argument("--dimension", required=True, choices=sorted(AS_LABELS))
    add.add_argument("--severity", default="p1", choices=("p0", "p1", "p2"))
    add.add_argument("--kind", required=True)
    add.add_argument("--evidence", required=True, help="path to the capture or report")
    add.add_argument("--observed", required=True)
    add.add_argument("--status", default="open")
    add.add_argument("--rationale", default="")
    resolve = sub.add_parser(
        "resolve", help="record a decision about a row (verification pass only)"
    )
    resolve.add_argument("--site", required=True)
    resolve.add_argument("--id", required=True, help="ledger row id, or a prefix")
    resolve.add_argument(
        "--status",
        required=True,
        choices=sorted(TERMINAL_STATES | {"open", "patched", "reopened"}),
    )
    resolve.add_argument(
        "--rationale", required=True, help="why — recorded verbatim in the ledger"
    )
    listing = sub.add_parser("status")
    listing.add_argument("--site", action="append", required=True)
    args = parser.parse_args()

    if args.command == "scan":
        census = scan(args.site)
        census["dead_affordances"] = census["dead_affordances"][:50]
        print(json.dumps(census, indent=2))
    elif args.command == "build":
        ledger = build(args.site)
        print(f"{args.site}: {len(ledger['gaps'])} ledger rows")
        print(status_line(args.site))
    elif args.command == "score":
        card = score(args.site)
        print(json.dumps(card["scores"], indent=2))
        print(json.dumps(card["derived"], indent=2))
    elif args.command == "add":
        path = parity_dir(args.site) / "gap-ledger.json"
        ledger = read_json(path) or {
            "schema_version": LEDGER_SCHEMA,
            "site_id": args.site,
            "authority": "diagnostic-tools-only-do-not-satisfy-release-gates",
            "gaps": [],
        }
        ledger["gaps"] = [g for g in ledger["gaps"] if g.get("id") != args.id]
        row = {
            "id": args.id,
            "route_family": None,
            "as_dimension": args.dimension,
            "severity": args.severity,
            "kind": args.kind,
            "source_evidence": {"kind": "manual-review", "path": args.evidence},
            "clone_state": {"observed": args.observed},
            "diff_refs": [],
            "status": args.status,
        }
        if args.rationale:
            row["rationale"] = args.rationale
        ledger["gaps"].append(row)
        ledger["gaps"].sort(key=lambda r: str(r["id"]))
        write_json(path, ledger)
        print(f"{args.id} -> {args.status}")
    elif args.command == "resolve":
        path = parity_dir(args.site) / "gap-ledger.json"
        ledger = read_json(path)
        if ledger is None:
            raise SystemExit(f"no ledger for {args.site}; run `build` first")
        matched = [
            row for row in ledger["gaps"] if str(row["id"]).startswith(args.id)
        ]
        if not matched:
            raise SystemExit(f"no ledger row matching {args.id!r}")
        for row in matched:
            row["status"] = args.status
            row["rationale"] = args.rationale
        write_json(path, ledger)
        for row in matched:
            print(f"{row['id']} -> {args.status}")
    else:
        for site in args.site:
            print(status_line(site))
    return 0


if __name__ == "__main__":
    sys.exit(main())
