"""Shared fail-closed launcher for repository-owned untrusted runtimes.

Harbor and offline-clone diagnostics execute candidate code for different
purposes, but the host boundary is the same: a read-only candidate tree, one
private writable data directory, bounded resources, no ambient credentials,
and TCP access limited to explicitly allocated loopback service ports.
"""

from __future__ import annotations

import os
import resource
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from websitebench.harbor.sandbox_v2 import sandbox_preflight


class IsolationUnavailable(RuntimeError):
    """The host cannot enforce the mandatory candidate sandbox."""


@dataclass(frozen=True)
class IsolationLimits:
    memory_mb: int = 2048
    cpu_seconds: int = 180
    file_size_mb: int = 64
    open_files: int = 256
    processes: int = 128


def _trusted_node_executable() -> Path | None:
    """Resolve the verifier-provided Node runtime before candidate isolation."""

    discovered = shutil.which("node")
    if discovered is None:
        return None
    try:
        resolved = Path(discovered).resolve(strict=True)
    except OSError:
        return None
    if resolved.name != "node" or not resolved.is_file():
        return None
    return resolved


def require_isolation() -> dict[str, object]:
    """Return non-sensitive capability evidence or fail before candidate exec."""

    if sys.platform != "linux":
        raise IsolationUnavailable("candidate sandbox requires Linux")
    try:
        return sandbox_preflight()
    except OSError as exc:
        raise IsolationUnavailable(f"candidate sandbox unavailable: {exc}") from exc


def prepare_data_directory(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    for name in ("cache", "config", "home", "state", "tmp"):
        (data / name).mkdir(exist_ok=True)
    data.chmod(0o700)


def clean_candidate_environment(
    data: Path,
    *,
    port: int,
    declared: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an allowlist environment with no inherited host credentials."""

    python_bin = str(Path(sys.executable).resolve().parent)
    node = _trusted_node_executable()
    executable_dirs = [python_bin]
    if node is not None:
        executable_dirs.append(str(node.parent))
    environment = {
        "PATH": os.pathsep.join(
            dict.fromkeys((*executable_dirs, "/usr/local/bin", "/usr/bin", "/bin"))
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(data / "home"),
        "TMPDIR": str(data / "tmp"),
        "XDG_CACHE_HOME": str(data / "cache"),
        "XDG_CONFIG_HOME": str(data / "config"),
        "XDG_STATE_HOME": str(data / "state"),
        "PORT": str(port),
        "WEBSITEBENCH_DATA_DIR": str(data),
        # Existing vendored clone runtimes read this compatibility name.  It is
        # runtime input, not a new persisted product identifier.
        "CLAWBENCH_DATA_DIR": str(data),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "WEBSITEBENCH_ISOLATION_ID": secrets.token_hex(16),
    }
    environment.update(
        {str(key): str(value) for key, value in (declared or {}).items()}
    )
    if node is not None:
        # Candidate configuration cannot redirect the trusted launcher to a
        # candidate-owned executable.
        environment["WEBSITEBENCH_NODE_EXECUTABLE"] = str(node)
    return environment


def _limit_resources(limits: IsolationLimits) -> None:
    memory = limits.memory_mb * 1024 * 1024
    file_size = limits.file_size_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
    # RLIMIT_NPROC is charged to the host UID, not this sandbox. Applying it on
    # a shared runner makes unrelated same-UID tasks consume the candidate's
    # allowance and can break an ordinary ASGI thread pool after a handful of
    # requests. The seccomp policy denies every process-producing fork/vfork/
    # clone form; thread clones remain available and are bounded by RLIMIT_AS,
    # CPU time and the diagnostic deadline.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class IsolatedProcess:
    """One sandbox launcher and its complete descendant process group."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        stderr: tempfile.TemporaryFile[bytes],
    ) -> None:
        self.process = process
        self._stderr = stderr

    def stderr_tail(self, limit: int = 400) -> str:
        try:
            self._stderr.flush()
            self._stderr.seek(0, os.SEEK_END)
            size = self._stderr.tell()
            self._stderr.seek(max(0, size - max(limit * 4, 4096)))
            return self._stderr.read().decode("utf-8", "replace")[-limit:]
        except OSError:
            return ""

    def terminate_tree(self, timeout: float = 15.0) -> None:
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=timeout)
        self._stderr.close()


def launch_candidate(
    command: Sequence[str],
    *,
    candidate_root: Path,
    data_dir: Path,
    bind_port: int,
    environment: Mapping[str, str],
    connect_ports: set[int] | None = None,
    read_paths: Sequence[Path] = (),
    limits: IsolationLimits = IsolationLimits(),
) -> IsolatedProcess:
    """Start candidate code only after the kernel isolation preflight passed."""

    require_isolation()
    if candidate_root.is_symlink():
        raise IsolationUnavailable("candidate root must not be a symbolic link")
    root = candidate_root.resolve(strict=True)
    data = data_dir.resolve(strict=True)
    if root == data or root in data.parents or data in root.parents:
        raise IsolationUnavailable(
            "candidate root and writable data directory must be disjoint"
        )
    sandbox = (Path(__file__).resolve().parent / "harbor" / "sandbox_v2.py").resolve(
        strict=True
    )
    argv = [
        sys.executable,
        str(sandbox),
        "--root",
        str(root),
        "--data",
        str(data),
        "--bind-port",
        str(bind_port),
        "--file-size-limit-bytes",
        str(limits.file_size_mb * 1024 * 1024),
    ]
    # A virtual environment's Python launcher may be an absolute symlink into a
    # separately managed base runtime (for example uv's per-version store).
    # Landlock must permit both trees: the venv contains installed packages,
    # while the resolved interpreter tree contains the executable and stdlib.
    runtime_roots = {
        Path(sys.prefix).resolve(strict=True),
        Path(sys.executable).resolve(strict=True).parent.parent,
        # Editable repository installs resolve ``websitebench`` from ``src/``.
        # Treat that package tree as verifier runtime, not candidate-declared
        # input, so isolated Python launchers remain importable without
        # exposing the rest of the checkout.
        Path(__file__).resolve(strict=True).parent.parent,
    }
    node = _trusted_node_executable()
    if node is not None:
        runtime_roots.add(node.parent.parent)
    for runtime_root in sorted(runtime_roots, key=str):
        if runtime_root not in {Path("/usr"), Path("/usr/local")}:
            argv.extend(("--read-path", str(runtime_root)))
    for path in read_paths:
        if path.is_symlink():
            raise IsolationUnavailable(
                f"candidate read path must not be a symbolic link: {path}"
            )
        resolved = path.resolve(strict=True)
        site_root = root.parent
        if resolved != site_root and site_root not in resolved.parents:
            raise IsolationUnavailable(
                f"candidate read path escapes its site directory: {path}"
            )
        argv.extend(("--read-path", str(resolved)))
    # Candidate servers normally need no outbound connection at all.  Explicit
    # ports remain available for a future trusted loopback sidecar contract;
    # allowing by destination port is never inferred from ambient services.
    for port in sorted(connect_ports or set()):
        argv.extend(("--connect-port", str(port)))
    argv.extend(("--", *command))
    stderr = tempfile.TemporaryFile(prefix="websitebench-candidate-stderr-")
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(root),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            start_new_session=True,
            preexec_fn=lambda: _limit_resources(limits),
        )
    except BaseException:
        stderr.close()
        raise
    return IsolatedProcess(process, stderr)
