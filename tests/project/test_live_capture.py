from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts/live_capture.py"
    spec = importlib.util.spec_from_file_location("test_live_capture_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chrome_mcp_provider_run_import_uses_common_capture_contract(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _module()
    output_root = tmp_path / "source-current"
    plan = tmp_path / "capture-plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema_version": "clawbench.live-capture-plan.v1",
                "site_id": "alpha",
                "output_root": str(output_root),
                "viewports": [{"width": 390, "height": 844}],
                "pages": [
                    {"id": "home", "url": "https://example.com/"}
                ],
            }
        ),
        encoding="utf-8",
    )
    provider_run = tmp_path / "chrome-mcp-run.json"
    provider_run.write_text(
        json.dumps(
            {
                "schema_version": "clawbench.live-capture-run.v2",
                "site_id": "alpha",
                "pages": [
                    {
                        "id": "home",
                        "status": "captured",
                        "artifacts": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "live_capture.py",
            "--plan",
            str(plan),
            "--provider",
            "chrome-mcp",
            "--import-provider-run",
            str(provider_run),
        ],
    )

    assert module.main() == 0
    output = json.loads(capsys.readouterr().out)
    imported = json.loads(
        (output_root / "capture-run.json").read_text(encoding="utf-8")
    )

    assert output["provider"] == "chrome-mcp"
    assert imported["provider"] == "chrome-mcp"
    assert imported["methods"] == ["GET"]
    assert imported["mutations_performed"] is False
