"""Record human browser interactions from an explicitly approved CDP target.

The recorder deliberately owns neither the browser process nor its profile.  It
attaches to a Chrome DevTools Protocol endpoint supplied by the caller, injects
passive DOM listeners, and retains a redacted structural interaction ledger.
This keeps reusable capture separate from task scoring, agent harnesses,
network interception, and browser provisioning.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


ACTION_SCHEMA_VERSION = "websitebench.browser-trajectory.action.v1"
SESSION_SCHEMA_VERSION = "websitebench.browser-trajectory.session.v1"
_BINDING_NAME = "__websitebenchTrajectory"
_EVENT_TYPES = frozenset(
    {"click", "keydown", "keyup", "input", "scroll", "change", "submit", "pageLoad"}
)
_SAFE_KEYS = frozenset(
    {
        "Alt",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "Backspace",
        "Delete",
        "End",
        "Enter",
        "Escape",
        "Home",
        "PageDown",
        "PageUp",
        "Tab",
    }
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|cookie|authorization|otp|cvv|cvc)"
    r"\b\s*[:=]\s*[^\s,;]+"
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


class BrowserTrajectoryError(RuntimeError):
    """Raised when a recorder cannot safely start or write its artifacts."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any, *, limit: int) -> str:
    """Return bounded structural text without common secret or payment values."""

    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = _EMAIL.sub("[REDACTED:email]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", text)
    text = _CARD.sub("[REDACTED:payment]", text)
    return " ".join(text.split())[:limit]


def _origin(value: str) -> str | None:
    """Normalize an HTTP(S) origin without retaining URL credentials."""

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not hostname:
        return None
    host = hostname.casefold()
    default_port = 80 if scheme == "http" else 443
    port_part = f":{port}" if port is not None and port != default_port else ""
    return f"{scheme}://{host}{port_part}"


def safe_url(value: Any) -> str | None:
    """Keep an origin and route while dropping query, fragment, and credentials."""

    if not isinstance(value, str) or not value:
        return None
    origin = _origin(value)
    if origin is None:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    path = _safe_text(parsed.path or "/", limit=2000)
    if not path.startswith("/"):
        path = "/" + path
    return urlunsplit(
        (parsed.scheme.casefold(), origin.split("://", 1)[1], path, "", "")
    )


def _number(value: Any, *, limit: int = 1_000_000) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value) or abs(value) > limit:
        return None
    return int(value)


def _target(raw: Any) -> dict[str, str]:
    """Retain stable element structure, never element text or input values."""

    if not isinstance(raw, dict):
        return {}
    fields = {
        "tag": raw.get("tagName"),
        "id": raw.get("id"),
        "name": raw.get("name"),
        "input_type": raw.get("type"),
        "role": raw.get("role"),
        "class_name": raw.get("className"),
        "xpath": raw.get("xpath"),
    }
    result: dict[str, str] = {}
    for key, value in fields.items():
        text = _safe_text(value, limit=512 if key == "xpath" else 160)
        if text:
            result[key] = text
    return result


def _safe_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value in _SAFE_KEYS:
        return value
    # Individual printable keys can reconstruct a password or other private
    # input.  Preserve only the fact that a character key was used.
    return "character"


ACTION_CAPTURE_SCRIPT = f"""
(() => {{
  "use strict";
  if (window.__websitebenchTrajectoryCaptureInstalled) return;
  window.__websitebenchTrajectoryCaptureInstalled = true;

  const throttleMs = 500;
  const lastSent = Object.create(null);

  function xpath(element) {{
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return "";
    const parts = [];
    for (let current = element; current && current.nodeType === Node.ELEMENT_NODE; current = current.parentElement) {{
      let index = 1;
      for (let sibling = current.previousElementSibling; sibling; sibling = sibling.previousElementSibling) {{
        if (sibling.tagName === current.tagName) index += 1;
      }}
      parts.unshift(`${{current.tagName.toLowerCase()}}[${{index}}]`);
    }}
    return "/" + parts.join("/");
  }}

  function className(element) {{
    if (!element || element.className === undefined) return "";
    if (typeof element.className === "string") return element.className;
    if (element.className && typeof element.className.baseVal === "string") return element.className.baseVal;
    return "";
  }}

  function targetFor(element) {{
    return {{
      tagName: element && element.tagName || "",
      id: element && element.id || "",
      name: element && element.getAttribute && element.getAttribute("name") || "",
      type: element && element.getAttribute && element.getAttribute("type") || "",
      role: element && element.getAttribute && element.getAttribute("role") || "",
      className: className(element),
      xpath: xpath(element),
    }};
  }}

  function emit(payload) {{
    try {{
      if (typeof window.{_BINDING_NAME} === "function") {{
        window.{_BINDING_NAME}(JSON.stringify(payload));
      }}
    }} catch (_) {{}}
  }}

  function send(type, event) {{
    if (type === "scroll" || type === "input") {{
      const now = Date.now();
      if (lastSent[type] && now - lastSent[type] < throttleMs) return;
      lastSent[type] = now;
    }}
    const payload = {{
      type,
      timestamp: Date.now(),
      url: location.href,
      target: targetFor(event.target),
    }};
    if (event.clientX !== undefined) {{
      payload.x = event.clientX;
      payload.y = event.clientY;
    }}
    if (event.key) {{
      payload.key = event.key.length === 1 ? "character" : event.key.slice(0, 64);
    }}
    if (type === "scroll") {{
      payload.scrollX = window.scrollX;
      payload.scrollY = window.scrollY;
    }}
    emit(payload);
  }}

  ["click", "keydown", "keyup", "input", "scroll", "change", "submit"].forEach((type) => {{
    document.addEventListener(type, (event) => send(type, event), true);
  }});

  function pageLoad() {{
    emit({{type: "pageLoad", timestamp: Date.now(), url: location.href}});
  }}
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", pageLoad, {{once: true}});
  }} else {{
    setTimeout(pageLoad, 0);
  }}
}})();
"""


@dataclass(frozen=True)
class RecorderConfig:
    """Capture settings for one append-free, origin-bounded session."""

    output_dir: Path
    allowed_origins: tuple[str, ...]
    cdp_url: str = "http://127.0.0.1:9222"
    screenshots: bool = False
    screenshot_interval_ms: int = 500

    def __post_init__(self) -> None:
        candidates = {_origin(value) for value in self.allowed_origins}
        if not candidates or None in candidates:
            raise BrowserTrajectoryError(
                "allowed_origins must contain one or more valid HTTP(S) origins"
            )
        if self.screenshot_interval_ms < 0:
            raise BrowserTrajectoryError("screenshot_interval_ms must be non-negative")
        object.__setattr__(
            self,
            "allowed_origins",
            tuple(sorted(value for value in candidates if value is not None)),
        )


class TrajectoryRecorder:
    """Attach to a browser and persist redacted human interaction events."""

    def __init__(self, config: RecorderConfig) -> None:
        self.config = config
        self._actions_path = config.output_dir / "actions.jsonl"
        self._screenshots_dir = config.output_dir / "screenshots"
        self._session_path = config.output_dir / "session.json"
        self._started_at = _utc_now()
        self._action_count = 0
        self._screenshot_count = 0
        self._dropped_event_count = 0
        self._last_screenshot_at = 0.0
        self._running = False
        self._finished = False
        self._playwright: Any = None
        self._browser: Any = None
        self._contexts: list[Any] = []
        self._prepare_output()

    @property
    def output_dir(self) -> Path:
        return self.config.output_dir

    def _prepare_output(self) -> None:
        output_dir = self.config.output_dir
        if output_dir.exists() and any(output_dir.iterdir()):
            raise BrowserTrajectoryError(
                f"refusing to write into non-empty output directory: {output_dir}"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        self._screenshots_dir.mkdir(exist_ok=True)
        self._actions_path.touch(exist_ok=False)
        self._write_session("prepared")

    def _session_document(self, status: str) -> dict[str, Any]:
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "status": status,
            "started_at": self._started_at,
            "finished_at": (
                _utc_now() if status in {"complete", "failed", "stopped"} else None
            ),
            "allowed_origins": list(self.config.allowed_origins),
            "artifacts": {
                "actions": "actions.jsonl",
                "screenshots": "screenshots",
            },
            "capture": {
                "screenshots_enabled": self.config.screenshots,
                "screenshot_interval_ms": self.config.screenshot_interval_ms,
                "event_types": sorted(_EVENT_TYPES),
            },
            "privacy": {
                "input_values": "omitted",
                "element_text": "omitted",
                "url_query_and_fragment": "omitted",
                "browser_credentials": "not-read",
                "network_traffic": "not-captured",
            },
            "counts": {
                "actions": self._action_count,
                "screenshots": self._screenshot_count,
                "dropped_events": self._dropped_event_count,
            },
        }

    def _write_session(self, status: str) -> None:
        temporary = self._session_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._session_document(status), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._session_path)

    def _write_action(self, action: dict[str, Any]) -> None:
        with self._actions_path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(action, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    def _event_for(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        event_type = raw.get("type")
        if not isinstance(event_type, str) or event_type not in _EVENT_TYPES:
            self._dropped_event_count += 1
            return None
        url = safe_url(raw.get("url"))
        if url is None or _origin(url) not in self.config.allowed_origins:
            self._dropped_event_count += 1
            return None
        self._action_count += 1
        timestamp = _number(raw.get("timestamp"), limit=10**15)
        event: dict[str, Any] = {
            "schema_version": ACTION_SCHEMA_VERSION,
            "event_id": f"e{self._action_count:08d}",
            "type": event_type,
            "timestamp_ms": timestamp
            if timestamp is not None
            else int(time.time() * 1000),
            "url": url,
        }
        target = _target(raw.get("target"))
        if target:
            event["target"] = target
        if event_type in {"input", "change"}:
            event["input_value"] = "omitted"
        if event_type in {"click", "scroll"}:
            x, y = _number(raw.get("x")), _number(raw.get("y"))
            if x is not None and y is not None:
                event["pointer"] = {"x": x, "y": y}
        key = _safe_key(raw.get("key"))
        if key is not None:
            event["key"] = key
        if event_type == "scroll":
            scroll_x, scroll_y = (
                _number(raw.get("scrollX")),
                _number(raw.get("scrollY")),
            )
            if scroll_x is not None and scroll_y is not None:
                event["scroll"] = {"x": scroll_x, "y": scroll_y}
        return event

    def _capture_screenshot(self, page: Any, event: dict[str, Any]) -> None:
        if not self.config.screenshots or page is None:
            return
        now = time.monotonic() * 1000
        if now - self._last_screenshot_at < self.config.screenshot_interval_ms:
            return
        self._last_screenshot_at = now
        relative = f"screenshots/{event['event_id']}.png"
        try:
            page.screenshot(path=str(self.output_dir / relative), type="png")
        except Exception:
            return
        event["screenshot"] = relative
        self._screenshot_count += 1

    def _record_payload(self, raw: dict[str, Any], page: Any = None) -> None:
        event = self._event_for(raw)
        if event is None:
            return
        self._capture_screenshot(page, event)
        self._write_action(event)

    def _on_binding(self, source: Any, payload: Any) -> None:
        if not isinstance(payload, str):
            self._dropped_event_count += 1
            return
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError:
            self._dropped_event_count += 1
            return
        if not isinstance(raw, dict):
            self._dropped_event_count += 1
            return
        self._record_payload(raw, getattr(source, "page", None))

    def _attach_page(self, page: Any) -> None:
        try:
            page.evaluate(ACTION_CAPTURE_SCRIPT)
        except Exception:
            # A page can close between context enumeration and evaluation.  The
            # context init script still covers future documents on that page.
            return
        for frame in page.frames:
            try:
                frame.evaluate(ACTION_CAPTURE_SCRIPT)
            except Exception:
                # A cross-origin or concurrently navigating frame must not
                # prevent capture from continuing for the rest of the page.
                continue

    def _attach_context(self, context: Any) -> None:
        context.expose_binding(_BINDING_NAME, self._on_binding)
        context.add_init_script(ACTION_CAPTURE_SCRIPT)
        for page in context.pages:
            self._attach_page(page)
        context.on("page", self._attach_page)
        self._contexts.append(context)

    def start(self) -> None:
        """Connect without taking ownership of the attached browser process."""

        if self._finished:
            raise BrowserTrajectoryError("a finalized recorder cannot be restarted")
        if self._running:
            return
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - declared project dependency
            raise BrowserTrajectoryError(
                "browser trajectory capture requires Playwright"
            ) from exc
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                self.config.cdp_url
            )
            for context in self._browser.contexts:
                self._attach_context(context)
        except PlaywrightError as exc:
            self.close(status="failed")
            raise BrowserTrajectoryError(
                "could not attach to the supplied CDP endpoint"
            ) from exc
        self._running = True
        self._write_session("recording")

    def wait(self, *, duration_seconds: float | None = None) -> None:
        """Dispatch browser events until interrupted, stopped, or duration expires."""

        if not self._running:
            raise BrowserTrajectoryError("start the recorder before waiting")
        deadline = (
            time.monotonic() + duration_seconds
            if duration_seconds is not None
            else None
        )
        while self._running and (deadline is None or time.monotonic() < deadline):
            pages = [page for context in self._contexts for page in context.pages]
            if not pages:
                time.sleep(0.2)
                continue
            try:
                pages[0].wait_for_timeout(200)
            except Exception:
                time.sleep(0.2)

    def close(self, *, status: str = "stopped") -> None:
        """Disconnect and finalize metadata without closing the human browser."""

        if self._finished:
            return
        self._running = False
        try:
            if self._playwright is not None:
                self._playwright.stop()
        finally:
            self._playwright = None
            self._browser = None
            self._finished = True
            self._write_session(status)
