"""Acquire six exact same-origin catalog-card images authorized for G3-C.

This is a create-only current-direct asset addendum.  It preserves the 278
existing manifest records byte-for-byte and issues GETs only for the six URLs
listed in ``ASSETS``.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from websitebench.offline_clone.assets import inspect_asset


SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parents[1]
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
OBSERVATION_REL = (
    "artifacts/mit-opencourseware/mit-opencourseware-20260903T032020Z/"
    "g1/search-authorized-matrix/report.json"
)
OBSERVATION = REPO / OBSERVATION_REL
OBSERVATION_SHA256 = "a918bc824c001a6d83308177a535fc1e258ea24ed590117c8fe0c0dd0acf8836"
ADDENDUM = SITE / "source-assets" / "g3c-catalog-asset-addendum.json"

ASSETS = [
    {
        "state": "math-undergraduate",
        "index": 0,
        "course_title": "Analysis I",
        "url": "https://ocw.mit.edu/courses/18-100b-analysis-i-fall-2010/5c88f9408009514f73f41d6b5d91fd13_18-100bf10.jpg",
    },
    {
        "state": "math-undergraduate",
        "index": 1,
        "course_title": "Differential Equations",
        "url": "https://ocw.mit.edu/courses/18-03-differential-equations-spring-2010/e51bbed857b0ae65e7536f120c1473d9_18-03s10.jpg",
    },
    {
        "state": "math-undergraduate",
        "index": 2,
        "course_title": "Probability and Random Variables",
        "url": "https://ocw.mit.edu/courses/18-440-probability-and-random-variables-spring-2014/73256e6260afadff2dc8f71302e4bff4_18-440s14.jpg",
    },
    {
        "state": "course-number",
        "index": 0,
        "course_title": "Single Variable Calculus",
        "url": "https://ocw.mit.edu/courses/18-01-single-variable-calculus-fall-2005/9c1339d31d8f122c6698a29e3a61a66e_18-01f05.jpg",
    },
    {
        "state": "course-number",
        "index": 1,
        "course_title": "Calculus I: Single Variable Calculus",
        "url": "https://ocw.mit.edu/courses/18-01-calculus-i-single-variable-calculus-fall-2020/18-01f20.jpg",
    },
    {
        "state": "course-number",
        "index": 2,
        "course_title": "Single Variable Calculus",
        "url": "https://ocw.mit.edu/courses/18-01-single-variable-calculus-fall-2006/24c4a7d9cd569a82ef34a8563e50add8_18-01f06.jpg",
    },
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: object, *, compact: bool = False) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        )
        + "\n",
        encoding="utf-8",
    )


def copy_distinct(source: Path, destination: Path) -> None:
    assert not destination.exists(), destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    assert destination.is_file() and not destination.is_symlink()
    assert source.stat().st_ino != destination.stat().st_ino
    assert destination.stat().st_nlink == 1
    assert digest(source) == digest(destination)


def acquire(url: str, destination: Path) -> tuple[str, str, int, str]:
    assert url in {str(row["url"]) for row in ASSETS}
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "WebsiteBench-MIT-OCW-G3C-Catalog/1.0", "Accept": "image/*"},
    )
    with urlopen(request, timeout=45) as response:  # noqa: S310 - six exact approved URLs
        status = int(response.status)
        final_url = response.geturl()
        content_type = response.headers.get_content_type()
        assert status == 200, (url, status)
        assert urlsplit(final_url).hostname in {"ocw.mit.edu", "www.ocw.mit.edu"}, final_url
        assert content_type.startswith("image/"), (url, content_type)
        with destination.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
    return final_url, content_type, destination.stat().st_size, digest(destination)


def main() -> None:
    if ADDENDUM.exists():
        raise SystemExit(f"create-only addendum already exists: {ADDENDUM}")

    assert OBSERVATION.is_file() and not OBSERVATION.is_symlink()
    assert digest(OBSERVATION) == OBSERVATION_SHA256
    observation_text = OBSERVATION.read_text(encoding="utf-8").replace("\\/", "/")
    assert all(str(row["url"]) in observation_text for row in ASSETS)
    assert len({str(row["url"]) for row in ASSETS}) == 6
    assert len({(str(row["state"]), int(row["index"])) for row in ASSETS}) == 6

    manifest_path = SITE / "source-assets" / "manifest.json"
    data_path = SITE / "clone" / "site-data.json"
    manifest = load(manifest_path)
    data = load(data_path)
    existing_assets = list(manifest["assets"])
    assert len(existing_assets) == 278
    existing_urls = {str(row["source_url"]) for row in existing_assets}
    assert not existing_urls.intersection(str(row["url"]) for row in ASSETS)
    assert "g3c_catalog_assets" not in data and "g3c_catalog_url_map" not in data
    prior_manifest_sha256 = canonical_digest(existing_assets)

    records: list[dict[str, object]] = []
    runtime_assets: dict[str, dict[str, object]] = {}
    url_map: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="mit-ocw-g3c-catalog-") as temporary:
        temp_root = Path(temporary)
        downloaded: list[tuple[dict[str, object], Path, str, str, int, str, dict[str, object]]] = []
        for ordinal, item in enumerate(ASSETS, start=1):
            temp = temp_root / f"asset-{ordinal}.jpg"
            final_url, response_type, byte_count, sha256 = acquire(str(item["url"]), temp)
            inspected = inspect_asset(temp)
            mime_type = str(inspected["mime_type"])
            assert mime_type == response_type or {mime_type, response_type} <= {"image/jpeg", "image/jpg"}
            downloaded.append((item, temp, final_url, response_type, byte_count, sha256, inspected))

        for item, temp, final_url, response_type, byte_count, sha256, inspected in downloaded:
            mime_type = str(inspected["mime_type"])
            suffix = mimetypes.guess_extension(mime_type) or Path(urlsplit(final_url).path).suffix.lower()
            suffix = ".jpg" if suffix in {".jpe", ".jpeg"} else suffix
            name = f"{sha256}{suffix}"
            source_copy = SITE / "source-assets" / "g3c-catalog" / name
            runtime_copy = SITE / "runtime-assets" / "g3c-catalog" / name
            copy_distinct(temp, source_copy)
            copy_distinct(temp, runtime_copy)
            assert source_copy.stat().st_ino != runtime_copy.stat().st_ino
            local_url = f"/g3c-catalog-assets/{name}"
            manifest_record = {
                "id": f"g3c-catalog-{item['state']}-{int(item['index']) + 1}-{sha256[:12]}",
                "priority": "p0",
                "required": True,
                "source_path": source_copy.relative_to(SITE).as_posix(),
                "runtime_path": runtime_copy.relative_to(SITE).as_posix(),
                "bytes": byte_count,
                "sha256": sha256,
                "mime_type": mime_type,
                "dimensions": inspected["dimensions"],
                "referenced_by": [f"catalog.{item['state']}"],
                "evidence_kind": "current-direct-g3c-catalog-addendum",
                "source_url": item["url"],
                "capture_id": CAPTURE_ID,
            }
            records.append({
                **manifest_record,
                "state": item["state"],
                "card_index": item["index"],
                "course_title": item["course_title"],
                "requested_url": item["url"],
                "final_url": final_url,
                "http_status": 200,
                "response_content_type": response_type,
                "observed_in": OBSERVATION_REL,
                "observation_sha256": OBSERVATION_SHA256,
            })
            runtime_assets[name] = {
                "runtime_path": manifest_record["runtime_path"],
                "mime_type": mime_type,
                "bytes": byte_count,
                "sha256": sha256,
            }
            url_map[str(item["url"])] = local_url

    assert len(records) == len(runtime_assets) == len(url_map) == 6
    assert len({str(row["sha256"]) for row in records}) == 6
    manifest_only_keys = {
        "state", "card_index", "course_title", "requested_url", "final_url", "http_status",
        "response_content_type", "observed_in", "observation_sha256",
    }
    manifest["assets"].extend(
        {key: value for key, value in row.items() if key not in manifest_only_keys}
        for row in records
    )
    assert manifest["assets"][:278] == existing_assets
    assert canonical_digest(manifest["assets"][:278]) == prior_manifest_sha256
    assert len(manifest["assets"]) == 284
    assert len({str(row["id"]) for row in manifest["assets"]}) == 284

    data["g3c_catalog_assets"] = runtime_assets
    data["g3c_catalog_url_map"] = url_map
    data["g3c_catalog_asset_addendum"] = {
        "status": "g3c-current-direct-assets-imported",
        "assets": 6,
        "bytes": sum(int(row["bytes"]) for row in records),
        "provenance": ADDENDUM.relative_to(SITE).as_posix(),
    }
    report = {
        "schema_version": "mit-ocw.g3c-catalog-asset-addendum.v1",
        "capture_id": CAPTURE_ID,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": "six-exact-same-origin-static-get-current-direct-addendum",
        "request_policy": {
            "allowed_method": "GET",
            "allowed_urls": [str(row["url"]) for row in ASSETS],
            "other_requests": 0,
        },
        "does_not_modify_prior_278_manifest_records": True,
        "prior_manifest_assets_sha256": prior_manifest_sha256,
        "observed_in": OBSERVATION_REL,
        "observation_sha256": OBSERVATION_SHA256,
        "assets": records,
    }
    dump(manifest_path, manifest)
    dump(data_path, data, compact=True)
    dump(ADDENDUM, report)
    print(json.dumps({
        "status": "g3c-catalog-assets-acquired",
        "requests": len(records),
        "assets": len(records),
        "bytes": sum(int(row["bytes"]) for row in records),
        "manifest_assets": len(manifest["assets"]),
        "sha256": [row["sha256"] for row in records],
    }, indent=2))


if __name__ == "__main__":
    main()
