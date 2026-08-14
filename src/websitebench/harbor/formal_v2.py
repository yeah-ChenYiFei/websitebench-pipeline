"""Formal evaluator for sealed Harbor compile-executable 200-case bundles."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

try:  # pragma: no cover - formal evaluator is Linux-only
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

from . import sandbox_v2
from .case_protocol import (
    CaseProtocolError,
    canonical_json_bytes,
    compute_case_evaluation,
    file_sha256,
    load_case_manifest,
    publish_case_evaluation,
    publish_invalid_run,
    synthesize_zero_results,
    validate_case_references,
)
from .compiler_v2 import (
    MAX_LOG_BYTES,
    CompilerSandboxError,
    ExecutableRuntime,
    compile_candidate,
    validate_runtime_lifecycle,
)
from .dsl_v2 import DslExecutionError, observe, run_actions
from .evaluate import _browser_context
from .executors_v2 import (
    BrowserUseRuntime,
    CandidateCaseFailure,
    CaseExecutionContext,
    CaseOutcome,
    DualExecutorRunner,
    InfrastructureCaseFailure,
    compile_neutral_actions,
    execute_case_manifest,
    sanitized_browser_use_environment,
)
from .judge_v2 import (
    DETERMINISTIC_CHROMIUM_ARGS,
    compute_visual_checkpoint,
    evaluate_observations,
    launch_deterministic_chromium,
    redact_visual_masks,
)
from .mailbox import redact_text


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaseProtocolError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise CaseProtocolError(f"{label} must be a JSON object")
    return value


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_cdp(process: subprocess.Popen[bytes], port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=0.25) as response:
                value = json.loads(response.read(1024 * 1024))
            if response.status == 200 and isinstance(
                value.get("webSocketDebuggerUrl"), str
            ):
                return True
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.025)
    return False


def _stop_group(process: subprocess.Popen[bytes], timeout: float = 10.0) -> bool:
    if process.poll() is not None:
        return True
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return False
        return False


def _target_url(base_url: str, path: str) -> str:
    target = urllib.parse.urljoin(base_url.rstrip("/") + "/", path)
    expected = urllib.parse.urlsplit(base_url)
    actual = urllib.parse.urlsplit(target)
    if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
        raise CandidateCaseFailure("direct request escaped the candidate origin")
    return target


def _request(
    opener: urllib.request.OpenerDirector,
    *,
    url: str,
    method: str,
    body: Any,
    headers: Mapping[str, Any],
    timeout: float,
) -> tuple[int, bytes]:
    payload: bytes | None = None
    request_headers = {str(key): str(value) for key, value in headers.items()}
    if body is not None:
        if isinstance(body, (dict, list)):
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = bytes(body)
    request = urllib.request.Request(
        url, data=payload, headers=request_headers, method=method.upper()
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), response.read(16 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(16 * 1024 * 1024)


def _json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise CandidateCaseFailure("JSON pointer must start with '/'")
    current = value
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, Mapping):
            current = current[key]
        else:
            raise KeyError(key)
    return current


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class FormalCaseRunner:
    def __init__(
        self,
        *,
        artifact: Any,
        task_suite: Mapping[str, Any],
        visual_suite: Mapping[str, Any],
        cicd_suite: Mapping[str, Any],
        reference: Mapping[str, Any],
        fixture_root: Path,
        browser_settings: Mapping[str, Any],
        browser_use_settings: Mapping[str, Any],
        timezone: str,
    ) -> None:
        self.artifact = artifact
        self.tasks = {str(item["id"]): item for item in task_suite["tasks"]}
        self.visuals = {
            str(item["id"]): item for item in visual_suite["checkpoints"]
        }
        self.checks = {str(item["id"]): item for item in cicd_suite["checks"]}
        self.reference = reference
        self.fixture_root = fixture_root
        self.browser_settings = browser_settings
        self.browser_use_settings = browser_use_settings
        self.timezone = timezone

    def _runtime(
        self, root: Path, context: CaseExecutionContext, executor: str
    ) -> ExecutableRuntime:
        data = root / "data"
        return ExecutableRuntime(
            self.artifact.build_root,
            data,
            _port(),
            context.seed,
            self.timezone,
            data / f"{executor}.log",
            expected_tree_sha256=self.artifact.tree_sha256,
        )

    def direct(
        self, case: Mapping[str, Any], context: CaseExecutionContext, root: Path
    ) -> CaseOutcome:
        if case["kind"] == "cicd":
            return self._cicd(case, context, root)
        declaration = self.tasks[str(case["task_id"])]
        runtime = self._runtime(root, context, "direct")
        runtime.start()
        try:
            if not runtime.ready(timeout=min(30.0, float(declaration["timeout_sec"]))):
                raise CandidateCaseFailure("compiled runtime did not become healthy")
            base_url = f"http://127.0.0.1:{runtime.port}"
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(CookieJar()), _NoRedirect()
            )
            captures: dict[str, Any] = {}
            deadline = time.monotonic() + float(declaration["timeout_sec"])
            for action in declaration["actions"]:
                if action["op"] != "api":
                    raise InfrastructureCaseFailure(
                        f"direct {case['kind']} case contains browser action {action['op']!r}"
                    )
                status, body = _request(
                    opener,
                    url=_target_url(base_url, str(action.get("path", "/"))),
                    method=str(action.get("method", "GET")),
                    body=action.get("body"),
                    headers=action.get("headers", {}),
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                capture_as = action.get("capture_as")
                if isinstance(capture_as, str):
                    try:
                        response_json = json.loads(body.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError):
                        response_json = None
                    captures[capture_as] = {
                        "status": status,
                        "json": response_json,
                    }
            actual: dict[str, Any] = {}
            for observation in declaration["observations"]:
                kind = observation["kind"]
                capture_as = observation.get("capture_as")
                if isinstance(capture_as, str):
                    captured = captures.get(capture_as)
                    if not isinstance(captured, Mapping):
                        raise CandidateCaseFailure("direct API capture is unavailable")
                    actual[observation["id"]] = (
                        captured["status"]
                        if kind == "api_status"
                        else _json_pointer(
                            captured["json"], str(observation.get("json_pointer", ""))
                        )
                    )
                elif kind in {"api_status", "api_json"}:
                    status, body = _request(
                        opener,
                        url=_target_url(base_url, str(observation.get("path", "/"))),
                        method="GET",
                        body=None,
                        headers={},
                        timeout=max(0.1, deadline - time.monotonic()),
                    )
                    if kind == "api_status":
                        actual[observation["id"]] = status
                    else:
                        payload = json.loads(body.decode("utf-8"))
                        actual[observation["id"]] = _json_pointer(
                            payload, str(observation.get("json_pointer", ""))
                        )
                else:
                    raise InfrastructureCaseFailure(
                        f"direct case declares browser observation {kind!r}"
                    )
            frozen = self.reference["tasks"][str(case["task_id"])]
            passed, _verdicts = evaluate_observations(
                actual, declaration["observations"], frozen["observations"]
            )
            return CaseOutcome(
                functional={"direct": passed, "playwright": None, "browser_use": None},
                reason=(
                    "direct terminal observations matched"
                    if passed
                    else "direct terminal observations differed"
                ),
            )
        except (CandidateCaseFailure, InfrastructureCaseFailure):
            raise
        except (OSError, ValueError, KeyError, TimeoutError) as exc:
            raise CandidateCaseFailure(f"direct task failed: {type(exc).__name__}") from exc
        finally:
            if not runtime.stop(timeout=10.0):
                raise CandidateCaseFailure("compiled runtime ignored SIGTERM")

    def _cicd(
        self, case: Mapping[str, Any], context: CaseExecutionContext, root: Path
    ) -> CaseOutcome:
        declaration = self.checks[str(case["cicd_check_id"])]
        if declaration["kind"] == "platform":
            identifier = str(declaration["id"])
            if identifier.startswith("platform::deploy/"):
                evidence = validate_runtime_lifecycle(
                    self.artifact,
                    port=_port(),
                    seed=context.seed,
                    working_root=root / "lifecycle",
                    timezone=self.timezone,
                )
                passed = bool(evidence["valid"])
                reason = "trusted compiled lifecycle probe"
            else:
                passed = True
                reason = "trusted quarantine/compiler/platform assertion"
            return CaseOutcome(
                functional={"direct": passed, "playwright": None, "browser_use": None},
                reason=reason,
            )
        runner = self.fixture_root / str(declaration["runner"])
        if not runner.is_file() or runner.is_symlink():
            raise InfrastructureCaseFailure("trusted CI/CD runner is unavailable")
        completed = subprocess.run(
            [str(runner)],
            cwd=self.fixture_root,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "WEBSITEBENCH_CANDIDATE_ROOT": str(self.artifact.build_root),
                "SEED": str(context.seed),
                "TZ": self.timezone,
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=float(declaration["timeout_sec"]),
            check=False,
        )
        return CaseOutcome(
            functional={
                "direct": completed.returncode == 0,
                "playwright": None,
                "browser_use": None,
            },
            reason=f"trusted check exit status {completed.returncode}",
        )

    def playwright(
        self, case: Mapping[str, Any], context: CaseExecutionContext, root: Path
    ) -> CaseOutcome:
        return self._browser(case, context, root, executor="playwright")

    def browser_use(
        self, case: Mapping[str, Any], context: CaseExecutionContext, root: Path
    ) -> CaseOutcome:
        browser_use = BrowserUseRuntime(
            root / "browser-use-home", Path(str(self.browser_use_settings["venv"]))
        )
        browser_use.assert_pinned()
        declaration = self.tasks[str(case["task_id"])]
        compile_neutral_actions(declaration["actions"], executor="browser-use")
        runtime = self._runtime(root, context, "browser-use")
        cdp_port = _port()
        environment = sanitized_browser_use_environment(
            os.environ,
            runtime=browser_use,
            candidate_port=runtime.port,
            cdp_port=cdp_port,
            seed=context.seed,
            timezone=self.timezone,
        )
        environment.update(
            {
                "ANONYMIZED_TELEMETRY": "false",
                "BROWSER_USE_DISABLE_EXTENSIONS": "1",
                "BROWSER_USE_LOGGING_LEVEL": "critical",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        chromium: subprocess.Popen[bytes] | None = None
        chromium_log = None
        controller: ThreadingHTTPServer | None = None
        controller_thread: threading.Thread | None = None
        try:
            runtime.start()
            if not runtime.ready(timeout=min(30.0, float(declaration["timeout_sec"]))):
                raise CandidateCaseFailure("compiled runtime did not become healthy")
            base_url = f"http://127.0.0.1:{runtime.port}"
            controller_port = _port()
            capability = hashlib.sha256(
                f"restart:{context.case_id}:{context.seed}".encode("utf-8")
            ).hexdigest()

            class RestartHandler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:
                    if (
                        self.path != "/restart"
                        or self.headers.get("X-WebsiteBench-Restart") != capability
                    ):
                        self.send_error(403)
                        return
                    if not runtime.stop(timeout=10.0):
                        self.send_error(500)
                        return
                    try:
                        runtime.start()
                        ready = runtime.ready(timeout=10.0)
                    except Exception:
                        ready = False
                    if not ready:
                        self.send_error(500)
                        return
                    body = b'{"status":"ok"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, format: str, *args: Any) -> None:
                    return

            controller = ThreadingHTTPServer(
                ("127.0.0.1", controller_port), RestartHandler
            )
            controller_thread = threading.Thread(
                target=controller.serve_forever,
                name=f"harbor-restart-{context.case_id}",
                daemon=True,
            )
            controller_thread.start()
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                chromium_path = playwright.chromium.executable_path
            profile = Path(environment["CHROME_USER_DATA_DIR"])
            profile.mkdir(parents=True, exist_ok=True, mode=0o700)
            chromium_log_path = root / "browser-use-chromium.log"
            chromium_log = chromium_log_path.open("wb")

            def browser_sandbox() -> None:
                if resource is not None:
                    resource.setrlimit(
                        resource.RLIMIT_FSIZE, (MAX_LOG_BYTES, MAX_LOG_BYTES)
                    )
                    resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 4096))
                sandbox_v2._landlock(
                    Path(chromium_path).resolve().parent,
                    browser_use.root,
                    cdp_port,
                    {runtime.port, cdp_port, controller_port},
                    read_paths=(Path("/proc"),),
                )

            chromium = subprocess.Popen(
                [
                    chromium_path,
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--disable-breakpad",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-domain-reliability",
                    "--disable-extensions",
                    "--disable-features=MediaRouter,OptimizationHints",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--no-default-browser-check",
                    "--no-first-run",
                    "--password-store=basic",
                    "--use-mock-keychain",
                    f"--lang={self.browser_settings.get('locale', 'en-US')}",
                    "--remote-debugging-address=127.0.0.1",
                    f"--remote-debugging-port={cdp_port}",
                    f"--user-data-dir={profile}",
                    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
                    *DETERMINISTIC_CHROMIUM_ARGS,
                    "about:blank",
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=chromium_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                preexec_fn=browser_sandbox,
            )
            if not _wait_cdp(chromium, cdp_port):
                raise InfrastructureCaseFailure(
                    "Browser Use deterministic Chromium did not expose CDP"
                )
            input_path = browser_use.root / "browser-use-input.json"
            output_path = browser_use.root / "browser-use-output.json"
            actions = json.loads(json.dumps(declaration["actions"]))
            for action in actions:
                if action.get("op") == "upload":
                    fixture = (self.fixture_root / str(action["fixture"])).resolve()
                    if self.fixture_root.resolve() not in fixture.parents:
                        raise InfrastructureCaseFailure(
                            "upload fixture escaped the verifier fixture root"
                        )
                    action["fixture"] = str(fixture)
            input_path.write_bytes(
                canonical_json_bytes(
                    {
                        "base_url": base_url,
                        "cdp_url": f"http://127.0.0.1:{cdp_port}",
                        "timeout_sec": declaration["timeout_sec"],
                        "viewport": {"width": 1280, "height": 720},
                        "actions": actions,
                        "observations": declaration["observations"],
                        "mailbox_values": {},
                        "restart_controller": {
                            "url": f"http://127.0.0.1:{controller_port}/restart",
                            "capability": capability,
                        },
                    }
                )
            )

            def adapter_sandbox() -> None:
                if resource is not None:
                    resource.setrlimit(
                        resource.RLIMIT_FSIZE, (MAX_LOG_BYTES, MAX_LOG_BYTES)
                    )
                    resource.setrlimit(resource.RLIMIT_NOFILE, (2048, 2048))
                sandbox_v2._landlock(
                    browser_use.venv,
                    browser_use.root,
                    cdp_port,
                    {runtime.port, cdp_port, controller_port},
                    read_paths=(
                        Path(__file__).resolve().parent,
                        self.fixture_root.resolve(),
                        Path("/proc"),
                    ),
                )

            adapter_log_path = root / "browser-use-adapter.log"
            with adapter_log_path.open("wb") as adapter_log:
                completed = subprocess.run(
                    [
                        str(browser_use.python),
                        "-I",
                        str(Path(__file__).with_name("browser_use_adapter.py")),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                    ],
                    cwd=root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=adapter_log,
                    stderr=subprocess.STDOUT,
                    timeout=float(declaration["timeout_sec"]) + 15.0,
                    check=False,
                    start_new_session=True,
                    preexec_fn=adapter_sandbox,
                )
                adapter_log.flush()
                os.fsync(adapter_log.fileno())
            if adapter_log_path.stat().st_size > MAX_LOG_BYTES:
                raise InfrastructureCaseFailure(
                    "Browser Use adapter log exceeded 256 MiB"
                )
            if not output_path.is_file():
                raise InfrastructureCaseFailure(
                    f"Browser Use adapter failed before result publication: {completed.returncode}"
                )
            adapter_result = json.loads(output_path.read_text(encoding="utf-8"))
            if adapter_result.get("status") != "ok":
                return CaseOutcome(
                    functional={
                        "direct": None,
                        "playwright": None,
                        "browser_use": False,
                    },
                    reason=f"browser-use candidate behavior failed: {adapter_result.get('error')}",
                )
            frozen = self.reference["tasks"][str(case["task_id"])]
            passed, _verdicts = evaluate_observations(
                adapter_result["actual"],
                declaration["observations"],
                frozen["observations"],
            )
            return CaseOutcome(
                functional={
                    "direct": None,
                    "playwright": None,
                    "browser_use": passed,
                },
                reason=(
                    "browser-use terminal observations matched"
                    if passed
                    else "browser-use terminal observations differed"
                ),
            )
        except (CandidateCaseFailure, InfrastructureCaseFailure):
            raise
        except subprocess.TimeoutExpired as exc:
            raise CandidateCaseFailure(
                "Browser Use candidate journey timed out"
            ) from exc
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise InfrastructureCaseFailure(
                f"Browser Use infrastructure failed: {type(exc).__name__}:{exc}"
            ) from exc
        finally:
            if controller is not None:
                controller.shutdown()
                controller.server_close()
            if controller_thread is not None:
                controller_thread.join(timeout=5)
            if chromium is not None and not _stop_group(chromium):
                raise InfrastructureCaseFailure(
                    "Browser Use Chromium process group ignored SIGTERM"
                )
            if chromium_log is not None:
                chromium_log.flush()
                os.fsync(chromium_log.fileno())
                chromium_log.close()
            if not runtime.stop(timeout=10.0):
                raise CandidateCaseFailure("compiled runtime ignored SIGTERM")

    def _browser(
        self,
        case: Mapping[str, Any],
        context: CaseExecutionContext,
        root: Path,
        *,
        executor: str,
    ) -> CaseOutcome:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        declaration = self.tasks[str(case["task_id"])]
        compile_neutral_actions(declaration["actions"], executor=executor)
        runtime = self._runtime(root, context, executor)
        runtime.start()
        screenshot_values: list[dict[str, Any]] = []
        browser = None
        try:
            if not runtime.ready(timeout=min(30.0, float(declaration["timeout_sec"]))):
                raise CandidateCaseFailure("compiled runtime did not become healthy")
            base_url = f"http://127.0.0.1:{runtime.port}"
            deadline = time.monotonic() + float(declaration["timeout_sec"])
            with sync_playwright() as playwright:
                browser = launch_deterministic_chromium(playwright)
                browser_context = _browser_context(
                    browser, self.browser_settings, allowed_origin=base_url
                )
                page = browser_context.new_page()
                actors = {"primary": (browser_context, page)}
                captures: dict[str, Any] = {}

                def restart() -> str:
                    if not runtime.stop(timeout=10.0):
                        raise CandidateCaseFailure("runtime ignored SIGTERM before restart")
                    runtime.start()
                    if not runtime.ready(timeout=min(30.0, deadline - time.monotonic())):
                        raise CandidateCaseFailure("runtime restart failed")
                    return base_url

                try:
                    page, current_base = run_actions(
                        page,
                        declaration["actions"],
                        base_url=base_url,
                        fixture_root=self.fixture_root,
                        actors=actors,
                        captures=captures,
                        restart=restart,
                        actor_context_factory=lambda: _browser_context(
                            browser, self.browser_settings, allowed_origin=base_url
                        ),
                        deadline=deadline,
                    )
                    actual = {
                        observation["id"]: observe(
                            page,
                            observation,
                            base_url=current_base,
                            captures=captures,
                            timeout_ms=max(
                                1, int((deadline - time.monotonic()) * 1000)
                            ),
                        )
                        for observation in declaration["observations"]
                    }
                    frozen = self.reference["tasks"][str(case["task_id"])]
                    passed, _verdicts = evaluate_observations(
                        actual, declaration["observations"], frozen["observations"]
                    )
                    if executor == "playwright" and passed:
                        screenshot_values = self._visual_checkpoints(
                            case, browser, base_url, runtime, root, deadline
                        )
                    return CaseOutcome(
                        functional={
                            "direct": None,
                            "playwright": passed if executor == "playwright" else None,
                            "browser_use": passed if executor == "browser-use" else None,
                        },
                        visuals=screenshot_values,
                        reason=(
                            f"{executor} terminal observations matched"
                            if passed
                            else f"{executor} terminal observations differed"
                        ),
                    )
                finally:
                    for actor_context, _actor_page in actors.values():
                        if actor_context is not browser_context:
                            actor_context.close()
                    browser_context.close()
                    browser.close()
                    browser = None
        except (CandidateCaseFailure, InfrastructureCaseFailure):
            raise
        except DslExecutionError as exc:
            raise CandidateCaseFailure(f"{executor} DSL failed: {exc}") from exc
        except PlaywrightError as exc:
            raise CandidateCaseFailure(f"{executor} browser assertion failed") from exc
        except (OSError, TimeoutError, ValueError, KeyError) as exc:
            raise InfrastructureCaseFailure(
                f"{executor} infrastructure failed: {type(exc).__name__}:{exc}"
            ) from exc
        finally:
            if browser is not None:
                browser.close()
            if not runtime.stop(timeout=10.0):
                raise CandidateCaseFailure("compiled runtime ignored SIGTERM")

    def _visual_checkpoints(
        self,
        case: Mapping[str, Any],
        browser: Any,
        base_url: str,
        runtime: ExecutableRuntime,
        root: Path,
        deadline: float,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for checkpoint_id in case.get("visual_checkpoint_ids", []):
            declaration = self.visuals[str(checkpoint_id)]
            context = _browser_context(
                browser,
                self.browser_settings,
                declaration["viewport"],
                allowed_origin=base_url,
            )
            page = context.new_page()
            actors = {"primary": (context, page)}
            try:
                page.goto(
                    _target_url(base_url, str(declaration["route"])),
                    wait_until="networkidle",
                    timeout=max(1, int((deadline - time.monotonic()) * 1000)),
                )
                page, _current = run_actions(
                    page,
                    declaration["actions"],
                    base_url=base_url,
                    fixture_root=self.fixture_root,
                    actors=actors,
                    captures={},
                    deadline=deadline,
                )
                page.add_style_tag(
                    content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
                )
                page.evaluate("() => document.fonts?.ready")
                screenshot = root / "screenshots" / f"{checkpoint_id}.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(screenshot), full_page=False, animations="disabled"
                )
                reference = self.fixture_root / str(declaration["reference_image"])
                heatmap = root / "heatmaps" / f"{checkpoint_id}.png"
                scored = compute_visual_checkpoint(
                    reference,
                    screenshot,
                    declaration,
                    heatmap_path=heatmap,
                )
                redact_visual_masks(screenshot, declaration)
                scored_area = sum(int(item["area"]) for item in scored["regions"])
                if scored_area <= 0:
                    # A candidate screenshot size/read failure has V=0.  Keep a
                    # positive declared area so the exact result schema remains
                    # valid and the failure stays in the 200-case denominator.
                    scored_area = sum(
                        int(region["rect"]["width"])
                        * int(region["rect"]["height"])
                        for region in declaration["regions"]
                    )
                results.append(
                    {
                        "checkpoint_id": checkpoint_id,
                        "area": scored_area,
                        "ssim": float(scored["ssim"]),
                    }
                )
                if float(scored["ssim"]) == 1.0:
                    screenshot.unlink(missing_ok=True)
                    heatmap.unlink(missing_ok=True)
            finally:
                context.close()
        return results


def _collect_artifacts(root: Path, build_log: Path | None) -> dict[str, bytes]:
    artifacts: dict[str, bytes] = {}
    if build_log is not None and build_log.is_file():
        artifacts["build.log"] = redact_text(
            build_log.read_text(encoding="utf-8", errors="replace")
        ).encode("utf-8")
    runtime_logs = sorted(root.rglob("*.log"))
    if runtime_logs:
        runtime_payload = b"".join(
            f"== {path.relative_to(root).as_posix()} ==\n".encode("utf-8")
            + redact_text(
                path.read_text(encoding="utf-8", errors="replace")
            ).encode("utf-8")
            for path in runtime_logs
        )
        if len(runtime_payload) > MAX_LOG_BYTES:
            raise InfrastructureCaseFailure("aggregate runtime logs exceeded 256 MiB")
        artifacts["runtime.log"] = runtime_payload
    for directory in ("screenshots", "heatmaps"):
        for path in root.rglob(f"{directory}/*.png"):
            artifacts[f"failures/{path.relative_to(root).as_posix()}"] = (
                path.read_bytes()
            )
    return artifacts


def evaluate_case_candidate(
    *,
    candidate_root: Path,
    case_manifest_path: Path,
    task_suite_path: Path,
    visual_suite_path: Path,
    cicd_suite_path: Path,
    reference_observations_path: Path,
    fixture_root: Path,
    output: Path,
    browser_settings: Mapping[str, Any],
    browser_use_settings: Mapping[str, Any],
    build_timeout_sec: float = 900.0,
    timezone: str = "UTC",
    seed: int = 0,
) -> int:
    """Compile once, run isolated cases, and atomically publish a receipt."""

    manifest_hash = file_sha256(case_manifest_path)
    trial_id = hashlib.sha256(
        f"{manifest_hash}:{seed}".encode("ascii")
    ).hexdigest()[:24]
    try:
        manifest, _summary = load_case_manifest(
            case_manifest_path, allow_draft=False, allow_sealed=True
        )
        task_suite = _load(task_suite_path, "task suite")
        visual_suite = _load(visual_suite_path, "visual suite")
        cicd_suite = _load(cicd_suite_path, "CI/CD suite")
        reference = _load(reference_observations_path, "reference observations")
        if any(
            isinstance(check, dict) and check.get("kind") == "platform"
            for check in cicd_suite.get("checks", [])
        ):
            raise CaseProtocolError(
                "trusted platform checks are verifier infrastructure and cannot "
                "occupy an active site case"
            )
        validate_case_references(
            manifest,
            task_suite=task_suite,
            visual_suite=visual_suite,
            cicd_suite=cicd_suite,
        )
    except Exception as exc:
        publish_invalid_run(
            output,
            trial_id=trial_id,
            seed=seed,
            manifest_sha256=manifest_hash,
            reason=f"VERIFIER_INPUT:{type(exc).__name__}:{exc}",
        )
        return 2

    with tempfile.TemporaryDirectory(prefix="websitebench-formal-v2-") as temporary:
        work = Path(temporary)
        artifact = None
        try:
            artifact = compile_candidate(
                candidate_root,
                work / "compiler",
                timeout=build_timeout_sec,
                seed=seed,
                timezone=timezone,
            )
        except CompilerSandboxError as exc:
            result_set = synthesize_zero_results(
                manifest,
                trial_id=trial_id,
                seed=seed,
                reason=f"CANDIDATE_COMPILE_FAILED:{exc}",
            )
            result_set["manifest_sha256"] = manifest_hash
        else:
            callbacks = FormalCaseRunner(
                artifact=artifact,
                task_suite=task_suite,
                visual_suite=visual_suite,
                cicd_suite=cicd_suite,
                reference=reference,
                fixture_root=fixture_root,
                browser_settings=browser_settings,
                browser_use_settings=browser_use_settings,
                timezone=timezone,
            )
            result_set = execute_case_manifest(
                manifest,
                DualExecutorRunner(
                    direct=callbacks.direct,
                    playwright=callbacks.playwright,
                    browser_use=callbacks.browser_use,
                ),
                trial_id=trial_id,
                seed=seed,
                working_root=work / "cases",
                max_workers=4,
            )
            result_set["manifest_sha256"] = manifest_hash

        if result_set["status"] != "VALID_RUN":
            publish_invalid_run(
                output,
                trial_id=trial_id,
                seed=seed,
                manifest_sha256=manifest_hash,
                reason=str(result_set.get("reason") or "INFRASTRUCTURE_FAILURE"),
            )
            return 2
        try:
            result_bytes = canonical_json_bytes(result_set)
            evaluation, events = compute_case_evaluation(
                manifest,
                result_set,
                manifest_sha256=manifest_hash,
                result_sha256=hashlib.sha256(result_bytes).hexdigest(),
            )
            extra_artifacts = _collect_artifacts(
                work, artifact.build_log if artifact is not None else None
            )
            failed_events = [item for item in events if item["status"] != "passed"]
            if failed_events:
                extra_artifacts["failures/trace.jsonl"] = b"".join(
                    canonical_json_bytes(item) for item in failed_events
                )
            publish_case_evaluation(
                output,
                manifest=manifest,
                result_set=result_set,
                evaluation=evaluation,
                events=events,
                extra_artifacts=extra_artifacts,
            )
        except Exception as exc:
            publish_invalid_run(
                output,
                trial_id=trial_id,
                seed=seed,
                manifest_sha256=manifest_hash,
                reason=f"FINALIZATION_FAILURE:{type(exc).__name__}:{exc}",
            )
            return 2
    return 0


__all__ = ["evaluate_case_candidate"]
