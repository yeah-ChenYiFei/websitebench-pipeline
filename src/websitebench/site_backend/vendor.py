"""Vendor the self-contained site backend runtime into a clone candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


VENDOR_SCHEMA = "websitebench.site-backend.vendor.v1"
RUNTIME_FILES = (
    "__init__.py",
    "auth_mail.py",
    "backend.py",
    "database.py",
    "effects_mail.py",
    "errors.py",
    "mail.py",
    "payments.py",
    "runtime.py",
    "stdio_bridge.py",
    "stripe_test.py",
    "validation_cli.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def vendor_site_backend(candidate_root: Path, *, overwrite: bool = False) -> Path:
    unresolved_root = candidate_root.absolute()
    if not unresolved_root.is_dir() or unresolved_root.is_symlink():
        raise ValueError("candidate_root must be an existing real directory")
    root = unresolved_root.resolve()
    package_root = Path(__file__).resolve().parent
    namespace_root = root / "websitebench"
    target_root = namespace_root / "site_backend"
    manifest_path = target_root / "VENDOR_MANIFEST.json"
    if target_root.exists() and any(target_root.iterdir()) and not overwrite:
        raise FileExistsError("site_backend runtime already exists in candidate")
    target_root.mkdir(parents=True, exist_ok=True)
    namespace_init = namespace_root / "__init__.py"
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
        target = target_root / relative_name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"canonical site backend file is unavailable: {relative_name}")
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
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": VENDOR_SCHEMA,
                "source": "src/websitebench/site_backend",
                "files": manifest_files,
            },
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
    parser = argparse.ArgumentParser(prog="websitebench-site-backend-vendor")
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(vendor_site_backend(args.candidate_root, overwrite=args.overwrite))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
