"""Tests for structural trajectory comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.browser_trajectory.cli import main
from websitebench.browser_trajectory.diff import (
    TrajectoryDiffError,
    diff_trajectories,
    normalize,
    resolve_actions_path,
)


def action(
    event_type: str,
    url: str,
    *,
    event_id: str = "e00000001",
    tag: str | None = None,
    element_id: str | None = None,
    name: str | None = None,
    role: str | None = None,
    class_name: str | None = None,
    xpath: str | None = None,
    **extra: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "websitebench.browser-trajectory.action.v1",
        "event_id": event_id,
        "type": event_type,
        "timestamp_ms": 1_700_000_000_000,
        "url": url,
    }
    target = {
        key: value
        for key, value in {
            "tag": tag,
            "id": element_id,
            "name": name,
            "role": role,
            "class_name": class_name,
            "xpath": xpath,
        }.items()
        if value is not None
    }
    if target:
        record["target"] = target
    record.update(extra)
    return record


def write_ledger(directory: Path, records: list[dict[str, object]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "actions.jsonl"
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return directory


SOURCE = "https://www.example.com"
CLONE = "http://127.0.0.1:8451"


def signin_journey(origin: str) -> list[dict[str, object]]:
    return [
        action("pageLoad", f"{origin}/account/login", event_id="e00000001"),
        action(
            "click",
            f"{origin}/account/login",
            event_id="e00000002",
            tag="INPUT",
            name="login_email_address",
        ),
        action(
            "change",
            f"{origin}/account/login",
            event_id="e00000003",
            tag="INPUT",
            name="login_email_address",
        ),
        action(
            "submit",
            f"{origin}/account/login",
            event_id="e00000004",
            tag="FORM",
            element_id="authenticate",
        ),
        action("pageLoad", f"{origin}/app/trips", event_id="e00000005"),
    ]


def test_identical_journeys_align_completely(tmp_path: Path) -> None:
    source = write_ledger(tmp_path / "src", signin_journey(SOURCE))
    candidate = write_ledger(tmp_path / "cand", signin_journey(CLONE))

    report = diff_trajectories(source, candidate)

    # Origins necessarily differ; only the route path participates.
    assert report.similarity == 1.0
    assert report.findings == []
    assert report.matched == 5


def test_noise_fields_never_produce_divergence(tmp_path: Path) -> None:
    fast = signin_journey(SOURCE)
    slow = signin_journey(CLONE)
    for index, record in enumerate(slow):
        record["timestamp_ms"] = 1_900_000_000_000 + index * 9_999
        record["pointer"] = {"x": index * 37, "y": index * 53}
        record["scroll"] = {"x": 0, "y": index * 400}
    source = write_ledger(tmp_path / "src", fast)
    candidate = write_ledger(tmp_path / "cand", slow)

    report = diff_trajectories(source, candidate)

    assert report.findings == []
    assert report.similarity == 1.0


def test_scroll_and_keystroke_streams_are_dropped(tmp_path: Path) -> None:
    noisy = signin_journey(SOURCE)
    noisy.extend(
        [
            action("scroll", f"{SOURCE}/account/login", event_id="e00000006"),
            action("input", f"{SOURCE}/account/login", event_id="e00000007"),
            action("keydown", f"{SOURCE}/account/login", event_id="e00000008"),
            action("keyup", f"{SOURCE}/account/login", event_id="e00000009"),
        ]
    )
    source = write_ledger(tmp_path / "src", noisy)
    candidate = write_ledger(tmp_path / "cand", signin_journey(CLONE))

    report = diff_trajectories(source, candidate)

    assert report.source_actions_total == 9
    assert len(report.source_steps) == 5
    assert report.findings == []


def test_include_input_opts_the_throttled_stream_back_in(tmp_path: Path) -> None:
    with_input = signin_journey(SOURCE) + [
        action(
            "input",
            f"{SOURCE}/account/login",
            event_id="e00000006",
            tag="INPUT",
            name="login_password",
        )
    ]
    source = write_ledger(tmp_path / "src", with_input)
    candidate = write_ledger(tmp_path / "cand", signin_journey(CLONE))

    assert diff_trajectories(source, candidate).findings == []

    report = diff_trajectories(source, candidate, include_input=True)
    assert [finding.kind for finding in report.findings] == ["missing-in-candidate"]


def test_control_absent_from_candidate_is_reported(tmp_path: Path) -> None:
    candidate_records = [
        record
        for record in signin_journey(CLONE)
        if record["event_id"] != "e00000004"  # the form submit never happens
    ]
    source = write_ledger(tmp_path / "src", signin_journey(SOURCE))
    candidate = write_ledger(tmp_path / "cand", candidate_records)

    report = diff_trajectories(source, candidate)

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.kind == "missing-in-candidate"
    assert finding.source_step is not None
    assert finding.source_step.type == "submit"
    assert finding.candidate_step is None
    assert "form#authenticate" in finding.source_step.label()
    assert report.similarity < 1.0


def test_extra_candidate_step_is_reported(tmp_path: Path) -> None:
    extra = signin_journey(CLONE) + [
        action(
            "click",
            f"{CLONE}/app/trips",
            event_id="e00000006",
            tag="BUTTON",
            element_id="unexpected-modal-dismiss",
        )
    ]
    source = write_ledger(tmp_path / "src", signin_journey(SOURCE))
    candidate = write_ledger(tmp_path / "cand", extra)

    report = diff_trajectories(source, candidate)

    assert [finding.kind for finding in report.findings] == ["extra-in-candidate"]
    assert report.findings[0].candidate_step is not None
    assert report.findings[0].source_step is None


def test_consecutive_pageload_duplicates_always_collapse() -> None:
    # Same-origin frames each emit their own pageLoad for one navigation.
    records = [
        action("pageLoad", f"{SOURCE}/app/trips", event_id=f"e0000000{n}")
        for n in range(1, 4)
    ]
    steps = normalize(records)

    assert len(steps) == 1
    assert steps[0].source_event_ids == ("e00000001", "e00000002", "e00000003")


def test_repeated_clicks_survive_unless_collapse_requested() -> None:
    records = [
        action(
            "click",
            f"{SOURCE}/checkout",
            event_id=f"e0000000{n}",
            tag="BUTTON",
            element_id="place-order",
        )
        for n in range(1, 3)
    ]

    # A double submit is a real behaviour, not injection noise.
    assert len(normalize(records)) == 2
    assert len(normalize(records, collapse_repeats=True)) == 1


def test_strict_mode_compares_dom_shape(tmp_path: Path) -> None:
    source_records = [
        action(
            "click",
            f"{SOURCE}/x",
            tag="BUTTON",
            element_id="go",
            class_name="btn btn-primary",
            xpath="/html[1]/body[1]/div[1]/button[1]",
        )
    ]
    candidate_records = [
        action(
            "click",
            f"{CLONE}/x",
            tag="BUTTON",
            element_id="go",
            class_name="button button--primary",
            xpath="/html[1]/body[1]/main[1]/button[1]",
        )
    ]
    source = write_ledger(tmp_path / "src", source_records)
    candidate = write_ledger(tmp_path / "cand", candidate_records)

    # Styling and nesting differences are not user-perceptible by default.
    assert diff_trajectories(source, candidate).findings == []

    strict = diff_trajectories(source, candidate, strict=True)
    assert {finding.kind for finding in strict.findings} == {
        "missing-in-candidate",
        "extra-in-candidate",
    }


def test_report_declares_diagnostic_authority(tmp_path: Path) -> None:
    source = write_ledger(tmp_path / "src", signin_journey(SOURCE))
    candidate = write_ledger(tmp_path / "cand", signin_journey(CLONE))

    document = diff_trajectories(source, candidate).as_dict()

    assert document["authority"] == "diagnostic"
    assert "satisfies no gate" in document["authority_note"]
    assert document["normalization"]["dropped_event_types"] == [
        "scroll",
        "input",
        "keydown",
        "keyup",
    ]


def test_accepts_a_ledger_file_as_well_as_a_directory(tmp_path: Path) -> None:
    directory = write_ledger(tmp_path / "src", signin_journey(SOURCE))

    assert resolve_actions_path(directory) == directory / "actions.jsonl"
    assert (
        resolve_actions_path(directory / "actions.jsonl")
        == directory / "actions.jsonl"
    )


def test_missing_and_malformed_ledgers_fail_loudly(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(TrajectoryDiffError, match="no actions.jsonl"):
        resolve_actions_path(empty)

    with pytest.raises(TrajectoryDiffError, match="not a trajectory ledger"):
        resolve_actions_path(tmp_path / "absent")

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "actions.jsonl").write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(TrajectoryDiffError, match="not valid JSON"):
        diff_trajectories(broken, broken)


def test_blank_lines_are_tolerated(tmp_path: Path) -> None:
    directory = tmp_path / "src"
    directory.mkdir()
    records = signin_journey(SOURCE)
    (directory / "actions.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n\n",
        encoding="utf-8",
    )

    report = diff_trajectories(directory, directory)

    assert report.source_actions_total == 5
    assert report.findings == []


def test_cli_writes_a_report_and_never_fails_on_divergence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_ledger(tmp_path / "src", signin_journey(SOURCE))
    candidate = write_ledger(
        tmp_path / "cand",
        [r for r in signin_journey(CLONE) if r["event_id"] != "e00000004"],
    )
    output = tmp_path / "nested" / "diff.json"

    code = main(
        [
            "diff",
            "--source",
            str(source),
            "--candidate",
            str(candidate),
            "--output",
            str(output),
        ]
    )

    # Divergence is a finding, not a failure.
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "compared"
    assert summary["findings"] == 1
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["findings"][0]["kind"] == "missing-in-candidate"
    assert document["findings"][0]["source"]["type"] == "submit"


def test_cli_reports_unreadable_input_as_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write_ledger(tmp_path / "src", signin_journey(SOURCE))

    code = main(
        [
            "diff",
            "--source",
            str(source),
            "--candidate",
            str(tmp_path / "absent"),
        ]
    )

    assert code == 2
    assert "not a trajectory ledger" in capsys.readouterr().err
