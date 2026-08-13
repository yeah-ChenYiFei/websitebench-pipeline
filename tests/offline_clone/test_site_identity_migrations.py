from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


REPOSITORY = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_site_identity_migrations_preserve_research_and_resolve_active_files() -> None:
    manifests = sorted(
        (REPOSITORY / "materials").glob("*/migration/*.json")
    )
    assert manifests, "no site identity migration manifest is checked in"
    for manifest_path in manifests:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert value["schema_version"] == "websitebench.site-identity-migration.v1"
        target_root = REPOSITORY / value["target"]["path"]
        assert target_root.resolve().is_relative_to(REPOSITORY / "materials")
        for section in ("regenerated_active_files", "active_identity_edits"):
            for item in value[section]:
                relative = PurePosixPath(item["path"])
                assert not relative.is_absolute() and ".." not in relative.parts
                path = target_root / relative
                assert path.is_file()
                before = item.get("before_sha256")
                assert before is None or (
                    len(before) == 64
                    and all(character in "0123456789abcdef" for character in before)
                )
        for item in value["byte_preserved_research"]:
            relative = PurePosixPath(item["path"])
            assert not relative.is_absolute() and ".." not in relative.parts
            path = target_root / relative
            assert _sha256(path) == item["sha256"], f"historical bytes changed: {path}"
