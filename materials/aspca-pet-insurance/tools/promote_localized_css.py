"""Promote safe localized CSS without mutating immutable capture copies."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from websitebench.offline_clone.assets import inspect_asset


SITE = Path(__file__).resolve().parents[1]
CLONE = SITE / "clone"
MANIFEST = SITE / "source-assets" / "manifest.json"
VENDOR = CLONE / "static" / "site" / "vendor"


def invalid(path: Path) -> bool:
    try:
        inspect_asset(path)
    except ValueError:
        return True
    return False


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    replacements: dict[str, str] = {}
    VENDOR.mkdir(parents=True, exist_ok=True)

    for asset in manifest["assets"]:
        source = SITE / asset["source_path"]
        runtime = SITE / asset["runtime_path"]
        if (
            not asset["required"]
            or runtime.suffix.casefold() != ".css"
            or not invalid(source)
        ):
            continue
        # The localized runtime copy must independently satisfy the same
        # closure inspector before it can leave the immutable asset tree.
        inspect_asset(runtime)
        payload = runtime.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()[:16]
        destination = VENDOR / f"localized-{digest}.css"
        destination.write_bytes(payload)
        old_url = "/" + asset["runtime_path"].removeprefix("clone/")
        replacements[old_url] = "/static/site/vendor/" + destination.name

    changed = 0
    for path in sorted(CLONE.rglob("*")):
        if not path.is_file() or "/static/assets/" in path.as_posix():
            continue
        try:
            before = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        after = before
        for old, new in replacements.items():
            after = after.replace(old, new)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed += 1

    print(
        json.dumps(
            {
                "promoted_stylesheets": len(replacements),
                "rewritten_files": changed,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
