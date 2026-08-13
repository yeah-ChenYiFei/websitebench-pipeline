"""Trusted, fixed-shape launcher for built Node offline clones.

The verify driver must begin every declared boot command with ``{python}``.
This module preserves that trust boundary while allowing only two repository-
owned Node server layouts; it never accepts an arbitrary script or command.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


PROFILES = {
    "vinext": Path("node_modules/vinext/dist/cli.js"),
    "next-standalone": Path(".next/standalone/server.js"),
    "next-standalone-linkedin": Path(".next/standalone/server.js"),
}


class NodeLauncherError(ValueError):
    """Raised when a declared Node clone is not a safe built candidate."""


def _regular_child(root: Path, relative: Path) -> Path:
    target = root / relative
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise NodeLauncherError(f"required built file is unavailable: {relative}") from exc
    if root not in resolved.parents or not resolved.is_file() or target.is_symlink():
        raise NodeLauncherError(f"required built file is unsafe: {relative}")
    return resolved


def launch(profile: str, port: int) -> None:
    """Replace this process with the selected fixed Node server."""

    if profile not in PROFILES:
        raise NodeLauncherError(f"unsupported Node clone profile: {profile}")
    if not 1 <= port <= 65535:
        raise NodeLauncherError("port must be between 1 and 65535")
    root = Path.cwd().resolve(strict=True)
    _regular_child(root, Path("package.json"))
    target = _regular_child(root, PROFILES[profile])
    configured_node = os.environ.get("WEBSITEBENCH_NODE_EXECUTABLE")
    node_path = Path(configured_node) if configured_node else None
    if node_path is not None:
        try:
            node_path = node_path.resolve(strict=True)
        except OSError as exc:
            raise NodeLauncherError(
                "the trusted Node executable is unavailable"
            ) from exc
        if (
            not node_path.is_absolute()
            or node_path.name != "node"
            or not node_path.is_file()
        ):
            raise NodeLauncherError("the trusted Node executable is invalid")
        node = str(node_path)
    else:
        node = shutil.which("node")
    if node is None:
        raise NodeLauncherError("the trusted Node executable is unavailable")

    environment = dict(os.environ)
    environment.update(
        {
            "HOST": "127.0.0.1",
            "HOSTNAME": "127.0.0.1",
            "PORT": str(port),
            "RAYON_NUM_THREADS": "2",
            "UV_THREADPOOL_SIZE": "4",
        }
    )
    if profile == "next-standalone-linkedin":
        environment.update(
            {
                "APP_URL": f"http://127.0.0.1:{port}",
                "PUBLIC_CLONE_AUTH_ALLOW_LOCAL_FALLBACK": "true",
                "PUBLIC_CLONE_AUTH_MODE": "local-dev",
                "SESSION_COOKIE_SECURE": "false",
            }
        )
    argv = [node]
    if profile == "vinext":
        # Keep V8's heap reservation inside the verifier's 2 GiB address-space
        # ceiling. This is fixed verifier policy, never candidate NODE_OPTIONS.
        argv.append("--max-old-space-size=768")
        argv.append("--v8-pool-size=2")
    argv.append(str(target))
    if profile == "vinext":
        argv.extend(["start", "--hostname", "127.0.0.1", "--port", str(port)])
    os.execve(node, argv, environment)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="websitebench-node-clone-launcher")
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES))
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        launch(args.profile, args.port)
    except (NodeLauncherError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
