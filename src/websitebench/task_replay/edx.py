"""Isolated upstream-agent playback for the edX offline clone.

The adapter deliberately keeps external task specifications immutable.  It
materializes an ephemeral upstream overlay, adds only local-runtime shims to
that overlay, and deletes its raw agent artifacts unless the configured
retention policy keeps them.  Its result is a local task-compatibility check, not a
canonical benchmark score.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence
from urllib.error import URLError
from urllib.request import urlopen


TASK_RUN_IDS: dict[str, str] = {
    "273": "harvardx-cs50x-2026",
    "1035": "mitx-ml-synthetic-2026",
    "1114": "harvardx-cs50x-2026",
    "1115": "ucsd-algs200x-2026",
    "1116": "ibm-py0101en-2026",
}
DEFAULT_TASK_IDS = tuple(TASK_RUN_IDS)
EVALUATOR_HOSTS = ("www.edx.org", "authn.edx.org")
DEFAULT_GATEWAY_IMAGE = "caddy:2.8.4-alpine"
DEFAULT_MODEL = "gpt-5-codex"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_API_TYPE = "openai-responses"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
FIXTURE_EMAIL = "jordan.rivera@websitebench.test"
FIXTURE_PASSWORD = "EdxPass456!"


class ReplayError(RuntimeError):
    """A local replay precondition or execution failure."""


@dataclass(frozen=True)
class ModelSettings:
    """The non-secret portion of an API model configuration."""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_type: str = DEFAULT_API_TYPE
    api_key_env: str = DEFAULT_API_KEY_ENV

    def require_api_key(self, environment: dict[str, str] | None = None) -> str:
        value = (environment or os.environ).get(self.api_key_env, "").strip()
        if not value:
            raise ReplayError(
                f"{self.api_key_env} is required for the Codex agent replay. "
                "Set it only in the current process environment; do not write it "
                "to this repository."
            )
        return value


@dataclass(frozen=True)
class GatewayBridge:
    """One isolated Docker network and its local TLS gateway address."""

    network_name: str
    gateway_ip: str
    probe_port: int


@dataclass(frozen=True)
class TaskReplayResult:
    """A sanitized outcome for one immutable task specification."""

    task_id: str
    task_sha256: str
    run_id: str
    upstream_exit_code: int | None
    intercepted: bool
    durable_enrollment: bool
    status: str
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "run_id": self.run_id,
            "upstream_exit_code": self.upstream_exit_code,
            "intercepted": self.intercepted,
            "durable_enrollment": self.durable_enrollment,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReplaySummary:
    """A non-secret summary of an isolated local replay suite."""

    results: tuple[TaskReplayResult, ...]
    dry_run: bool
    artifact_root: Path | None
    api_key_configured: bool

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": "local-offline-task-compatibility",
            "judge": "disabled",
            "dry_run": self.dry_run,
            "api_key_configured": self.api_key_configured,
            "passed": self.passed if not self.dry_run else None,
            "artifact_root": str(self.artifact_root) if self.artifact_root else None,
            "results": [result.as_dict() for result in self.results],
        }


def repository_root() -> Path:
    """Return the repository root without relying on the current directory."""

    return Path(__file__).resolve().parents[3]


def default_clone_root() -> Path:
    return repository_root() / "materials" / "edx"


def _task_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task_payload(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"task specification is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ReplayError(f"task specification must be an object: {path}")
    schema = value.get("eval_schema")
    if not isinstance(schema, dict):
        raise ReplayError(f"task specification has no eval schema: {path}")
    if schema.get("method") != "POST":
        raise ReplayError(f"task specification has an unexpected method: {path}")
    pattern = schema.get("url_pattern")
    if not isinstance(pattern, str) or "www" not in pattern:
        raise ReplayError(f"task specification has an unexpected URL pattern: {path}")
    return value


def discover_task_specs(
    specs_root: Path, task_ids: Sequence[str] = DEFAULT_TASK_IDS
) -> dict[str, Path]:
    """Locate and validate the immutable edX task JSON files.

    The caller passes a separate task-specification directory so neither the
    repository nor the upstream source checkout is rewritten.
    """

    root = specs_root.resolve()
    if not root.is_dir():
        raise ReplayError(f"task specification directory does not exist: {root}")
    selected: dict[str, Path] = {}
    for task_id in task_ids:
        if task_id not in TASK_RUN_IDS:
            raise ReplayError(f"unsupported edX task id: {task_id}")
        matches = sorted(root.glob(f"v2-{task_id}-*.json"))
        if len(matches) != 1:
            raise ReplayError(
                f"expected exactly one task specification for {task_id} under {root}"
            )
        _task_payload(matches[0])
        selected[task_id] = matches[0]
    return selected


def gateway_config(clone_port: int) -> str:
    """Return the ephemeral TLS reverse-proxy configuration.

    The public hostnames stay in the browser URL so the original evaluator
    pattern can observe them, while all traffic terminates at the local clone.
    """

    if not 1 <= clone_port <= 65535:
        raise ReplayError(f"invalid clone port: {clone_port}")
    names = ", ".join(f"https://{host}" for host in EVALUATOR_HOSTS)
    return (
        "{\n"
        "  admin off\n"
        "}\n\n"
        f"{names} {{\n"
        "  tls internal\n"
        f"  reverse_proxy host.docker.internal:{clone_port} {{\n"
        "    header_up Host {http.request.host}\n"
        "    header_up X-Forwarded-Proto https\n"
        "  }\n"
        "}\n"
    )


def evaluator_docker_flags(bridge: GatewayBridge) -> tuple[str, ...]:
    """Map source edX hosts to the gateway inside one isolated Docker network."""

    return (
        f"--network={bridge.network_name}",
        *(f"--add-host={host}:{bridge.gateway_ip}" for host in EVALUATOR_HOSTS),
    )


def gateway_command(
    docker_binary: str,
    *,
    name: str,
    caddyfile: Path,
    network_name: str,
    probe_port: int,
    image: str = DEFAULT_GATEWAY_IMAGE,
) -> list[str]:
    """Build the Docker command for the local TLS gateway without running it."""

    return [
        docker_binary,
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "--network",
        network_name,
        "--add-host=host.docker.internal:host-gateway",
        "-p",
        f"127.0.0.1:{probe_port}:443",
        "-v",
        f"{caddyfile.resolve()}:/etc/caddy/Caddyfile:ro",
        image,
    ]


def _safe_extract_archive(payload: bytes, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise ReplayError("upstream archive contains an unsafe member path")
            # Task records are supplied separately below and stay byte-for-byte
            # immutable.  Excluding the upstream corpus also avoids copying
            # unrelated symlinked fixtures into the temporary agent overlay.
            if relative.name == ".env" or relative.parts[0] in {".git", "test-cases"}:
                continue
            target = (destination / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ReplayError("upstream archive escapes its temporary overlay") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ReplayError("upstream archive contains an unsupported member type")
            source = archive.extractfile(member)
            if source is None:
                raise ReplayError("upstream archive member could not be read")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())


def materialize_upstream_overlay(upstream_root: Path, destination: Path) -> None:
    """Copy an upstream checkout into a disposable overlay, excluding .env."""

    source = upstream_root.resolve()
    if not source.is_dir():
        raise ReplayError(f"upstream checkout does not exist: {source}")
    destination.mkdir(parents=True, exist_ok=False)
    git = shutil.which("git")
    if git:
        archive = subprocess.run(
            [git, "-C", str(source), "archive", "--format=tar", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
        if archive.returncode == 0:
            _safe_extract_archive(archive.stdout, destination)
            return
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", ".env", "__pycache__", "*.pyc"),
    )


def _agent_package_root(overlay: Path) -> Path:
    candidates = sorted((overlay / "src").glob("*/runner/run.py"))
    if len(candidates) != 1:
        raise ReplayError(
            "upstream checkout must contain exactly one src/*/runner/run.py entrypoint"
        )
    return candidates[0].parents[1]


def _replace_once(path: Path, expected: str, replacement: str, label: str) -> None:
    value = path.read_text(encoding="utf-8")
    count = value.count(expected)
    if count != 1:
        raise ReplayError(
            f"unsupported upstream {label}: expected one compatible patch marker, found {count}"
        )
    path.write_text(value.replace(expected, replacement, 1), encoding="utf-8")


def patch_upstream_overlay(overlay: Path) -> Path:
    """Apply a narrow, ephemeral local-runtime bridge to an upstream overlay.

    This changes neither task bytes nor the checked-out upstream directory.
    The patches use the upstream recorder but continue the matching POST so the
    local clone can durably commit the enrollment before the agent stops.
    """

    package_root = _agent_package_root(overlay)
    email_path = package_root / "runner" / "run_support" / "email.py"
    docker_path = package_root / "runner" / "run_support" / "docker.py"
    server_path = package_root / "runtime" / "runtime-server" / "server.py"
    entrypoint_path = package_root / "runtime" / "harnesses" / "base" / "entrypoint.sh"

    _replace_once(
        email_path,
        "import json\nimport secrets\nimport uuid\n",
        "import json\nimport os\nimport secrets\nimport uuid\n",
        "email imports",
    )
    _replace_once(
        email_path,
        "def create_email(api_key: str, domain: str) -> tuple[str, str]:\n"
        "    local = f\"cb{uuid.uuid4().hex[:12]}\"\n",
        "def create_email(api_key: str, domain: str) -> tuple[str, str]:\n"
        "    if os.environ.get(\"WEBSITEBENCH_OFFLINE_MAIL\") == \"1\":\n"
        "        email = os.environ.get(\"WEBSITEBENCH_EVALUATOR_EMAIL\", \"\")\n"
        "        password = os.environ.get(\"WEBSITEBENCH_EVALUATOR_PASSWORD\", \"\")\n"
        "        if not email or not password:\n"
        "            raise RuntimeError(\"local evaluator credentials are missing\")\n"
        "        return email, password\n"
        "    local = f\"cb{uuid.uuid4().hex[:12]}\"\n",
        "email creation",
    )
    _replace_once(
        email_path,
        "def delete_email(api_key: str, email: str) -> None:\n"
        "    try:\n",
        "def delete_email(api_key: str, email: str) -> None:\n"
        "    if os.environ.get(\"WEBSITEBENCH_OFFLINE_MAIL\") == \"1\":\n"
        "        return\n"
        "    try:\n",
        "email cleanup",
    )

    network_marker = (
        "def _network_flags() -> list[str]:\n"
        "    \"\"\"Force slirp4netns on podman to avoid host-network port collisions.\"\"\"\n"
        "    if ENGINE == \"podman\":\n"
        "        return [\"--network=slirp4netns\"]\n"
        "    return []\n\n\n"
    )
    network_replacement = network_marker + (
        "def _websitebench_evaluator_flags() -> list[str]:\n"
        "    \"\"\"Forward the local host-alias bridge only in the temporary overlay.\"\"\"\n"
        "    raw = os.environ.get(\"WEBSITEBENCH_EVALUATOR_DOCKER_FLAGS\", \"\").strip()\n"
        "    return shlex.split(raw) if raw else []\n\n\n"
    )
    _replace_once(docker_path, network_marker, network_replacement, "Docker flags")
    docker_text = docker_path.read_text(encoding="utf-8")
    docker_marker = "        *_network_flags(),\n        *_proxy_env_flags(),\n"
    if docker_text.count(docker_marker) != 2:
        raise ReplayError("unsupported upstream Docker launch layout")
    docker_path.write_text(
        docker_text.replace(
            docker_marker,
            "        *_network_flags(),\n"
            "        *_websitebench_evaluator_flags(),\n"
            "        *_proxy_env_flags(),\n",
        ),
        encoding="utf-8",
    )

    _replace_once(
        entrypoint_path,
        "\"$BROWSER\" \\\n  --window-size=1920,1080 \\\n",
        "\"$BROWSER\" \\\n"
        "  --ignore-certificate-errors \\\n"
        "  --allow-insecure-localhost \\\n"
        "  --window-size=1920,1080 \\\n",
        "Chrome launch flags",
    )
    _replace_once(
        server_path,
        "            print(f\"[interceptor] Blocked: {request_url[:100]}\", flush=True)\n\n"
        "            send(\n"
        "                \"Fetch.failRequest\",\n"
        "                {\"requestId\": request_id, \"errorReason\": \"BlockedByClient\"},\n"
        "                session_id,\n"
        "            )\n",
        "            print(f\"[interceptor] Captured: {request_url[:100]}\", flush=True)\n\n"
        "            send(\n"
        "                \"Fetch.continueRequest\",\n"
        "                {\"requestId\": request_id},\n"
        "                session_id,\n"
        "            )\n",
        "interceptor continuation",
    )
    return package_root


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_overlay_configuration(
    overlay: Path, settings: ModelSettings, api_key: str
) -> None:
    """Write only ephemeral model and inert local-mail configuration."""

    (overlay / ".env").write_text(
        "PURELY_MAIL_API_KEY=offline-placeholder\n"
        "PURELY_MAIL_DOMAIN=offline.invalid\n",
        encoding="utf-8",
    )
    models = overlay / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "models.yaml").write_text(
        f"{_yaml_scalar(settings.model)}:\n"
        f"  api_key: {_yaml_scalar(api_key)}\n"
        f"  base_url: {_yaml_scalar(settings.base_url)}\n"
        f"  api_type: {_yaml_scalar(settings.api_type)}\n",
        encoding="utf-8",
    )


def stage_task_specification(source: Path, destination: Path) -> Path:
    """Copy task bytes unchanged into the disposable upstream workspace."""

    _task_payload(source)
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / "task.json"
    target.write_bytes(source.read_bytes())
    return target


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _prepend_path(existing: str, directory: Path) -> str:
    return str(directory) + os.pathsep + existing if existing else str(directory)


def resolve_docker_binary(explicit: str | None = None) -> str:
    """Locate a usable Docker client without mutating the caller's PATH."""

    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    discovered = shutil.which("docker")
    if discovered:
        candidates.append(Path(discovered))
    candidates.append(Path(r"D:\Docker\DockerDesktop\resources\bin\docker.exe"))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        probe = subprocess.run(
            [str(candidate), "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
        if probe.returncode == 0:
            return str(candidate)
    raise ReplayError(
        "Docker is unavailable. Start the local Docker daemon and retry; the adapter "
        "will not use a remote container service."
    )


def _wait_for_clone(port: int, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    address = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urlopen(address, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, URLError):
            time.sleep(0.25)
    raise ReplayError(f"local edX clone did not become ready at {address}")


@contextlib.contextmanager
def running_clone(clone_root: Path, data_root: Path, log_path: Path) -> Iterator[int]:
    """Run a fresh evaluator-only clone process with an isolated database."""

    site_root = clone_root.resolve()
    app_file = site_root / "clone" / "app.py"
    if not app_file.is_file():
        raise ReplayError(f"edX clone app is missing: {app_file}")
    runtime = site_root / "backend" / "runtime.json"
    if not runtime.is_file():
        raise ReplayError(f"edX backend runtime contract is missing: {runtime}")
    port = _free_port()
    environment = os.environ.copy()
    environment["WEBSITEBENCH_EDX_DATA_DIR"] = str(data_root.resolve())
    environment["WEBSITEBENCH_EVALUATOR_COMPAT"] = "1"
    environment["WEBSITEBENCH_SITE_BACKEND_RUNTIME"] = str(runtime.resolve())
    environment["PYTHONPATH"] = _prepend_path(
        environment.get("PYTHONPATH", ""), repository_root() / "src"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "websitebench.task_replay.serve_clone",
                "--app-file",
                str(app_file),
                "--port",
                str(port),
            ],
            cwd=repository_root(),
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            try:
                _wait_for_clone(port)
            except ReplayError as exc:
                log_file.flush()
                exit_code = process.poll()
                detail = ""
                if exit_code is not None:
                    try:
                        tail = log_path.read_text(encoding="utf-8")[-500:].strip()
                    except OSError:
                        tail = ""
                    detail = f" (process exit: {exit_code}; log tail: {tail})" if tail else (
                        f" (process exit: {exit_code})"
                    )
                raise ReplayError(str(exc) + detail) from exc
            yield port
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)


def _wait_for_gateway(probe_port: int, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    context = ssl._create_unverified_context()
    last_status: int | None = None
    while time.monotonic() < deadline:
        connection: socket.socket | None = None
        try:
            raw = socket.create_connection(("127.0.0.1", probe_port), timeout=2)
            connection = context.wrap_socket(raw, server_hostname=EVALUATOR_HOSTS[0])
            connection.sendall(
                (
                    f"GET / HTTP/1.1\r\nHost: {EVALUATOR_HOSTS[0]}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
            )
            response = http.client.HTTPResponse(connection)
            response.begin()
            response.read()
            last_status = response.status
            if 200 <= response.status < 500:
                return
        except (OSError, ssl.SSLError, http.client.HTTPException):
            time.sleep(0.25)
        finally:
            if connection is not None:
                connection.close()
    suffix = f" (last HTTP status: {last_status})" if last_status is not None else ""
    raise ReplayError(
        f"local TLS gateway did not become ready on 127.0.0.1:{probe_port}" + suffix
    )


@contextlib.contextmanager
def running_gateway(
    docker_binary: str,
    clone_port: int,
    workspace: Path,
    *,
    image: str = DEFAULT_GATEWAY_IMAGE,
) -> Iterator[GatewayBridge]:
    """Expose the clone under the two public edX hostnames for one replay."""

    workspace.mkdir(parents=True, exist_ok=True)
    name = f"websitebench-edx-evaluator-{uuid.uuid4().hex[:12]}"
    network_name = f"websitebench-edx-network-{uuid.uuid4().hex[:12]}"
    probe_port = _free_port()
    caddyfile = workspace / "Caddyfile"
    caddyfile.write_text(gateway_config(clone_port), encoding="utf-8")
    launched = False
    network_created = False
    try:
        network = subprocess.run(
            [docker_binary, "network", "create", network_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        if network.returncode != 0:
            raise ReplayError("could not create the isolated evaluator network")
        network_created = True
        launch = subprocess.run(
            gateway_command(
                docker_binary,
                name=name,
                caddyfile=caddyfile,
                network_name=network_name,
                probe_port=probe_port,
                image=image,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        if launch.returncode != 0:
            raise ReplayError("could not start the local TLS gateway")
        launched = True
        inspected = subprocess.run(
            [
                docker_binary,
                "inspect",
                "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                name,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        gateway_ip = inspected.stdout.decode("utf-8", errors="replace").strip()
        if inspected.returncode != 0 or not re.fullmatch(r"[0-9.]+", gateway_ip):
            raise ReplayError("could not resolve the local TLS gateway address")
        try:
            _wait_for_gateway(probe_port)
        except ReplayError as exc:
            logs = subprocess.run(
                [docker_binary, "logs", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=30,
            )
            tail = logs.stdout.decode("utf-8", errors="replace")[-600:].strip()
            published = subprocess.run(
                [docker_binary, "port", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
            ports = published.stdout.decode("utf-8", errors="replace").strip()
            suffix = f" (gateway log tail: {tail})" if tail else ""
            if ports:
                suffix += f" (published ports: {ports})"
            raise ReplayError(str(exc) + suffix) from exc
        yield GatewayBridge(
            network_name=network_name,
            gateway_ip=gateway_ip,
            probe_port=probe_port,
        )
    finally:
        if launched:
            subprocess.run(
                [docker_binary, "rm", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        if network_created:
            subprocess.run(
                [docker_binary, "network", "rm", network_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )


def _agent_entrypoint(package_root: Path) -> Path:
    path = package_root / "runner" / "run.py"
    if not path.is_file():
        raise ReplayError(f"upstream runner entrypoint is missing: {path}")
    return path


def agent_command(
    *,
    overlay: Path,
    package_root: Path,
    task_path: Path,
    output_root: Path,
    settings: ModelSettings,
    no_build: bool,
) -> list[str]:
    """Build the upstream Codex harness command without starting it."""

    command = [
        sys.executable,
        str(_agent_entrypoint(package_root)),
        str(task_path),
        settings.model,
        "--harness",
        "codex",
        "--no-judge",
        "--no-upload",
        "--output-dir",
        str(output_root),
    ]
    if no_build:
        command.append("--no-build")
    return command


def _agent_environment(
    *,
    overlay: Path,
    docker_binary: str,
    bridge: GatewayBridge,
) -> dict[str, str]:
    environment = os.environ.copy()
    docker_directory = Path(docker_binary).resolve().parent
    environment["PATH"] = _prepend_path(environment.get("PATH", ""), docker_directory)
    environment["PYTHONPATH"] = _prepend_path(
        environment.get("PYTHONPATH", ""), overlay / "src"
    )
    environment["WEBSITEBENCH_EVALUATOR_DOCKER_FLAGS"] = " ".join(
        evaluator_docker_flags(bridge)
    )
    environment["WEBSITEBENCH_OFFLINE_MAIL"] = "1"
    environment["WEBSITEBENCH_EVALUATOR_EMAIL"] = FIXTURE_EMAIL
    environment["WEBSITEBENCH_EVALUATOR_PASSWORD"] = FIXTURE_PASSWORD
    return environment


def _run_agent(
    command: Sequence[str], *, environment: dict[str, str], cwd: Path, log_path: Path
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return int(completed.returncode)


def _was_intercepted(output_root: Path) -> bool:
    for path in output_root.rglob("interception.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("intercepted") is True:
            return True
    return False


def durable_enrollment(data_root: Path, run_id: str) -> bool:
    """Check only durable local state; no request body or learner PII is read."""

    database = data_root / "edx.sqlite3"
    if not database.is_file():
        return False
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM enrollments WHERE run_id=? AND track='audit'",
            (run_id,),
        ).fetchone()
    finally:
        connection.close()
    return bool(row and int(row[0]) > 0)


def _make_result(
    *,
    task_id: str,
    task_path: Path,
    exit_code: int | None,
    intercepted: bool,
    enrolled: bool,
) -> TaskReplayResult:
    if exit_code == 0 and intercepted and enrolled:
        status = "passed"
        detail = "intercepted evaluator POST and durable local audit enrollment"
    elif exit_code is None:
        status = "planned"
        detail = "validated immutable task specification; replay was not started"
    elif not intercepted:
        status = "not-intercepted"
        detail = "upstream harness exited without the required evaluator POST"
    elif not enrolled:
        status = "not-durable"
        detail = "evaluator POST was captured but no durable local audit enrollment exists"
    else:
        status = "agent-failed"
        detail = f"upstream harness exited with status {exit_code}"
    return TaskReplayResult(
        task_id=task_id,
        task_sha256=_task_sha256(task_path),
        run_id=TASK_RUN_IDS[task_id],
        upstream_exit_code=exit_code,
        intercepted=intercepted,
        durable_enrollment=enrolled,
        status=status,
        detail=detail,
    )


def replay_edx_tasks(
    *,
    upstream_root: Path,
    task_specs_root: Path,
    clone_root: Path | None = None,
    task_ids: Sequence[str] = DEFAULT_TASK_IDS,
    settings: ModelSettings = ModelSettings(),
    docker_binary: str | None = None,
    gateway_image: str = DEFAULT_GATEWAY_IMAGE,
    no_build: bool = False,
    dry_run: bool = False,
    retain_artifacts: bool = False,
) -> ReplaySummary:
    """Run all selected immutable edX tasks through the local clone.

    The harness's LLM judge is always disabled.  A task passes this adapter
    only when the original evaluator POST is captured *and* the local clone's
    SQLite state contains the expected audit enrollment after the replay.
    """

    selected_ids = tuple(dict.fromkeys(task_ids))
    if not selected_ids:
        raise ReplayError("at least one task id is required")
    specs = discover_task_specs(task_specs_root, selected_ids)
    api_configured = bool(os.environ.get(settings.api_key_env, "").strip())
    if dry_run:
        return ReplaySummary(
            results=tuple(
                _make_result(
                    task_id=task_id,
                    task_path=specs[task_id],
                    exit_code=None,
                    intercepted=False,
                    enrolled=False,
                )
                for task_id in selected_ids
            ),
            dry_run=True,
            artifact_root=None,
            api_key_configured=api_configured,
        )

    api_key = settings.require_api_key()
    docker = resolve_docker_binary(docker_binary)
    site_root = (clone_root or default_clone_root()).resolve()

    retained_root: Path | None = None
    workspace_context: tempfile.TemporaryDirectory[str] | None = None
    if retain_artifacts:
        workspace = Path(tempfile.mkdtemp(prefix="websitebench-edx-agent-replay-"))
        retained_root = workspace
    else:
        workspace_context = tempfile.TemporaryDirectory(
            prefix="websitebench-edx-agent-replay-"
        )
        workspace = Path(workspace_context.name)
    try:
        overlay = workspace / "upstream-overlay"
        materialize_upstream_overlay(upstream_root, overlay)
        package_root = patch_upstream_overlay(overlay)
        write_overlay_configuration(overlay, settings, api_key)
        results: list[TaskReplayResult] = []
        for task_id in selected_ids:
            task_workspace = workspace / "tasks" / task_id
            staged_task = stage_task_specification(specs[task_id], task_workspace)
            output_root = workspace / "agent-output" / task_id
            data_root = workspace / "clone-data" / task_id
            run_workspace = workspace / "gateway" / task_id
            run_workspace.mkdir(parents=True, exist_ok=True)
            with running_clone(
                site_root, data_root, workspace / "logs" / f"clone-{task_id}.log"
            ) as clone_port:
                with running_gateway(
                    docker,
                    clone_port,
                    run_workspace,
                    image=gateway_image,
                ) as bridge:
                    environment = _agent_environment(
                        overlay=overlay,
                        docker_binary=docker,
                        bridge=bridge,
                    )
                    exit_code = _run_agent(
                        agent_command(
                            overlay=overlay,
                            package_root=package_root,
                            task_path=staged_task,
                            output_root=output_root,
                            settings=settings,
                            no_build=no_build,
                        ),
                        environment=environment,
                        cwd=overlay,
                        log_path=workspace / "logs" / f"agent-{task_id}.log",
                    )
            results.append(
                _make_result(
                    task_id=task_id,
                    task_path=specs[task_id],
                    exit_code=exit_code,
                    intercepted=_was_intercepted(output_root),
                    enrolled=durable_enrollment(data_root, TASK_RUN_IDS[task_id]),
                )
            )
        return ReplaySummary(
            results=tuple(results),
            dry_run=False,
            artifact_root=retained_root,
            api_key_configured=True,
        )
    finally:
        if workspace_context is not None:
            workspace_context.cleanup()
