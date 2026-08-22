"""Runtime network closure: the clone serves only same-origin resources.

Every served HTML/CSS/JS/SVG file must contain no remote-origin references,
and the pages must render without any outbound runtime request (CSP + no
third-party URLs in markup).
"""

from __future__ import annotations

import re
from pathlib import Path

CLONE_DIR = Path(__file__).resolve().parents[1]

REMOTE_RE = re.compile(
    r"(?i)\b(?:https?:)?//(?!127\.0\.0\.1|localhost|testserver|/|'|\.)"
)
URL_ATTR_RE = re.compile(
    r"""(?:src|href|action|poster|srcset|data-src)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


def _text_files(root: Path, suffixes: set[str]) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix in suffixes]


def test_no_remote_http_references_in_markup() -> None:
    files = _text_files(CLONE_DIR / "frontend", {".html", ".j2"}) + _text_files(
        CLONE_DIR / "static", {".css", ".js", ".svg"}
    )
    assert files
    offenders: list[tuple[Path, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in REMOTE_RE.finditer(text):
            context = text[max(0, match.start() - 40) : match.end() + 40]
            if "http://www.w3.org" in context or "xmlns" in context:
                continue
            offenders.append((path, context.replace("\n", " ")[:120]))
    assert not offenders, offenders[:5]


def test_all_markup_urls_are_same_origin() -> None:
    files = _text_files(CLONE_DIR / "frontend", {".html"})
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in URL_ATTR_RE.finditer(text):
            url = match.group(1)
            if url.startswith(("http://", "https://", "//")):
                assert not url.startswith("//"), f"{path}: remote url {url}"
                assert "testserver" in url or "127.0.0.1" in url, f"{path}: {url}"


def test_no_source_maps_or_bundle_references() -> None:
    for path in _text_files(CLONE_DIR / "static", {".js", ".css"}):
        text = path.read_text(encoding="utf-8")
        assert "sourceMappingURL" not in text
        assert "webpack" not in text.lower()


def test_csp_policy_is_same_origin() -> None:
    app_source = (CLONE_DIR / "app.py").read_text(encoding="utf-8")
    assert "default-src 'self'" in app_source
    assert "frame-ancestors 'none'" in app_source


def test_no_credentials_or_secrets_in_served_files() -> None:
    for root in ("frontend", "static"):
        for path in _text_files(CLONE_DIR / root, {".html", ".css", ".js", ".svg"}):
            text = path.read_text(encoding="utf-8", errors="replace")
            for secret_marker in ("password=", "api_key=", "secret=", "Authorization:"):
                assert secret_marker not in text.lower(), f"{path}: {secret_marker}"
