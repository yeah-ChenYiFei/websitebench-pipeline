"""Scaffold and package reviewable offline-clone contributions."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from websitebench.site_backend import load_runtime

from .backend_scaffold import scaffold_site_backend
from .diagnostics import DIAGNOSTIC_SECTIONS, verify
from .manifest import initialize_site, load_manifest, utc_now
from .secrets import sensitive_findings


CONTRIBUTION_REPORT_SCHEMA = "offline-clone.contribution-report.v1"
BUNDLE_SCHEMA = "offline-clone.contribution-bundle.v1"
BACKEND_SCOPE_SCHEMA = "offline-clone.contribution-backend-scope.v1"
BACKEND_CAPABILITIES = (
    "accounts",
    "password-recovery",
    "transactional-mail",
    "orders",
    "checkout",
    "payments",
    "database",
)
_BLOCKED_PARTS = {
    ".clone-harness",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "artifacts",
    "data",
    "raw",
    "raw-captures",
}
_BLOCKED_SUFFIXES = {".db", ".pem", ".pyc", ".pyo", ".sqlite", ".sqlite3"}
_BLOCKED_NAMES = {
    ".env",
    ".env.local",
    "cookies.json",
    "storage-state.json",
    "storage_state.json",
}
_SECRET_FINDINGS = frozenset({"private_key", "bearer_token", "jwt", "provider_key"})


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _scope_documents(site_id: str, display_name: str) -> dict[str, Any]:
    journey = "home-mainline"
    invariant = "home-reachable"
    return {
        "scope/purpose.json": {
            "schema_version": "offline-clone.purpose.v1",
            "status": "draft",
            "purpose_id": "public-home",
            "statement": f"Render the scoped public home page for {display_name} offline.",
            "primary_actor_ids": ["visitor"],
            "mainline_journey_ids": [journey],
            "out_of_scope": [],
        },
        "scope/invariants.json": {
            "schema_version": "offline-clone.invariants.v1",
            "status": "draft",
            "invariants": [
                {
                    "id": invariant,
                    "statement": "The public home route remains reachable without remote requests.",
                    "priority": "p0",
                    "journey_ids": [journey],
                    "positive_test_refs": ["clone/tests/test_smoke.py::test_home"],
                    "negative_test_refs": [
                        "clone/tests/test_smoke.py::test_unknown_route"
                    ],
                    "coverage_dimension_ids": ["public-home"],
                }
            ],
        },
        "scope/routes.json": {
            "schema_version": "offline-clone.routes.v1",
            "routes": [
                {
                    "id": "home",
                    "route_pattern": "/",
                    "priority": "p0",
                    "purpose_edge": "primary",
                    "local_destination": True,
                    "states": ["loaded"],
                }
            ],
        },
        "scope/journeys.json": {
            "schema_version": "offline-clone.journeys.v1",
            "journeys": [
                {
                    "id": journey,
                    "kind": "success",
                    "priority": "p0",
                    "status": "draft",
                    "actor": "visitor",
                    "steps": [
                        "Open the public home route and inspect its local response."
                    ],
                }
            ],
        },
        "scope/checkpoints.json": {
            "schema_version": "offline-clone.checkpoints.v1",
            "status": "draft",
            "viewports": {"desktop": {"width": 1280, "height": 800}},
            "checkpoints": [
                {
                    "id": "home.loaded.desktop",
                    "route_id": "home",
                    "state": "loaded",
                    "viewport": "desktop",
                    "priority": "p0",
                    "evidence_kind": "unavailable",
                    "acceptance_eligible": False,
                    "verification_kind": "scaffold-local-diagnostic",
                }
            ],
        },
        "scope/coverage.json": {
            "schema_version": "offline-clone.coverage.v1",
            "status": "draft",
            "dimensions": [
                {
                    "id": "public-home",
                    "label": "Public home route-state",
                    "unit": "route-state",
                    "category": "reachability",
                    "required_evidence_kinds": ["browser"],
                    "required_items": ["home.loaded.desktop"],
                    "satisfied_items": [],
                }
            ],
        },
        "scope/verify.json": {
            "schema_version": "offline-clone.verify-driver.v1",
            "site_id": site_id,
            "routes": {"home": "/"},
            "deferred": {},
            "prepare": [],
            "states": {"home.loaded": []},
            "boot": {
                "argv": [
                    "{python}",
                    "-m",
                    "uvicorn",
                    "app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "{port}",
                    "--log-level",
                    "warning",
                ],
                "cwd": "clone",
                "env": {},
            },
        },
    }


def _app_source(site_id: str, display_name: str) -> str:
    title = json.dumps(display_name, ensure_ascii=False)
    identity = json.dumps(site_id)
    return f'''"""Minimal WebsiteBench offline clone application."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


SITE_ID = {identity}
DISPLAY_NAME = {title}
app = FastAPI(title=DISPLAY_NAME)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {{"ok": True, "site_id": SITE_ID}}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + DISPLAY_NAME + """</title><style>body{{font:16px system-ui;margin:0;background:#f6f7f9;color:#18202a}}main{{max-width:54rem;margin:12vh auto;padding:3rem;background:white;border-radius:1rem;box-shadow:0 1rem 3rem #18202a18}}h1{{font-size:clamp(2rem,6vw,4rem);margin:0 0 1rem}}p{{line-height:1.6}}</style></head>
<body><main><p>WebsiteBench offline contribution scaffold</p><h1>""" + DISPLAY_NAME + """</h1><p>This local page is ready for source-grounded implementation.</p></main></body></html>"""
'''


def _smoke_test_source() -> str:
    return """from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "WebsiteBench offline contribution scaffold" in response.text


def test_unknown_route() -> None:
    assert client.get("/not-in-scope").status_code == 404
"""


def _dispatcher(site_id: str) -> str:
    return f"""name: diagnostics ({site_id})
on:
  pull_request:
    paths:
      - materials/{site_id}/**
      - .github/workflows/tests-{site_id}.yml
      - .github/workflows/clone-diagnostics.yml
  push:
    paths:
      - materials/{site_id}/**
      - .github/workflows/tests-{site_id}.yml
      - .github/workflows/clone-diagnostics.yml
permissions:
  contents: read
concurrency:
  group: diagnostics-{site_id}-${{{{ github.ref }}}}
  cancel-in-progress: true
jobs:
  diagnostics:
    uses: ./.github/workflows/clone-diagnostics.yml
    with:
      site: {site_id}
"""


def initialize_contribution(
    repo: Path,
    *,
    site_id: str,
    display_name: str,
    source_urls: list[str],
    backend_profile: str = "full",
) -> dict[str, Any]:
    """Create one non-deployable contribution without overwriting anything."""

    if backend_profile not in {"full", "none"}:
        raise ValueError("backend_profile must be 'full' or 'none'")
    repository = repo.resolve()
    site = repository / "materials" / site_id
    dispatcher = repository / ".github" / "workflows" / f"tests-{site_id}.yml"
    if site.exists():
        raise FileExistsError(f"refusing to overwrite contribution site: {site}")
    if dispatcher.exists():
        raise FileExistsError(
            f"refusing to overwrite contribution workflow: {dispatcher}"
        )

    initialize_site(
        site,
        site_id=site_id,
        display_name=display_name,
        source_url=source_urls,
    )
    for relative, value in _scope_documents(site_id, display_name).items():
        _write_json(site / relative, value)
    _write_json(
        site / "source-assets" / "manifest.json",
        {
            "schema_version": "offline-clone.assets.v1",
            "snapshot_id": f"{site_id}-scaffold",
            "created_at": utc_now(),
            "remote_runtime_policy": "forbidden",
            "closure_status": "no-assets",
            "no_assets_reason": (
                "The initial text-only scaffold declares no downloaded source assets."
            ),
            "assets": [],
        },
    )
    applicability = "in-scope" if backend_profile == "full" else "not-applicable"
    _write_json(
        site / "scope" / "backend-capabilities.json",
        {
            "schema_version": BACKEND_SCOPE_SCHEMA,
            "site_id": site_id,
            "backend_profile": backend_profile,
            "runtime_required": backend_profile == "full",
            "capabilities": [
                {
                    "id": capability,
                    "applicability": applicability,
                    "rationale": (
                        "Included by the contribution scaffold's conservative full profile."
                        if backend_profile == "full"
                        else "The contributor explicitly selected a frontend-only clone."
                    ),
                }
                for capability in BACKEND_CAPABILITIES
            ],
        },
    )
    clone = site / "clone"
    (clone / "tests").mkdir(exist_ok=True)
    (clone / "app.py").write_text(_app_source(site_id, display_name), encoding="utf-8")
    (clone / "requirements.txt").write_text(
        "fastapi>=0.115\nuvicorn>=0.30\n", encoding="utf-8"
    )
    (clone / "tests" / "test_smoke.py").write_text(
        _smoke_test_source(), encoding="utf-8"
    )
    (clone / "tests" / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n",
        encoding="utf-8",
    )
    dispatcher.parent.mkdir(parents=True, exist_ok=True)
    dispatcher.write_text(_dispatcher(site_id), encoding="utf-8")
    backend: dict[str, Any] | None = None
    if backend_profile == "full":
        backend = scaffold_site_backend(site)
    # Re-load every declared contract and the verify driver before handing
    # the scaffold back to its contributor.
    load_manifest(site)
    return {
        "schema_version": "offline-clone.contribution-init.v1",
        "site_id": site_id,
        "site": str(site),
        "backend_profile": backend_profile,
        "backend": backend,
        "diagnostic_workflow": str(dispatcher),
        "public_deployment_generated": False,
        "harbor_instance_generated": False,
    }


def _blocked(relative: PurePosixPath) -> bool:
    lowered = tuple(part.casefold() for part in relative.parts)
    return (
        any(part in _BLOCKED_PARTS for part in lowered)
        or relative.name.casefold() in _BLOCKED_NAMES
        or relative.suffix.casefold() in _BLOCKED_SUFFIXES
        or relative.name.casefold().startswith(".env.")
    )


def _declared_asset_paths(site: Path) -> tuple[set[str], set[str]]:
    value = json.loads((site / "source-assets" / "manifest.json").read_text("utf-8"))
    source = {str(row["source_path"]) for row in value.get("assets", [])}
    runtime = {str(row["runtime_path"]) for row in value.get("assets", [])}
    return source, runtime


def _bundle_files(site: Path) -> Iterable[tuple[str, Path]]:
    source_assets, runtime_assets = _declared_asset_paths(site)
    fixed = {
        "clone.yaml",
        "backend/model.json",
        "backend/runtime.json",
        "source-assets/manifest.json",
    }
    for path in sorted(site.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"handoff bundle refuses symbolic link: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(site).as_posix()
        posix = PurePosixPath(relative)
        if _blocked(posix):
            continue
        allowed = (
            relative in fixed
            or relative in source_assets
            or relative.startswith("scope/")
            or relative.startswith("clone/")
        )
        if not allowed:
            continue
        if (
            relative.startswith("source-assets/")
            and relative not in source_assets
            and relative != "source-assets/manifest.json"
        ):
            continue
        if (
            relative.startswith("clone/static/assets/")
            and relative not in runtime_assets
        ):
            continue
        yield relative, path


def _safe_payload(relative: str, payload: bytes) -> None:
    if len(payload) > 4 * 1024 * 1024:
        return
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return
    findings = _SECRET_FINDINGS.intersection(sensitive_findings(text))
    if findings:
        raise ValueError(
            f"handoff bundle refuses {relative}: sensitive value pattern(s) "
            f"{', '.join(sorted(findings))}"
        )


def _zip_entry(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, payload)


def _backend_summary(site: Path) -> dict[str, Any]:
    runtime_path = site / "backend" / "runtime.json"
    if not runtime_path.is_file():
        return {
            "runtime": None,
            "site_id": load_manifest(site).data["site_id"],
            "database_identity": None,
            "volume_identity": None,
            "mail_purposes": [],
            "payment_profile": "not-applicable",
            "deployment_profiles": [],
        }
    runtime = load_runtime(runtime_path)
    raw = runtime.raw
    return {
        "runtime": "backend/runtime.json",
        "site_id": runtime.site_id,
        "database_identity": {
            "data_dir": raw["database"]["data_dir"],
            "filename": runtime.database_filename,
        },
        "volume_identity": f"websitebench-{runtime.site_id}-data",
        "mail_purposes": sorted(runtime.mail.get("purposes", {})),
        "payment_profile": runtime.payments["default_adapter"],
        "deployment_profiles": sorted(raw["deployment"]["profiles"]),
    }


def contribution_report(
    site: Path,
    *,
    output: Path,
    bundle_output: Path,
) -> dict[str, Any]:
    """Run diagnostics, summarize backend identity, and write a stable handoff ZIP."""

    root = site.resolve()
    manifest = load_manifest(root)
    diagnostic = verify(root, DIAGNOSTIC_SECTIONS)
    diagnostic_payload = _json_bytes(diagnostic)
    payloads: dict[str, bytes] = {}
    for relative, path in _bundle_files(root):
        payload = path.read_bytes()
        _safe_payload(relative, payload)
        payloads[relative] = payload
    payloads["diagnostics/diagnostic-report.json"] = diagnostic_payload
    entries = [
        {
            "path": relative,
            "bytes": len(payload),
        }
        for relative, payload in sorted(payloads.items())
    ]
    bundle_manifest = {
        "schema_version": BUNDLE_SCHEMA,
        "site_id": manifest.data["site_id"],
        "files": entries,
    }
    manifest_payload = _json_bytes(bundle_manifest)
    bundle_output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_output, "w") as archive:
        for relative, payload in sorted(payloads.items()):
            _zip_entry(archive, relative, payload)
        _zip_entry(archive, "BUNDLE-MANIFEST.json", manifest_payload)

    coverage_gaps: list[dict[str, Any]] = []
    for section_name, section in diagnostic.get("sections", {}).items():
        for reason in section.get("execution", {}).get("incomplete_reasons", []):
            coverage_gaps.append(
                {"section": section_name, "kind": "incomplete", "detail": reason}
            )
        for key, count in section.get("coverage", {}).items():
            if count and any(
                marker in key
                for marker in (
                    "deferred",
                    "excluded",
                    "undeclared",
                    "unvisited",
                    "without_source",
                    "needs_state_recipe",
                )
            ):
                coverage_gaps.append(
                    {
                        "section": section_name,
                        "kind": key,
                        "count": count,
                    }
                )
    report = {
        "schema_version": CONTRIBUTION_REPORT_SCHEMA,
        "authority": "diagnostic-only",
        "qualification": "maintainer-judgment-required",
        "site_id": manifest.data["site_id"],
        "generated_at": utc_now(),
        "diagnostic": diagnostic,
        "coverage_gaps": coverage_gaps,
        "backend": _backend_summary(root),
        "bundle": {
            "path": str(bundle_output),
            "payload_files": entries,
        },
    }
    _write_json(output, report)
    return report
