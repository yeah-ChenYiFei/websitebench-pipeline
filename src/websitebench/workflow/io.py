"""Canonical, atomic and path-safe workflow I/O."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from websitebench.site_compiler.canonical import canonical_json_bytes

from .errors import WorkflowError


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"cannot read JSON document {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"JSON document must be an object: {path}")
    return value


def atomic_write(path: Path, payload: bytes, *, create_only: bool = False) -> bool:
    """Atomically write ``payload`` and return whether bytes changed.

    Generated workflow views are rebuilt frequently.  Avoiding an identical
    replace preserves mtimes and prevents downstream watchers, packet builders,
    and test runners from treating a no-op regeneration as a real change.
    """

    path = path.absolute()
    if path.is_symlink():
        raise WorkflowError(f"refusing to write through symbolic link: {path}")
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return False
        if create_only:
            raise WorkflowError(f"refusing to overwrite immutable file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def write_json(path: Path, value: Any, *, create_only: bool = False) -> bool:
    payload = canonical_json_bytes(value)
    return atomic_write(path, payload, create_only=create_only)


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise WorkflowError(f"path is outside workflow repository root: {path}") from exc


def resolve_relative(root: Path, value: str, *, must_exist: bool = False) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise WorkflowError(f"path must be repository-relative: {value}")
    requested = root / Path(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise WorkflowError(f"workflow path must not traverse a symlink: {value}")
    resolved = requested.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise WorkflowError(f"path escapes repository root: {value}") from exc
    if must_exist and not resolved.is_file():
        raise WorkflowError(f"required evidence file does not exist: {value}")
    return resolved
