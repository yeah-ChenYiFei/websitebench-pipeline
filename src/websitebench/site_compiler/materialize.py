"""Atomic materialization of a machine-resolved scope workspace."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from websitebench.offline_clone.manifest import (
    initialize_site,
    load_manifest,
    resolve_inside,
)

from .canonical import canonical_json_bytes
from .compile import COMPILER_VERSION, CompilationResult, write_compilation
from .diagnostics import SiteCompilerError
from .schema import validate_value

PENDING_ASSET_CREATED_AT = "1970-01-01T00:00:00+00:00"
SCOPE_STAGE = "scope"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _rewrite_clone_manifest(root: Path, result: CompilationResult) -> None:
    manifest_path = root / "clone.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    site = result.plan["site_ir"]["site"]
    baseline = manifest["source"]["baseline"]
    baseline["locale"] = site["locale_defaults"]["locale"]
    baseline["currency"] = site["locale_defaults"]["currency"]
    baseline["timezone"] = site["locale_defaults"]["timezone"]
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def _emitted_file(
    root: Path,
    relative: str,
    *,
    role: str,
) -> dict[str, str]:
    path = root / relative
    return {"path": relative, "role": role, "bytes": path.stat().st_size}


def _build_site_tree(
    result: CompilationResult,
    root: Path,
) -> None:
    ir = result.plan["site_ir"]
    site = ir["site"]
    site_id = site["site_id"]
    initialize_site(
        root,
        site_id=site_id,
        display_name=site["display_name"],
        source_url=site["source_origins"],
        created_at=PENDING_ASSET_CREATED_AT,
    )
    for relative in ("source-capture", "source-current"):
        (root / relative).mkdir(parents=True, exist_ok=False)

    _write_json(root / "backend/model.json", ir["backend_model_seed"])
    compiler_root = root / "artifacts/site-compiler"
    write_compilation(result, output_dir=compiler_root)
    for filename, value in result.inputs.items():
        _write_json(compiler_root / "inputs" / filename, value)
    _write_json(
        compiler_root / "frontend-obligations.json",
        {
            "schema_version": "offline-clone.frontend-obligations.v1",
            "site_id": site_id,
            "status": "planned-inferred",
            "evidence_tier": "inferred",
            "confirmation_status": "machine-resolved",
            "frontend_contract": ir["frontend_contract"],
        },
    )
    _write_json(
        compiler_root / "backend-obligations.json",
        {
            "schema_version": "offline-clone.backend-obligations.v1",
            "site_id": site_id,
            "status": "planned-inferred",
            "evidence_tier": "inferred",
            "confirmation_status": "machine-resolved",
            "runtime_contract": ir["backend_runtime_contract"],
            "capability_provenance": ir["capability_provenance"],
        },
    )
    _rewrite_clone_manifest(root, result)

    emitted = [
        _emitted_file(root, "clone.yaml", role="harness"),
        _emitted_file(root, "backend/model.json", role="planned-obligation"),
        _emitted_file(root, "scope/purpose.json", role="harness"),
        _emitted_file(root, "scope/invariants.json", role="harness"),
        _emitted_file(root, "scope/routes.json", role="harness"),
        _emitted_file(root, "scope/journeys.json", role="harness"),
        _emitted_file(root, "scope/checkpoints.json", role="harness"),
        _emitted_file(root, "scope/coverage.json", role="harness"),
        _emitted_file(root, "scope/claims.jsonl", role="harness"),
        _emitted_file(root, "source-assets/manifest.json", role="harness"),
        _emitted_file(
            root,
            f"artifacts/site-compiler/{site_id}.compiled.json",
            role="compiler-identity",
        ),
        _emitted_file(
            root,
            f"artifacts/site-compiler/{site_id}.explain.json",
            role="compiler-identity",
        ),
        _emitted_file(
            root,
            "artifacts/site-compiler/inputs/site-profile.json",
            role="compiler-identity",
        ),
        _emitted_file(
            root,
            "artifacts/site-compiler/inputs/inventory-row.json",
            role="compiler-identity",
        ),
        _emitted_file(
            root,
            "artifacts/site-compiler/inputs/resolved-packs.json",
            role="compiler-identity",
        ),
        _emitted_file(
            root,
            "artifacts/site-compiler/frontend-obligations.json",
            role="planned-obligation",
        ),
        _emitted_file(
            root,
            "artifacts/site-compiler/backend-obligations.json",
            role="planned-obligation",
        ),
    ]
    record = {
        "schema_version": "offline-clone.materialization.v3",
        "compiler_version": COMPILER_VERSION,
        "site_id": site_id,
        "stage": "machine-scope",
        "status": "ready-for-implementation",
        "evidence_boundary": {
            "classification": "machine-inferred",
            "generated_source_claims": "forbidden",
            "candidate_as_source_truth": "forbidden",
        },
        "emitted_files": emitted,
        "forbidden_at_this_stage": [
            "captured-source-contract",
            "source-direct-claims",
            "persistent-business-runtime",
            "vendored-auth-runtime",
            "machine-fidelity-validation",
            "harbor-release-evidence",
        ],
    }
    record_problems = validate_value(
        record,
        "offline-clone-materialization-v3.schema.json",
        location="materialization record",
    )
    if record_problems:
        raise SiteCompilerError(record_problems)
    _write_json(compiler_root / "materialization.json", record)

    # The regular harness must be able to consume the materialized workspace.
    loaded = load_manifest(root)
    if loaded.data["site_id"] != site_id:
        raise SiteCompilerError("materialized harness resolved a different site_id")
    if any((root / "clone/backend").rglob("*")):
        raise SiteCompilerError("scope materialization created persistent backend files")
    if (root / "clone/clawbench").exists():
        raise SiteCompilerError("scope materialization vendored runtime")
    if list(root.rglob("*.sqlite*")):
        raise SiteCompilerError("scope materialization created a persistent database")


def _new_temporary_directory(parent: Path, site_id: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(prefix=f".{site_id}.materialize-", dir=parent)
    ).resolve()


def _ensure_new_destination(path: Path, label: str) -> Path:
    requested = path.absolute()
    if requested.exists() or requested.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing {label}: {requested}")
    return requested


def materialize_compilation(
    result: CompilationResult,
    site_dir: Path,
    *,
    stage: str = SCOPE_STAGE,
) -> dict[str, Any]:
    """Atomically create one scope draft from a compiled profile."""

    if stage != SCOPE_STAGE:
        raise SiteCompilerError(
            "only stage='scope' is implemented by the scaffold materializer"
        )
    if result.plan["target"] != "scope":
        raise SiteCompilerError(
            "scope materialization requires a compilation with target='scope'"
        )
    blockers = result.plan["site_ir"]["blockers"]
    if blockers:
        blocker_ids = ", ".join(item["id"] for item in blockers)
        raise SiteCompilerError(
            f"profile is blocked and cannot be materialized: {blocker_ids}"
        )
    destination = _ensure_new_destination(Path(site_dir), "site directory")
    site_id = result.plan["site_ir"]["site"]["site_id"]
    site_temp = _new_temporary_directory(destination.parent, site_id)
    destination_owned = False
    completed = False
    try:
        _build_site_tree(result, site_temp)
        os.replace(site_temp, destination)
        destination_owned = True
        response = {
            "status": "materialized",
            "stage": "machine-scope",
            "site_id": site_id,
            "site_dir": str(destination),
        }
        completed = True
        return response
    finally:
        if site_temp.exists():
            shutil.rmtree(site_temp)
        if destination_owned and not completed and destination.exists():
            # Only rollback a directory created by this call after its atomic
            # rename. A destination introduced by a concurrent writer between
            # the preflight check and os.replace is never ours to remove.
            shutil.rmtree(destination)


def check_materialization(
    result: CompilationResult,
    site_dir: Path,
) -> dict[str, Any]:
    """Rebuild expected compiler outputs and compare their files directly."""

    root = Path(site_dir).resolve()
    if not root.is_dir() or root.is_symlink():
        raise SiteCompilerError(f"materialized site directory is unavailable: {root}")

    site_id = result.plan["site_ir"]["site"]["site_id"]
    expected_root = _new_temporary_directory(root.parent, f"{site_id}-check")
    try:
        _build_site_tree(result, expected_root)
        expected_record_path = (
            expected_root / "artifacts/site-compiler/materialization.json"
        )
        expected_record = json.loads(expected_record_path.read_text(encoding="utf-8"))
        expected_paths = {
            item["path"] for item in expected_record["emitted_files"]
        }
        expected_paths.add("artifacts/site-compiler/materialization.json")

        compiler_root = root / "artifacts/site-compiler"
        actual_compiler_paths = {
            path.relative_to(root).as_posix()
            for path in compiler_root.rglob("*")
            if path.is_file() or path.is_symlink()
        } if compiler_root.is_dir() else set()
        expected_compiler_paths = {
            relative
            for relative in expected_paths
            if relative.startswith("artifacts/site-compiler/")
        }
        extra = sorted(actual_compiler_paths - expected_compiler_paths)
        if extra:
            raise SiteCompilerError(
                "materialized compiler output has unexpected files: "
                + ", ".join(extra)
            )

        for relative in sorted(expected_paths):
            expected = resolve_inside(expected_root, relative, must_exist=True)
            try:
                actual = resolve_inside(root, relative, must_exist=True)
            except ValueError as exc:
                raise SiteCompilerError(
                    f"materialized compiler output is missing: {relative}"
                ) from exc
            if not actual.is_file() or actual.is_symlink():
                raise SiteCompilerError(
                    f"materialized compiler output is not a regular file: {relative}"
                )
            if actual.read_bytes() != expected.read_bytes():
                raise SiteCompilerError(
                    f"materialized compiler output drifted: {relative}"
                )
    finally:
        shutil.rmtree(expected_root, ignore_errors=True)

    load_manifest(root)
    return {
        "status": "current",
        "stage": "machine-scope",
        "site_id": site_id,
        "site_dir": str(root),
    }
