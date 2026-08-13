"""Fail-closed site-backend preflight, then exec the frozen application argv."""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable


def _declared_hook(
    declaration: str | None,
    *,
    import_root: Path | None = None,
) -> Callable[[sqlite3.Connection], None] | None:
    if declaration is None:
        return None
    module_name, function_name = declaration.split(":", 1)
    if import_root is not None and module_name in sys.modules:
        cached = sys.modules[module_name]
        cached_file = getattr(cached, "__file__", None)
        if (
            cached_file is None
            or not Path(cached_file).resolve().is_relative_to(import_root)
        ):
            # A long-lived verifier process may preflight multiple isolated
            # clone roots. Never let Python's module cache select another
            # site's hook implementation.
            del sys.modules[module_name]
    importlib.invalidate_caches()
    module = importlib.import_module(module_name)
    if import_root is not None:
        module_file = getattr(module, "__file__", None)
        if (
            module_file is None
            or not Path(module_file).resolve().is_relative_to(import_root)
        ):
            raise RuntimeError(
                "declared backend hook did not resolve from the clone root: "
                f"{declaration}"
            )
    hook: Any = getattr(module, function_name, None)
    if not callable(hook):
        raise RuntimeError(f"declared backend hook is not callable: {declaration}")
    actual = f"{hook.__module__}:{hook.__name__}"
    if actual != declaration:
        raise RuntimeError(
            f"declared backend hook resolved as {actual!r}, expected {declaration!r}"
        )
    return hook


def preflight_backend(
    deployment_path: Path,
    backend_runtime_path: Path,
    data_root: Path,
    *,
    hook_import_root: Path | None = None,
) -> dict[str, Any] | None:
    """Initialize/bind the exact site database before public traffic starts."""

    if hook_import_root is not None:
        resolved_hook_root = hook_import_root.resolve(strict=True)
        if not resolved_hook_root.is_dir():
            raise RuntimeError("backend hook import root must be a directory")
        hook_root_text = str(resolved_hook_root)
        if hook_root_text not in sys.path:
            sys.path.insert(0, hook_root_text)

    deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    if (
        deployment.get("schema_version")
        != "websitebench.generic-public-clone-deployment.v2"
    ):
        return None
    if not backend_runtime_path.is_file():
        raise RuntimeError("v2 deployment is missing backend-runtime.json")
    runtime = json.loads(backend_runtime_path.read_text(encoding="utf-8"))
    if (
        runtime.get("schema_version")
        == "websitebench.site-backend-runtime.v1"
    ):
        from websitebench.site_backend import SiteBackend, load_runtime

        runtime_environment_prefix = "WEBSITEBENCH"
    elif runtime.get("schema_version") == "clawbench.site-backend-runtime.v1":
        # Explicit compatibility adapter for already-migrated clone databases.
        # New scaffold output never selects this branch.
        from clawbench.site_backend import SiteBackend, load_runtime

        runtime_environment_prefix = "CLAWBENCH"
    else:
        raise RuntimeError("unsupported backend runtime schema_version")
    config = load_runtime(runtime)
    migration_hook = _declared_hook(
        config.migration_hook,
        import_root=resolved_hook_root if hook_import_root is not None else None,
    )
    seed_hook = _declared_hook(
        config.seed_hook,
        import_root=resolved_hook_root if hook_import_root is not None else None,
    )
    backend = SiteBackend.open(
        runtime,
        data_root=data_root,
        migration_hook=migration_hook,
        seed_hook=seed_hook,
    )
    # Normal startup is never migration authorization. A pre-existing,
    # unbound legacy database must be adopted by a separate, explicit site
    # migration command before this public launcher will accept it.
    result = backend.lifecycle.initialize()
    os.environ[f"{runtime_environment_prefix}_SITE_BACKEND_RUNTIME"] = str(
        backend_runtime_path
    )
    os.environ[f"{runtime_environment_prefix}_SITE_BACKEND_DATABASE"] = str(
        backend.lifecycle.database_path
    )
    return result


def main() -> None:
    deployment_path = Path("/app/runtime/deployment.json")
    value = json.loads(deployment_path.read_text(encoding="utf-8"))
    backend_runtime = Path("/app/runtime/backend-runtime.json")
    data_root = Path(os.environ.get("WEBSITEBENCH_DATA_DIR", "/data"))
    try:
        preflight_backend(
            deployment_path,
            backend_runtime,
            data_root,
            hook_import_root=Path("/app/clone"),
        )
    except Exception as exc:
        raise SystemExit(f"site backend preflight failed: {exc}") from exc
    command = value["runtime"]["command"]
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item and "\x00" not in item for item in command
    ):
        raise SystemExit("invalid deployment runtime command")
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
