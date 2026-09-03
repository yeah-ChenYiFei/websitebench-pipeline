#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""像素相似度比较 —— §11 要求每条检查点 ≥ 0.94，且 threshold 冻在 0.94。

metric 与引擎的 visual_contract 对齐：pixel-mae-similarity-v1
（逐通道平均绝对误差归一化后取 1 - MAE）。

参照帧来自源站（用户机器上 `cb_capture.py shots` 拍的），
候选帧由本地起站后拍。两侧视口尺寸一致才有可比性。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "materials" / "creativebug"
THRESHOLD = 0.94


def similarity(a: Path, b: Path) -> tuple[float, tuple[int, int], tuple[int, int]]:
    from PIL import Image
    import numpy as np
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    sa, sb = ia.size, ib.size
    if sa != sb:
        # 尺寸不同就按较小者裁切左上角再比；尺寸差异本身另行报告，不静默缩放
        w, h = min(sa[0], sb[0]), min(sa[1], sb[1])
        ia, ib = ia.crop((0, 0, w, h)), ib.crop((0, 0, w, h))
    na = np.asarray(ia, dtype="float32")
    nb = np.asarray(ib, dtype="float32")
    mae = float(np.abs(na - nb).mean()) / 255.0
    return 1.0 - mae, sa, sb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True, help="源站参照帧目录")
    ap.add_argument("--candidate", required=True, help="克隆候选帧目录")
    ap.add_argument("--write-contracts", action="store_true",
                    help="把结果写回 checkpoints.json 的 visual_contract")
    a = ap.parse_args()
    ref, cand = Path(a.reference), Path(a.candidate)

    cps = json.loads((SITE / "scope" / "checkpoints.json").read_text(encoding="utf-8"))
    rows, missing = [], []
    for c in cps["checkpoints"]:
        rp, cp = ref / f"{c['id']}.png", cand / f"{c['id']}.png"
        if not rp.is_file() or not cp.is_file():
            missing.append((c["id"], "参照帧缺失" if not rp.is_file() else "候选帧缺失"))
            continue
        score, sa, sb = similarity(rp, cp)
        rows.append({"id": c["id"], "score": round(score, 4),
                     "ref_size": list(sa), "cand_size": list(sb),
                     "pass": score >= THRESHOLD})

    (HERE / "_visual.json").write_text(
        json.dumps({"threshold": THRESHOLD, "results": rows, "missing": missing},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    if rows:
        rows.sort(key=lambda r: r["score"])
        n_pass = sum(1 for r in rows if r["pass"])
        # 用户 2026-08-30 裁定 A：参考帧主体与候选帧主体不同的检查点计入
        # valid_exclusions，不进达标分母（ULTIMATE §7:
        # required = discovered - valid_exclusions）。读数仍照常打印，
        # 只是分母里不算 —— 排除项必须看得见，不能悄悄消失。
        # 注：rows 里的键是 "score"。此处三处曾写成 r["similarity"]，
        # 一旦 checkpoints.json 出现 acceptance_eligible 就 KeyError ——
        # 也就是说"排除项不进分母"这条裁定从未真正打印过一次读数。
        elig = {c["id"] for c in cps["checkpoints"] if c.get("acceptance_eligible", True)}
        er = [r for r in rows if r["id"] in elig]
        xr = [r for r in rows if r["id"] not in elig]
        n_pass_e = sum(1 for r in er if r["score"] >= THRESHOLD)
        print(f"比较 {len(rows)} 条  达标 {n_pass}  未达标 {len(rows)-n_pass}  阈值 {THRESHOLD}")
        print(f"纳入分母 {len(er)} 条  达标 {n_pass_e}  未达标 {len(er)-n_pass_e}")
        if xr:
            print(f"已声明排除 {len(xr)} 条（不进分母）：")
            for r in sorted(xr, key=lambda r: r["score"]):
                cp = next(c for c in cps["checkpoints"] if c["id"] == r["id"])
                print(f"  {r['score']:.4f}  {r['id']}  <- {cp.get('exclusion',{}).get('code','?')}")
        print(f"  最低 {rows[0]['score']:.4f} ({rows[0]['id']})"
              f"   中位 {rows[len(rows)//2]['score']:.4f}"
              f"   最高 {rows[-1]['score']:.4f}")
        print("\n未达标逐条：")
        for r in rows:
            if not r["pass"]:
                note = "  尺寸不一致" if r["ref_size"] != r["cand_size"] else ""
                print(f"   {r['score']:.4f}  {r['id']}{note}")
    if missing:
        print(f"\n缺帧 {len(missing)} 条（不能算作达标）：")
        for i, why in missing[:10]:
            print(f"   {i}: {why}")

    if a.write_contracts and rows:
        by = {r["id"]: r for r in rows}
        for c in cps["checkpoints"]:
            r = by.get(c["id"])
            if not r:
                continue
            c["visual_contract"] = {
                "source_artifact_path": f"reference/{c['id']}.png",
                "viewport": cps["viewports"][c["viewport"]],
                "comparison_region": {"x": 0, "y": 0,
                                      "width": r["ref_size"][0], "height": r["ref_size"][1]},
                "metric": "pixel-mae-similarity-v1",
                "threshold": THRESHOLD,     # §11：冻的就是 0.94，不是 0.995
            }
        (SITE / "scope" / "checkpoints.json").write_text(
            json.dumps(cps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n已写回 {sum(1 for c in cps['checkpoints'] if 'visual_contract' in c)} 条 visual_contract")
    return 0 if rows and all(r["pass"] for r in rows) and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
