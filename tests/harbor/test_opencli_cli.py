"""CLI defaults and documentation for local OpenCLI contract replay."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from websitebench.harbor.cli import build_parser, main


ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SITE = ROOT / "harbor" / "sites" / "tripit" / "site.yaml"


def _parse_run_opencli() -> argparse.Namespace:
    return build_parser().parse_args(
        [
            "run-opencli",
            "--site",
            str(GOLDEN_SITE),
            "--profile",
            "marketing-and-auth-entry",
            "--out",
            "result.json",
            "--legacy-v1",
        ]
    )


def test_run_opencli_defaults_to_candidate_without_a_site_specific_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEBSITEBENCH_ADMIN_TOKEN", raising=False)

    args = _parse_run_opencli()

    assert args.target == "candidate"
    assert args.admin_token == ""


def test_run_opencli_reads_the_generic_admin_token_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBSITEBENCH_ADMIN_TOKEN", "local-replay-token")

    args = _parse_run_opencli()

    assert args.admin_token == "local-replay-token"


def test_run_opencli_explicit_admin_token_overrides_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBSITEBENCH_ADMIN_TOKEN", "environment-token")

    args = build_parser().parse_args(
        [
            "run-opencli",
            "--site",
            str(GOLDEN_SITE),
            "--profile",
            "marketing-and-auth-entry",
            "--out",
            "result.json",
            "--admin-token",
            "explicit-token",
            "--legacy-v1",
        ]
    )

    assert args.admin_token == "explicit-token"


def test_missing_base_url_points_to_the_candidate_clone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "run-opencli",
            "--site",
            str(GOLDEN_SITE),
            "--profile",
            "marketing-and-auth-entry",
            "--out",
            "result.json",
            "--legacy-v1",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "start the candidate clone first" in captured.err
    assert "http://127.0.0.1:18913" in captured.err
    assert "reference/run.sh" not in captured.err


def test_replay_documentation_matches_cli_defaults_and_committed_evidence() -> None:
    replay = (ROOT / "docs" / "opencli-contract-replay.md").read_text(encoding="utf-8")

    assert "`--target candidate`" in replay and "the default" in replay
    assert "`WEBSITEBENCH_ADMIN_TOKEN`" in replay
    assert "interactions/replay-evidence/<profile-id>.json" in replay
    assert "test-output/" in replay and "cannot" in replay
