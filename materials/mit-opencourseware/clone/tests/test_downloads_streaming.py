from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest


CLONE = Path(__file__).resolve().parents[1]
SITE = CLONE.parent
DATA = json.loads((CLONE / "site-data.json").read_text(encoding="utf-8"))
DOWNLOADS = DATA["downloads"]


@pytest.fixture(scope="session")
def local_server() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=CLONE,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if httpx.get(base_url + "/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise AssertionError("local isolated clone server did not become ready")
            time.sleep(0.05)
        yield base_url
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
    assert response.headers["content-type"].split(";", 1)[0] == record["content_type"]
    assert response.headers["x-content-sha256"] == record["sha256"]
    assert f"filename*=UTF-8''{quote(str(record['filename']))}" in response.headers["content-disposition"]


def stream_digest(client: httpx.Client, path: str, record: dict[str, object]) -> tuple[int, str]:
    size = 0
    result = hashlib.sha256()
    with client.stream("GET", path) as response:
        assert_headers(response, record)
        for block in response.iter_bytes(chunk_size=1024 * 1024):
            size += len(block)
            result.update(block)
    return size, result.hexdigest()


def test_all_480_head_responses(local_server: str) -> None:
    assert len(DOWNLOADS) == 480
    assert len({record["sha256"] for record in DOWNLOADS.values()}) == 478
    assert sum(record["bytes"] for record in DOWNLOADS.values()) == 1_551_223_348
    with httpx.Client(base_url=local_server, timeout=60) as client:
        for path, record in DOWNLOADS.items():
            assert_headers(client.head(path), record)


def test_all_478_unique_payloads_stream_exactly_once_and_duplicate_is_repeatable(local_server: str) -> None:
    by_sha: dict[str, list[tuple[str, dict[str, object]]]] = defaultdict(list)
    for path, record in DOWNLOADS.items():
        by_sha[str(record["sha256"])].append((path, record))
    assert len(by_sha) == 478
    with httpx.Client(base_url=local_server, timeout=300) as client:
        for path, record in (rows[0] for _, rows in sorted(by_sha.items())):
            size, sha256 = stream_digest(client, path, record)
            assert size == record["bytes"]
            assert sha256 == record["sha256"]
        duplicate_rows = next(rows for rows in by_sha.values() if len(rows) > 1)
        first_size, first_sha = stream_digest(client, *duplicate_rows[0])
        second_size, second_sha = stream_digest(client, *duplicate_rows[1])
        assert first_size == second_size == duplicate_rows[0][1]["bytes"]
        assert first_sha == second_sha == duplicate_rows[0][1]["sha256"]


def test_chunk_files_respect_packaging_and_link_constraints() -> None:
    denominator = DATA["download_denominator"]
    unique_chunks = {row["path"]: row for record in DOWNLOADS.values() for row in record["chunks"]}
    assert len(unique_chunks) == denominator["chunks"] == 542
    assert denominator["maximum_chunk_bytes"] <= 15 * 1024 * 1024
    assert denominator["maximum_source_bytes"] == 392_263_382
    for relative, row in unique_chunks.items():
        path = SITE / relative
        stat = path.stat()
        assert not path.is_symlink() and stat.st_nlink == 1
        assert stat.st_size == row["bytes"] <= 15 * 1024 * 1024
