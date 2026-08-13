from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from websitebench.harbor.materialize import materialize_instance
from websitebench.harbor.scaffold import initialize_instance, initialize_site


def test_service_fallback_emits_the_exact_failed_node_set(tmp_path: Path) -> None:
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
    bundle = materialize_instance(instance, tmp_path / "bundle", allow_legacy_v1=True)
    output = tmp_path / "failed-ctrf.json"
    code = (
        "from pathlib import Path\n"
        "from service_lib import write_all_failed_ctrf\n"
        f"write_all_failed_ctrf(Path({str(bundle / 'tests/required-nodes.json')!r}), "
        f"Path({str(output)!r}), 'CANDIDATE_START_FAILED')\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=bundle / "tests",
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    required = json.loads(
        (bundle / "tests/required-nodes.json").read_text(encoding="utf-8")
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    tests = report["results"]["tests"]
    assert {test["name"] for test in tests} == set(required["nodes"])
    assert {test["status"] for test in tests} == {"failed"}
    assert report["results"]["extra"]["hard_failures"] == []


def test_service_helper_has_a_windows_process_cleanup_path(
    tmp_path: Path,
) -> None:
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
    bundle = materialize_instance(
        instance,
        tmp_path / "bundle-windows-cleanup",
        allow_legacy_v1=True,
    )
    helper = (bundle / "tests/service_lib.py").read_text(encoding="utf-8")

    assert 'if os.name == "nt":' in helper
    assert "process.terminate()" in helper
    assert "process.kill()" in helper
    assert '"SYSTEMROOT"' in helper
