#!/usr/bin/env python3
"""Validate a private conversation concern corpus and raw quote provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_SCHEMA_ROOT = (
    Path(__file__).resolve().parents[2] / "websitebench" / "schemas"
)


def _default_schema_path(name: str) -> Path:
    canonical = REPOSITORY_SCHEMA_ROOT / name
    return canonical


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_record(path: Path, line_number: int) -> dict[str, Any]:
    with path.open("rb") as stream:
        for current, line in enumerate(stream, start=1):
            if current == line_number:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number}: expected object")
                return value
    raise ValueError(f"{path}:{line_number}: line does not exist")


def _message_text(record: dict[str, Any]) -> tuple[str | None, str]:
    if record.get("type") != "response_item":
        return None, ""
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return None, ""
    content = payload.get("content")
    texts = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    return payload.get("role"), "\n".join(texts)


def validate_corpus(
    corpus_path: Path,
    schema_path: Path,
    archive_root: Path,
) -> list[str]:
    corpus = _read_json(corpus_path)
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in sorted(
            validator.iter_errors(corpus),
            key=lambda item: list(item.absolute_path),
        )
    ]
    if errors or not isinstance(corpus, dict):
        return errors

    sources = {
        source["archive_id"]: source
        for source in corpus["sources"]
        if isinstance(source, dict)
    }
    for concern in corpus["concerns"]:
        concern_id = concern["id"]
        source = concern["source"]
        archive_id = source["archive_id"]
        declared_source = sources.get(archive_id)
        if declared_source is None:
            errors.append(f"{concern_id}: unknown archive_id {archive_id}")
            continue
        if source["thread_id"] != declared_source["thread_id"]:
            errors.append(f"{concern_id}: thread_id differs from source")

        quote = concern["exact_user_quote"]
        quote_sha256 = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        if quote_sha256 != concern["quote_sha256"]:
            errors.append(f"{concern_id}: quote_sha256 mismatch")

        archive = (archive_root / archive_id).resolve()
        root = archive_root.resolve()
        if archive != root and root not in archive.parents:
            errors.append(f"{concern_id}: archive path escapes root")
            continue
        manifest_path = archive / "manifest.json"
        if not manifest_path.is_file():
            errors.append(f"{concern_id}: archive manifest missing")
            continue
        manifest = _read_json(manifest_path)
        if manifest["thread"]["id"] != source["thread_id"]:
            errors.append(f"{concern_id}: manifest thread_id mismatch")
        raw_path = archive / manifest["snapshot"]["authoritative_file"]
        if manifest["snapshot"]["sha256"] != declared_source["sha256"]:
            errors.append(f"{concern_id}: source raw sha256 mismatch")
        try:
            record = _raw_record(raw_path, source["raw_jsonl_line"])
        except (OSError, json.JSONDecodeError, ValueError) as error:
            errors.append(f"{concern_id}: {error}")
            continue
        role, text = _message_text(record)
        if role != "user":
            errors.append(f"{concern_id}: raw locator is not a user message")
        if quote not in text:
            errors.append(f"{concern_id}: exact quote absent at raw locator")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=_default_schema_path(
            "conversation-concern-corpus.schema.json"
        ),
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path("artifacts/conversations"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    errors = validate_corpus(args.corpus, args.schema, args.archive_root)
    print(
        json.dumps(
            {
                "status": "invalid" if errors else "valid",
                "corpus": str(args.corpus),
                "errors": errors,
            },
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
