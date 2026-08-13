"""Load an OpenCLI interaction contract into executable step objects.

Two entry points exist because the same contract is reachable from two places:

* ``load_contract_from_site`` reads the authoring tree
  (``harbor/sites/<site-id>/site.yaml`` -> ``opencli.contract``). Authoring-time
  validation has already run by then, so the payload is schema-conformant.
* ``load_contract_from_runner`` reads ``tests/opencli/interactions-runner.json``
  from a materialized bundle, which carries exactly one profile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..manifest import HarborManifestError, load_site, safe_regular_file

RUNNER_SCHEMA_VERSION = "websitebench.harbor.opencli.interactions-runner.v1"
CONTRACT_SCHEMA_VERSION = "websitebench.harbor.opencli-interaction-contract.v1"


class OpenCliContractError(ValueError):
    """Raised when a contract cannot be loaded or a profile cannot be resolved."""


@dataclass(frozen=True)
class Step:
    """One executable interaction step."""

    id: str
    observation_id: str
    command: str
    route: str
    tier: str
    selector: str | None = None
    intent: str = ""
    required_state: dict[str, str] = field(default_factory=dict)
    # Form overrides for a submit step. Public local fixtures only; the runner
    # records the field names and never the values.
    fields: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class SessionPrecondition:
    """Owner-scoped setup performed before step 1.

    This is setup, not a measured interaction, so it never appears as a step and
    never contributes to the step tally. Field *names* are recorded in the
    artifact; values never are.
    """

    route: str
    method: str
    fields: dict[str, str]
    notes: str = ""


@dataclass(frozen=True)
class Profile:
    """One named interaction journey."""

    id: str
    label: str
    tier: str
    steps: tuple[Step, ...]
    session: SessionPrecondition | None = None
    local_semantics: tuple[str, ...] = ()
    failure_paths: tuple[str, ...] = ()
    recovery_paths: tuple[str, ...] = ()
    network_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadedContract:
    """A contract plus the identity of the file it came from."""

    site_id: str
    opencli_version: str
    profiles: dict[str, Profile]
    source_path: Path

    def profile(self, profile_id: str) -> Profile:
        try:
            return self.profiles[profile_id]
        except KeyError:
            available = ", ".join(sorted(self.profiles)) or "<none>"
            raise OpenCliContractError(
                f"profile {profile_id!r} is not declared in {self.source_path}; "
                f"available: {available}"
            ) from None


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _build_step(raw: Any, *, profile_id: str, index: int, profile_tier: str) -> Step:
    if not isinstance(raw, dict):
        raise OpenCliContractError(
            f"profile {profile_id!r} step {index}: expected an object"
        )
    for required in ("id", "observation_id", "command", "route"):
        if not isinstance(raw.get(required), str) or not raw[required]:
            raise OpenCliContractError(
                f"profile {profile_id!r} step {index}: {required!r} must be a "
                "non-empty string"
            )
    selector = raw.get("selector")
    required_state = raw.get("required_state")
    overrides = raw.get("fields")
    return Step(
        id=raw["id"],
        observation_id=raw["observation_id"],
        command=raw["command"],
        route=raw["route"],
        # `tier` is an optional per-step override; absent means inherit the profile.
        tier=raw["tier"] if isinstance(raw.get("tier"), str) else profile_tier,
        selector=selector if isinstance(selector, str) and selector else None,
        intent=raw["intent"] if isinstance(raw.get("intent"), str) else "",
        required_state=(
            {str(key): str(item) for key, item in required_state.items()}
            if isinstance(required_state, dict)
            else {}
        ),
        fields=(
            {str(key): str(item) for key, item in overrides.items()}
            if isinstance(overrides, dict)
            else {}
        ),
        notes=raw["notes"] if isinstance(raw.get("notes"), str) else "",
    )


def _build_profile(profile_id: str, raw: Any) -> Profile:
    if not isinstance(raw, dict):
        raise OpenCliContractError(f"profile {profile_id!r}: expected an object")
    tier = raw["tier"] if isinstance(raw.get("tier"), str) else "p1"
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise OpenCliContractError(f"profile {profile_id!r}: steps must be non-empty")
    network = raw.get("network")
    allowlist = _strings(network.get("allowlist")) if isinstance(network, dict) else ()
    raw_session = raw.get("session")
    session = None
    if isinstance(raw_session, dict):
        fields = raw_session.get("fields")
        session = SessionPrecondition(
            route=str(raw_session.get("route", "")),
            method=str(raw_session.get("method", "POST")).upper(),
            fields={
                str(key): str(value)
                for key, value in (fields.items() if isinstance(fields, dict) else ())
            },
            notes=(
                raw_session["notes"]
                if isinstance(raw_session.get("notes"), str)
                else ""
            ),
        )
        if not session.route or not session.fields:
            raise OpenCliContractError(
                f"profile {profile_id!r}: session requires a route and fields"
            )
    return Profile(
        id=profile_id,
        label=raw["label"] if isinstance(raw.get("label"), str) else profile_id,
        tier=tier,
        steps=tuple(
            _build_step(step, profile_id=profile_id, index=index, profile_tier=tier)
            for index, step in enumerate(steps)
        ),
        session=session,
        local_semantics=_strings(raw.get("local_semantics")),
        failure_paths=_strings(raw.get("failure_paths")),
        recovery_paths=_strings(raw.get("recovery_paths")),
        network_allowlist=allowlist,
    )


def _contract_from_payload(payload: Any, *, source_path: Path) -> LoadedContract:
    if not isinstance(payload, dict):
        raise OpenCliContractError(f"{source_path}: expected a JSON object")
    site_id = payload.get("site_id")
    if not isinstance(site_id, str) or not site_id:
        raise OpenCliContractError(f"{source_path}: site_id must be a non-empty string")
    opencli_version = payload.get("opencli_version")
    if not isinstance(opencli_version, str) or not opencli_version:
        raise OpenCliContractError(
            f"{source_path}: opencli_version must be a non-empty string"
        )
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise OpenCliContractError(
            f"{source_path}: profiles must be a non-empty object"
        )
    return LoadedContract(
        site_id=site_id,
        opencli_version=opencli_version,
        profiles={
            profile_id: _build_profile(profile_id, raw)
            for profile_id, raw in profiles.items()
        },
        source_path=source_path,
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenCliContractError(f"{path}: cannot read JSON: {exc}") from exc


def load_contract_from_site(
    site_manifest: Path, *, allow_legacy_v1: bool = False
) -> LoadedContract:
    """Load the contract declared by ``site.yaml``'s ``opencli.contract``."""

    try:
        site = load_site(site_manifest, allow_legacy_v1=allow_legacy_v1)
    except HarborManifestError as exc:
        raise OpenCliContractError(str(exc)) from exc
    opencli = site.data.get("opencli")
    if not isinstance(opencli, dict):
        raise OpenCliContractError(
            f"{site_manifest}: site does not declare an 'opencli' block"
        )
    relative = opencli.get("contract")
    if not isinstance(relative, str):
        raise OpenCliContractError(
            f"{site_manifest}: opencli.contract must be a relative path"
        )
    try:
        contract_path = safe_regular_file(site.root, relative)
    except (OSError, ValueError) as exc:
        raise OpenCliContractError(f"{site_manifest}: opencli.contract: {exc}") from exc
    return _contract_from_payload(_read_json(contract_path), source_path=contract_path)


def load_contract_from_runner(runner_json: Path) -> tuple[LoadedContract, str]:
    """Load a materialized bundle's runner file.

    Returns the contract and the single profile id it carries.
    """

    payload = _read_json(runner_json)
    if not isinstance(payload, dict):
        raise OpenCliContractError(f"{runner_json}: expected a JSON object")
    if payload.get("schema_version") != RUNNER_SCHEMA_VERSION:
        raise OpenCliContractError(
            f"{runner_json}: expected schema_version {RUNNER_SCHEMA_VERSION!r}, "
            f"got {payload.get('schema_version')!r}"
        )
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise OpenCliContractError(f"{runner_json}: profile_id must be a string")
    contract_block = payload.get("contract")
    opencli_version = (
        contract_block.get("opencli_version")
        if isinstance(contract_block, dict)
        else None
    )
    synthetic = {
        "site_id": payload.get("site_id"),
        "opencli_version": opencli_version,
        "profiles": {profile_id: payload.get("profile")},
    }
    return _contract_from_payload(synthetic, source_path=runner_json), profile_id
