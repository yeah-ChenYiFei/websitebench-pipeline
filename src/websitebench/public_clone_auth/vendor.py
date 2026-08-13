"""Vendor the shared runtime into a self-contained offline clone candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


VENDOR_SCHEMA = "websitebench.public-clone-auth.vendor.v1"
RUNTIME_FILES = (
    "__init__.py",
    "fastapi.py",
    "frontend.py",
    "sqlite.py",
    "verification.py",
    "static/verification.js",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def vendor_public_clone_auth(candidate_root: Path) -> Path:
    """Copy the canonical runtime into ``candidate_root/websitebench``.

    The target clone remains self-contained for Harbor and its candidate-tree
    fingerprint includes the exact shared runtime it executes.
    """

    unresolved_root = candidate_root.absolute()
    if not unresolved_root.is_dir() or unresolved_root.is_symlink():
        raise ValueError("candidate_root must be an existing real directory")
    root = unresolved_root.resolve()
    package_root = Path(__file__).resolve().parent
    target_websitebench = root / "websitebench"
    target_package = target_websitebench / "public_clone_auth"
    target_package.mkdir(parents=True, exist_ok=True)
    namespace_init = target_websitebench / "__init__.py"
    if not namespace_init.exists():
        namespace_init.write_text(
            '"""Vendored WebsiteBench runtime modules."""\n',
            encoding="utf-8",
            newline="\n",
        )
    elif not namespace_init.is_file() or namespace_init.is_symlink():
        raise ValueError("candidate websitebench namespace is not a regular file")

    manifest_files: list[dict[str, object]] = []
    for relative_name in RUNTIME_FILES:
        source = package_root / relative_name
        target = target_package / relative_name
        if not source.is_file() or source.is_symlink():
            raise ValueError(
                f"canonical public clone auth file is unavailable: {relative_name}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        temporary.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        temporary.replace(target)
        manifest_files.append(
            {
                "path": relative_name,
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )

    manifest = {
        "schema_version": VENDOR_SCHEMA,
        "source": "src/websitebench/public_clone_auth",
        "files": manifest_files,
    }
    manifest_path = target_package / "VENDOR_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="websitebench-public-clone-auth-vendor")
    parser.add_argument(
        "--candidate-root",
        type=Path,
        required=True,
        help="clone candidate directory that will receive the vendored runtime",
    )
    args = parser.parse_args()
    manifest_path = vendor_public_clone_auth(args.candidate_root)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
