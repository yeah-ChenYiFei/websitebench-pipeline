from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from websitebench.harbor.materialize import materialize_instance
from websitebench.harbor.scaffold import initialize_instance, initialize_site


def _bundle(tmp_path: Path) -> Path:
    corpus = tmp_path / "harbor"
    (corpus / "instances").mkdir(parents=True)
    initialize_site(
        corpus / "sites" / "demo",
        site_id="demo",
        display_name="Demo",
        legacy_v1=True,
    )
    instance = initialize_instance(
        corpus / "instances" / "demo-rebuild",
        instance_id="demo-rebuild",
        site_manifest="sites/demo/site.yaml",
        author_name="Benchmark Team",
        author_email="bench@example.test",
        legacy_v1=True,
    )
    return materialize_instance(instance, tmp_path / "bundle", allow_legacy_v1=True)


def _report(required: dict[str, object]) -> dict[str, object]:
    scores = {
        "api::core/write-path": 0.5,
        "visual::primary/reference-checkpoint": 0.8,
        "robustness::refresh-and-retry": 0.0,
    }
    tests = []
    for node in required["nodes"]:
        score = scores.get(node, 1.0)
        tests.append(
            {
                "name": node,
                "status": "passed" if score == 1 else "failed",
                "extra": {"clawbench_score": score},
            }
        )
    return {
        "results": {
            "tool": {"name": "unit-test"},
            "summary": {"tests": len(tests)},
            "tests": tests,
            "extra": {"hard_failures": []},
        }
    }


def test_fractional_dimension_scoring_and_exact_set_validation(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    required_path = bundle / "tests/required-nodes.json"
    required = json.loads(required_path.read_text(encoding="utf-8"))
    report_path = tmp_path / "ctrf.json"
    report_path.write_text(
        json.dumps(_report(required)),
        encoding="utf-8",
    )
    output = tmp_path / "score"
    output.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(bundle / "tests/compute_reward.py"),
            str(report_path),
            str(required_path),
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    score = json.loads((output / "scorecard.json").read_text(encoding="utf-8"))
    reported_scores = {
        test["name"]: test["extra"]["clawbench_score"]
        for test in _report(required)["results"]["tests"]
    }
    expected_score = round(
        sum(
            required["dimension_max_points"][dimension]
            * sum(reported_scores[node] for node in nodes)
            / len(nodes)
            for dimension, nodes in required["groups"].items()
            if nodes
        ),
        6,
    )
    expected_reward = round(expected_score / 100, 8)
    assert not (output / "reward.json").exists()
    assert float((output / "reward.txt").read_text(encoding="utf-8")) == expected_reward
    assert score["score"] == expected_score
    assert score["reward"] == expected_reward
    assert score["dimensions"]["visual"]["score"] == 12

    invalid = _report(required)
    invalid["results"]["tests"].pop()
    report_path.write_text(json.dumps(invalid), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(bundle / "tests/compute_reward.py"),
            str(report_path),
            str(required_path),
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert not (output / "reward.txt").exists()
    verdict = json.loads((output / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["valid"] is False
    assert "EXACT_SET_MISMATCH" in verdict["reason"]


def test_platform_gate_recomputes_mandatory_nodes_from_semantic_facts(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    required_path = bundle / "tests/required-nodes.json"
    required = json.loads(required_path.read_text(encoding="utf-8"))
    site_report = tmp_path / "site-ctrf.json"
    site_report.write_text(json.dumps(_report(required)), encoding="utf-8")

    runtime = {
        "site": {"id": "demo"},
        "deployment": {
            "profiles": {
                "offline-harbor": {
                    "mail_adapter": "local-outbox",
                    "payment_adapter": "local-sandbox",
                }
            }
        },
    }
    runtime_bytes = (json.dumps(runtime, sort_keys=True) + "\n").encode()
    runtime_sha256 = hashlib.sha256(runtime_bytes).hexdigest()
    candidate_root = tmp_path / "candidate"
    reference_root = tmp_path / "reference"
    for root in (candidate_root, reference_root):
        (root / "backend").mkdir(parents=True)
        (root / "backend/runtime.json").write_bytes(runtime_bytes)

    auth_checkout = {
        "registration_status": 303,
        "outbox_status": 200,
        "outbox_local_only": True,
        "outbox_without_token_status": 403,
        "outbox_wrong_token_status": 403,
        "public_outbox_status": 403,
        "verification_status": 303,
        "replay_status": 400,
        "duplicate_status": 409,
        "logout_status": 303,
        "wrong_password_status": 200,
        "login_status": 303,
        "expired_verification_status": 410,
        "expired_accounts": 0,
        "replay_accounts": 1,
        "post_logout_protected_status": 401,
        "wrong_password_protected_status": 401,
        "checkout_status": 200,
        "decline_status": 303,
        "decline_orders": 0,
        "retry_status": 303,
        "replay_order_status": 303,
        "replay_same_order": True,
        "order_detail_status": 200,
        "order_detail_has_item": True,
        "foreign_order_status": 404,
        "auth_ui_controls": 5,
        "checkout_ui_options": 3,
        "checkout_simulation_disclosed": True,
        "ui_remote_requests": [],
        "accounts": 2,
        "orders": 1,
        "payment_attempts": 2,
        "completed_checkouts": 1,
        "plaintext_registration_codes": 0,
        "mail_delivery": "LOCAL_ONLY",
        "payment_adapter": "local-sandbox",
        "site_id": "demo",
        "database_identity": "a" * 64,
        "backend_runtime_sha256": runtime_sha256,
        "restart_login_status": 303,
        "restart_order_visible": True,
        "restart_orders": 1,
        "error": "",
    }
    candidate_facts = tmp_path / "candidate-facts.json"
    candidate_facts.write_text(
        json.dumps({"auth_checkout": auth_checkout}),
        encoding="utf-8",
    )
    reference_auth = dict(auth_checkout)
    reference_auth["database_identity"] = "b" * 64
    reference_facts = tmp_path / "reference-facts.json"
    reference_facts.write_text(
        json.dumps({"auth_checkout": reference_auth}),
        encoding="utf-8",
    )
    output = tmp_path / "platform-ctrf.json"
    evidence = tmp_path / "platform-evidence.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(bundle / "tests/platform_auth_checkout_gate.py"),
            "--policy",
            str(bundle / "tests/platform-auth-checkout-policy.json"),
            "--required",
            str(required_path),
            "--site-report",
            str(site_report),
            "--candidate-facts",
            str(candidate_facts),
            "--reference-facts",
            str(reference_facts),
            "--candidate-root",
            str(candidate_root),
            "--reference-root",
            str(reference_root),
            "--output",
            str(output),
            "--evidence",
            str(evidence),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    enforced = json.loads(output.read_text(encoding="utf-8"))
    by_name = {test["name"]: test for test in enforced["results"]["tests"]}
    negative = by_name["api::auth/error-expiry-replay-guards"]
    assert negative["status"] == "failed"
    assert negative["extra"]["websitebench_platform_enforced"] is True
    assert "wrong_password" not in negative.get("message", "")
    assert (
        json.loads(evidence.read_text(encoding="utf-8"))["nodes"][
            "api::auth/error-expiry-replay-guards"
        ]["passed"]
        is False
    )


def test_hard_failure_zeroes_an_otherwise_passing_run(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    required_path = bundle / "tests/required-nodes.json"
    required = json.loads(required_path.read_text(encoding="utf-8"))
    report = _report(required)
    for test in report["results"]["tests"]:
        test["status"] = "passed"
        test["extra"]["clawbench_score"] = 1
    report["results"]["extra"]["hard_failures"] = ["REFERENCE_RESET_DIVERGED"]
    report_path = tmp_path / "ctrf.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    output = tmp_path / "score"
    output.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(bundle / "tests/compute_reward.py"),
            str(report_path),
            str(required_path),
            str(output),
        ],
        check=False,
    )

    assert completed.returncode == 0
    score = json.loads((output / "scorecard.json").read_text(encoding="utf-8"))
    assert score["score"] == 0
    assert score["reward"] == 0
