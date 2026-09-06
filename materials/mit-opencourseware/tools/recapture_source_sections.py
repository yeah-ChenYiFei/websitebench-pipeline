"""Re-capture the 6.006 course-section source rasters that do not depict the live source.

Five frozen `source-current/g3c/fullpage-v2` rasters render the stacked responsive
table layout that ocw.mit.edu does not produce at CSS 1440x900; the live pages use a
column table. This tool retakes exactly those pages from the source in one batch and,
in the same session, re-verifies every other directly reachable checkpoint against live
so the batch is self-consistent rather than a cherry-picked correction.

GET-only. Writes rasters plus a report; never touches the candidate or the contracts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SOURCE_ORIGIN = "https://ocw.mit.edu"
VIEWPORT = {"width": 1440, "height": 900}
ENVIRONMENT = {
    "viewport": VIEWPORT,
    "device_scale_factor": 1,
    "locale": "en-US",
    "timezone_id": "America/Toronto",
    "color_scheme": "light",
    "reduced_motion": "reduce",
}
# Pages whose frozen raster shows the clone's stacked layout instead of the live column table.
RETAKE = {
    "course-readings-default": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/",
    "course-calendar-default": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/calendar/",
    "course-lecture-notes-default": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-notes/",
    "course-assignments-default": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/",
    "course-exams-default": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/exams/",
}


def settle(page) -> int:
    """Return the page's own scrollHeight once lazy content has stopped growing."""
    previous = -1
    for _ in range(30):
        height = page.evaluate("document.documentElement.scrollHeight")
        if height == previous:
            break
        previous = height
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(300)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    return page.evaluate("document.documentElement.scrollHeight")


def table_shape(page) -> dict[str, object]:
    return page.evaluate(
        """() => {
            const table = document.querySelector('main table, table');
            if (!table) return {present: false};
            const cell = table.querySelector('tbody td');
            const head = table.querySelector('thead');
            return {
                present: true,
                rows: table.querySelectorAll('tbody tr').length,
                td_display: cell ? getComputedStyle(cell).display : null,
                thead_display: head ? getComputedStyle(head).display : null,
                width: Math.round(table.getBoundingClientRect().width),
            };
        }"""
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, help="directory that receives the rasters")
    parser.add_argument("--report", required=True, help="path of the batch report")
    parser.add_argument("--verify-manifest", required=True,
                        help="JSON list of {id, clone_path, frozen_h} to re-verify in the same session")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    verify_rows = json.loads(Path(args.verify_manifest).read_text(encoding="utf-8"))

    report: dict[str, object] = {
        "schema_version": "mit-ocw.source-section-recapture.v1",
        "authority": "source-capture",
        "source_origin": SOURCE_ORIGIN,
        "method": "GET-only; Playwright CDP captureBeyondViewport, exact clip "
                  "x=0,y=0,width=1440,height=document scrollHeight; no resize, no post-crop, no mask",
        "environment": ENVIRONMENT,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "retaken": [],
        "same_session_verification": [],
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT, device_scale_factor=1, locale="en-US",
            timezone_id="America/Toronto", color_scheme="light", reduced_motion="reduce",
        )

        for checkpoint_id, path in RETAKE.items():
            page = context.new_page()
            response = page.goto(SOURCE_ORIGIN + path, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1200)
            height = settle(page)
            shape = table_shape(page)
            target = out_dir / f"{checkpoint_id}-1440xfull.png"
            page.screenshot(path=str(target), full_page=True,
                            clip={"x": 0, "y": 0, "width": 1440, "height": height})
            payload = target.read_bytes()
            report["retaken"].append({
                "checkpoint_id": checkpoint_id,
                "url": SOURCE_ORIGIN + path,
                "http_status": response.status,
                "document_scroll_height": height,
                "raster_path": str(target),
                "raster_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "table_shape": shape,
            })
            print(f"  retaken {checkpoint_id:<32} h={height} rows={shape.get('rows')} "
                  f"td={shape.get('td_display')} thead={shape.get('thead_display')}")
            page.close()

        for row in verify_rows:
            path = row.get("clone_path")
            if not path or "?" in path:
                continue
            page = context.new_page()
            try:
                response = page.goto(SOURCE_ORIGIN + path, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(900)
                # /search/ is an infinite-scroll surface; its frozen state is the unscrolled first batch.
                height = (page.evaluate("document.documentElement.scrollHeight")
                          if path.rstrip("/") == "/search" else settle(page))
                report["same_session_verification"].append({
                    "checkpoint_id": row["id"], "url": SOURCE_ORIGIN + path,
                    "http_status": response.status, "frozen_height": row.get("frozen_h"),
                    "live_height": height, "equal": height == row.get("frozen_h"),
                })
            except Exception as error:  # keep the batch report complete
                report["same_session_verification"].append({
                    "checkpoint_id": row["id"], "url": SOURCE_ORIGIN + path,
                    "error": repr(error)[:200],
                })
            page.close()
        browser.close()

    equal = sum(1 for r in report["same_session_verification"] if r.get("equal"))
    total = len(report["same_session_verification"])
    report["same_session_summary"] = {"checked": total, "height_equal_to_frozen": equal}
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nretaken {len(report['retaken'])}; same-session verification {equal}/{total} equal to frozen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
