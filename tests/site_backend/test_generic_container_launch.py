from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from websitebench.site_backend import SiteBindingError

from .helpers import runtime_config


ROOT = Path(__file__).resolve().parents[2]
LAUNCH_PATH = ROOT / "deploy/generic-offline-clone/runtime/launch.py"


def _launch_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "websitebench_generic_container_launch",
        LAUNCH_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deployment(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "websitebench.generic-public-clone-deployment.v2"
                ),
                "runtime": {"command": ["python", "-m", "example"]},
            }
        ),
        encoding="utf-8",
    )


def test_v2_container_preflight_binds_runtime_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = _launch_module()
    monkeypatch.delenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", raising=False)
    deployment = tmp_path / "deployment.json"
    runtime_path = tmp_path / "backend-runtime.json"
    data_root = tmp_path / "data"
    _deployment(deployment)
    runtime_path.write_text(json.dumps(runtime_config("alpha")), encoding="utf-8")

    result = launch.preflight_backend(deployment, runtime_path, data_root)

    assert result is not None and result["status"] == "ok"
    database = data_root / "alpha.sqlite3"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT site_id FROM websitebench_site_binding"
        ).fetchone() == ("alpha",)
    assert launch.os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] == str(database)


def test_v2_container_preflight_imports_declared_hooks_from_clone_root(
    tmp_path: Path,
) -> None:
    launch = _launch_module()
    deployment = tmp_path / "deployment.json"
    runtime_path = tmp_path / "backend-runtime.json"
    data_root = tmp_path / "data"
    clone_root = tmp_path / "clone"
    clone_root.mkdir()
    (clone_root / "site_hooks.py").write_text(
        "def migrate(connection):\n"
        "    connection.execute("
        "\"CREATE TABLE site_hook_probe(value TEXT NOT NULL)\""
        ")\n"
        "\n"
        "def seed(connection):\n"
        "    connection.execute("
        "\"INSERT INTO site_hook_probe(value) VALUES ('seeded')\""
        ")\n",
        encoding="utf-8",
    )
    _deployment(deployment)
    runtime = runtime_config("alpha")
    runtime["database"]["migration_hook"] = "site_hooks:migrate"
    runtime["database"]["seed_hook"] = "site_hooks:seed"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")

    result = launch.preflight_backend(
        deployment,
        runtime_path,
        data_root,
        hook_import_root=clone_root,
    )

    assert result is not None and result["status"] == "ok"
    with sqlite3.connect(data_root / "alpha.sqlite3") as connection:
        assert connection.execute(
            "SELECT value FROM site_hook_probe"
        ).fetchall() == [("seeded",)]


def test_cloudflare_review_rebuild_uses_fresh_filesystem_and_reseeds(
    tmp_path: Path,
) -> None:
    launch = _launch_module()
    deployment = tmp_path / "deployment.json"
    runtime_path = tmp_path / "backend-runtime.json"
    clone_root = tmp_path / "clone"
    clone_root.mkdir()
    (clone_root / "site_hooks.py").write_text(
        "def migrate(connection):\n"
        "    connection.execute("
        "\"CREATE TABLE rebuild_probe(value TEXT PRIMARY KEY)\""
        ")\n"
        "\n"
        "def seed(connection):\n"
        "    connection.execute("
        "\"INSERT INTO rebuild_probe(value) VALUES ('seeded')\""
        ")\n",
        encoding="utf-8",
    )
    _deployment(deployment)
    runtime = runtime_config("alpha")
    runtime["database"]["migration_hook"] = "site_hooks:migrate"
    runtime["database"]["seed_hook"] = "site_hooks:seed"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    assert (
        runtime["deployment"]["profiles"]["cloudflare-review"]["persistence"]
        == "ephemeral-reset"
    )

    first_root = tmp_path / "first-container-filesystem"
    launch.preflight_backend(
        deployment,
        runtime_path,
        first_root,
        hook_import_root=clone_root,
    )
    with sqlite3.connect(first_root / "alpha.sqlite3") as connection:
        connection.execute(
            "INSERT INTO rebuild_probe(value) VALUES ('runtime-mutation')"
        )

    second_root = tmp_path / "replacement-container-filesystem"
    result = launch.preflight_backend(
        deployment,
        runtime_path,
        second_root,
        hook_import_root=clone_root,
    )

    assert result is not None and result["status"] == "ok"
    with sqlite3.connect(second_root / "alpha.sqlite3") as connection:
        assert connection.execute(
            "SELECT value FROM rebuild_probe ORDER BY value"
        ).fetchall() == [("seeded",)]
        assert connection.execute(
            "SELECT site_id FROM websitebench_site_binding"
        ).fetchone() == ("alpha",)
    with sqlite3.connect(first_root / "alpha.sqlite3") as connection:
        assert connection.execute(
            "SELECT value FROM rebuild_probe ORDER BY value"
        ).fetchall() == [("runtime-mutation",), ("seeded",)]


def test_v2_container_preflight_rejects_foreign_site_volume(
    tmp_path: Path,
) -> None:
    launch = _launch_module()
    deployment = tmp_path / "deployment.json"
    runtime_path = tmp_path / "backend-runtime.json"
    data_root = tmp_path / "data"
    _deployment(deployment)
    runtime_path.write_text(json.dumps(runtime_config("alpha")), encoding="utf-8")
    launch.preflight_backend(deployment, runtime_path, data_root)

    foreign = runtime_config("beta", "Beta")
    foreign["database"]["filename"] = "alpha.sqlite3"
    runtime_path.write_text(json.dumps(foreign), encoding="utf-8")
    with pytest.raises(SiteBindingError, match="belongs to site"):
        launch.preflight_backend(deployment, runtime_path, data_root)


def test_v2_container_preflight_never_authorizes_legacy_adoption(
    tmp_path: Path,
) -> None:
    launch = _launch_module()
    deployment = tmp_path / "deployment.json"
    runtime_path = tmp_path / "backend-runtime.json"
    data_root = tmp_path / "data"
    data_root.mkdir()
    _deployment(deployment)
    legacy_runtime = runtime_config(
        "alpha",
        legacy_unbound_migration=True,
    )
    runtime_path.write_text(json.dumps(legacy_runtime), encoding="utf-8")
    with sqlite3.connect(data_root / "alpha.sqlite3") as connection:
        connection.execute("CREATE TABLE arbitrary_data(value TEXT)")

    with pytest.raises(
        SiteBindingError,
        match="explicit migration authorization",
    ):
        launch.preflight_backend(deployment, runtime_path, data_root)

    with sqlite3.connect(data_root / "alpha.sqlite3") as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='websitebench_site_binding'"
        ).fetchone() is None


def test_amazon_descriptor_and_preflight_select_the_same_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = _launch_module()
    deployment_path = (
        ROOT / "deploy/generic-offline-clone/deployment.amazon.v2.json"
    )
    runtime_path = ROOT / "materials/amazon/backend/runtime.json"
    data_root = tmp_path / "container-data"
    monkeypatch.delenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", raising=False)

    launch.preflight_backend(deployment_path, runtime_path, data_root)

    deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    command = deployment["runtime"]["command"]
    command_database = Path(command[command.index("--db") + 1])
    # Amazon's descriptor and canonical WebsiteBench preflight must bind the
    # same container-owned database selected by the application command.
    preflight_database = Path(
        launch.os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"]
    )
    assert command_database.as_posix() == "/data/amazon.sqlite3"
    assert preflight_database == data_root / command_database.name
    assert preflight_database.is_file()
