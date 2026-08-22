"""Freeze a supplied signed-out Coursera Business page as an offline view."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


SANITIZE_DOM = r"""
() => {
  document.querySelectorAll(
    "script, base, iframe, object, embed, meta[http-equiv]"
  ).forEach((element) => element.remove());

  for (const anchor of document.querySelectorAll("a[href]")) {
    const raw = anchor.getAttribute("href");
    if (!raw || raw.startsWith("#")) continue;
    try {
      const url = new URL(raw, "https://www.coursera.org");
      if (url.protocol === "http:" || url.protocol === "https:") {
        if (url.hostname === "www.coursera.org" || url.hostname === "coursera.org") {
          anchor.setAttribute("href", `${url.pathname}${url.search}${url.hash}`);
        } else {
          anchor.setAttribute("href", "#");
        }
      } else {
        anchor.setAttribute("href", "#");
      }
    } catch {
      anchor.setAttribute("href", "#");
    }
  }

  for (const element of document.querySelectorAll("[href]:not(a)")) {
    const raw = element.getAttribute("href");
    if (!raw) continue;
    if (/^(?:data|javascript|vbscript):/i.test(raw)) {
      element.removeAttribute("href");
      continue;
    }
    if (!/^https?:\/\//i.test(raw)) continue;
    try {
      const url = new URL(raw);
      if (url.hostname === "www.coursera.org" || url.hostname === "coursera.org") {
        element.setAttribute("href", `${url.pathname}${url.search}${url.hash}`);
      } else {
        element.removeAttribute("href");
      }
    } catch {
      element.removeAttribute("href");
    }
  }

  for (const style of document.querySelectorAll("style")) {
    style.textContent = style.textContent.replace(/\/\*[\s\S]*?\*\//g, "");
  }

  for (const form of document.querySelectorAll("form")) {
    const action = form.getAttribute("action") || "/search";
    try {
      const url = new URL(action, "https://www.coursera.org");
      form.setAttribute("action", url.hostname.endsWith("coursera.org") ? url.pathname : "/search");
    } catch {
      form.setAttribute("action", "/search");
    }
    form.setAttribute("method", "get");
  }

  const networkAttributes = new Set([
    "src", "srcset", "poster", "action", "formaction", "ping"
  ]);
  for (const element of document.querySelectorAll("*")) {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on")) {
        element.removeAttribute(attribute.name);
      } else if (
        networkAttributes.has(name) &&
        /https?:\/\//i.test(attribute.value)
      ) {
        element.removeAttribute(attribute.name);
      } else if (
        name !== "href" &&
        /https?:\/\//i.test(attribute.value)
      ) {
        element.removeAttribute(attribute.name);
      }
    }
  }

  const comments = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
  const removable = [];
  while (comments.nextNode()) removable.push(comments.currentNode);
  removable.forEach((comment) => comment.remove());

  document.documentElement.lang = "en";
  document.documentElement.dataset.websitebenchSnapshot = "business-2026-08-19-233413";
  document.body.classList.add("source-business-snapshot-page");
  const businessHeading = [...document.querySelectorAll("h1")].find(
    (heading) => heading.textContent.trim() === "Business"
  );
  let shell = businessHeading?.parentElement;
  while (shell) {
    if (Math.abs(shell.getBoundingClientRect().width - 1344) <= 2) {
      shell.dataset.businessShell = "";
      break;
    }
    shell = shell.parentElement;
  }
  return document.documentElement.outerHTML;
}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport={"width": 1692, "height": 979})
        context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.url.startswith(("http://", "https://"))
            else route.continue_(),
        )
        page = context.new_page()
        page.goto(args.source.resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(500)
        html = page.evaluate(SANITIZE_DOM)
        context.close()
        browser.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(f"<!doctype html>\n{html}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
