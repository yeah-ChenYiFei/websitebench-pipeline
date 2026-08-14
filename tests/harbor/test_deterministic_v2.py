from __future__ import annotations

import hashlib
import json
import os
import fcntl
import shutil
import socket
import smtplib
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from PIL import Image

from websitebench.harbor.bundle_v2 import BundleValidationError, validate_bundle
from websitebench.harbor.calibration_v2 import calibrate_bundle, calibration_assertions
from websitebench.harbor.dsl_v2 import (
    DslExecutionError,
    _mailbox_capture,
    _target_url,
    observe,
    run_actions,
)
from websitebench.harbor.evaluate import (
    _mailbox_environment,
    _runtime_network_audit,
    evaluate_candidate,
    evaluate_task_suite,
)
from websitebench.harbor.capture import ReferenceObservationError, capture_reference
from websitebench.harbor.capture import _run_actions as run_reference_actions
from websitebench.harbor.judge_v2 import (
    CICD_RESULTS_SCHEMA,
    TASK_RESULTS_SCHEMA,
    VISUAL_RESULTS_SCHEMA,
    PLATFORM_CICD_CHECKS,
    CandidateProcess,
    InvalidRun,
    accessibility_role_name,
    compare_values,
    compute_visual_checkpoint,
    font_manifest_text,
    score_results,
    verifier_network_policy_enforced,
)
from websitebench.harbor.manifest import HarborManifestError, load_instance, load_site
from websitebench.harbor.materialize import materialize_instance
from websitebench.harbor.mailbox import (
    LocalMailboxSidecar,
    redact_evidence,
    redact_log_file,
)
from websitebench.harbor.scaffold import initialize_instance, initialize_site
from websitebench.harbor.sandbox_v2 import sandbox_preflight


def _runtime_skip(reason: str) -> None:
    if os.environ.get("WEBSITEBENCH_REQUIRE_REAL_V2_E2E") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def _corpus(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "harbor"
    (root / "instances").mkdir(parents=True)
    site = initialize_site(root / "sites" / "demo", site_id="demo", display_name="Demo")
    instance = initialize_instance(
        root / "instances" / "demo",
        instance_id="demo",
        site_manifest="sites/demo/site.yaml",
        author_name="Team",
        author_email="team@example.test",
    )
    return root, site, instance


def _capture_fake_observations(instance: Path) -> None:
    value = yaml.safe_load(instance.read_text(encoding="utf-8"))
    hidden = instance.parent / "fixtures" / "hidden"
    (hidden / "visual").mkdir(parents=True)
    raster = hidden / "visual" / "home.png"
    Image.new("RGB", (1280, 720), "white").save(raster)
    observations = {"status": 200}
    reference_observations = {
        "schema_version": "websitebench.harbor.reference-observations.v1",
        "site_id": "demo",
        "instance_id": "demo",
        "render_environment": {
            "schema_version": "websitebench.harbor.render-environment.v1",
            "engine": "chromium",
            "playwright_version": "1.61.0",
            "chromium_version": "Chromium 137.0.0.0",
            "font_profile": "websitebench-linux-fonts-v1",
        },
        "reset_strategy": "fresh-local-data-directory",
        "authenticated_reference": False,
        "tasks": {
            "healthz": {
                "observations": observations,
            }
        },
        "visual_checkpoints": [
            {
                "checkpoint_id": "home",
                "reference_image": "visual/home.png",
                "width": 1280,
                "height": 720,
            }
        ],
    }
    (hidden / "reference-observations.json").write_text(
        json.dumps(reference_observations, sort_keys=True) + "\n", encoding="utf-8"
    )
    value["reference_observations"]["status"] = "captured"
    instance.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_v2_is_default_and_draft_cannot_materialize(tmp_path: Path) -> None:
    _, site_path, instance_path = _corpus(tmp_path)
    site = load_site(site_path)
    instance = load_instance(instance_path)

    assert site.data["schema_version"] == "websitebench.harbor.site.v2"
    assert instance.data["schema_version"] == "websitebench.harbor.instance.v2"
    assert instance.data["budgets"]["agent_timeout_sec"] == 8 * 60 * 60
    assert instance.data["budgets"]["verifier_timeout_sec"] == 60 * 60
    assert site.data["runtime"]["formal_workers"] == 4
    assert site.data["runtime"]["reference_reset_url_env"] == (
        "WEBSITEBENCH_REFERENCE_RESET_URL"
    )
    assert (instance.root / "public/deploy.sh").stat().st_mode & 0o100
    assert not (instance.root / "public/run.sh").exists()
    with pytest.raises(HarborManifestError, match="capture-reference"):
        materialize_instance(instance_path, tmp_path / "draft-bundle")


def test_v2_bundle_is_structured_hidden_and_model_free(tmp_path: Path) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    output = materialize_instance(instance, tmp_path / "bundle")
    report = validate_bundle(output)

    assert report["status"] == "valid"
    assert report["model_runtime"] is False
    assert (output / "environment/seed/deploy.sh").is_file()
    assert not (output / "environment/seed/fixtures/hidden/task-suite.json").exists()
    assert (output / "tests/fixtures/task-suite.json").is_file()
    assert (output / "tests/fixtures/visual/home.png").is_file()
    assert (output / "tests/websitebench/harbor/sandbox_v2.py").is_file()
    compose = yaml.safe_load(
        (output / "environment/docker-compose.yaml").read_text(encoding="utf-8")
    )
    assert compose["services"]["main"]["depends_on"]["mailbox"] == {
        "condition": "service_healthy"
    }
    capability = compose["services"]["main"]["environment"][
        "WEBSITEBENCH_MAILBOX_CAPABILITY"
    ]
    assert len(capability) == 64
    assert (
        compose["services"]["mailbox"]["environment"][
            "WEBSITEBENCH_MAILBOX_INITIAL_CAPABILITY"
        ]
        == capability
    )
    assert (
        compose["services"]["reference"]["environment"][
            "WEBSITEBENCH_MAILBOX_CAPABILITY"
        ]
        == capability
    )
    assert (output / "environment/mailbox/mailbox.py").is_file()
    assert (
        json.loads((output / "tests/network-policy.json").read_text())[
            "public_internet"
        ]
        is False
    )
    wrapper = (output / "tests/test.sh").read_text(encoding="utf-8")
    assert "WEBSITEBENCH_NETWORK_POLICY_ENFORCED" in wrapper
    assert "bool(external_allowlist)" not in wrapper


def test_manifest_rejects_model_runtime_dependencies(tmp_path: Path) -> None:
    _, site, _ = _corpus(tmp_path)
    (site.parent / "verifier" / "requirements.txt").write_text(
        "openai==1.2.3\n", encoding="utf-8"
    )
    with pytest.raises(HarborManifestError, match="model runtime"):
        load_site(site)


def test_manifest_rejects_model_judge_config_in_yaml(tmp_path: Path) -> None:
    _, site, _ = _corpus(tmp_path)
    (site.parent / "verifier" / "judge.yaml").write_text(
        "prompt: decide whether this clone is good\n", encoding="utf-8"
    )
    with pytest.raises(HarborManifestError, match="configuration keys"):
        load_site(site)


@pytest.mark.parametrize(
    ("actual", "expected", "comparator", "passed"),
    [
        ("A", "A", {"type": "exact"}, True),
        (" A\n B ", "A B", {"type": "normalized_exact"}, True),
        ("order-42", None, {"type": "regex", "pattern": r"order-\d+"}, True),
        (["a", "b"], ["a", "b"], {"type": "ordered_list"}, True),
        (["a", "b"], ["b", "a"], {"type": "set"}, True),
        (10.1, 10, {"type": "number", "absolute_tolerance": 0.11}, True),
        ("a" * 64, "a" * 64, {"type": "sha256"}, True),
        (["a", "b"], ["b", "a"], {"type": "ordered_list"}, False),
    ],
)
def test_declared_comparators(
    actual: object,
    expected: object,
    comparator: dict[str, object],
    passed: bool,
) -> None:
    assert compare_values(actual, expected, comparator)["passed"] is passed


def test_regex_requires_an_explicit_pattern_in_schema_and_runtime() -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "websitebench/schemas/harbor-task-suite.schema.json"
        ).read_text(encoding="utf-8")
    )
    comparator_schema = schema["$defs"]["comparator"]
    assert list(Draft202012Validator(comparator_schema).iter_errors({"type": "regex"}))
    with pytest.raises(ValueError, match="string pattern"):
        compare_values("value", "value", {"type": "regex"})


def test_accessibility_observation_uses_browser_computed_role_and_name() -> None:
    class Locator:
        def aria_snapshot(self) -> str:
            return '- button "Computed name"\n'

    assert accessibility_role_name(Locator()) == ("button", "Computed name")


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_two_of_three_tasks_is_the_only_reward_source(tmp_path: Path) -> None:
    task_suite = {
        "schema_version": "websitebench.harbor.task-suite.v1",
        "suite_id": "tasks",
        "site_id": "demo",
        "dsl_version": "websitebench.harbor.playwright-dsl.v1",
        "tasks": [
            {
                "id": item,
                "timeout_sec": 1,
                "actions": [],
                "observations": [
                    {
                        "id": "x",
                        "kind": "count",
                        "selector": {"css": "body"},
                        "comparator": {"type": "exact"},
                    }
                ],
            }
            for item in ("one", "two", "three")
        ],
    }
    visual_suite = {
        "schema_version": "websitebench.harbor.visual-suite.v1",
        "suite_id": "visual",
        "site_id": "demo",
        "checkpoints": [{"id": "home", "regions": [{"id": "page"}]}],
    }
    cicd_suite = {
        "schema_version": "websitebench.harbor.cicd-suite.v1",
        "suite_id": "cicd",
        "site_id": "demo",
        "checks": [
            {"id": identifier, "kind": "platform", "timeout_sec": 1}
            for identifier in PLATFORM_CICD_CHECKS
        ],
    }
    task_results = {
        "schema_version": TASK_RESULTS_SCHEMA,
        "tasks": [
            {
                "task_id": "one",
                "status": "passed",
                "reason": "ALL_OBSERVATIONS_MATCH",
                "attempts": 1,
                "observations": [{"id": "x", "comparator": "exact", "passed": True}],
            },
            {
                "task_id": "two",
                "status": "passed",
                "reason": "ALL_OBSERVATIONS_MATCH",
                "attempts": 1,
                "observations": [{"id": "x", "comparator": "exact", "passed": True}],
            },
            {
                "task_id": "three",
                "status": "failed",
                "reason": "TERMINAL_STATE_MISMATCH",
                "attempts": 1,
                "observations": [{"id": "x", "comparator": "exact", "passed": False}],
            },
        ],
    }
    visual_results = {
        "schema_version": VISUAL_RESULTS_SCHEMA,
        "checkpoints": [
            {
                "checkpoint_id": "home",
                "status": "passed",
                "reason": "SSIM_COMPUTED",
                "ssim": 0.01,
                "regions": [{"region_id": "page", "area": 1, "ssim": 0.01}],
            }
        ],
    }
    cicd_results = {
        "schema_version": CICD_RESULTS_SCHEMA,
        "checks": [
            {
                "check_id": identifier,
                "status": "skipped" if index == 0 else "flaky",
                "reason": "TEST_STATUS",
                "source": "trusted_platform_assertion",
            }
            for index, identifier in enumerate(PLATFORM_CICD_CHECKS)
        ],
    }
    output = tmp_path / "score"
    assert (
        score_results(
            task_suite=_write(tmp_path / "task-suite.json", task_suite),
            task_results=_write(tmp_path / "task-results.json", task_results),
            visual_suite=_write(tmp_path / "visual-suite.json", visual_suite),
            visual_results=_write(tmp_path / "visual-results.json", visual_results),
            cicd_suite=_write(tmp_path / "cicd-suite.json", cicd_suite),
            cicd_results=_write(tmp_path / "cicd-results.json", cicd_results),
            output=output,
        )
        == 0
    )
    scorecard = json.loads((output / "scorecard.json").read_text())
    assert scorecard["task_score"] == pytest.approx(66.66666667)
    assert scorecard["visual_score"] == 1
    assert scorecard["cicd_score"] == 0
    assert (output / "reward.txt").read_text() == "0.66666667\n"

    schema = json.loads(
        Path("websitebench/schemas/harbor-score-v2.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(scorecard)

    task_results["tasks"][1]["attempts"] = 2
    assert (
        score_results(
            task_suite=tmp_path / "task-suite.json",
            task_results=_write(tmp_path / "retried-task-results.json", task_results),
            visual_suite=tmp_path / "visual-suite.json",
            visual_results=tmp_path / "visual-results.json",
            cicd_suite=tmp_path / "cicd-suite.json",
            cicd_results=tmp_path / "cicd-results.json",
            output=output,
        )
        == 0
    )
    assert (output / "reward.txt").read_text() == "0.33333333\n"
    junit = ET.parse(output / "results.junit.xml").getroot()
    task_junit = junit.find("./testsuite[@name='tasks']")
    assert task_junit is not None
    assert task_junit.attrib["failures"] == "2"
    assert task_junit.find("./testcase[@name='two']/failure").attrib["type"] == (
        "failed_after_retry"
    )


def test_rgb_ssim_identity_and_region_area_weighting(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    identical = tmp_path / "identical.png"
    changed = tmp_path / "changed.png"
    Image.new("RGB", (20, 10), "white").save(reference)
    Image.new("RGB", (20, 10), "white").save(identical)
    image = Image.new("RGB", (20, 10), "white")
    for x in range(5):
        for y in range(10):
            image.putpixel((x, y), (0, 0, 0))
    image.save(changed)
    checkpoint = {
        "id": "page",
        "viewport": {"width": 20, "height": 10},
        "regions": [
            {
                "id": "small",
                "rect": {"x": 0, "y": 0, "width": 5, "height": 10},
                "masks": [],
            },
            {
                "id": "large",
                "rect": {"x": 5, "y": 0, "width": 15, "height": 10},
                "masks": [],
            },
        ],
    }
    same = compute_visual_checkpoint(reference, identical, checkpoint)
    result = compute_visual_checkpoint(reference, changed, checkpoint)
    assert same["ssim"] == 1
    expected = sum(item["ssim"] * item["area"] for item in result["regions"]) / 200
    assert result["ssim"] == pytest.approx(expected, abs=1e-9)
    assert result["regions"][0]["area"] == 50
    assert result["regions"][1]["area"] == 150


def test_invalid_exact_result_set_removes_reward(tmp_path: Path) -> None:
    task_suite = {
        "schema_version": "websitebench.harbor.task-suite.v1",
        "tasks": [
            {"id": "one"},
            {"id": "two"},
        ],
    }
    visual_suite = {
        "schema_version": "websitebench.harbor.visual-suite.v1",
        "checkpoints": [{"id": "home"}],
    }
    cicd_suite = {
        "schema_version": "websitebench.harbor.cicd-suite.v1",
        "checks": [
            {"id": identifier, "kind": "platform"}
            for identifier in PLATFORM_CICD_CHECKS
        ],
    }
    output = tmp_path / "output"
    output.mkdir()
    (output / "reward.txt").write_text("1.00000000\n", encoding="utf-8")
    (output / "scorecard.json").write_text("{}\n", encoding="utf-8")
    assert (
        score_results(
            task_suite=_write(tmp_path / "task-suite.json", task_suite),
            task_results=_write(
                tmp_path / "task-results.json",
                {
                    "schema_version": TASK_RESULTS_SCHEMA,
                    "tasks": [{"task_id": "one", "status": "failed", "attempts": 1}],
                },
            ),
            visual_suite=_write(tmp_path / "visual-suite.json", visual_suite),
            visual_results=_write(
                tmp_path / "visual-results.json",
                {
                    "schema_version": VISUAL_RESULTS_SCHEMA,
                    "checkpoints": [
                        {
                            "checkpoint_id": "home",
                            "status": "failed",
                            "ssim": 0,
                        }
                    ],
                },
            ),
            cicd_suite=_write(tmp_path / "cicd-suite.json", cicd_suite),
            cicd_results=_write(
                tmp_path / "cicd-results.json",
                {
                    "schema_version": CICD_RESULTS_SCHEMA,
                    "checks": [
                        {"check_id": identifier, "status": "failed"}
                        for identifier in PLATFORM_CICD_CHECKS
                    ],
                },
            ),
            output=output,
        )
        == 2
    )
    assert not (output / "reward.txt").exists()
    assert not (output / "scorecard.json").exists()
    assert json.loads((output / "verdict.json").read_text())["status"] == "INVALID_RUN"


def test_local_mailbox_sidecar_isolates_namespace_and_redacts_evidence() -> None:
    with LocalMailboxSidecar() as sidecar:
        capability = "a" * 64
        sidecar.register_namespace("task-a", capability)
        message = EmailMessage()
        message["From"] = "noreply@example.test"
        message["To"] = "user@example.test"
        message["Subject"] = "Your code"
        message["X-WebsiteBench-Namespace"] = "task-a"
        message["X-WebsiteBench-Capability"] = capability
        message.set_content("Use 123456 to continue")
        with smtplib.SMTP("127.0.0.1", sidecar.smtp_port) as smtp:
            smtp.send_message(message)
        request = urllib.request.Request(
            sidecar.url
            + "/api/namespaces/task-a/messages/latest?recipient=user%40example.test",
            headers={"Authorization": f"Bearer {capability}"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read())
        assert payload["otp"] == "123456"
        with pytest.raises(Exception):
            urllib.request.urlopen(
                urllib.request.Request(
                    sidecar.url + "/api/namespaces/task-a/messages/latest",
                    headers={"Authorization": "Bearer " + "b" * 64},
                ),
                timeout=2,
            )

    assert redact_evidence(
        {"authorization": "Bearer secret", "nested": {"otp": "123456"}, "status": 200}
    ) == {
        "authorization": "[REDACTED]",
        "nested": {"otp": "[REDACTED]"},
        "status": 200,
    }


def test_local_mailbox_enforces_stream_and_namespace_quotas() -> None:
    with LocalMailboxSidecar() as sidecar:
        capability = "q" * 64
        sidecar.register_namespace("quota", capability)
        with socket.create_connection(("127.0.0.1", sidecar.smtp_port)) as client:
            stream = client.makefile("rwb", buffering=0)
            assert stream.readline().startswith(b"220 ")
            stream.write(b"EHLO test\r\n")
            assert stream.readline().startswith(b"250-")
            assert b"SIZE 1048576" in stream.readline()
            stream.write(b"MAIL FROM:<sender@example.test>\r\n")
            assert stream.readline().startswith(b"250 ")
            stream.write(b"RCPT TO:<user@example.test>\r\n")
            assert stream.readline().startswith(b"250 ")
            stream.write(b"DATA\r\n")
            assert stream.readline().startswith(b"354 ")
            for _ in range(17):
                stream.write(b"x" * 65535 + b"\r\n")
            stream.write(b".\r\n")
            assert stream.readline().startswith(b"552 ")
        assert sidecar.store.messages("quota") == []

        raw = (
            b"From: sender@example.test\r\n"
            b"To: user@example.test\r\n"
            b"X-WebsiteBench-Namespace: quota\r\n"
            + f"X-WebsiteBench-Capability: {capability}\r\n".encode()
            + b"\r\nCode 123456\r\n"
        )
        for _ in range(32):
            assert sidecar.store.deliver(
                raw, "sender@example.test", ["user@example.test"]
            )
        assert not sidecar.store.deliver(
            raw, "sender@example.test", ["user@example.test"]
        )
        assert len(sidecar.store.messages("quota")) == 32


def test_visual_masks_cannot_bleed_into_neighbouring_ssim_windows(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (21, 9), "white").save(reference)
    changed = Image.new("RGB", (21, 9), "white")
    for x in range(7, 14):
        for y in range(9):
            changed.putpixel((x, y), (0, 0, 0))
    changed.save(candidate)
    checkpoint = {
        "id": "masked",
        "viewport": {"width": 21, "height": 9},
        "regions": [
            {
                "id": "page",
                "rect": {"x": 0, "y": 0, "width": 21, "height": 9},
                "masks": [{"x": 7, "y": 0, "width": 7, "height": 9}],
            }
        ],
    }
    result = compute_visual_checkpoint(reference, candidate, checkpoint)
    assert result["ssim"] == 1
    assert result["regions"][0]["area"] == 14 * 9


def test_external_mailbox_is_allowlisted_and_hidden_from_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEBSITEBENCH_MAILBOX_URL", "https://mail.example.test")
    monkeypatch.setenv("WEBSITEBENCH_MAILBOX_CREDENTIAL", "runtime-secret")
    monkeypatch.setenv("FUTURE_MODEL_PROVIDER_API_KEY", "future-secret")
    monkeypatch.setenv("UNRELATED_CI_SECRET", "ci-secret")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    deploy = candidate / "deploy.sh"
    deploy.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        "printf '%s|%s|%s' \"${WEBSITEBENCH_MAILBOX_CREDENTIAL-unset}\" "
        '"${FUTURE_MODEL_PROVIDER_API_KEY-unset}" '
        '"${UNRELATED_CI_SECRET-unset}" '
        '> "$WEBSITEBENCH_DATA_DIR/credential-seen"\n'
        "trap 'exit 0' TERM\n"
        "while :; do sleep 1; done\n",
        encoding="utf-8",
    )
    deploy.chmod(0o755)
    data = tmp_path / "data"
    with _mailbox_environment(
        {
            "mode": "external-proxy",
            "external_allowlist": ["mail.example.test"],
        }
    ) as mailbox_runtime:
        evidence, sidecar = mailbox_runtime
        assert sidecar is None
        process = CandidateProcess(candidate, 34567, data, "external-test")
        try:
            process.start()
            deadline = time.monotonic() + 5
            while not (data / "credential-seen").is_file():
                assert time.monotonic() < deadline
                time.sleep(0.02)
        finally:
            process.stop()
    assert (data / "credential-seen").read_text() == "unset|unset|unset"
    assert evidence["credential_injected"] is True


def test_external_mailbox_https_gateway_fetches_otp_and_redacts_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    openssl = shutil.which("openssl")
    if openssl is None:
        _runtime_skip("openssl is required for the external HTTPS gateway fixture")
    certificate = tmp_path / "gateway-cert.pem"
    key = tmp_path / "gateway-key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    authorizations: list[str | None] = []

    class Gateway(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            authorizations.append(self.headers.get("Authorization"))
            payload = json.dumps({"otp": "654321"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    gateway.socket = context.wrap_socket(gateway.socket, server_side=True)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "WEBSITEBENCH_MAILBOX_URL",
        f"https://localhost:{gateway.server_port}",
    )
    monkeypatch.setenv("WEBSITEBENCH_MAILBOX_CREDENTIAL", "external-runtime-secret")
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    captures: dict[str, object] = {}
    try:
        with _runtime_network_audit({"localhost"}) as audit:
            with _mailbox_environment(
                {"mode": "external-proxy", "external_allowlist": ["localhost"]}
            ) as mailbox_runtime:
                evidence, sidecar = mailbox_runtime
                assert sidecar is None
                _mailbox_capture(
                    {
                        "op": "mailbox_code",
                        "value": "user@example.test",
                        "capture_as": "otp",
                    },
                    captures,
                    namespace="external-worker",
                    timeout_ms=5000,
                )
        assert captures == {"otp": "654321"}
        assert authorizations == ["Bearer external-runtime-secret"]
        serialized = json.dumps(redact_evidence({"runtime": evidence, "otp": captures}))
        assert "external-runtime-secret" not in serialized
        assert "654321" not in serialized
        assert audit.evidence()["violations"] == []
    finally:
        gateway.shutdown()
        gateway.server_close()
        thread.join(timeout=5)


def test_runtime_network_audit_blocks_model_and_unallowlisted_requests() -> None:
    with _runtime_network_audit({"mail.example.test"}) as audit:
        sys.audit(
            "urllib.Request", "https://mail.example.test/messages", None, {}, "GET"
        )
        with pytest.raises(InvalidRun, match="forbidden network"):
            sys.audit(
                "urllib.Request",
                "https://" + "api." + "openai.com/v1/chat",
                None,
                {},
                "POST",
            )
    evidence = audit.evidence()
    assert evidence["model_request_count"] == 1
    assert evidence["violations"] == ["MODEL_SERVICE_REQUEST_BLOCKED"]
    assert "runtime-secret" not in json.dumps(evidence)
    with pytest.raises(InvalidRun, match="outside its exact HTTPS allowlist"):
        with _mailbox_environment(
            {
                "mode": "external-proxy",
                "external_allowlist": ["other.example.test"],
            }
        ):
            pass


def test_verifier_log_redaction_is_applied_in_place(tmp_path: Path) -> None:
    log = tmp_path / "verifier.log"
    log.write_text(
        "Authorization: Bearer abc123 token=very-secret otp=123456 safe=ok\n",
        encoding="utf-8",
    )
    redact_log_file(str(log))
    value = log.read_text()
    assert "abc123" not in value
    assert "very-secret" not in value
    assert "123456" not in value
    assert "safe=ok" in value


def _add_bundle_file(bundle: Path, relative: str, source: Path) -> None:
    destination = bundle / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    payload = destination.read_bytes()
    manifest["files"].append(
        {
            "path": relative,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "visibility": "agent-public",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_hidden_artifacts_are_rejected_by_exact_content_after_rename(
    tmp_path: Path,
) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    _add_bundle_file(
        bundle,
        "environment/seed/assets/neutral.bin",
        bundle / "tests/fixtures/reference-observations.json",
    )
    with pytest.raises(BundleValidationError, match="exact content"):
        validate_bundle(bundle)


def test_reference_raster_is_rejected_after_lossless_reencoding(
    tmp_path: Path,
) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    source = bundle / "tests/fixtures/visual/home.png"
    reencoded = tmp_path / "neutral-image.png"
    with Image.open(source) as image:
        image.save(reencoded, format="PNG", optimize=True, compress_level=9)
    assert reencoded.read_bytes() != source.read_bytes()
    _add_bundle_file(bundle, "environment/seed/assets/neutral-image.png", reencoded)
    with pytest.raises(BundleValidationError, match="decoded pixels"):
        validate_bundle(bundle)


def test_vendored_model_runtime_archive_is_rejected(tmp_path: Path) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    archive = tmp_path / "neutral.whl"
    with zipfile.ZipFile(archive, "w") as wheel:
        wheel.writestr("openai-1.0.dist-info/METADATA", "Name: hidden\n")
    _add_bundle_file(bundle, "tests/site/neutral.whl", archive)
    with pytest.raises(BundleValidationError, match="model runtime"):
        validate_bundle(bundle)


def test_hidden_artifact_inside_candidate_zip_is_rejected(tmp_path: Path) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as value:
        value.writestr(
            "assets/data.bin",
            (bundle / "tests/fixtures/reference-observations.json").read_bytes(),
        )
    _add_bundle_file(bundle, "environment/seed/assets/assets.zip", archive)
    with pytest.raises(BundleValidationError, match="candidate-visible archive"):
        validate_bundle(bundle)


def test_neutral_candidate_zip_remains_allowed(tmp_path: Path) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as value:
        value.writestr("assets/readme.txt", "ordinary offline runtime asset\n")
    _add_bundle_file(bundle, "environment/seed/assets/assets.zip", archive)
    assert validate_bundle(bundle)["status"] == "valid"


def test_javascript_model_sdk_is_rejected(tmp_path: Path) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    package = tmp_path / "package.json"
    package.write_text(
        json.dumps({"dependencies": {"@anthropic-ai/sdk": "1.0.0"}}),
        encoding="utf-8",
    )
    _add_bundle_file(bundle, "tests/site/package.json", package)
    with pytest.raises(BundleValidationError, match="model runtime"):
        validate_bundle(bundle)


def test_calibration_thresholds_cover_nop_oracle_and_repeatability() -> None:
    thresholds = {
        "nop_max_task_score": 5,
        "oracle_min_visual_score": 95,
    }
    nop = {"task_score": 5}
    oracle = {"task_score": 100, "visual_score": 95, "cicd_score": 100}
    assertions = calibration_assertions(
        nop,
        oracle,
        dict(oracle),
        thresholds,
        first_projection={"run": 1},
        second_projection={"run": 1},
    )
    assert all(assertions.values())
    assertions = calibration_assertions(
        {"task_score": 5.0001},
        oracle,
        dict(oracle),
        thresholds,
        first_projection={"run": 1},
        second_projection={"run": 2},
    )
    assert assertions["nop_task_score_at_most_threshold"] is False
    assert assertions["oracle_discrete_results_repeat_exactly"] is False


def test_reference_failure_does_not_publish_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, instance = _corpus(tmp_path)

    def fail_capture(*args: object, **kwargs: object) -> object:
        raise ReferenceObservationError("reference task failed")

    monkeypatch.setattr(
        "websitebench.harbor.capture._capture_observations", fail_capture
    )
    with pytest.raises(ReferenceObservationError, match="reference task failed"):
        capture_reference(instance)
    value = yaml.safe_load(instance.read_text())
    assert value["reference_observations"]["status"] == "pending"
    assert not (instance.parent / value["reference_observations"]["artifact"]).exists()


def test_task_urls_and_reference_mutations_stay_in_explicit_scope(
    tmp_path: Path,
) -> None:
    with pytest.raises(DslExecutionError, match="escaped"):
        _target_url("http://127.0.0.1:3000", "https://outside.example/path")
    with pytest.raises(
        ReferenceObservationError, match="requires scenario authorization"
    ):
        run_reference_actions(
            object(),
            [{"op": "api", "path": "/mutate", "method": "POST"}],
            base_url="https://reference.example.test",
            fixture_root=tmp_path,
            actors={},
            captures={},
            reference_mutation_allowed=False,
        )


def test_api_dsl_reuses_browser_context_session(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    class Response:
        status = 201

        @staticmethod
        def body() -> bytes:
            return b'{"owner":"current-actor"}'

    class Request:
        @staticmethod
        def fetch(url: str, **kwargs: object) -> Response:
            calls.append(("fetch", url))
            assert kwargs["method"] == "POST"
            return Response()

        @staticmethod
        def get(url: str, **kwargs: object) -> Response:
            calls.append(("get", url))
            return Response()

    class Context:
        request = Request()

    class Page:
        context = Context()

    page = Page()
    captures: dict[str, object] = {}
    run_actions(
        page,
        [
            {
                "op": "api",
                "path": "/session",
                "method": "POST",
                "body": {"value": 1},
                "capture_as": "response",
            }
        ],
        base_url="http://127.0.0.1:3000",
        fixture_root=tmp_path,
        actors={"primary": (Context(), page)},
        captures=captures,
    )
    assert captures["response"] == {
        "status": 201,
        "json": {"owner": "current-actor"},
    }
    assert (
        observe(
            page,
            {
                "kind": "api_json",
                "path": "/session",
                "json_pointer": "/owner",
            },
            base_url="http://127.0.0.1:3000",
            captures={},
        )
        == "current-actor"
    )
    assert calls == [
        ("fetch", "http://127.0.0.1:3000/session"),
        ("get", "http://127.0.0.1:3000/session"),
    ]


def test_remote_reference_mutation_requires_reset_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, instance = _corpus(tmp_path)
    manifest = yaml.safe_load(instance.read_text(encoding="utf-8"))
    suite_path = instance.parent / manifest["suites"]["task"]
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    suite["tasks"][0].update(
        {
            "reference_mutation_authorized": True,
            "actions": [{"op": "api", "path": "/resettable", "method": "POST"}],
        }
    )
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    monkeypatch.delenv("WEBSITEBENCH_REFERENCE_RESET_URL", raising=False)
    monkeypatch.delenv("WEBSITEBENCH_REFERENCE_RESET_CREDENTIAL", raising=False)

    with pytest.raises(ReferenceObservationError, match="reset gateway"):
        capture_reference(
            instance,
            reference_url="https://reference.example.test",
            allow_source_mutations=True,
        )


def test_candidate_deploy_failure_is_valid_zero_task_reward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    contract = json.loads((bundle / "tests/evaluation-contract.json").read_text())

    def no_render_check(*args: object, **kwargs: object) -> None:
        return None

    def failed_cicd(
        candidate_root: Path, suite: dict[str, object], **kwargs: object
    ) -> dict[str, object]:
        return {
            "schema_version": CICD_RESULTS_SCHEMA,
            "checks": [
                {
                    "check_id": item["id"],
                    "status": "failed",
                    "reason": "CANDIDATE_DEPLOY_FAILED",
                    "source": "trusted_platform_assertion",
                }
                for item in suite["checks"]  # type: ignore[index]
            ],
        }

    monkeypatch.setattr(
        "websitebench.harbor.evaluate.verify_render_environment", no_render_check
    )
    monkeypatch.setattr("websitebench.harbor.evaluate.run_platform_cicd", failed_cicd)
    output = tmp_path / "results"
    code = evaluate_candidate(
        candidate_root=bundle / "environment/seed",
        task_suite_path=bundle / "tests/fixtures/task-suite.json",
        visual_suite_path=bundle / "tests/fixtures/visual-suite.json",
        cicd_suite_path=bundle / "tests/fixtures/cicd-suite.json",
        reference_observations_path=bundle
        / "tests/fixtures/reference-observations.json",
        fixture_root=bundle / "tests/fixtures",
        output=output,
        browser_settings=contract["browser"],
        workers=4,
        mailbox=contract["mailbox"],
        network_policy_path=bundle / "tests/network-policy.json",
        budgets=contract["budgets"],
        reference_render_environment=contract["reference_render_environment"],
    )
    assert code == 0
    assert (output / "reward.txt").read_text() == "0.00000000\n"
    scorecard = json.loads((output / "scorecard.json").read_text())
    assert scorecard["task_score"] == 0
    assert scorecard["visual_score"] == 0
    visual = json.loads((output / "visual-results.json").read_text())
    assert visual["summary"]["minimum_ssim"] == 0


def test_four_worker_and_serial_task_order_are_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite = {
        "tasks": [
            {
                "id": f"task-{index}",
                "actions": [],
                "observations": [{"id": "state", "comparator": {"type": "exact"}}],
            }
            for index in range(12)
        ]
    }
    reference_observations = {
        "tasks": {
            task["id"]: {
                "observations": {"state": task["id"]},
            }
            for task in suite["tasks"]
        }
    }
    roots: list[Path] = []

    def fake_worker(
        declaration: dict[str, object],
        observed: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        roots.append(kwargs["worker_root"])  # type: ignore[arg-type]
        return {
            "task_id": declaration["id"],
            "status": "passed",
            "reason": "ALL_OBSERVATIONS_MATCH",
            "attempts": 1,
            "observations": [{"id": "state", "comparator": "exact", "passed": True}],
        }

    monkeypatch.setattr("websitebench.harbor.evaluate._task_worker", fake_worker)
    common = {
        "candidate_root": tmp_path,
        "fixture_root": tmp_path,
        "browser_settings": {},
        "ready_path": "/healthz",
    }
    serial = evaluate_task_suite(
        suite,
        reference_observations,
        working_root=tmp_path / "serial-work",
        trace_root=tmp_path / "serial-trace",
        workers=1,
        **common,
    )
    parallel = evaluate_task_suite(
        suite,
        reference_observations,
        working_root=tmp_path / "parallel-work",
        trace_root=tmp_path / "parallel-trace",
        workers=4,
        **common,
    )
    assert serial == parallel
    assert len({path.resolve() for path in roots}) == 24
    assert all(path.name.startswith("worker-") for path in roots)
    assert all(
        task["id"] not in path.as_posix() for path in roots for task in suite["tasks"]
    )


def test_one_worker_isolation_violation_invalidates_the_whole_task_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite = {
        "tasks": [
            {"id": f"task-{index}", "actions": [], "observations": []}
            for index in range(4)
        ]
    }
    reference_observations = {
        "tasks": {task["id"]: {"observations": {}} for task in suite["tasks"]}
    }

    def fake_worker(
        declaration: dict[str, object],
        observed: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        failed = declaration["id"] == "task-0"
        return {
            "task_id": declaration["id"],
            "status": "failed" if failed else "passed",
            "reason": (
                "CANDIDATE_WRITE_OUTSIDE_DATA_DIR"
                if failed
                else "ALL_OBSERVATIONS_MATCH"
            ),
            "attempts": 1,
            "observations": [],
        }

    monkeypatch.setattr("websitebench.harbor.evaluate._task_worker", fake_worker)
    result = evaluate_task_suite(
        suite,
        reference_observations,
        candidate_root=tmp_path,
        fixture_root=tmp_path,
        browser_settings={},
        ready_path="/healthz",
        working_root=tmp_path / "workers",
        trace_root=tmp_path / "traces",
        workers=4,
    )
    assert result["summary"] == {"passed": 0, "total": 4}
    assert {item["reason"] for item in result["tasks"]} == {
        "CANDIDATE_WRITE_OUTSIDE_DATA_DIR"
    }


def test_real_reference_observations_and_four_worker_evaluation_are_deterministic(
    tmp_path: Path,
) -> None:
    try:
        from playwright.sync_api import sync_playwright

        if shutil.which("strace") is None:
            _runtime_skip("local strace runtime is unavailable")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<h1>Font probe</h1>")
            page.screenshot()
            browser.close()
        font_manifest_text()
    except Exception as exc:
        _runtime_skip(f"local Chromium runtime is unavailable: {type(exc).__name__}")

    corpus, site_path, instance_path = _corpus(tmp_path)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        reference_port = int(probe.getsockname()[1])
    site_value = yaml.safe_load(site_path.read_text(encoding="utf-8"))
    site_value["runtime"]["reference_port"] = reference_port
    site_path.write_text(yaml.safe_dump(site_value, sort_keys=False), encoding="utf-8")

    server_source = """from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import smtplib

DATA = Path(os.environ["WEBSITEBENCH_DATA_DIR"])
DATA.mkdir(parents=True, exist_ok=True)

def count():
    path = DATA / "count"
    return int(path.read_text()) if path.exists() else 0

class Handler(BaseHTTPRequestHandler):
    def reply(self, body, content_type="text/html; charset=utf-8", cookie=None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(b"ok\\n", "text/plain")
        if self.path == "/count":
            return self.reply(json.dumps({"count": count()}).encode(), "application/json")
        cookie = self.headers.get("Cookie", "none")
        body = ("<!doctype html><html><body><h1>Stable page</h1>"
                "<span id=launch-name>Launch</span>"
                "<button aria-labelledby=launch-name>ignored</button>"
                f"<div id=cookie>{cookie}</div><label>OTP<input id=otp></label>"
                "</body></html>").encode()
        return self.reply(
            body,
            cookie="session=primary; Path=/" if self.path == "/set-cookie" else None,
        )

    def do_POST(self):
        if self.path == "/increment":
            value = count() + 1
            (DATA / "count").write_text(str(value))
            return self.reply(json.dumps({"count": value}).encode(), "application/json")
        if self.path == "/send-email":
            message = EmailMessage()
            message["From"] = "noreply@example.test"
            message["To"] = "user@example.test"
            message["Subject"] = "Verification code"
            message["X-WebsiteBench-Namespace"] = os.environ["WEBSITEBENCH_MAILBOX_NAMESPACE"]
            message["X-WebsiteBench-Capability"] = os.environ["WEBSITEBENCH_MAILBOX_CAPABILITY"]
            message.set_content("Use 123456 to continue")
            with smtplib.SMTP(os.environ["WEBSITEBENCH_SMTP_HOST"], int(os.environ["WEBSITEBENCH_SMTP_PORT"])) as smtp:
                smtp.send_message(message)
            return self.reply(b'{"sent": true}', "application/json")
        if self.path == "/verify":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = "accepted" if payload.get("value") == "123456" else "rejected"
            return self.reply(json.dumps({"result": result}).encode(), "application/json")
        self.send_error(404)

    def log_message(self, format, *args):
        return

ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
"""
    (site_path.parent / "reference/server.py").write_text(
        server_source, encoding="utf-8"
    )
    candidate_root = instance_path.parent / "public"
    (candidate_root / "server.py").write_text(server_source, encoding="utf-8")
    deploy = candidate_root / "deploy.sh"
    deploy.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\nexec python server.py\n",
        encoding="utf-8",
    )
    deploy.chmod(0o755)

    task_path = instance_path.parent / "fixtures/hidden/task-suite.json"
    task_suite = json.loads(task_path.read_text(encoding="utf-8"))
    static_tasks = [
        {
            "id": f"browser-semantics-{index}",
            "timeout_sec": 30,
            "actions": [{"op": "goto", "path": "/"}],
            "observations": [
                {
                    "id": "role",
                    "kind": "role",
                    "selector": {"role": "button", "name": "Launch"},
                    "comparator": {"type": "exact"},
                },
                {
                    "id": "label",
                    "kind": "label",
                    "selector": {"role": "button", "name": "Launch"},
                    "comparator": {"type": "exact"},
                },
                {
                    "id": "heading",
                    "kind": "text",
                    "selector": {"role": "heading", "name": "Stable page"},
                    "comparator": {"type": "exact"},
                },
                {"id": "url", "kind": "url", "comparator": {"type": "exact"}},
            ],
        }
        for index in range(2)
    ]
    actor_tasks = [
        {
            "id": f"actor-isolation-{index}",
            "timeout_sec": 30,
            "actions": [
                {"op": "goto", "path": "/set-cookie"},
                {"op": "new_actor", "actor": "secondary"},
                {"op": "use_actor", "actor": "secondary"},
                {"op": "goto", "path": "/"},
            ],
            "observations": [
                {
                    "id": "secondary-state",
                    "kind": "text",
                    "selector": {"css": "#cookie"},
                    "comparator": {"type": "exact"},
                }
            ],
        }
        for index in range(2)
    ]
    persistence_tasks = [
        {
            "id": f"restart-persistence-{index}",
            "timeout_sec": 30,
            "reference_mutation_authorized": True,
            "actions": [
                {
                    "op": "api",
                    "method": "POST",
                    "path": "/increment",
                    "capture_as": "increment",
                },
                {"op": "restart"},
                {
                    "op": "api",
                    "method": "GET",
                    "path": "/count",
                    "capture_as": "count",
                },
            ],
            "observations": [
                {
                    "id": "persisted-count",
                    "kind": "api_json",
                    "capture_as": "count",
                    "json_pointer": "/count",
                    "comparator": {"type": "exact"},
                }
            ],
        }
        for index in range(2)
    ]
    mailbox_tasks = [
        {
            "id": f"mailbox-isolation-{index}",
            "timeout_sec": 30,
            "reference_mutation_authorized": True,
            "actions": [
                {"op": "goto", "path": "/"},
                {"op": "api", "method": "POST", "path": "/send-email"},
                {
                    "op": "mailbox_code",
                    "value": "user@example.test",
                    "capture_as": "otp",
                },
                {
                    "op": "fill",
                    "selector": {"css": "#otp"},
                    "value": "${otp}",
                },
                {
                    "op": "api",
                    "method": "POST",
                    "path": "/verify",
                    "body": {"value": "${otp}"},
                    "capture_as": "verification",
                },
            ],
            "observations": [
                {
                    "id": "verification-result",
                    "kind": "api_json",
                    "capture_as": "verification",
                    "json_pointer": "/result",
                    "comparator": {"type": "exact"},
                }
            ],
        }
        for index in range(2)
    ]
    task_suite["tasks"] = static_tasks + actor_tasks + persistence_tasks + mailbox_tasks
    task_path.write_text(
        json.dumps(task_suite, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    observations_path = capture_reference(
        instance_path, corpus_root=corpus, allow_source_mutations=True
    )
    bundle = materialize_instance(
        instance_path, tmp_path / "bundle", corpus_root=corpus
    )
    reference_observations = json.loads(observations_path.read_text(encoding="utf-8"))
    browser_settings = load_site(site_path).data["runtime"]["browser"]
    with _mailbox_environment({"mode": "local-sidecar"}) as serial_mailbox:
        _, serial_sidecar = serial_mailbox
        serial = evaluate_task_suite(
            task_suite,
            reference_observations,
            candidate_root=bundle / "environment/seed",
            fixture_root=bundle / "tests/fixtures",
            browser_settings=browser_settings,
            ready_path="/healthz",
            working_root=tmp_path / "serial-workers",
            trace_root=tmp_path / "serial-traces",
            workers=1,
            mailbox_sidecar=serial_sidecar,
        )
    output = tmp_path / "formal-output"
    assert (
        evaluate_candidate(
            candidate_root=bundle / "environment/seed",
            task_suite_path=bundle / "tests/fixtures/task-suite.json",
            visual_suite_path=bundle / "tests/fixtures/visual-suite.json",
            cicd_suite_path=bundle / "tests/fixtures/cicd-suite.json",
            reference_observations_path=bundle
            / "tests/fixtures/reference-observations.json",
            fixture_root=bundle / "tests/fixtures",
            output=output,
            browser_settings=browser_settings,
            workers=4,
            mailbox={"mode": "local-sidecar"},
            network_policy_path=bundle / "tests/network-policy.json",
            budgets={"cpus": 4, "memory_mb": 8192, "storage_mb": 20480},
            reference_render_environment=reference_observations["render_environment"],
        )
        == 0
    )
    parallel = json.loads((output / "task-results.json").read_text(encoding="utf-8"))
    assert serial == parallel
    assert parallel["summary"] == {"passed": 8, "total": 8}
    assert (output / "reward.txt").read_text(encoding="utf-8") == "1.00000000\n"
    scorecard = json.loads((output / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["task_score"] == 100
    assert scorecard["visual_score"] == 100
    assert scorecard["cicd_score"] == 100
    assert scorecard["reward"] == 1
    network_evidence = json.loads(
        (output / "network-runtime-evidence.json").read_text(encoding="utf-8")
    )
    assert network_evidence["model_request_count"] == 0
    assert network_evidence["violations"] == []


def test_real_nop_and_repeated_oracle_calibration_meets_thresholds(
    tmp_path: Path,
) -> None:
    try:
        from playwright.sync_api import sync_playwright

        if shutil.which("strace") is None:
            _runtime_skip("local strace runtime is unavailable")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<h1>Calibration probe</h1>")
            page.screenshot()
            browser.close()
        font_manifest_text()
    except Exception as exc:
        _runtime_skip(f"local calibration runtime is unavailable: {type(exc).__name__}")

    corpus, site_path, instance_path = _corpus(tmp_path)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        reference_port = int(probe.getsockname()[1])
    site_value = yaml.safe_load(site_path.read_text(encoding="utf-8"))
    site_value["runtime"]["reference_port"] = reference_port
    site_path.write_text(yaml.safe_dump(site_value, sort_keys=False), encoding="utf-8")
    server_source = """from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"ok\\n" if self.path == "/healthz" else b"<!doctype html><html><body><h1>Oracle page</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, format, *args):
        return

ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
"""
    deploy_source = "#!/usr/bin/env bash\nset -Eeuo pipefail\nexec python server.py\n"
    reference = site_path.parent / "reference"
    (reference / "server.py").write_text(server_source, encoding="utf-8")
    (reference / "run.sh").write_text(deploy_source, encoding="utf-8")
    (reference / "run.sh").chmod(0o755)
    oracle = site_path.parent / "oracle"
    (oracle / "server.py").write_text(server_source, encoding="utf-8")
    (oracle / "deploy.sh").write_text(deploy_source, encoding="utf-8")
    (oracle / "deploy.sh").chmod(0o755)
    solve = instance_path.parent / "solution/solve.sh"
    solve.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        'cp -a "$WEBSITEBENCH_SOLUTION_SITE_ROOT/." '
        '"$WEBSITEBENCH_CANDIDATE_ROOT/"\n',
        encoding="utf-8",
    )
    solve.chmod(0o755)

    capture_reference(instance_path, corpus_root=corpus)
    bundle = materialize_instance(
        instance_path, tmp_path / "calibration-bundle", corpus_root=corpus
    )
    output = tmp_path / "real-calibration"
    assert calibrate_bundle(bundle, output) == 0
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["runs"]["nop"]["task_score"] <= 5
    for name in ("oracle-first", "oracle-second"):
        assert report["runs"][name]["task_score"] == 100
        assert report["runs"][name]["visual_score"] >= 95
        assert report["runs"][name]["cicd_score"] == 100
    assert (
        report["runs"]["oracle-first"]["discrete_signature"]
        == report["runs"]["oracle-second"]["discrete_signature"]
    )


def test_verifier_wrapper_crash_is_invalid_and_has_no_reward(
    tmp_path: Path,
) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    invalid_contract = tmp_path / "invalid-contract.json"
    invalid_contract.write_text(
        json.dumps({"schema_version": "wrong"}), encoding="utf-8"
    )
    output = tmp_path / "wrapper-output"
    completed = subprocess.run(
        [
            sys.executable,
            str(bundle / "tests/run_v2.py"),
            "--contract",
            str(invalid_contract),
            "--candidate",
            str(bundle / "environment/seed"),
            "--output",
            str(output),
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(bundle / "tests"),
        },
        check=False,
    )
    assert completed.returncode == 2
    assert json.loads((output / "verdict.json").read_text())["status"] == "INVALID_RUN"
    assert not (output / "reward.txt").exists()
    assert not (output / "scorecard.json").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="formal verifier is Linux-only")
def test_sandbox_preflight_records_required_kernel_features() -> None:
    fingerprint = sandbox_preflight()
    assert fingerprint["landlock_abi"] >= 4
    assert fingerprint["seccomp_user_notification"] is True
    assert fingerprint["x32_unavailable"] is True
    assert fingerprint["enforcement_probe_passed"] is True


def test_sandbox_preflight_failure_is_invalid_and_emits_no_reward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> dict[str, object]:
        raise OSError("sandbox unavailable")

    monkeypatch.setattr("websitebench.harbor.evaluate.sandbox_preflight", unavailable)
    output = tmp_path / "output"
    with pytest.raises(InvalidRun, match="kernel sandbox"):
        evaluate_candidate(
            candidate_root=tmp_path / "candidate",
            task_suite_path=tmp_path / "task.json",
            visual_suite_path=tmp_path / "visual.json",
            cicd_suite_path=tmp_path / "cicd.json",
            reference_observations_path=tmp_path / "reference-observations.json",
            fixture_root=tmp_path,
            output=output,
            browser_settings={},
            reference_render_environment={},
        )
    assert not (output / "reward.txt").exists()
    assert not (output / "scorecard.json").exists()


def test_network_policy_requires_runtime_closure_or_platform_attestation() -> None:
    policy = {
        "default": "deny",
        "public_internet": False,
        "model_services": False,
        "mailbox_external_allowlist": [],
    }
    assert not verifier_network_policy_enforced(
        policy, default_route_present=True, platform_attested=False
    )
    assert verifier_network_policy_enforced(
        policy, default_route_present=True, platform_attested=True
    )
    assert verifier_network_policy_enforced(
        policy, default_route_present=False, platform_attested=False
    )
    assert not verifier_network_policy_enforced(
        {**policy, "public_internet": True},
        default_route_present=False,
        platform_attested=True,
    )


def test_calibration_runner_executes_nop_and_two_fresh_oracles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, instance = _corpus(tmp_path)
    _capture_fake_observations(instance)
    bundle = materialize_instance(instance, tmp_path / "bundle")
    applied: list[Path] = []
    evaluated: list[str] = []

    def fake_oracle(bundle_root: Path, candidate: Path, timeout: float) -> None:
        applied.append(candidate)

    def fake_evaluate(
        bundle_root: Path,
        candidate: Path,
        output: Path,
        contract: dict[str, object],
    ) -> int:
        name = output.name
        evaluated.append(name)
        output.mkdir(parents=True)
        oracle = name.startswith("oracle-")
        scorecard = {
            "task_score": 100 if oracle else 0,
            "visual_score": 100 if oracle else 0,
            "cicd_score": 100 if oracle else 0,
            "reward": 1 if oracle else 0,
        }
        (output / "scorecard.json").write_text(json.dumps(scorecard))
        (output / "task-results.json").write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "healthz",
                            "status": "passed" if oracle else "failed",
                            "attempts": 1,
                            "observations": [],
                        }
                    ]
                }
            )
        )
        (output / "visual-results.json").write_text(
            json.dumps(
                {
                    "checkpoints": [
                        {
                            "checkpoint_id": "home",
                            "status": "passed" if oracle else "failed",
                            "ssim": 1 if oracle else 0,
                            "regions": [],
                        }
                    ]
                }
            )
        )
        (output / "cicd-results.json").write_text(
            json.dumps(
                {
                    "checks": [
                        {
                            "check_id": identifier,
                            "status": "passed" if oracle else "failed",
                        }
                        for identifier in PLATFORM_CICD_CHECKS
                    ]
                }
            )
        )
        return 0

    monkeypatch.setattr("websitebench.harbor.calibration_v2._apply_oracle", fake_oracle)
    monkeypatch.setattr(
        "websitebench.harbor.calibration_v2._run_candidate", fake_evaluate
    )
    output = tmp_path / "calibration"
    assert calibrate_bundle(bundle, output) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "passed"
    assert evaluated == ["nop", "oracle-first", "oracle-second"]
    assert len(applied) == 2
    assert applied[0] != applied[1]


def test_candidate_write_audit_rejects_paths_outside_data_dir(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidate"
    data = tmp_path / "data"
    audit = tmp_path / "audit" / "candidate"
    root.mkdir()
    data.mkdir()
    audit.parent.mkdir()
    (audit.parent / "candidate.123").write_text(
        f'openat(AT_FDCWD, "{data / "inside"}", O_WRONLY|O_CREAT, 0666) = 3\n'
        'openat(AT_FDCWD, "/tmp/escape", O_WRONLY|O_CREAT, 0666) = 4\n',
        encoding="utf-8",
    )
    process = CandidateProcess(root, 3000, data, "audit", audit_prefix=audit)
    assert process.write_violations() == ["/tmp/escape"]


def test_candidate_write_audit_covers_metadata_fd_and_shared_mmap(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidate"
    data = tmp_path / "data"
    audit = tmp_path / "audit" / "candidate"
    root.mkdir()
    data.mkdir()
    audit.parent.mkdir()
    (audit.parent / "candidate.123").write_text(
        'openat2(AT_FDCWD, "/tmp/openat2", {flags=O_WRONLY|O_CREAT}, 24) = 3\n'
        "ftruncate(4</tmp/ftruncate>, 0) = 0\n"
        "mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, 5</tmp/mapped>, 0) = 0x1\n",
        encoding="utf-8",
    )
    process = CandidateProcess(root, 3000, data, "audit", audit_prefix=audit)
    assert process.write_violations() == [
        "/tmp/ftruncate",
        "/tmp/mapped",
        "/tmp/openat2",
    ]


def test_candidate_write_audit_normalizes_seccomp_broker_proc_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidate"
    data = tmp_path / "data"
    audit = tmp_path / "audit" / "candidate"
    root.mkdir()
    data.mkdir()
    audit.parent.mkdir()
    inside = data / "site.sqlite3"
    (audit.parent / "candidate.123").write_text(
        f'openat(AT_FDCWD, "/proc/4242/fd/9", O_RDWR|O_CLOEXEC) = 4<{inside}>\n'
        'openat(AT_FDCWD, "/proc/4242/mem", O_WRONLY|O_CLOEXEC) = 5</proc/4242/mem>\n'
        'openat(AT_FDCWD, "/proc/4242/fd/10", O_RDWR|O_CLOEXEC) = 6</tmp/escape>\n',
        encoding="utf-8",
    )
    process = CandidateProcess(root, 3000, data, "audit", audit_prefix=audit)
    assert process.write_violations() == ["/tmp/escape"]


def test_candidate_network_audit_rejects_non_loopback_destinations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidate"
    data = tmp_path / "data"
    audit = tmp_path / "audit" / "candidate"
    root.mkdir()
    data.mkdir()
    audit.parent.mkdir()
    (audit.parent / "candidate.123").write_text(
        'connect(3, {sa_family=AF_INET, sin_port=htons(3000), sin_addr=inet_addr("127.0.0.1")}, 16) = 0\n'
        'connect(3, {sa_family=AF_INET, sin_port=htons(43210), sin_addr=inet_addr("127.0.0.1")}, 16) = -1 EPERM\n'
        'connect(4, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("203.0.113.8")}, 16) = -1\n',
        encoding="utf-8",
    )
    process = CandidateProcess(root, 3000, data, "audit", audit_prefix=audit)
    assert process.network_violations() == [
        "203.0.113.8",
        "LOOPBACK_CONNECT_OUTSIDE_ALLOWED_PORTS",
    ]


def test_candidate_ipc_audit_rejects_kernel_global_channels(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    data = tmp_path / "data"
    audit = tmp_path / "audit" / "candidate"
    root.mkdir()
    data.mkdir()
    audit.parent.mkdir()
    (audit.parent / "candidate.123").write_text(
        "shmget(IPC_PRIVATE, 4096, IPC_CREAT|0600) = -1 EPERM (Operation not permitted)\n",
        encoding="utf-8",
    )
    process = CandidateProcess(root, 3000, data, "audit", audit_prefix=audit)
    assert process.ipc_violations() == ["SHARED_IPC_ATTEMPT"]


def test_audited_candidate_keeps_tracer_privileged_and_drops_only_tracee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    deploy = root / "deploy.sh"
    deploy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    deploy.chmod(0o755)
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            captured["command"] = command
            captured.update(kwargs)

    monkeypatch.setattr("websitebench.harbor.judge_v2.os.geteuid", lambda: 0)
    monkeypatch.setattr("websitebench.harbor.judge_v2.os.chown", lambda *args: None)
    monkeypatch.setattr(
        "websitebench.harbor.judge_v2.shutil.which",
        lambda name: "/usr/bin/strace" if name == "strace" else None,
    )
    monkeypatch.setattr("websitebench.harbor.judge_v2.subprocess.Popen", FakeProcess)

    process = CandidateProcess(
        root,
        3000,
        tmp_path / "worker" / "data",
        "opaque-worker",
        audit_prefix=tmp_path / "root-audit" / "first",
        isolation_uid=54321,
    )
    process.start()

    assert captured["command"] == [
        "/usr/bin/strace",
        "--follow-forks",
        "--decode-fds=path",
        "--output-separately",
        "--output",
        str(tmp_path / "root-audit" / "first"),
        "--trace=%file,%memory,%network,%ipc,ftruncate",
        sys.executable,
        str(
            Path(sys.modules["websitebench.harbor.judge_v2"].__file__).with_name(
                "sandbox_v2.py"
            )
        ),
        "--root",
        str(root),
        "--data",
        str(tmp_path / "worker" / "data"),
        "--bind-port",
        "3000",
        "--connect-port",
        "3000",
        "--uid",
        "54321",
        "--gid",
        "54321",
        "--",
        str(deploy),
    ]
    assert captured["preexec_fn"] is None


def test_kernel_sandbox_blocks_cross_worker_tmp_leak(tmp_path: Path) -> None:
    if (
        not hasattr(os, "geteuid")
        or os.geteuid() != 0
        or shutil.which("strace") is None
    ):
        _runtime_skip("root and strace are required for kernel isolation test")

    with tempfile.TemporaryDirectory(
        prefix="websitebench-root-isolation-", dir="/tmp"
    ) as temporary:
        root = Path(temporary)
        root.chmod(0o711)
        shared = Path("/tmp") / f"websitebench-cross-worker-{os.getpid()}"
        writer_root = root / "writer"
        reader_root = root / "reader"
        writer_root.mkdir(mode=0o755)
        reader_root.mkdir(mode=0o755)
        writer_deploy = writer_root / "deploy.sh"
        reader_deploy = reader_root / "deploy.sh"
        writer_deploy.write_text(
            "#!/bin/sh\nprintf leak > " + str(shared) + "\nexec sleep 30\n",
            encoding="utf-8",
        )
        reader_deploy.write_text(
            "#!/bin/sh\n"
            f'test -r {shared} && printf seen > "$WEBSITEBENCH_DATA_DIR/seen"\n'
            "exec sleep 30\n",
            encoding="utf-8",
        )
        writer_deploy.chmod(0o755)
        reader_deploy.chmod(0o755)
        writer = CandidateProcess(
            writer_root,
            3001,
            root / "writer-data",
            "writer",
            audit_prefix=root / "audit" / "writer",
            isolation_uid=61001,
        )
        reader = CandidateProcess(
            reader_root,
            3002,
            root / "reader-data",
            "reader",
            audit_prefix=root / "audit" / "reader",
            isolation_uid=61002,
        )
        try:
            writer.start()
            deadline = time.monotonic() + 5
            while not shared.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            writer.stop()
            reader.start()
            seen = reader.data_dir / "seen"
            deadline = time.monotonic() + 5
            while not seen.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            reader.stop()
            assert not shared.exists()
            assert not seen.exists()
            assert str(shared) in writer.write_violations()
            assert reader.write_violations() == []
        finally:
            writer.stop()
            reader.stop()
            shared.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform != "linux", reason="formal verifier is Linux-only")
def test_kernel_sandbox_blocks_file_network_and_ipc_before_exec(
    tmp_path: Path,
) -> None:
    shared = Path("/tmp") / f"websitebench-sandbox-probe-{os.getpid()}"
    root = tmp_path / "candidate"
    root.mkdir()
    deploy = root / "deploy.sh"
    deploy.write_text(
        "#!/usr/bin/env python3\n"
        "import ctypes, errno, fcntl, json, os, socket, sqlite3\n"
        f"shared = {str(shared)!r}\n"
        "blocked = {}\n"
        "try:\n"
        "    open(shared, 'w').write('leak')\n"
        "    blocked['file'] = False\n"
        "except PermissionError:\n"
        "    blocked['file'] = True\n"
        "try:\n"
        "    open('/proc/1/cmdline', 'rb').read()\n"
        "    blocked['proc'] = False\n"
        "except PermissionError:\n"
        "    blocked['proc'] = True\n"
        "try:\n"
        "    open('/sys/fs/cgroup/memory.current', 'rb').read()\n"
        "    blocked['sys'] = False\n"
        "except PermissionError:\n"
        "    blocked['sys'] = True\n"
        "try:\n"
        "    os.setsid()\n"
        "    blocked['setsid'] = False\n"
        "except PermissionError:\n"
        "    blocked['setsid'] = True\n"
        "try:\n"
        "    common = open(__file__, 'rb')\n"
        "    fcntl.flock(common, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "    blocked['flock'] = False\n"
        "except PermissionError:\n"
        "    blocked['flock'] = True\n"
        "try:\n"
        "    fcntl.lockf(common, fcntl.LOCK_SH | fcntl.LOCK_NB)\n"
        "    blocked['record_lock'] = False\n"
        "except PermissionError:\n"
        "    blocked['record_lock'] = True\n"
        "try:\n"
        "    socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "    blocked['udp'] = False\n"
        "except PermissionError:\n"
        "    blocked['udp'] = True\n"
        "try:\n"
        "    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    tcp.bind(('127.0.0.1', 31338))\n"
        "    blocked['tcp_bind'] = False\n"
        "except PermissionError:\n"
        "    blocked['tcp_bind'] = True\n"
        "try:\n"
        "    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    tcp.connect(('127.0.0.1', 31338))\n"
        "    blocked['tcp_connect'] = False\n"
        "except PermissionError:\n"
        "    blocked['tcp_connect'] = True\n"
        "try:\n"
        "    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "    blocked['unix'] = False\n"
        "except PermissionError:\n"
        "    blocked['unix'] = True\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "machine = os.uname().machine\n"
        "shmget = 29 if machine in {'x86_64', 'amd64'} else 194\n"
        "result = libc.syscall(shmget, 0, 4096, 0o1600)\n"
        "blocked['ipc'] = result == -1 and ctypes.get_errno() == errno.EPERM\n"
        "inotify_init1 = 294 if machine in {'x86_64', 'amd64'} else 26\n"
        "result = libc.syscall(inotify_init1, 0)\n"
        "blocked['inotify'] = result == -1 and ctypes.get_errno() == errno.EPERM\n"
        "path = os.path.join(os.environ['WEBSITEBENCH_DATA_DIR'], 'result.json')\n"
        "database = sqlite3.connect(os.path.join(os.environ['WEBSITEBENCH_DATA_DIR'], 'db.sqlite'))\n"
        "database.execute('create table state (value text)')\n"
        "database.commit()\n"
        "database.close()\n"
        "blocked['sqlite'] = True\n"
        "open(path, 'w').write(json.dumps(blocked, sort_keys=True))\n",
        encoding="utf-8",
    )
    deploy.chmod(0o755)
    process = CandidateProcess(root, 31337, tmp_path / "data", "sandbox-probe")
    try:
        process.start()
        deadline = time.monotonic() + 10
        result = process.data_dir / "result.json"
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert json.loads(result.read_text(encoding="utf-8")) == {
            "file": True,
            "flock": True,
            "inotify": True,
            "ipc": True,
            "proc": True,
            "record_lock": True,
            "setsid": True,
            "sqlite": True,
            "sys": True,
            "tcp_bind": True,
            "tcp_connect": True,
            "udp": True,
            "unix": True,
        }
        assert not shared.exists()
    finally:
        process.stop()
        shared.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform != "linux", reason="formal verifier is Linux-only")
def test_lock_broker_never_continues_an_fd_swap_to_shared_inode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    deploy = root / "deploy.sh"
    lock_start = 2_000_000_000 + os.getpid()
    deploy.write_text(
        "#!/usr/bin/env python3\n"
        "import fcntl, os, struct, threading, time\n"
        f"start = {lock_start}\n"
        "data = open(os.path.join(os.environ['WEBSITEBENCH_DATA_DIR'], 'private.lock'), 'w+b')\n"
        "shared = open('/dev/null', 'r+b', buffering=0)\n"
        "target = 100\n"
        "os.dup2(data.fileno(), target)\n"
        "running = True\n"
        "def swap():\n"
        "    while running:\n"
        "        os.dup2(data.fileno(), target)\n"
        "        os.dup2(shared.fileno(), target)\n"
        "thread = threading.Thread(target=swap)\n"
        "thread.start()\n"
        "value = struct.pack('hhqqi', fcntl.F_WRLCK, os.SEEK_SET, start, 1, 0)\n"
        "for _ in range(5000):\n"
        "    try:\n"
        "        fcntl.fcntl(target, getattr(fcntl, 'F_OFD_SETLK', 37), value)\n"
        "    except (OSError, PermissionError):\n"
        "        pass\n"
        "running = False\n"
        "thread.join()\n"
        "open(os.path.join(os.environ['WEBSITEBENCH_DATA_DIR'], 'ready'), 'w').write('ok')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    deploy.chmod(0o755)
    process = CandidateProcess(root, 31339, tmp_path / "data", "fd-race")
    try:
        process.start()
        ready = process.data_dir / "ready"
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.is_file()
        value = struct.pack("hhqqi", fcntl.F_WRLCK, os.SEEK_SET, lock_start, 1, 0)
        with open("/dev/null", "r+b", buffering=0) as shared:
            fcntl.fcntl(shared, getattr(fcntl, "F_OFD_SETLK", 37), value)
    finally:
        process.stop()
