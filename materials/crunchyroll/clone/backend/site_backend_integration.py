"""Generated, site-bound backend integration seam."""

from __future__ import annotations

import importlib
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
    runtime = load_runtime(runtime_path)
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
