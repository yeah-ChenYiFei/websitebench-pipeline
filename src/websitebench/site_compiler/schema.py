"""Strict JSON loading and repository/bundled schema resolution."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .diagnostics import SiteCompilerError

MAX_COMPILER_DOCUMENT_BYTES = 16 * 1024 * 1024


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SiteCompilerError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def schema_path(filename: str) -> Path:
    source_root = Path(__file__).resolve().parents[3]
    source = source_root / "websitebench" / "schemas" / filename
    if source.is_file():
        return source
    bundled = (
        Path(__file__).resolve().parents[1]
        / "viewer"
        / "_schemas"
        / filename
    )
    if bundled.is_file():
        return bundled
    raise SiteCompilerError(f"site compiler schema is unavailable: {filename}")


@lru_cache(maxsize=None)
def load_schema(filename: str) -> dict[str, Any]:
    value = json.loads(schema_path(filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def load_json_document(path: Path, schema_filename: str) -> dict[str, Any]:
    resolved = path.resolve()
    size = resolved.stat().st_size
    if size > MAX_COMPILER_DOCUMENT_BYTES:
        raise SiteCompilerError(
            f"{resolved}: document exceeds {MAX_COMPILER_DOCUMENT_BYTES} bytes"
        )
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SiteCompilerError(f"{resolved}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SiteCompilerError(f"{resolved}: top-level JSON value must be an object")
    problems = validate_value(value, schema_filename, location=str(resolved))
    if problems:
        raise SiteCompilerError(problems)
    return value


def validate_value(
    value: Any,
    schema_filename: str,
    *,
    location: str,
) -> list[str]:
    validator = Draft202012Validator(
        load_schema(schema_filename), format_checker=FormatChecker()
    )
    problems: list[str] = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
        suffix = ".".join(str(part) for part in error.absolute_path)
        error_location = f"{location}:{suffix}" if suffix else location
        problems.append(f"{error_location}: {error.message}")
    return problems
