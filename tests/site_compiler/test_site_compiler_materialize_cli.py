from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.site_compiler.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "generic-v2"
INVENTORY = FIXTURE_ROOT / "platform-inventory.json"
PROFILES = FIXTURE_ROOT / "profiles"
PACKS = REPO_ROOT / "websitebench" / "capability-packs"


def _unblocked_target(tmp_path: Path) -> Path:
    return PROFILES / "alpha-market" / "site.json"


def _single_profile_args(command: str, profile: Path | None = None) -> list[str]:
    return [
        command,
        "--inventory",
        str(INVENTORY),
        "--profile",
        str(profile or (PROFILES / "alpha-market" / "site.json")),
        "--packs-root",
        str(PACKS),
        "--target",
        "scope",
    ]


def test_compile_and_check_one_materialized_scope_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    site_dir = tmp_path / "site"
    compiled_dir = tmp_path / "compiled"
    profile = _unblocked_target(tmp_path)

    assert main(
        [
            *_single_profile_args("compile", profile),
            "--out",
            str(compiled_dir),
            "--site-dir",
            str(site_dir),
        ]
    ) == 0
    compiled = json.loads(capsys.readouterr().out)
    assert compiled["status"] == "compiled-and-materialized"
    assert compiled["compiled"]["status"] == "written"
    assert compiled["materialized"]["status"] == "materialized"
    assert compiled["materialized"]["stage"] == "machine-scope"
    assert (site_dir / "clone.yaml").is_file()

    assert main(
        [
            *_single_profile_args("check", profile),
            "--out",
            str(compiled_dir),
            "--site-dir",
            str(site_dir),
        ]
    ) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["status"] == "current"
    assert checked["compiled"]["status"] == "current"
    assert checked["materialization"]["status"] == "current"
    assert checked["materialization"]["stage"] == "machine-scope"


def test_explicit_materialize_command_creates_scope_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    site_dir = tmp_path / "site"
    assert main(
        [
            "materialize",
            "--inventory",
            str(INVENTORY),
            "--profile",
            str(_unblocked_target(tmp_path)),
            "--packs-root",
            str(PACKS),
            "--site-dir",
            str(site_dir),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "materialized"
    assert result["stage"] == "machine-scope"
    assert (site_dir / "clone.yaml").is_file()


def test_check_site_dir_detects_materialization_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    site_dir = tmp_path / "site"
    profile = _unblocked_target(tmp_path)
    assert main(
        [
            *_single_profile_args("compile", profile),
            "--site-dir",
            str(site_dir),
        ]
    ) == 0
    capsys.readouterr()
    backend = site_dir / "backend/model.json"
    backend.write_bytes(backend.read_bytes() + b" ")

    assert main(
        [
            *_single_profile_args("check", profile),
            "--site-dir",
            str(site_dir),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "drifted" in captured.err
    assert "backend/model.json" in captured.err


@pytest.mark.parametrize(
    ("command", "extra_args", "message"),
    [
        (
            "compile",
            ["--profiles-root", str(PROFILES), "--site-dir", "{site}"],
            "batch --profiles-root materialization is forbidden",
        ),
        (
            "check",
            ["--profiles-root", str(PROFILES), "--site-dir", "{site}"],
            "batch --profiles-root materialization is forbidden",
        ),
    ],
)
def test_materialization_options_fail_closed_for_ambiguous_scope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    extra_args: list[str],
    message: str,
) -> None:
    site_dir = tmp_path / "site"
    resolved_extra = [
        value.format(site=site_dir) for value in extra_args
    ]
    argv = [
        command,
        "--inventory",
        str(INVENTORY),
        "--packs-root",
        str(PACKS),
        "--target",
        "scope",
        *resolved_extra,
    ]
    if command == "compile" and "--site-dir" not in resolved_extra:
        argv.extend(["--out", str(tmp_path / "compiled")])

    assert main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
    assert not site_dir.exists()
    assert not (tmp_path / "compiled").exists()


@pytest.mark.parametrize("command", ["compile", "check"])
def test_materialization_rejects_non_scope_target_before_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    site_dir = tmp_path / "site"
    compiled_dir = tmp_path / "compiled"
    argv = [
        command,
        "--inventory",
        str(INVENTORY),
        "--profile",
        str(PROFILES / "alpha-market/site.json"),
        "--packs-root",
        str(PACKS),
        "--target",
        "release",
        "--site-dir",
        str(site_dir),
    ]
    if command == "compile":
        argv.extend(["--out", str(compiled_dir)])

    assert main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--site-dir requires --target scope" in captured.err
    assert not site_dir.exists()
    assert not compiled_dir.exists()


def test_blocked_profile_materialization_writes_no_optional_compile_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    site_dir = tmp_path / "site"
    compiled_dir = tmp_path / "compiled"
    assert main(
        [
            "compile",
            "--inventory",
            str(INVENTORY),
            "--profile",
            str(PROFILES / "beta-learning/site.json"),
            "--packs-root",
            str(PACKS),
            "--target",
            "scope",
            "--site-dir",
            str(site_dir),
            "--out",
            str(compiled_dir),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "blocked" in captured.err
    assert not site_dir.exists()
    assert not compiled_dir.exists()


def test_compile_still_requires_an_output_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(_single_profile_args("compile")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "compile requires --out, --site-dir, or both" in captured.err
