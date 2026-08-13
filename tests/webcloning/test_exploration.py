from __future__ import annotations

import json
from pathlib import Path

import yaml

from websitebench.webcloning.cli import main as webcloning_main
from websitebench.webcloning.contracts import (
    require_valid,
    write_json_atomic,
)
from websitebench.webcloning.exploration import (
    build_exploration_bundle,
    build_exploration_coverage,
    import_clawbench_run,
    select_clawbench_runs,
)
from websitebench.webcloning.trace import normalize_trace

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def _task(path: Path, *, task_id: int = 1035) -> None:
    _write_json(
        path,
        {
            "metadata": {"task_id": task_id, "platform": "edx"},
            "instruction": "Enroll without retaining user credentials.",
        },
    )


def _run(
    root: Path,
    name: str,
    *,
    success: bool,
    password: str = "super-secret-password",
) -> Path:
    run = root / name
    _write_json(
        run / "run-meta.json",
        {
            "timestamp": name.rsplit("-", 2)[-2] + "-" + name.rsplit("-", 1)[-1],
            "harness": "hermes",
            "model": "fixture-model",
            "provider": "fixture",
        },
    )
    _write_json(run / "data" / "interception.json", {"intercepted": success})
    _write_json(run / "data" / "judge.json", {"match": success})
    _write_jsonl(
        run / "data" / "actions.jsonl",
        [
            {
                "type": "pageLoad",
                "url": "https://www.edx.org/course?token=query-secret",
                "title": "Course",
            },
            {
                "type": "input",
                "url": "https://authn.edx.org/register",
                "target": {
                    "tagName": "INPUT",
                    "id": "password",
                    "type": "password",
                    "xpath": "/form/input[4]",
                },
                "value": password,
            },
            {
                "type": "change",
                "url": "https://authn.edx.org/register",
                "target": {
                    "tagName": "INPUT",
                    "id": "email",
                    "type": "email",
                },
                "value": "private-person@example.test",
            },
            {
                "type": "click",
                "url": "https://authn.edx.org/register",
                "target": {
                    "tagName": "BUTTON",
                    "textContent": "Create account",
                    "xpath": "/form/button",
                },
            },
        ],
    )
    _write_jsonl(
        run / "data" / "agent-messages.jsonl",
        [
            {
                "role": "assistant",
                "content": f"I reasoned about password={password}",
            },
            {
                "role": "tool",
                "name": "browser_click",
                "content": "cookie=session-secret",
            },
        ],
    )
    return run


def test_selects_latest_success_and_failure_without_cross_task_scan(
    tmp_path: Path,
) -> None:
    old_success = _run(
        tmp_path,
        "hermes-v2-1035-edx-model-20260509-120000",
        success=True,
    )
    latest_success = _run(
        tmp_path,
        "hermes-v2-1035-edx-model-20260510-120000",
        success=True,
    )
    failure = _run(
        tmp_path,
        "hermes-v2-1035-edx-model-20260511-120000",
        success=False,
    )
    _run(
        tmp_path,
        "hermes-v2-1036-other-model-20260512-120000",
        success=True,
    )
    selected = select_clawbench_runs(runs_root=tmp_path, task_id=1035)
    assert selected["candidate_count"] == 3
    assert selected["success"] == str(latest_success)
    assert selected["failure"] == str(failure)
    assert selected["success"] != str(old_success)
    assert selected["status"] == "complete"


def test_select_runs_cli_writes_task_scoped_selection(tmp_path: Path) -> None:
    selected_run = _run(
        tmp_path / "controlled-cache",
        "hermes-v2-1035-edx-model-20260510-120000",
        success=True,
    )
    output = tmp_path / "selection.json"
    result = webcloning_main(
        [
            "select-clawbench-runs",
            "--runs-root",
            str(tmp_path / "controlled-cache"),
            "--task-id",
            "1035",
            "--output",
            str(output),
        ]
    )
    assert result == 0
    selection = json.loads(output.read_text(encoding="utf-8"))
    assert selection["task_id"] == 1035
    assert selection["success"] == str(selected_run)
    assert selection["failure"] is None
    assert selection["status"] == "incomplete"


def test_real_action_import_redacts_values_and_agent_content(tmp_path: Path) -> None:
    secret = "fixture-password-never-retained"
    task = tmp_path / "source-task.json"
    _task(task)
    run = _run(
        tmp_path / "controlled-cache",
        "hermes-v2-1035-edx-model-20260510-120000",
        success=True,
        password=secret,
    )
    imported = import_clawbench_run(
        run_dir=run,
        task_path=task,
        artifact_root=tmp_path,
        output_dir=tmp_path / "artifacts" / "imported",
        site_id="edx",
        suite="v2",
    )
    trace = imported["trace"]
    require_valid(trace, location="imported", root=tmp_path)
    retained = (
        imported["sanitized_actions_path"].read_text(encoding="utf-8")
        + imported["transcript_path"].read_text(encoding="utf-8")
        + imported["provenance_path"].read_text(encoding="utf-8")
        + json.dumps(trace, ensure_ascii=False)
    )
    assert secret not in retained
    assert "private-person@example.test" not in retained
    assert "session-secret" not in retained
    assert "query-secret" not in retained
    assert "I reasoned" not in retained
    assert "[REDACTED:sensitive-input]" in retained
    provenance = json.loads(
        imported["provenance_path"].read_text(encoding="utf-8")
    )
    assert provenance["raw_content_retained"] is False
    assert {
        item["name"] for item in provenance["source_files"]
    } >= {"data/actions.jsonl", "data/agent-messages.jsonl"}
    assert all(
        step["action"]["family"] != "other"
        for step in trace["steps"]
    )


def _write_trace(
    root: Path,
    *,
    name: str,
    environment: str,
    title: str,
    target: str = "course",
) -> Path:
    folder = root / name
    task = folder / "task.json"
    run = folder / "run.json"
    actions = folder / "actions.jsonl"
    _task(task, task_id=1)
    _write_json(
        run,
        {
            "agent": "fixture",
            "model": "fixture",
            "provider": "fixture",
            "config_sha256": "a" * 64,
            "seed": 1,
            "run_id": name,
            "task_result": "success",
            "raw_trace_access": "repository-redacted",
        },
    )
    _write_jsonl(
        actions,
        [
            {
                "action": "click",
                "target": target,
                "before": {"url": "/home", "title": "Home", "markers": []},
                "after": {
                    "url": "/course",
                    "title": title,
                    "markers": [title],
                },
                "outcome": "ok",
            }
        ],
    )
    value = normalize_trace(
        raw_path=actions,
        task_path=task,
        run_manifest_path=run,
        artifact_root=root,
        site_id="edx",
        environment=environment,
        suite="fixture",
    )
    path = root / f"{name}.json"
    write_json_atomic(path, value)
    return path


def _bundle(
    root: Path,
    *,
    name: str,
    traces: list[Path],
    hypotheses: list[dict] | None = None,
) -> Path:
    spec = root / f"{name}-spec.json"
    _write_json(
        spec,
        {
            "site_id": "edx",
            "strategy": "dfs",
            "source_context": {
                "supervisor": "Fixture Human",
                "viewport": "desktop",
            },
            "traces": [path.relative_to(root).as_posix() for path in traces],
            "interaction_transcripts": [],
            "frontier": [{"route": "/unvisited", "reason": "budget"}],
            "architecture_hypotheses": hypotheses or [],
            "status": "complete",
        },
    )
    value = build_exploration_bundle(repository_root=root, spec_path=spec)
    path = root / f"{name}.json"
    write_json_atomic(path, value)
    require_valid(value, location=name, root=root)
    return path


def test_bundle_and_coverage_report_missing_and_inferred_separately(
    tmp_path: Path,
) -> None:
    source = _write_trace(
        tmp_path, name="source", environment="source", title="Source course"
    )
    clone = _write_trace(
        tmp_path, name="clone", environment="clone", title="Clone course"
    )
    bundle = _bundle(
        tmp_path,
        name="dfs-bundle",
        traces=[source],
        hypotheses=[
            {
                "id": "service-boundary",
                "layer": "backend",
                "summary": "A course service is inferred from requests.",
            }
        ],
    )
    spec = tmp_path / "coverage-spec.json"
    _write_json(
        spec,
        {
            "site_id": "edx",
            "bundles": [bundle.relative_to(tmp_path).as_posix()],
            "clone_traces": [clone.relative_to(tmp_path).as_posix()],
        },
    )
    coverage = build_exploration_coverage(
        repository_root=tmp_path, spec_path=spec
    )
    require_valid(coverage, location="coverage", root=tmp_path)
    assert coverage["counts"]["missing"] == 1
    assert coverage["counts"]["matched"] == 0
    assert coverage["architecture"] == {
        "inferred": 1,
        "conflicting": 0,
        "unavailable": 0,
    }
    assert coverage["status"] == "incomplete"


def test_conflicting_source_observations_fail_closed(tmp_path: Path) -> None:
    source_a = _write_trace(
        tmp_path, name="source-a", environment="source", title="Course A"
    )
    source_b = _write_trace(
        tmp_path, name="source-b", environment="source", title="Course B"
    )
    clone = _write_trace(
        tmp_path, name="clone", environment="clone", title="Course A"
    )
    bundle = _bundle(
        tmp_path,
        name="conflicting-bundle",
        traces=[source_a, source_b],
    )
    spec = tmp_path / "conflicting-coverage-spec.json"
    _write_json(
        spec,
        {
            "site_id": "edx",
            "bundles": [bundle.relative_to(tmp_path).as_posix()],
            "clone_traces": [clone.relative_to(tmp_path).as_posix()],
        },
    )
    coverage = build_exploration_coverage(
        repository_root=tmp_path, spec_path=spec
    )
    require_valid(coverage, location="coverage", root=tmp_path)
    assert coverage["counts"]["conflicting"] == 2
    assert coverage["status"] == "incomplete"


def test_skill_is_explicit_only() -> None:
    skill = REPOSITORY_ROOT / "skills" / "trace-guided-offline-clone"
    metadata = yaml.safe_load(
        (skill / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    assert metadata["policy"]["allow_implicit_invocation"] is False
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert "$trace-guided-offline-clone" in text
    assert "machine-verification" in text.casefold()
    assert "human-supervised" not in text.casefold()
