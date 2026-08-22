"""Visual inspector — pixel-derived layout analysis and source/clone compare.

Because the working model cannot view images, this tool turns screenshots
into structured, readable layout facts:

* row density profile  -> content bands and blank bands (header, gaps, footer);
* column density profile -> column boundaries of multi-column layouts;
* dominant color palette and background detection;
* text-row estimation;
* source-vs-clone layout comparison producing a readable diff report;
* DOM geometry dump for the running clone (exact element boxes + styles).

Usage:
    python visual_inspector.py pixels <png>                # layout facts of one image
    python visual_inspector.py compare <src.png> <clone.png> [--label NAME]
    python visual_inspector.py dom <url> [--port N]        # live clone geometry
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# pixel analysis
# ---------------------------------------------------------------------------


def _gray(path: str) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return np.asarray(img).mean(axis=2), img.size


def row_profile(gray: np.ndarray, threshold: int = 235) -> list[int]:
    return [int((gray[y, :] < threshold).sum()) for y in range(gray.shape[0])]


def col_profile(gray: np.ndarray, y0: int, y1: int, threshold: int = 235) -> list[int]:
    return [int((gray[y0:y1, x] < threshold).sum()) for x in range(gray.shape[1])]


def bands_from_profile(profile: list[int], min_dark: int, min_gap: int) -> list[tuple[int, int]]:
    """Return (start,end) runs where profile >= min_dark; merge gaps < min_gap."""
    runs: list[tuple[int, int]] = []
    in_run = False
    for i, value in enumerate(profile):
        if value >= min_dark and not in_run:
            start = i
            in_run = True
        elif value < min_dark and in_run:
            runs.append((start, i))
            in_run = False
    if in_run:
        runs.append((start, len(profile)))
    merged: list[tuple[int, int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= min_gap:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return merged


def blank_bands(profile: list[int], min_dark: int = 20, min_len: int = 30) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    in_run = False
    for i, value in enumerate(profile):
        if value < min_dark and not in_run:
            start = i
            in_run = True
        elif value >= min_dark and in_run:
            if i - start >= min_len:
                runs.append((start, i))
            in_run = False
    if in_run and len(profile) - start >= min_len:
        runs.append((start, len(profile)))
    return runs


def detect_columns(gray: np.ndarray, y0: int, y1: int, min_gap: int = 30) -> list[dict]:
    """Find vertical whitespace gaps that split the band into columns."""
    profile = col_profile(gray, y0, y1)
    gaps: list[tuple[int, int]] = []
    in_gap = False
    for x, value in enumerate(profile):
        if value < 15 and not in_gap:
            start = x
            in_gap = True
        elif value >= 15 and in_gap:
            if x - start >= min_gap:
                gaps.append((start, x))
            in_gap = False
    if in_gap and len(profile) - start >= min_gap:
        gaps.append((start, len(profile)))
    columns: list[dict] = []
    cursor = 0
    for gx0, gx1 in gaps:
        if gx0 - cursor >= 40:
            columns.append({"x0": cursor, "x1": gx0, "width": gx0 - cursor})
        cursor = gx1
    if len(profile) - cursor >= 40:
        columns.append({"x0": cursor, "x1": len(profile), "width": len(profile) - cursor})
    return columns


def dominant_colors(gray: np.ndarray, k: int = 6) -> list[dict]:
    """k-most-common quantized gray levels of the image."""
    flat = np.asarray(gray, dtype=np.uint8)
    q = (flat // 24) * 24
    counts: dict[int, int] = {}
    for value in q.reshape(-1):
        counts[value] = counts.get(value, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:k]
    return [{"gray": int(v), "share": round(c / q.size, 4)} for v, c in top]


def text_row_estimate(gray: np.ndarray, y0: int, y1: int) -> dict:
    """Estimate typical text height from dark runs in vertical strips."""
    band = gray[y0:y1, :]
    heights: list[int] = []
    for x in range(0, band.shape[1], 4):
        col = band[:, x]
        dark = np.where(col < 150)[0]
        if len(dark) < 2:
            continue
        groups: list[tuple[int, int]] = []
        start = prev = dark[0]
        for v in dark[1:]:
            if v - prev > 6:
                groups.append((start, prev))
                start = v
            prev = v
        groups.append((start, prev))
        for g0, g1 in groups:
            height = g1 - g0 + 1
            if 5 <= height <= 45:
                heights.append(height)
    if not heights:
        return {"samples": 0, "median_px": 0}
    return {"samples": len(heights), "median_px": int(np.median(heights))}


def density_profile(gray: np.ndarray, band: int = 24, threshold: int = 235) -> list[dict]:
    """Per-band dark-pixel counts across the full height."""
    rows = row_profile(gray, threshold)
    profile: list[dict] = []
    for y in range(0, gray.shape[0], band):
        slice_rows = rows[y : y + band]
        profile.append({"y": y, "dark": int(sum(slice_rows))})
    return profile


def band_sum(gray: np.ndarray, y0: int, y1: int, threshold: int = 235) -> int:
    rows = row_profile(gray, threshold)
    return int(sum(rows[y0:y1]))


def layout_structure(path: str) -> dict:
    gray, size = _gray(path)
    h, w = gray.shape
    rows = row_profile(gray)
    blanks = blank_bands(rows, min_dark=20, min_len=30)
    # header band = top 170px density; footer band = bottom 90px density
    header_dark = band_sum(gray, 0, 170)
    footer_dark = band_sum(gray, h - 90, h)
    # columns in the upper-middle band (content section)
    c0, c1 = int(h * 0.30), int(h * 0.85)
    columns = detect_columns(gray, c0, c1)
    text = text_row_estimate(gray, c0, c1)
    colors = dominant_colors(gray)
    return {
        "width": w,
        "height": h,
        "header_dark_170": header_dark,
        "footer_dark_90": footer_dark,
        "blank_bands": [[int(a), int(b)] for a, b in blanks[:10]],
        "columns_in_content": columns[:10],
        "text_median_px": text["median_px"],
        "top_colors": colors[:4],
        "density": density_profile(gray),
    }


def compare_layouts(src_png: str, clone_png: str, label: str = "") -> dict:
    src_gray, _ = _gray(src_png)
    clone_gray, _ = _gray(clone_png)
    src = layout_structure(src_png)
    clone = layout_structure(clone_png)
    # band-level divergence: where clone is empty but source has content
    divergences: list[dict] = []
    s_profile = src["density"]
    c_profile = clone["density"]
    for s, c in zip(s_profile, c_profile):
        if s["dark"] > 400 and c["dark"] < 60:
            divergences.append(
                {"y": s["y"], "src_dark": s["dark"], "clone_dark": c["dark"],
                 "kind": "clone-blank-where-source-has-content"}
            )
        elif c["dark"] > 400 and s["dark"] < 60:
            divergences.append(
                {"y": s["y"], "src_dark": s["dark"], "clone_dark": c["dark"],
                 "kind": "clone-content-where-source-blank"}
            )
    return {
        "page": label,
        "source": {k: v for k, v in src.items() if k != "density"},
        "clone": {k: v for k, v in clone.items() if k != "density"},
        "divergences": divergences[:40],
        "density_src": src["density"],
        "density_clone": clone["density"],
    }


# ---------------------------------------------------------------------------
# live clone DOM geometry
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[3]
SITE = REPO / "materials" / "craigslist"
VENV_PY = REPO / ".venv" / "bin" / "python"


def dom_geometry(url_path: str, selectors: list[str]) -> dict:
    """Boot the clone and dump bounding boxes + computed styles for selectors."""
    db_dir = Path(tempfile.mkdtemp(prefix="cl-dom-"))
    env = dict(os.environ)
    env["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(db_dir / "craigslist.sqlite3")
    port = 8490
    server = subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(SITE / "clone"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        import urllib.request

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2)
                break
            except Exception:
                time.sleep(1)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            page = browser.new_context(viewport={"width": 1915, "height": 989}).new_page()
            page.goto(f"http://127.0.0.1:{port}{url_path}", wait_until="networkidle")
            elements: list[dict] = []
            for selector in selectors:
                for el in page.query_selector_all(selector):
                    box = el.bounding_box()
                    style = el.evaluate(
                        "el => { const s = getComputedStyle(el); return {"
                        "font: s.fontSize + '/' + s.lineHeight + ' ' + s.fontFamily,"
                        "color: s.color, bg: s.backgroundColor,"
                        "margin: s.margin, padding: s.padding, border: s.borderTopWidth,"
                        "display: s.display, align: s.alignItems, justify: s.justifyContent,"
                        "flex: s.flexDirection + ' ' + s.flexWrap}" 
                        "}"
                    )
                    elements.append(
                        {"selector": selector, "text": (el.text_content() or "")[:40],
                         "box": box, "style": style}
                    )
            doc = page.evaluate(
                "() => ({h: document.documentElement.scrollHeight,"
                " w: document.documentElement.scrollWidth})"
            )
            browser.close()
        return {"path": url_path, "doc": doc, "elements": elements}
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    mode = sys.argv[1]
    if mode == "pixels":
        print(json.dumps(layout_structure(sys.argv[2]), indent=2))
        return 0
    if mode == "compare":
        label = ""
        if "--label" in sys.argv:
            label = sys.argv[sys.argv.index("--label") + 1]
        print(json.dumps(compare_layouts(sys.argv[2], sys.argv[3], label), indent=2))
        return 0
    if mode == "dom":
        url = sys.argv[2]
        selectors = sys.argv[3].split(",") if len(sys.argv) > 3 else [
            ".cl-header", ".cl-header-inner", ".cl-logo", ".header-search",
            ".cl-header-links", ".cl-main", ".cl-footer", ".cl-breadcrumb",
        ]
        print(json.dumps(dom_geometry(url, selectors), indent=2, ensure_ascii=False))
        return 0
    print(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
