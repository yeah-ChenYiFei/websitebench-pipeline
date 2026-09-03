#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FAST-CLONE §4.4 落盘前 scrub —— 去凭据与 PII，但保留 DOM 结构。

规则由 tools/scrub-rules.json 驱动（该文件本身 gitignore，不入库）。
去的是"值"，留的是属性名、标签、布局——克隆侧还要照着这个结构实现登录态注入。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "scrub-rules.json"

# 结构性替换：属性名保留，值换占位符
STRUCTURAL = [
    (re.compile(r'(\bdata-email\s*=\s*")[^"]*(")'), r'\1learner@clone.test\2'),
    (re.compile(r'(\bdata-user-id\s*=\s*")[^"]*(")'), r'\1REDACTED-USER-ID\2'),
    # data-id 承载的是真实账号内部 id；此前只挡了 data-user-id，302 个出货页漏了出去。
    (re.compile(r'(\bdata-id\s*=\s*")\d{4,}(")'), r'\g<1>2000001\2'),
    (re.compile(r'(["\']email["\']\s*:\s*")[^"]*(")'), r'\1learner@clone.test\2'),
    (re.compile(r'\b[\w.+-]+@(?:qq|gmail|163|126|outlook|hotmail|foxmail)\.com\b'), 'learner@clone.test'),
    # 会话/令牌类：整条抹掉值
    (re.compile(r'(["\'](?:csrf[_-]?token|session[_-]?id|auth[_-]?token|access[_-]?token|api[_-]?key)["\']\s*:\s*")[^"]*(")', re.I), r'\1REDACTED\2'),
]


def load_rules() -> list[tuple[str, str]]:
    if not RULES.is_file():
        return []
    return [(r["find"], r["replace"]) for r in json.loads(RULES.read_text(encoding="utf-8"))]


def scrub_text(t: str, literals: list[tuple[str, str]]) -> tuple[str, int]:
    n = 0
    for find, repl in literals:
        c = t.count(find)
        if c:
            t = t.replace(find, repl)
            n += c
    for pat, repl in STRUCTURAL:
        t, k = pat.subn(repl, t)
        n += k
    return t, n


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python tools/scrub.py <目录>")
        return 2
    root = Path(argv[1])
    literals = load_rules()
    if not literals:
        print(f"!! 没有 {RULES}，只跑结构性规则。")
        print("   建一份（格式 [{\"find\":\"...\",\"replace\":\"...\"}]），它不入库。")
    total_files = total_hits = 0
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".html", ".htm", ".json", ".txt", ".jsonl"}:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        new, n = scrub_text(t, literals)
        if n:
            p.write_text(new, encoding="utf-8")
            total_files += 1
            total_hits += n
            print(f"  {p.relative_to(root)}: {n} 处")
    print(f"\nscrub 完成：{total_files} 个文件，{total_hits} 处替换")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
