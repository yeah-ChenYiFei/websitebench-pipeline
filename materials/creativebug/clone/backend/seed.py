"""目录种子：把抓取件里抽出的课程元数据灌进业务库。

只灌**元数据**（标题、讲师、分类、难度、时长），不灌课程正文或视频内容。
确定性：同一份 _seed_classes.json 反复执行结果一致（UPSERT，不追加）。
这是 backend/model.json 里 database.proofs 的 deterministic-reset 义务的落地点。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SEED_FILE = Path(__file__).resolve().parent / "catalog-seed.json"


def load_catalog(conn: sqlite3.Connection, seed_path: Path | None = None) -> int:
    path = seed_path or SEED_FILE
    if not path.is_file():
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO cb_class(class_id,title,route,instructor,category,subcategory,"
        " level,duration_minutes,rating,unit_count) VALUES(?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(class_id) DO UPDATE SET title=excluded.title, route=excluded.route,"
        " instructor=excluded.instructor, category=excluded.category,"
        " subcategory=excluded.subcategory, level=excluded.level,"
        " duration_minutes=excluded.duration_minutes, rating=excluded.rating,"
        " unit_count=excluded.unit_count",
        [(r["class_id"], r["title"], r["route"], r.get("instructor"), r.get("category"),
          r.get("subcategory"), r.get("level"), r.get("duration_minutes"),
          r.get("rating"), r.get("unit_count") or 1) for r in rows])
    return len(rows)


def reset_account_state(conn: sqlite3.Connection) -> None:
    """确定性重置：清空账户侧状态，保留目录种子。"""
    for t in ("cb_enrollment", "cb_progress", "cb_watchlist",
              "cb_subscription", "cb_order", "cb_rating", "cb_preference"):
        conn.execute(f"DELETE FROM {t}")
