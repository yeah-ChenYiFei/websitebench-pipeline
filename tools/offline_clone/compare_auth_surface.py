#!/usr/bin/env python3
"""Compare a clone's auth surface against the captured source surface.

Diagnostic only.  Renders the running clone's sign-in / register page with the
same extractor used against the source, then reports the structural diff plus a
crude vertical-alignment measurement so layout drift shows up as a number rather
than an impression.

It answers two different questions, and both matter:

* **structure** — same heading, same field order and labels, same provider row,
  same legal copy, same links.  A clone can look right and still ask for the
  wrong things.
* **alignment** — where the content band starts and ends, and where full-width
  rules land.  A clone can have identical markup and still sit 30px low.

Neither is a release metric.  The gate's visual metric is
``pixel-mae-similarity-v1``; nothing here produces a number in that family.

Usage::

    # start the clone first, then:
    .venv/bin/python tools/offline_clone/compare_auth_surface.py \
        --site amazon --surface signin --base-url http://127.0.0.1:8496
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_auth_surfaces import EXTRACT, auth_relevance  # noqa: E402

# Where each site's auth pages live on its own clone.
CLONE_PATHS: dict[str, dict[str, str]] = {
    "amazon": {"signin": "/ap/signin", "register": "/ap/register"},
    "edx": {"signin": "/login", "register": "/register"},
    "capterra": {"signin": "/auth/login", "register": "/auth/register"},
    "petfinder": {"signin": "/auth/login", "register": "/auth/register"},
    "tripit": {"signin": "/account/login", "register": "/account/create"},
    "change": {"signin": "/login_or_join", "register": "/register"},
    "taskrabbit": {"signin": "/login", "register": "/register"},
    "etsy": {"signin": "/signin", "register": "/register"},
}


def fields(structure: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (str(field.get("type")), (field.get("label") or "").strip())
        for form in structure.get("forms") or []
        for field in form.get("fields") or []
    ]


def buttons(structure: dict[str, Any]) -> list[str]:
    return [b for form in structure.get("forms") or [] for b in form.get("buttons") or []]


def alignment(path: Path) -> dict[str, Any]:
    """Where content starts/ends and where full-width rules land."""

    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {"unavailable": "Pillow/numpy not installed"}
    grey = np.asarray(Image.open(path).convert("L"))[:900, :]
    rows = [y for y in range(grey.shape[0]) if (grey[y] < 230).sum() > 2]
    rules = [y for y in range(grey.shape[0]) if (grey[y] < 245).sum() > grey.shape[1] * 0.8]
    return {
        "content_top": rows[0] if rows else None,
        "content_bottom": rows[-1] if rows else None,
        "full_width_rules": rules[:4],
    }


def render_clone(base_url: str, path: str, out: Path, viewport: dict[str, int]) -> dict:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=viewport)
        page.goto(base_url.rstrip("/") + path, wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        page.screenshot(path=str(out / "viewport.png"))
        structure = page.evaluate(EXTRACT)
        browser.close()
    (out / "structure.json").write_text(
        json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return structure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, choices=sorted(CLONE_PATHS))
    parser.add_argument("--surface", default="signin", choices=("signin", "register"))
    parser.add_argument("--base-url", required=True, help="the running clone")
    parser.add_argument("--path", help="override the clone path for this surface")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()

    root = REPO_ROOT / "materials" / args.site / "artifacts" / "parity" / "auth"
    source_dir = root / args.surface / "desktop"
    source_file = source_dir / "structure.json"
    if not source_file.is_file():
        print(
            f"no source capture for {args.site}/{args.surface}. Run:\n"
            f"  .venv/bin/python tools/offline_clone/capture_auth_surfaces.py "
            f"--site {args.site}",
            file=sys.stderr,
        )
        return 2
    source = json.loads(source_file.read_text(encoding="utf-8"))
    source_score = auth_relevance(source)
    if source_score < 5:
        print(
            f"WARNING: the stored source capture scores {source_score} "
            f"(<5 is not a usable rebuild source). Re-capture before trusting "
            f"this comparison.\n",
            file=sys.stderr,
        )

    path = args.path or CLONE_PATHS[args.site][args.surface]
    clone_dir = root / args.surface / "clone"
    try:
        clone = render_clone(
            args.base_url, path, clone_dir, {"width": args.width, "height": args.height}
        )
    except Exception as exc:  # noqa: BLE001 - the cause is almost always "not running"
        print(
            f"could not render {args.base_url.rstrip('/')}{path}: "
            f"{type(exc).__name__}\n"
            "Is the clone running? Start the selected clone with its current "
            "site-specific runtime command and retry.",
            file=sys.stderr,
        )
        return 2

    print(f"{'':12s} {'SOURCE':<48s} CLONE")
    for label, key in (("title", "title"), ("lang", "lang")):
        print(f"{label:12s} {str(source.get(key))[:46]:<48s} {str(clone.get(key))[:46]}")
    print(
        f"{'heading':12s} {str((source.get('headings') or [''])[:1])[:46]:<48s} "
        f"{str((clone.get('headings') or [''])[:1])[:46]}"
    )
    print(f"{'auth score':12s} {source_score:<48d} {auth_relevance(clone)}")

    for label, getter in (("fields", fields), ("buttons", buttons)):
        want, got = getter(source), getter(clone)
        print(f"\n{label}:  {'MATCH' if want == got else 'DIFFER'}")
        print(f"  source  {want}")
        print(f"  clone   {got}")

    for label, key in (("third-party", "thirdPartyControls"), ("legal", "legal")):
        want = [str(v)[:70] for v in (source.get(key) or [])]
        got = [str(v)[:70] for v in (clone.get(key) or [])]
        print(f"\n{label}:  {'MATCH' if want == got else 'DIFFER'}")
        print(f"  source  {want}")
        print(f"  clone   {got}")

    print("\nalignment (lower is not better — closer to source is):")
    print(f"  source  {alignment(source_dir / 'viewport.png')}")
    print(f"  clone   {alignment(clone_dir / 'viewport.png')}")
    print(f"\nscreenshots: {source_dir / 'viewport.png'}\n             {clone_dir / 'viewport.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
