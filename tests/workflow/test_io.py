from __future__ import annotations

from pathlib import Path

from websitebench.workflow.io import atomic_write


def test_atomic_write_preserves_identical_generated_output(tmp_path: Path) -> None:
    path = tmp_path / "derived.json"

    assert atomic_write(path, b'{"derived":true}\n') is True
    inode = path.stat().st_ino
    assert atomic_write(path, b'{"derived":true}\n') is False
    assert path.stat().st_ino == inode


def test_atomic_write_replaces_changed_generated_output(tmp_path: Path) -> None:
    path = tmp_path / "derived.json"
    atomic_write(path, b"old")

    assert atomic_write(path, b"new") is True
    assert path.read_bytes() == b"new"
