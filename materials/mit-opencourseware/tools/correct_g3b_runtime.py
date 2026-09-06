"""Create-only correction of G3-B runtime fragments and index paths.

The original raw HTML and per-batch acquisition reports are immutable.  This
tool replays extraction/sanitization from the hash-verified raw bodies into a
new runtime directory, records old/new hashes, and atomically migrates the
mutable content index to canonical raw and corrected runtime paths.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import acquire_g3b as g3b


class BalanceValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() not in g3b.VOID_TAGS:
            self.stack.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if not self.stack or self.stack[-1] != lower:
            self.errors.append(f"unexpected </{lower}> after {self.stack[-1:]}")
            return
        self.stack.pop()


def execute(batch: int, revision: int) -> dict[str, object]:
    if batch not in {1, 2, 3, 4}:
        raise SystemExit("--batch must be 1..4")
    source_root = g3b.SITE / "source-current" / "g3b-content" / f"batch-{batch:02d}"
    source_report = source_root / "report.json"
    if not source_report.exists():
        raise SystemExit(f"source batch does not exist: {source_report}")
    corrected_name = "g3b-corrected" if revision == 1 else f"g3b-corrected-v{revision}"
    report_name = "g3b-content-corrections" if revision == 1 else f"g3b-content-corrections-v{revision}"
    corrected_root = g3b.SITE / "runtime-content" / corrected_name / f"batch-{batch:02d}"
    correction_report = g3b.SITE / "source-current" / report_name / f"batch-{batch:02d}" / "report.json"
    if corrected_root.exists() or correction_report.exists():
        raise SystemExit(f"create-only correction already exists for batch {batch}")

    data = g3b.load(g3b.CLONE / "site-data.json")
    route_map, download_map, asset_map = g3b.build_known_maps(data)
    report = g3b.load(source_report)
    index_path = g3b.CLONE / "content-index.json"
    index = g3b.load(index_path)
    stage = Path(tempfile.mkdtemp(prefix=f".g3b-correction-{batch:02d}.", dir=g3b.SITE))
    runtime_stage = stage / "runtime"
    runtime_stage.mkdir()
    rows: list[dict[str, object]] = []
    rewrite_totals: Counter[str] = Counter()
    fallback_count = 0
    for source_row in report["routes"]:
        path = str(source_row["path"])
        raw = source_root / str(source_row["raw_path"])
        assert raw.exists() and g3b.sha_file(raw) == source_row["raw_sha256"]
        fragment, selector, fallback = g3b.extract_fragment(raw.read_bytes(), str(source_row["family"]))
        source_text = g3b.visible_text(fragment)
        sanitizer = g3b.Sanitizer(
            base_url=str(source_row["final_url"]), route_path=path,
            route_map=route_map, download_map=download_map, asset_map=asset_map,
        )
        sanitizer.feed(fragment)
        output = sanitizer.output + "\n"
        validator = BalanceValidator()
        validator.feed(output)
        if validator.stack or validator.errors:
            raise AssertionError(f"unbalanced sanitized HTML for {path}: stack={validator.stack[-6:]} errors={validator.errors[:3]}")
        name = Path(str(source_row["raw_path"])).name
        destination = runtime_stage / name
        destination.write_text(output, encoding="utf-8")
        runtime_text = g3b.visible_text(output)
        fallback_count += int(fallback)
        rewrite_totals.update(sanitizer.counts)
        old = index["routes"][path]
        rows.append({
            "path": path, "page_id": source_row["page_id"], "family": source_row["family"],
            "raw_path": f"source-current/g3b-content/batch-{batch:02d}/{source_row['raw_path']}",
            "raw_sha256": source_row["raw_sha256"],
            "old_runtime_path": old["runtime_path"], "old_runtime_sha256": old["runtime_sha256"],
            "corrected_source_visible_text_bytes": len(source_text.encode()),
            "corrected_source_visible_text_sha256": g3b.sha_bytes(source_text.encode()),
            "corrected_runtime_path": f"runtime-content/{corrected_name}/batch-{batch:02d}/{name}",
            "corrected_runtime_bytes": destination.stat().st_size,
            "corrected_runtime_sha256": g3b.sha_file(destination),
            "corrected_visible_text_bytes": len(runtime_text.encode()),
            "corrected_visible_text_sha256": g3b.sha_bytes(runtime_text.encode()),
            "content_selector": selector, "selector_fallback": fallback,
            "sanitize_rewrite_counts": dict(sorted(sanitizer.counts.items())),
            "balanced_html": True,
        })
    correction = {
        "schema_version": f"mit-ocw.g3b-content-runtime-correction.v{revision}",
        "capture_id": g3b.CAPTURE_ID, "correction_id": f"g3b-runtime-correction-v{revision}-batch-{batch:02d}",
        "created_at": g3b.now(), "create_only": True, "does_not_modify_source_batch": True,
        "source_batch_report": g3b.relative(source_report),
        "reason": (
            "Drop style/script/media content from visible text, canonicalize trailing-slash route aliases, "
            "bind the exact G2-A PDF locally, and retain balanced network-closed HTML."
            if revision >= 2 else
            "Canonicalize raw evidence paths, fix unsafe-tag stack accounting, close emitted tags deterministically, and use documented family-variant selectors before whole-body fallback."
        ),
        "closure": {"status": "closed", "routes": len(rows), "balanced": len(rows), "selector_fallbacks": fallback_count},
        "sanitize_rewrite_totals": dict(sorted(rewrite_totals.items())),
        "routes": rows,
    }
    g3b.dump_atomic(stage / "report.json", correction)
    corrected_root.parent.mkdir(parents=True, exist_ok=True)
    correction_report.parent.mkdir(parents=True, exist_ok=True)
    os.replace(runtime_stage, corrected_root)
    os.replace(stage / "report.json", correction_report)
    stage.rmdir()

    for row in rows:
        current = index["routes"][row["path"]]
        if revision >= 2:
            current["pre_v2_source_visible_text_bytes"] = current["source_visible_text_bytes"]
            current["pre_v2_source_visible_text_sha256"] = current["source_visible_text_sha256"]
        current.update({
            "raw_path": row["raw_path"],
            "content_selector": row["content_selector"],
            "selector_fallback": row["selector_fallback"],
            "source_visible_text_bytes": row["corrected_source_visible_text_bytes"],
            "source_visible_text_sha256": row["corrected_source_visible_text_sha256"],
            "runtime_path": row["corrected_runtime_path"],
            "runtime_bytes": row["corrected_runtime_bytes"],
            "runtime_sha256": row["corrected_runtime_sha256"],
            "runtime_visible_text_bytes": row["corrected_visible_text_bytes"],
            "runtime_visible_text_sha256": row["corrected_visible_text_sha256"],
            "sanitize_rewrite_counts": row["sanitize_rewrite_counts"],
            "runtime_correction_report": g3b.relative(correction_report),
        })
    index.setdefault("corrections", []).append({
        "correction_id": correction["correction_id"], "report": g3b.relative(correction_report),
        "routes": len(rows), "status": "closed",
    })
    index["updated_at"] = g3b.now()
    g3b.dump_atomic(index_path, index, compact=True)
    return {
        "status": "closed", "batch": batch, "routes": len(rows),
        "balanced": len(rows), "selector_fallbacks": fallback_count,
        "report": g3b.relative(correction_report),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--revision", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    print(json.dumps(execute(args.batch, args.revision), indent=2))


if __name__ == "__main__":
    main()
