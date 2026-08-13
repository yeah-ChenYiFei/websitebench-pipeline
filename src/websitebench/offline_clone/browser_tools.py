"""Declarative, safety-bounded browser exploration for source and clone targets."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from .toolbox import (
    ToolboxError,
    load_json_object,
    origin,
    safe_component,
    safe_text,
    safe_url,
    write_json_atomic,
)


BROWSER_SPEC_SCHEMA = "websitebench.offline-clone.browser-scenario.v1"
_SENSITIVE_SELECTOR = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|cookie|authorization|otp|cvv|cvc|card)"
)


def _selector(value: Any, *, environment: str, field: str) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        selected = value.get(environment, value.get("default"))
        if isinstance(selected, str) and selected:
            return selected
    raise ToolboxError(f"{field} must be a selector string or target selector mapping")


def _route(value: str) -> str:
    parsed = urlsplit(value)
    return parsed.path or "/"


def _approved_origins(spec: dict[str, Any], *, environment: str) -> list[str]:
    values = spec.get("allowed_origins")
    if isinstance(values, dict):
        values = values.get(environment, values.get("default"))
    if not isinstance(values, list) or not values:
        raise ToolboxError(
            "allowed_origins must declare a non-empty target origin list"
        )
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ToolboxError("allowed_origins entries must be strings")
        result.append(origin(value))
    return sorted(set(result))


def _input_value(step: dict[str, Any], *, selector: str) -> str:
    has_literal = "value" in step
    has_environment = "value_env" in step
    if has_literal == has_environment:
        raise ToolboxError("fill requires exactly one of value or value_env")
    if has_environment:
        variable = step["value_env"]
        if not isinstance(variable, str) or not variable:
            raise ToolboxError(
                "value_env must be a non-empty environment variable name"
            )
        value = os.environ.get(variable)
        if value is None:
            raise ToolboxError(f"required environment variable {variable!r} is not set")
        return value
    if _SENSITIVE_SELECTOR.search(selector):
        raise ToolboxError(
            "sensitive browser inputs must use value_env; literals are forbidden"
        )
    value = step["value"]
    if not isinstance(value, (str, int, float, bool)):
        raise ToolboxError("fill literal value must be a scalar")
    return str(value)


def _expectation_passes(actual: Any, expectation: Any) -> bool:
    if expectation is None:
        return True
    if not isinstance(expectation, dict) or len(expectation) != 1:
        raise ToolboxError(
            "observation expect must contain exactly one of equals, contains, "
            "or matches"
        )
    operator, expected = next(iter(expectation.items()))
    if operator == "equals":
        return actual == expected
    if operator == "contains":
        return str(expected) in str(actual)
    if operator == "matches":
        if not isinstance(expected, str) or len(expected) > 500:
            raise ToolboxError(
                "matches expectation must be a regex string <= 500 chars"
            )
        return re.search(expected, str(actual)) is not None
    raise ToolboxError(f"unsupported observation expectation {operator!r}")


def _observe(
    page: Any,
    observation: dict[str, Any],
    *,
    environment: str,
) -> dict[str, Any]:
    observation_id = safe_component(
        observation.get("id"), field="browser observation id"
    )
    kind = observation.get("kind")
    selector_value = observation.get("selector")
    locator = None
    if kind not in {"url_path", "title"}:
        selector = _selector(
            selector_value,
            environment=environment,
            field=f"observation {observation_id}.selector",
        )
        locator = page.locator(selector)

    if kind == "url_path":
        actual: Any = _route(page.url)
    elif kind == "title":
        actual = safe_text(page.title(), limit=500)
    elif kind == "text":
        assert locator is not None
        actual = safe_text(" ".join(locator.inner_text().split()), limit=1000)
    elif kind == "visible":
        assert locator is not None
        actual = locator.is_visible()
    elif kind == "enabled":
        assert locator is not None
        actual = locator.is_enabled()
    elif kind == "checked":
        assert locator is not None
        actual = locator.is_checked()
    elif kind == "count":
        assert locator is not None
        actual = locator.count()
    elif kind == "attribute":
        assert locator is not None
        attribute = observation.get("attribute")
        if not isinstance(attribute, str) or not attribute:
            raise ToolboxError(
                f"observation {observation_id}: attribute name is required"
            )
        if attribute.casefold() in {
            "value",
            "cookie",
            "authorization",
            "srcdoc",
        }:
            raise ToolboxError(
                f"observation {observation_id}: sensitive attribute is forbidden"
            )
        raw = locator.get_attribute(attribute)
        actual = (
            safe_url(raw)
            if raw and attribute.casefold() in {"href", "src", "action"}
            else safe_text(raw, limit=1000)
        )
    else:
        raise ToolboxError(
            f"observation {observation_id}: unsupported kind {kind!r}"
        )
    passed = _expectation_passes(actual, observation.get("expect"))
    return {
        "id": observation_id,
        "kind": kind,
        "actual": actual,
        "passed": passed,
    }


def _screenshot(
    page: Any,
    *,
    artifacts_dir: Path,
    scenario_id: str,
    step_id: str,
    full_page: bool,
) -> dict[str, Any]:
    path = (artifacts_dir / f"{scenario_id}-{step_id}.png").resolve()
    page.screenshot(
        path=str(path),
        full_page=full_page,
        animations="disabled",
    )
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
    }


def run_browser_exploration(
    *,
    spec_path: Path,
    base_url: str,
    environment: str,
    output_path: Path,
    artifacts_dir: Path,
    storage_state: Path | None = None,
    headed: bool = False,
    allow_source_mutations: bool = False,
) -> dict[str, Any]:
    """Execute one approved browser scenario and retain sanitized observations."""

    if environment not in {"source", "clone"}:
        raise ToolboxError("browser environment must be source or clone")
    spec = load_json_object(spec_path, schema_version=BROWSER_SPEC_SCHEMA)
    scenario_id = safe_component(spec.get("scenario_id"), field="scenario_id")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ToolboxError("browser scenario requires a non-empty steps array")
    viewport = spec.get("viewport")
    if not isinstance(viewport, dict):
        raise ToolboxError("browser scenario viewport must be an object")
    try:
        viewport_width = int(viewport["width"])
        viewport_height = int(viewport["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolboxError("viewport requires integer width and height") from exc
    if not (240 <= viewport_width <= 7680 and 240 <= viewport_height <= 7680):
        raise ToolboxError("viewport dimensions are outside the supported range")
    base_origin = origin(base_url)
    approved = _approved_origins(spec, environment=environment)
    if base_origin not in approved:
        raise ToolboxError("base URL origin is absent from allowed_origins")
    if allow_source_mutations and environment != "source":
        raise ToolboxError(
            "--allow-source-mutations only applies to source exploration"
        )
    if allow_source_mutations and not spec.get("source_mutations_authorized", False):
        raise ToolboxError(
            "source mutations require source_mutations_authorized=true in the scenario"
        )
    if output_path.exists():
        raise ToolboxError(f"refusing to overwrite existing report: {output_path}")
    if artifacts_dir.exists() and any(artifacts_dir.iterdir()):
        raise ToolboxError(f"refusing non-empty artifacts directory: {artifacts_dir}")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if storage_state is not None and not storage_state.is_file():
        raise ToolboxError(f"storage state does not exist: {storage_state}")

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ToolboxError("browser exploration requires Playwright") from exc

    network_requests: list[dict[str, Any]] = []
    blocked_requests: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []
    console_errors: list[str] = []
    step_results: list[dict[str, Any]] = []
    seen_steps: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        try:
            context_options: dict[str, Any] = {
                "viewport": {
                    "width": viewport_width,
                    "height": viewport_height,
                },
                "service_workers": "block",
                "accept_downloads": False,
            }
            if storage_state is not None:
                context_options["storage_state"] = str(storage_state.resolve())
            context = browser.new_context(**context_options)

            def route_request(route: Any, request: Any) -> None:
                request_scheme = urlsplit(request.url).scheme.casefold()
                if request_scheme in {"data", "blob"}:
                    route.continue_()
                    return
                request_origin = origin(request.url)
                method = request.method.upper()
                if request_origin not in approved:
                    blocked_requests.append(
                        {
                            "method": method,
                            "url": safe_url(request.url),
                            "reason": "origin-not-approved",
                        }
                    )
                    route.abort("blockedbyclient")
                    return
                if (
                    environment == "source"
                    and method != "GET"
                    and not allow_source_mutations
                ):
                    blocked_requests.append(
                        {
                            "method": method,
                            "url": safe_url(request.url),
                            "reason": "source-mutation-not-authorized",
                        }
                    )
                    route.abort("blockedbyclient")
                    return
                route.continue_()

            context.route("**/*", route_request)
            page = context.new_page()
            page.on(
                "request",
                lambda request: network_requests.append(
                    {
                        "method": request.method,
                        "url": safe_url(request.url),
                        "resource_type": request.resource_type,
                    }
                ),
            )
            page.on(
                "requestfailed",
                lambda request: failed_requests.append(
                    {
                        "method": request.method,
                        "url": safe_url(request.url),
                        "reason": safe_text(
                            request.failure or "request-failed", limit=300
                        ),
                    }
                ),
            )
            page.on(
                "console",
                lambda message: (
                    console_errors.append(safe_text(message.text, limit=500))
                    if message.type == "error"
                    else None
                ),
            )
            timeout_ms = int(spec.get("timeout_ms", 10000))
            if timeout_ms < 100 or timeout_ms > 60000:
                raise ToolboxError("timeout_ms must be between 100 and 60000")
            page.set_default_timeout(timeout_ms)
            stop = False
            for raw_step in steps:
                if stop:
                    break
                if not isinstance(raw_step, dict):
                    raise ToolboxError("browser scenario step must be an object")
                step_id = safe_component(raw_step.get("id"), field="browser step id")
                if step_id in seen_steps:
                    raise ToolboxError(f"duplicate browser step id {step_id!r}")
                seen_steps.add(step_id)
                action = raw_step.get("action")
                observations: list[dict[str, Any]] = []
                screenshot = None
                error = None
                outcome = "passed"
                try:
                    if action == "goto":
                        path = raw_step.get("path")
                        if not isinstance(path, str) or not path.startswith("/"):
                            raise ToolboxError(
                                "goto.path must be an absolute local path"
                            )
                        target_url = urljoin(
                            base_url.rstrip("/") + "/", path.lstrip("/")
                        )
                        if origin(target_url) != base_origin:
                            raise ToolboxError(
                                "goto path escapes the configured base origin"
                            )
                        page.goto(
                            target_url,
                            wait_until=raw_step.get("wait_until", "domcontentloaded"),
                        )
                    elif action in {
                        "click",
                        "fill",
                        "press",
                        "hover",
                        "select",
                        "check",
                        "uncheck",
                    }:
                        selector = _selector(
                            raw_step.get("selector"),
                            environment=environment,
                            field=f"step {step_id}.selector",
                        )
                        locator = page.locator(selector)
                        if action == "click":
                            locator.click()
                        elif action == "fill":
                            locator.fill(_input_value(raw_step, selector=selector))
                        elif action == "press":
                            key = raw_step.get("key")
                            if not isinstance(key, str) or not key:
                                raise ToolboxError(
                                    "press.key must be a non-empty string"
                                )
                            locator.press(key)
                        elif action == "hover":
                            locator.hover()
                        elif action == "select":
                            option = raw_step.get("option")
                            if not isinstance(option, str):
                                raise ToolboxError("select.option must be a string")
                            locator.select_option(option)
                        elif action == "check":
                            locator.check()
                        elif action == "uncheck":
                            locator.uncheck()
                    elif action == "wait":
                        selector_value = raw_step.get("selector")
                        wait_ms = raw_step.get("milliseconds")
                        if selector_value is not None:
                            selector = _selector(
                                selector_value,
                                environment=environment,
                                field=f"step {step_id}.selector",
                            )
                            page.locator(selector).wait_for(
                                state=raw_step.get("state", "visible")
                            )
                        elif isinstance(wait_ms, int) and 0 <= wait_ms <= 10000:
                            page.wait_for_timeout(wait_ms)
                        else:
                            raise ToolboxError(
                                "wait requires selector or milliseconds from 0 to 10000"
                            )
                    elif action != "snapshot":
                        raise ToolboxError(
                            f"step {step_id}: unsupported action {action!r}"
                        )

                    raw_observations = raw_step.get("observations", [])
                    if not isinstance(raw_observations, list):
                        raise ToolboxError(
                            f"step {step_id}.observations must be an array"
                        )
                    observations = [
                        _observe(page, item, environment=environment)
                        for item in raw_observations
                        if isinstance(item, dict)
                    ]
                    if len(observations) != len(raw_observations):
                        raise ToolboxError(
                            f"step {step_id}: every observation must be an object"
                        )
                    if any(not item["passed"] for item in observations):
                        outcome = "failed"
                    if raw_step.get("screenshot", False):
                        screenshot = _screenshot(
                            page,
                            artifacts_dir=artifacts_dir,
                            scenario_id=scenario_id,
                            step_id=step_id,
                            full_page=bool(raw_step.get("full_page", False)),
                        )
                except (PlaywrightError, PlaywrightTimeoutError, ToolboxError) as exc:
                    error = safe_text(str(exc), limit=1000)
                    outcome = "error"
                    stop = True
                step_results.append(
                    {
                        "id": step_id,
                        "action": action,
                        "route": _route(page.url) if page.url else None,
                        "outcome": outcome,
                        "observations": observations,
                        "screenshot": screenshot,
                        "error": error,
                    }
                )
            context.close()
        finally:
            browser.close()

    assertion_failures = sum(
        not observation["passed"]
        for step in step_results
        for observation in step["observations"]
    )
    result = {
            "schema_version": "websitebench.offline-clone.browser-exploration.v1",
            "scenario_id": scenario_id,
            "environment": environment,
            "spec": {"path": str(spec_path.resolve())},
            "target": {
                "base_origin": base_origin,
                "allowed_origins": approved,
                "viewport": {
                    "width": viewport_width,
                    "height": viewport_height,
                },
                "authenticated_storage_consumed": storage_state is not None,
                "source_mutations_authorized": bool(
                    environment == "source" and allow_source_mutations
                ),
            },
            "steps": step_results,
            "network": {
                "requests": network_requests,
                "blocked": blocked_requests,
                "failed": failed_requests,
            },
            "console_errors": console_errors,
            "summary": {
                "steps_total": len(step_results),
                "steps_passed": sum(
                    step["outcome"] == "passed" for step in step_results
                ),
                "assertion_failures": assertion_failures,
                "console_error_count": len(console_errors),
                "failed_request_count": len(failed_requests),
                "blocked_request_count": len(blocked_requests),
            },
            "status": (
                "passed"
                if len(step_results) == len(steps)
                and all(step["outcome"] == "passed" for step in step_results)
                else "failed"
            ),
            "authority": "diagnostic-only",
    }
    write_json_atomic(output_path, result)
    return result
