"""Vendor the canonical local auth runtime into an offline clone candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


VENDOR_SCHEMA = "websitebench.local-clone-auth.vendor.v1"
RUNTIME_FILES = ("__init__.py", "store.py")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def vendor_local_clone_auth(
    candidate_root: Path,
) -> Path:
    unresolved_root = candidate_root.absolute()
    if not unresolved_root.is_dir() or unresolved_root.is_symlink():
        raise ValueError("candidate_root must be an existing real directory")
    root = unresolved_root.resolve()
    package_root = Path(__file__).resolve().parent
    namespace = "websitebench"
    namespace_root = root / namespace
    target_root = namespace_root / "local_clone_auth"
    target_root.mkdir(parents=True, exist_ok=True)
    namespace_init = namespace_root / "__init__.py"
    if not namespace_init.exists():
        namespace_init.write_text(
            f'"""Vendored {namespace} runtime components."""\n',
            encoding="utf-8",
            newline="\n",
        )
    elif not namespace_init.is_file() or namespace_init.is_symlink():
        raise ValueError(
            f"candidate {namespace} namespace is not a regular file"
        )

    manifest_files: list[dict[str, object]] = []
    for relative_name in RUNTIME_FILES:
        source = package_root / relative_name
        target = target_root / relative_name
        if not source.is_file() or source.is_symlink():
            raise ValueError(
                f"canonical local clone auth file is unavailable: {relative_name}"
            )
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
        "source": "src/websitebench/local_clone_auth",
        "files": manifest_files,
    }
    manifest_path = target_root / "VENDOR_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="websitebench-local-clone-auth-vendor")
    parser.add_argument("--candidate-root", type=Path, required=True)
    args = parser.parse_args()
    print(vendor_local_clone_auth(args.candidate_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
