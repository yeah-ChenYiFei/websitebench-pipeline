from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from websitebench.offline_clone import backend_scaffold
from websitebench.offline_clone.cli import main
from websitebench.site_backend import RUNTIME_SCHEMA_VERSION, load_runtime

from .helpers import initialized_site


def test_backend_scaffold_is_site_branded_vendored_and_non_overwriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = initialized_site(tmp_path)
    assert main(["backend", "scaffold", "--site", str(root)]) == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["business_schema"] == "not-generated"
    runtime = load_runtime(root / "backend/runtime.json")
    assert runtime.site_id == "example-shop"
    assert runtime.public_origin == "https://example-shop.offline.invalid"
    assert runtime.mail["sender"]["display_name"] == "Example Shop"
    assert runtime.payments["default_adapter"] == "local-sandbox"
    vendor = json.loads(
        (root / "clone/websitebench/site_backend/VENDOR_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    assert vendor["schema_version"] == "websitebench.site-backend.vendor.v1"
    assert runtime.raw["schema_version"] == RUNTIME_SCHEMA_VERSION
    assert {item["path"] for item in vendor["files"]} >= {
        "__init__.py",
        "database.py",
        "payments.py",
    }
    auth_vendor = json.loads(
        (
            root
            / "clone/websitebench/local_clone_auth/VENDOR_MANIFEST.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        auth_vendor["schema_version"]
        == "websitebench.local-clone-auth.vendor.v1"
    )
    integration = (
        root / "clone/backend/site_backend_integration.py"
    ).read_text(encoding="utf-8")
    assert "site_id=backend.config.site_id" in integration
    assert "LocalAuthStore(" in integration
    assert "WEBSITEBENCH_SITE_BACKEND_RUNTIME" in integration
    assert "WEBSITEBENCH_SITE_BACKEND_DATABASE" in integration

    deployed_runtime = tmp_path / "container" / "backend-runtime.json"
    deployed_runtime.parent.mkdir()
    deployed_runtime.write_bytes((root / "backend/runtime.json").read_bytes())
    deployed_database = tmp_path / "volume" / "example-shop.sqlite3"
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_RUNTIME",
        str(deployed_runtime),
    )
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE",
        str(deployed_database),
    )
    integration_path = root / "clone/backend/site_backend_integration.py"
    spec = importlib.util.spec_from_file_location(
        "generated_site_backend_integration",
        integration_path,
    )
    assert spec is not None and spec.loader is not None
    generated: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generated)
    opened, auth = generated.open_site_services()
    assert opened.lifecycle.database_path == deployed_database.resolve()
    assert auth.site_id == "example-shop"
    with sqlite3.connect(deployed_database) as connection:
        assert connection.execute(
            "SELECT site_id FROM websitebench_site_binding"
        ).fetchone() == ("example-shop",)

    existing = root / "backend/runtime.json"
    before = existing.read_bytes()
    assert main(["backend", "scaffold", "--site", str(root)]) == 2
    assert existing.read_bytes() == before


def test_backend_scaffold_cleans_partial_vendor_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = initialized_site(tmp_path)

    def fail_auth_vendor(_: Path, **__: object) -> Path:
        raise RuntimeError("injected auth vendor failure")

    monkeypatch.setattr(
        backend_scaffold,
        "vendor_local_clone_auth",
        fail_auth_vendor,
    )
    with pytest.raises(RuntimeError, match="injected"):
        backend_scaffold.scaffold_site_backend(root)
    assert not (root / "backend/runtime.json").exists()
    assert not (root / "clone/websitebench/site_backend").exists()
    assert not (root / "clone/websitebench/local_clone_auth").exists()
    assert not (root / "clone/backend/site_backend_integration.py").exists()
