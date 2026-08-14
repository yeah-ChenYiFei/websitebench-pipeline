#!/usr/bin/env python3
"""Pinned Browser Use 0.12.6 deterministic-CDP adapter.

This program is executed only by the isolated Browser Use interpreter.  It
accepts a closed neutral-DSL JSON document, connects to an already-running
loopback Chromium CDP endpoint, and returns terminal observations.  It exposes
no natural-language agent, arbitrary script, cloud, profile, tunnel, MCP, or
cookie import/export command surface.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from browser_use import BrowserSession


_ACTION_SCRIPT = r"""(request) => {
  const norm = value => String(value ?? '').replace(/\s+/g, ' ').trim();
  const roleOf = el => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'button') return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      return 'textbox';
    }
    return explicit || '';
  };
  const nameOf = el => norm(el.getAttribute('aria-label') || el.value || el.innerText || el.textContent);
  const nodesFor = selector => {
    if (!selector) return [];
    if (selector.css) return Array.from(document.querySelectorAll(selector.css));
    if (selector.test_id) return Array.from(document.querySelectorAll('[data-testid]')).filter(el => el.getAttribute('data-testid') === selector.test_id);
    if (selector.text) return Array.from(document.querySelectorAll('body *')).filter(el => norm(el.textContent) === norm(selector.text));
    if (selector.label) {
      const labels = Array.from(document.querySelectorAll('label')).filter(el => norm(el.textContent) === norm(selector.label));
      return labels.flatMap(label => {
        const id = label.getAttribute('for');
        const target = id ? document.getElementById(id) : label.querySelector('input,textarea,select,button');
        return target ? [target] : [];
      });
    }
    if (selector.role) return Array.from(document.querySelectorAll('body *')).filter(el => roleOf(el) === selector.role && (selector.name === undefined || nameOf(el) === norm(selector.name)));
    return [];
  };
  const nodes = nodesFor(request.selector || {});
  const index = Number((request.selector || {}).nth || 0);
  const el = nodes[index];
  if (!el) return {ok: false, error: 'selector did not resolve'};
  if (request.op === 'click') el.click();
  else if (request.op === 'fill' || request.op === 'type') {
    el.focus();
    if (request.op === 'fill') el.value = '';
    el.value = String(el.value || '') + String(request.value ?? '');
    el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: String(request.value ?? '')}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  } else if (request.op === 'select') {
    el.value = String(request.value ?? '');
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  } else if (request.op === 'press') {
    el.focus();
  } else if (request.op === 'upload') {
    el.setAttribute('data-websitebench-upload-target', request.marker);
  }
  return {ok: true};
}"""

_WAIT_SCRIPT = r"""(request) => {
  const selector = request.selector || {};
  let nodes = [];
  if (selector.css) nodes = Array.from(document.querySelectorAll(selector.css));
  else if (selector.test_id) nodes = Array.from(document.querySelectorAll('[data-testid]')).filter(el => el.getAttribute('data-testid') === selector.test_id);
  else if (selector.text) nodes = Array.from(document.querySelectorAll('body *')).filter(el => String(el.textContent || '').replace(/\s+/g, ' ').trim() === String(selector.text).replace(/\s+/g, ' ').trim());
  const el = nodes[Number(selector.nth || 0)];
  const visible = !!el && !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
  const attached = !!el;
  const matched = request.state === 'hidden' ? !visible : request.state === 'detached' ? !attached : request.state === 'attached' ? attached : visible;
  return {matched};
}"""

_API_SCRIPT = r"""async (request) => {
  const headers = {...(request.headers || {})};
  let body = request.body;
  if (body !== undefined && body !== null && typeof body === 'object') {
    body = JSON.stringify(body);
    if (!Object.keys(headers).some(name => name.toLowerCase() === 'content-type')) headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(request.url, {method: request.method || 'GET', headers, body: ['GET', 'HEAD'].includes(request.method || 'GET') ? undefined : body, redirect: 'manual'});
  const bytes = new Uint8Array(await response.arrayBuffer());
  const text = new TextDecoder().decode(bytes);
  let value = null;
  try { value = JSON.parse(text); } catch (_) {}
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(item => item.toString(16).padStart(2, '0')).join('');
  return {status: response.status, json: value, sha256: digest};
}"""

_OBSERVE_SCRIPT = r"""(request) => {
  const norm = value => String(value ?? '').replace(/\s+/g, ' ').trim();
  const roleOf = el => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'button') return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      return 'textbox';
    }
    return '';
  };
  const nameOf = el => norm(el.getAttribute('aria-label') || el.value || el.innerText || el.textContent);
  const selector = request.selector || {};
  let nodes = [];
  if (selector.css) nodes = Array.from(document.querySelectorAll(selector.css));
  else if (selector.test_id) nodes = Array.from(document.querySelectorAll('[data-testid]')).filter(el => el.getAttribute('data-testid') === selector.test_id);
  else if (selector.text) nodes = Array.from(document.querySelectorAll('body *')).filter(el => norm(el.textContent) === norm(selector.text));
  else if (selector.label) {
    const labels = Array.from(document.querySelectorAll('label')).filter(el => norm(el.textContent) === norm(selector.label));
    nodes = labels.flatMap(label => { const id = label.getAttribute('for'); const target = id ? document.getElementById(id) : label.querySelector('input,textarea,select,button'); return target ? [target] : []; });
  } else if (selector.role) nodes = Array.from(document.querySelectorAll('body *')).filter(el => roleOf(el) === selector.role && (selector.name === undefined || nameOf(el) === norm(selector.name)));
  const el = nodes[Number(selector.nth || 0)];
  const kind = request.kind;
  let value = null;
  if (kind === 'count') value = nodes.length;
  else if (kind === 'ordered_list' || kind === 'set') value = nodes.map(item => norm(item.innerText || item.textContent));
  else if (!el) throw new Error('observation selector did not resolve');
  else if (kind === 'role') value = roleOf(el);
  else if (kind === 'label') value = nameOf(el);
  else if (kind === 'text') value = norm(el.innerText || el.textContent);
  else if (kind === 'value') value = el.value;
  else if (kind === 'checked') value = !!el.checked;
  else if (kind === 'enabled') value = !el.disabled;
  else if (kind === 'number') value = Number(el.value || el.textContent);
  else if (kind === 'visible') value = !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
  else throw new Error('unsupported observation kind');
  return {value};
}"""


def _safe_target(base_url: str, path: str) -> str:
    target = urllib.parse.urljoin(base_url.rstrip("/") + "/", path)
    base = urllib.parse.urlsplit(base_url)
    parsed = urllib.parse.urlsplit(target)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise ValueError("navigation escaped the candidate origin")
    return target


def _substitute(value: Any, captures: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        for name, captured in captures.items():
            token = "${" + name + "}"
            if value == token:
                return captured
            value = value.replace(token, str(captured))
        return value
    if isinstance(value, list):
        return [_substitute(item, captures) for item in value]
    if isinstance(value, dict):
        return {str(key): _substitute(item, captures) for key, item in value.items()}
    return value


async def _json_call(page: Any, script: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = await page.evaluate(script, dict(payload))
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("Browser Use CDP adapter returned a non-object")
    return value


async def _wait_ready(page: Any, deadline: float) -> None:
    while time.monotonic() < deadline:
        state = await _json_call(
            page,
            "() => ({state: document.readyState})",
            {},
        )
        if state.get("state") == "complete":
            return
        await asyncio.sleep(0.02)
    raise TimeoutError("page load deadline exceeded")


async def _run(payload: Mapping[str, Any]) -> dict[str, Any]:
    if importlib.metadata.version("browser-use") != "0.12.6":
        raise RuntimeError("Browser Use is not pinned to 0.12.6")
    base_url = str(payload["base_url"])
    deadline = time.monotonic() + float(payload["timeout_sec"])
    session = BrowserSession(
        cdp_url=str(payload["cdp_url"]),
        keep_alive=True,
        allowed_domains=["127.0.0.1", "localhost"],
        enable_default_extensions=False,
        captcha_solver=False,
        highlight_elements=False,
        dom_highlight_elements=False,
        cross_origin_iframes=False,
        minimum_wait_page_load_time=0.0,
        wait_for_network_idle_page_load_time=0.0,
        wait_between_actions=0.0,
    )
    captures: dict[str, Any] = {}
    actors: dict[str, Any] = {}
    upload_sequence = 0
    try:
        await session.start()
        page = await session.new_page(base_url)
        await page.set_viewport_size(
            int(payload["viewport"]["width"]), int(payload["viewport"]["height"])
        )
        actors["primary"] = page
        current_actor = "primary"
        for declared in payload["actions"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("action deadline exceeded")
            action = _substitute(declared, captures)
            op = str(action["op"])
            page = actors[current_actor]
            if op == "goto":
                await page.goto(_safe_target(base_url, str(action.get("path", "/"))))
                await _wait_ready(page, deadline)
            elif op == "reload":
                await page.reload()
                await _wait_ready(page, deadline)
            elif op in {"click", "fill", "type", "select", "press"}:
                result = await _json_call(page, _ACTION_SCRIPT, action)
                if not result.get("ok"):
                    raise RuntimeError(str(result.get("error") or "action failed"))
                if op == "press":
                    await page.press(str(action.get("value", "")))
            elif op == "upload":
                upload_sequence += 1
                marker = f"upload-{upload_sequence}-{current_actor}"
                result = await _json_call(
                    page, _ACTION_SCRIPT, {**action, "marker": marker}
                )
                if not result.get("ok"):
                    raise RuntimeError(str(result.get("error") or "upload failed"))
                elements = await page.get_elements_by_css_selector(
                    f'[data-websitebench-upload-target="{marker}"]'
                )
                if len(elements) != 1:
                    raise RuntimeError("upload selector did not resolve exactly once")
                await page._client.send.DOM.setFileInputFiles(
                    {
                        "files": [str(action["fixture"])],
                        "backendNodeId": elements[0]._backend_node_id,
                    },
                    session_id=await page.session_id,
                )
            elif op == "wait_for":
                wait_deadline = min(
                    deadline,
                    time.monotonic() + int(action.get("timeout_ms", 30_000)) / 1000,
                )
                while True:
                    result = await _json_call(
                        page,
                        _WAIT_SCRIPT,
                        {**action, "state": action.get("state", "visible")},
                    )
                    if result.get("matched"):
                        break
                    if time.monotonic() >= wait_deadline:
                        raise TimeoutError("wait_for deadline exceeded")
                    await asyncio.sleep(0.02)
            elif op in {"api", "parallel_api"}:
                requests = action.get("requests") if op == "parallel_api" else [action]
                for request in requests:
                    item = dict(request)
                    item["url"] = _safe_target(base_url, str(item.get("path", "/")))
                    result = await _json_call(page, _API_SCRIPT, item)
                    capture_as = item.get("capture_as")
                    if isinstance(capture_as, str):
                        captures[capture_as] = result
            elif op == "new_actor":
                name = str(action["actor"])
                if name in actors:
                    raise RuntimeError("duplicate actor")
                actors[name] = await session.new_page(base_url)
                await actors[name].set_viewport_size(
                    int(payload["viewport"]["width"]),
                    int(payload["viewport"]["height"]),
                )
            elif op == "use_actor":
                name = str(action["actor"])
                if name not in actors:
                    raise RuntimeError("unknown actor")
                current_actor = name
            elif op == "mailbox_code":
                name = str(action["capture_as"])
                values = payload.get("mailbox_values", {})
                if str(action.get("value")) not in values:
                    raise RuntimeError("mailbox value unavailable")
                captures[name] = values[str(action["value"])]
            elif op == "restart":
                controller = payload.get("restart_controller")
                if not isinstance(controller, dict):
                    raise RuntimeError("restart controller unavailable")
                request = urllib.request.Request(
                    str(controller["url"]),
                    method="POST",
                    headers={
                        "X-WebsiteBench-Restart": str(controller["capability"])
                    },
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    restarted = json.loads(response.read(4096))
                if response.status != 200 or restarted != {"status": "ok"}:
                    raise RuntimeError("candidate restart failed")
            else:
                raise RuntimeError(f"operation outside closed adapter: {op}")

        page = actors[current_actor]
        actual: dict[str, Any] = {}
        for observation in payload["observations"]:
            kind = str(observation["kind"])
            capture_as = observation.get("capture_as")
            if kind == "url":
                actual[str(observation["id"])] = await page.get_url()
            elif isinstance(capture_as, str):
                captured = captures[capture_as]
                if kind == "api_status":
                    value = captured["status"]
                elif kind == "download_sha256":
                    value = captured["sha256"]
                else:
                    value = captured["json"]
                    pointer = str(observation.get("json_pointer", ""))
                    for raw in pointer.lstrip("/").split("/") if pointer else []:
                        key = raw.replace("~1", "/").replace("~0", "~")
                        value = value[int(key)] if isinstance(value, list) else value[key]
                actual[str(observation["id"])] = value
            else:
                result = await _json_call(page, _OBSERVE_SCRIPT, observation)
                actual[str(observation["id"])] = result["value"]
        return {"status": "ok", "actual": actual}
    finally:
        await session.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = asyncio.run(_run(payload))
        return_code = 0
    except Exception as exc:
        result = {"status": "error", "error": f"{type(exc).__name__}:{exc}"}
        return_code = 2
    encoded = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
