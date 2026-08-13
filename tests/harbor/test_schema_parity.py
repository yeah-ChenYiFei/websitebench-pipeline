"""Guard the two schema directories against silent divergence.

``websitebench/schemas`` is canonical and ``src/websitebench/viewer/_schemas``
is a checked-in duplicate. ``_schema_path`` in
``src/websitebench/harbor/manifest.py`` prefers the canonical copy when a
source tree is present and falls back to the duplicate otherwise, so drift is
latent: it only changes behaviour in an installed wheel, where the canonical
copy is absent. Nothing synchronises the two directories automatically, so
these tests are the only thing that keeps them aligned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
CANONICAL = REPOSITORY / "websitebench" / "schemas"
BUNDLED = REPOSITORY / "src" / "websitebench" / "viewer" / "_schemas"


def _schema_names(root: Path) -> set[str]:
    return {path.name for path in root.glob("*.schema.json")}


def test_both_schema_directories_declare_the_same_files() -> None:
    canonical = _schema_names(CANONICAL)
    bundled = _schema_names(BUNDLED)
    assert canonical == bundled, (
        "schema directories disagree on which files exist; "
        f"canonical-only={sorted(canonical - bundled)} "
        f"bundled-only={sorted(bundled - canonical)}"
    )


@pytest.mark.parametrize("name", sorted(_schema_names(CANONICAL)))
def test_canonical_and_bundled_schemas_are_byte_identical(name: str) -> None:
    assert (CANONICAL / name).read_bytes() == (BUNDLED / name).read_bytes(), (
        f"{name} has drifted between websitebench/schemas and "
        "src/websitebench/viewer/_schemas; copy the canonical file over the "
        "bundled one"
    )
