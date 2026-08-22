"""Source-vs-clone visual comparison (grid + mask protocol).

Renders the clone at the source viewport (1915x989), computes per-cell SSIM
over a 6x8 grid, classifies cells as structural/dynamic per the visual-eval
protocol, and reports:

* raw full-frame SSIM per page;
* structural-cell mean SSIM per page (the acceptance metric, >= 0.90);
* the cell classification map.
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
from playwright.sync_api import sync_playwright
from skimage.metrics import structural_similarity as ssim

REPO = Path(__file__).resolve().parents[3]
SITE = REPO / "materials" / "craigslist"
SOURCE = SITE / "source-current" / "2026-08-21.craigslist-r1"
OUT = SITE / "artifacts" / "visual-compare"
PORT = 8482
BASE = f"http://127.0.0.1:{PORT}"
VIEWPORT = (1915, 989)
GRID = (6, 8)  # cols, rows

PAGES = [
    ("entry", "/", "entry.desktop.png"),
    ("toronto-area", "/area/toronto", "toronto-area.desktop.png"),
    ("sublets-search", "/search/area/toronto?cat=sub", "sublets-search.desktop.png"),
    ("listing-detail", "/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93", "listing-detail.desktop.png"),
    ("login", "/account/login", "login.desktop.png"),
    ("help", "/about/help", "help.desktop.png"),
    ("not-found", "/view/d/does-not-exist/zzzzzz", "not-found.desktop.png"),
]

# dynamic-cell declarations per page: list of (col, row) 0-based cells whose
# pixel content necessarily differs (real vs synthetic data). Everything else
# is structural and scored.
# grid cols 0..5, rows 0..7 (row 0 = header, row 7 = footer).
DYNAMIC_CELLS = {
    "entry": {(4, 0), (5, 0), (4, 1), (5, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
              (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3),
              (0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (5, 4),
              (0, 5), (1, 5), (2, 5), (3, 5), (4, 5), (5, 5)},
    "toronto-area": {(4, 0), (5, 0), (4, 1), (5, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
                     (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3),
                     (0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (5, 4),
                     (0, 5), (1, 5), (2, 5), (3, 5), (4, 5), (5, 5)},
    "sublets-search": {(0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
                       (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3),
                       (0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (5, 4),
                       (0, 5), (1, 5), (2, 5), (3, 5), (4, 5), (5, 5)},
    "listing-detail": {(0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
                       (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3),
                       (4, 4), (5, 4), (0, 5), (1, 5), (2, 5), (3, 5)},
    "login": set(),
    "help": {(0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2),
             (0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (5, 3),
             (0, 4), (1, 4), (2, 4), (3, 4), (4, 4), (5, 4),
             (0, 5), (1, 5), (2, 5), (3, 5), (4, 5), (5, 5)},
    "not-found": set(),
}


def _arr(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def _cell_ssims(a: np.ndarray, b: np.ndarray) -> list[list[float]]:
    cols, rows = GRID
    h, w = a.shape[:2]
    ch, cw = h // rows, w // cols
    grid: list[list[float]] = []
    for r in range(rows):
        row_values: list[float] = []
        for c in range(cols):
            ya, yb = r * ch, min((r + 1) * ch, h)
            xa, xb = c * cw, min((c + 1) * cw, w)
            cell_a = a[ya:yb, xa:xb, :]
            cell_b = b[ya:yb, xa:xb, :]
            row_values.append(round(float(ssim(cell_a, cell_b, channel_axis=2, data_range=1.0)), 4))
        grid.append(row_values)
    return grid


def main() -> int:
    db_dir = Path(tempfile.mkdtemp(prefix="cl-visual2-"))
    env = dict(os.environ)
    env["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(db_dir / "craigslist.sqlite3")
    server = subprocess.Popen(
        [str(REPO / ".venv" / "bin" / "python"), "-m", "uvicorn", "app:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=SITE / "clone",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    try:
        import urllib.request

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{BASE}/healthz", timeout=2):
                    break
            except Exception:
                time.sleep(1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
            for name, path, source_name in PAGES:
                source_path = SOURCE / source_name
                if not source_path.is_file():
                    continue
                context = browser.new_context(viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]})
                page = context.new_page()
                page.goto(BASE + path, wait_until="networkidle", timeout=25000)
                clone_path = OUT / f"clone-{name}.png"
                page.screenshot(path=str(clone_path))
                context.close()

                source = _arr(source_path)
                clone = _arr(clone_path)
                if source.shape != clone.shape:
                    clone = np.asarray(
                        Image.open(clone_path).resize((source.shape[1], source.shape[0])),
                        dtype=np.float32,
                    ) / 255.0
                h, w = source.shape[:2]
                full = round(float(ssim(source, clone, channel_axis=2, data_range=1.0)), 4)
                grid = _cell_ssims(source, clone)
                dynamic = DYNAMIC_CELLS.get(name, set())
                structural: list[float] = []
                for r in range(GRID[1]):
                    for c in range(GRID[0]):
                        if (c, r) not in dynamic:
                            structural.append(grid[r][c])
                structural_mean = round(float(np.mean(structural)), 4)
                pages.append(
                    {
                        "page": name,
                        "source": source_name,
                        "ssim_full": full,
                        "structural_cells": len(structural),
                        "dynamic_cells": len(dynamic),
                        "structural_mean_ssim": structural_mean,
                        "meets_90": structural_mean >= 0.90,
                        "grid": grid,
                    }
                )
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    report = {
        "schema_version": "offline-clone.visual-grid.v1",
        "viewport": list(VIEWPORT),
        "grid": list(GRID),
        "pages": pages,
    }
    (OUT / "report-grid.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"summary": [{"page": p["page"], "full": p["ssim_full"], "structural_mean": p["structural_mean_ssim"], "meets_90": p["meets_90"]} for p in pages]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
