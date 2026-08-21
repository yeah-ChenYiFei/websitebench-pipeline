from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from websitebench.offline_clone.cli import build_parser
from websitebench.offline_clone.comparison_tools import (
    compare_functional_reports,
    compare_visual_spec,
)
from websitebench.offline_clone.semantic_tools import run_backend_semantic_suite
from websitebench.offline_clone.toolbox import tool_catalog


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _browser_report(*, environment: str, text: str) -> dict:
    return {
        "schema_version": "websitebench.offline-clone.browser-exploration.v1",
        "scenario_id": "search-mainline",
        "environment": environment,
        "steps": [
            {
                "id": "result",
                "action": "snapshot",
                "route": "/search",
                "outcome": "passed",
                "observations": [
                    {
                        "id": "heading",
                        "kind": "text",
                        "actual": text,
                        "passed": True,
                    }
                ],
            }
        ],
        "summary": {
            "console_error_count": 0,
            "failed_request_count": 0,
            "blocked_request_count": 0,
        },
    }


def test_tool_catalog_and_cli_are_discoverable() -> None:
    catalog = tool_catalog()
    assert catalog["schema_version"] == "websitebench.offline-clone.tool-catalog.v1"
    assert {item["id"] for item in catalog["tools"]} == {
        "browser-explore",
        "functional-compare",
        "visual-compare",
        "backend-semantic-test",
        "frontend-spec-extract",
    }
    args = build_parser().parse_args(["tools", "list"])
    assert args.tool_command == "list"
    args = build_parser().parse_args(
        [
            "tools",
            "frontend-spec",
            "--url",
            "https://example.test/",
            "--allowed-origin",
            "https://example.test",
            "--out",
            "spec.json",
        ]
    )
    assert args.tool_command == "frontend-spec"
    assert args.viewport == "1692,979"


def test_functional_compare_reports_observable_difference(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "functional.json"
    _write_json(source, _browser_report(environment="source", text="Three results"))
    _write_json(candidate, _browser_report(environment="clone", text="No results"))

    result = compare_functional_reports(
        source_path=source,
        candidate_path=candidate,
        output_path=output,
    )

    assert result["status"] == "failed"
    assert result["counts"]["differences"] == 1
    assert result["differences"][0]["category"] == "observable-state"
    assert output.is_file()


def test_visual_compare_reads_current_rasters_without_hashes(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (32, 32), (255, 255, 255)).save(source)
    Image.new("RGB", (32, 32), (255, 255, 255)).save(candidate)
    spec = tmp_path / "visual-spec.json"
    _write_json(
        spec,
        {
            "schema_version": "websitebench.offline-clone.visual-comparison-spec.v1",
            "checkpoints": [
                {
                    "id": "home-desktop",
                    "source": {"path": source.name},
                    "candidate": {"path": candidate.name},
                    "viewport": {"width": 32, "height": 32},
                    "capture_mode": "viewport",
                    "regions": [
                        {
                            "id": "primary",
                            "box": "full",
                            "metric": "ssim",
                            "threshold": 0.99,
                        }
                    ],
                }
            ],
        },
    )

    result = compare_visual_spec(
        spec_path=spec,
        output_path=tmp_path / "visual.json",
        heatmap_dir=tmp_path / "heatmaps",
    )

    assert result["status"] == "passed"
    assert result["counts"] == {
        "checkpoints_total": 1,
        "checkpoints_passed": 1,
        "regions_total": 1,
        "regions_passed": 1,
    }
    assert result["checkpoints"][0]["regions"][0]["score"] == 1.0
    assert "sha256" not in result["checkpoints"][0]["source"]


class _SemanticHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: dict, *, cookie: str | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/items":
            self._json(404, {"error": "not-found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if set(payload) != {"name"}:
            self._json(400, {"error": "invalid-fields"})
            return
        self._json(
            201,
            {"id": "opaque-1", "state": "created"},
            cookie="owner=owner-a; Path=/; HttpOnly",
        )

    def do_GET(self) -> None:
        if self.path == "/items/opaque-1" and "owner=owner-a" in self.headers.get(
            "Cookie", ""
        ):
            self._json(200, {"id": "opaque-1", "state": "created"})
            return
        self._json(404, {"error": "not-found"})


def test_backend_semantic_runner_covers_positive_and_negative_actor_cases(
    tmp_path: Path,
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SemanticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        spec = tmp_path / "backend.json"
        _write_json(
            spec,
            {
                "schema_version": (
                    "websitebench.offline-clone.backend-semantic-suite.v1"
                ),
                "suite_id": "ownership",
                "allowed_origin": base_url,
                "invariants": [
                    {
                        "id": "AUTHY-002",
                        "applicability": "applicable",
                        "required_polarities": ["positive", "negative"],
                    }
                ],
                "cases": [
                    {
                        "id": "owner-can-read",
                        "invariant_id": "AUTHY-002",
                        "polarity": "positive",
                        "actor": "owner",
                        "steps": [
                            {
                                "id": "create",
                                "request": {
                                    "method": "POST",
                                    "path": "/items",
                                    "json": {"name": "fixture"},
                                },
                                "expect": {
                                    "status": 201,
                                    "json_equal": {"/state": "created"},
                                },
                                "capture": {"item_id": "/id"},
                            },
                            {
                                "id": "read",
                                "request": {
                                    "method": "GET",
                                    "path": "/items/${VAR:item_id}",
                                },
                                "expect": {
                                    "status": 200,
                                    "json_equal": {
                                        "/id": "${VAR:item_id}",
                                        "/state": "created",
                                    },
                                },
                            },
                        ],
                    },
                    {
                        "id": "foreign-owner-denied",
                        "invariant_id": "AUTHY-002",
                        "polarity": "negative",
                        "actor": "foreign",
                        "steps": [
                            {
                                "id": "read",
                                "request": {
                                    "method": "GET",
                                    "path": "/items/${VAR:item_id}",
                                },
                                "expect": {
                                    "status": 404,
                                    "json_absent": ["/owner"],
                                },
                            }
                        ],
                    },
                ],
            },
        )

        result = run_backend_semantic_suite(
            spec_path=spec,
            base_url=base_url,
            output_path=tmp_path / "backend-report.json",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["status"] == "passed"
    assert result["counts"]["cases_passed"] == 2
    assert result["invariant_coverage"][0]["verified_polarities"] == [
        "negative",
        "positive",
    ]
    assert result["retention"] == {
        "request_bodies": False,
        "response_bodies": False,
        "captured_values": False,
        "environment_values": False,
    }
