"""Behavioural guarantees for the OpenCLI replay runner.

Everything here runs without a live target and without the real ``opencli``
binary: backends are driven through a fake executable written to ``tmp_path``,
or replaced by a stub implementing the same ``run_step`` protocol. The point is
to pin the safety properties — non-gating exit behaviour, redaction, the verb
allow-list, and graceful degradation — not to re-test HTTP.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from websitebench.harbor.opencli.backends import (
    AdapterBackend,
    StepResult,
    UnsupportedCommandError,
)
from websitebench.harbor.opencli.contract import (
    LoadedContract,
    OpenCliContractError,
    Profile,
    SessionPrecondition,
    Step,
    load_contract_from_site,
)
from websitebench.harbor.opencli.doctor import DoctorReport
from websitebench.harbor.opencli.runner import (
    AUTHORITY,
    replay_profile,
    select_backend,
    write_result,
)

ROOT = Path(__file__).resolve().parents[2]
PETFINDER = ROOT / "harbor" / "sites" / "petfinder" / "site.yaml"

DOWN = DoctorReport(
    binary_present=True,
    version="1.8.6",
    extension_connected=False,
    connectivity_ok=False,
    notes=("opencli-unavailable: Browser Bridge extension not connected",),
)
GREEN = DoctorReport(
    binary_present=True, version="1.8.6", extension_connected=True, connectivity_ok=True
)


def _step(command: str = "state", **overrides: object) -> Step:
    values: dict[str, object] = {
        "id": "only-step",
        "observation_id": "only_step",
        "command": command,
        "route": "some/route/",
        "tier": "p0",
    }
    values.update(overrides)
    return Step(**values)  # type: ignore[arg-type]


def _contract(profile: Profile) -> LoadedContract:
    return LoadedContract(
        site_id="petfinder",
        opencli_version="1.8.6",
        profiles={profile.id: profile},
        source_path=ROOT
        / "harbor/sites/petfinder/interactions/opencli-interaction-contract.json",
    )


class _StubBackend:
    """Implements the backend protocol without touching a process or a socket."""

    name = "stub"

    def __init__(self, result: StepResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def run_step(self, step: Step, *, base_url: str, session: str) -> StepResult:
        self.calls.append((step.id, session))
        return self.result


def _fake_opencli(tmp_path: Path, *, stdout: str, code: int = 0) -> str:
    script = tmp_path / "fake-opencli"
    script.write_text(
        f"#!/usr/bin/env bash\ncat <<'PAYLOAD'\n{stdout}\nPAYLOAD\nexit {code}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


# --------------------------------------------------------------------------
# Verb allow-list
# --------------------------------------------------------------------------


def test_unknown_command_is_refused_at_dispatch() -> None:
    backend = AdapterBackend(site_id="petfinder", binary="/nonexistent")
    with pytest.raises(UnsupportedCommandError, match="frobnicate"):
        backend.run_step(_step("frobnicate"), base_url="http://127.0.0.1:1", session="")


def test_unknown_command_becomes_an_error_step_not_an_exception() -> None:
    profile = Profile(
        id="p",
        label="p",
        tier="p0",
        steps=(_step("frobnicate"),),
        network_allowlist=("127.0.0.1",),
    )
    payload = replay_profile(
        _contract(profile),
        "p",
        base_url="http://127.0.0.1:18082",
        backend=AdapterBackend(site_id="petfinder", binary="/nonexistent"),
        report=DOWN,
    )
    assert payload["status"] == "failed"
    assert payload["summary"]["unsupported_commands"] == 1
    assert payload["steps"][0]["outcome"] == "error"


# --------------------------------------------------------------------------
# Backend selection and degradation
# --------------------------------------------------------------------------


def test_browser_backend_is_refused_when_doctor_is_not_green() -> None:
    with pytest.raises(OpenCliContractError, match="Browser Bridge"):
        select_backend(
            requested="browser",
            site_id="petfinder",
            report=DOWN,
            binary="opencli",
            timeout=5,
        )


def test_auto_degrades_to_adapter_and_records_why() -> None:
    backend, notes = select_backend(
        requested="auto", site_id="petfinder", report=DOWN, binary="opencli", timeout=5
    )
    assert backend.name == "adapter"
    assert any("opencli-unavailable" in note for note in notes)
    assert any("degraded" in note for note in notes)


def test_auto_prefers_browser_when_doctor_is_green() -> None:
    backend, notes = select_backend(
        requested="auto", site_id="petfinder", report=GREEN, binary="opencli", timeout=5
    )
    assert backend.name == "browser"
    assert notes == []


# --------------------------------------------------------------------------
# Target binding
# --------------------------------------------------------------------------


def test_target_outside_the_profile_allowlist_is_refused() -> None:
    profile = Profile(
        id="p", label="p", tier="p0", steps=(_step(),), network_allowlist=("127.0.0.1",)
    )
    with pytest.raises(
        OpenCliContractError, match="not in the profile network allowlist"
    ):
        replay_profile(
            _contract(profile),
            "p",
            base_url="http://localhost:18082",
            backend=_StubBackend(StepResult("s", "s", "state", "p0", "r", "passed")),
            report=DOWN,
        )


def test_external_target_is_refused_even_when_a_contract_allowlists_it() -> None:
    """Hand-authored allowlists cannot turn local replay into an external POST."""

    profile = Profile(
        id="p",
        label="p",
        tier="p0",
        steps=(_step(),),
        network_allowlist=("evil.example.com",),
    )
    with pytest.raises(OpenCliContractError, match="is not loopback"):
        replay_profile(
            _contract(profile),
            "p",
            base_url="https://evil.example.com",
            backend=_StubBackend(StepResult("s", "s", "state", "p0", "r", "passed")),
            report=DOWN,
        )


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("http://user:secret@127.0.0.1:18082", "is not loopback"),
        ("http://127.0.0.1:bad", "invalid base URL"),
        ("http://127.0.0.1:0", "is not loopback"),
    ],
)
def test_malformed_loopback_origins_are_refused(base_url: str, message: str) -> None:
    profile = Profile(
        id="p",
        label="p",
        tier="p0",
        steps=(_step(),),
        network_allowlist=("127.0.0.1",),
    )
    with pytest.raises(OpenCliContractError, match=message):
        replay_profile(
            _contract(profile),
            "p",
            base_url=base_url,
            backend=_StubBackend(StepResult("s", "s", "state", "p0", "r", "passed")),
            report=DOWN,
        )


# --------------------------------------------------------------------------
# Artifact shape and safety properties
# --------------------------------------------------------------------------


def _passing_payload() -> dict[str, object]:
    result = StepResult(
        step_id="only-step",
        observation_id="only_step",
        command="state",
        tier="p0",
        declared_route="some/route/",
        outcome="passed",
        http_status=200,
        observations=[
            {
                "key": "visible",
                "expected": "Nala",
                "observed": "Nala",
                "asserted": True,
                "passed": True,
            },
            {
                "key": "expectation",
                "expected": "prose",
                "observed": "",
                "asserted": False,
                "passed": None,
            },
        ],
    )
    profile = Profile(
        id="p", label="p", tier="p0", steps=(_step(),), network_allowlist=("127.0.0.1",)
    )
    return replay_profile(
        _contract(profile),
        "p",
        base_url="http://127.0.0.1:18082",
        backend=_StubBackend(result),
        report=DOWN,
    )


def test_artifact_carries_the_diagnostic_authority_string() -> None:
    payload = _passing_payload()
    assert payload["authority"] == AUTHORITY
    assert payload["authority"] == "diagnostic-only"


def test_artifact_uses_a_repository_relative_contract_path() -> None:
    payload = _passing_payload()
    assert payload["contract"]["path"] == (
        "harbor/sites/petfinder/interactions/opencli-interaction-contract.json"
    )


def test_artifact_has_no_content_seal() -> None:
    payload = _passing_payload()
    assert "content_sha256" not in payload
    assert "sha256" not in payload["contract"]


def test_unasserted_observations_never_fail_a_step() -> None:
    payload = _passing_payload()
    assert payload["status"] == "passed"
    assert payload["summary"]["assertion_failures"] == 0
    assert payload["summary"]["unasserted_observations"] == 1


def test_session_values_never_reach_the_artifact() -> None:
    session = SessionPrecondition(
        route="fixture/session",
        method="POST",
        fields={"csrf": "super-secret-value", "account": "alex-green"},
    )
    profile = Profile(
        id="p",
        label="p",
        tier="p0",
        steps=(_step(),),
        session=session,
        network_allowlist=("127.0.0.1",),
    )
    stub = _StubBackend(
        StepResult("only-step", "only_step", "state", "p0", "r", "passed")
    )
    # The session POST targets a closed port, which surfaces as a contract error
    # rather than silently continuing without a session.
    with pytest.raises(OpenCliContractError, match="session precondition failed"):
        replay_profile(
            _contract(profile),
            "p",
            base_url="http://127.0.0.1:1",
            backend=stub,
            report=DOWN,
        )


def test_session_field_names_are_recorded_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from websitebench.harbor.opencli import runner as runner_module

    monkeypatch.setattr(
        runner_module, "_post_form", lambda *args, **kwargs: (303, "sid=abc123")
    )
    session = SessionPrecondition(
        route="fixture/session", method="POST", fields={"csrf": "super-secret-value"}
    )
    profile = Profile(
        id="p",
        label="p",
        tier="p0",
        steps=(_step(),),
        session=session,
        network_allowlist=("127.0.0.1",),
    )
    stub = _StubBackend(
        StepResult("only-step", "only_step", "state", "p0", "r", "passed")
    )
    payload = replay_profile(
        _contract(profile),
        "p",
        base_url="http://127.0.0.1:18082",
        backend=stub,
        report=DOWN,
    )
    serialized = json.dumps(payload)
    assert payload["target_binding"]["session_fields"] == ["csrf"]
    assert "super-secret-value" not in serialized
    assert "sid=abc123" not in serialized
    # The session must still have reached the backend.
    assert stub.calls == [("only-step", "sid=abc123")]


def test_write_result_refuses_to_clobber(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    payload = _passing_payload()
    write_result(payload, output)
    with pytest.raises(OpenCliContractError, match="refusing to overwrite"):
        write_result(payload, output)
    write_result(payload, output, force=True)


# --------------------------------------------------------------------------
# Subprocess sentinels
# --------------------------------------------------------------------------


def test_missing_binary_becomes_an_error_step_not_a_crash() -> None:
    backend = AdapterBackend(site_id="petfinder", binary="/nonexistent/opencli")
    result = backend.run_step(_step(), base_url="http://127.0.0.1:1", session="")
    assert result.outcome == "error"
    assert result.error


def test_adapter_rows_are_graded_by_the_asserted_flag(tmp_path: Path) -> None:
    rows = json.dumps(
        [
            {
                "status": 200,
                "checkKey": "visible",
                "expected": "x",
                "observed": "x",
                "passed": True,
                "asserted": True,
                "setCookie": "",
            },
            {
                "status": 200,
                "checkKey": "expectation",
                "expected": "prose",
                "observed": "",
                "passed": None,
                "asserted": False,
                "setCookie": "",
            },
        ]
    )
    backend = AdapterBackend(
        site_id="petfinder", binary=_fake_opencli(tmp_path, stdout=rows)
    )
    result = backend.run_step(_step(), base_url="http://127.0.0.1:1", session="")
    assert result.outcome == "passed"
    assert result.http_status == 200
    assert [item["asserted"] for item in result.observations] == [True, False]


def test_failed_assertion_is_data_not_an_error(tmp_path: Path) -> None:
    rows = json.dumps(
        [
            {
                "status": 200,
                "checkKey": "visible",
                "expected": "x",
                "observed": "",
                "passed": False,
                "asserted": True,
                "setCookie": "",
            }
        ]
    )
    backend = AdapterBackend(
        site_id="petfinder", binary=_fake_opencli(tmp_path, stdout=rows)
    )
    result = backend.run_step(_step(), base_url="http://127.0.0.1:1", session="")
    assert result.outcome == "failed"
    assert result.error is None


def test_zero_selector_matches_fails_the_adapter_step(tmp_path: Path) -> None:
    """A stale selector is an asserted contract mismatch, not a silent pass."""

    rows = json.dumps(
        [
            {
                "status": 200,
                "selectorMatches": 0,
                "checkKey": "title",
                "expected": "Eventbrite",
                "observed": "Eventbrite",
                "passed": True,
                "asserted": True,
                "setCookie": "",
            }
        ]
    )
    backend = AdapterBackend(
        site_id="eventbrite", binary=_fake_opencli(tmp_path, stdout=rows)
    )
    result = backend.run_step(
        _step(selector="li.result-card"),
        base_url="http://127.0.0.1:1",
        session="",
    )
    assert result.outcome == "failed"
    assert result.observations[0] == {
        "key": "selector",
        "expected": "at least one match",
        "observed": "0",
        "asserted": True,
        "passed": False,
    }


def test_nonzero_opencli_exit_becomes_an_error_step(tmp_path: Path) -> None:
    backend = AdapterBackend(
        site_id="petfinder", binary=_fake_opencli(tmp_path, stdout="boom", code=1)
    )
    result = backend.run_step(_step(), base_url="http://127.0.0.1:1", session="")
    assert result.outcome == "error"
    assert "boom" in (result.error or "")


def test_submit_fields_are_only_passed_for_submit_steps() -> None:
    backend = AdapterBackend(site_id="petfinder", binary="opencli")
    submit = _step("submit", fields={"username": "a@b.test"}, selector="form")
    state = _step("state", fields={"username": "a@b.test"})
    assert "--fields" in backend._argv(submit, base_url="http://x", session="")
    assert "--fields" not in backend._argv(state, base_url="http://x", session="")


# --------------------------------------------------------------------------
# Real corpus wiring
# --------------------------------------------------------------------------


def test_petfinder_profiles_expose_only_executable_verbs() -> None:
    contract = load_contract_from_site(PETFINDER, allow_legacy_v1=True)
    commands = {
        step.command for profile in contract.profiles.values() for step in profile.steps
    }
    assert commands <= {"state", "click", "submit"}


def test_opencli_is_not_referenced_by_any_scoring_verifier() -> None:
    """OpenCLI results are advisory; no site verifier may consume them."""

    for verifier in (ROOT / "harbor" / "sites").glob("*/verifier/run.py"):
        assert "opencli" not in verifier.read_text(encoding="utf-8").lower(), verifier
