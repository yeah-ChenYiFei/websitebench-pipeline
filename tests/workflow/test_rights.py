from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.site_compiler.canonical import canonical_json_bytes
from websitebench.workflow.errors import WorkflowError
from websitebench.workflow.rights import RIGHTS_CATEGORIES, validate_rights_metadata


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _metadata(root: Path) -> Path:
    note = root / "materials/alpha/rights/provenance.txt"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("provenance metadata", encoding="utf-8")
    evidence = {
        "path": "materials/alpha/rights/provenance.txt",
        "bytes": note.stat().st_size,
    }
    path = root / "materials/alpha/rights/metadata.json"
    _write(path, {
        "schema_version": "offline-clone.rights-metadata.v2",
        "site_id": "alpha",
        "categories": {
            category: {
                "status": "documented",
                "notes": "metadata only; non-gating",
                "evidence": [evidence],
            }
            for category in RIGHTS_CATEGORIES
        },
    })
    return path


def test_rights_metadata_is_optional_format_and_file_validation(tmp_path: Path) -> None:
    path = _metadata(tmp_path)
    result = validate_rights_metadata(
        path, repository_root=tmp_path, expected_site_id="alpha"
    )
    assert result["status"] == "valid"
    assert result["documented_category_count"] == 5
    assert set(result) == {
        "schema_version",
        "site_id",
        "categories",
        "status",
        "documented_category_count",
    }


def test_rights_metadata_rejects_size_drift(tmp_path: Path) -> None:
    path = _metadata(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["categories"]["images"]["evidence"][0]["bytes"] = 1
    _write(path, value)
    with pytest.raises(WorkflowError, match="byte count mismatch"):
        validate_rights_metadata(path, repository_root=tmp_path)
