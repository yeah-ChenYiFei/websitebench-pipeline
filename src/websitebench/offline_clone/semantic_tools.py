"""Black-box HTTP semantic testing for isolated offline-clone backends."""

from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .toolbox import (
    ToolboxError,
    load_json_object,
    origin,
    safe_component,
    safe_text,
    write_json_atomic,
)


BACKEND_SPEC_SCHEMA = "websitebench.offline-clone.backend-semantic-suite.v1"
_TEMPLATE = re.compile(r"\$\{(ENV|VAR):([A-Za-z_][A-Za-z0-9_.-]*)\}")
_SENSITIVE_NAME = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|cookie|authorization|otp|cvv|cvc|card)"
)


def _is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _resolve_template(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [_resolve_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_template(item, variables) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    full = _TEMPLATE.fullmatch(value)
    if full:
        namespace, name = full.groups()
        if namespace == "ENV":
            if name not in os.environ:
                raise ToolboxError(
                    f"required environment variable {name!r} is not set"
                )
            return os.environ[name]
        if name not in variables:
            raise ToolboxError(f"captured variable {name!r} is not available")
        return variables[name]

    def replace(match: re.Match[str]) -> str:
        namespace, name = match.groups()
        if namespace == "ENV":
            if name not in os.environ:
                raise ToolboxError(
                    f"required environment variable {name!r} is not set"
                )
            return os.environ[name]
        if name not in variables:
            raise ToolboxError(f"captured variable {name!r} is not available")
        return str(variables[name])

    return _TEMPLATE.sub(replace, value)


def _validate_secret_values(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if _SENSITIVE_NAME.search(str(key)):
                if not isinstance(item, str) or not re.search(
                    r"\$\{ENV:[A-Za-z_][A-Za-z0-9_.-]*\}", item
                ):
                    raise ToolboxError(
                        f"{child_path}: sensitive values must come from ENV templates"
                    )
            _validate_secret_values(item, path=child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_secret_values(item, path=f"{path}[{index}]")


def _json_pointer(value: Any, pointer: str) -> tuple[bool, Any]:
    if pointer == "":
        return True, value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ToolboxError(f"invalid JSON pointer {pointer!r}")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return False, None
            if index < 0 or index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _expected_status(value: Any) -> set[int]:
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ToolboxError("expect.status must not be empty")
    result: set[int] = set()
    for item in values:
        if not isinstance(item, int) or item < 100 or item > 599:
            raise ToolboxError("expect.status values must be HTTP status integers")
        result.add(item)
    return result


def _assert_response(
    response: Any,
    expectation: dict[str, Any],
    *,
    variables: dict[str, Any],
) -> tuple[list[dict[str, Any]], Any]:
    assertions: list[dict[str, Any]] = []
    statuses = _expected_status(expectation.get("status"))
    assertions.append(
        {
            "kind": "status",
            "passed": response.status_code in statuses,
            "actual": response.status_code,
            "expected": sorted(statuses),
        }
    )
    needs_json = any(
        key in expectation for key in ("json_equal", "json_present", "json_absent")
    )
    payload: Any = None
    if needs_json:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            assertions.append(
                {
                    "kind": "json-decode",
                    "passed": False,
                    "summary": "response was not valid JSON",
                }
            )
            return assertions, None

    json_equal = expectation.get("json_equal", {})
    if not isinstance(json_equal, dict):
        raise ToolboxError("expect.json_equal must be an object")
    for pointer, raw_expected in json_equal.items():
        present, actual = _json_pointer(payload, pointer)
        expected = _resolve_template(raw_expected, variables)
        assertions.append(
            {
                "kind": "json-equal",
                "pointer": pointer,
                "passed": present and actual == expected,
            }
        )
    for key, should_be_present in (
        ("json_present", True),
        ("json_absent", False),
    ):
        pointers = expectation.get(key, [])
        if not isinstance(pointers, list) or not all(
            isinstance(pointer, str) for pointer in pointers
        ):
            raise ToolboxError(f"expect.{key} must be an array of JSON pointers")
        for pointer in pointers:
            present, _ = _json_pointer(payload, pointer)
            assertions.append(
                {
                    "kind": key.replace("_", "-"),
                    "pointer": pointer,
                    "passed": present is should_be_present,
                }
            )
    header_equal = expectation.get("header_equal", {})
    if not isinstance(header_equal, dict):
        raise ToolboxError("expect.header_equal must be an object")
    for header, raw_expected in header_equal.items():
        if _SENSITIVE_NAME.search(header):
            raise ToolboxError("assertions on sensitive response headers are forbidden")
        expected = str(_resolve_template(raw_expected, variables))
        assertions.append(
            {
                "kind": "header-equal",
                "header": header.casefold(),
                "passed": response.headers.get(header) == expected,
            }
        )
    return assertions, payload


def _request_headers(
    request: dict[str, Any], *, variables: dict[str, Any]
) -> dict[str, str]:
    literal = request.get("headers", {})
    environment = request.get("headers_env", {})
    if not isinstance(literal, dict) or not isinstance(environment, dict):
        raise ToolboxError("request headers and headers_env must be objects")
    headers: dict[str, str] = {}
    for name, value in literal.items():
        if _SENSITIVE_NAME.search(name):
            raise ToolboxError(
                f"sensitive request header {name!r} must use headers_env"
            )
        headers[str(name)] = str(_resolve_template(value, variables))
    for name, variable in environment.items():
        if not isinstance(variable, str) or variable not in os.environ:
            raise ToolboxError(
                f"headers_env requires a set environment variable for {name!r}"
            )
        headers[str(name)] = os.environ[variable]
    return headers


def run_backend_semantic_suite(
    *,
    spec_path: Path,
    base_url: str,
    output_path: Path,
    allow_non_loopback: bool = False,
) -> dict[str, Any]:
    """Run actor-isolated HTTP cases without retaining request or response bodies."""

    parsed_base = urlsplit(base_url)
    base_origin = origin(base_url)
    if not allow_non_loopback and not _is_loopback_host(parsed_base.hostname):
        raise ToolboxError(
            "backend semantic tests default to loopback targets; "
            "pass --allow-non-loopback only for an explicitly isolated clone"
        )
    spec = load_json_object(spec_path, schema_version=BACKEND_SPEC_SCHEMA)
    suite_id = safe_component(spec.get("suite_id"), field="backend suite_id")
    declared_origin = spec.get("allowed_origin")
    if not isinstance(declared_origin, str) or origin(declared_origin) != base_origin:
        raise ToolboxError(
            "backend suite allowed_origin must exactly match base URL origin"
        )
    if output_path.exists():
        raise ToolboxError(f"refusing to overwrite existing report: {output_path}")

    invariants = spec.get("invariants")
    cases = spec.get("cases")
    if not isinstance(invariants, list) or not invariants:
        raise ToolboxError("backend suite requires a non-empty invariants array")
    if not isinstance(cases, list) or not cases:
        raise ToolboxError("backend suite requires a non-empty cases array")
    invariant_contracts: dict[str, dict[str, Any]] = {}
    for invariant in invariants:
        if not isinstance(invariant, dict):
            raise ToolboxError("backend invariant declaration must be an object")
        invariant_id = safe_component(
            invariant.get("id"), field="backend invariant id"
        )
        if invariant_id in invariant_contracts:
            raise ToolboxError(f"duplicate backend invariant id {invariant_id!r}")
        applicability = invariant.get("applicability", "applicable")
        if applicability not in {"applicable", "not_applicable"}:
            raise ToolboxError(
                "invariant applicability must be applicable/not_applicable"
            )
        if applicability == "not_applicable" and not invariant.get("reason"):
            raise ToolboxError(
                f"invariant {invariant_id}: not_applicable requires a reason"
            )
        raw_polarities = invariant.get(
            "required_polarities", ["positive", "negative"]
        )
        if (
            not isinstance(raw_polarities, list)
            or not raw_polarities
            or any(item not in {"positive", "negative"} for item in raw_polarities)
        ):
            raise ToolboxError(
                f"invariant {invariant_id}: required_polarities is invalid"
            )
        invariant_contracts[invariant_id] = {
            "applicability": applicability,
            "reason": safe_text(invariant.get("reason"), limit=500) or None,
            "required_polarities": sorted(set(raw_polarities)),
        }

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise ToolboxError("backend semantic testing requires httpx") from exc

    timeout = float(spec.get("timeout_seconds", 10))
    if timeout <= 0 or timeout > 60:
        raise ToolboxError("timeout_seconds must be > 0 and <= 60")
    follow_redirects = bool(spec.get("follow_redirects", False))
    clients: dict[str, Any] = {}
    variables: dict[str, Any] = {}
    case_ids: set[str] = set()
    case_results: list[dict[str, Any]] = []
    try:
        for raw_case in cases:
            if not isinstance(raw_case, dict):
                raise ToolboxError("backend case must be an object")
            case_id = safe_component(raw_case.get("id"), field="backend case id")
            if case_id in case_ids:
                raise ToolboxError(f"duplicate backend case id {case_id!r}")
            case_ids.add(case_id)
            invariant_id = raw_case.get("invariant_id")
            if invariant_id not in invariant_contracts:
                raise ToolboxError(
                    f"case {case_id}: unknown invariant_id {invariant_id!r}"
                )
            if (
                invariant_contracts[invariant_id]["applicability"]
                != "applicable"
            ):
                raise ToolboxError(
                    f"case {case_id}: references a not_applicable invariant"
                )
            polarity = raw_case.get("polarity")
            if polarity not in {"positive", "negative"}:
                raise ToolboxError(f"case {case_id}: invalid polarity")
            actor = safe_component(raw_case.get("actor"), field="backend actor")
            if actor not in clients:
                clients[actor] = httpx.Client(
                    base_url=base_origin,
                    timeout=timeout,
                    follow_redirects=follow_redirects,
                )
            steps = raw_case.get("steps")
            if not isinstance(steps, list) or not steps:
                raise ToolboxError(f"case {case_id}: steps must be non-empty")
            step_ids: set[str] = set()
            step_results: list[dict[str, Any]] = []
            case_passed = True
            for raw_step in steps:
                if not isinstance(raw_step, dict):
                    raise ToolboxError(f"case {case_id}: step must be an object")
                step_id = safe_component(
                    raw_step.get("id"), field=f"case {case_id} step id"
                )
                if step_id in step_ids:
                    raise ToolboxError(
                        f"case {case_id}: duplicate step id {step_id!r}"
                    )
                step_ids.add(step_id)
                request = raw_step.get("request")
                expectation = raw_step.get("expect")
                if not isinstance(request, dict) or not isinstance(
                    expectation, dict
                ):
                    raise ToolboxError(
                        f"case {case_id}/{step_id}: request and expect are required"
                    )
                method = str(request.get("method", "GET")).upper()
                if method not in {
                    "GET",
                    "HEAD",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                }:
                    raise ToolboxError(
                        f"case {case_id}/{step_id}: unsupported HTTP method"
                    )
                raw_path = request.get("path")
                if (
                    not isinstance(raw_path, str)
                    or not raw_path.startswith("/")
                    or raw_path.startswith("//")
                    or "://" in raw_path
                ):
                    raise ToolboxError(
                        f"case {case_id}/{step_id}: path must stay on allowed_origin"
                    )
                path = str(_resolve_template(raw_path, variables))
                body = request.get("json")
                if body is not None:
                    _validate_secret_values(body)
                    body = _resolve_template(body, variables)
                headers = _request_headers(request, variables=variables)
                request_error = None
                assertions: list[dict[str, Any]] = []
                captured_names: list[str] = []
                status_code = None
                response_bytes = 0
                response_content_type = None
                try:
                    response = clients[actor].request(
                        method,
                        path,
                        headers=headers,
                        json=body,
                    )
                    status_code = response.status_code
                    response_bytes = len(response.content)
                    response_content_type = response.headers.get("content-type")
                    assertions, payload = _assert_response(
                        response, expectation, variables=variables
                    )
                    passed = all(item["passed"] for item in assertions)
                    captures = raw_step.get("capture", {})
                    if not isinstance(captures, dict):
                        raise ToolboxError(
                            f"case {case_id}/{step_id}: capture must be an object"
                        )
                    if passed and captures:
                        if payload is None:
                            try:
                                payload = response.json()
                            except (json.JSONDecodeError, ValueError) as exc:
                                raise ToolboxError(
                                    f"case {case_id}/{step_id}: capture requires JSON"
                                ) from exc
                        for name, pointer in captures.items():
                            variable_name = safe_component(
                                name, field="captured variable name"
                            )
                            present, captured = _json_pointer(payload, pointer)
                            if not present:
                                raise ToolboxError(
                                    f"case {case_id}/{step_id}: capture pointer "
                                    f"{pointer!r} is absent"
                                )
                            variables[variable_name] = captured
                            captured_names.append(variable_name)
                except (httpx.HTTPError, ToolboxError) as exc:
                    passed = False
                    request_error = safe_text(str(exc), limit=500)
                case_passed = case_passed and passed
                step_results.append(
                    {
                        "id": step_id,
                        "request": {
                            "method": method,
                            "path": urlsplit(path).path or "/",
                            "body_present": body is not None,
                            "environment_header_names": sorted(
                                request.get("headers_env", {})
                            ),
                        },
                        "response": {
                            "status": status_code,
                            "bytes": response_bytes,
                            "content_type": response_content_type,
                        },
                        "assertions": assertions,
                        "captured_variable_names": captured_names,
                        "passed": passed,
                        "error": request_error,
                    }
                )
                if request_error:
                    break
            case_results.append(
                {
                    "id": case_id,
                    "invariant_id": invariant_id,
                    "polarity": polarity,
                    "actor": actor,
                    "steps": step_results,
                    "passed": case_passed and len(step_results) == len(steps),
                }
            )
    finally:
        for client in clients.values():
            client.close()

    coverage: list[dict[str, Any]] = []
    for invariant_id, contract in invariant_contracts.items():
        if contract["applicability"] == "not_applicable":
            coverage.append(
                {
                    "id": invariant_id,
                    **contract,
                    "verified_polarities": [],
                    "complete": True,
                }
            )
            continue
        verified = sorted(
            {
                case["polarity"]
                for case in case_results
                if case["invariant_id"] == invariant_id and case["passed"]
            }
        )
        coverage.append(
            {
                "id": invariant_id,
                **contract,
                "verified_polarities": verified,
                "complete": set(contract["required_polarities"]).issubset(verified),
            }
        )

    passed = all(case["passed"] for case in case_results) and all(
        item["complete"] for item in coverage
    )
    result = {
            "schema_version": "websitebench.offline-clone.backend-semantic-report.v1",
            "suite_id": suite_id,
            "spec": {"path": str(spec_path.resolve())},
            "target": {
                "origin": base_origin,
                "loopback": _is_loopback_host(parsed_base.hostname),
                "non_loopback_explicitly_allowed": bool(allow_non_loopback),
            },
            "cases": case_results,
            "invariant_coverage": coverage,
            "counts": {
                "cases_total": len(case_results),
                "cases_passed": sum(case["passed"] for case in case_results),
                "applicable_invariants": sum(
                    item["applicability"] == "applicable" for item in coverage
                ),
                "complete_invariants": sum(
                    item["complete"]
                    and item["applicability"] == "applicable"
                    for item in coverage
                ),
            },
            "status": "passed" if passed else "failed",
            "retention": {
                "request_bodies": False,
                "response_bodies": False,
                "captured_values": False,
                "environment_values": False,
            },
            "authority": "diagnostic-only",
    }
    write_json_atomic(output_path, result)
    return result
