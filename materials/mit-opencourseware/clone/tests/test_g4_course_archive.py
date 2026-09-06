from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from app import DOWNLOADS, SUPPLEMENTARY_DOWNLOADS, SITE_ROOT, app, local_path


SOURCE_URL = (
    "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/"
    "6.006-fall-2011.zip"
)
LOCAL_PATH = "/courses/6-006-introduction-to-algorithms-fall-2011/6.006-fall-2011.zip"
COURSE_DOWNLOAD_PAGE = "/courses/6-006-introduction-to-algorithms-fall-2011/download/"
EXPECTED_BYTES = 173_887_153
EXPECTED_SHA256 = "7ce95a304a80b42f542d2945d8a3d883ad2b27d6a6ebb4c2cde4a886071bbac0"
FROZEN_DOWNLOADS_SHA256 = "d4493389f3438795d415f44115e5226fc242692557ea538d8d84b5cbad008338"
def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_sha(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@pytest.fixture(scope="module")
def local_server() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=SITE_ROOT / "clone",
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    origin = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if httpx.get(origin + "/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise AssertionError("isolated candidate did not become ready")
        yield origin
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def assert_headers(response: httpx.Response, record: dict[str, object]) -> None:
    assert response.status_code == 200
    assert response.headers["content-length"] == str(record["bytes"])
    assert response.headers["content-type"].split(";", 1)[0] == "application/zip"
    assert response.headers["x-content-sha256"] == record["sha256"]
    assert response.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{quote(str(record['filename']))}"
    )


def streamed_http_sha(client: httpx.Client) -> tuple[int, str, str]:
    digest = hashlib.sha256()
    length = 0
    with client.stream("GET", LOCAL_PATH) as response:
        record = SUPPLEMENTARY_DOWNLOADS[LOCAL_PATH]
        assert_headers(response, record)
        disposition = response.headers["content-disposition"]
        for block in response.iter_bytes(chunk_size=1024 * 1024):
            length += len(block)
            digest.update(block)
    return length, digest.hexdigest(), disposition


def test_g4_delivery_metadata_and_runtime_chunks_are_exact_and_portable() -> None:
    runtime = SUPPLEMENTARY_DOWNLOADS[LOCAL_PATH]
    assert runtime["url"] == SOURCE_URL
    assert runtime["content_type"] == "application/zip"
    assert runtime["bytes"] == EXPECTED_BYTES
    assert runtime["sha256"] == EXPECTED_SHA256
    assert runtime["etag"] == '"43d0009c056dd448cdee1485559ca8e0-21"'
    assert runtime["last_modified"] == "Wed, 19 Aug 2026 18:47:19 GMT"
    assert runtime["x_amz_meta_site_id"] == "6-006-introduction-to-algorithms-fall-2011"
    assert runtime["source_report"].endswith("/g4/course-archive/report.json")
    assert len(runtime["chunks"]) == 12

    assembled = hashlib.sha256()
    total = 0
    for row in runtime["chunks"]:
        part = SITE_ROOT / row["path"]
        assert part.is_file() and not part.is_symlink() and part.stat().st_nlink == 1
        assert part.stat().st_size == row["bytes"] <= 15 * 1024 * 1024
        assert sha(part) == row["sha256"]
        with part.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                total += len(block)
                assembled.update(block)
    assert total == EXPECTED_BYTES
    assert assembled.hexdigest() == EXPECTED_SHA256


def test_frozen_480_are_unchanged_and_archive_is_separate_supplementary_record() -> None:
    assert len(DOWNLOADS) == 480
    assert len({row["sha256"] for row in DOWNLOADS.values()}) == 478
    assert sum(int(row["bytes"]) for row in DOWNLOADS.values()) == 1_551_223_348
    assert ordered_sha(DOWNLOADS) == FROZEN_DOWNLOADS_SHA256
    assert SOURCE_URL not in {row["url"] for row in DOWNLOADS.values()}
    assert set(SUPPLEMENTARY_DOWNLOADS) == {LOCAL_PATH}
    record = SUPPLEMENTARY_DOWNLOADS[LOCAL_PATH]
    assert record["url"] == SOURCE_URL
    assert record["bytes"] == EXPECTED_BYTES and record["sha256"] == EXPECTED_SHA256
    assert local_path(SOURCE_URL) == LOCAL_PATH


def test_course_download_button_targets_enabled_exact_local_archive() -> None:
    from fastapi.testclient import TestClient

    page = TestClient(app).get(COURSE_DOWNLOAD_PAGE)
    assert page.status_code == 200
    assert 'data-wb-control="course-download"' in page.text
    assert 'data-wb-capability="local-course-archive"' in page.text
    assert f'href="{LOCAL_PATH}"' in page.text
    assert f"/data-boundary/?url={quote(SOURCE_URL, safe='')}" not in page.text


def test_head_and_two_streamed_gets_are_exact_repeatable_and_stable(local_server: str) -> None:
    record = SUPPLEMENTARY_DOWNLOADS[LOCAL_PATH]
    with httpx.Client(base_url=local_server, timeout=300) as client:
        head = client.head(LOCAL_PATH)
        assert_headers(head, record)
        assert head.content == b""
        first = streamed_http_sha(client)
        second = streamed_http_sha(client)
    assert first[0] == second[0] == EXPECTED_BYTES
    assert first[1] == second[1] == EXPECTED_SHA256
    assert first[2] == second[2] == "attachment; filename*=UTF-8''6.006-fall-2011.zip"
