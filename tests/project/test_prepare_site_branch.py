from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "prepare_site_branch", SCRIPTS / "prepare_site_branch.py"
)
assert SPEC and SPEC.loader
prepare_site_branch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare_site_branch
SPEC.loader.exec_module(prepare_site_branch)
site_workspace = prepare_site_branch.site_workspace


def site(snapshot: dict[str, object]) -> site_workspace.SiteBranch:
    return site_workspace.SiteBranch(
        site_id="example-shop",
        material_path=Path("materials/example-shop"),
        component_paths=(
            Path("materials/example-shop"),
            Path("harbor/sites/example-shop"),
        ),
        branch="sites/example-shop",
        status="planned",
        snapshot=snapshot,
    )


def test_source_remote_name_is_stable() -> None:
    assert (
        prepare_site_branch.source_remote_name("Example/Pipeline")
        == "migration-example-pipeline"
    )


def test_snapshot_fetch_command_fetches_only_one_pull_ref() -> None:
    command, ref = prepare_site_branch.snapshot_fetch_command(
        site({"repo": "example/pipeline", "pr": 7}),
        "migration-example-pipeline",
    )

    assert command == [
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "--filter=blob:none",
        "migration-example-pipeline",
        "refs/pull/7/head:refs/remotes/migration-example-pipeline/snapshot/example-shop",
    ]
    assert ref == "refs/remotes/migration-example-pipeline/snapshot/example-shop"


def test_snapshot_fetch_command_requires_pr_number() -> None:
    with pytest.raises(site_workspace.WorkspaceError, match="PR number"):
        prepare_site_branch.snapshot_fetch_command(
            site({"repo": "example/pipeline"}), "migration-example-pipeline"
        )
