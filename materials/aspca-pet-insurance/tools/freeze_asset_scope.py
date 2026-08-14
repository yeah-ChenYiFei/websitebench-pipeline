"""Freeze the candidate asset denominator without rewriting capture payloads.

The source capture intentionally retained every observed network payload,
including analytics and telemetry.  The offline-clone asset contract covers
only files referenced by shipped candidate documents and their local CSS
dependencies.  This script preserves every historical asset row, byte/hash,
source reference, and payload path while recomputing the mutable candidate
scope fields (required, priority, referenced_by).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path

from websitebench.offline_clone.assets import inspect_asset


SITE = Path(__file__).resolve().parents[1]
CLONE = SITE / "clone"
MANIFEST = SITE / "source-assets" / "manifest.json"
CAPTURE_ID = "2026-08-13.aspca-pet-insurance-r1"
ASSET_URL = re.compile(
    rf"/static/assets/{re.escape(CAPTURE_ID)}/[^\s\"'<>;)]+"
)


def references(text: str) -> set[str]:
    return {match.rstrip(".,;}]") for match in ASSET_URL.findall(text)}


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_url = {
        "/" + asset["runtime_path"].removeprefix("clone/"): asset
        for asset in manifest["assets"]
    }
    referenced_by: dict[str, set[str]] = defaultdict(set)
    pending: deque[str] = deque()

    for path in sorted(CLONE.rglob("*")):
        if not path.is_file() or "/static/assets/" in path.as_posix():
            continue
        relative = path.relative_to(CLONE).as_posix()
        for url in references(path.read_text(encoding="utf-8", errors="ignore")):
            if url not in by_url:
                continue
            if url not in referenced_by:
                pending.append(url)
            referenced_by[url].add(f"candidate:{relative}")

    visited_css: set[str] = set()
    while pending:
        url = pending.popleft()
        asset = by_url[url]
        runtime = SITE / asset["runtime_path"]
        if runtime.suffix.casefold() != ".css" or url in visited_css:
            continue
        visited_css.add(url)
        relative = runtime.relative_to(CLONE).as_posix()
        for dependency in references(
            runtime.read_text(encoding="utf-8", errors="ignore")
        ):
            if dependency not in by_url:
                continue
            if dependency not in referenced_by:
                pending.append(dependency)
            referenced_by[dependency].add(f"candidate:{relative}")

    for url, asset in by_url.items():
        required = url in referenced_by
        asset["required"] = required
        asset["referenced_by"] = sorted(referenced_by.get(url, ()))
        if not required:
            asset["priority"] = "p2"
            continue
        # Capture response headers are not a reliable MIME/dimension oracle
        # (CDNs commonly serve SVG/GIF/font bytes as octet-stream).  Freeze
        # metadata from the immutable source payload using the repository's
        # own closure inspector; the bytes and sha256 remain untouched.
        source = SITE / asset["source_path"]
        try:
            observed = inspect_asset(source)
        except ValueError:
            # Keep the original declaration so the diagnostic reports a real
            # unsafe/invalid required payload instead of silently blessing it.
            continue
        asset["bytes"] = observed["bytes"]
        asset["mime_type"] = observed["mime_type"]
        asset["dimensions"] = observed["dimensions"]

    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "declared": len(by_url),
                "required": len(referenced_by),
                "css_dependencies_scanned": len(visited_css),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
