"""Measure whether the ocw.mit.edu catalog result set is a stable source property.

The frozen catalog entity denominator and the frozen catalog rasters disagree on which
courses the listing shows. Before treating that as a clone defect or recapturing the
denominator, this probe establishes whether any capture could pin the listing at all.

GET-only, read-only. Writes one evidence report; touches nothing else.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SOURCE_ORIGIN = "https://ocw.mit.edu"
SURFACES = {
    "catalog-default": "/search/",
    "catalog-department-mathematics": "/search/?d=Mathematics",
}
COURSE_HREF = r"^/courses/[^/]+/$"


def distinct_courses(page) -> list[str]:
    hrefs = page.evaluate(
        """(pattern) => {
            const re = new RegExp(pattern);
            return [...document.querySelectorAll('a[href]')]
                .map(a => a.getAttribute('href'))
                .filter(h => h && re.test(h));
        }""",
        COURSE_HREF,
    )
    ordered: list[str] = []
    for href in hrefs:
        if href not in ordered:
            ordered.append(href)
    return [h.strip("/").split("/")[-1] for h in ordered[:10]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    report: dict[str, object] = {
        "schema_version": "mit-ocw.catalog-determinism-probe.v1",
        "authority": "source-observation",
        "source_origin": SOURCE_ORIGIN,
        "method": "GET-only; a fresh browser context per run; first ten distinct course hrefs, in order",
        "environment": {"viewport": {"width": 1440, "height": 900}, "locale": "en-US",
                        "timezone_id": "America/Toronto"},
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runs_per_surface": args.runs,
        "surfaces": [],
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, path in SURFACES.items():
            runs: list[list[str]] = []
            for index in range(args.runs):
                context = browser.new_context(viewport={"width": 1440, "height": 900},
                                              locale="en-US", timezone_id="America/Toronto")
                page = context.new_page()
                page.goto(SOURCE_ORIGIN + path, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2500)
                runs.append(distinct_courses(page))
                context.close()
                if index + 1 < args.runs:
                    time.sleep(3)
            sets = [set(r) for r in runs]
            intersection = sorted(set.intersection(*sets)) if sets else []
            report["surfaces"].append({
                "surface": name,
                "url": SOURCE_ORIGIN + path,
                "runs": runs,
                "all_runs_identical": all(r == runs[0] for r in runs),
                "intersection_across_runs": intersection,
                "intersection_size": len(intersection),
                "union_size": len(set().union(*sets)) if sets else 0,
            })
            print(f"  {name:<32} identical={all(r == runs[0] for r in runs)!s:<6} "
                  f"intersection={len(intersection)}/10 union={len(set().union(*sets))}")
        browser.close()

    stable = all(s["all_runs_identical"] for s in report["surfaces"])
    report["conclusion"] = (
        "The catalog result set is stable across runs; a capture can pin it."
        if stable else
        "The catalog result set is not a stable source property: independent runs seconds apart "
        "return different courses, so no capture can pin the listing and no captured card list "
        "can be re-verified against the source later."
    )
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + report["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
