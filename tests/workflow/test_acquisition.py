from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from websitebench.site_compiler.canonical import canonical_json_bytes
from websitebench.workflow.acquisition import acquire_source
from websitebench.workflow.errors import WorkflowError
from websitebench.workflow.fullstack import validate_source_acquisition_report


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00"
    b"\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


class _SourceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            payload = (
                b"<!doctype html><html><head><title>Alpha source</title>"
                b'<link rel="stylesheet" href="/style.css"></head>'
                b'<body><h1>Alpha</h1><img src="/pixel.png"></body></html>'
            )
            content_type = "text/html; charset=utf-8"
            status = 200
        elif self.path == "/style.css":
            payload = b"body{color:#123;background-image:url('/pixel.png')}\n"
            content_type = "text/css; charset=utf-8"
            status = 200
        elif self.path == "/pixel.png":
            payload = PNG
            content_type = "image/png"
            status = 200
        else:
            payload = b"not found\n"
            content_type = "text/plain; charset=utf-8"
            status = 404
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture
def source_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SourceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _write_spec(root: Path, origin: str, *, page_url: str | None = None) -> Path:
    spec = {
        "schema_version": "offline-clone.source-acquisition-spec.v2",
        "site_id": "alpha",
        "capture_id": "alpha.capture.1",
        "allowed_origins": [origin],
        "pages": [
            {
                "row_id": "home.loaded.desktop",
                "priority": "p0",
                "url": page_url or f"{origin}/",
                "viewport": {"name": "desktop", "width": 800, "height": 600},
                "wait_until": "load",
                "full_page": True,
            }
        ],
        "limits": {
            "navigation_timeout_ms": 10000,
            "settle_ms": 0,
            "max_resource_bytes": 1048576,
            "max_total_resource_bytes": 4194304,
        },
    }
    path = root / "materials/alpha/scope/source-acquisition-spec.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(canonical_json_bytes(spec))
    return path


def test_acquire_source_captures_and_validates_v3_report(
    tmp_path: Path,
    source_server: str,
) -> None:
    spec = _write_spec(tmp_path, source_server)
    output = Path("materials/alpha/source-current/alpha-capture-1")
    report = Path(
        "materials/alpha/artifacts/offline-clone/frontend/"
        "source-acquisition-report-v3.json"
    )

    result = acquire_source(
        tmp_path,
        spec.relative_to(tmp_path),
        output,
        report,
        browser_channel="",
    )

    assert result["status"] == "complete"
    report_path = tmp_path / report
    value = json.loads(report_path.read_text(encoding="utf-8"))
    assert value["source_scope"] == {
        "path": spec.relative_to(tmp_path).as_posix(),
        "bytes": spec.stat().st_size,
    }
    assert "report_sha256" not in result
    assert all(
        "sha256" not in artifact
        for artifact in value["pages"][0]["artifacts"]
    )
    assert value["pages"][0]["status"] == "captured"
    assert value["resources"]["logical_required"] == 2
    assert value["resources"]["downloaded"] == 2
    assert value["closure"]["unresolved_css_reference_count"] == 0
    assert {item["kind"] for item in value["pages"][0]["artifacts"]} == {
        "computed-style",
        "dom",
        "geometry",
        "network",
        "resource-inventory",
        "screenshot",
        "visible-text",
    }
    validated = validate_source_acquisition_report(tmp_path, report)
    assert validated["status"] == "passed"
    assert validated["active"] is True
    assert "authority" not in validated


def test_acquisition_refuses_page_outside_configured_origins(
    tmp_path: Path,
    source_server: str,
) -> None:
    spec = _write_spec(
        tmp_path,
        source_server,
        page_url="https://example.invalid/",
    )

    with pytest.raises(WorkflowError, match="outside allowed_origins"):
        acquire_source(
            tmp_path,
            spec.relative_to(tmp_path),
            Path("materials/alpha/source-current/rejected"),
            Path("materials/alpha/artifacts/rejected.json"),
        )


def test_acquisition_refuses_to_overwrite_evidence(
    tmp_path: Path,
    source_server: str,
) -> None:
    spec = _write_spec(tmp_path, source_server)
    output = tmp_path / "materials/alpha/source-current/existing"
    output.mkdir(parents=True)

    with pytest.raises(WorkflowError, match="output already exists"):
        acquire_source(
            tmp_path,
            spec.relative_to(tmp_path),
            output.relative_to(tmp_path),
            Path("materials/alpha/artifacts/rejected.json"),
        )
