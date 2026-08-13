"""Attach the shared WebsiteBench backend through its generated integration seam."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from websitebench.site_backend.runtime import validate_runtime
from websitebench.site_backend.vendor import RUNTIME_FILES, vendor_site_backend
from websitebench.local_clone_auth.vendor import (
    RUNTIME_FILES as AUTH_RUNTIME_FILES,
    vendor_local_clone_auth,
)

from .manifest import LoadedManifest, load_manifest


def _default_runtime(manifest: LoadedManifest) -> dict[str, Any]:
    site_id = str(manifest.data["site_id"])
    label = str(manifest.data["display_name"])
    return {
        "schema_version": "websitebench.site-backend-runtime.v1",
        "site": {
            "id": site_id,
            "label": label,
            "public_origin": f"https://{site_id}.offline.invalid",
        },
        "database": {
            "engine": "sqlite",
            "data_dir": "data",
            "filename": f"{site_id}.sqlite3",
            "migration_hook": None,
            "seed_hook": None,
            "legacy_unbound_migration": False,
        },
        "session": {
            "host_only": True,
            "secure": True,
            "http_only": True,
            "same_site": "Lax",
        },
        "mail": {
            "sender": {
                "display_name": label,
                "address_env": "RESEND_FROM_EMAIL",
            },
            "purposes": {
                "registration": {
                    "template_id": f"{site_id}.registration.v1",
                    "subject": f"Verify your {label} account",
                    "lead": f"Finish creating your {label} account.",
                    "body": "Your verification code is ${code}.",
                    "expiry": "This code expires in ${minutes} minutes.",
                    "footer": f"This code is only for {label}.",
                    "required_variables": ["code", "minutes"],
                    "secret_variables": ["code"],
                },
                "password-reset": {
                    "template_id": f"{site_id}.password-reset.v1",
                    "subject": f"Reset your {label} password",
                    "lead": f"A password reset was requested for {label}.",
                    "body": "Your password reset code is ${code}.",
                    "expiry": "This code expires in ${minutes} minutes.",
                    "footer": f"Ignore this message if you did not contact {label}.",
                    "required_variables": ["code", "minutes"],
                    "secret_variables": ["code"],
                },
            },
        },
        "payments": {
            "default_adapter": "local-sandbox",
            "currency": "USD",
            "local_sandbox": {
                "scenarios": [
                    {
                        "id": "sandbox-approved",
                        "outcome": "approved",
                        "display_label": "Simulated approval",
                    },
                    {
                        "id": "sandbox-declined",
                        "outcome": "declined",
                        "display_label": "Simulated decline",
                    },
                    {
                        "id": "sandbox-retry",
                        "outcome": "retryable",
                        "display_label": "Simulated retry",
                    },
                ]
            },
            "stripe_test": None,
        },
        "deployment": {
            "profiles": {
                "offline-harbor": {
                    "persistence": "persistent",
                    "mail_adapter": "local-outbox",
                    "payment_adapter": "local-sandbox",
                },
                "cloudflare-review": {
                    "persistence": "ephemeral-reset",
                    "mail_adapter": "redis-resend",
                    "payment_adapter": "local-sandbox",
                },
                "docker-volume": {
                    "persistence": "persistent-volume",
                    "mail_adapter": "effects-gateway",
                    "payment_adapter": "local-sandbox",
                },
            }
        },
    }


def scaffold_site_backend(site: Path) -> dict[str, Any]:
    # Scaffolding is ordered by the build and validated directly; no prior
    # diagnostic result is stored or consulted.
    manifest = load_manifest(site)

    runtime_path = manifest.root / "backend" / "runtime.json"
    candidate_root = manifest.resolve(manifest.data["paths"]["candidate_root"])
    vendor_root = candidate_root / "websitebench" / "site_backend"
    auth_vendor_root = candidate_root / "websitebench" / "local_clone_auth"
    integration_path = candidate_root / "backend" / "site_backend_integration.py"
    if runtime_path.exists():
        raise FileExistsError(f"backend runtime already exists: {runtime_path}")
    if vendor_root.exists():
        raise FileExistsError(f"vendored site backend already exists: {vendor_root}")
    if auth_vendor_root.exists():
        raise FileExistsError(
            f"vendored local auth runtime already exists: {auth_vendor_root}"
        )
    if integration_path.exists():
        raise FileExistsError(
            f"site backend integration already exists: {integration_path}"
        )
    for name in RUNTIME_FILES:
        source = (
            Path(__file__).resolve().parents[2]
            / "websitebench"
            / "site_backend"
            / name
        )
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"site backend runtime is unavailable: {name}")
    for name in AUTH_RUNTIME_FILES:
        source = (
            Path(__file__).resolve().parents[2]
            / "websitebench"
            / "local_clone_auth"
            / name
        )
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"local auth runtime is unavailable: {name}")

    runtime = _default_runtime(manifest)
    validate_runtime(runtime)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = runtime_path.with_name(f".{runtime_path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(runtime_path)
        vendor_manifest = vendor_site_backend(candidate_root)
        auth_vendor_manifest = vendor_local_clone_auth(candidate_root)
        integration_path.parent.mkdir(parents=True, exist_ok=True)
        integration_path.write_text(
            '''"""Generated, site-bound backend integration seam."""

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


DEFAULT_RUNTIME_PATH = (
    Path(__file__).resolve().parents[2] / "backend" / "runtime.json"
)
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
''',
            encoding="utf-8",
            newline="\n",
        )
    except Exception:
        runtime_path.unlink(missing_ok=True)
        integration_path.unlink(missing_ok=True)
        if vendor_root.exists():
            shutil.rmtree(vendor_root)
        if auth_vendor_root.exists():
            shutil.rmtree(auth_vendor_root)
        raise
    return {
        "status": "scaffolded",
        "site_id": manifest.data["site_id"],
        "runtime": str(runtime_path),
        "vendor_manifest": str(vendor_manifest),
        "auth_vendor_manifest": str(auth_vendor_manifest),
        "integration": str(integration_path),
        "business_schema": "not-generated",
        "payment_adapter": "local-sandbox",
    }
