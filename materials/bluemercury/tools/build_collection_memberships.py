#!/usr/bin/env python3
"""Build compact local collection membership from captured public collection JSON."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "source-assets" / "2026-08-20.playwright-r3"
OUTPUT = ROOT / "clone" / "static" / "collection-memberships.json"
SOURCES = {
    "fall-beauty-must-haves": CAPTURE / "fall-beauty-products.json",
    "m-61-perfect-collection": CAPTURE / "m61-perfect-products.json",
}


def main() -> None:
    memberships = {}
    for handle, source in SOURCES.items():
        document = json.loads(source.read_text(encoding="utf-8-sig"))
        memberships[handle] = [product["handle"] for product in document.get("products", [])]
    OUTPUT.write_text(json.dumps(memberships, indent=2), encoding="utf-8")
    print(json.dumps({handle: len(products) for handle, products in memberships.items()}))


if __name__ == "__main__":
    main()
