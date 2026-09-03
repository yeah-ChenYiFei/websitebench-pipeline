#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注入式自检：故意破坏产物，确认检查器真的会叫。

"0 issue" 只有在检查器活着的时候才有意义。本脚本对每一类检查各注入一处
已知缺陷，要求 precheck 报出对应的 issue code；报不出来就是检查器死了。
每次注入后立即还原。
"""
from __future__ import annotations

import atexit
import signal
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "materials" / "creativebug"
BACKUP = Path("/tmp/mutation-backup")

_PENDING: list = []


def _restore_all(*_a):
    """把还没撤销的注入还原回去，然后退出。"""
    while _PENDING:
        try:
            _PENDING.pop()()
        except Exception as exc:                 # 还原失败必须说出来
            print(f"!! 还原失败: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(130)


atexit.register(lambda: [f() for f in reversed(_PENDING)])
for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, _restore_all)


def precheck() -> tuple[int, set[str]]:
    """跑 precheck 并取出 by_code。

    precheck 的 stdout 是「一段 JSON + 若干人类可读的 issue 行」，
    对整段做 json.loads 必然抛错。早先把这个异常 pass 掉，于是
    每次注入都返回空集合 —— 解析失败被读成了"没发现问题"，
    正好把这个用来防误判的工具本身变成了误判源。
    这里只解析开头那个 JSON 对象，解析失败就当作错误抛出去，不再吞。
    """
    r = subprocess.run([sys.executable, str(HERE / "precheck.py")],
                       capture_output=True, text=True)
    out = r.stdout or ""
    depth = end = 0
    for i, ch in enumerate(out):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if not end:
        raise RuntimeError(f"precheck 没有输出 JSON:\nstdout={out[:200]}\nstderr={r.stderr[:300]}")
    return r.returncode, set(json.loads(out[:end]).get("by_code", {}))


def mutate(name, apply_fn, undo_fn, expect: str) -> bool:
    # 注入前登记撤销动作：被 SIGTERM/SIGINT 打断时也要还原。
    # 曾经一次 timeout 杀进程发生在注入④与撤销之间，manifest 里留下
    # bytes=1 的假声明，之后所有 precheck 都报 ASSET_MISMATCH。
    _PENDING.append(undo_fn)
    apply_fn()
    try:
        rc, codes = precheck()
        ok = expect in codes
        print(f"  {'PASS' if ok else 'FAIL'}  {name:34s} 期望 {expect:28s} "
              f"实得 {sorted(codes) or '（无）'}")
        return ok
    finally:
        undo_fn()
        if _PENDING and _PENDING[-1] is undo_fn:
            _PENDING.pop()


def main() -> int:
    BACKUP.mkdir(parents=True, exist_ok=True)
    man_path = SITE / "source-assets" / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    a = man["assets"][0]
    rp, sp = SITE / a["runtime_path"], SITE / a["source_path"]

    rc0, codes0 = precheck()
    print(f"基线: 退出码 {rc0}  issue {sorted(codes0) or '（无，符合预期）'}\n")
    if codes0:
        print("!! 基线本身就有 issue，注入测试结果不可信")
        return 2

    results = []

    # ① 字节被改 → ASSET_MISMATCH
    shutil.copy2(rp, BACKUP / "rt.bin")
    results.append(mutate(
        "runtime 副本被篡改", lambda: rp.write_bytes(rp.read_bytes() + b"X"),
        lambda: shutil.copy2(BACKUP / "rt.bin", rp), "ASSET_MISMATCH"))

    # ② 文件丢失 → ASSET_MISSING
    results.append(mutate(
        "runtime 副本缺失", lambda: rp.unlink(),
        lambda: shutil.copy2(BACKUP / "rt.bin", rp), "ASSET_MISSING"))

    # ③ 硬链接 → ASSET_MULTIPLE_HARD_LINKS（§7.3(a) 红线 3）
    def make_link():
        rp.unlink()
        import os
        os.link(sp, rp)
    results.append(mutate(
        "source/runtime 做成硬链接", make_link,
        lambda: (rp.unlink(missing_ok=True), shutil.copy2(BACKUP / "rt.bin", rp)),
        "ASSET_MULTIPLE_HARD_LINKS"))

    # ④ 声明与实测不符 → ASSET_MISMATCH
    def bad_decl():
        m = json.loads(man_path.read_text(encoding="utf-8"))
        m["assets"][0]["bytes"] = 1
        man_path.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    results.append(mutate(
        "清单声明的 bytes 被改错", bad_decl,
        lambda: man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8"),
        "ASSET_MISMATCH"))

    # ⑤ 页面里放回源站绝对地址 → OUTBOUND_ABSOLUTE_URL（§7.5）
    page = SITE / "clone" / "frontend" / "site" / "about" / "index.html"
    shutil.copy2(page, BACKUP / "page.html")
    results.append(mutate(
        "页面残留源站绝对地址",
        lambda: page.write_bytes(page.read_bytes().replace(
            b"</body>", b'<img src="https://www.creativebug.com/pimage/x.jpg"></body>', 1)),
        lambda: shutil.copy2(BACKUP / "page.html", page), "OUTBOUND_ABSOLUTE_URL"))

    # ⑥ 协议相对形式 → 同上（这一类曾整类漏过，由引擎 verify 抓出）
    results.append(mutate(
        "协议相对 //host 形式",
        lambda: page.write_bytes(page.read_bytes().replace(
            b"</body>", b'<img src="//www.creativebug.com/pimage/y.jpg"></body>', 1)),
        lambda: shutil.copy2(BACKUP / "page.html", page), "OUTBOUND_ABSOLUTE_URL"))

    # ⑦ 凭据落进产物 → CREDENTIAL_LEAK（§9 红线 1）
    rules = HERE / "scrub-rules.json"
    needle = json.loads(rules.read_text(encoding="utf-8"))[0]["find"] if rules.is_file() else None
    if needle:
        results.append(mutate(
            "产物里出现凭据串",
            lambda: page.write_bytes(page.read_bytes().replace(
                b"</body>", f'<!-- {needle} -->'.encode() + b"</body>", 1)),
            lambda: shutil.copy2(BACKUP / "page.html", page), "CREDENTIAL_LEAK"))

    rc1, codes1 = precheck()
    print(f"\n还原后: 退出码 {rc1}  issue {sorted(codes1) or '（无）'}")
    ok = all(results) and not codes1 and rc1 == 0
    print(f"\n注入自检: {sum(results)}/{len(results)} 通过，还原干净: {not codes1}")
    print("结论:", "检查器有效" if ok else "!! 检查器存在盲区或未能还原")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
