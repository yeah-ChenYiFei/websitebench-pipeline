# -*- coding: utf-8 -*-
"""评分的服务端校验。

存在的理由：/api/rating 曾经直接 int(stars) 入库，没有任何范围校验 ——
stars=99 会被欣然接受并参与课程评分聚合；浏览器审计发现它时，接口层测试是全绿的：它们只发合法的 1..5。
"""
from __future__ import annotations

import itertools

from conftest import Client, mailpit_code

_seq = itertools.count()
PW = "Correct-Horse-9"


def signed_in(server):
    c = Client(server)
    e = f"rating-creativebug-{next(_seq)}@clone.test"
    c.post("/api/auth/register/start", {"email": e, "password": PW})
    c.post("/api/auth/register/verify", {"code": mailpit_code(e)})
    return c


def enrolled(server):
    c = signed_in(server)
    cls = c.get("/api/search?q=&level=beginner")[1]["results"][0]
    assert c.post("/api/enroll", {"class_id": cls["class_id"], "track": "audit"})[0] == 200
    return c, cls["class_id"]


def test_valid_rating_is_saved(server):
    c, cid = enrolled(server)
    code, body = c.post("/api/rating", {"class_id": cid, "stars": 4, "review": "nice"})
    assert code == 200, body
    assert body["stars"] == 4


def test_out_of_range_stars_are_rejected(server):
    c, cid = enrolled(server)
    for bad in (0, 6, 99, -3):
        assert c.post("/api/rating", {"class_id": cid, "stars": bad})[0] == 400, bad


def test_non_numeric_stars_are_rejected(server):
    c, cid = enrolled(server)
    for bad in ("five", None, [], {}):
        assert c.post("/api/rating", {"class_id": cid, "stars": bad})[0] == 400, bad


def test_unknown_class_cannot_be_rated(server):
    c, _ = enrolled(server)
    assert c.post("/api/rating", {"class_id": "no-such-class", "stars": 5})[0] == 404


def test_rating_does_not_require_enrollment(server):
    """不加"必须已报名"这条前置：源站无证据支持，且它会改掉已声明旅程的语义。"""
    c = signed_in(server)
    cid = c.get("/api/search?q=&level=beginner")[1]["results"][0]["class_id"]
    assert c.post("/api/rating", {"class_id": cid, "stars": 5})[0] == 200


def test_rating_requires_authentication(server):
    anon = Client(server)
    cid = anon.get("/api/search?q=&level=beginner")[1]["results"][0]["class_id"]
    assert anon.post("/api/rating", {"class_id": cid, "stars": 5})[0] == 401
