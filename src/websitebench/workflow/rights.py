"""Optional machine validation for redistribution-rights metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from websitebench.site_compiler.schema import load_json_document

from .errors import WorkflowError
from .io import resolve_relative

RIGHTS_CATEGORIES = (
    "trademark",
    "images",
    "fonts",
    "content",
    "code",
)


def validate_rights_metadata(
    path: Path | str,
    *,
    repository_root: Path | str | None = None,
    expected_site_id: str | None = None,
) -> dict[str, Any]:
    document_path = Path(path).resolve()
    value = load_json_document(
        document_path,
        "offline-clone-rights-metadata-v2.schema.json",
    )
    root = (
        Path(repository_root).resolve()
        if repository_root is not None
        else document_path.parents[3]
    )
    problems: list[str] = []
    if expected_site_id is not None and value["site_id"] != expected_site_id:
        problems.append("rights metadata site_id does not match the workflow site")
    categories = value["categories"]
    if set(categories) != set(RIGHTS_CATEGORIES):
        problems.append("rights metadata must cover the five exact rights categories")
    for category, item in categories.items():
        for evidence in item["evidence"]:
            evidence_path = resolve_relative(root, evidence["path"], must_exist=True)
            if not evidence_path.is_file():
                problems.append(
                    f"{category}: evidence is not a regular file: {evidence['path']}"
                )
            elif evidence_path.stat().st_size != evidence["bytes"]:
                problems.append(
                    f"{category}: evidence byte count mismatch: {evidence['path']}"
                )
    if problems:
        raise WorkflowError(problems)
    return {
        **value,
        "status": "valid",
        "documented_category_count": sum(
            item["status"] == "documented" for item in categories.values()
        ),
    }
