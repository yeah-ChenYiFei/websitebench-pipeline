"""Execute Harbor OpenCLI interaction contracts against a running target.

The contract under ``harbor/sites/<site-id>/interactions/`` is the single source
of truth. This package turns it into something that actually runs: it resolves a
profile, drives every step through an OpenCLI backend, and writes a sealed
diagnostic artifact.

Results are advisory. They never form trace coverage and never satisfy a source,
frontend, Harbor or technical-verification stage.
"""

from __future__ import annotations

from .contract import (
    LoadedContract,
    OpenCliContractError,
    Profile,
    Step,
    load_contract_from_runner,
    load_contract_from_site,
)

__all__ = [
    "LoadedContract",
    "OpenCliContractError",
    "Profile",
    "Step",
    "load_contract_from_runner",
    "load_contract_from_site",
]
