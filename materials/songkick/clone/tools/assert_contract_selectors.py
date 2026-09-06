#!/usr/bin/env python3
"""Fail closed when any frozen recipe selector resolves to zero elements.

The registered Pipeline ``verify`` emits observations only for the visual
checkpoint slice; the control/link/external/component/capability/media recipes
produce no observation and therefore can never produce a finding.  A control
that is missing, mis-rendered or refused by the binder is invisible to a
"clean" diagnostic.  This site-local guard closes that gap by resolving every
recipe selector against the running clone.

usage: assert_contract_selectors.py BASE_URL [--out REPORT.json]
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SITE_ROOT = Path(__file__).resolve().parents[2]
CLONE_ROOT = SITE_ROOT / "clone"


def _load_recipes() -> list[dict[str, Any]]:
    out = []
    for path in sorted((SITE_ROOT / "scope" / "recipes").glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"unreadable recipe {path}: {error}")
    return out


def _session_spec() -> dict[str, Any]:
    verify = json.loads((SITE_ROOT / "scope" / "verify.json").read_text(encoding="utf-8"))
    return dict(verify.get("session") or {})


def _open_session(page, base_url: str, spec: dict[str, Any]) -> bool:
    """Establish the registered loopback verifier session inside the page's own context.

    The seam is driven from the page (not an API request context) so the resulting
    cookie is unambiguously the one the subsequent navigations and fetches will use.
    """
    token = os.environ.get(spec.get("token_env", "WEBSITEBENCH_FIXTURE_TOKEN"), "")
    if not token or not spec.get("post"):
        return False
    headers = {k: v.replace("{{token}}", token) for k, v in (spec.get("headers") or {}).items()}
    headers.setdefault("content-type", "application/json")
    try:
        page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=30000)
        result = page.evaluate(
            "async ({path, headers}) => {"
            "  const response = await fetch(path, {method: 'POST', headers, body: '{}'});"
            "  if (!response.ok) return {ok: false, status: response.status};"
            "  const session = await (await fetch('/api/auth/session')).json();"
            "  return {ok: Boolean(session.authenticated), status: response.status};"
            "}",
            {"path": spec["post"], "headers": headers},
        )
        return bool(result.get("ok"))
    except Exception:
        return False


def _routes() -> dict[str, str]:
    verify = json.loads((SITE_ROOT / "scope" / "verify.json").read_text(encoding="utf-8"))
    return dict(verify.get("routes") or {})


def _checkpoint_route(checkpoint_id: str, routes: dict[str, str]) -> str | None:
    """Map 'state:<route>:<state>' / 'route:<route>' onto a route path."""
    parts = str(checkpoint_id).split(":")
    if len(parts) >= 2 and parts[0] in {"state", "route"}:
        return routes.get(parts[1])
    return None


def _state_key(
    checkpoint_id: str,
    states: dict[str, Any],
    ledger: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Resolve a checkpoint id onto a verify.json states key.

    'state:<route>:<state>' is usually '<route>.<state>', but some checkpoints use a
    logical group name ('state:global-search:...') or the auth prefix ('auth:<state>'),
    so fall back to a suffix match on the state name.  A suffix shared by several
    states is left unresolved rather than guessed; such recipes are reported as
    ambiguous instead of being silently counted either way.
    """
    entry = (ledger or {}).get(str(checkpoint_id)) or {}
    declared = f"{entry.get('route_id')}.{entry.get('state')}"
    if declared in states:
        return declared
    parts = str(checkpoint_id).split(":")
    if len(parts) == 3 and parts[0] == "state":
        direct = f"{parts[1]}.{parts[2]}"
        if direct in states:
            return direct
        name = parts[2]
    elif len(parts) == 2 and parts[0] == "auth":
        name = parts[1]
    else:
        return None
    matches = [key for key in states if key.split(".", 1)[-1] == name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1 and len(parts) >= 2:
        # disambiguate with the checkpoint's own route segment before giving up
        preferred = [key for key in matches if key.split(".", 1)[0] == parts[1]]
        if len(preferred) == 1:
            return preferred[0]
    return None


def _checkpoint_ledger() -> dict[str, dict[str, Any]]:
    """checkpoint_id -> its declared route_id / state / clone_path."""
    data = json.loads((SITE_ROOT / "scope" / "checkpoints.json").read_text(encoding="utf-8"))
    return {
        str(c.get("id")): c
        for c in data.get("checkpoints", [])
        if isinstance(c, dict) and c.get("id")
    }


def _states() -> dict[str, Any]:
    verify = json.loads((SITE_ROOT / "scope" / "verify.json").read_text(encoding="utf-8"))
    return dict(verify.get("states") or {})


def _drive(context, page, base_url: str, path: str, steps: list[dict[str, Any]]) -> list[Any]:
    """Replay the registered non-authenticated steps for one interaction state.

    A click may legitimately open a new tab (the ticket boundary keeps the source's
    ``target=_blank`` behaviour), so any popup is returned alongside the origin page
    and the selector is resolved against whichever surface holds it.
    """
    page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=45000)
    surfaces = [page]
    for step in steps:
        if "goto" in step:
            page.goto(f"{base_url}{step['goto']}", wait_until="networkidle", timeout=45000)
        elif "click" in step:
            try:
                with context.expect_page(timeout=4000) as popup:
                    page.click(step["click"], timeout=15000)
                opened = popup.value
                opened.wait_for_load_state("networkidle", timeout=20000)
                surfaces.append(opened)
            except Exception:
                # no popup: the click stayed on the same surface
                page.wait_for_timeout(400)
        elif "fill" in step:
            page.fill(step["fill"], step.get("value", ""))
            page.wait_for_timeout(200)
        elif "eval" in step:
            page.evaluate(step["eval"])
            page.wait_for_timeout(300)
    page.wait_for_timeout(200)
    return surfaces


def _browser_env() -> dict[str, str]:
    environment = os.environ.copy()
    dependency_root = Path.home() / "chromium-libs"
    libraries = dependency_root / "usr" / "lib" / "x86_64-linux-gnu"
    fonts = dependency_root / "etc" / "fonts" / "fonts.conf"
    if libraries.is_dir():
        environment["LD_LIBRARY_PATH"] = str(libraries)
    if fonts.is_file():
        environment["FONTCONFIG_FILE"] = str(fonts)
    return environment


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(f"usage: {Path(argv[0]).name} BASE_URL [--out REPORT.json]", file=sys.stderr)
        return 2
    base_url = argv[1].rstrip("/")
    out_path = None
    if "--out" in argv:
        out_path = Path(argv[argv.index("--out") + 1])

    from playwright.sync_api import sync_playwright

    routes = _routes()
    states = _states()
    ledger = _checkpoint_ledger()
    recipes = [r for r in _load_recipes() if r.get("selector")]
    by_state: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    unmapped: list[dict[str, Any]] = []
    needs_session: list[dict[str, Any]] = []
    for recipe in recipes:
        checkpoint = recipe.get("checkpoint_id", "")
        path = _checkpoint_route(checkpoint, routes)
        if path is None:
            entry = ledger.get(checkpoint) or {}
            path = routes.get(str(entry.get("route_id"))) or entry.get("clone_path")
        if path is None:
            resolved = _state_key(checkpoint, states, ledger)
            if resolved:
                path = routes.get(resolved.split(".", 1)[0])
        if path is None:
            unmapped.append(recipe)
            continue
        key = _state_key(checkpoint, states, ledger)
        by_state.setdefault((path, key), []).append(recipe)

    unresolved: list[dict[str, Any]] = []
    checked = 0
    args = [
        "--disable-partial-raster",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
        "--proxy-server=http://127.0.0.1:9",
        "--proxy-bypass-list=localhost;127.0.0.1;[::1]",
        "--disable-webrtc",
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=args, env=_browser_env())
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
            locale="en-US",
            timezone_id="America/Toronto",
        )
        session_spec = _session_spec()
        page = context.new_page()
        for (path, key), group in sorted(by_state.items(), key=lambda item: (item[0][0], item[0][1] or "")):
            declared = states.get(key) if key else None
            steps = declared if isinstance(declared, list) else (declared or {}).get("steps") if isinstance(declared, dict) else None
            account = declared.get("session") if isinstance(declared, dict) else None
            # Re-establish per state group: an earlier state (logout, relogin) may have
            # ended the session, so a cached "already opened" flag would be wrong.
            opened = _open_session(page, base_url, session_spec) if account else True
            if account and not opened:
                for recipe in group:
                    needs_session.append(recipe)
                continue
            surfaces = [page]
            try:
                if steps:
                    surfaces = _drive(context, page, base_url, path, steps)
                else:
                    page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=45000)
                    page.wait_for_timeout(150)
            except Exception as error:  # a state that cannot be driven is reported, not silently passed
                for recipe in group:
                    unresolved.append({
                        "subject_id": recipe.get("subject_id"), "kind": recipe.get("kind"),
                        "checkpoint_id": recipe.get("checkpoint_id"), "selector": recipe["selector"],
                        "route_path": path, "matches": None,
                        "state_error": f"{type(error).__name__}: {error}"[:200]})
                checked += len(group)
                continue
            selectors = [r["selector"] for r in group]
            counts = [0] * len(selectors)
            for surface in surfaces:
                try:
                    found = surface.evaluate(
                        "selectors => selectors.map(s => { try { return document.querySelectorAll(s).length; }"
                        " catch (error) { return -1; } })",
                        selectors,
                    )
                except Exception:
                    continue
                counts = [max(a, b) for a, b in zip(counts, found)]
            for surface in surfaces[1:]:
                try:
                    surface.close()
                except Exception:
                    pass
            for recipe, count in zip(group, counts):
                checked += 1
                if count < 1:
                    unresolved.append(
                        {
                            "subject_id": recipe.get("subject_id"),
                            "kind": recipe.get("kind"),
                            "checkpoint_id": recipe.get("checkpoint_id"),
                            "selector": recipe["selector"],
                            "route_path": path,
                            "matches": count,
                        }
                    )
        context.close()
        browser.close()

    skipped = len(unmapped) + len(needs_session)
    result = {
        "ok": not unresolved and skipped == 0,
        "base_url": base_url,
        "selector_recipes_total": len(recipes),
        "selector_recipes_checked": checked,
        "selector_recipes_ambiguous_or_unmapped": len(unmapped),
        "ambiguous_or_unmapped_subjects": sorted({str(r.get("subject_id")) for r in unmapped}),
        "selector_recipes_needing_authenticated_session": len(needs_session),
        "needing_session_subjects": sorted({str(r.get("subject_id")) for r in needs_session}),
        "unresolved_count": len(unresolved),
        "unresolved_by_kind": dict(Counter(u["kind"] for u in unresolved)),
        "unresolved": unresolved,
        "errors": (
            ([f"{len(unresolved)} recipe selector(s) resolve to zero elements"] if unresolved else [])
            + ([f"{len(unmapped)} recipe(s) could not be mapped to a route/state and were never observed"] if unmapped else [])
            + ([f"{len(needs_session)} recipe(s) needed an authenticated session that could not be opened"] if needs_session else [])
        ),
        "observed": checked - skipped,
        "skipped": skipped,
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if out_path:
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
