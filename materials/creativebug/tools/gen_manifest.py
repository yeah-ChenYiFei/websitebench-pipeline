#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 source-assets/manifest.json。

MIME 一律用引擎 inspect_asset 推导的那个（声明必须与实测一致，否则 ASSET_MISMATCH）。
尺寸：引擎对 .ico 不走 PIL 分支，推导不出尺寸；但声明 image/* 又必须有尺寸
（§7.3(b)）。两难的出路是用 PIL 把真实尺寸补进声明，而不是把 MIME 降级。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from precheck import inspect_asset  # noqa: E402

SITE = HERE.parent / "materials" / "creativebug"
SRC = SITE / "source-assets" / "2026-08-28.creativebug-r1"
SERVED = SITE / "source-assets" / "served"
RUN = SITE / "clone" / "static" / "assets"


def pil_dimensions(path: Path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return {"width": im.size[0], "height": im.size[1]}
    except Exception:
        return None


def main() -> int:
    amap = json.loads((HERE / "_assets.json").read_text(encoding="utf-8"))["assets"]
    url_of = {n: u for u, n in amap.items()}
    for css in list(SERVED.glob("*.css")) + list(SRC.glob("*.css")):
        txt = css.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'url\((https://fonts\.gstatic\.com/[^)]+)\)', txt):
            url_of.setdefault("font-" + Path(m.group(1).split("?")[0]).name, m.group(1))
    for u, n in amap.items():
        if "fonts.googleapis.com" not in u or not (SRC / n).is_file():
            continue
        for m in re.finditer(r'url\((https://fonts\.gstatic\.com/[^)]+)\)',
                             (SRC / n).read_text(encoding="utf-8", errors="replace")):
            url_of["font-" + Path(m.group(1).split("?")[0]).name] = m.group(1)

    assets, no_dims, rejected = [], [], []
    for name in sorted({p.name for p in RUN.glob("*")}):
        sp = SERVED / name if (SERVED / name).is_file() else SRC / name
        rp = RUN / name
        if not sp.is_file():
            continue
        try:
            obs = inspect_asset(sp)
        except ValueError as exc:
            # §7.1 第 1 步：内容其实是 HTML 的"资产"。源站对不存在的图片
            # 返回 200 + 品牌化 404 页（见 known-differences 的
            # source_soft_404_returns_200），下载器据此记为成功。
            # 这类文件不声明、也不交付，逐条记账而不是让清单生成崩掉。
            rejected.append((name, str(exc)))
            continue
        mime, dims = obs["mime_type"], obs["dimensions"]
        if mime.startswith("image/") and dims is None:
            # §7.3(b) 的两难：引擎对 .ico 推导出 image/* 却拿不到尺寸。
            # 声明尺寸 → 与实测不符；声明 octet-stream → MIME 不符；
            # 不声明尺寸 → IMAGE_DIMENSIONS_UNDECLARED。
            # 文档给的第一条出路是别把它声明成资产 —— favicon 不影响保真度，
            # 从清单剔除并记进 known-differences。
            no_dims.append(name)
            continue
        src_url = url_of.get(name)
        if src_url is not None and not re.match(r"^https?://", str(src_url)):
            src_url = None
        assets.append({
            "id": re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")[:200],
            "priority": "p0", "required": True,
            "source_url": src_url,
            "evidence_kind": "current-direct" if src_url else "bounded",
            "source_path": str(sp.relative_to(SITE)),
            "runtime_path": str(rp.relative_to(SITE)),
            "bytes": obs["bytes"], "mime_type": mime, "dimensions": dims,
            "referenced_by": ["route:home"],
        })

    man = {"schema_version": "offline-clone.assets.v1",
           "snapshot_id": "2026-08-28.creativebug-r1",
           "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
           "closure_status": "declared", "no_assets_reason": None,
           "remote_runtime_policy": "forbidden", "assets": assets}
    (SITE / "source-assets" / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    import collections
    print(f"manifest {len(assets)} 个资产")
    print("  MIME:", dict(collections.Counter(a["mime_type"] for a in assets).most_common(8)))
    if rejected:
        print(f"  拒绝（内容是 HTML 外壳）{len(rejected)} 个: {[r[0] for r in rejected][:3]}")
    print(f"  有尺寸 {sum(1 for a in assets if a['dimensions'])}"
          f"  未声明(补不出尺寸) {len(no_dims)} {no_dims[:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
