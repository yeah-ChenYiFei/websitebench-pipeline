"""Trusted receipt verification and fixed Harbor reward publication."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .case_protocol import (
    RECEIPT_SCHEMA_FILE,
    CaseProtocolError,
    _validate_schema,
    file_sha256,
)


def validate_receipt_run(root: Path | str) -> dict[str, Any]:
    run = Path(root).resolve(strict=True)
    receipt_path = run / "receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaseProtocolError(f"receipt is unreadable: {exc}") from exc
    if not isinstance(receipt, dict):
        raise CaseProtocolError("receipt must be an object")
    _validate_schema(receipt, RECEIPT_SCHEMA_FILE, "receipt")
    declared = receipt["artifacts"]
    actual = {
        path.relative_to(run).as_posix()
        for path in run.rglob("*")
        if path.is_file() and path.name != "receipt.json"
    }
    if actual != set(declared):
        raise CaseProtocolError(
            "receipt exact artifact set mismatch: "
            f"missing={sorted(set(declared) - actual)}:extra={sorted(actual - set(declared))}"
        )
    for relative, expected in declared.items():
        if file_sha256(run / relative) != expected:
            raise CaseProtocolError(f"receipt hash mismatch: {relative}")
    expected_valid = receipt["status"] == "VALID_RUN"
    if receipt["valid"] is not expected_valid:
        raise CaseProtocolError("receipt.valid does not match receipt.status")
    valid = expected_valid
    reward = run / "reward.txt"
    if valid != reward.is_file():
        raise CaseProtocolError(
            "reward.txt must exist if and only if the receipt is valid"
        )
    if valid:
        value = reward.read_text(encoding="ascii")
        if not value.endswith("\n") or len(value.splitlines()) != 1:
            raise CaseProtocolError("reward.txt is not the fixed one-line Harbor reward")
        try:
            reward_value = float(value.strip())
        except ValueError as exc:
            raise CaseProtocolError("reward.txt is not numeric") from exc
        if not 0 <= reward_value <= 1:
            raise CaseProtocolError("reward.txt leaves [0,1]")
    return receipt


def finalize_run(source: Path | str, destination: Path | str) -> int:
    """Verify a private run, then publish a byte-identical directory atomically."""

    source_root = Path(source).resolve(strict=True)
    receipt = validate_receipt_run(source_root)
    destination_root = Path(destination).resolve()
    destination_root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_root.name}.publish-",
            dir=destination_root.parent,
        )
    )
    try:
        # Preserve receipt-last ordering in the public directory too.
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.name == "receipt.json":
                continue
            relative = path.relative_to(source_root)
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            with target.open("rb") as handle:
                os.fsync(handle.fileno())
        shutil.copyfile(source_root / "receipt.json", stage / "receipt.json")
        with (stage / "receipt.json").open("rb") as handle:
            os.fsync(handle.fileno())
        descriptor = os.open(stage, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if destination_root.exists():
            if not destination_root.is_dir() or any(destination_root.iterdir()):
                raise FileExistsError(
                    f"public Harbor output already exists and is not empty: {destination_root}"
                )
            destination_root.rmdir()
        os.replace(stage, destination_root)
        parent_descriptor = os.open(
            destination_root.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return 0 if receipt["valid"] is True else 2


__all__ = ["finalize_run", "validate_receipt_run"]
