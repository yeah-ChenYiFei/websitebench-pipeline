"""Acquire the exact 6.006 Fall 2011 course archive authorized for G4.

The command performs exactly one external GET, preserves the complete response
as create-only G4 evidence, and materializes a single supplementary download as
ordinary runtime chunks no larger than 15 MiB.  It never mutates the frozen
480-record ``downloads`` mapping.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parents[1]
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
SOURCE_URL = (
    "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/"
    "6.006-fall-2011.zip"
)
LOCAL_PATH = "/courses/6-006-introduction-to-algorithms-fall-2011/6.006-fall-2011.zip"
FILENAME = "6.006-fall-2011.zip"
EXPECTED_BYTES = 173_887_153
CHUNK_LIMIT = 15 * 1024 * 1024
EVIDENCE_REL = (
    "artifacts/mit-opencourseware/mit-opencourseware-20260903T032020Z/"
    "g4/course-archive"
)
EVIDENCE = REPO / EVIDENCE_REL


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_sha(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: object, *, compact: bool = False) -> None:
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


def acquire_once(destination: Path) -> dict[str, object]:
    request = Request(
        SOURCE_URL,
        method="GET",
        headers={"User-Agent": "WebsiteBench-MIT-OCW-G4-Archive/1.0", "Accept": "application/zip"},
    )
    digest = hashlib.sha256()
    byte_count = 0
    with urlopen(request, timeout=300) as response:  # noqa: S310 - one exact authorized URL
        status = int(response.status)
        final_url = response.geturl()
        raw_headers = [[key, value] for key, value in response.headers.items()]
        content_type = response.headers.get_content_type()
        content_length = response.headers.get("Content-Length")
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        site_id = response.headers.get("x-amz-meta-site-id")
        assert status == 200
        assert final_url == SOURCE_URL
        assert urlsplit(final_url).hostname == "ocw.mit.edu"
        assert content_type == "application/zip"
        assert content_length == str(EXPECTED_BYTES)
        assert etag == '"43d0009c056dd448cdee1485559ca8e0-21"'
        assert last_modified and "19 Aug 2026" in last_modified
        assert site_id == "6-006-introduction-to-algorithms-fall-2011"
        with destination.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
                digest.update(block)
                byte_count += len(block)
    assert byte_count == destination.stat().st_size == EXPECTED_BYTES
    return {
        "method": "GET",
        "requested_url": SOURCE_URL,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "content_length": int(content_length),
        "etag": etag,
        "last_modified": last_modified,
        "x_amz_meta_site_id": site_id,
        "sha256": digest.hexdigest(),
        "raw_headers": raw_headers,
    }


def materialize_chunks(source: Path, temporary_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with source.open("rb") as stream:
        index = 0
        while block := stream.read(CHUNK_LIMIT):
            part = temporary_root / f"{index:04d}.part"
            part.write_bytes(block)
            assert part.is_file() and not part.is_symlink()
            assert part.stat().st_nlink == 1
            assert part.stat().st_size == len(block) <= CHUNK_LIMIT
            rows.append({
                "name": part.name,
                "bytes": len(block),
                "sha256": sha256(part),
            })
            index += 1
    assert sum(int(row["bytes"]) for row in rows) == source.stat().st_size
    return rows


def verify_reassembled(source: Path, chunk_root: Path, rows: list[dict[str, object]], expected_sha: str) -> None:
    aggregate = hashlib.sha256()
    total = 0
    with source.open("rb") as original:
        for row in rows:
            part = chunk_root / str(row["name"])
            assert part.stat().st_size == row["bytes"]
            assert sha256(part) == row["sha256"]
            with part.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    assert original.read(len(block)) == block
                    aggregate.update(block)
                    total += len(block)
        assert original.read(1) == b""
    assert total == EXPECTED_BYTES
    assert aggregate.hexdigest() == expected_sha == sha256(source)


def main() -> None:
    if EVIDENCE.exists():
        raise SystemExit(f"create-only evidence already exists: {EVIDENCE}")

    data_path = SITE / "clone" / "site-data.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    downloads = data["downloads"]
    assert len(downloads) == 480
    assert len({row["sha256"] for row in downloads.values()}) == 478
    assert sum(int(row["bytes"]) for row in downloads.values()) == 1_551_223_348
    assert LOCAL_PATH not in downloads
    assert SOURCE_URL not in {row["url"] for row in downloads.values()}
    assert "supplementary_downloads" not in data
    downloads_sha_before = ordered_sha(downloads)

    runtime_parent = SITE / "runtime-downloads"
    evidence_parent = EVIDENCE.parent
    evidence_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mit-ocw-g4-source-") as source_temporary, tempfile.TemporaryDirectory(
        prefix=".g4-6-006-", dir=runtime_parent
    ) as chunk_temporary, tempfile.TemporaryDirectory(prefix=".course-archive-", dir=evidence_parent) as evidence_temporary:
        source_temp = Path(source_temporary) / FILENAME
        response = acquire_once(source_temp)
        source_sha = str(response["sha256"])
        final_chunk_root = runtime_parent / source_sha
        assert not final_chunk_root.exists()

        chunk_temp_root = Path(chunk_temporary)
        chunk_rows = materialize_chunks(source_temp, chunk_temp_root)
        assert len(chunk_rows) == 12
        assert max(int(row["bytes"]) for row in chunk_rows) <= CHUNK_LIMIT
        verify_reassembled(source_temp, chunk_temp_root, chunk_rows, source_sha)

        evidence_temp_root = Path(evidence_temporary)
        source_evidence = evidence_temp_root / "source" / FILENAME
        source_evidence.parent.mkdir(parents=True)
        shutil.copyfile(source_temp, source_evidence)
        assert source_evidence.stat().st_size == EXPECTED_BYTES
        assert sha256(source_evidence) == source_sha
        response_headers = {
            "schema_version": "mit-ocw.g4-course-archive-response.v1",
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "request_count": 1,
            "other_requests": 0,
            **response,
        }
        write_json(evidence_temp_root / "response-headers.json", response_headers)
        (evidence_temp_root / "source" / "6.006-fall-2011.zip.sha256").write_text(
            f"{source_sha}  {FILENAME}\n", encoding="ascii"
        )

        final_chunks = [
            {
                "path": f"runtime-downloads/{source_sha}/{row['name']}",
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in chunk_rows
        ]
        record = {
            "url": SOURCE_URL,
            "path": LOCAL_PATH,
            "filename": FILENAME,
            "content_type": "application/zip",
            "bytes": EXPECTED_BYTES,
            "sha256": source_sha,
            "source_set": "g4-course-archive-addendum",
            "source_report": f"{EVIDENCE_REL}/report.json",
            "evidence_file": f"{EVIDENCE_REL}/source/{FILENAME}",
            "etag": response["etag"],
            "last_modified": response["last_modified"],
            "x_amz_meta_site_id": response["x_amz_meta_site_id"],
            "chunks": final_chunks,
        }
        report = {
            "schema_version": "mit-ocw.g4-course-archive.v1",
            "capture_id": CAPTURE_ID,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "authority": "one-exact-same-origin-get-current-direct-addendum",
            "request_policy": {"allowed_method": "GET", "allowed_urls": [SOURCE_URL], "request_count": 1, "other_requests": 0},
            "response_headers_path": f"{EVIDENCE_REL}/response-headers.json",
            "source": {
                **{key: value for key, value in response.items() if key != "raw_headers"},
                "path": f"{EVIDENCE_REL}/source/{FILENAME}",
            },
            "runtime": {
                "root": f"materials/mit-opencourseware/runtime-downloads/{source_sha}",
                "chunk_limit_bytes": CHUNK_LIMIT,
                "chunk_count": len(final_chunks),
                "maximum_chunk_bytes": max(int(row["bytes"]) for row in final_chunks),
                "total_bytes": sum(int(row["bytes"]) for row in final_chunks),
                "reassembled_sha256": source_sha,
                "byte_for_byte_equal_to_source": True,
                "chunks": final_chunks,
            },
            "frozen_480_preservation": {
                "logical": 480,
                "unique_sha256": 478,
                "logical_bytes": 1_551_223_348,
                "ordered_sha256_before": downloads_sha_before,
                "ordered_sha256_after": ordered_sha(data["downloads"]),
                "unchanged": True,
            },
            "supplementary_record": record,
        }
        assert report["frozen_480_preservation"]["ordered_sha256_after"] == downloads_sha_before
        write_json(evidence_temp_root / "report.json", report)

        # Both create-only trees are complete and verified before becoming visible.
        os.replace(chunk_temp_root, final_chunk_root)
        os.replace(evidence_temp_root, EVIDENCE)

    data["supplementary_downloads"] = {LOCAL_PATH: record}
    data["supplementary_download_denominator"] = {
        "status": "closed",
        "logical": 1,
        "unique_sha256": 1,
        "bytes": EXPECTED_BYTES,
        "chunks": len(record["chunks"]),
        "maximum_chunk_bytes": max(int(row["bytes"]) for row in record["chunks"]),
        "provenance": f"{EVIDENCE_REL}/report.json",
    }
    assert ordered_sha(data["downloads"]) == downloads_sha_before
    write_json(data_path, data, compact=True)
    print(json.dumps({
        "status": "g4-course-archive-acquired",
        "external_gets": 1,
        "bytes": EXPECTED_BYTES,
        "sha256": source_sha,
        "chunks": len(record["chunks"]),
        "maximum_chunk_bytes": max(int(row["bytes"]) for row in record["chunks"]),
        "frozen_downloads_sha256": downloads_sha_before,
        "evidence": EVIDENCE_REL,
    }, indent=2))


if __name__ == "__main__":
    main()
