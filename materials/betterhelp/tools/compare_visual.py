from __future__ import annotations

import json
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "source-current" / "2026-08-21.playwright-anon"
candidate = ROOT / "artifacts" / "offline-clone" / "candidate-capture"
rows = []
for name, width, height in (("desktop", 1440, 900), ("tablet", 768, 1024), ("mobile", 390, 844)):
    src = Image.open(source / f"home-{name}-{width}x{height}.png").convert("RGB")
    cand = Image.open(candidate / f"home-{name}-{width}x{height}.png").convert("RGB")
    src = src.crop((0, 0, width, height))
    cand = cand.crop((0, 0, width, height))
    diff = ImageChops.difference(src, cand)
    mean = sum(ImageStat.Stat(diff).mean) / 3 / 255
    rows.append({"viewport": name, "width": width, "height": height, "source": str(source / f"home-{name}-{width}x{height}.png"), "candidate": str(candidate / f"home-{name}-{width}x{height}.png"), "mean_absolute_error_normalized": round(mean, 6), "similarity_estimate": round(1 - mean, 6), "threshold": 0.7, "passes_threshold": (1 - mean) >= 0.7})
(ROOT / "artifacts" / "offline-clone" / "visual-comparison.json").write_text(json.dumps({"schema_version": "betterhelp.visual-comparison.v1", "method": "pixel-mae-similarity-v1", "rows": rows}, indent=2) + "\n", encoding="utf-8")
print(json.dumps(rows))
