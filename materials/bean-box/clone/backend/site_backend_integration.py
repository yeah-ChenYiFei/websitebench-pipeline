"""Generated, site-bound backend integration seam."""

from __future__ import annotations

import importlib
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable

from websitebench.local_clone_auth import LocalAuthStore
from websitebench.site_backend import (
    SiteBackend,
    load_runtime,
    serve_jsonl,
    validate_allowlist,
)


DEFAULT_RUNTIME_PATH = Path(__file__).resolve().parents[2] / "backend" / "runtime.json"
SANDBOX_RUNTIME_MIRROR = Path(__file__).resolve().parent / "runtime.json"
RUNTIME_SHA256 = "7cf987141301b4f98c4fa9ca028291cc13c05936ac7e093bfe934210d26d0e30"
BRIDGE_DESCRIPTOR_PATH = (
    Path(__file__).resolve().parents[2] / "backend" / "node-bridge.json"
)


def _declared_hook(
    declaration: str | None,
) -> Callable[[sqlite3.Connection], None] | None:
    if declaration is None:
        return None
    module_name, function_name = declaration.split(":", 1)
    module = importlib.import_module(module_name)
    hook: Any = getattr(module, function_name, None)
    if not callable(hook):
        raise RuntimeError(f"declared backend hook is not callable: {declaration}")
    actual = f"{hook.__module__}:{hook.__name__}"
    if actual != declaration:
        raise RuntimeError(
            f"declared backend hook resolved as {actual!r}, expected {declaration!r}"
        )
    return hook


def open_site_services() -> tuple[SiteBackend, LocalAuthStore]:
    """Open one bound database; never omit the site id for permanent auth."""

    runtime_path = Path(
        os.environ.get(
            "WEBSITEBENCH_SITE_BACKEND_RUNTIME",
            str(DEFAULT_RUNTIME_PATH),
        )
    ).resolve()
    runtime_digest = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    if runtime_digest != RUNTIME_SHA256:
        raise RuntimeError("runtime contract digest does not match the site-bound contract")
    runtime = load_runtime(runtime_path)
    if runtime.site_id != "bean-box":
        raise RuntimeError(f"runtime contract site_id {runtime.site_id!r} is not bound to bean-box")
    expected_runtime = DEFAULT_RUNTIME_PATH.resolve()
    if runtime_path != expected_runtime:
        if (
            runtime_path != SANDBOX_RUNTIME_MIRROR.resolve()
            or os.environ.get("WEBSITEBENCH_USE_SANDBOX_RUNTIME_MIRROR") != "1"
        ):
            raise RuntimeError("runtime override is disabled for this site")
    migration_hook = _declared_hook(runtime.migration_hook)
    seed_hook = _declared_hook(runtime.seed_hook)
    deployed_database = os.environ.get(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE",
    )
    if deployed_database is None:
        backend = SiteBackend.open(
            runtime_path,
            migration_hook=migration_hook,
            seed_hook=seed_hook,
        )
    else:
        database_path = Path(deployed_database).resolve()
        declared_data_dir = os.environ.get("WEBSITEBENCH_DATA_DIR")
        if (
            declared_data_dir
            and database_path.parent != Path(declared_data_dir).resolve()
            and os.environ.get("WEBSITEBENCH_ALLOW_TEST_DATABASE_OVERRIDE") != "1"
        ):
            raise RuntimeError("deployed database must remain in the site data directory")
        if database_path.name != runtime.database_filename:
            raise RuntimeError(
                "deployed database filename does not match runtime contract"
            )
        backend = SiteBackend.open(
            json.loads(runtime_path.read_text(encoding="utf-8")),
            data_root=database_path.parent,
            migration_hook=migration_hook,
            seed_hook=seed_hook,
        )
        if backend.lifecycle.database_path != database_path:
            raise RuntimeError(
                "deployed database path does not match backend preflight"
            )
    backend.lifecycle.initialize()
    # The shared lifecycle initializer is intentionally conservative once a
    # database exists. Site migrations are forward-only and idempotent, so run
    # the current hook on every boot to apply newly authored schema versions.
    if migration_hook is not None:
        with backend.lifecycle.connection(transaction=True) as connection:
            migration_hook(connection)
            if seed_hook is not None:
                seed_hook(connection)
    auth = LocalAuthStore(
        backend.lifecycle.database_path,
        site_id=backend.config.site_id,
    )
    auth.ensure_schema()
    return backend, auth


def run_stdio_bridge() -> None:
    """Run only operations frozen in this site's descriptor."""

    backend, auth = open_site_services()
    descriptor = json.loads(BRIDGE_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    allowed = validate_allowlist(
        descriptor,
        expected_site_id=backend.config.site_id,
    )
    serve_jsonl(backend, auth, allowed, sys.stdin, sys.stdout)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="websitebench-node-backend-bridge")
    parser.add_argument("--stdio", action="store_true", required=True)
    parser.parse_args()
    run_stdio_bridge()
