from __future__ import annotations

import json
import os
import signal
import socket
import stat
from pathlib import Path

import pytest
import yaml

from websitebench.harbor.bundle_v2 import validate_bundle
from websitebench.harbor.case_protocol import (
    CaseProtocolError,
    canonical_json_bytes,
    compute_case_evaluation,
    publish_case_evaluation,
    sealed_case_manifest,
    synthesize_zero_results,
    validate_case_manifest_payload,
)
from websitebench.harbor.cli import main as harbor_main
from websitebench.harbor.compiler_v2 import (
    CompilerSandboxError,
    compile_candidate,
    quarantine_artifact,
    tree_digest,
    validate_artifact_tree,
    validate_runtime_lifecycle,
)
from websitebench.harbor.executors_v2 import (
    BrowserUseRuntime,
    CandidateCaseFailure,
    CaseExecutionContext,
    CaseOutcome,
    ExecutorPolicyError,
    InfrastructureCaseFailure,
    compile_neutral_actions,
    execute_case_manifest,
    sanitized_browser_use_environment,
)
from websitebench.harbor.finalizer_v2 import finalize_run, validate_receipt_run
from websitebench.harbor.formal_v2 import FormalCaseRunner, evaluate_case_candidate
from websitebench.harbor.materialize import materialize_instance
from websitebench.harbor.scaffold import initialize_instance, initialize_site


def _case_manifest(*, status: str = "complete", visual: bool = False) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for index in range(20):
        cases.append(
            {
                "id": f"T1-{index + 1:03d}",
                "tier": "T1",
                "kind": "http",
                "timeout_sec": 30,
                "task_id": f"t1-{index + 1:03d}",
            }
        )
    offset = 0
    for level, count in (("L1", 35), ("L2", 50), ("L3", 80)):
        for index in range(count):
            identifier = f"T2-{level}-{index + 1:03d}"
            case: dict[str, object] = {
                "id": identifier,
                "tier": "T2",
                "level": level,
                "kind": "journey",
                "timeout_sec": 60,
                "task_id": f"T{offset + index + 21:03d}",
            }
            if visual and level == "L1" and index == 0:
                case["visual_checkpoint_ids"] = ["home"]
            cases.append(case)
        offset += count
    for index in range(15):
        cases.append(
            {
                "id": f"T3-{index + 1:03d}",
                "tier": "T3",
                "kind": "cicd",
                "timeout_sec": 120,
                "cicd_check_id": f"platform/check-{index + 1:03d}",
            }
        )
    return {
        "schema_version": "websitebench.harbor.case-manifest.v1",
        "manifest_id": "synthetic-200",
        "site_id": "synthetic",
        "status": status,
        "dsl_version": "websitebench.harbor.neutral-dsl.v1",
        "cases": cases,
    }


def _passing_results(manifest: dict[str, object], *, seed: int = 19) -> dict[str, object]:
    results = synthesize_zero_results(
        manifest,
        trial_id="synthetic-trial",
        seed=seed,
        reason="synthetic default",
    )
    for result in results["results"]:
        assert isinstance(result, dict)
        result["status"] = "passed"
        result.pop("failure_kind", None)
        result["reason"] = "terminal observations matched"
        if result["kind"] == "journey":
            result["functional"] = {
                "direct": None,
                "playwright": True,
                "browser_use": True,
            }
        else:
            result["functional"] = {
                "direct": True,
                "playwright": None,
                "browser_use": None,
            }
    return results


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _write_compilable_candidate(root: Path) -> None:
    root.mkdir()
    app = root / "app.py"
    app.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  body=json.dumps({'status':'ok'},separators=(',',':')).encode() if self.path=='/__websitebench/health' else b'ok'\n"
        "  self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)\n"
        " def log_message(self,*args): pass\n"
        "ThreadingHTTPServer((os.environ['HOST'],int(os.environ['PORT'])),H).serve_forever()\n",
        encoding="utf-8",
    )
    compile_script = root / "compile.sh"
    compile_script.write_text(
        "#!/bin/sh\nset -eu\ncp app.py executable\nchmod 755 executable\n",
        encoding="utf-8",
    )
    compile_script.chmod(0o755)


def _complete_scaffold(tmp_path: Path) -> Path:
    corpus = tmp_path / "harbor"
    (corpus / "instances").mkdir(parents=True)
    site_path = initialize_site(
        corpus / "sites" / "synthetic",
        site_id="synthetic",
        display_name="Synthetic",
    )
    instance_path = initialize_instance(
        corpus / "instances" / "synthetic",
        instance_id="synthetic",
        site_manifest="sites/synthetic/site.yaml",
        author_name="Synthetic",
        author_email="synthetic@example.test",
    )
    instance = yaml.safe_load(instance_path.read_text(encoding="utf-8"))
    hidden = instance_path.parent / "fixtures" / "hidden"

    manifest = _case_manifest()
    manifest["site_id"] = "synthetic"
    for index, case in enumerate(
        [
            item
            for item in manifest["cases"]  # type: ignore[index]
            if item["tier"] == "T3"
        ],
        start=1,
    ):
        case["kind"] = "http"
        case["task_id"] = f"t3-{index:03d}"
        case.pop("cicd_check_id")
    task_ids = [
        str(case["task_id"])
        for case in manifest["cases"]  # type: ignore[index]
        if "task_id" in case
    ]
    tasks = [
        {
            "id": identifier,
            "timeout_sec": 30,
            "actions": [
                {"op": "api", "path": "/", "capture_as": "response"}
            ],
            "observations": [
                {
                    "id": "terminal",
                    "kind": "api_status",
                    "capture_as": "response",
                    "comparator": {"type": "exact"},
                }
            ],
        }
        for identifier in task_ids
    ]
    task_suite = json.loads(
        (hidden / "task-suite.json").read_text(encoding="utf-8")
    )
    task_suite["tasks"] = tasks
    cicd_suite = json.loads(
        (hidden / "cicd-suite.json").read_text(encoding="utf-8")
    )
    cicd_suite["checks"] = []
    (hidden / "task-suite.json").write_bytes(canonical_json_bytes(task_suite))
    (hidden / "cicd-suite.json").write_bytes(canonical_json_bytes(cicd_suite))
    (hidden / "case-manifest.json").write_bytes(canonical_json_bytes(manifest))

    site = yaml.safe_load(site_path.read_text(encoding="utf-8"))
    browser = site["runtime"]["browser"]
    observations = {
        "schema_version": "websitebench.harbor.reference-observations.v1",
        "site_id": "synthetic",
        "instance_id": "synthetic",
        "render_environment": {
            "schema_version": "websitebench.harbor.render-environment.v1",
            "engine": "chromium",
            "playwright_version": browser["playwright_version"],
            "chromium_version": "Chromium synthetic",
            "font_profile": browser["font_profile"],
        },
        "reset_strategy": "fresh-local-data-directory",
        "authenticated_reference": False,
        "tasks": {
            identifier: {"observations": {"terminal": 200}}
            for identifier in task_ids
        },
        "visual_checkpoints": [],
    }
    (hidden / "reference-observations.json").write_bytes(
        canonical_json_bytes(observations)
    )
    instance["reference_observations"]["status"] = "captured"
    instance_path.write_text(
        yaml.safe_dump(instance, sort_keys=False), encoding="utf-8"
    )
    return instance_path


def test_case_manifest_draft_and_exact_cardinalities() -> None:
    draft = {
        "schema_version": "websitebench.harbor.case-manifest.v1",
        "manifest_id": "empty-draft",
        "site_id": "synthetic",
        "status": "draft",
        "dsl_version": "websitebench.harbor.neutral-dsl.v1",
        "cases": [],
    }
    summary = validate_case_manifest_payload(draft)
    assert summary.status == "draft"
    assert summary.scorable is False
    assert summary.missing == {
        "total": 200,
        "T1": 20,
        "T2": 165,
        "T3": 15,
        "L1": 35,
        "L2": 50,
        "L3": 80,
    }
    complete = _case_manifest()
    assert validate_case_manifest_payload(complete).counts["total"] == 200
    assert sealed_case_manifest(complete)["status"] == "sealed"

    duplicate = _case_manifest()
    duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]  # type: ignore[index]
    with pytest.raises(CaseProtocolError, match="duplicate ids"):
        validate_case_manifest_payload(duplicate)
    missing = _case_manifest()
    missing["cases"].pop()  # type: ignore[union-attr]
    with pytest.raises(CaseProtocolError, match="expected 200"):
        validate_case_manifest_payload(missing)


def test_score20_visual_weight_dual_executor_and_tie_break() -> None:
    manifest = _case_manifest(visual=True)
    results = _passing_results(manifest)
    indexed = {item["case_id"]: item for item in results["results"]}  # type: ignore[index]
    indexed["T2-L1-001"]["visuals"] = [
        {"checkpoint_id": "home", "area": 10, "ssim": 0.5}
    ]
    failed = indexed["T2-L2-001"]
    failed["functional"]["browser_use"] = False
    failed["status"] = "failed"
    failed["failure_kind"] = "candidate"

    evaluation, events = compute_case_evaluation(manifest, results)
    expected = 4 * (34.5 / 35) + 6 * (49 / 50) + 10
    assert evaluation["score20"] == round(expected, 8)
    assert evaluation["reward"] == round(expected / 20, 8)
    assert evaluation["tie_break"] == [round(expected, 8), 1.0, 1.0]
    assert len(events) == 200


def test_exact_result_set_and_deploy_failure_zeroes_all_200_cases() -> None:
    manifest = _case_manifest()
    zeroes = synthesize_zero_results(
        manifest, trial_id="deploy-failed", seed=7, reason="COMPILE_FAILED"
    )
    evaluation, _ = compute_case_evaluation(manifest, zeroes)
    assert len(zeroes["results"]) == 200
    assert evaluation["score20"] == 0
    assert evaluation["reward"] == 0
    zeroes["results"].pop()
    with pytest.raises(CaseProtocolError, match="exact set mismatch"):
        compute_case_evaluation(manifest, zeroes)


def test_eight_shards_candidate_failure_and_single_infrastructure_retry(
    tmp_path: Path,
) -> None:
    manifest = _case_manifest()
    attempts: dict[str, int] = {}

    def runner(case: dict[str, object], context: object) -> CaseOutcome:
        identifier = str(case["id"])
        attempts[identifier] = attempts.get(identifier, 0) + 1
        if identifier == "T1-001":
            raise CandidateCaseFailure("assertion")
        if identifier == "T1-002" and attempts[identifier] == 1:
            raise InfrastructureCaseFailure("browser crashed")
        if case["kind"] == "journey":
            functional = {
                "direct": None,
                "playwright": True,
                "browser_use": True,
            }
        else:
            functional = {
                "direct": True,
                "playwright": None,
                "browser_use": None,
            }
        return CaseOutcome(functional=functional)

    result = execute_case_manifest(
        manifest,
        runner,
        trial_id="retry",
        seed=11,
        working_root=tmp_path / "work",
    )
    assert result["status"] == "VALID_RUN"
    assert attempts["T1-001"] == 1
    assert attempts["T1-002"] == 2
    indexed = {item["case_id"]: item for item in result["results"]}
    assert indexed["T1-001"]["failure_kind"] == "candidate"
    assert indexed["T1-002"]["attempts"] == 2
    assert len({path.name for path in (tmp_path / "work").glob("shard-*")}) == 8


def test_second_infrastructure_failure_invalidates_entire_trial(tmp_path: Path) -> None:
    manifest = _case_manifest()

    def broken(case: object, context: object) -> CaseOutcome:
        raise InfrastructureCaseFailure("trusted browser unavailable")

    result = execute_case_manifest(
        manifest,
        broken,
        trial_id="invalid",
        seed=13,
        working_root=tmp_path / "work",
    )
    assert result["status"] == "INVALID_RUN"
    assert result["results"] == []
    assert "INFRASTRUCTURE_FAILURE" in result["reason"]


def test_browser_use_policy_and_environment_are_closed(tmp_path: Path) -> None:
    compiled = compile_neutral_actions(
        [{"op": "goto", "path": "/"}, {"op": "click", "selector": {"text": "Go"}}],
        executor="browser-use",
    )
    assert all(item["deterministic_cdp"] is True for item in compiled)
    for forbidden in ("run", "extract", "eval", "python", "cloud", "profile", "tunnel", "mcp", "cookie-export"):
        with pytest.raises(ExecutorPolicyError):
            compile_neutral_actions([{"op": forbidden}], executor="browser-use")

    runtime = BrowserUseRuntime(tmp_path / "browser-use")
    environment = sanitized_browser_use_environment(
        {
            "OPENAI_API_KEY": "must-not-leak",
            "AWS_SECRET_ACCESS_KEY": "must-not-leak",
            "UNRELATED": "also-not-copied",
        },
        runtime=runtime,
        candidate_port=3000,
        cdp_port=9222,
        seed=41,
    )
    assert environment["WEBSITEBENCH_BROWSER_USE_VERSION"] == "0.12.6"
    assert environment["WEBSITEBENCH_ALLOWED_CONNECT_PORTS"] == "3000,9222"
    assert "OPENAI_API_KEY" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    assert "UNRELATED" not in environment
    assert environment["HTTP_PROXY"] == environment["HTTPS_PROXY"] == ""


def test_artifact_quarantine_rejects_links_and_freezes_build(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_compilable_candidate(source)
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    (source / "escape").symlink_to(outside)
    with pytest.raises(CompilerSandboxError, match="symbolic links"):
        validate_artifact_tree(source)
    (source / "escape").unlink()

    linked = source / "linked"
    os.link(source / "app.py", linked)
    with pytest.raises(CompilerSandboxError, match="hard-linked"):
        quarantine_artifact(source, tmp_path / "quarantine")
    linked.unlink()

    fifo = source / "special"
    os.mkfifo(fifo)
    with pytest.raises(CompilerSandboxError, match="special files"):
        validate_artifact_tree(source)
    fifo.unlink()

    preexisting = source / "executable"
    preexisting.write_text("untrusted", encoding="utf-8")
    preexisting.chmod(0o755)
    artifact = compile_candidate(source, tmp_path / "private", timeout=20)
    assert artifact.executable.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")
    assert artifact.tree_sha256 == tree_digest(artifact.build_root)
    assert stat.S_IMODE(artifact.build_root.stat().st_mode) == 0o555
    assert stat.S_IMODE(artifact.executable.stat().st_mode) == 0o555


def test_compiler_blocks_public_network_and_reaps_background_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    network = tmp_path / "network"
    _write_compilable_candidate(network)
    compile_script = network / "compile.sh"
    compile_script.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 80), 1)\"\n"
        "cp app.py executable\n"
        "chmod 755 executable\n",
        encoding="utf-8",
    )
    with pytest.raises(CompilerSandboxError, match="compile.sh exited"):
        compile_candidate(network, tmp_path / "network-private", timeout=10)

    background = tmp_path / "background"
    _write_compilable_candidate(background)
    background_script = background / "compile.sh"
    background_script.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "sleep 60 &\n"
        "cp app.py executable\n"
        "chmod 755 executable\n",
        encoding="utf-8",
    )

    def terminate_immediately(process: object, timeout: float = 10.0) -> bool:
        pid = process.pid  # type: ignore[attr-defined]
        os.killpg(pid, signal.SIGKILL)
        process.wait(timeout=5)  # type: ignore[attr-defined]
        return False

    monkeypatch.setattr(
        "websitebench.harbor.compiler_v2._terminate_group", terminate_immediately
    )
    with pytest.raises(CompilerSandboxError, match="child process or listener"):
        compile_candidate(background, tmp_path / "background-private", timeout=10)


@pytest.mark.skipif(os.name != "posix", reason="compile runtime is POSIX-only")
def test_compile_executable_health_sigterm_restart_and_isolation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_compilable_candidate(source)
    artifact = compile_candidate(source, tmp_path / "private", timeout=20, seed=23)
    report = validate_runtime_lifecycle(
        artifact,
        port=_free_port(),
        seed=23,
        working_root=tmp_path / "runtime",
    )
    assert report["deployment_abi"] == "websitebench.harbor.compile-executable.v1"
    assert report["valid"] is True
    assert report["health"] is True
    assert report["sigterm"] is True
    assert report["restart"] is True
    assert report["persistence"] is True
    assert report["new_data_dir_isolation"] is True


def test_receipt_last_publication_is_reproducible_and_finalizable(tmp_path: Path) -> None:
    manifest = _case_manifest()
    results = _passing_results(manifest)
    evaluation, events = compute_case_evaluation(manifest, results)
    first = tmp_path / "first"
    second = tmp_path / "second"
    publish_case_evaluation(
        first,
        manifest=manifest,
        result_set=results,
        evaluation=evaluation,
        events=events,
    )
    publish_case_evaluation(
        second,
        manifest=manifest,
        result_set=results,
        evaluation=evaluation,
        events=events,
    )
    assert (first / "receipt.json").read_bytes() == (second / "receipt.json").read_bytes()
    assert validate_receipt_run(first)["valid"] is True
    contradictory = json.loads(
        (second / "receipt.json").read_text(encoding="utf-8")
    )
    contradictory["status"] = "INVALID_RUN"
    (second / "receipt.json").write_bytes(canonical_json_bytes(contradictory))
    with pytest.raises(CaseProtocolError, match="does not match"):
        validate_receipt_run(second)
    public = tmp_path / "public"
    assert finalize_run(first, public) == 0
    assert (public / "reward.txt").read_text(encoding="ascii") == "1.00000000\n"
    assert (public / "receipt.json").read_bytes() == (first / "receipt.json").read_bytes()


def test_complete_200_case_scaffold_materializes_active_bundle(tmp_path: Path) -> None:
    instance = _complete_scaffold(tmp_path)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    assert validate_bundle(bundle)["status"] == "valid"
    sealed = json.loads(
        (bundle / "tests/fixtures/case-manifest.json").read_text(encoding="utf-8")
    )
    contract = json.loads(
        (bundle / "tests/evaluation-contract.json").read_text(encoding="utf-8")
    )
    assert sealed["status"] == "sealed"
    assert len(sealed["cases"]) == 200
    assert contract["deployment_abi"] == "websitebench.harbor.compile-executable.v1"
    assert contract["formal_browsers"] == ["playwright", "browser-use"]
    assert contract["logical_shards"] == 8
    wrapper = (bundle / "tests/test.sh").read_text(encoding="utf-8")
    assert "run_v2.py" in wrapper
    assert "finalizer_v2" in wrapper

    zero_output = tmp_path / "zero-output"
    assert (
        evaluate_case_candidate(
            candidate_root=bundle / "environment/seed",
            case_manifest_path=bundle / "tests/fixtures/case-manifest.json",
            task_suite_path=bundle / "tests/fixtures/task-suite.json",
            visual_suite_path=bundle / "tests/fixtures/visual-suite.json",
            cicd_suite_path=bundle / "tests/fixtures/cicd-suite.json",
            reference_observations_path=bundle
            / "tests/fixtures/reference-observations.json",
            fixture_root=bundle / "tests/fixtures",
            output=zero_output,
            browser_settings=contract["browser"],
            browser_use_settings=contract["browser_use"],
            build_timeout_sec=10,
            seed=0,
        )
        == 0
    )
    assert (zero_output / "reward.txt").read_text(encoding="ascii") == "0.00000000\n"
    assert validate_receipt_run(zero_output)["valid"] is True
    zero_results = json.loads(
        (zero_output / "case-results.json").read_text(encoding="utf-8")
    )
    assert len(zero_results["results"]) == 200
    assert {item["status"] for item in zero_results["results"]} == {"failed"}
    assert (zero_output / "failures/trace.jsonl").is_file()

    cicd_path = bundle / "tests/fixtures/cicd-suite.json"
    hostile_cicd = json.loads(cicd_path.read_text(encoding="utf-8"))
    hostile_cicd["checks"] = [{"id": "platform/escape", "kind": "platform"}]
    cicd_path.write_bytes(canonical_json_bytes(hostile_cicd))
    invalid_output = tmp_path / "invalid-platform-output"
    assert (
        evaluate_case_candidate(
            candidate_root=bundle / "environment/seed",
            case_manifest_path=bundle / "tests/fixtures/case-manifest.json",
            task_suite_path=bundle / "tests/fixtures/task-suite.json",
            visual_suite_path=bundle / "tests/fixtures/visual-suite.json",
            cicd_suite_path=cicd_path,
            reference_observations_path=bundle
            / "tests/fixtures/reference-observations.json",
            fixture_root=bundle / "tests/fixtures",
            output=invalid_output,
            browser_settings=contract["browser"],
            browser_use_settings=contract["browser_use"],
            build_timeout_sec=10,
            seed=0,
        )
        == 2
    )
    assert not (invalid_output / "reward.txt").exists()
    invalid_receipt = validate_receipt_run(invalid_output)
    assert invalid_receipt["valid"] is False
    assert "cannot occupy an active site case" in invalid_receipt["reason"]


def test_canonical_manifest_fixture_is_byte_stable() -> None:
    assert canonical_json_bytes(_case_manifest()) == canonical_json_bytes(_case_manifest())


def test_cli_draft_validation_and_active_score_interface(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = tmp_path / "draft-harbor"
    (corpus / "instances").mkdir(parents=True)
    initialize_site(
        corpus / "sites" / "draft",
        site_id="draft",
        display_name="Draft",
    )
    instance = initialize_instance(
        corpus / "instances" / "draft",
        instance_id="draft",
        site_manifest="sites/draft/site.yaml",
        author_name="Draft",
        author_email="draft@example.test",
    )
    assert harbor_main(["validate", "--instance", str(instance)]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["status"] == "draft"
    assert validation["scorable"] is False
    assert validation["missing"]["total"] == 200
    assert (
        harbor_main(
            [
                "materialize",
                "--instance",
                str(instance),
                "--out",
                str(tmp_path / "draft-bundle"),
            ]
        )
        == 2
    )
    assert "complete 200-case" in capsys.readouterr().err

    manifest = _case_manifest()
    results = _passing_results(manifest)
    manifest_path = tmp_path / "case-manifest.json"
    result_path = tmp_path / "case-results.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    result_path.write_bytes(canonical_json_bytes(results))
    output = tmp_path / "score"
    assert (
        harbor_main(
            [
                "score-v2",
                "--case-manifest",
                str(manifest_path),
                "--case-results",
                str(result_path),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "reward.txt").read_text(encoding="ascii") == "1.00000000\n"

    assert (
        harbor_main(
            [
                "score-v2",
                "--task-suite",
                str(tmp_path / "legacy-task.json"),
                "--out",
                str(tmp_path / "legacy-score"),
            ]
        )
        == 2
    )
    assert "requires --legacy-deploy-v2" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="formal browser runtime is POSIX-only")
def test_real_pinned_browser_use_adapter_executes_terminal_observation(
    tmp_path: Path,
) -> None:
    venv = Path(
        os.environ.get(
            "WEBSITEBENCH_TEST_BROWSER_USE_VENV",
            "/opt/websitebench/browser-use-0.12.6",
        )
    )
    if not (venv / "bin/python").is_file():
        pytest.skip("pinned Browser Use venv is unavailable")
    source = tmp_path / "source"
    _write_compilable_candidate(source)
    artifact = compile_candidate(source, tmp_path / "private", timeout=20, seed=31)
    task = {
        "id": "T001",
        "timeout_sec": 30,
        "actions": [{"op": "goto", "path": "/"}],
        "observations": [
            {"id": "terminal", "kind": "url", "comparator": {"type": "exact"}}
        ],
    }
    runner = FormalCaseRunner(
        artifact=artifact,
        task_suite={"tasks": [task]},
        visual_suite={"checkpoints": []},
        cicd_suite={"checks": []},
        reference={"tasks": {"T001": {"observations": {"terminal": "/"}}}},
        fixture_root=tmp_path,
        browser_settings={"locale": "en-US", "timezone": "UTC"},
        browser_use_settings={"venv": str(venv)},
        timezone="UTC",
    )
    context = CaseExecutionContext(
        case_id="T2-L1-001",
        seed=31,
        shard=0,
        attempt=1,
        root=tmp_path / "case",
    )
    root = tmp_path / "browser-use-case"
    root.mkdir()
    outcome = runner.browser_use(
        {
            "id": "T2-L1-001",
            "tier": "T2",
            "level": "L1",
            "kind": "journey",
            "task_id": "T001",
            "timeout_sec": 30,
        },
        context,
        root,
    )
    assert outcome.functional["browser_use"] is True
