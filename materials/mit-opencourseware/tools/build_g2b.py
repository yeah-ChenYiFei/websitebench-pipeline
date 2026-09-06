"""Mechanically build G2-B from the immutable, fixed G1 capture.

With ``--inventory-only`` this script is strictly read-only and validates every
business denominator before any large payload is materialized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

from websitebench.offline_clone.assets import inspect_asset


SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parents[1]
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
CAPTURE = REPO / "artifacts" / "mit-opencourseware" / CAPTURE_ID
G1 = CAPTURE / "g1"
CHUNK_BYTES = 15 * 1024 * 1024


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: object, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(value, ensure_ascii=False, indent=2)
    path.write_text(encoded + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def compact_route_rows() -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    boundary = load(G1 / "business-contracts" / "scope-boundary-contract.json")
    report_cache: dict[str, dict[str, object]] = {}
    page_cache: dict[str, dict[str, dict[str, object]]] = {}
    routes: dict[str, dict[str, object]] = {}
    route_instances: list[dict[str, object]] = []
    for source in boundary["full_route_instances"]:
        report_name = source["evidence_report"]
        if report_name not in report_cache:
            report_cache[report_name] = load(CAPTURE / report_name)
            page_cache[report_name] = {str(page["id"]): page for page in report_cache[report_name].get("pages", [])}
        page = page_cache[report_name][source["page_id"]]
        dom = page.get("dom_structure") or {}
        headings = [
            {"level": int(row["level"]), "text": str(row["text"])}
            for row in dom.get("headings", [])
            if row.get("text")
        ]
        landmarks = [
            {key: str(row.get(key, "")) for key in ("kind", "label", "role")}
            for row in dom.get("regions", [])
        ]
        links: list[dict[str, str]] = []
        seen_links: set[tuple[str, str]] = set()
        for link in page.get("links", []):
            url = link.get("url")
            if not isinstance(url, str) or not url:
                continue
            key = (str(link.get("text") or ""), url)
            if key in seen_links:
                continue
            seen_links.add(key)
            links.append({"text": key[0], "url": key[1]})
        row: dict[str, object] = {
            "path": source["path"],
            "title": source["title"],
            "status": source["http_status"],
            "family": source["family"],
            "page_id": source["page_id"],
            "source_url": source["source_url"],
            "evidence_report": report_name,
            "observed_title": dom.get("title"),
            "lang": dom.get("lang"),
            "node_count": dom.get("node_count"),
            "headings": headings,
            "landmarks": landmarks,
            "links": links,
        }
        for visible_key in ("visible_text", "body_text"):
            if isinstance(page.get(visible_key), str):
                row[visible_key] = page[visible_key]
        assert page["http_status"] == source["http_status"]
        assert page["final_url"].rstrip("/") == source["source_url"].rstrip("/")
        routes[source["path"]] = row
        route_instances.append({key: row[key] for key in ("path", "title", "status", "family", "page_id", "source_url")})
    assert len(routes) == len(route_instances) == 732
    return routes, route_instances


def materialize_presentation_assets() -> tuple[list[dict[str, object]], dict[str, dict[str, object]], dict[str, str], dict[str, dict[str, object]]]:
    manifest_assets: list[dict[str, object]] = []
    runtime_assets: dict[str, dict[str, object]] = {}
    url_map: dict[str, str] = {}
    unavailable: dict[str, dict[str, object]] = {}
    for source_set in ("first-party-static-assets", "authorized-static-assets"):
        report_path = G1 / source_set / "report.json"
        report = load(report_path)
        for item in report["items"]:
            url = str(item["url"])
            if item.get("status") == 404:
                unavailable[url] = {
                    "status": 404,
                    "reason": str(item.get("error") or "source-http-404"),
                    "source_report": f"g1/{source_set}/report.json",
                    "capture_id": CAPTURE_ID,
                }
                continue
            assert item["status"] == 200
            evidence = G1 / source_set / item["file"]
            suffix = evidence.suffix.lower()
            logical_name = f"{item['sha256']}{suffix}"
            source_path = SITE / "source-assets" / "presentation" / logical_name
            runtime_path = SITE / "runtime-assets" / "presentation" / logical_name
            source_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(evidence, source_path)
            shutil.copyfile(evidence, runtime_path)
            source_stat = source_path.stat()
            runtime_stat = runtime_path.stat()
            assert not source_path.is_symlink() and not runtime_path.is_symlink()
            assert source_stat.st_ino != runtime_stat.st_ino
            assert source_stat.st_size == runtime_stat.st_size == item["bytes"]
            assert digest(source_path) == digest(runtime_path) == item["sha256"]
            source_info = inspect_asset(source_path)
            runtime_info = inspect_asset(runtime_path)
            assert source_info == runtime_info
            assert source_info["mime_type"] == item["content_type"]
            references = sorted({str(ref.get("manifest")) for ref in item.get("observed_references", []) if ref.get("manifest")})
            if not references:
                references = [f"g1/{source_set}/report.json"]
            local_url = f"/presentation-assets/{logical_name}"
            manifest_assets.append({
                "id": f"asset-{item['sha256']}",
                "priority": "p0",
                "required": True,
                "source_path": source_path.relative_to(SITE).as_posix(),
                "runtime_path": runtime_path.relative_to(SITE).as_posix(),
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "mime_type": item["content_type"],
                "dimensions": source_info["dimensions"],
                "referenced_by": references,
                "evidence_kind": "current-direct",
                "source_url": url,
                "capture_id": CAPTURE_ID,
            })
            runtime_assets[logical_name] = {
                "runtime_path": runtime_path.relative_to(SITE).as_posix(),
                "mime_type": item["content_type"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            url_map[url] = local_url
    assert len(manifest_assets) == len(runtime_assets) == len(url_map) == 231
    assert sum(int(item["bytes"]) for item in manifest_assets) == 35_298_609
    assert len(unavailable) == 5
    return manifest_assets, runtime_assets, url_map, unavailable


def materialize_assets_routes() -> dict[str, object]:
    routes, route_instances = compact_route_rows()
    manifest_assets, runtime_assets, url_map, unavailable = materialize_presentation_assets()
    data_path = SITE / "clone" / "site-data.json"
    data = load(data_path)
    data.update({
        "phase": "g2b-assets-routes-closed",
        "pages": routes,
        "route_instances": route_instances,
        "route_denominator": {"status": "closed", "logical": 732, "unique_paths": 732},
        "presentation_assets": runtime_assets,
        "asset_url_map": url_map,
        "unavailable_assets": unavailable,
        "presentation_asset_denominator": {"status": "closed", "retained": 231, "bytes": 35_298_609, "source_404": 5},
    })
    logo_url = "https://ocw.mit.edu/static_shared/images/ocw_logo_white.cabdc9a745b03db3dad4.svg"
    data["shell_assets"] = {"logo": url_map[logo_url]}
    for course in data["catalog"]["courses"]:
        if course["image_url"] in url_map:
            course["local_image"] = url_map[course["image_url"]]
    dump(data_path, data, compact=True)
    dump(SITE / "source-assets" / "manifest.json", {
        "schema_version": "offline-clone.assets.v1",
        "snapshot_id": "mit-opencourseware-g2b-20260903",
        "created_at": "2026-09-03T06:30:00Z",
        "remote_runtime_policy": "forbidden",
        "closure_status": "declared",
        "no_assets_reason": None,
        "assets": manifest_assets,
    })
    return {
        "route_instances": len(route_instances),
        "route_data_bytes": data_path.stat().st_size,
        "assets": len(manifest_assets),
        "asset_bytes": sum(int(item["bytes"]) for item in manifest_assets),
        "unavailable": len(unavailable),
        "status": "assets-routes-materialized",
    }


def enrich_page_asset_index() -> dict[str, object]:
    """Bind assets only to the exact capture report that observed them."""
    data_path = SITE / "clone" / "site-data.json"
    data = load(data_path)
    retained = data.get("asset_url_map", {})
    unavailable = data.get("unavailable_assets", {})
    known_urls = set(retained) | set(unavailable)
    report_names = sorted({
        str(row["evidence_report"])
        for row in data.get("pages", {}).values()
        if row.get("evidence_report")
    })
    reports: dict[str, list[dict[str, object]]] = {}
    retained_refs = 0
    unavailable_refs = 0
    for report_name in report_names:
        report_path = CAPTURE / report_name
        report = load(report_path)
        index_path = Path(str(report.get("localized_asset_index", "")))
        if not index_path.is_absolute():
            index_path = report_path.parent / index_path
        index_path = index_path.resolve()
        if not index_path.is_relative_to(CAPTURE.resolve()):
            raise AssertionError(f"asset index escapes capture root: {index_path}")
        index = load(index_path)
        refs: list[dict[str, object]] = []
        seen: set[str] = set()
        for asset in index.get("assets", []):
            url = str(asset.get("url", ""))
            if not url or url in seen or url not in known_urls:
                continue
            seen.add(url)
            ref: dict[str, object] = {
                "url": url,
                "kind": str(asset.get("kind", "")),
                "alt": str(asset.get("alt", "")),
            }
            if url in retained:
                ref["status"] = 200
                ref["local_url"] = retained[url]
                retained_refs += 1
            else:
                ref["status"] = 404
                unavailable_refs += 1
            refs.append(ref)
        reports[report_name] = refs
    data["asset_reports"] = reports
    dump(data_path, data, compact=True)
    return {
        "asset_report_count": len(reports),
        "asset_report_retained_refs": retained_refs,
        "asset_report_unavailable_refs": unavailable_refs,
    }


def clean_g2a_asset_remainders(manifest: dict[str, object]) -> list[str]:
    removed: list[str] = []
    referenced = {
        str(asset[field])
        for asset in manifest["assets"]
        for field in ("source_path", "runtime_path")
    }
    for relative in ("source-assets/g2a", "runtime-assets/g2a"):
        target = SITE / relative
        assert target.parent.parent.resolve() == SITE.resolve()
        assert not target.is_symlink()
        assert not any(path == relative or path.startswith(relative + "/") for path in referenced)
        if target.exists():
            assert target.is_dir()
            shutil.rmtree(target)
            removed.append(relative)
    return removed


def materialize_downloads() -> dict[str, object]:
    source_reports = (
        ("home-course-files", G1 / "home-course-files" / "report.json"),
        ("catalog-attachments", G1 / "catalog-attachments" / "report.json"),
    )
    logical: list[dict[str, object]] = []
    source_by_sha: dict[str, Path] = {}
    seen_paths: set[str] = set()
    for source_set, report_path in source_reports:
        report = load(report_path)
        for item in report["items"]:
            assert item["valid"] is True and item["status"] == 200
            path = urlsplit(item["url"]).path
            assert path.startswith("/") and path not in seen_paths
            seen_paths.add(path)
            source_by_sha.setdefault(item["sha256"], G1 / source_set / item["file"])
            logical.append({
                "url": item["url"],
                "path": path,
                "filename": unquote(Path(path).name),
                "content_type": item["content_type"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "source_set": source_set,
                "source_report": f"g1/{source_set}/report.json",
                "evidence_file": item["file"],
            })
    assert len(logical) == len(seen_paths) == 480
    assert len(source_by_sha) == 478
    assert sum(int(row["bytes"]) for row in logical) == 1_551_223_348

    chunks_by_sha: dict[str, list[dict[str, object]]] = {}
    total_physical_bytes = 0
    maximum_source_bytes = 0
    maximum_chunk_bytes = 0
    for position, (sha256, source) in enumerate(sorted(source_by_sha.items()), start=1):
        source_size = source.stat().st_size
        maximum_source_bytes = max(maximum_source_bytes, source_size)
        target_dir = SITE / "runtime-downloads" / sha256
        assert target_dir.parent.resolve() == (SITE / "runtime-downloads").resolve()
        assert not target_dir.is_symlink()
        target_dir.mkdir(parents=True, exist_ok=True)
        source_hash = hashlib.sha256()
        chunk_rows: list[dict[str, object]] = []
        expected_paths: set[Path] = set()
        with source.open("rb") as reader:
            index = 0
            while True:
                block = reader.read(CHUNK_BYTES)
                if not block:
                    break
                source_hash.update(block)
                chunk_path = target_dir / f"{index:04d}.part"
                expected_paths.add(chunk_path)
                with chunk_path.open("wb") as writer:
                    writer.write(block)
                chunk_stat = chunk_path.stat()
                assert not chunk_path.is_symlink() and chunk_stat.st_nlink == 1
                assert 0 < chunk_stat.st_size <= CHUNK_BYTES
                maximum_chunk_bytes = max(maximum_chunk_bytes, chunk_stat.st_size)
                chunk_rows.append({
                    "path": chunk_path.relative_to(SITE).as_posix(),
                    "bytes": chunk_stat.st_size,
                    "sha256": hashlib.sha256(block).hexdigest(),
                })
                index += 1
        assert source_hash.hexdigest() == sha256
        assert sum(int(row["bytes"]) for row in chunk_rows) == source_size
        reconstructed_hash = hashlib.sha256()
        reconstructed_bytes = 0
        for row in chunk_rows:
            chunk_path = SITE / str(row["path"])
            with chunk_path.open("rb") as reader:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    reconstructed_hash.update(block)
                    reconstructed_bytes += len(block)
        assert reconstructed_bytes == source_size
        assert reconstructed_hash.hexdigest() == sha256
        for stale in target_dir.glob("*.part"):
            if stale not in expected_paths:
                assert stale.parent == target_dir and not stale.is_symlink()
                stale.unlink()
        chunks_by_sha[sha256] = chunk_rows
        total_physical_bytes += source_size
        if position % 50 == 0:
            print(f"validated {position}/478 unique payloads", flush=True)

    by_path: dict[str, dict[str, object]] = {}
    for row in logical:
        enriched = {**row, "chunks": chunks_by_sha[str(row["sha256"])]}
        by_path[str(row["path"])] = enriched
    assert len(by_path) == 480
    assert maximum_chunk_bytes <= CHUNK_BYTES
    assert total_physical_bytes == sum(path.stat().st_size for path in source_by_sha.values())

    data_path = SITE / "clone" / "site-data.json"
    data = load(data_path)
    data["phase"] = "g2b-downloads-closed"
    data["downloads"] = by_path
    data["download_denominator"] = {
        "status": "closed",
        "logical": 480,
        "unique_sha256": 478,
        "logical_bytes": 1_551_223_348,
        "physical_bytes": total_physical_bytes,
        "chunks": sum(len(rows) for rows in chunks_by_sha.values()),
        "maximum_chunk_bytes": maximum_chunk_bytes,
        "maximum_source_bytes": maximum_source_bytes,
    }
    if data["pdf"]["path"] in by_path:
        data["pdf"] = by_path[data["pdf"]["path"]]
    dump(data_path, data, compact=True)

    manifest = load(SITE / "source-assets" / "manifest.json")
    removed = clean_g2a_asset_remainders(manifest)
    return {
        "status": "downloads-materialized",
        "logical_downloads": len(logical),
        "unique_payloads": len(chunks_by_sha),
        "logical_bytes": sum(int(row["bytes"]) for row in logical),
        "physical_bytes": total_physical_bytes,
        "chunks": sum(len(rows) for rows in chunks_by_sha.values()),
        "maximum_chunk_bytes": maximum_chunk_bytes,
        "maximum_source_bytes": maximum_source_bytes,
        "removed_g2a_asset_directories": removed,
    }


def inventory() -> dict[str, object]:
    boundary = load(G1 / "business-contracts" / "scope-boundary-contract.json")
    invariant = load(G1 / "business-contracts" / "data-invariant-contract.json")
    routes = boundary["full_route_instances"]
    home_downloads = load(G1 / "home-course-files" / "report.json")["items"]
    catalog_downloads = load(G1 / "catalog-attachments" / "report.json")["items"]
    downloads = home_downloads + catalog_downloads
    first_party = load(G1 / "first-party-static-assets" / "report.json")
    authorized = load(G1 / "authorized-static-assets" / "report.json")
    retained_assets = [item for report in (first_party, authorized) for item in report["items"] if item.get("status") == 200]
    unavailable_assets = [item for report in (first_party, authorized) for item in report["items"] if item.get("status") == 404]

    assert boundary["capture_id"] == invariant["capture_id"] == CAPTURE_ID
    assert len(routes) == 732
    assert len(downloads) == 480
    assert len({item["sha256"] for item in downloads}) == 478
    assert sum(item["bytes"] for item in downloads) == 1_551_223_348
    assert len(retained_assets) == 231
    assert sum(item["bytes"] for item in retained_assets) == 35_298_609
    assert len(unavailable_assets) == 5
    assert all(item["valid"] and item["status"] == 200 for item in downloads)
    assert invariant["download_closure"]["logical_items"] == len(downloads)
    assert invariant["download_closure"]["unique_payload_hashes"] == len({item["sha256"] for item in downloads})
    assert invariant["download_closure"]["aggregate_logical_bytes"] == sum(item["bytes"] for item in downloads)

    evidence_cache: dict[str, dict[str, object]] = {}
    evidence_missing: list[dict[str, str]] = []
    for route in routes:
        report_name = route["evidence_report"]
        if report_name not in evidence_cache:
            evidence_cache[report_name] = load(CAPTURE / report_name)
        report = evidence_cache[report_name]
        pages = report.get("pages", [])
        if not any(page.get("id") == route["page_id"] for page in pages):
            evidence_missing.append({"page_id": route["page_id"], "report": report_name})
    assert not evidence_missing, evidence_missing[:10]

    return {
        "capture_id": CAPTURE_ID,
        "route_instances": len(routes),
        "unique_route_paths": len({row["path"] for row in routes}),
        "route_families": dict(sorted(Counter(row["family"] for row in routes).items())),
        "evidence_reports": len(evidence_cache),
        "evidence_rows_resolved": len(routes),
        "downloads": {
            "logical": len(downloads),
            "unique_sha256": len({item["sha256"] for item in downloads}),
            "logical_bytes": sum(item["bytes"] for item in downloads),
            "home": len(home_downloads),
            "catalog": len(catalog_downloads),
        },
        "presentation_assets": {
            "retained": len(retained_assets),
            "bytes": sum(item["bytes"] for item in retained_assets),
            "source_404": len(unavailable_assets),
        },
        "status": "inventory-closed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-only", action="store_true", help="validate immutable inputs without writing")
    parser.add_argument("--materialize-assets-routes", action="store_true", help="write only compact routes and presentation assets")
    parser.add_argument("--materialize-downloads", action="store_true", help="write only deduplicated runtime download chunks and compact mappings")
    parser.add_argument("--enrich-page-assets", action="store_true", help="bind retained assets to exact capture reports")
    args = parser.parse_args()
    result = inventory()
    if args.materialize_assets_routes:
        result = {**result, **materialize_assets_routes()}
    elif args.materialize_downloads:
        result = {**result, **materialize_downloads()}
    elif args.enrich_page_assets:
        result = {**result, **enrich_page_asset_index()}
    elif not args.inventory_only:
        parser.error("choose --inventory-only, --materialize-assets-routes, --materialize-downloads, or --enrich-page-assets")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
