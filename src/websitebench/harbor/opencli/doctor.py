"""Preflight probe for the OpenCLI runtime.

The repository convention is that OpenCLI is supplied by the runtime, never
installed or upgraded automatically, and that an unusable OpenCLI degrades
rather than fails. This module reports what is available so the runner can pick
a backend and record ``opencli-unavailable`` when nothing is.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

VERSION_PATTERN = re.compile(r"\b(\d+\.\d+\.\d+)\b")


@dataclass(frozen=True)
class DoctorReport:
    """What the local OpenCLI installation can currently do."""

    binary_present: bool
    version: str | None = None
    extension_connected: bool = False
    connectivity_ok: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def doctor_green(self) -> bool:
        """True only when browser-driven commands can actually run."""

        return self.binary_present and self.extension_connected and self.connectivity_ok

    def payload(self, *, contract_version: str) -> dict[str, object]:
        return {
            "binary_present": self.binary_present,
            "version": self.version,
            "contract_version": contract_version,
            "version_matches": self.version == contract_version,
            "extension_connected": self.extension_connected,
            "connectivity_ok": self.connectivity_ok,
            "doctor_green": self.doctor_green,
            "notes": list(self.notes),
        }


def _capture(argv: list[str], *, timeout: int = 30) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout + done.stderr).decode(
        "utf-8", errors="replace"
    )


def probe_opencli(binary: str = "opencli", *, timeout: int = 30) -> DoctorReport:
    """Probe the binary, its version, and browser-bridge connectivity."""

    code, output = _capture([binary, "--version"], timeout=timeout)
    if code == 127:
        return DoctorReport(
            binary_present=False,
            notes=("opencli-unavailable: binary not found on PATH",),
        )
    match = VERSION_PATTERN.search(output)
    version = match.group(1) if match else None

    notes: list[str] = []
    _, doctor_output = _capture([binary, "doctor"], timeout=timeout)
    lowered = doctor_output.lower()
    # `doctor` exits non-zero when the bridge is down, which is a normal,
    # expected state here, so the text is the signal rather than the code.
    extension_connected = "extension: not connected" not in lowered and (
        "[ok] extension" in lowered or "extension: connected" in lowered
    )
    connectivity_ok = "[fail] connectivity" not in lowered and (
        "[ok] connectivity" in lowered
    )
    if not extension_connected:
        notes.append("opencli-unavailable: Browser Bridge extension not connected")
    if not connectivity_ok:
        notes.append("opencli-unavailable: browser connectivity check failed")
    return DoctorReport(
        binary_present=True,
        version=version,
        extension_connected=extension_connected,
        connectivity_ok=connectivity_ok,
        notes=tuple(notes),
    )
