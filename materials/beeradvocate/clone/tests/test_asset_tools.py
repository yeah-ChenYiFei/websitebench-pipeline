from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest


SITE_ROOT = Path(__file__).resolve().parents[2]
WRITER_PATH = SITE_ROOT / "tools" / "write_asset_manifest.py"


def load_writer() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "beeradvocate_write_asset_manifest", WRITER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    canonical = ModuleType("websitebench.site_compiler.canonical")

    def sha256_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    canonical.sha256_file = sha256_file  # type: ignore[attr-defined]
    site_compiler = ModuleType("websitebench.site_compiler")
    with patch.dict(
        sys.modules,
        {
            "websitebench.site_compiler": site_compiler,
            "websitebench.site_compiler.canonical": canonical,
        },
    ):
        spec.loader.exec_module(module)
    return module


def write_report(site_root: Path, source_path: str) -> tuple[Path, bytes]:
    body = b"directly-observed-webp-response"
    digest = hashlib.sha256(body).hexdigest()
    report_path = site_root / "source-assets" / "snapshot" / "capture-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    source_file = site_root / source_path
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(body)
    report = {
        "captured_at": "2026-08-20T00:00:00+00:00",
        "closure_ready": True,
        "missing_required_paths": [],
        "failures": [],
        "assets": [
            {
                "id": f"beeradvocate.{digest[:16]}",
                "priority": "p0",
                "required": True,
                "source_path": source_path,
                "runtime_path": (
                    "clone/static/assets/brand/beeradvocate-nav-logo.png"
                ),
                "bytes": len(body),
                "sha256": digest,
                "mime_type": "image/webp",
                "dimensions": {"width": 1, "height": 1},
                "referenced_by": ["candidate:clone/app.py"],
                "evidence_kind": "current-direct",
                "source_url": "https://cdn.beeradvocate.com/logo.png",
                "source_url_variants": [
                    "https://cdn.beeradvocate.com/logo.png"
                ],
                "capture_id": "test",
            }
        ],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path, body


def test_manifest_writer_reconstructs_canonical_webp_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site"
    source_path = "source-assets/snapshot/brand/beeradvocate-nav-logo.png"
    report_path, body = write_report(site_root, source_path)
    writer = load_writer()
    manifest_path = site_root / "source-assets" / "manifest.json"
    monkeypatch.setattr(writer, "SITE_ROOT", site_root)
    monkeypatch.setattr(writer, "CAPTURE_REPORT", report_path)
    monkeypatch.setattr(writer, "MANIFEST", manifest_path)
    monkeypatch.setattr(writer, "ACTIVE_SUFFIXES", {"brand/beeradvocate-nav-logo.png"})
    monkeypatch.setattr(writer, "SCREENSHOT_DERIVED_ASSETS", ())

    assert writer.main() == 0
    runtime = site_root / "clone/static/assets/brand/beeradvocate-nav-logo.webp"
    assert runtime.read_bytes() == body
    manifest_bytes = manifest_path.read_bytes()
    assert b"\r\n" not in manifest_bytes
    assert manifest_bytes.endswith(b"\n")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["closure_status"] == "declared"
    assert manifest["assets"][0]["runtime_path"].endswith(".webp")


def test_manifest_writer_rejects_source_path_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site"
    report_path, _ = write_report(site_root, "../outside.webp")
    writer = load_writer()
    monkeypatch.setattr(writer, "SITE_ROOT", site_root)
    monkeypatch.setattr(writer, "CAPTURE_REPORT", report_path)
    monkeypatch.setattr(writer, "SCREENSHOT_DERIVED_ASSETS", ())
    monkeypatch.setattr(
        writer, "MANIFEST", site_root / "source-assets" / "manifest.json"
    )

    with pytest.raises(ValueError, match="source_path must be a site-relative path"):
        writer.main()


def test_manifest_writer_keeps_closure_pending_for_reported_required_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site"
    source_path = "source-assets/snapshot/brand/beeradvocate-nav-logo.png"
    report_path, _ = write_report(site_root, source_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["missing_required_paths"] = ["beers/required-but-missing.jpg"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    writer = load_writer()
    manifest_path = site_root / "source-assets" / "manifest.json"
    monkeypatch.setattr(writer, "SITE_ROOT", site_root)
    monkeypatch.setattr(writer, "CAPTURE_REPORT", report_path)
    monkeypatch.setattr(writer, "MANIFEST", manifest_path)
    monkeypatch.setattr(writer, "ACTIVE_SUFFIXES", {"brand/beeradvocate-nav-logo.png"})
    monkeypatch.setattr(writer, "SCREENSHOT_DERIVED_ASSETS", ())

    assert writer.main() == 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["closure_status"] == "pending"


def test_manifest_writer_detects_unreported_required_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site"
    source_path = "source-assets/snapshot/brand/beeradvocate-nav-logo.png"
    report_path, _ = write_report(site_root, source_path)
    writer = load_writer()
    manifest_path = site_root / "source-assets" / "manifest.json"
    monkeypatch.setattr(writer, "SITE_ROOT", site_root)
    monkeypatch.setattr(writer, "CAPTURE_REPORT", report_path)
    monkeypatch.setattr(writer, "MANIFEST", manifest_path)
    monkeypatch.setattr(
        writer,
        "ACTIVE_SUFFIXES",
        {"brand/beeradvocate-nav-logo.png", "beers/required-but-missing.jpg"},
    )
    monkeypatch.setattr(writer, "SCREENSHOT_DERIVED_ASSETS", ())

    assert writer.main() == 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["closure_status"] == "pending"
