"""Replay an OpenCLI interaction profile and report the result.

The output is a diagnostic artifact. It carries no source, frontend, Harbor or
release authority, and a failing step is reported rather than raised: the
process still exits 0 because replay is advisory.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ...offline_clone.toolbox import origin, safe_text, write_json_atomic
from .backends import (
    AdapterBackend,
    Backend,
    BrowserBackend,
    StepResult,
    UnsupportedCommandError,
)
from .contract import LoadedContract, OpenCliContractError, Profile
from .doctor import DoctorReport, probe_opencli

RESULT_SCHEMA_VERSION = "websitebench.harbor.opencli.replay-result.v1"
AUTHORITY = "diagnostic-only"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _portable_contract_path(path: Path) -> str:
    """Prefer a repository-relative identity in artifacts meant for Git."""

    resolved = path.resolve()
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / "harbor").is_dir() and (candidate / "materials").is_dir():
            return resolved.relative_to(candidate).as_posix()
    return str(resolved)


def _check_allowlist(base_url: str, profile: Profile) -> str:
    """Refuse non-loopback targets and anything the profile did not authorize."""

    try:
        base_origin = origin(base_url)
    except Exception as exc:  # ToolboxError subclasses ValueError-like errors
        raise OpenCliContractError(f"invalid base URL {base_url!r}: {exc}") from exc
    try:
        parsed = urllib.parse.urlsplit(base_origin)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise OpenCliContractError(f"invalid base URL {base_url!r}: {exc}") from exc
    if (
        host not in LOOPBACK_HOSTS
        or port == 0
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OpenCliContractError(
            f"target host {host!r} is not loopback; local clone replay accepts "
            "only 127.0.0.1 or localhost"
        )
    if profile.network_allowlist and host not in profile.network_allowlist:
        raise OpenCliContractError(
            f"target host {host!r} is not in the profile network allowlist "
            f"{list(profile.network_allowlist)}"
        )
    return base_origin


def _post_form(
    url: str, fields: dict[str, str], *, timeout: int = 15
) -> tuple[int, str]:
    """POST a urlencoded form and return status plus any issued cookie header."""

    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            headers = response.headers
            status = response.status
    except urllib.error.HTTPError as exc:
        headers = exc.headers
        status = exc.code
    except OSError as exc:
        raise OpenCliContractError(f"session precondition failed: {exc}") from exc
    issued = [
        value.split(";", 1)[0].strip()
        for value in headers.get_all("Set-Cookie") or []
        if "=" in value
    ]
    return status, "; ".join(issued)


def _reset(
    base_url: str, reset_path: str, token: str, *, timeout: int = 15
) -> int | None:
    """Reset the target so a profile is re-runnable. Best effort, never fatal."""

    if not reset_path:
        return None
    url = f"{base_url.rstrip('/')}/{reset_path.lstrip('/')}"
    request = urllib.request.Request(
        url, data=b"", headers={"X-WebsiteBench-Admin-Token": token}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return None


def select_backend(
    *,
    requested: str,
    site_id: str,
    report: DoctorReport,
    binary: str,
    timeout: int,
) -> tuple[Backend, list[str]]:
    """Pick a backend, degrading to `adapter` rather than failing."""

    notes: list[str] = []
    if requested == "browser" and not report.doctor_green:
        raise OpenCliContractError(
            "backend 'browser' requires a connected OpenCLI Browser Bridge; "
            + "; ".join(report.notes or ("opencli doctor is not green",))
        )
    if requested == "auto":
        if report.doctor_green:
            requested = "browser"
        else:
            requested = "adapter"
            notes.extend(report.notes)
            notes.append("backend degraded to 'adapter'")
    if requested == "browser":
        return (
            BrowserBackend(
                session_name=f"websitebench-{site_id}", binary=binary, timeout=timeout
            ),
            notes,
        )
    return (
        AdapterBackend(site_id=site_id, binary=binary, timeout=timeout),
        notes,
    )


def replay_profile(
    contract: LoadedContract,
    profile_id: str,
    *,
    base_url: str,
    backend: Backend,
    report: DoctorReport,
    target: str = "reference",
    instance_id: str | None = None,
    reset_path: str = "",
    admin_token: str = "",
    degradation_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Run one profile end to end and return the sealed artifact payload."""

    profile = contract.profile(profile_id)
    base_origin = _check_allowlist(base_url, profile)

    reset_status = _reset(base_url, reset_path, admin_token) if reset_path else None

    session = ""
    session_fields: list[str] = []
    session_status: int | None = None
    if profile.session is not None:
        session_fields = sorted(profile.session.fields)
        url = f"{base_url.rstrip('/')}/{profile.session.route.lstrip('/')}"
        session_status, session = _post_form(url, profile.session.fields)

    results: list[StepResult] = []
    unsupported = 0
    for step in profile.steps:
        try:
            result = backend.run_step(step, base_url=base_url, session=session)
        except UnsupportedCommandError as exc:
            unsupported += 1
            result = StepResult(
                step_id=step.id,
                observation_id=step.observation_id,
                command=step.command,
                tier=step.tier,
                declared_route=step.route,
                outcome="error",
                error=str(exc),
            )
        results.append(result)
        if result.session:
            session = result.session

    steps_payload: list[dict[str, Any]] = []
    for result in results:
        payload = asdict(result)
        # Session material is runtime state, never evidence.
        payload.pop("session", None)
        payload["observations"] = [
            {**item, "observed": safe_text(item.get("observed"), limit=200)}
            for item in payload.get("observations", [])
        ]
        if payload.get("error"):
            payload["error"] = safe_text(payload["error"], limit=400)
        steps_payload.append(payload)

    passed = sum(1 for item in results if item.outcome == "passed")
    assertion_failures = sum(
        1
        for item in results
        for observation in item.observations
        if observation.get("asserted") and observation.get("passed") is not True
    )
    unasserted = sum(
        1
        for item in results
        for observation in item.observations
        if not observation.get("asserted")
    )

    return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "site_id": contract.site_id,
            "instance_id": instance_id,
            "profile_id": profile_id,
            "profile_label": profile.label,
            "profile_tier": profile.tier,
            "target": target,
            "backend": backend.name,
            "opencli": report.payload(contract_version=contract.opencli_version),
            "contract": {
                "path": _portable_contract_path(contract.source_path),
            },
            "target_binding": {
                "base_origin": base_origin,
                "allowlist": list(profile.network_allowlist),
                "reset_status": reset_status,
                "session_status": session_status,
                "session_fields": session_fields,
            },
            "steps": steps_payload,
            "summary": {
                "steps_total": len(results),
                "steps_passed": passed,
                "assertion_failures": assertion_failures,
                "unasserted_observations": unasserted,
                "unsupported_commands": unsupported,
            },
            "status": "passed" if passed == len(results) and results else "failed",
            "degradation": list(degradation_notes or []),
            "authority": AUTHORITY,
        }


def write_result(payload: dict[str, Any], output: Path, *, force: bool = False) -> Path:
    """Write the artifact, refusing to clobber unless explicitly forced."""

    output = output.resolve()
    if output.exists() and not force:
        raise OpenCliContractError(f"refusing to overwrite existing result: {output}")
    write_json_atomic(output, payload)
    return output


def run(
    contract: LoadedContract,
    profile_id: str,
    *,
    base_url: str,
    output: Path,
    backend_name: str = "adapter",
    binary: str = "opencli",
    timeout: int = 30,
    target: str = "reference",
    instance_id: str | None = None,
    reset_path: str = "",
    admin_token: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Probe, select a backend, replay, and write the artifact."""

    started = time.monotonic()
    report = probe_opencli(binary)
    backend, notes = select_backend(
        requested=backend_name,
        site_id=contract.site_id,
        report=report,
        binary=binary,
        timeout=timeout,
    )
    payload = replay_profile(
        contract,
        profile_id,
        base_url=base_url,
        backend=backend,
        report=report,
        target=target,
        instance_id=instance_id,
        reset_path=reset_path,
        admin_token=admin_token,
        degradation_notes=notes,
    )
    payload = {**payload, "duration_seconds": round(time.monotonic() - started, 6)}
    write_result(payload, output, force=force)
    return payload
