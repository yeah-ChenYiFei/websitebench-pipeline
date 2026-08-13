from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from threading import Lock

from PIL import Image


def _module(repo_root: Path):
    path = Path(__file__).resolve().parents[2] / "scripts/fetch_assets.py"
    spec = importlib.util.spec_from_file_location("test_fetch_assets_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = repo_root
    return module


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 80)).save(stream, format="PNG")
    return stream.getvalue()


def test_parallel_fetch_imports_network_media_and_retries_throttling(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _module(tmp_path)
    payload = _png()
    counts: dict[str, int] = {}
    lock = Lock()

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.content = payload
            self.headers = {"retry-after": "0"}

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def get(self, url: str) -> Response:
            with lock:
                counts[url] = counts.get(url, 0) + 1
                attempt = counts[url]
            return Response(429 if "retry" in url and attempt == 1 else 200)

        def close(self) -> None:
            pass

    monkeypatch.setattr(module.httpx, "Client", Client)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    spec_path = tmp_path / "asset-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "site_id": "alpha",
                "capture_id": "alpha-capture",
                "capture_date": "2026-07-29",
                "entries": [
                    {
                        "url": "https://assets.example/retry.png",
                        "page": "home",
                        "priority": "p0",
                        "required": True,
                        "referenced_by": ["/"],
                        "evidence_kind": "current-direct",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    network_path = tmp_path / "network.json"
    network_path.write_text(
        json.dumps(
            [
                {
                    "url": "https://cdn.example/font.png",
                    "status": 200,
                    "resource_type": "image",
                },
                {
                    "url": "https://cdn.example/ignored.js",
                    "status": 200,
                    "resource_type": "script",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_assets.py",
            "--spec",
            str(spec_path),
            "--jobs",
            "4",
            "--per-origin-jobs",
            "2",
            "--import-network-log",
            str(network_path),
        ],
    )

    assert module.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert output["downloaded"] == 2
    assert output["jobs"] == 4
    assert output["per_origin_jobs"] == 2
    assert counts["https://assets.example/retry.png"] == 2
    assert "https://cdn.example/ignored.js" not in counts
    manifest = json.loads(
        (
            tmp_path / "materials/alpha/source-assets/manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert len(manifest["assets"]) == 2
    assert {item["source_url"] for item in manifest["assets"]} == {
        "https://assets.example/retry.png",
        "https://cdn.example/font.png",
    }
