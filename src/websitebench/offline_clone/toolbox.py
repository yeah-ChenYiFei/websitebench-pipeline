"""Shared discovery and safety helpers for offline-clone diagnostic tools."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class ToolboxError(ValueError):
    """Raised when a shared offline-clone tool contract is invalid."""


_EMAIL = re.compile(
    r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|cookie|authorization|otp|cvv|cvc)"
    r"\b\s*[:=]\s*[^\s,;]+"
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


TOOL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "browser-explore",
        "command": "websitebench-offline-clone tools explore",
        "repository_command": (
            "python tools/offline_clone/run.py tools explore"
        ),
        "purpose": (
            "Run a declarative Playwright interaction scenario against one approved "
            "source or offline-clone target and retain sanitized observations."
        ),
        "input_schema_versions": [
            "websitebench.offline-clone.browser-scenario.v1"
        ],
        "output_schema_version": (
            "websitebench.offline-clone.browser-exploration.v1"
        ),
        "safety": [
            "approved origins only",
            "source mutations blocked by default",
            "storage state is consumed but never copied",
            "input values are omitted from reports",
        ],
    },
    {
        "id": "functional-compare",
        "command": "websitebench-offline-clone tools compare-functional",
        "repository_command": (
            "python tools/offline_clone/run.py tools compare-functional"
        ),
        "purpose": (
            "Compare two browser exploration reports by stable step and observation "
            "identity, including action, route, visible state, and error behavior."
        ),
        "input_schema_versions": [
            "websitebench.offline-clone.browser-exploration.v1"
        ],
        "output_schema_version": (
            "websitebench.offline-clone.functional-comparison.v1"
        ),
        "safety": ["sanitized reports only", "diagnostic authority only"],
    },
    {
        "id": "visual-compare",
        "command": "websitebench-offline-clone tools compare-visual",
        "repository_command": (
            "python tools/offline_clone/run.py tools compare-visual"
        ),
        "purpose": (
            "Compare source and candidate screenshot regions and create lossless "
            "diagnostic heatmaps."
        ),
        "input_schema_versions": [
            "websitebench.offline-clone.visual-comparison-spec.v1"
        ],
        "output_schema_version": (
            "websitebench.offline-clone.visual-comparison.v1"
        ),
        "safety": [
            "non-zero configured thresholds required",
            "region-level verdicts",
            "diagnostic authority only",
        ],
    },
    {
        "id": "backend-semantic-test",
        "command": "websitebench-offline-clone tools test-backend",
        "repository_command": (
            "python tools/offline_clone/run.py tools test-backend"
        ),
        "purpose": (
            "Run actor-isolated black-box HTTP semantic cases with JSON-pointer "
            "assertions, in-memory captures, and positive/negative invariant coverage."
        ),
        "input_schema_versions": [
            "websitebench.offline-clone.backend-semantic-suite.v1"
        ],
        "output_schema_version": (
            "websitebench.offline-clone.backend-semantic-report.v1"
        ),
        "safety": [
            "loopback targets only by default",
            "no arbitrary command execution",
            "secrets may be injected from environment only",
            "request and response bodies are never retained",
        ],
    },
    {
        "id": "frontend-spec-extract",
        "command": "websitebench-offline-clone tools frontend-spec",
        "repository_command": (
            "python tools/offline_clone/run.py tools frontend-spec"
        ),
        "purpose": (
            "Extract a sanitized frontend specification from one approved-origin "
            "page: document structure, headings, semantic regions, interactive "
            "controls, forms, data points, and style/script references that clone "
            "implementations and backend contracts can share."
        ),
        "input_schema_versions": [],
        "output_schema_version": (
            "websitebench.offline-clone.frontend-spec.v1"
        ),
        "safety": [
            "approved origins only",
            "source exploration is GET-only",
            "storage state is never retained",
            "input values and cookies are never collected",
            "URLs are sanitized to path plus allowlisted query parameters",
        ],
    },
    {
        "id": "visual-diff-diagnose",
        "command": "websitebench-offline-clone tools visual-diff",
        "repository_command": (
            "python tools/offline_clone/run.py tools visual-diff"
        ),
        "purpose": (
            "Locate and classify difference regions between a source raster and "
            "a candidate raster (bbox, intensity, kind) with heatmap and "
            "overlay outputs, so visual similarity work targets exact areas."
        ),
        "input_schema_versions": [],
        "output_schema_version": (
            "websitebench.offline-clone.visual-diff.v1"
        ),
        "safety": [
            "raster comparison only",
            "diagnostic authority only",
        ],
    },
)


def tool_catalog() -> dict[str, Any]:
    """Return the machine-readable shared tool catalog."""

    return {
        "schema_version": "websitebench.offline-clone.tool-catalog.v1",
        "authority": "diagnostic-only",
        "tools": [dict(item) for item in TOOL_CATALOG],
    }


def load_json_object(
    path: Path, *, schema_version: str | None = None
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolboxError(f"{path}: cannot read JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ToolboxError(f"{path}: expected a JSON object")
    if schema_version is not None and value.get("schema_version") != schema_version:
        raise ToolboxError(
            f"{path}: expected schema_version {schema_version!r}, "
            f"got {value.get('schema_version')!r}"
        )
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def safe_text(value: Any, *, limit: int = 1000) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True
    )
    text = _EMAIL.sub("[REDACTED:email]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", text)
    text = _CARD.sub("[REDACTED:payment]", text)
    return text[:limit]


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return safe_text(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolboxError(f"expected an absolute HTTP(S) URL, got {value!r}")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def safe_component(value: Any, *, field: str) -> str:
    text = str(value or "")
    if not text or not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        raise ToolboxError(
            f"{field} must use only letters, digits, dot, dash, underscore"
        )
    return text


def resolve_relative(path_value: str, *, anchor: Path) -> Path:
    path = Path(path_value)
    return path.resolve() if path.is_absolute() else (anchor / path).resolve()
