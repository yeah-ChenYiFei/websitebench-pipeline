"""Acquire the four same-origin collection-card images authorized for G3-C v6.

This is a create-only current-direct addendum.  It does not alter G1 evidence or
the G3-B raw page; it records the exact frozen raw page that declared each URL.
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
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
RAW_REL = "source-current/g3b-content/batch-01/raw/361c4012e29218244ae1.html"
RAW_SHA256 = "36c9a1e1012ab2be186595a55ca380d453e5a90e2c736664731db420acaab935"
ADDENDUM = SITE / "source-assets" / "g3c-collection-asset-addendum.json"
ASSETS = [
    {
        "course_code": "6.100L",
        "url": "https://ocw.mit.edu/courses/6-100l-introduction-to-cs-and-programming-using-python-fall-2022/mit6_100l_f22.jpeg",
    },
    {
        "course_code": "6.0001",
        "url": "https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/bb7bc760922abfcd37f5d8b9203d771f_6-0001f16.jpg",
    },
    {
        "course_code": "6.0002",
        "url": "https://ocw.mit.edu/courses/6-0002-introduction-to-computational-thinking-and-data-science-fall-2016/d9b969b1e9e2029d7e9b9e2c9324dde4_6-0002f16.jpg",
    },
    {
        "course_code": "6.S095",
        "url": "https://ocw.mit.edu/courses/6-s095-programming-for-the-puzzled-january-iap-2018/8a47e175cc72845e080f083fcfbc7c29_6-S095IAP18.jpg",
    },
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


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
    assert digest(source) == digest(destination)


def acquire(url: str, destination: Path) -> tuple[str, str, int, str]:
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "WebsiteBench-MIT-OCW-G3C/1.0", "Accept": "image/*"},
    )
    with urlopen(request, timeout=45) as response:  # noqa: S310 - exact approved URLs
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

    raw = SITE / RAW_REL
    assert raw.is_file() and not raw.is_symlink()
    assert digest(raw) == RAW_SHA256
    raw_text = raw.read_text(encoding="utf-8").replace("\\/", "/")
    assert all(str(item["url"]).removeprefix("https://ocw.mit.edu") in raw_text for item in ASSETS)

    manifest_path = SITE / "source-assets" / "manifest.json"
    data_path = SITE / "clone" / "site-data.json"
    manifest = load(manifest_path)
    data = load(data_path)
    existing_urls = {str(item["source_url"]) for item in manifest["assets"]}
    assert not existing_urls.intersection(str(item["url"]) for item in ASSETS)

    records: list[dict[str, object]] = []
    runtime_assets: dict[str, dict[str, object]] = {}
    url_map: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="mit-ocw-g3c-collection-") as temporary:
        temp_root = Path(temporary)
        for index, item in enumerate(ASSETS, start=1):
            temp = temp_root / f"asset-{index}{Path(urlsplit(str(item['url'])).path).suffix.lower()}"
            final_url, header_mime, byte_count, sha256 = acquire(str(item["url"]), temp)
            inspected = inspect_asset(temp)
            mime_type = str(inspected["mime_type"])
            assert mime_type == header_mime or {mime_type, header_mime} <= {"image/jpeg", "image/jpg"}
            suffix = mimetypes.guess_extension(mime_type) or Path(urlsplit(final_url).path).suffix.lower()
            suffix = ".jpg" if suffix in {".jpe", ".jpeg"} else suffix
            name = f"{sha256}{suffix}"
            source_copy = SITE / "source-assets" / "g3c-collection" / name
            runtime_copy = SITE / "runtime-assets" / "g3c-collection" / name
            copy_distinct(temp, source_copy)
            copy_distinct(temp, runtime_copy)
            assert source_copy.stat().st_ino != runtime_copy.stat().st_ino
            local_url = f"/g3c-collection-assets/{name}"
            record = {
                "id": f"g3c-collection-{item['course_code'].lower().replace('.', '-')}-{sha256[:12]}",
                "priority": "p0",
                "required": True,
                "source_path": source_copy.relative_to(SITE).as_posix(),
                "runtime_path": runtime_copy.relative_to(SITE).as_posix(),
                "bytes": byte_count,
                "sha256": sha256,
                "mime_type": mime_type,
                "dimensions": inspected["dimensions"],
                "referenced_by": ["collection.default"],
                "evidence_kind": "current-direct-g3c-addendum",
                "source_url": item["url"],
                "capture_id": CAPTURE_ID,
            }
            records.append({
                **record,
                "course_code": item["course_code"],
                "requested_url": item["url"],
                "final_url": final_url,
                "http_status": 200,
                "response_content_type": header_mime,
                "declared_by_raw_path": RAW_REL,
                "declared_by_raw_sha256": RAW_SHA256,
            })
            runtime_assets[name] = {
                "runtime_path": record["runtime_path"],
                "mime_type": mime_type,
                "bytes": byte_count,
                "sha256": sha256,
            }
            url_map[str(item["url"])] = local_url

    assert len(records) == len(runtime_assets) == len(url_map) == 4
    assert len({str(item["sha256"]) for item in records}) == 4
    manifest["assets"].extend(
        {key: value for key, value in item.items() if key not in {
            "course_code", "requested_url", "final_url", "http_status",
            "response_content_type", "declared_by_raw_path", "declared_by_raw_sha256",
        }}
        for item in records
    )
    assert len({item["id"] for item in manifest["assets"]}) == len(manifest["assets"])
    data["g3c_collection_assets"] = runtime_assets
    data["g3c_collection_url_map"] = url_map
    data["g3c_collection_asset_addendum"] = {
        "status": "g3c-v6-current-direct-assets-imported",
        "assets": 4,
        "bytes": sum(int(item["bytes"]) for item in records),
        "provenance": ADDENDUM.relative_to(SITE).as_posix(),
    }
    report = {
        "schema_version": "mit-ocw.g3c-collection-asset-addendum.v1",
        "capture_id": CAPTURE_ID,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": "same-origin-asset-only-current-direct-addendum",
        "does_not_modify_g1_or_g3b_evidence": True,
        "source_route": "https://ocw.mit.edu/collections/introductory-programming/",
        "declared_by_raw_path": RAW_REL,
        "declared_by_raw_sha256": RAW_SHA256,
        "assets": records,
    }
    dump(manifest_path, manifest)
    dump(data_path, data, compact=True)
    dump(ADDENDUM, report)
    print(json.dumps({
        "status": "g3c-collection-assets-acquired",
        "assets": len(records),
        "bytes": sum(int(item["bytes"]) for item in records),
        "manifest_assets": len(manifest["assets"]),
        "sha256": [item["sha256"] for item in records],
    }, indent=2))


if __name__ == "__main__":
    main()
