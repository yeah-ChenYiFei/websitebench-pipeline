"""Finalize and mechanically verify the G3-B route-content addendum."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import acquire_g3b as g3b
from correct_g3b_runtime import BalanceValidator


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finalize() -> dict[str, object]:
    index_path = g3b.CLONE / "content-index.json"
    index = g3b.load(index_path)
    data_path = g3b.CLONE / "site-data.json"
    data = g3b.load(data_path)
    pages = data["pages"]
    assert len(index["routes"]) == len(pages) == g3b.TOTAL_ROUTES
    assert set(index["routes"]) == set(pages)
    contract = g3b.load(g3b.SITE / "scope" / "business-contracts" / "route-state-contract.json")
    expected_families = contract["route_family_counts"]
    actual_families = Counter(str(row["family"]) for row in index["routes"].values())
    assert dict(actual_families) == expected_families

    migration_path = g3b.SITE / "source-current" / "g3b-content-index-migration-v2" / "report.json"
    aggregate_path = g3b.SITE / "source-current" / "g3b-content" / "report.json"
    if migration_path.exists() or aggregate_path.exists():
        raise SystemExit("G3-B finalize artifacts are create-only and already exist")

    migrations: list[dict[str, object]] = []
    selector_counts: Counter[str] = Counter()
    raw_bytes = runtime_bytes = 0
    source_text_bytes = runtime_text_bytes = 0
    fallback_paths: list[str] = []
    raw_hashes: set[str] = set()
    content_hashes: set[str] = set()
    for path, current in index["routes"].items():
        page = pages[path]
        assert current["page_id"] == page["page_id"]
        assert current["family"] == page["family"]
        assert current["requested_url"] == page["source_url"]
        assert current["http_status"] == page["status"] == 200
        raw = g3b.SITE / str(current["raw_path"])
        runtime = g3b.SITE / str(current["runtime_path"])
        assert raw.is_file() and runtime.is_file()
        assert not raw.is_symlink() and not runtime.is_symlink()
        assert raw.stat().st_size == current["raw_bytes"]
        assert file_sha(raw) == current["raw_sha256"]
        assert runtime.stat().st_size == current["runtime_bytes"]
        assert file_sha(runtime) == current["runtime_sha256"]
        fragment, selector, fallback = g3b.extract_fragment(raw.read_bytes(), str(current["family"]))
        source_text = g3b.visible_text(fragment)
        source_bytes = len(source_text.encode())
        source_sha = g3b.sha_bytes(source_text.encode())
        runtime_markup = runtime.read_text(encoding="utf-8")
        parser = BalanceValidator()
        parser.feed(runtime_markup)
        assert not parser.stack and not parser.errors, (path, parser.stack[-4:], parser.errors[:2])
        assert f'data-wb-g3b-content="{path}"' in runtime_markup
        rendered_text = g3b.visible_text(runtime_markup)
        rendered_bytes = len(rendered_text.encode())
        rendered_sha = g3b.sha_bytes(rendered_text.encode())
        assert rendered_bytes == current["runtime_visible_text_bytes"]
        assert rendered_sha == current["runtime_visible_text_sha256"]

        old_selector = current["content_selector"]
        old_source_bytes = current["source_visible_text_bytes"]
        old_source_sha = current["source_visible_text_sha256"]
        if (old_selector, old_source_bytes, old_source_sha) != (selector, source_bytes, source_sha):
            migrations.append({
                "path": path, "raw_path": current["raw_path"], "raw_sha256": current["raw_sha256"],
                "original_selector": old_selector,
                "original_source_visible_text_bytes": old_source_bytes,
                "original_source_visible_text_sha256": old_source_sha,
                "current_selector": selector,
                "current_source_visible_text_bytes": source_bytes,
                "current_source_visible_text_sha256": source_sha,
                "reason": "runtime selector correction and canonical current-selector hash binding",
            })
            current["original_content_selector"] = old_selector
            current["original_source_visible_text_bytes"] = old_source_bytes
            current["original_source_visible_text_sha256"] = old_source_sha
        current["content_selector"] = selector
        current["selector_fallback"] = fallback
        current["source_visible_text_bytes"] = source_bytes
        current["source_visible_text_sha256"] = source_sha
        current["render_policy"] = (
            "preserve-g3a-home-custom"
            if path == "/"
            else "preserve-frozen-search-state-renderer"
            if path == "/search/"
            else "preserve-g3a-authentic-6.006-overview"
            if path == "/courses/6-006-introduction-to-algorithms-fall-2011/"
            else "render-sanitized-g3b-fragment"
        )
        selector_counts[selector] += 1
        if fallback:
            fallback_paths.append(path)
        raw_bytes += raw.stat().st_size
        runtime_bytes += runtime.stat().st_size
        source_text_bytes += source_bytes
        runtime_text_bytes += rendered_bytes
        raw_hashes.add(str(current["raw_sha256"]))
        content_hashes.add(str(current["runtime_visible_text_sha256"]))

    migration = {
        "schema_version": "mit-ocw.g3b-content-index-migration.v2",
        "capture_id": g3b.CAPTURE_ID, "created_at": g3b.now(), "create_only": True,
        "reason": "Bind canonical raw paths and current selectors to recomputed visible-text bytes/SHA without modifying immutable acquisition or correction reports.",
        "closure": {"status": "closed", "routes_recomputed": len(index["routes"]), "rows_changed": len(migrations)},
        "rows": migrations,
    }
    g3b.dump_atomic(migration_path, migration)

    asset_addendum = g3b.load(g3b.SITE / "source-assets" / "g3b-content-asset-addendum.json")
    for asset in asset_addendum["assets"]:
        source = g3b.SITE / asset["source_path"]
        runtime = g3b.SITE / asset["runtime_path"]
        assert source.is_file() and runtime.is_file()
        assert not source.is_symlink() and not runtime.is_symlink()
        assert not os.path.samefile(source, runtime)
        assert source.stat().st_ino != runtime.stat().st_ino
        assert source.stat().st_nlink == runtime.stat().st_nlink == 1
        assert source.stat().st_size == runtime.stat().st_size == asset["bytes"]
        assert file_sha(source) == file_sha(runtime) == asset["sha256"]

    batch_reports = [
        g3b.load(g3b.SITE / row["report"])
        for row in index["batches"]
    ]
    aggregate = {
        "schema_version": "mit-ocw.g3b-content-addendum.v1",
        "capture_id": g3b.CAPTURE_ID, "created_at": g3b.now(),
        "does_not_modify_g1_evidence": True,
        "authority": "four-create-only-current-direct-anonymous-same-origin-get-batches",
        "authoritative_interface_audit": batch_reports[0]["authoritative_interface_audit"],
        "request_policy": batch_reports[0]["request_policy"],
        "closure": {
            "status": "closed", "routes_expected": g3b.TOTAL_ROUTES,
            "routes_captured": len(index["routes"]), "route_failures": 0,
            "http_200": sum(row["http_status"] == 200 for row in index["routes"].values()),
            "families": dict(sorted(actual_families.items())),
        },
        "content": {
            "raw_bytes": raw_bytes, "runtime_bytes": runtime_bytes,
            "source_visible_text_bytes": source_text_bytes,
            "runtime_visible_text_bytes": runtime_text_bytes,
            "unique_raw_sha256": len(raw_hashes), "unique_runtime_visible_text_sha256": len(content_hashes),
            "selector_counts": dict(sorted(selector_counts.items())),
            "selector_fallback_paths": sorted(fallback_paths),
            "fallback_note": "The four frozen legacy boundary URLs return an intentionally empty SSR page plus the OCW external-link modal; candidate renders the branded local boundary and preserves that current source response.",
        },
        "assets": {
            "new_retained": len(asset_addendum["assets"]),
            "new_bytes": sum(int(row["bytes"]) for row in asset_addendum["assets"]),
            "unavailable": len(asset_addendum["unavailable"]),
            "unavailable_map": asset_addendum["unavailable"],
        },
        "sanitization": {
            "rewrite_totals": dict(sorted(sum((Counter(row["sanitize_rewrite_totals"]) for row in batch_reports), Counter()).items())),
            "runtime_remote_requests": 0, "external_asset_requests": 0,
            "post_requests": 0, "video_policy": "static-disabled",
        },
        "batches": index["batches"], "corrections": index.get("corrections", []),
        "index_migration": g3b.relative(migration_path),
    }
    g3b.dump_atomic(aggregate_path, aggregate)
    index["source_hash_migration"] = g3b.relative(migration_path)
    index["aggregate_report"] = g3b.relative(aggregate_path)
    index["phase"] = "closed"
    index["updated_at"] = g3b.now()
    g3b.dump_atomic(index_path, index, compact=True)

    data["phase"] = "g3b-route-content-closed"
    data["g3b_content"].update({
        "status": "closed", "routes": g3b.TOTAL_ROUTES,
        "aggregate_report": g3b.relative(aggregate_path),
        "source_hash_migration": g3b.relative(migration_path),
        "raw_bytes": raw_bytes, "runtime_bytes": runtime_bytes,
        "visual_status": "deferred-except-existing-g3a-two-p0-contracts",
        "formal_acceptance_status": "not-run",
    })
    g3b.dump_atomic(data_path, data, compact=True)
    return {
        "status": "closed", "routes": len(index["routes"]),
        "families": dict(sorted(actual_families.items())),
        "raw_bytes": raw_bytes, "runtime_bytes": runtime_bytes,
        "selector_fallbacks": len(fallback_paths), "source_hash_migrations": len(migrations),
        "new_assets": len(asset_addendum["assets"]),
        "report": g3b.relative(aggregate_path),
    }


def repair_manifest_schema() -> dict[str, object]:
    """Project addendum provenance records onto the strict asset schema."""
    path = g3b.SITE / "source-assets" / "manifest.json"
    manifest = g3b.load(path)
    repaired = 0
    for asset in manifest["assets"]:
        if not str(asset.get("id", "")).startswith("g3b-"):
            continue
        asset["evidence_kind"] = "current-direct"
        for extra in ("captured_at", "final_url", "http_status"):
            asset.pop(extra, None)
        repaired += 1
    assert repaired == 40
    g3b.dump_atomic(path, manifest)
    return {"status": "schema-projected", "assets": repaired, "manifest_assets": len(manifest["assets"])}


def finalize_correction_v2() -> dict[str, object]:
    """Publish an immutable aggregate for the four post-finalize v2 batches."""
    index_path = g3b.CLONE / "content-index.json"
    index = g3b.load(index_path)
    report_path = g3b.SITE / "source-current" / "g3b-content-corrections-v2" / "report.json"
    if report_path.exists():
        raise SystemExit(f"create-only correction aggregate already exists: {report_path}")
    batch_rows = [
        row for row in index.get("corrections", [])
        if str(row["correction_id"]).startswith("g3b-runtime-correction-v2-")
    ]
    assert len(batch_rows) == 4 and sum(int(row["routes"]) for row in batch_rows) == 732
    source_bytes = runtime_bytes = 0
    fallback_paths: list[str] = []
    for path, row in index["routes"].items():
        raw = g3b.SITE / row["raw_path"]
        runtime = g3b.SITE / row["runtime_path"]
        assert "/g3b-corrected-v2/" in f"/{row['runtime_path']}"
        assert raw.is_file() and runtime.is_file()
        assert file_sha(raw) == row["raw_sha256"]
        assert file_sha(runtime) == row["runtime_sha256"]
        fragment, selector, fallback = g3b.extract_fragment(raw.read_bytes(), row["family"])
        text = g3b.visible_text(fragment).encode()
        assert selector == row["content_selector"] and fallback == row["selector_fallback"]
        assert len(text) == row["source_visible_text_bytes"]
        assert hashlib.sha256(text).hexdigest() == row["source_visible_text_sha256"]
        markup = runtime.read_text(encoding="utf-8")
        assert "<style" not in markup.lower() and "<script" not in markup.lower()
        assert not any(token in markup for token in (".material-icons {", "@font-face {", "--bs-blue:"))
        source_bytes += len(text)
        runtime_bytes += runtime.stat().st_size
        if fallback:
            fallback_paths.append(path)
    report = {
        "schema_version": "mit-ocw.g3b-content-runtime-correction-aggregate.v2",
        "capture_id": g3b.CAPTURE_ID, "created_at": g3b.now(), "create_only": True,
        "does_not_modify_source_batches": True,
        "reason": "Drop style/script/media text, canonicalize slash aliases and the exact G2-A PDF edge, and publish balanced network-closed runtime fragments.",
        "closure": {"status": "closed", "routes": 732, "balanced": 732, "batches": 4},
        "source_visible_text_bytes": source_bytes,
        "runtime_bytes": runtime_bytes,
        "selector_fallback_paths": sorted(fallback_paths),
        "batch_reports": batch_rows,
        "runtime_remote_requests": 0,
    }
    g3b.dump_atomic(report_path, report)
    index["current_runtime_revision"] = "g3b-corrected-v2"
    index["correction_v2_report"] = g3b.relative(report_path)
    index["updated_at"] = g3b.now()
    g3b.dump_atomic(index_path, index, compact=True)
    data_path = g3b.CLONE / "site-data.json"
    data = g3b.load(data_path)
    data["g3b_content"].update({
        "current_runtime_revision": "g3b-corrected-v2",
        "current_runtime_report": g3b.relative(report_path),
        "current_runtime_bytes": runtime_bytes,
        "style_text_pollution": 0,
    })
    g3b.dump_atomic(data_path, data, compact=True)
    return {"status": "closed", "routes": 732, "batches": 4, "runtime_bytes": runtime_bytes, "report": g3b.relative(report_path)}


def restore_g2a_pdf() -> dict[str, object]:
    """Restore the G2-A exact PS1 payload as a site-owned streamed download."""
    data_path = g3b.CLONE / "site-data.json"
    data = g3b.load(data_path)
    pdf = data["pdf"]
    evidence = g3b.REPO / "artifacts" / "mit-opencourseware" / g3b.CAPTURE_ID / "ea1" / "safe-get-download" / "problem-set-1.pdf"
    assert evidence.is_file() and evidence.stat().st_size == pdf["bytes"]
    assert file_sha(evidence) == pdf["sha256"]
    target = g3b.SITE / "runtime-downloads" / str(pdf["sha256"]) / "0000.part"
    report = g3b.SITE / "source-current" / "g3b-g2a-pdf-restoration" / "report.json"
    if target.exists() or report.exists():
        raise SystemExit("create-only G2-A PDF restoration already exists")
    target.parent.mkdir(parents=True)
    shutil.copyfile(evidence, target)
    assert target.stat().st_nlink == 1 and not target.is_symlink()
    assert target.stat().st_size == pdf["bytes"] and file_sha(target) == pdf["sha256"]
    pdf["runtime_path"] = g3b.relative(target)
    pdf["provenance_report"] = g3b.relative(report)
    g3b.dump_atomic(report, {
        "schema_version": "mit-ocw.g3b-g2a-exact-pdf-restoration.v1",
        "capture_id": g3b.CAPTURE_ID, "created_at": g3b.now(), "create_only": True,
        "reason": "Restore the exact G2-A 6.006 problem-set payload removed as an undeclared presentation-asset orphan during G2-B; keep it outside the presentation asset manifest and outside the 480-download G2-B denominator.",
        "source_evidence": evidence.relative_to(g3b.REPO).as_posix(),
        "runtime_path": g3b.relative(target), "source_url": pdf["source_url"],
        "bytes": pdf["bytes"], "sha256": pdf["sha256"], "mime_type": "application/pdf",
        "g2b_download_denominator_unchanged": True,
    })
    g3b.dump_atomic(data_path, data, compact=True)
    return {"status": "restored", "bytes": pdf["bytes"], "sha256": pdf["sha256"], "runtime_path": pdf["runtime_path"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--finalize", action="store_true")
    choice.add_argument("--repair-manifest-schema", action="store_true")
    choice.add_argument("--finalize-correction-v2", action="store_true")
    choice.add_argument("--restore-g2a-pdf", action="store_true")
    args = parser.parse_args()
    if args.repair_manifest_schema:
        result = repair_manifest_schema()
    elif args.finalize_correction_v2:
        result = finalize_correction_v2()
    elif args.restore_g2a_pdf:
        result = restore_g2a_pdf()
    else:
        result = finalize()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
