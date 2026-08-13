#!/usr/bin/env python3
"""Repository-local launcher for the canonical offline-clone CLI.

This entry point avoids editable-install path decoding issues when a Windows
checkout lives under a non-ASCII directory. It contains no tool logic.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from websitebench.offline_clone.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
