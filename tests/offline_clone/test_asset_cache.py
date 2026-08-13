from __future__ import annotations

import json
from pathlib import Path

from websitebench.offline_clone.asset_cache import (
    AssetPayloadCache,
    write_bytes_if_changed,
)


def test_asset_payload_cache_reuses_exact_url_and_content_blob(tmp_path: Path) -> None:
    cache = AssetPayloadCache(tmp_path / "cache")
    payload = b"same inspected media bytes"

    first_digest = cache.put("https://assets.example/one.png", payload)
    second_digest = cache.put("https://cdn.example/two.png", payload)

    assert first_digest == second_digest
    assert cache.get("https://assets.example/one.png") == payload
    assert cache.get("https://cdn.example/two.png") == payload
    assert len(list((tmp_path / "cache/sha256").rglob(first_digest))) == 1
    records = list((tmp_path / "cache/urls").rglob("*.json"))
    assert records
    assert {
        json.loads(record.read_text(encoding="utf-8"))["schema_version"]
        for record in records
    } == {"websitebench.asset-payload-cache.v1"}


def test_asset_payload_cache_reads_legacy_schema_without_writing_it(
    tmp_path: Path,
) -> None:
    cache = AssetPayloadCache(tmp_path / "cache")
    url = "https://assets.example/legacy.png"
    payload = b"legacy inspected media bytes"
    cache.put(url, payload)
    record_path = next((tmp_path / "cache/urls").rglob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["schema_version"] = "clawbench.asset-payload-cache.v1"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    assert cache.get(url) == payload


def test_asset_payload_cache_fails_closed_on_corrupt_blob(tmp_path: Path) -> None:
    cache = AssetPayloadCache(tmp_path / "cache")
    url = "https://assets.example/logo.svg"
    digest = cache.put(url, b"<svg></svg>")
    blob = tmp_path / "cache/sha256" / digest[:2] / digest
    blob.write_bytes(b"changed")

    assert cache.get(url) is None


def test_write_bytes_if_changed_does_not_replace_identical_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "generated.json"

    assert write_bytes_if_changed(path, b"{}\n") is True
    inode = path.stat().st_ino
    assert write_bytes_if_changed(path, b"{}\n") is False
    assert path.stat().st_ino == inode
