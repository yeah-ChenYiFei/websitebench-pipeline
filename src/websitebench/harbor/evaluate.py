"""Four-worker deterministic Harbor v2 candidate evaluator."""

from __future__ import annotations

import concurrent.futures
import contextlib
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterator, Mapping

from .dsl_v2 import observe, run_actions
from .judge_v2 import (
    TASK_RESULTS_SCHEMA,
    VISUAL_RESULTS_SCHEMA,
    CandidateProcess,
    InvalidRun,
    compute_visual_checkpoint,
    evaluate_observations,
    launch_deterministic_chromium,
    opaque_isolation_uid,
    run_platform_cicd,
    redact_visual_masks,
    render_environment_fingerprint,
    score_results,
    synthesize_deploy_failure,
)
from .mailbox import LocalMailboxSidecar
from .sandbox_v2 import sandbox_preflight


_PORT_LOCK = threading.Lock()
_ALLOCATED_PORTS: set[int] = set()
_NETWORK_AUDIT_LOCK = threading.Lock()
_NETWORK_AUDIT_ACTIVE: list["_RuntimeNetworkAudit"] = []
_NETWORK_AUDIT_INSTALLED = False
_MODEL_HOST = re.compile(
    r"(?:^|[.-])(?:openai|anthropic|claude|gemini|generativelanguage|bedrock|"
    r"vertex|aiplatform|cohere|mistral|groq|openrouter|huggingface|ollama|vllm)"
    r"(?:[.-]|$)",
    re.IGNORECASE,
)


def _loopback_host(host: str) -> bool:
    lowered = host.rstrip(".").lower()
    if lowered == "localhost":
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


class _RuntimeNetworkAudit:
    def __init__(self, allowed_hosts: set[str]) -> None:
        self.allowed_hosts = {item.rstrip(".").lower() for item in allowed_hosts}
        self.hosts: set[str] = set()
        self.raw_connect_hosts: set[str] = set()
        self.request_count = 0
        self.model_request_count = 0
        self.violations: set[str] = set()
        self._lock = threading.Lock()

    def observe(self, event: str, arguments: tuple[Any, ...]) -> None:
        host: str | None = None
        enforce = False
        if event == "urllib.Request" and arguments and isinstance(arguments[0], str):
            parsed = urllib.parse.urlsplit(arguments[0])
            host = parsed.hostname
            enforce = True
            with self._lock:
                self.request_count += 1
        elif (
            event == "socket.getaddrinfo"
            and arguments
            and isinstance(arguments[0], str)
        ):
            host = arguments[0]
            enforce = True
        elif event == "socket.connect" and len(arguments) >= 2:
            address = arguments[1]
            if isinstance(address, tuple) and address and isinstance(address[0], str):
                host = address[0]
                with self._lock:
                    self.raw_connect_hosts.add(host.rstrip(".").lower())
        if not host:
            return
        normalized = host.rstrip(".").lower()
        if _loopback_host(normalized):
            return
        with self._lock:
            self.hosts.add(normalized)
            model_host = _MODEL_HOST.search(normalized) is not None
            if model_host:
                self.model_request_count += 1
                self.violations.add("MODEL_SERVICE_REQUEST_BLOCKED")
            elif enforce and normalized not in self.allowed_hosts:
                self.violations.add("UNALLOWLISTED_NETWORK_REQUEST_BLOCKED")
            denied = model_host or (enforce and normalized not in self.allowed_hosts)
        if denied:
            raise InvalidRun("verifier attempted a forbidden network request")

    def evidence(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": "websitebench.harbor.network-runtime-evidence.v1",
                "allowed_hosts": sorted(self.allowed_hosts),
                "observed_non_loopback_hosts": sorted(self.hosts),
                "observed_raw_connect_hosts": sorted(self.raw_connect_hosts),
                "http_request_count": self.request_count,
                "model_request_count": self.model_request_count,
                "violations": sorted(self.violations),
                "verdict_source": "python-runtime-audit-hook",
            }


def _network_audit_hook(event: str, arguments: tuple[Any, ...]) -> None:
    with _NETWORK_AUDIT_LOCK:
        active = tuple(_NETWORK_AUDIT_ACTIVE)
    for audit in active:
        audit.observe(event, arguments)


@contextlib.contextmanager
def _runtime_network_audit(
    allowed_hosts: set[str],
) -> Iterator[_RuntimeNetworkAudit]:
    global _NETWORK_AUDIT_INSTALLED
    audit = _RuntimeNetworkAudit(allowed_hosts)
    with _NETWORK_AUDIT_LOCK:
        if not _NETWORK_AUDIT_INSTALLED:
            sys.addaudithook(_network_audit_hook)
            _NETWORK_AUDIT_INSTALLED = True
        _NETWORK_AUDIT_ACTIVE.append(audit)
    try:
        yield audit
    finally:
        with _NETWORK_AUDIT_LOCK:
            _NETWORK_AUDIT_ACTIVE.remove(audit)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InvalidRun(f"JSON input must contain an object: {path}")
    return value


def _validate_reference_observations(
    reference_observations: Mapping[str, Any],
    task_suite: Mapping[str, Any],
    visual_suite: Mapping[str, Any],
    reference_root: Path,
) -> None:
    reset_strategy = reference_observations.get("reset_strategy")
    if reset_strategy not in {
        "fresh-local-data-directory",
        "remote-read-only",
        "remote-reset-gateway",
    }:
        raise InvalidRun("reference observations have no reset strategy")
    if not isinstance(reference_observations.get("authenticated_reference"), bool):
        raise InvalidRun("reference observations have no authentication-state marker")
    observed_tasks = reference_observations.get("tasks")
    if not isinstance(observed_tasks, Mapping) or set(observed_tasks) != {
        task["id"] for task in task_suite["tasks"]
    }:
        raise InvalidRun("reference observation task set differs from task suite")
    for task in task_suite["tasks"]:
        fact = observed_tasks[task["id"]]
        observations = fact.get("observations") if isinstance(fact, Mapping) else None
        if not isinstance(observations, Mapping) or set(observations) != {
            item["id"] for item in task["observations"]
        }:
            raise InvalidRun(f"reference task facts drift: {task['id']}")
    observed_visuals = reference_observations.get("visual_checkpoints")
    indexed = (
        {
            item.get("checkpoint_id"): item
            for item in observed_visuals
            if isinstance(item, Mapping)
        }
        if isinstance(observed_visuals, list)
        else {}
    )
    if set(indexed) != {item["id"] for item in visual_suite["checkpoints"]}:
        raise InvalidRun("reference observation visual set differs from visual suite")
    resolved_root = reference_root.resolve()
    for checkpoint in visual_suite["checkpoints"]:
        fact = indexed[checkpoint["id"]]
        relative = checkpoint["reference_image"]
        image = (resolved_root / relative).resolve()
        if resolved_root not in image.parents or not image.is_file():
            raise InvalidRun(f"reference raster path is unsafe: {checkpoint['id']}")
        try:
            from PIL import Image

            with Image.open(image) as raster:
                actual_size = raster.size
        except (OSError, ValueError) as exc:
            raise InvalidRun(
                f"reference raster is unreadable: {checkpoint['id']}"
            ) from exc
        if (
            fact.get("reference_image") != relative
            or fact.get("width") != checkpoint["viewport"]["width"]
            or fact.get("height") != checkpoint["viewport"]["height"]
            or actual_size
            != (
                checkpoint["viewport"]["width"],
                checkpoint["viewport"]["height"],
            )
        ):
            raise InvalidRun(f"reference raster binding drift: {checkpoint['id']}")


def _port() -> int:
    with _PORT_LOCK:
        while True:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            if port not in _ALLOCATED_PORTS:
                _ALLOCATED_PORTS.add(port)
                return port


def _isolation_uid() -> int:
    return opaque_isolation_uid()


def _opaque_worker_identity() -> str:
    """Return a capability-shaped identity with no suite/phase information."""

    return secrets.token_hex(16)


def verify_render_environment(
    browser_settings: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch_deterministic_chromium(playwright)
        try:
            actual = render_environment_fingerprint(browser_settings, browser.version)
        finally:
            browser.close()
    if dict(actual) != dict(expected):
        raise InvalidRun(
            "verifier browser/font environment differs from reference capture"
        )


def _browser_context(
    browser: Any,
    settings: Mapping[str, Any],
    viewport: Mapping[str, int] | None = None,
    *,
    allowed_origin: str,
) -> Any:
    arguments: dict[str, Any] = {
        "locale": settings["locale"],
        "timezone_id": settings["timezone"],
        "color_scheme": settings["color_scheme"],
        "reduced_motion": "reduce",
    }
    if viewport is not None:
        arguments["viewport"] = {
            "width": viewport["width"],
            "height": viewport["height"],
        }
    context = browser.new_context(**arguments)
    if settings.get("disable_animations") is True:
        context.add_init_script(
            """document.addEventListener('DOMContentLoaded', () => {
              const style = document.createElement('style');
              style.textContent = '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}';
              document.documentElement.appendChild(style);
            }, {once: true});"""
        )
    allowed = urllib.parse.urlsplit(allowed_origin)

    def route_request(route: Any) -> None:
        target = urllib.parse.urlsplit(route.request.url)
        if target.scheme in {"about", "blob", "data"} or (
            target.scheme.lower(),
            target.netloc.lower(),
        ) == (allowed.scheme.lower(), allowed.netloc.lower()):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    context.route("**/*", route_request)
    frozen_time = settings.get("frozen_time")
    if isinstance(frozen_time, str):
        encoded = json.dumps(frozen_time)
        context.add_init_script(
            """
            (() => {
              const RealDate = Date;
              const frozen = new RealDate(%s).valueOf();
              function FrozenDate(...args) {
                if (!new.target) return new RealDate(frozen).toString();
                return new RealDate(...(args.length ? args : [frozen]));
              }
              Object.setPrototypeOf(FrozenDate, RealDate);
              FrozenDate.prototype = RealDate.prototype;
              FrozenDate.now = () => frozen;
              globalThis.Date = FrozenDate;
            })();
            """
            % encoded
        )
    return context


def _task_worker(
    declaration: Mapping[str, Any],
    frozen: Mapping[str, Any],
    *,
    candidate_root: Path,
    fixture_root: Path,
    browser_settings: Mapping[str, Any],
    ready_path: str,
    worker_root: Path,
    worker_identity: str,
    mailbox_capability: str | None,
    cpu_limit: int | None,
    memory_limit_mb: int | None,
    storage_limit_mb: int | None,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    identifier = str(declaration["id"])
    deadline = time.monotonic() + float(declaration["timeout_sec"])
    port = _port()
    deployment = CandidateProcess(
        candidate_root,
        port,
        worker_root / "data",
        f"worker-{worker_identity}",
        mailbox_capability=mailbox_capability,
        audit_prefix=worker_root / "audit" / "candidate",
        cpu_limit=cpu_limit,
        memory_limit_mb=memory_limit_mb,
        storage_limit_mb=storage_limit_mb,
        isolation_uid=_isolation_uid(),
    )

    def audited(result: dict[str, Any]) -> dict[str, Any]:
        deployment.stop()
        if deployment.write_violations():
            return {
                "task_id": identifier,
                "status": "failed",
                "reason": "CANDIDATE_WRITE_OUTSIDE_DATA_DIR",
                "attempts": 1,
                "observations": [],
            }
        if deployment.network_violations():
            return {
                "task_id": identifier,
                "status": "failed",
                "reason": "CANDIDATE_EXTERNAL_NETWORK_ATTEMPT",
                "attempts": 1,
                "observations": [],
            }
        if deployment.ipc_violations():
            return {
                "task_id": identifier,
                "status": "failed",
                "reason": "CANDIDATE_SHARED_IPC_ATTEMPT",
                "attempts": 1,
                "observations": [],
            }
        return result

    try:
        deployment.start()
        if not deployment.ready(
            ready_path,
            timeout=max(0.1, min(deadline - time.monotonic(), 30.0)),
        ):
            return audited(
                {
                    "task_id": identifier,
                    "status": "failed",
                    "reason": "CANDIDATE_DEPLOY_FAILED",
                    "attempts": 1,
                    "observations": [],
                }
            )
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = launch_deterministic_chromium(playwright)
            context = _browser_context(
                browser, browser_settings, allowed_origin=base_url
            )
            page = context.new_page()
            page.set_default_timeout(int(declaration["timeout_sec"]) * 1000)
            actors = {"primary": (context, page)}
            captures: dict[str, Any] = {}

            def restart() -> str:
                deployment.stop()
                deployment.start()
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not deployment.ready(
                    ready_path, timeout=min(remaining, 30.0)
                ):
                    raise RuntimeError("candidate restart failed")
                return base_url

            try:
                page, current_base = run_actions(
                    page,
                    declaration["actions"],
                    base_url=base_url,
                    fixture_root=fixture_root,
                    actors=actors,
                    captures=captures,
                    restart=restart,
                    mailbox_namespace=f"worker-{worker_identity}",
                    mailbox_credential=mailbox_capability,
                    actor_context_factory=lambda: _browser_context(
                        browser, browser_settings, allowed_origin=base_url
                    ),
                    deadline=deadline,
                )
                actual: dict[str, Any] = {}
                for observation in declaration["observations"]:
                    remaining_ms = int((deadline - time.monotonic()) * 1000)
                    if remaining_ms <= 0:
                        raise TimeoutError("task deadline exceeded")
                    page.set_default_timeout(remaining_ms)
                    actual[observation["id"]] = observe(
                        page,
                        observation,
                        base_url=current_base,
                        captures=captures,
                        timeout_ms=remaining_ms,
                    )
                passed, observations = evaluate_observations(
                    actual,
                    declaration["observations"],
                    frozen["observations"],
                )
                reason = (
                    "ALL_OBSERVATIONS_MATCH" if passed else "TERMINAL_STATE_MISMATCH"
                )
                return audited(
                    {
                        "task_id": identifier,
                        "status": "passed" if passed else "failed",
                        "reason": reason,
                        "attempts": 1,
                        "observations": observations,
                    }
                )
            except Exception as exc:
                return audited(
                    {
                        "task_id": identifier,
                        "status": "failed",
                        "reason": f"TASK_EXECUTION_FAILED:{type(exc).__name__}",
                        "attempts": 1,
                        "observations": [],
                    }
                )
            finally:
                for actor_context, _actor_page in actors.values():
                    if actor_context is not context:
                        actor_context.close()
                context.close()
                browser.close()
    finally:
        deployment.stop()


def evaluate_task_suite(
    suite: Mapping[str, Any],
    reference_observations: Mapping[str, Any],
    *,
    candidate_root: Path,
    fixture_root: Path,
    browser_settings: Mapping[str, Any],
    ready_path: str,
    working_root: Path,
    trace_root: Path,
    workers: int = 4,
    mailbox_sidecar: LocalMailboxSidecar | None = None,
    cpu_limit: int | None = None,
    memory_limit_mb: int | None = None,
    storage_limit_mb: int | None = None,
) -> dict[str, Any]:
    observed = reference_observations.get("tasks")
    if not isinstance(observed, dict):
        raise InvalidRun("reference observations have no task facts")
    expected = {task["id"] for task in suite["tasks"]}
    if set(observed) != expected:
        raise InvalidRun("reference observation task set differs from task suite")
    futures: dict[concurrent.futures.Future[dict[str, Any]], str] = {}
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for declaration in suite["tasks"]:
            identifier = declaration["id"]
            worker_identity = _opaque_worker_identity()
            namespace = f"worker-{worker_identity}"
            mailbox_capability = (
                secrets.token_hex(32) if mailbox_sidecar is not None else None
            )
            if mailbox_sidecar is not None and mailbox_capability is not None:
                mailbox_sidecar.register_namespace(namespace, mailbox_capability)
            root = working_root / f"worker-{worker_identity}"
            root.mkdir(parents=True, exist_ok=True)
            future = executor.submit(
                _task_worker,
                declaration,
                observed[identifier],
                candidate_root=candidate_root,
                fixture_root=fixture_root,
                browser_settings=browser_settings,
                ready_path=ready_path,
                worker_root=root,
                worker_identity=worker_identity,
                mailbox_capability=mailbox_capability,
                cpu_limit=cpu_limit,
                memory_limit_mb=memory_limit_mb,
                storage_limit_mb=storage_limit_mb,
            )
            futures[future] = identifier
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["task_id"]] = result
    payload = {
        "schema_version": TASK_RESULTS_SCHEMA,
        "tasks": [results[task["id"]] for task in suite["tasks"]],
        "summary": {
            "passed": sum(
                results[task["id"]]["status"] == "passed" for task in suite["tasks"]
            ),
            "total": len(suite["tasks"]),
        },
    }
    isolation_failures = [
        item["reason"]
        for item in payload["tasks"]
        if item["reason"]
        in {
            "CANDIDATE_WRITE_OUTSIDE_DATA_DIR",
            "CANDIDATE_EXTERNAL_NETWORK_ATTEMPT",
            "CANDIDATE_SHARED_IPC_ATTEMPT",
        }
    ]
    if isolation_failures:
        # A shared-file or external-network side channel may already have
        # influenced sibling workers.  Invalidate the complete suite so a
        # sacrificial writer cannot boost later tasks.
        reason = sorted(isolation_failures)[0]
        payload = synthesize_deploy_failure(suite, reason)
        payload["summary"] = {"passed": 0, "total": len(suite["tasks"])}
    _write_task_traces(suite, payload, trace_root)
    return payload


def _write_task_traces(
    suite: Mapping[str, Any],
    task_results: Mapping[str, Any],
    trace_root: Path,
) -> None:
    """Write value-free task traces for every success and failure path."""

    results = {item["task_id"]: item for item in task_results["tasks"]}
    trace_root.mkdir(parents=True, exist_ok=True)
    for task in suite["tasks"]:
        result = results[task["id"]]
        trace = {
            "schema_version": "websitebench.harbor.sanitized-task-trace.v1",
            "task_id": task["id"],
            "status": result["status"],
            "attempts": result["attempts"],
            "actions": [action["op"] for action in task["actions"]],
            "observations": [
                {"id": item["id"], "comparator": item.get("comparator")}
                for item in result.get("observations", [])
            ],
        }
        (trace_root / f"{task['id']}.json").write_text(
            json.dumps(trace, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def _visual_worker(
    declaration: Mapping[str, Any],
    *,
    candidate_root: Path,
    fixture_root: Path,
    reference_root: Path,
    browser_settings: Mapping[str, Any],
    ready_path: str,
    worker_root: Path,
    heatmap_root: Path,
    screenshot_root: Path,
    worker_identity: str,
    mailbox_capability: str | None,
    cpu_limit: int | None,
    memory_limit_mb: int | None,
    storage_limit_mb: int | None,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    identifier = declaration["id"]
    deadline = time.monotonic() + float(declaration["timeout_sec"])
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshot = screenshot_root / f"{identifier}.png"
    deployment = CandidateProcess(
        candidate_root,
        _port(),
        worker_root / "data",
        f"worker-{worker_identity}",
        mailbox_capability=mailbox_capability,
        audit_prefix=worker_root / "audit" / "candidate",
        cpu_limit=cpu_limit,
        memory_limit_mb=memory_limit_mb,
        storage_limit_mb=storage_limit_mb,
        isolation_uid=_isolation_uid(),
    )

    def audited(result: dict[str, Any]) -> dict[str, Any]:
        deployment.stop()
        if deployment.write_violations():
            return {
                "checkpoint_id": identifier,
                "status": "failed",
                "reason": "CANDIDATE_WRITE_OUTSIDE_DATA_DIR",
                "ssim": 0.0,
                "regions": [],
            }
        if deployment.network_violations():
            return {
                "checkpoint_id": identifier,
                "status": "failed",
                "reason": "CANDIDATE_EXTERNAL_NETWORK_ATTEMPT",
                "ssim": 0.0,
                "regions": [],
            }
        if deployment.ipc_violations():
            return {
                "checkpoint_id": identifier,
                "status": "failed",
                "reason": "CANDIDATE_SHARED_IPC_ATTEMPT",
                "ssim": 0.0,
                "regions": [],
            }
        return result

    try:
        deployment.start()
        if not deployment.ready(
            ready_path, timeout=max(0.1, min(deadline - time.monotonic(), 30.0))
        ):
            return audited(
                {
                    "checkpoint_id": identifier,
                    "status": "failed",
                    "reason": "CANDIDATE_DEPLOY_FAILED",
                    "ssim": 0.0,
                    "regions": [],
                }
            )
        base_url = f"http://127.0.0.1:{deployment.port}"

        def restart() -> str:
            deployment.stop()
            deployment.start()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not deployment.ready(
                ready_path, timeout=min(remaining, 30.0)
            ):
                raise RuntimeError("candidate visual restart failed")
            return base_url

        with sync_playwright() as playwright:
            browser = launch_deterministic_chromium(playwright)
            context = _browser_context(
                browser,
                browser_settings,
                declaration["viewport"],
                allowed_origin=base_url,
            )
            page = context.new_page()
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            page.set_default_timeout(max(1, remaining_ms))
            actors = {"primary": (context, page)}
            try:
                if remaining_ms <= 0:
                    raise TimeoutError("visual checkpoint deadline exceeded")
                url = urllib.parse.urljoin(
                    base_url.rstrip("/") + "/", declaration["route"].lstrip("/")
                )
                page.goto(url, wait_until="networkidle", timeout=remaining_ms)
                page.add_style_tag(
                    content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
                )
                page, _ = run_actions(
                    page,
                    declaration["actions"],
                    base_url=base_url,
                    fixture_root=fixture_root,
                    actors=actors,
                    captures={},
                    restart=restart,
                    mailbox_namespace=f"worker-{worker_identity}",
                    mailbox_credential=mailbox_capability,
                    actor_context_factory=lambda: _browser_context(
                        browser,
                        browser_settings,
                        declaration["viewport"],
                        allowed_origin=base_url,
                    ),
                    deadline=deadline,
                )
                page.evaluate("() => document.fonts?.ready")
                page.screenshot(
                    path=str(screenshot), full_page=False, animations="disabled"
                )
            except Exception as exc:
                return audited(
                    {
                        "checkpoint_id": identifier,
                        "status": "failed",
                        "reason": f"SCREENSHOT_UNREACHABLE:{type(exc).__name__}",
                        "ssim": 0.0,
                        "regions": [],
                    }
                )
            finally:
                for actor_context, _actor_page in actors.values():
                    if actor_context is not context:
                        actor_context.close()
                context.close()
                browser.close()
        result = compute_visual_checkpoint(
            reference_root / declaration["reference_image"],
            screenshot,
            declaration,
            heatmap_path=heatmap_root / f"{identifier}.png",
        )
        redact_visual_masks(screenshot, declaration)
        return audited(result)
    finally:
        deployment.stop()


def evaluate_visual_suite(
    suite: Mapping[str, Any],
    *,
    candidate_root: Path,
    fixture_root: Path,
    reference_root: Path,
    browser_settings: Mapping[str, Any],
    ready_path: str,
    working_root: Path,
    heatmap_root: Path,
    screenshot_root: Path,
    workers: int = 4,
    mailbox_sidecar: LocalMailboxSidecar | None = None,
    cpu_limit: int | None = None,
    memory_limit_mb: int | None = None,
    storage_limit_mb: int | None = None,
) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for declaration in suite["checkpoints"]:
            worker_identity = _opaque_worker_identity()
            namespace = f"worker-{worker_identity}"
            mailbox_capability = (
                secrets.token_hex(32) if mailbox_sidecar is not None else None
            )
            if mailbox_sidecar is not None and mailbox_capability is not None:
                mailbox_sidecar.register_namespace(namespace, mailbox_capability)
            future = executor.submit(
                _visual_worker,
                declaration,
                candidate_root=candidate_root,
                fixture_root=fixture_root,
                reference_root=reference_root,
                browser_settings=browser_settings,
                ready_path=ready_path,
                worker_root=working_root / f"worker-{worker_identity}",
                heatmap_root=heatmap_root,
                screenshot_root=screenshot_root,
                worker_identity=worker_identity,
                mailbox_capability=mailbox_capability,
                cpu_limit=cpu_limit,
                memory_limit_mb=memory_limit_mb,
                storage_limit_mb=storage_limit_mb,
            )
            futures[future] = declaration["id"]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["checkpoint_id"]] = result
    ordered = [results[item["id"]] for item in suite["checkpoints"]]
    isolation_failures = [
        item["reason"]
        for item in ordered
        if item["reason"]
        in {
            "CANDIDATE_WRITE_OUTSIDE_DATA_DIR",
            "CANDIDATE_EXTERNAL_NETWORK_ATTEMPT",
            "CANDIDATE_SHARED_IPC_ATTEMPT",
        }
    ]
    if isolation_failures:
        reason = sorted(isolation_failures)[0]
        ordered = [
            {
                "checkpoint_id": item["id"],
                "status": "failed",
                "reason": reason,
                "ssim": 0.0,
                "regions": [],
            }
            for item in suite["checkpoints"]
        ]
    values = [float(item["ssim"]) for item in ordered]
    return {
        "schema_version": VISUAL_RESULTS_SCHEMA,
        "checkpoints": ordered,
        "summary": {
            "minimum_ssim": min(values),
            "mean_ssim": sum(values) / len(values),
            "total": len(values),
        },
    }


@contextlib.contextmanager
def _mailbox_environment(
    config: Mapping[str, Any],
) -> Iterator[tuple[dict[str, Any], LocalMailboxSidecar | None]]:
    mode = config.get("mode")
    names = (
        "WEBSITEBENCH_MAILBOX_URL",
        "WEBSITEBENCH_MAILBOX_ALLOWLIST",
        "WEBSITEBENCH_SMTP_HOST",
        "WEBSITEBENCH_SMTP_PORT",
        "WEBSITEBENCH_MAILBOX_CREDENTIAL",
    )
    previous = {name: os.environ.get(name) for name in names}
    sidecar: LocalMailboxSidecar | None = None
    try:
        if mode == "local-sidecar":
            sidecar = LocalMailboxSidecar().start()
            os.environ.pop("WEBSITEBENCH_MAILBOX_CREDENTIAL", None)
            os.environ.update(
                {
                    "WEBSITEBENCH_MAILBOX_URL": sidecar.url,
                    "WEBSITEBENCH_MAILBOX_ALLOWLIST": "",
                    "WEBSITEBENCH_SMTP_HOST": "127.0.0.1",
                    "WEBSITEBENCH_SMTP_PORT": str(sidecar.smtp_port),
                }
            )
        elif mode == "external-proxy":
            gateway = os.environ.get("WEBSITEBENCH_MAILBOX_URL", "")
            parsed = urllib.parse.urlsplit(gateway)
            allowlist = {
                str(item).lower() for item in config.get("external_allowlist", [])
            }
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.hostname.lower() not in allowlist
            ):
                raise InvalidRun(
                    "external mailbox gateway is outside its exact HTTPS allowlist"
                )
            if not os.environ.get("WEBSITEBENCH_MAILBOX_CREDENTIAL"):
                raise InvalidRun(
                    "external mailbox credential was not injected at runtime"
                )
            os.environ["WEBSITEBENCH_MAILBOX_ALLOWLIST"] = ",".join(sorted(allowlist))
        else:
            raise InvalidRun(f"unsupported mailbox mode: {mode!r}")
        yield (
            {
                "schema_version": "websitebench.harbor.mailbox-runtime-evidence.v1",
                "mode": mode,
                "gateway": "loopback"
                if mode == "local-sidecar"
                else "allowlisted-https",
                "credential_injected": (
                    False
                    if mode == "local-sidecar"
                    else bool(os.environ.get("WEBSITEBENCH_MAILBOX_CREDENTIAL"))
                ),
                "external_allowlist": sorted(config.get("external_allowlist", [])),
                "sensitive_values_retained": False,
            },
            sidecar,
        )
    finally:
        if sidecar is not None:
            sidecar.close()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def evaluate_candidate(
    *,
    candidate_root: Path,
    task_suite_path: Path,
    visual_suite_path: Path,
    cicd_suite_path: Path,
    reference_observations_path: Path,
    fixture_root: Path,
    output: Path,
    browser_settings: Mapping[str, Any],
    ready_path: str = "/healthz",
    workers: int = 4,
    mailbox: Mapping[str, Any] | None = None,
    network_policy_path: Path | None = None,
    budgets: Mapping[str, Any] | None = None,
    reference_render_environment: Mapping[str, Any] | None = None,
) -> int:
    """Evaluate one immutable candidate tree and emit all v2 result artifacts."""

    mailbox_config = mailbox or {"mode": "local-sidecar"}
    allowed_hosts = {
        str(item).lower()
        for item in mailbox_config.get("external_allowlist", [])
        if isinstance(item, str)
    }
    output.mkdir(parents=True, exist_ok=True)
    try:
        sandbox_fingerprint = sandbox_preflight()
    except OSError as exc:
        raise InvalidRun("verifier kernel sandbox is unavailable") from exc
    (output / "sandbox-runtime-evidence.json").write_text(
        json.dumps(sandbox_fingerprint, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with _runtime_network_audit(allowed_hosts) as network_audit:
        try:
            with _mailbox_environment(mailbox_config) as mailbox_runtime:
                mailbox_evidence, mailbox_sidecar = mailbox_runtime
                result = _evaluate_candidate_inner(
                    candidate_root=candidate_root,
                    task_suite_path=task_suite_path,
                    visual_suite_path=visual_suite_path,
                    cicd_suite_path=cicd_suite_path,
                    reference_observations_path=reference_observations_path,
                    fixture_root=fixture_root,
                    output=output,
                    browser_settings=browser_settings,
                    ready_path=ready_path,
                    workers=workers,
                    network_policy_path=network_policy_path,
                    budgets=budgets or {},
                    reference_render_environment=reference_render_environment,
                    mailbox_sidecar=mailbox_sidecar,
                )
                (output / "mailbox-runtime-evidence.json").write_text(
                    json.dumps(mailbox_evidence, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                return result
        finally:
            (output / "network-runtime-evidence.json").write_text(
                json.dumps(network_audit.evidence(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )


def _evaluate_candidate_inner(
    *,
    candidate_root: Path,
    task_suite_path: Path,
    visual_suite_path: Path,
    cicd_suite_path: Path,
    reference_observations_path: Path,
    fixture_root: Path,
    output: Path,
    browser_settings: Mapping[str, Any],
    ready_path: str,
    workers: int,
    network_policy_path: Path | None,
    budgets: Mapping[str, Any],
    reference_render_environment: Mapping[str, Any] | None,
    mailbox_sidecar: LocalMailboxSidecar | None,
) -> int:

    if workers != 4:
        raise InvalidRun("formal Harbor v2 evaluation requires exactly four workers")
    if not isinstance(reference_render_environment, Mapping):
        raise InvalidRun("reference render environment is missing")
    verify_render_environment(browser_settings, reference_render_environment)
    task_suite = _load_json(task_suite_path)
    visual_suite = _load_json(visual_suite_path)
    cicd_suite = _load_json(cicd_suite_path)
    reference_observations = _load_json(reference_observations_path)
    network_policy = (
        _load_json(network_policy_path) if network_policy_path is not None else None
    )
    _validate_reference_observations(
        reference_observations,
        task_suite,
        visual_suite,
        reference_observations_path.parent,
    )
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="websitebench-v2-evaluate-") as temporary:
        working = Path(temporary)
        working.chmod(0o711)
        # A failed public entrypoint is a valid candidate outcome: task and visual
        # checks score zero. A verifier exception remains INVALID_RUN.
        probe_identity = _opaque_worker_identity()
        probe_namespace = f"worker-{probe_identity}"
        probe_capability = (
            secrets.token_hex(32) if mailbox_sidecar is not None else None
        )
        if mailbox_sidecar is not None and probe_capability is not None:
            mailbox_sidecar.register_namespace(probe_namespace, probe_capability)
        probe = CandidateProcess(
            candidate_root,
            _port(),
            working / "workers" / f"worker-{probe_identity}" / "data",
            probe_namespace,
            mailbox_capability=probe_capability,
            audit_prefix=(
                working / "workers" / f"worker-{probe_identity}" / "audit" / "candidate"
            ),
            cpu_limit=(int(budgets["cpus"]) if "cpus" in budgets else None),
            memory_limit_mb=(
                int(budgets["memory_mb"]) if "memory_mb" in budgets else None
            ),
            storage_limit_mb=(
                int(budgets["storage_mb"]) if "storage_mb" in budgets else None
            ),
            isolation_uid=_isolation_uid(),
        )
        probe_started = False
        try:
            probe.start()
            probe_started = True
            deploy_ready = probe.ready(ready_path, timeout=30)
        except OSError:
            deploy_ready = False
        finally:
            probe.stop()
        if probe_started and (
            probe.write_violations()
            or probe.network_violations()
            or probe.ipc_violations()
        ):
            deploy_ready = False

        if deploy_ready:
            task_results = evaluate_task_suite(
                task_suite,
                reference_observations,
                candidate_root=candidate_root,
                fixture_root=fixture_root,
                browser_settings=browser_settings,
                ready_path=ready_path,
                working_root=working / "workers",
                trace_root=output / "traces",
                workers=workers,
                mailbox_sidecar=mailbox_sidecar,
                cpu_limit=(int(budgets["cpus"]) if "cpus" in budgets else None),
                memory_limit_mb=(
                    int(budgets["memory_mb"]) if "memory_mb" in budgets else None
                ),
                storage_limit_mb=(
                    int(budgets["storage_mb"]) if "storage_mb" in budgets else None
                ),
            )
            visual_results = evaluate_visual_suite(
                visual_suite,
                candidate_root=candidate_root,
                fixture_root=fixture_root,
                reference_root=reference_observations_path.parent,
                browser_settings=browser_settings,
                ready_path=ready_path,
                working_root=working / "workers",
                heatmap_root=output / "heatmaps",
                screenshot_root=output / "screenshots",
                workers=workers,
                mailbox_sidecar=mailbox_sidecar,
                cpu_limit=(int(budgets["cpus"]) if "cpus" in budgets else None),
                memory_limit_mb=(
                    int(budgets["memory_mb"]) if "memory_mb" in budgets else None
                ),
                storage_limit_mb=(
                    int(budgets["storage_mb"]) if "storage_mb" in budgets else None
                ),
            )
            isolation_reasons = {
                item["reason"]
                for item in [
                    *task_results["tasks"],
                    *visual_results["checkpoints"],
                ]
                if item["reason"]
                in {
                    "CANDIDATE_WRITE_OUTSIDE_DATA_DIR",
                    "CANDIDATE_EXTERNAL_NETWORK_ATTEMPT",
                    "CANDIDATE_SHARED_IPC_ATTEMPT",
                }
            }
            if isolation_reasons:
                # Task and visual runs share the verifier host.  Invalidate both
                # suites after any side-channel attempt so one sacrificial run
                # cannot contaminate a different scoring phase.
                reason = sorted(isolation_reasons)[0]
                task_results = synthesize_deploy_failure(task_suite, reason)
                visual_results = {
                    "schema_version": VISUAL_RESULTS_SCHEMA,
                    "checkpoints": [
                        {
                            "checkpoint_id": item["id"],
                            "status": "failed",
                            "reason": reason,
                            "ssim": 0.0,
                            "regions": [],
                        }
                        for item in visual_suite["checkpoints"]
                    ],
                    "summary": {
                        "minimum_ssim": 0.0,
                        "mean_ssim": 0.0,
                        "total": len(visual_suite["checkpoints"]),
                    },
                }
                _write_task_traces(task_suite, task_results, output / "traces")
        else:
            task_results = synthesize_deploy_failure(
                task_suite, "CANDIDATE_DEPLOY_FAILED"
            )
            visual_results = {
                "schema_version": VISUAL_RESULTS_SCHEMA,
                "checkpoints": [
                    {
                        "checkpoint_id": item["id"],
                        "status": "failed",
                        "reason": "CANDIDATE_DEPLOY_FAILED",
                        "ssim": 0.0,
                        "regions": [],
                    }
                    for item in visual_suite["checkpoints"]
                ],
                "summary": {
                    "minimum_ssim": 0.0,
                    "mean_ssim": 0.0,
                    "total": len(visual_suite["checkpoints"]),
                },
            }
            _write_task_traces(task_suite, task_results, output / "traces")
        cicd_results = run_platform_cicd(
            candidate_root,
            cicd_suite,
            ready_path=ready_path,
            startup_timeout=min(float(budgets.get("startup_timeout_sec", 30)), 30),
            memory_limit_mb=(
                int(budgets["memory_mb"]) if "memory_mb" in budgets else None
            ),
            storage_limit_mb=(
                int(budgets["storage_mb"]) if "storage_mb" in budgets else None
            ),
            cpu_limit=(int(budgets["cpus"]) if "cpus" in budgets else None),
            network_policy=network_policy,
            trusted_runner_root=fixture_root.parent,
            output_root=working / "cicd",
            mailbox_sidecar=mailbox_sidecar,
        )

    paths = {
        "task": output / "task-results.json",
        "visual": output / "visual-results.json",
        "cicd": output / "cicd-results.json",
    }
    for key, value in (
        ("task", task_results),
        ("visual", visual_results),
        ("cicd", cicd_results),
    ):
        paths[key].write_text(
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return score_results(
        task_suite=task_suite_path,
        task_results=paths["task"],
        visual_suite=visual_suite_path,
        visual_results=paths["visual"],
        cicd_suite=cicd_suite_path,
        cicd_results=paths["cicd"],
        output=output,
    )
