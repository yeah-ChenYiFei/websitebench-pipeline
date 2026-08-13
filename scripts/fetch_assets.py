"""Download frozen source assets and build/merge the offline-clone asset
manifest for one site.

Spec JSON (clawbench.asset-fetch-spec.v1):
{
  "site_id": "edx",
  "capture_id": "edx-public-readonly-2026-07-25",
  "capture_date": "2026-07-25",
  "entries": [
    {"url": "https://.../logo.svg", "page": "home", "priority": "p0",
     "required": true, "referenced_by": ["/", "shared-header"],
     "evidence_kind": "current-direct", "name": "edx-logo.svg"}
  ]
}

Source copy:  materials/<site>/source-assets/<date>/<page>/<name>
Runtime copy: materials/<site>/clone/static/assets/source-current/<date>/<page>/<name>
Manifest:     materials/<site>/source-assets/manifest.json (offline-clone.assets.v1)

GET-only, anonymous. Assets failing content inspection (HTML shells, active
SVG, broken images, CSS with external refs) are skipped and reported, never
silently shipped. Use `--jobs 16 --per-origin-jobs 6 --resume` for the bounded
v3 fast path; the default remains the legacy serial behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Lock
from urllib.parse import unquote, urlparse

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from websitebench.offline_clone.assets import inspect_asset  # noqa: E402
from websitebench.offline_clone.asset_cache import (  # noqa: E402
    AssetPayloadCache,
    write_bytes_if_changed,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sanitize_name(url: str, override: str | None) -> str:
    if override:
        return SAFE_NAME.sub("-", override)[:120]
    path = unquote(urlparse(url).path)
    base = path.rsplit("/", 1)[-1] or "asset"
    base = SAFE_NAME.sub("-", base)[:100]
    if "." not in base:
        base += ".bin"
    return base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(".clone-harness/asset-cache"),
        help="shared content-addressed cache, relative to the repository by default",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ignore URL cache entries and fetch a fresh anonymous source response",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="never use the network; report cache misses as skipped",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="global concurrent download jobs (1-16; default keeps legacy serial behavior)",
    )
    parser.add_argument(
        "--per-origin-jobs",
        type=int,
        default=6,
        help="maximum concurrent requests to one origin (1-6)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume from the manifest and content-addressed cache (already the safe default)",
    )
    parser.add_argument(
        "--import-network-log",
        type=Path,
        action="append",
        default=[],
        help="append captured image/font/stylesheet/media response URLs to the fetch set",
    )
    args = parser.parse_args()
    if args.refresh and args.cache_only:
        parser.error("--refresh and --cache-only cannot be combined")
    if not 1 <= args.jobs <= 16:
        parser.error("--jobs must be between 1 and 16")
    if not 1 <= args.per_origin_jobs <= 6:
        parser.error("--per-origin-jobs must be between 1 and 6")
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    site_id = spec["site_id"]
    capture_id = spec["capture_id"]
    date = spec.get("capture_date", "2026-07-25")
    if not isinstance(site_id, str) or not SAFE_SEGMENT.fullmatch(site_id):
        raise SystemExit("spec site_id must be one safe path segment")
    if not isinstance(date, str) or not SAFE_SEGMENT.fullmatch(date):
        raise SystemExit("spec capture_date must be one safe path segment")
    site_root = REPO / "materials" / site_id
    manifest_path = site_root / "source-assets" / "manifest.json"
    cache_root = (
        args.cache_root
        if args.cache_root.is_absolute()
        else REPO / args.cache_root
    )
    cache = AssetPayloadCache(cache_root)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {}
    assets: list[dict] = [
        asset
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict)
    ]
    known_urls = {asset.get("source_url") for asset in assets}
    used_names: set[str] = set()
    for asset in assets:
        used_names.add(asset["source_path"])

    entries = list(spec["entries"])
    captured_resource_types = {
        "image",
        "font",
        "stylesheet",
        "media",
    }
    for network_path in args.import_network_log:
        network = json.loads(network_path.read_text(encoding="utf-8"))
        rows = network if isinstance(network, list) else network.get("network", [])
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("status") != 200
                or row.get("resource_type") not in captured_resource_types
                or not isinstance(row.get("url"), str)
                or not row["url"].startswith(("https://", "http://"))
            ):
                continue
            entries.append(
                {
                    "url": row["url"],
                    "page": "network",
                    "priority": "p1",
                    "required": True,
                    "referenced_by": [
                        f"network:{row['resource_type']}"
                    ],
                    "evidence_kind": "current-direct",
                }
            )

    results = {
        "downloaded": [],
        "cache_hits": [],
        "skipped": [],
        "reused": [],
    }
    client = httpx.Client(
        headers=HEADERS,
        follow_redirects=True,
        timeout=args.timeout,
        limits=httpx.Limits(
            max_connections=args.jobs,
            max_keepalive_connections=args.jobs,
        ),
    )
    planned: list[dict] = []
    scheduled_urls = set(known_urls)
    for entry in entries:
        url = entry["url"]
        if url in scheduled_urls:
            results["reused"].append(url)
            continue
        scheduled_urls.add(url)
        page = SAFE_NAME.sub("-", entry.get("page", "shared"))
        name = sanitize_name(url, entry.get("name"))
        source_rel = f"source-assets/{date}/{page}/{name}"
        if source_rel in used_names:
            digest = hashlib.sha256(url.encode()).hexdigest()[:8]
            stem, dot, ext = name.rpartition(".")
            name = f"{stem or ext}-{digest}.{ext}" if dot else f"{name}-{digest}"
            source_rel = f"source-assets/{date}/{page}/{name}"
        runtime_rel = (
            f"clone/static/assets/source-current/{date}/{page}/{name}"
        )
        used_names.add(source_rel)
        planned.append(
            {
                "entry": entry,
                "url": url,
                "page": page,
                "source_rel": source_rel,
                "runtime_rel": runtime_rel,
            }
        )

    origin_semaphores: dict[str, BoundedSemaphore] = {}
    semaphore_lock = Lock()

    def origin_semaphore(url: str) -> BoundedSemaphore:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}".lower()
        with semaphore_lock:
            return origin_semaphores.setdefault(
                origin,
                BoundedSemaphore(args.per_origin_jobs),
            )

    def fetch_one(item: dict) -> dict:
        url = item["url"]
        try:
            payload = None if args.refresh else cache.get(url)
            fetched = payload is None
            if fetched and args.cache_only:
                return {
                    **item,
                    "payload": None,
                    "fetched": False,
                    "reason": "content-addressed cache miss",
                }
            if fetched:
                response = None
                with origin_semaphore(url):
                    for attempt in range(3):
                        response = client.get(url)
                        if response.status_code == 200:
                            break
                        if response.status_code not in {429, 503}:
                            break
                        retry_after = response.headers.get("retry-after", "")
                        try:
                            delay = min(float(retry_after), 10.0)
                        except ValueError:
                            delay = min(0.5 * (2**attempt), 4.0)
                        time.sleep(max(delay, 0.0))
                assert response is not None
                if response.status_code != 200:
                    return {
                        **item,
                        "payload": None,
                        "fetched": True,
                        "reason": f"http {response.status_code}",
                    }
                payload = response.content
            if not payload:
                return {
                    **item,
                    "payload": None,
                    "fetched": fetched,
                    "reason": "empty body",
                }
            return {
                **item,
                "payload": payload,
                "fetched": fetched,
                "reason": None,
            }
        except httpx.HTTPError as error:
            return {
                **item,
                "payload": None,
                "fetched": True,
                "reason": f"network: {error}",
            }

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        fetched_items = list(executor.map(fetch_one, planned))

    for item in fetched_items:
        entry = item["entry"]
        url = item["url"]
        payload = item["payload"]
        fetched = item["fetched"]
        if payload is None:
            results["skipped"].append(
                {"url": url, "reason": item["reason"]}
            )
            continue
        source_rel = item["source_rel"]
        runtime_rel = item["runtime_rel"]
        page = item["page"]
        try:
            source_path = site_root / source_rel
            runtime_path = site_root / runtime_rel
            write_bytes_if_changed(source_path, payload)
            try:
                info = inspect_asset(source_path)
            except ValueError as error:
                source_path.unlink(missing_ok=True)
                results["skipped"].append(
                    {"url": url, "reason": f"inspect: {error}"}
                )
                continue
            write_bytes_if_changed(runtime_path, payload)
            cache.put(url, payload)
            asset_id = (
                f"{page}.{len(assets):03d}."
                f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]}"
            )
            assets.append(
                {
                    "id": asset_id,
                    "priority": entry.get("priority", "p1"),
                    "required": bool(entry.get("required", True)),
                    "source_path": source_rel,
                    "runtime_path": runtime_rel,
                    "bytes": info["bytes"],
                    "mime_type": info["mime_type"],
                    "dimensions": info["dimensions"],
                    "referenced_by": list(entry.get("referenced_by", [])),
                    "evidence_kind": entry.get(
                        "evidence_kind", "current-direct"
                    ),
                    "source_url": url,
                    "capture_id": capture_id,
                }
            )
            known_urls.add(url)
            result_row = {
                "url": url,
                "path": source_rel,
                "bytes": info["bytes"],
            }
            results["downloaded" if fetched else "cache_hits"].append(result_row)
        except httpx.HTTPError as error:
            results["skipped"].append(
                {"url": url, "reason": f"network: {error}"}
            )
    client.close()

    manifest = {
        "schema_version": "offline-clone.assets.v1",
        "snapshot_id": f"{site_id}-source-assets-{date}",
        "created_at": f"{date}T12:00:00-04:00",
        "remote_runtime_policy": "forbidden",
        "closure_status": "declared" if assets else "pending",
        "no_assets_reason": None,
        "assets": assets,
    }
    manifest_changed = False
    if manifest != (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else None
    ):
        manifest_changed = write_bytes_if_changed(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"),
        )
    print(
        json.dumps(
            {
                "site_id": site_id,
                "downloaded": len(results["downloaded"]),
                "cache_hits": len(results["cache_hits"]),
                "reused": len(results["reused"]),
                "skipped": results["skipped"],
                "total_assets": len(assets),
                "manifest_changed": manifest_changed,
                "jobs": args.jobs,
                "per_origin_jobs": args.per_origin_jobs,
                "network_logs_imported": len(args.import_network_log),
                "manifest": str(manifest_path.relative_to(REPO)),
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
