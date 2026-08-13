from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from websitebench.site_compiler.canonical import canonical_json_bytes
from websitebench.workflow.errors import WorkflowError
from websitebench.workflow.fullstack import (
    calibrate_visual_stability,
    scaffold_semantic_selection,
    validate_fullstack_candidate,
    validate_semantic_selection,
    validate_source_acquisition_report,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _acquisition(root: Path) -> Path:
    source_scope = root / "materials/alpha/scope/source-acquisition-spec.json"
    _write(source_scope, {"site_id": "alpha"})
    artifact = root / "materials/alpha/source-current/home-dom.html"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("<html><body>Alpha</body></html>\n", encoding="utf-8")
    report = {
        "schema_version": "offline-clone.source-acquisition-report.v3",
        "site_id": "alpha",
        "capture_id": "alpha.capture.1",
        "capture_provider": "playwright-chrome",
        "source_scope": {
            "path": source_scope.relative_to(root).as_posix(),
            "bytes": source_scope.stat().st_size,
        },
        "started_at": "2026-07-29T12:00:00Z",
        "finished_at": "2026-07-29T12:05:00Z",
        "safety": {
            "methods": ["GET"],
            "anonymous": True,
            "mutations_performed": False,
            "bypass_attempted": False,
            "isolated_context_per_page": True,
        },
        "concurrency": {
            "global_download_jobs": 1,
            "per_origin_download_jobs": 1,
            "per_origin_page_jobs": 1,
            "adaptive_backoff": False,
        },
        "pages": [
            {
                "row_id": "home.loaded.desktop",
                "priority": "p0",
                "requested_url": "https://example.com/",
                "final_url": "https://example.com/",
                "status": "captured",
                "viewports": ["desktop"],
                "artifacts": [
                    {
                        "kind": "dom",
                        "path": "materials/alpha/source-current/home-dom.html",
                        "bytes": artifact.stat().st_size,
                    }
                ],
            }
        ],
        "resources": {
            "logical_required": 2,
            "downloaded": 2,
            "verified": 2,
            "referenced": 2,
            "browser_requested": 2,
            "physical_file_count": 1,
            "missing_required_ids": [],
        },
        "closure": {
            "status": "complete",
            "failed_request_count": 0,
            "broken_resource_count": 0,
            "blocked_mutation_request_count": 0,
            "unresolved_css_reference_count": 0,
        },
        "blockers": [],
    }
    path = (
        root
        / "materials/alpha/artifacts/offline-clone/frontend"
        / "source-acquisition-report.json"
    )
    _write(path, report)
    return path


def _selection(root: Path) -> Path:
    frontend = root / "materials/alpha/clone/frontend/ui.html"
    frontend.parent.mkdir(parents=True, exist_ok=True)
    if not frontend.exists():
        frontend.write_text("<main>Alpha</main>\n", encoding="utf-8")
    purpose = root / "materials/alpha/scope/purpose.json"
    if not purpose.exists():
        _write(purpose, {"purpose": "alpha"})
    frontend_artifacts = [
        {
            "kind": "tree",
            "path": "materials/alpha/clone/frontend",
        }
    ]
    source_artifacts = [
        {
            "kind": "file",
            "path": "materials/alpha/scope/purpose.json",
            "bytes": purpose.stat().st_size,
        }
    ]
    backend = root / "materials/alpha/backend/model.json"
    if backend.is_file():
        source_artifacts.append(
            {
                "kind": "file",
                "path": "materials/alpha/backend/model.json",
                "bytes": backend.stat().st_size,
            }
        )
    source_artifacts.sort(key=lambda item: item["path"])
    value = {
        "schema_version": "offline-clone.semantic-selection.v3",
        "site_id": "alpha",
        "selection_id": "alpha.selection.1",
        "frontend_subject": {"artifacts": frontend_artifacts},
        "source_scope_subject": {"artifacts": source_artifacts},
        "generated_at": "2026-07-29T12:08:00Z",
        "selection_policy": "fidelity-first-automatic-v1",
        "capabilities": [
            {
                "id": "social.comment",
                "priority": "p0",
                "applicable": True,
                "certainty": "ambiguous",
                "mandatory_when_applicable": True,
                "trigger": "source-visible",
                "evidence_refs": ["home.loaded.desktop#comment-control"],
                "disposition": "full-local-model",
                "decision_source": "mechanical",
                "rationale": "P0 ambiguity mechanically selects full local depth.",
            }
        ],
    }
    path = root / "materials/alpha/scope/semantic-selection.json"
    _write(path, value)
    return path


def test_source_acquisition_checks_files_and_closure(tmp_path: Path) -> None:
    report = _acquisition(tmp_path)

    result = validate_source_acquisition_report(
        tmp_path,
        report.relative_to(tmp_path),
    )

    assert result["status"] == "passed"
    assert result["logical_required"] == 2
    assert result["physical_file_count"] == 1

    artifact = tmp_path / "materials/alpha/source-current/home-dom.html"
    artifact.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="byte count mismatch"):
        validate_source_acquisition_report(
            tmp_path,
            report.relative_to(tmp_path),
        )


def test_source_acquisition_accepts_redacted_browserbase_evidence(
    tmp_path: Path,
) -> None:
    report = _acquisition(tmp_path)
    value = json.loads(report.read_text(encoding="utf-8"))
    value["capture_provider"] = "browserbase-chrome-devtools"
    value["safety"].update(
        {
            "methods": ["GET", "HEAD"],
            "anonymous": False,
            "isolated_context_per_page": False,
        }
    )
    value["pages"][0]["artifacts"][0]["kind"] = "availability"
    _write(report, value)

    result = validate_source_acquisition_report(
        tmp_path,
        report.relative_to(tmp_path),
    )

    assert result["status"] == "passed"
    assert result["capture_provider"] == "browserbase-chrome-devtools"


def test_ambiguous_p0_semantics_are_resolved_mechanically(tmp_path: Path) -> None:
    decided = _selection(tmp_path)
    result = validate_semantic_selection(
        tmp_path,
        decided.relative_to(tmp_path),
    )
    assert result["status"] == "passed"
    assert result["persistent_backend_ready"] is True
    assert result["selected_capability_ids"] == ["social.comment"]


def test_applicable_common_capability_cannot_be_excluded(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    value = json.loads(selection.read_text(encoding="utf-8"))
    capability = value["capabilities"][0]
    capability["certainty"] = "determinate"
    capability["decision_source"] = "mechanical"
    capability["disposition"] = "excluded-with-rationale"
    _write(selection, value)

    with pytest.raises(WorkflowError, match="mandatory capability"):
        validate_semantic_selection(
            tmp_path,
            selection.relative_to(tmp_path),
        )


def test_external_blocker_never_marks_persistent_backend_ready(
    tmp_path: Path,
) -> None:
    selection = _selection(tmp_path)
    value = json.loads(selection.read_text(encoding="utf-8"))
    capability = value["capabilities"][0]
    capability["certainty"] = "determinate"
    capability["decision_source"] = "mechanical"
    capability["disposition"] = "external-blocked"
    _write(selection, value)

    result = validate_semantic_selection(
        tmp_path,
        selection.relative_to(tmp_path),
    )

    assert result["status"] == "blocked"
    assert result["persistent_backend_ready"] is False
    assert result["external_blocked_capability_ids"] == ["social.comment"]


def test_fullstack_candidate_checks_all_inner_loop_inputs(tmp_path: Path) -> None:
    acquisition = _acquisition(tmp_path)
    backend_model = tmp_path / "materials/alpha/backend/model.json"
    _write(backend_model, {"site_id": "alpha", "capabilities": ["social.comment"]})
    selection = _selection(tmp_path)
    clone = tmp_path / "materials/alpha/clone"
    clone.mkdir(parents=True, exist_ok=True)
    (clone / "app.py").write_text("APP = 'alpha'\n", encoding="utf-8")
    frontend_evidence = []
    for kind in ("visual-calibration", "browser-audit", "focused-regression"):
        path = (
            tmp_path
            / "materials/alpha/artifacts/offline-clone/frontend"
            / f"{kind}.json"
        )
        _write(path, {"kind": kind, "passed": True})
        frontend_evidence.append(
            {
                "kind": kind,
                "path": path.relative_to(tmp_path).as_posix(),
                "bytes": path.stat().st_size,
            }
        )
    backend_evidence = []
    for kind, relative in (
        ("backend-model", "materials/alpha/backend/model.json"),
        (
            "proof-matrix",
            "materials/alpha/artifacts/offline-clone/backend/proof-matrix.json",
        ),
        (
            "focused-regression",
            "materials/alpha/artifacts/offline-clone/backend/focused-regression.json",
        ),
        (
            "reset-audit",
            "materials/alpha/artifacts/offline-clone/backend/reset-audit.json",
        ),
    ):
        path = tmp_path / relative
        if not path.exists():
            _write(path, {"kind": kind, "passed": True})
        backend_evidence.append(
            {
                "kind": kind,
                "path": relative,
                "bytes": path.stat().st_size,
            }
        )
    value = {
        "schema_version": "offline-clone.fullstack-candidate.v3",
        "site_id": "alpha",
        "candidate_tree": {"path": "materials/alpha/clone"},
        "source_acquisition": {
            "path": acquisition.relative_to(tmp_path).as_posix(),
            "bytes": acquisition.stat().st_size,
        },
        "semantic_selection": {
            "path": selection.relative_to(tmp_path).as_posix(),
            "bytes": selection.stat().st_size,
        },
        "frontend": {
            "candidate_stability_runs": 2,
            "p0_region_failures": 0,
            "console_error_count": 0,
            "runtime_remote_request_count": 0,
            "evidence": frontend_evidence,
        },
        "backend": {
            "applicable_capability_count": 1,
            "verified_capability_count": 1,
            "proof_obligation_failures": 0,
            "evidence": backend_evidence,
        },
        "status": "complete",
    }
    candidate = (
        tmp_path
        / "materials/alpha/artifacts/offline-clone/fullstack/candidate.json"
    )
    _write(candidate, value)

    result = validate_fullstack_candidate(
        tmp_path,
        candidate.relative_to(tmp_path),
    )

    assert result["status"] == "passed"
    assert "candidate_identity_sha256" not in result

    (tmp_path / frontend_evidence[0]["path"]).unlink()
    with pytest.raises(WorkflowError, match="evidence is not a file"):
        validate_fullstack_candidate(
            tmp_path,
            candidate.relative_to(tmp_path),
        )


def test_visual_calibration_uses_three_source_frames_and_region_floor(
    tmp_path: Path,
) -> None:
    sample_paths = []
    for index in range(3):
        path = tmp_path / f"materials/alpha/source-current/main-{index}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), (240, 240, 240)).save(path)
        sample_paths.append(path.relative_to(tmp_path).as_posix())
    spec = tmp_path / "materials/alpha/scope/visual-calibration-spec.json"
    _write(
        spec,
        {
            "schema_version": (
                "offline-clone.visual-stability-calibration-spec.v1"
            ),
            "site_id": "alpha",
            "rows": [
                {
                    "id": "home.loaded.desktop.main",
                    "region": "main",
                    "source_samples": [
                        {"path": path} for path in sample_paths
                    ],
                    "ignore_regions": [],
                }
            ],
        },
    )

    result = calibrate_visual_stability(
        tmp_path,
        spec.relative_to(tmp_path),
        "materials/alpha/artifacts/offline-clone/frontend/calibration.json",
    )

    assert result["status"] == "calibrated"
    assert result["rows"][0]["source_self_similarity"] == 1.0
    assert result["rows"][0]["recommended_threshold"] == 0.995
    assert "authority" not in result


def test_semantic_scaffold_auto_selects_all_capabilities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from websitebench.workflow import fullstack

    backend = tmp_path / "materials/alpha/backend/model.json"
    _write(backend, {"fixture": True})
    frontend = tmp_path / "materials/alpha/clone/frontend/index.html"
    frontend.parent.mkdir(parents=True, exist_ok=True)
    frontend.write_text("<main>Alpha</main>\n", encoding="utf-8")
    purpose = tmp_path / "materials/alpha/scope/purpose.json"
    _write(purpose, {"purpose": "alpha"})
    source = tmp_path / "materials/alpha/source-current/capture.json"
    _write(source, {"source": True})
    original_loader = fullstack.load_json_document

    def load(path: Path, schema: str):
        if schema == "offline-clone-backend-model.schema.json":
            return {
                "capabilities": [
                    {"id": "account-registration", "priority": "p0"},
                    {
                        "id": "course-enrollment",
                        "priority": "p0",
                        "journey_ids": ["enroll.success"],
                        "invariant_ids": ["enroll.server-authority"],
                        "server_authorities": ["Server owns enrollment truth."],
                        "state_machine": {
                            "states": ["available", "enrolled"],
                            "transitions": [
                                {
                                    "from": "available",
                                    "to": "enrolled",
                                    "trigger": "valid enrollment",
                                }
                            ],
                        },
                    },
                    {"id": "booking-workflow", "priority": "p0"},
                ]
            }
        return original_loader(path, schema)

    monkeypatch.setattr(fullstack, "load_json_document", load)
    result = scaffold_semantic_selection(tmp_path, "alpha")

    assert result["status"] == "passed"
    assert result["automatically_resolved_capability_ids"] == ["booking-workflow"]
    selection = json.loads(
        (
            tmp_path / "materials/alpha/scope/semantic-selection.json"
        ).read_text(encoding="utf-8")
    )
    assert selection["schema_version"] == "offline-clone.semantic-selection.v3"
    by_id = {item["id"]: item for item in selection["capabilities"]}
    source_paths = {
        item["path"] for item in selection["source_scope_subject"]["artifacts"]
    }
    assert "materials/alpha/backend/model.json" in source_paths
    assert by_id["account-registration"]["disposition"] == "full-local-model"
    assert by_id["account-registration"]["mandatory_when_applicable"] is True
    assert by_id["course-enrollment"]["disposition"] == "full-local-model"
    assert by_id["course-enrollment"]["certainty"] == "determinate"
    assert by_id["booking-workflow"]["disposition"] == "full-local-model"
    gate = validate_semantic_selection(
        tmp_path,
        "materials/alpha/scope/semantic-selection.json",
    )
    assert gate["status"] == "passed"
