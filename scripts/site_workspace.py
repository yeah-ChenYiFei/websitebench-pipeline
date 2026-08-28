#!/usr/bin/env python3
"""Fetch exactly one persistent WebsiteBench site branch.

The supported repository layout keeps shared Pipeline code on ``main`` and one
site on each ``sites/<site-id>`` branch. This helper intentionally uses shallow,
blob-filtered, single-ref fetches so a main checkout does not download every
website.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


SITE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DEFAULT_REPOSITORY = "780078268/websitebench-pipeline"
DEFAULT_URL = f"https://github.com/{DEFAULT_REPOSITORY}.git"


class WorkspaceError(RuntimeError):
    """A user-facing site workspace error."""


@dataclass(frozen=True)
class SiteBranch:
    site_id: str
    material_path: Path
    component_paths: tuple[Path, ...]
    branch: str
    status: str
    snapshot: dict[str, Any]


def repository_root(candidate: Path | None = None) -> Path:
    command = ["git"]
    if candidate is not None:
        command.extend(["-C", str(candidate)])
    command.extend(["rev-parse", "--show-toplevel"])
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise WorkspaceError("run this command inside a Pipeline Git checkout")
    return Path(result.stdout.strip()).resolve()


def load_registry(root: Path) -> tuple[str, dict[str, SiteBranch]]:
    registry_path = root / "sites" / "registry.json"
    if not registry_path.is_file():
        raise WorkspaceError(f"missing site registry: {registry_path}")
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceError(f"cannot read site registry: {error}") from error

    repository = payload.get("repository", DEFAULT_REPOSITORY)
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise WorkspaceError("registry repository must be in owner/name form")
    raw_sites = payload.get("sites")
    if not isinstance(raw_sites, list):
        raise WorkspaceError("registry sites must be a list")

    sites: dict[str, SiteBranch] = {}
    for raw in raw_sites:
        if not isinstance(raw, dict):
            raise WorkspaceError("every registry site must be an object")
        site_id = raw.get("id")
        material_path = raw.get("material_path")
        raw_component_paths = raw.get("component_paths", [material_path])
        branch = raw.get("branch")
        status = raw.get("branch_status", "planned")
        snapshot = raw.get("snapshot", {})
        if not isinstance(site_id, str) or not SITE_ID.fullmatch(site_id):
            raise WorkspaceError(f"invalid registry site id: {site_id!r}")
        expected_branch = f"sites/{site_id}"
        if branch != expected_branch:
            raise WorkspaceError(
                f"{site_id} must use branch {expected_branch!r}, got {branch!r}"
            )
        path = Path(material_path) if isinstance(material_path, str) else Path()
        if len(path.parts) != 2 or path.parts[0] != "materials":
            raise WorkspaceError(
                f"{site_id} must use materials/<material-id>, got {material_path!r}"
            )
        if not isinstance(raw_component_paths, list) or not raw_component_paths:
            raise WorkspaceError(f"{site_id} component_paths must be a non-empty list")
        component_paths = tuple(Path(item) for item in raw_component_paths)
        if component_paths[0] != path:
            raise WorkspaceError(
                f"{site_id} component_paths must start with {path.as_posix()!r}"
            )
        if any(component.is_absolute() or ".." in component.parts for component in component_paths):
            raise WorkspaceError(f"{site_id} has an unsafe component path")
        if site_id in sites:
            raise WorkspaceError(f"duplicate registry site id: {site_id}")
        sites[site_id] = SiteBranch(
            site_id=site_id,
            material_path=path,
            component_paths=component_paths,
            branch=branch,
            status=str(status),
            snapshot=snapshot if isinstance(snapshot, dict) else {},
        )
    return repository, sites


def require_site(sites: dict[str, SiteBranch], site_id: str) -> SiteBranch:
    if not SITE_ID.fullmatch(site_id):
        raise WorkspaceError(
            "site id must contain lowercase letters, digits, and hyphens only"
        )
    site = sites.get(site_id)
    if site is None:
        raise WorkspaceError(f"site is not registered: {site_id}")
    return site


def run(command: Sequence[str], *, cwd: Path) -> None:
    subprocess.run(list(command), cwd=cwd, check=True)


def shell_command(command: Sequence[str]) -> str:
    return shlex.join(str(item) for item in command)


def clone_command(site: SiteBranch, repository: str, destination: Path) -> list[str]:
    return [
        "git",
        "clone",
        "--single-branch",
        "--branch",
        site.branch,
        "--filter=blob:none",
        "--depth=1",
        f"https://github.com/{repository}.git",
        str(destination),
    ]


def fetch_command(site: SiteBranch) -> list[str]:
    return [
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "--filter=blob:none",
        "origin",
        f"refs/heads/{site.branch}:refs/remotes/origin/{site.branch}",
    ]


def pr_fetch_command(pr: int) -> list[str]:
    return [
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "--filter=blob:none",
        "origin",
        f"refs/pull/{pr}/head:refs/remotes/origin/pr/{pr}",
    ]


def default_destination(root: Path, site: SiteBranch, suffix: str = "") -> Path:
    return root.parent / f"{root.name}-{site.site_id}{suffix}"


def ensure_destination_available(root: Path, destination: Path) -> Path:
    resolved = destination.expanduser().resolve()
    if resolved == root or root in resolved.parents:
        raise WorkspaceError("site worktrees must be outside the main checkout")
    if resolved.exists():
        raise WorkspaceError(f"destination already exists: {resolved}")
    return resolved


def checkout(root: Path, site: SiteBranch, destination: Path) -> None:
    destination = ensure_destination_available(root, destination)
    run(fetch_command(site), cwd=root)
    run(
        [
            "git",
            "worktree",
            "add",
            "--detach",
            str(destination),
            f"refs/remotes/origin/{site.branch}",
        ],
        cwd=root,
    )


def pr_base(repository: str, pr: int) -> str:
    result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            repository,
            "--json",
            "baseRefName",
            "--jq",
            ".baseRefName",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WorkspaceError(result.stderr.strip() or f"cannot read PR {pr}")
    return result.stdout.strip()


def review(
    root: Path,
    repository: str,
    site: SiteBranch,
    pr: int,
    destination: Path,
) -> None:
    base = pr_base(repository, pr)
    if base != site.branch:
        raise WorkspaceError(
            f"PR {pr} targets {base!r}; expected {site.branch!r} for {site.site_id}"
        )
    destination = ensure_destination_available(root, destination)
    run(pr_fetch_command(pr), cwd=root)
    run(
        [
            "git",
            "worktree",
            "add",
            "--detach",
            str(destination),
            f"refs/remotes/origin/pr/{pr}",
        ],
        cwd=root,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Clone or review exactly one WebsiteBench site branch."
    )
    result.add_argument(
        "--repo",
        type=Path,
        help="Pipeline checkout (defaults to the current Git repository)",
    )
    subcommands = result.add_subparsers(dest="command", required=True)
    subcommands.add_parser("list", help="List registered site branches")

    command_parser = subcommands.add_parser(
        "command", help="Print the shallow single-site clone command"
    )
    command_parser.add_argument("site_id")
    command_parser.add_argument("--destination", type=Path)

    fetch_parser = subcommands.add_parser(
        "fetch", help="Fetch exactly one persistent site branch"
    )
    fetch_parser.add_argument("site_id")

    checkout_parser = subcommands.add_parser(
        "checkout", help="Fetch one site and add a detached sibling worktree"
    )
    checkout_parser.add_argument("site_id")
    checkout_parser.add_argument("--destination", type=Path)

    review_parser = subcommands.add_parser(
        "review", help="Verify a site's PR base and add a detached review worktree"
    )
    review_parser.add_argument("site_id")
    review_parser.add_argument("--pr", type=int, required=True)
    review_parser.add_argument("--destination", type=Path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = repository_root(args.repo)
        repository, sites = load_registry(root)
        if args.command == "list":
            for site_id in sorted(sites):
                site = sites[site_id]
                snapshot = site.snapshot
                pr = snapshot.get("pr")
                source = f"{snapshot.get('repo', '-')}#{pr}" if pr else "-"
                print(
                    f"{site.site_id}\t{site.status}\t{site.branch}\t"
                    f"{site.material_path.as_posix()}\t{source}"
                )
            return 0

        site = require_site(sites, args.site_id)
        if args.command == "command":
            destination = args.destination or Path(f"websitebench-{site.site_id}")
            print(shell_command(clone_command(site, repository, destination)))
        elif args.command == "fetch":
            run(fetch_command(site), cwd=root)
        elif args.command == "checkout":
            destination = args.destination or default_destination(root, site)
            checkout(root, site, destination)
            print(destination.expanduser().resolve())
        elif args.command == "review":
            destination = args.destination or default_destination(
                root, site, f"-pr-{args.pr}"
            )
            review(root, repository, site, args.pr, destination)
            print(destination.expanduser().resolve())
        return 0
    except (WorkspaceError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
