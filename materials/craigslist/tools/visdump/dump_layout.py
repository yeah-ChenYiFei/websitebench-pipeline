"""Visual layout dumper: render a URL in a real browser and dump its block
structure (tag, class, bounding box, visibility, text) as JSON.

Usage:
  python dump_layout.py <url> [--out out.json] [--viewport 1915x989]
  python dump_layout.py <url> --tree   # print a compact indented tree
"""
import argparse
import json
import re
import sys

from playwright.sync_api import sync_playwright


def _visible(el) -> bool:
    try:
        return el.is_visible()
    except Exception:
        return False


def collect(page, root_sel="body", max_nodes=1200):
    """Return layout blocks under root_sel as a list of dicts."""
    blocks = []
    nodes = page.query_selector_all(root_sel + " *")
    for el in nodes[:max_nodes]:
        try:
            tag = el.evaluate("e => e.tagName.toLowerCase()")
        except Exception:
            continue
        cls = ""
        try:
            cls = el.get_attribute("class") or ""
        except Exception:
            pass
        if not cls:
            continue
        # keep only structural classes (skip pure style/utility noise later)
        try:
            box = el.bounding_box()
        except Exception:
            box = None
        if box is None:
            continue
        try:
            text = (el.inner_text() or "").strip()[:60]
        except Exception:
            text = ""
        visible = _visible(el)
        # depth
        depth = 0
        try:
            parent = el.evaluate_handle("e => e.parentElement")
            while parent and depth < 20:
                parent = parent.evaluate_handle("e => e.parentElement")
                depth += 1
        except Exception:
            pass
        blocks.append({
            "tag": tag,
            "class": cls,
            "x": round(box["x"]), "y": round(box["y"]),
            "w": round(box["width"]), "h": round(box["height"]),
            "visible": visible,
            "text": text,
        })
    return blocks


def dedupe(blocks):
    """Drop near-duplicate blocks (same class+pos) and style noise."""
    seen = set()
    out = []
    for b in blocks:
        key = (b["class"], b["x"] // 4, b["y"] // 4, b["w"] // 8, b["h"] // 8)
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def tree_text(blocks, min_w=40, min_h=12):
    """Compact indented tree of significant visible blocks."""
    vis = [b for b in blocks if b["visible"] and b["w"] >= min_w and b["h"] >= min_h]
    # sort top-to-bottom, left-to-right
    vis.sort(key=lambda b: (b["y"], b["x"]))
    lines = []
    for b in vis:
        t = b["text"].replace("\n", " ")[:48]
        cls = b["class"][:60]
        lines.append(
            f'{b["y"]:>5},{b["x"]:>5} {b["w"]:>4}x{b["h"]:<4} '
            f'{b["tag"]:<8} .{cls:<40} {"| " + t if t else ""}'
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out")
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--viewport", default="1915x989")
    ap.add_argument("--selector", default="body")
    ap.add_argument("--shot", help="save screenshot to this path")
    args = ap.parse_args()
    w, h = (int(v) for v in args.viewport.split("x"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(args.url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(600)
        if args.shot:
            page.screenshot(path=args.shot, full_page=True)
        blocks = dedupe(collect(page, args.selector))
        if args.tree:
            print(tree_text(blocks))
        else:
            print(json.dumps(blocks, ensure_ascii=False, indent=1))
        browser.close()


if __name__ == "__main__":
    main()
