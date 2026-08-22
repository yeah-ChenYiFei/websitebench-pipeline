from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from websitebench.offline_clone.frontend_spec import (
    FRONTEND_SPEC_SCHEMA,
    extract_frontend_spec,
)
from websitebench.offline_clone.toolbox import ToolboxError

_SAMPLE_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sample Shop Catalog</title>
  <link rel="stylesheet" href="/assets/site.css" media="all">
  <script src="/assets/app.js"></script>
</head>
<body>
  <header aria-label="Site header"><a href="/">Home</a><a href="/catalog?sort=title-asc&utm=drop">Catalog</a></header>
  <nav aria-label="Primary"><a href="/catalog">Browse</a><button type="button" data-testid="filter-open">Filters</button></nav>
  <main>
    <h1>Example Catalog</h1>
    <h2>Featured</h2>
    <article data-product-id="p-1">
      <h3>Basic Course</h3>
      <p>CNY 196/month · 4.8 rating · 12,000 learners</p>
      <a href="/catalog/p-1">View details</a>
    </article>
    <form action="/search" method="get">
      <input type="search" name="q" placeholder="Search courses">
      <select name="level"><option>Beginner</option><option>Intermediate</option></select>
      <button type="submit">Search</button>
    </form>
  </main>
  <footer aria-label="Site footer"><a href="/help">Help</a></footer>
</body>
</html>
"""


class _PageHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path.startswith("/assets/"):
            body = b"body{}"
            self.send_response(200)
            self.send_header("Content-Type", "text/css")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = _SAMPLE_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # pragma: no cover - source exploration is GET-only
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _serve() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PageHandler)
    return server, f"http://127.0.0.1:{server.server_port}"


def test_frontend_spec_extracts_structure_controls_forms_and_styles(
    tmp_path: Path,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    del playwright
    server, base_url = _serve()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / "frontend.json"
        result = extract_frontend_spec(
            target_url=base_url + "/",
            allowed_origins=[base_url],
            viewport=(1692, 979),
            environment="source",
            output_path=output,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result["schema_version"] == FRONTEND_SPEC_SCHEMA
    assert result["environment"] == "source"
    assert result["document"]["title"] == "Sample Shop Catalog"
    assert result["document"]["lang"] == "en"
    heading_texts = {item["text"] for item in result["document"]["headings"]}
    assert {"Example Catalog", "Featured", "Basic Course"} <= heading_texts
    region_kinds = {item["kind"] for item in result["document"]["regions"]}
    assert {"header", "nav", "main", "footer"} <= region_kinds

    controls = result["controls"]
    links = {item["text"] for item in controls if item["kind"] == "a"}
    assert {"Home", "Catalog", "Browse", "View details", "Help"} <= links
    # Query allowlist keeps sort but drops utm.
    catalog_link = next(
        item for item in controls if "sort=title-asc" in item["href"]
    )
    assert catalog_link["href"].endswith("/catalog?sort=title-asc")
    assert "utm" not in catalog_link["href"]

    forms = [item for item in controls if item["kind"] == "form"]
    assert len(forms) == 1
    assert forms[0]["action"].endswith("/search")
    assert forms[0]["method"] == "get"
    field = next(
        item for item in controls if item["kind"] == "input" and item["name"] == "q"
    )
    assert field["placeholder"] == "Search courses"
    select = next(item for item in controls if item["kind"] == "select")
    assert select["options"] == ["Beginner", "Intermediate"]

    kinds = {item["kind"] for item in result["data_points"]}
    assert "price" in kinds and "rating" in kinds and "count" in kinds
    assert any(item["text"] == "CNY 196" for item in result["data_points"])

    styles = result["styles"]
    assert any(item["href"].endswith("/assets/site.css") for item in styles)
    assert any(item.endswith("/assets/app.js") for item in result["scripts"])

    # No sensitive values are ever collected.
    assert not json.dumps(result).__contains__('name="q" value="')
    assert output.is_file()


def test_frontend_spec_rejects_unapproved_origin(tmp_path: Path) -> None:
    with pytest.raises(ToolboxError, match="origin is absent"):
        extract_frontend_spec(
            target_url="https://example.test/",
            allowed_origins=["https://other.test"],
            viewport=(1280, 720),
            environment="source",
            output_path=tmp_path / "out.json",
        )


def test_frontend_spec_refuses_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "existing.json"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(ToolboxError, match="refusing to overwrite"):
        extract_frontend_spec(
            target_url="https://example.test/",
            allowed_origins=["https://example.test"],
            viewport=(1280, 720),
            environment="source",
            output_path=output,
        )
