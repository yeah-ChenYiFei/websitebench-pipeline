#!/usr/bin/env python3
"""Prepare one persistent site branch in an isolated worktree.

This migration helper never commits, pushes, deletes refs, or rewrites history.
It creates a local branch from a caller-selected slim base and restores only the
component paths recorded for one frozen site snapshot.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import site_workspace


def run(command: Sequence[str], *, cwd: Path) -> None:
    subprocess.run(list(command), cwd=cwd, check=True)


def output(command: Sequence[str], *, cwd: Path) -> str:
    result = subprocess.run(
        list(command), cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def source_remote_name(repository: str) -> str:
    return "migration-" + re.sub(r"[^a-z0-9]+", "-", repository.lower()).strip("-")


def ensure_source_remote(root: Path, repository: str) -> str:
    remote = source_remote_name(repository)
    expected_url = f"https://github.com/{repository}.git"
    result = subprocess.run(
        ["git", "remote", "get-url", remote],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        actual_url = result.stdout.strip()
        if actual_url != expected_url:
            raise site_workspace.WorkspaceError(
                f"remote {remote!r} uses {actual_url!r}, expected {expected_url!r}"
            )
    else:
        run(["git", "remote", "add", remote, expected_url], cwd=root)
    run(["git", "config", f"remote.{remote}.promisor", "true"], cwd=root)
    run(
        ["git", "config", f"remote.{remote}.partialclonefilter", "blob:none"],
        cwd=root,
    )
    return remote


def snapshot_fetch_command(
    site: site_workspace.SiteBranch, remote: str
) -> tuple[list[str], str]:
    pr = site.snapshot.get("pr")
    if not isinstance(pr, int) or pr <= 0:
        raise site_workspace.WorkspaceError(
            f"{site.site_id} snapshot is missing a positive PR number"
        )
    ref = f"refs/remotes/{remote}/snapshot/{site.site_id}"
    return (
        [
            "git",
            "fetch",
            "--no-tags",
            "--depth=1",
            "--filter=blob:none",
            remote,
            f"refs/pull/{pr}/head:{ref}",
        ],
        ref,
    )


def require_commit(root: Path, revision: str) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise site_workspace.WorkspaceError(f"base is not a commit: {revision}")


def require_missing_branch(root: Path, branch: str) -> None:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=root,
        check=False,
    )
    if result.returncode == 0:
        raise site_workspace.WorkspaceError(f"local branch already exists: {branch}")


def prepare(
    root: Path,
    site: site_workspace.SiteBranch,
    base: str,
    branch: str,
    destination: Path,
) -> None:
    require_commit(root, base)
    require_missing_branch(root, branch)
    destination = site_workspace.ensure_destination_available(root, destination)

    repository = site.snapshot.get("repo")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise site_workspace.WorkspaceError(
            f"{site.site_id} snapshot repository is invalid"
        )
    remote = ensure_source_remote(root, repository)
    fetch_command, snapshot_ref = snapshot_fetch_command(site, remote)
    run(fetch_command, cwd=root)

    run(
        ["git", "worktree", "add", "-b", branch, str(destination), base],
        cwd=root,
    )
    try:
        run(
            [
                "git",
                "restore",
                "--source",
                snapshot_ref,
                "--staged",
                "--worktree",
                "--",
                *(path.as_posix() for path in site.component_paths),
            ],
            cwd=destination,
        )
    except subprocess.CalledProcessError:
        print(
            f"worktree kept for inspection after restore failure: {destination}",
            file=sys.stderr,
        )
        raise

    changed = output(["git", "diff", "--cached", "--name-only"], cwd=destination)
    if not changed:
        raise site_workspace.WorkspaceError(
            "snapshot produced no staged changes; check the base and component paths"
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Prepare one local site branch from a frozen PR snapshot."
    )
    result.add_argument("site_id")
    result.add_argument(
        "--repo", type=Path, help="Pipeline checkout (defaults to current repository)"
    )
    result.add_argument(
        "--base", default="main", help="verified slim Pipeline commit or ref"
    )
    result.add_argument(
        "--branch", help="local branch name (defaults to the registered site branch)"
    )
    result.add_argument("--destination", type=Path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = site_workspace.repository_root(args.repo)
        _, sites = site_workspace.load_registry(root)
        site = site_workspace.require_site(sites, args.site_id)
        branch = args.branch or site.branch
        destination = args.destination or site_workspace.default_destination(
            root, site, "-migration"
        )
        prepare(root, site, args.base, branch, destination)
        print(destination.expanduser().resolve())
        if not site.snapshot.get("merged_at"):
            print(
                "warning: the frozen source is an unmerged PR head; preserve that fact"
            )
        if not site.snapshot.get("draft") and site.snapshot.get("pr_state") == "open":
            print("source status: open PR")
        return 0
    except (site_workspace.WorkspaceError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
