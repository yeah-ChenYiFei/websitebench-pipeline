"""Offline audit: no served HTML/JS/CSS may reference a remote origin."""

import re
from pathlib import Path

CLONE_DIR = Path(__file__).resolve().parents[1]

# Same shape as the tripit audit: any absolute or protocol-relative URL whose
# host is not localhost is a remote reference. data:, /static/... and
# fragment-router hrefs (#/...) are inherently local and never match.
_REMOTE_RE = re.compile(
    r"(?ix)"
    r"(?:https?:)?//"
    r"(?!localhost\b|127\.0\.0\.1)"
    r"[a-z0-9.-]+\.[a-z]{2,}"
    r"[^\"'\s<>)]*"
)

# Frozen marketing pages keep human-readable URLs inside visible copy and
# schema-less attributes; the audit targets fetchable references only.
_FETCH_ATTR_RE = re.compile(
    r"(?i)\b(?:src|href|srcset|poster|data-src|data-srcset|action|content)\s*=\s*"
    r"([\"'])(.*?)\1"
)
_CSS_URL_RE = re.compile(r"(?i)url\(\s*([\"']?)([^\)\"']+)\1\s*\)")
_CSS_IMPORT_RE = re.compile(
    r"(?i)@import\s+(?!url\()[\"']([^\"']+)[\"']"
)


def _iter_served_files():
    for root in (CLONE_DIR / "frontend", CLONE_DIR / "static" / "site"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".html", ".js", ".css", ".json"}:
                continue
            # Build/provenance reports document the original remote URLs by
            # design and are never served by the app.
            if path.name.endswith("-report.json"):
                continue
            yield path


def _remote_refs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    found: list[str] = []
    if path.suffix == ".html":
        for match in _FETCH_ATTR_RE.finditer(text):
            value = match.group(2)
            if _REMOTE_RE.match(value.strip()):
                found.append(value[:120])
        for match in _CSS_URL_RE.finditer(text):
            value = match.group(2)
            if _REMOTE_RE.match(value.strip()):
                found.append(value[:120])
    elif path.suffix == ".css":
        for match in _CSS_URL_RE.finditer(text):
            value = match.group(2)
            if _REMOTE_RE.match(value.strip()):
                found.append(value[:120])
        for match in _CSS_IMPORT_RE.finditer(text):
            value = match.group(1)
            if _REMOTE_RE.match(value.strip()):
                found.append(value[:120])
    else:
        for match in _REMOTE_RE.finditer(text):
            found.append(match.group(0)[:120])
    return found


def test_no_served_file_references_a_remote_origin() -> None:
    offenders: dict[str, list[str]] = {}
    checked = 0
    for path in _iter_served_files():
        checked += 1
        refs = _remote_refs(path)
        if refs:
            offenders[str(path.relative_to(CLONE_DIR))] = refs[:5]
    assert checked > 0, "no served files found to audit"
    assert not offenders, f"remote references found: {offenders}"
