"""Execution backends for OpenCLI interaction contracts.

Two backends exist because OpenCLI offers two transports and only one of them
works without a browser:

* ``AdapterBackend`` shells out to generated ``browser: false`` adapters
  (``opencli wb-<site> <command>``). Pure HTTP, no Chrome, no Bridge extension.
  This is the default and the only backend that runs in a headless environment.
* ``BrowserBackend`` shells out to ``opencli browser <session> <command>``,
  which drives a real tab. Higher fidelity, but ``getBrowserFactory`` in OpenCLI
  routes every non-Electron site through the extension-backed BrowserBridge, so
  it only works once ``opencli doctor`` reports a connected extension.

Neither backend raises on an assertion mismatch. A failed check is *data*; only
an inability to run the step is an error. Conflating the two would make a
non-gating diagnostic unable to say which happened.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .contract import Step

# Verbs this executor can run. Enforced at dispatch, deliberately not as a
# schema enum: the schema is a portable authoring contract that is duplicated
# into the viewer wheel and embedded into already-materialized bundles, whereas
# this set is a capability of one executor version. Coupling them would make
# every new verb retroactively invalidate shipped bundles. Same call as
# offline_clone/browser_tools.py.
SUPPORTED_COMMANDS = frozenset({"state", "click", "submit"})

TIMEOUT_RETURN_CODE = 124
UNAVAILABLE_RETURN_CODE = 127


class UnsupportedCommandError(ValueError):
    """Raised when a contract step names a verb this executor cannot run."""


@dataclass
class StepResult:
    """Outcome of one executed step.

    ``outcome`` follows the vocabulary already used by
    ``offline_clone/browser_tools.py``: ``passed`` and ``failed`` both mean the
    step ran, ``error`` means it could not.
    """

    step_id: str
    observation_id: str
    command: str
    tier: str
    declared_route: str
    outcome: str
    http_status: int | None = None
    duration_seconds: float = 0.0
    observations: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    session: str = ""


class Backend(Protocol):
    """Common shape both backends satisfy."""

    name: str

    def run_step(self, step: Step, *, base_url: str, session: str) -> StepResult: ...


def _run(argv: list[str], *, timeout: int) -> tuple[int, str, str]:
    """Run a command without a shell, mapping failures onto sentinel codes.

    Mirrors ``offline_clone/gates.py``: list argv, explicit timeout,
    ``check=False``, 124 for a timeout and 127 for a missing binary.
    """

    environment = os.environ.copy()
    environment.setdefault("OPENCLI_VERBOSE", "0")
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            TIMEOUT_RETURN_CODE,
            (exc.stdout or b"").decode("utf-8", errors="replace"),
            f"timed out after {timeout}s",
        )
    except OSError as exc:
        return UNAVAILABLE_RETURN_CODE, "", str(exc)
    return (
        done.returncode,
        done.stdout.decode("utf-8", errors="replace"),
        done.stderr.decode("utf-8", errors="replace"),
    )


def _rows(stdout: str) -> list[dict[str, Any]]:
    """Parse adapter stdout, which `-f json` emits as a bare array."""

    payload = json.loads(stdout)
    if not isinstance(payload, list):
        raise ValueError("expected a JSON array of rows")
    return [row for row in payload if isinstance(row, dict)]


def _grade(rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Turn adapter rows into an outcome plus recorded observations.

    Only rows the adapter marked ``asserted`` can fail a step. Descriptive
    contract prose is recorded verbatim and never graded.
    """

    observations: list[dict[str, Any]] = []
    failures = 0
    selector_matches = rows[0].get("selectorMatches") if rows else None
    if isinstance(selector_matches, int) and selector_matches == 0:
        observations.append(
            {
                "key": "selector",
                "expected": "at least one match",
                "observed": "0",
                "asserted": True,
                "passed": False,
            }
        )
        failures += 1
    for row in rows:
        if not row.get("checkKey"):
            continue
        asserted = bool(row.get("asserted"))
        passed = row.get("passed")
        observations.append(
            {
                "key": row.get("checkKey"),
                "expected": row.get("expected"),
                "observed": row.get("observed"),
                "asserted": asserted,
                "passed": passed if asserted else None,
            }
        )
        if asserted and passed is not True:
            failures += 1
    return ("failed" if failures else "passed"), observations


class AdapterBackend:
    """Drive a site through its generated ``browser: false`` OpenCLI adapters."""

    name = "adapter"

    def __init__(
        self,
        *,
        site_id: str,
        binary: str = "opencli",
        timeout: int = 30,
        namespace_prefix: str = "wb-",
    ) -> None:
        self.site = f"{namespace_prefix}{site_id}"
        self.binary = binary
        self.timeout = timeout

    def _argv(self, step: Step, *, base_url: str, session: str) -> list[str]:
        argv = [
            self.binary,
            self.site,
            step.command,
            "--route",
            step.route,
            "--base",
            base_url,
            "--timeout",
            str(self.timeout),
            "-f",
            "json",
        ]
        if step.selector:
            argv += ["--selector", step.selector]
        if step.required_state:
            argv += ["--expect", json.dumps(step.required_state, sort_keys=True)]
        if step.fields and step.command == "submit":
            argv += ["--fields", json.dumps(step.fields, sort_keys=True)]
        if session:
            argv += ["--session", session]
        return argv

    def run_step(self, step: Step, *, base_url: str, session: str) -> StepResult:
        if step.command not in SUPPORTED_COMMANDS:
            raise UnsupportedCommandError(
                f"step {step.id!r}: unsupported command {step.command!r}"
            )
        started = time.monotonic()
        code, stdout, stderr = _run(
            self._argv(step, base_url=base_url, session=session),
            timeout=self.timeout + 5,
        )
        elapsed = round(time.monotonic() - started, 6)
        result = StepResult(
            step_id=step.id,
            observation_id=step.observation_id,
            command=step.command,
            tier=step.tier,
            declared_route=step.route,
            outcome="error",
            duration_seconds=elapsed,
            session=session,
        )
        if code != 0:
            result.error = (stderr or stdout or f"opencli exited {code}").strip()[:400]
            return result
        try:
            rows = _rows(stdout)
        except (ValueError, json.JSONDecodeError) as exc:
            result.error = f"could not parse adapter output: {exc}"
            return result
        if not rows:
            result.error = "adapter returned no rows"
            return result
        outcome, observations = _grade(rows)
        result.outcome = outcome
        result.observations = observations
        status = rows[0].get("status")
        result.http_status = status if isinstance(status, int) else None
        issued = rows[0].get("setCookie")
        if isinstance(issued, str) and issued:
            result.session = issued
        return result


class BrowserBackend:
    """Drive a site through ``opencli browser``, which needs the Bridge extension.

    Kept deliberately thin. It is unreachable until ``opencli doctor`` is green,
    so it is wired but unproven; ``runner`` refuses to select it otherwise
    rather than letting it fail obscurely at the first step.
    """

    name = "browser"

    def __init__(
        self,
        *,
        session_name: str,
        binary: str = "opencli",
        timeout: int = 30,
    ) -> None:
        self.session_name = session_name
        self.binary = binary
        self.timeout = timeout

    def run_step(self, step: Step, *, base_url: str, session: str) -> StepResult:
        if step.command not in SUPPORTED_COMMANDS:
            raise UnsupportedCommandError(
                f"step {step.id!r}: unsupported command {step.command!r}"
            )
        started = time.monotonic()
        url = f"{base_url.rstrip('/')}/{step.route.lstrip('/')}"
        result = StepResult(
            step_id=step.id,
            observation_id=step.observation_id,
            command=step.command,
            tier=step.tier,
            declared_route=step.route,
            outcome="error",
            session=session,
        )
        # `opencli browser` has no `submit` verb. When the selector names a
        # control this collapses to `click`; when it names the <form> element
        # itself there is no faithful mapping, so refuse rather than guess.
        if step.command == "submit" and (step.selector or "").strip().startswith(
            "form"
        ):
            result.error = "browser backend cannot submit a form by form selector"
            result.duration_seconds = round(time.monotonic() - started, 6)
            return result

        base_argv = [self.binary, "browser", self.session_name]
        code, stdout, stderr = _run(
            [*base_argv, "open", url, "-f", "json"], timeout=self.timeout + 5
        )
        if code != 0:
            result.error = (stderr or stdout).strip()[:400]
            result.duration_seconds = round(time.monotonic() - started, 6)
            return result
        if step.command in {"click", "submit"} and step.selector:
            code, stdout, stderr = _run(
                [*base_argv, "click", step.selector, "-f", "json"],
                timeout=self.timeout + 5,
            )
            if code != 0:
                result.error = (stderr or stdout).strip()[:400]
                result.duration_seconds = round(time.monotonic() - started, 6)
                return result
        code, stdout, stderr = _run(
            [*base_argv, "state", "-f", "json"], timeout=self.timeout + 5
        )
        result.duration_seconds = round(time.monotonic() - started, 6)
        if code != 0:
            result.error = (stderr or stdout).strip()[:400]
            return result
        # Assertions are evaluated against the rendered snapshot text.
        observations: list[dict[str, Any]] = []
        failures = 0
        for key, expected in step.required_state.items():
            asserted = key in {"title", "visible", "list_contains", "link_text"}
            present = expected in stdout
            observations.append(
                {
                    "key": key,
                    "expected": expected,
                    "observed": expected if present else "",
                    "asserted": asserted,
                    "passed": present if asserted else None,
                }
            )
            if asserted and not present:
                failures += 1
        result.observations = observations
        result.outcome = "failed" if failures else "passed"
        return result
