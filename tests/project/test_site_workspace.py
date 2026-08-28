from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "site_workspace", ROOT / "scripts" / "site_workspace.py"
)
assert SPEC and SPEC.loader
site_workspace = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = site_workspace
SPEC.loader.exec_module(site_workspace)


def write_registry(root: Path, sites: list[dict[str, object]]) -> None:
    (root / "sites").mkdir()
    (root / "sites" / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": "example/pipeline",
                "sites": sites,
            }
        ),
        encoding="utf-8",
    )


def example_site(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": "example-shop",
        "material_path": "materials/example-shop",
        "component_paths": ["materials/example-shop"],
        "branch": "sites/example-shop",
        "branch_status": "active",
        "snapshot": {"repo": "example/pipeline", "pr": 7, "sha": "abc"},
    }
    result.update(overrides)
    return result


def test_load_registry_accepts_historical_material_alias(tmp_path: Path) -> None:
    write_registry(
        tmp_path,
        [
            example_site(
                id="coursera",
                branch="sites/coursera",
                material_path="materials/33",
                component_paths=[
                    "materials/33",
                    "harbor/sites/33",
                    "harbor/instances/33",
                ],
            )
        ],
    )

    repository, sites = site_workspace.load_registry(tmp_path)

    assert repository == "example/pipeline"
    assert sites["coursera"] == site_workspace.SiteBranch(
        site_id="coursera",
        material_path=Path("materials/33"),
        component_paths=(
            Path("materials/33"),
            Path("harbor/sites/33"),
            Path("harbor/instances/33"),
        ),
        branch="sites/coursera",
        status="active",
        snapshot={"repo": "example/pipeline", "pr": 7, "sha": "abc"},
    )


def test_load_registry_rejects_branch_that_does_not_match_site(tmp_path: Path) -> None:
    write_registry(tmp_path, [example_site(branch="sites/another-shop")])

    with pytest.raises(site_workspace.WorkspaceError, match="must use branch"):
        site_workspace.load_registry(tmp_path)


def test_load_registry_rejects_paths_outside_materials(tmp_path: Path) -> None:
    write_registry(tmp_path, [example_site(material_path="vendor/example-shop")])

    with pytest.raises(site_workspace.WorkspaceError, match="materials/<material-id>"):
        site_workspace.load_registry(tmp_path)


def test_clone_command_is_shallow_filtered_and_single_branch() -> None:
    site = site_workspace.SiteBranch(
        site_id="example-shop",
        material_path=Path("materials/example-shop"),
        component_paths=(Path("materials/example-shop"),),
        branch="sites/example-shop",
        status="active",
        snapshot={},
    )

    assert site_workspace.clone_command(
        site, "example/pipeline", Path("websitebench-example-shop")
    ) == [
        "git",
        "clone",
        "--single-branch",
        "--branch",
        "sites/example-shop",
        "--filter=blob:none",
        "--depth=1",
        "https://github.com/example/pipeline.git",
        "websitebench-example-shop",
    ]


def test_fetch_command_fetches_only_exact_persistent_branch() -> None:
    site = site_workspace.SiteBranch(
        site_id="example-shop",
        material_path=Path("materials/example-shop"),
        component_paths=(Path("materials/example-shop"),),
        branch="sites/example-shop",
        status="active",
        snapshot={},
    )

    assert site_workspace.fetch_command(site) == [
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "--filter=blob:none",
        "origin",
        "refs/heads/sites/example-shop:refs/remotes/origin/sites/example-shop",
    ]


def test_pr_fetch_command_fetches_only_pull_head() -> None:
    assert site_workspace.pr_fetch_command(123) == [
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "--filter=blob:none",
        "origin",
        "refs/pull/123/head:refs/remotes/origin/pr/123",
    ]


def test_destination_must_be_outside_main_checkout(tmp_path: Path) -> None:
    root = tmp_path / "pipeline"
    root.mkdir()

    with pytest.raises(site_workspace.WorkspaceError, match="outside"):
        site_workspace.ensure_destination_available(root, root / "review")


def test_require_site_rejects_unregistered_names() -> None:
    with pytest.raises(site_workspace.WorkspaceError, match="not registered"):
        site_workspace.require_site({}, "missing-site")
