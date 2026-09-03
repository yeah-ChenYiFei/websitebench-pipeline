# -*- coding: utf-8 -*-
"""class_id 的参照完整性（独立评审 2026-08-30 P1-1）。

存在的理由：enroll / progress / watchlist 曾把请求体里的 class_id 直接写库。
后果实测：
- enroll 缺 class_id → 200「报名成功」，而 INSERT OR IGNORE 一行没写；
- enroll / watchlist 用不存在的 class_id → 200 并写入幽灵行；
- progress 用不存在的 class_id → 200 且 completed=true —— 幽灵结业证书的入口；
- progress 缺 class_id → IntegrityError 冒成 500。
"""
from __future__ import annotations

import itertools

import pytest
from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"
GHOST = "no-such-class-xyz"


def signed_in(server) -> Client:
    c = Client(server)
    e = f"refint-creativebug-{next(_seq)}@clone.test"
    c.post("/api/auth/register/start", {"email": e, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(e)})
    assert c.get("/api/session")[1]["authenticated"] is True
    return c


@pytest.mark.parametrize("endpoint", ["/api/enroll", "/api/progress", "/api/watchlist"])
def test_missing_class_id_is_rejected(server, endpoint):
    c = signed_in(server)
    code, body = c.post(endpoint, {"unit_id": "u1", "watched": 1})
    assert code == 400, f"{endpoint} 缺 class_id 时回了 {code}: {body}"


@pytest.mark.parametrize("endpoint", ["/api/enroll", "/api/progress", "/api/watchlist"])
def test_unknown_class_id_is_rejected(server, endpoint):
    c = signed_in(server)
    code, body = c.post(endpoint, {"class_id": GHOST, "unit_id": "u1", "watched": 1})
    assert code == 404, f"{endpoint} 用幽灵 class_id 时回了 {code}: {body}"


def test_ghost_class_never_reaches_myclasses(server):
    c = signed_in(server)
    for ep in ("/api/enroll", "/api/progress", "/api/watchlist"):
        c.post(ep, {"class_id": GHOST, "unit_id": "u1", "watched": 1})
    rows = c.get("/api/myclasses")[1]["classes"]
    assert not [r for r in rows if r["class_id"] == GHOST], "幽灵课进了 myclasses"
    assert all(r.get("title") for r in rows), f"出现无标题的脏卡片: {rows[:2]}"


def test_ghost_class_cannot_complete_or_certify(server):
    """幽灵课不得被判定完成，更不得签发证书。"""
    c = signed_in(server)
    assert c.post("/api/progress", {"class_id": GHOST, "unit_id": "u1", "watched": 1})[0] == 404
    assert c.post("/api/certificate", {"class_id": GHOST})[0] in (404, 409)


def test_real_class_still_works(server):
    """校验不能误伤正常路径。"""
    c = signed_in(server)
    cid = c.get("/api/search?q=&level=beginner")[1]["results"][0]["class_id"]
    assert c.post("/api/enroll", {"class_id": cid, "track": "audit"})[0] == 200
    assert c.post("/api/progress", {"class_id": cid, "unit_id": "unit-1", "watched": 1})[0] == 200
    assert c.post("/api/watchlist", {"class_id": cid})[0] == 200
