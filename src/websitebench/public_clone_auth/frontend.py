"""Framework-neutral browser asset for the shared verification API contract."""

from __future__ import annotations

from importlib.resources import files


def registration_frontend_script() -> bytes:
    """Return the local, versioned registration helper without remote assets."""

    return (
        files("websitebench.public_clone_auth")
        .joinpath("static", "verification.js")
        .read_bytes()
    )
