# -*- coding: utf-8 -*-
"""排除项必须是有据可查的少数，不能拿来刷分。

存在的理由：用户 2026-08-30 裁定 A —— 参考帧主体与候选帧主体不同的 5 条检查点
计入 `valid_exclusions`，不进达标分母（ULTIMATE §7:
required = discovered - valid_exclusions）。

排除机制一旦没人守，就是最省事的刷分通道：把不达标的检查点逐条标成"排除"，
分母越缩越小，达标率一路走高。所以这里钉死三件事：
1. 排除项恰好是裁定的那 5 条 —— 多一条少一条都要红；
2. 每条都必须写明 code / ruling / reason，不许空标；
3. 被排除的检查点仍须保留 visual_contract 且 threshold 冻在 0.94 ——
   排除的是"是否计入分母"，不是"是否还要量"。
"""
from __future__ import annotations

import json
from pathlib import Path

SCOPE = Path(__file__).resolve().parents[2] / "scope"
RULED = {
    "gallery-mine.loaded.desktop",
    "recent.loaded.desktop",
    "library.loaded.desktop",
    "dashboard.loaded.desktop",
    "watchlist.loaded.desktop",
}


def _checkpoints():
    return json.loads((SCOPE / "checkpoints.json").read_text(encoding="utf-8"))["checkpoints"]


def test_excluded_checkpoints_are_exactly_the_ruled_five():
    excluded = {c["id"] for c in _checkpoints() if not c.get("acceptance_eligible", True)}
    assert excluded == RULED, (
        f"排除集合变了 —— 多出: {sorted(excluded - RULED)}；少了: {sorted(RULED - excluded)}。"
        "扩大排除范围会缩小达标分母，属于刷分，必须由用户重新裁定。"
    )


def test_every_exclusion_states_its_grounds():
    for c in _checkpoints():
        if c.get("acceptance_eligible", True):
            assert "exclusion" not in c, f"{c['id']} 仍计入分母却带了 exclusion 字段"
            continue
        ex = c.get("exclusion")
        assert ex, f"{c['id']} 被排除但没写理由"
        for k in ("code", "ruling", "reason"):
            assert ex.get(k), f"{c['id']} 的 exclusion 缺 {k}"


def test_excluded_checkpoints_still_measured_at_frozen_threshold():
    """排除的是分母资格，不是测量本身；阈值仍须冻在 0.94（§11）。"""
    for c in _checkpoints():
        if c.get("acceptance_eligible", True):
            continue
        vc = c.get("visual_contract")
        assert vc, f"{c['id']} 被排除后丢了 visual_contract —— 读数不能一起消失"
        assert vc.get("threshold") == 0.94, f"{c['id']} 的 threshold 被改成了 {vc.get('threshold')}"
