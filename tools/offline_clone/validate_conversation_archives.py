#!/usr/bin/env python3
"""Validate private conversation archive integrity.

The validator is deliberately read-only. Pass archive directories explicitly;
it never discovers or copies source sessions on its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


class ArchiveValidationError(ValueError):
    """Raised when an archive does not match its manifest."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchiveValidationError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ArchiveValidationError(f"{path}: expected a JSON object")
    return value


def _validate_jsonl(path: Path) -> tuple[int, Counter[str]]:
    count = 0
    record_types: Counter[str] = Counter()
    with path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                raise ArchiveValidationError(
                    f"{path}:{line_number}: blank JSONL record"
                )
            try:
                record = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ArchiveValidationError(
                    f"{path}:{line_number}: invalid JSON: {error}"
                ) from error
            if not isinstance(record, dict):
                raise ArchiveValidationError(
                    f"{path}:{line_number}: expected a JSON object"
                )
            record_types[str(record.get("type", "<missing>"))] += 1
            count += 1
    return count, record_types


def _parse_sha256sums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ArchiveValidationError(f"{path}: unreadable: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ArchiveValidationError(
                f"{path}:{line_number}: invalid checksum entry"
            )
        filename = parts[1].lstrip("*").strip()
        if Path(filename).name != filename:
            raise ArchiveValidationError(
                f"{path}:{line_number}: checksum path must be a filename"
            )
        result[filename] = parts[0]
    return result


def validate_archive(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ArchiveValidationError(f"{root}: archive directory not found")

    manifest_path = root / "manifest.json"
    messages_path = root / "MESSAGES.md"
    sums_path = root / "SHA256SUMS.txt"
    manifest = _read_json(manifest_path)

    if manifest.get("schema_version") != "codex.conversation.archive.v1":
        raise ArchiveValidationError(
            f"{manifest_path}: unsupported schema_version"
        )

    snapshot = manifest.get("snapshot")
    rendered = manifest.get("rendered_messages")
    if not isinstance(snapshot, dict) or not isinstance(rendered, dict):
        raise ArchiveValidationError(
            f"{manifest_path}: missing snapshot or rendered_messages"
        )

    raw_name = snapshot.get("authoritative_file")
    if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
        raise ArchiveValidationError(
            f"{manifest_path}: unsafe authoritative_file"
        )
    raw_path = root / raw_name

    required = [raw_path, messages_path, manifest_path, sums_path]
    for path in required:
        if not path.is_file():
            raise ArchiveValidationError(f"{path}: required file missing")

    raw_bytes = raw_path.stat().st_size
    raw_sha256 = _sha256(raw_path)
    if raw_bytes != snapshot.get("bytes"):
        raise ArchiveValidationError(
            f"{raw_path}: bytes {raw_bytes} != manifest {snapshot.get('bytes')}"
        )
    if raw_sha256 != snapshot.get("sha256"):
        raise ArchiveValidationError(
            f"{raw_path}: sha256 {raw_sha256} != manifest {snapshot.get('sha256')}"
        )

    jsonl_records, record_types = _validate_jsonl(raw_path)
    if jsonl_records != snapshot.get("jsonl_records"):
        raise ArchiveValidationError(
            f"{raw_path}: records {jsonl_records} != "
            f"manifest {snapshot.get('jsonl_records')}"
        )
    if dict(record_types) != snapshot.get("record_type_counts"):
        raise ArchiveValidationError(
            f"{raw_path}: record type counts differ from manifest"
        )
    if snapshot.get("all_records_valid_json") is not True:
        raise ArchiveValidationError(
            f"{manifest_path}: all_records_valid_json must be true"
        )

    messages_bytes = messages_path.stat().st_size
    messages_sha256 = _sha256(messages_path)
    if messages_bytes != rendered.get("bytes"):
        raise ArchiveValidationError(
            f"{messages_path}: bytes {messages_bytes} != "
            f"manifest {rendered.get('bytes')}"
        )
    if messages_sha256 != rendered.get("sha256"):
        raise ArchiveValidationError(
            f"{messages_path}: sha256 {messages_sha256} != "
            f"manifest {rendered.get('sha256')}"
        )

    sums = _parse_sha256sums(sums_path)
    expected_sums = {
        raw_name: raw_sha256,
        "MESSAGES.md": messages_sha256,
        "manifest.json": _sha256(manifest_path),
    }
    if sums != expected_sums:
        raise ArchiveValidationError(
            f"{sums_path}: checksum set differs from archive files"
        )

    thread = manifest.get("thread")
    snapshot_meta = manifest.get("snapshot")
    return {
        "status": "valid",
        "archive": str(root),
        "thread_id": thread.get("id") if isinstance(thread, dict) else None,
        "snapshot_kind": (
            snapshot_meta.get("kind")
            if isinstance(snapshot_meta, dict)
            else None
        ),
        "raw_sha256": raw_sha256,
        "jsonl_records": jsonl_records,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archives",
        nargs="+",
        type=Path,
        help="One or more explicit conversation archive directories",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    results: list[dict[str, Any]] = []
    try:
        for archive in args.archives:
            results.append(validate_archive(archive))
    except ArchiveValidationError as error:
        print(json.dumps({"status": "invalid", "error": str(error)}))
        return 1
    print(json.dumps({"status": "valid", "archives": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
