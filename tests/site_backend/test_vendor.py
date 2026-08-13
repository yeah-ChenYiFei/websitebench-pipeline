from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from websitebench.site_backend.vendor import RUNTIME_FILES, vendor_site_backend


def test_vendor_site_backend_copies_complete_runtime_with_hash_manifest(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "clone"
    candidate.mkdir()
    manifest_path = vendor_site_backend(candidate)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["files"]} == set(RUNTIME_FILES)
    for item in manifest["files"]:
        target = manifest_path.parent / item["path"]
        assert target.stat().st_size == item["bytes"]
        assert len(item["sha256"]) == 64
    with pytest.raises(FileExistsError, match="already exists"):
        vendor_site_backend(candidate)


def test_vendored_backend_import_does_not_require_an_auth_runtime(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "clone"
    candidate.mkdir()
    vendor_site_backend(candidate)

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(candidate)!r}); "
                "import websitebench.site_backend"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (candidate / "websitebench/local_clone_auth").exists()
