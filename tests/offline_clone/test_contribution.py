from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from websitebench.offline_clone.cli import main
from websitebench.site_backend import load_runtime


def _init(repo: Path, *, profile: str) -> int:
    return main(
        [
            "contribution",
            "init",
            "--repo",
            str(repo),
            "--site-id",
            "sample-shop",
            "--display-name",
            "Sample Shop",
            "--source-url",
            "https://example.test/",
            "--backend-profile",
            profile,
        ]
    )


def test_contribution_none_is_explicit_non_deployable_and_non_overwriting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _init(tmp_path, profile="none") == 0
    capsys.readouterr()
    site = tmp_path / "materials" / "sample-shop"
    capability_scope = json.loads(
        (site / "scope" / "backend-capabilities.json").read_text("utf-8")
    )
    assert capability_scope["backend_profile"] == "none"
    assert {row["applicability"] for row in capability_scope["capabilities"]} == {
        "not-applicable"
    }
    assert not (site / "backend" / "runtime.json").exists()
    assert not (tmp_path / "harbor").exists()
    assert not list((tmp_path / ".github" / "workflows").glob("deploy-*-public.yml"))

    app_before = (site / "clone" / "app.py").read_bytes()
    assert _init(tmp_path, profile="none") == 2
    capsys.readouterr()
    assert (site / "clone" / "app.py").read_bytes() == app_before


def test_contribution_full_uses_unique_shared_backend_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _init(tmp_path, profile="full") == 0
    capsys.readouterr()
    runtime = load_runtime(tmp_path / "materials/sample-shop/backend/runtime.json")
    assert runtime.site_id == "sample-shop"
    assert runtime.database_filename == "sample-shop.sqlite3"
    assert sorted(runtime.mail["purposes"]) == ["password-reset", "registration"]
    assert runtime.payments["default_adapter"] == "local-sandbox"
    assert runtime.raw["schema_version"] == "websitebench.site-backend-runtime.v1"

    report = tmp_path / "full-report.json"
    bundle = tmp_path / "full-handoff.zip"
    assert (
        main(
            [
                "contribution",
                "report",
                "--site",
                str(tmp_path / "materials/sample-shop"),
                "--out",
                str(report),
                "--bundle-out",
                str(bundle),
            ]
        )
        == 0
    )
    capsys.readouterr()
    summary = json.loads(report.read_text("utf-8"))
    assert summary["diagnostic"]["diagnostic_status"] == "clean"
    assert summary["backend"] == {
        "database_identity": {
            "data_dir": "data",
            "filename": "sample-shop.sqlite3",
        },
        "deployment_profiles": [
            "cloudflare-review",
            "docker-volume",
            "offline-harbor",
        ],
        "mail_purposes": ["password-reset", "registration"],
        "payment_profile": "local-sandbox",
        "runtime": "backend/runtime.json",
        "site_id": "sample-shop",
        "volume_identity": "websitebench-sample-shop-data",
    }
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
    assert "backend/runtime.json" in names
    assert "clone/tests/test_smoke.py" in names
    assert "diagnostics/diagnostic-report.json" in names


def test_contribution_report_lists_files_and_excludes_runtime_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _init(tmp_path, profile="none") == 0
    capsys.readouterr()
    site = tmp_path / "materials" / "sample-shop"
    (site / "data").mkdir()
    (site / "data" / "sample-shop.sqlite3").write_bytes(b"must-not-ship")
    (site / "clone" / ".env").write_text("API_TOKEN=must-not-ship", encoding="utf-8")
    report = tmp_path / "report.json"
    bundle = tmp_path / "handoff.zip"

    assert (
        main(
            [
                "contribution",
                "report",
                "--site",
                str(site),
                "--out",
                str(report),
                "--bundle-out",
                str(bundle),
            ]
        )
        == 0
    )
    capsys.readouterr()
    summary = json.loads(report.read_text("utf-8"))
    assert summary["authority"] == "diagnostic-only"
    assert summary["qualification"] == "maintainer-judgment-required"
    assert summary["backend"]["runtime"] is None
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert names[:-1] == sorted(names[:-1])
        assert names[-1] == "BUNDLE-MANIFEST.json"
        assert not any(".env" in name or name.endswith(".sqlite3") for name in names)
        manifest = json.loads(archive.read("BUNDLE-MANIFEST.json"))
        assert all(set(row) == {"path", "bytes"} for row in manifest["files"])
        assert {row["path"] for row in manifest["files"]} == set(names[:-1])
