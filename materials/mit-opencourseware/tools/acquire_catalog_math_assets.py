"""Acquire four current same-origin images for frozen Mathematics cards.

The exact image URLs and course identities come from the authorized current
search observation.  This create-only addendum preserves the existing 284
asset records and writes distinct source/runtime copies.
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
CAPTURE_ID = "mit-opencourseware-20260905T070619Z"
OBSERVATION_REL = (
    "artifacts/mit-opencourseware/mit-opencourseware-20260905T070619Z/"
    "g1/exact-width-source-v2/report.json"
)
OBSERVATION = REPO / OBSERVATION_REL
OBSERVATION_SHA256 = "3b96cfe218bcd6515a3196f410e46a88ae81589c1af91fdae6fa6568c7b3c59e"
ADDENDUM = SITE / "source-assets" / "g3c-catalog-math-asset-addendum.json"

ASSETS = [
    {
        "state": "math",
        "index": 0,
        "source_index": 7,
        "course_title": "Topics in Statistics: Nonparametrics and Robustness",
        "url": "https://ocw.mit.edu/courses/18-465-topics-in-statistics-nonparametrics-and-robustness-spring-2005/e4689bd84e821cbef0e93289d30e0fc2_18-465s05.JPG",
    },
    {
        "state": "math",
        "index": 1,
        "source_index": 6,
        "course_title": "Honors Differential Equations",
        "url": "https://ocw.mit.edu/courses/18-034-honors-differential-equations-spring-2004/ade3412a58f3fa8f7cf4888d277ad571_18-034s04.jpg",
    },
    {
        "state": "math",
        "index": 2,
        "source_index": 8,
        "course_title": "Topics in Algebraic Number Theory",
        "url": "https://ocw.mit.edu/courses/18-786-topics-in-algebraic-number-theory-spring-2006/06e3b8f52ff0b481586b699a9f7c85ef_18-786s06.jpg",
    },
    {
        "state": "math",
        "index": 3,
        "source_index": 9,
        "course_title": "Topics in Algebraic Number Theory",
        "url": "https://ocw.mit.edu/courses/18-786-topics-in-algebraic-number-theory-spring-2010/ad625fcdbac79d7e2633be2dd7b4aedd_18-786s10.jpg",
    },
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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
        headers={
            "User-Agent": "WebsiteBench-MIT-OCW-G3C-Math-Catalog/1.0",
            "Accept": "image/*",
        },
    )
    with urlopen(request, timeout=45) as response:  # noqa: S310 - four exact approved URLs
        status = int(response.status)
        final_url = response.geturl()
        content_type = response.headers.get_content_type()
        assert status == 200, (url, status)
        assert urlsplit(final_url).hostname in {"ocw.mit.edu", "www.ocw.mit.edu"}
        assert content_type.startswith("image/"), (url, content_type)
        with destination.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
    return final_url, content_type, destination.stat().st_size, digest(destination)


def main() -> None:
    if ADDENDUM.exists():
        raise SystemExit(f"create-only addendum already exists: {ADDENDUM}")
    assert OBSERVATION.is_file() and digest(OBSERVATION) == OBSERVATION_SHA256
    observation_text = OBSERVATION.read_text(encoding="utf-8").replace("\\/", "/")
    assert all(str(row["url"]) in observation_text for row in ASSETS)

    manifest_path = SITE / "source-assets" / "manifest.json"
    data_path = SITE / "clone" / "site-data.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = json.loads(data_path.read_text(encoding="utf-8"))
    existing_assets = list(manifest["assets"])
    assert len(existing_assets) == 284
    existing_urls = {str(row["source_url"]) for row in existing_assets}
    assert not existing_urls.intersection(str(row["url"]) for row in ASSETS)
    prior_manifest_sha256 = canonical_digest(existing_assets)

    records: list[dict[str, object]] = []
    runtime_assets = dict(data["g3c_catalog_assets"])
    url_map = dict(data["g3c_catalog_url_map"])
    assert len(runtime_assets) == len(url_map) == 6
    with tempfile.TemporaryDirectory(prefix="mit-ocw-g3c-catalog-math-") as temporary:
        temporary_root = Path(temporary)
        for ordinal, item in enumerate(ASSETS, start=1):
            temporary_asset = temporary_root / f"asset-{ordinal}.jpg"
            final_url, response_type, byte_count, sha256 = acquire(
                str(item["url"]), temporary_asset
            )
            inspected = inspect_asset(temporary_asset)
            mime_type = str(inspected["mime_type"])
            assert mime_type == response_type or {mime_type, response_type} <= {
                "image/jpeg",
                "image/jpg",
            }
            suffix = mimetypes.guess_extension(mime_type) or ".jpg"
            suffix = ".jpg" if suffix in {".jpe", ".jpeg"} else suffix
            name = f"{sha256}{suffix}"
            source_copy = SITE / "source-assets" / "g3c-catalog" / name
            runtime_copy = SITE / "runtime-assets" / "g3c-catalog" / name
            copy_distinct(temporary_asset, source_copy)
            copy_distinct(temporary_asset, runtime_copy)
            local_url = f"/g3c-catalog-assets/{name}"
            manifest_record = {
                "id": f"g3c-catalog-math-{int(item['index']) + 1}-{sha256[:12]}",
                "priority": "p0",
                "required": True,
                "source_path": source_copy.relative_to(SITE).as_posix(),
                "runtime_path": runtime_copy.relative_to(SITE).as_posix(),
                "bytes": byte_count,
                "sha256": sha256,
                "mime_type": mime_type,
                "dimensions": inspected["dimensions"],
                "referenced_by": ["catalog.math"],
                "evidence_kind": "current-direct",
                "source_url": item["url"],
                "capture_id": CAPTURE_ID,
            }
            manifest["assets"].append(manifest_record)
            records.append(
                {
                    **manifest_record,
                    "evidence_kind": "current-direct-g3c-catalog-math-addendum",
                    "state": item["state"],
                    "card_index": item["index"],
                    "source_card_index": item["source_index"],
                    "course_title": item["course_title"],
                    "requested_url": item["url"],
                    "final_url": final_url,
                    "http_status": 200,
                    "response_content_type": response_type,
                    "observed_in": OBSERVATION_REL,
                    "observation_sha256": OBSERVATION_SHA256,
                }
            )
            runtime_assets[name] = {
                "runtime_path": manifest_record["runtime_path"],
                "mime_type": mime_type,
                "bytes": byte_count,
                "sha256": sha256,
            }
            url_map[str(item["url"])] = local_url

    assert manifest["assets"][:284] == existing_assets
    assert len(manifest["assets"]) == 288
    assert len(runtime_assets) == len(url_map) == 10
    data["g3c_catalog_assets"] = runtime_assets
    data["g3c_catalog_url_map"] = url_map
    data["g3c_catalog_math_asset_addendum"] = {
        "status": "g3c-current-direct-math-assets-imported",
        "assets": 4,
        "bytes": sum(int(row["bytes"]) for row in records),
        "provenance": ADDENDUM.relative_to(SITE).as_posix(),
    }
    data["final_denominator_status"]["presentation_assets"] = len(manifest["assets"])
    data["final_denominator_status"]["presentation_asset_bytes"] = sum(
        int(row["bytes"]) for row in manifest["assets"]
    )
    report = {
        "schema_version": "mit-ocw.g3c-catalog-math-asset-addendum.v1",
        "capture_id": CAPTURE_ID,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": "four-exact-same-origin-static-get-current-direct-addendum",
        "request_policy": {
            "allowed_method": "GET",
            "allowed_urls": [str(row["url"]) for row in ASSETS],
            "other_requests": 0,
        },
        "does_not_modify_prior_284_manifest_records": True,
        "prior_manifest_assets_sha256": prior_manifest_sha256,
        "observed_in": OBSERVATION_REL,
        "observation_sha256": OBSERVATION_SHA256,
        "assets": records,
    }
    dump(manifest_path, manifest)
    dump(data_path, data, compact=True)
    dump(ADDENDUM, report)
    print(
        json.dumps(
            {
                "status": "g3c-catalog-math-assets-acquired",
                "requests": len(records),
                "assets": len(records),
                "bytes": sum(int(row["bytes"]) for row in records),
                "manifest_assets": len(manifest["assets"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
