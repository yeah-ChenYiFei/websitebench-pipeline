"""Prevent retired publication-readiness names from returning to active files."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROHIBITED = (
    re.compile("release" + r"[-_ ]?ready", re.IGNORECASE),
    re.compile("release" + "_gates", re.IGNORECASE),
    re.compile("check" + "-release", re.IGNORECASE),
)
ACTIVE_PATHS = (
    "AGENTS.md",
    "README.md",
    "PROJECT.md",
    "DEPLOYMENT.md",
    "docs",
    "deploy",
    "prompts",
    "scripts",
    ".github",
    "src",
    "tests",
    "materials",
    "harbor",
    "websitebench/schemas",
)
HISTORICAL_OR_COMPATIBILITY = (
    "materials/*/source-assets/**",
    "materials/*/source-current/**",
    "materials/*/artifacts/**",
    "materials/*/agent-review/**",
    "materials/*/.clone-harness/**",
    "harbor/**/evidence/**",
    "harbor/**/reference/**",
)


def _is_exempt(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    return any(
        fnmatch(relative, pattern) or relative == pattern
        for pattern in HISTORICAL_OR_COMPATIBILITY
    )


def _active_files() -> list[Path]:
    files: list[Path] = []
    for relative in ACTIVE_PATHS:
        path = ROOT / relative
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
    return sorted(set(files))


def test_retired_readiness_names_are_absent_from_active_content() -> None:
    matches: list[str] = []
    for path in _active_files():
        if _is_exempt(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PROHIBITED:
            if pattern.search(text):
                matches.append(path.relative_to(ROOT).as_posix())
                break
    assert not matches, "retired readiness names in active files: " + ", ".join(matches)
