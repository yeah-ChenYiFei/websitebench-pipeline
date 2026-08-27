#!/usr/bin/env python3
"""Sanitize volatile browser runtime data from committed Crunchyroll evidence.

The source collector intentionally stores enough DOM and network metadata for
reproducibility. Cloudflare challenge pages embed one-shot identifiers that are
not useful evidence and must not enter Git. This script removes executable
script bodies, strips URL queries/fragments, redacts challenge paths, trims trailing
horizontal whitespace, and keeps report byte counts aligned with artifacts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[3]
REPORTS = (
    ROOT
    / "materials/crunchyroll/artifacts/offline-clone/frontend/source-acquisition-report-v3.json",
    ROOT
    / "materials/crunchyroll/artifacts/offline-clone/frontend/reset-acquisition-report-v3.json",
)
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
CF_PATH = re.compile(r"/cdn-cgi/challenge-platform(?:/[^\"'\s<>?]*)?")
TRAILING_SPACE = re.compile(r"[ \t]+(?=\r?$)", re.MULTILINE)
RUNTIME_FIELD = re.compile(
    r'(["\'](?:clientToken|applicationId|__CF\$cv\$params)["\']\s*[:=]\s*)["\'][^"\']*["\']',
    re.IGNORECASE,
)


def sanitized_url(value: str) -> str:
    parts = urlsplit(value)
    path = CF_PATH.sub("/cdn-cgi/challenge-platform/[redacted]", parts.path)
    if parts.scheme and parts.netloc:
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return CF_PATH.sub("/cdn-cgi/challenge-platform/[redacted]", value.split("?", 1)[0])


def sanitize_network(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "url" and isinstance(child, str):
                    value[key] = sanitized_url(child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sanitize_dom(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = SCRIPT.sub(
        '<script data-source-sanitized="runtime-body-redacted"></script>', text
    )
    text = CF_PATH.sub("/cdn-cgi/challenge-platform/[redacted]", text)
    text = RUNTIME_FIELD.sub(r'\1"[redacted]"', text)
    text = TRAILING_SPACE.sub("", text)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    touched: set[Path] = set()
    source_root = ROOT / "materials/crunchyroll/source-current"
    for artifact_path in source_root.rglob("network.json"):
        sanitize_network(artifact_path)
        touched.add(artifact_path)
    for artifact_path in source_root.rglob("dom.html"):
        sanitize_dom(artifact_path)
        touched.add(artifact_path)
    for report_path in REPORTS:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for page in report.get("pages", []):
            for artifact in page.get("artifacts", []):
                artifact_path = ROOT / artifact["path"]
                if artifact_path.exists():
                    artifact["bytes"] = artifact_path.stat().st_size
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"sanitized_artifacts={len(touched)}")


if __name__ == "__main__":
    main()
