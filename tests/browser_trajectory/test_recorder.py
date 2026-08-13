from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.browser_trajectory.cli import build_parser, main
from websitebench.browser_trajectory.recorder import (
    ACTION_CAPTURE_SCRIPT,
    ACTION_SCHEMA_VERSION,
    BrowserTrajectoryError,
    RecorderConfig,
    TrajectoryRecorder,
    safe_url,
)


class _FakePage:
    def screenshot(self, *, path: str, type: str) -> None:
        assert type == "png"
        Path(path).write_bytes(b"fixture-png")


class _InstrumentableFrame:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def evaluate(self, script: str) -> None:
        self.scripts.append(script)


class _InstrumentablePage(_InstrumentableFrame):
    def __init__(self) -> None:
        super().__init__()
        self.child_frame = _InstrumentableFrame()
        self.frames = [self, self.child_frame]


def _config(tmp_path: Path, **kwargs: object) -> RecorderConfig:
    return RecorderConfig(
        output_dir=tmp_path / "trajectory",
        allowed_origins=("https://example.test",),
        **kwargs,
    )


def test_recorder_retains_structure_and_never_input_values(tmp_path: Path) -> None:
    secret = "password=do-not-retain"
    recorder = TrajectoryRecorder(_config(tmp_path, screenshots=True))
    recorder._record_payload(
        {
            "type": "input",
            "timestamp": 1_710_000_001_234,
            "url": "https://example.test/account?token=query-secret#private",
            "target": {
                "tagName": "INPUT",
                "id": "password",
                "name": "password",
                "type": "password",
                "className": "form-control",
                "xpath": "/html[1]/body[1]/form[1]/input[1]",
                "textContent": secret,
            },
            "value": secret,
            "key": "p",
        },
        _FakePage(),
    )
    recorder.close(status="complete")

    action = json.loads(recorder._actions_path.read_text(encoding="utf-8"))
    retained = recorder._actions_path.read_text(
        encoding="utf-8"
    ) + recorder._session_path.read_text(encoding="utf-8")
    assert secret not in retained
    assert "query-secret" not in retained
    assert action == {
        "schema_version": ACTION_SCHEMA_VERSION,
        "event_id": "e00000001",
        "type": "input",
        "timestamp_ms": 1_710_000_001_234,
        "url": "https://example.test/account",
        "target": {
            "tag": "INPUT",
            "id": "password",
            "name": "password",
            "input_type": "password",
            "class_name": "form-control",
            "xpath": "/html[1]/body[1]/form[1]/input[1]",
        },
        "input_value": "omitted",
        "key": "character",
        "screenshot": "screenshots/e00000001.png",
    }
    assert (recorder.output_dir / action["screenshot"]).read_bytes() == b"fixture-png"


def test_recorder_ignores_events_outside_the_declared_origins(tmp_path: Path) -> None:
    recorder = TrajectoryRecorder(_config(tmp_path))
    recorder._record_payload(
        {"type": "click", "url": "https://outside.test/", "timestamp": 1}
    )
    recorder.close(status="complete")
    assert recorder._actions_path.read_text(encoding="utf-8") == ""
    session = json.loads(recorder._session_path.read_text(encoding="utf-8"))
    assert session["counts"]["dropped_events"] == 1


def test_output_directory_is_append_free_and_origins_must_be_http(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "existing.txt").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(BrowserTrajectoryError, match="non-empty"):
        TrajectoryRecorder(
            RecorderConfig(
                output_dir=output,
                allowed_origins=("https://example.test",),
            )
        )
    with pytest.raises(BrowserTrajectoryError, match="valid HTTP"):
        RecorderConfig(output_dir=tmp_path / "bad", allowed_origins=("file:///tmp",))


def test_url_and_injected_listener_contract_are_privacy_preserving() -> None:
    assert safe_url("https://user:pass@example.test:443/a?token=secret#fragment") == (
        "https://example.test/a"
    )
    assert "textContent" not in ACTION_CAPTURE_SCRIPT
    assert "payload.value" not in ACTION_CAPTURE_SCRIPT
    assert "__websitebenchTrajectory" in ACTION_CAPTURE_SCRIPT


def test_existing_child_frames_are_instrumented(tmp_path: Path) -> None:
    recorder = TrajectoryRecorder(_config(tmp_path))
    page = _InstrumentablePage()
    recorder._attach_page(page)
    recorder.close(status="complete")
    assert page.scripts == [ACTION_CAPTURE_SCRIPT, ACTION_CAPTURE_SCRIPT]
    assert page.child_frame.scripts == [ACTION_CAPTURE_SCRIPT]


def test_cli_requires_an_origin_and_rejects_negative_duration(tmp_path: Path) -> None:
    parser = build_parser()
    assert parser.prog == "websitebench-browser-trajectory"
    assert (
        main(
            [
                "record",
                "--output",
                str(tmp_path / "output"),
                "--allowed-origin",
                "https://example.test",
                "--duration-seconds",
                "-1",
            ]
        )
        == 2
    )
