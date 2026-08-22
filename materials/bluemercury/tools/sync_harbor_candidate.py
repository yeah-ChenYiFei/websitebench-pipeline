#!/usr/bin/env python3
"""Synchronize the frozen local clone into the Bluemercury Harbor public seed."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SITE = REPO / "materials" / "bluemercury"
PUBLIC = REPO / "harbor" / "instances" / "bluemercury" / "public"


def main() -> None:
    if PUBLIC.resolve().parent.name != "bluemercury" or PUBLIC.name != "public":
        raise SystemExit("refusing unexpected public candidate target")
    shutil.copytree(SITE / "backend", PUBLIC / "backend", dirs_exist_ok=True)
    shutil.copytree(SITE / "clone", PUBLIC / "clone", dirs_exist_ok=True)
    for stale in (PUBLIC / "clone" / "__pycache__", PUBLIC / "clone" / "backend" / "__pycache__", PUBLIC / "clone" / "tests" / "__pycache__"):
        if stale.is_dir() and PUBLIC.resolve() in stale.resolve().parents:
            shutil.rmtree(stale)
    summary = {
        "backend_files": sum(path.is_file() for path in (PUBLIC / "backend").rglob("*")),
        "clone_files": sum(path.is_file() for path in (PUBLIC / "clone").rglob("*")),
        "products": len(json.loads((PUBLIC / "clone" / "static" / "products.json").read_text(encoding="utf-8"))["products"]),
    }
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
