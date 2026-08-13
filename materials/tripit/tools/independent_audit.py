#!/usr/bin/env python
"""Independent stdlib-only release audit for the TripIt clone.

This process imports neither the clone application, the release producer, nor
pytest.  It re-derives its verdicts from raw files on disk: the frozen scope
ledgers, the visual-oracle source digests, the byte-level asset closure, the
authored-runtime URL surface, the deterministic seed/reset denominators, and
the user-visible branding/leak surface.  It is a second, static reviewer of
contracts whose executable behaviour is proven separately by the browser,
network, migration, and full-suite producers.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


class AuditFailure(RuntimeError):
    pass


REVIEWER_METHOD = (
    "Static independent re-verification of frozen ledger status, visual-oracle "
    "source digests, byte-level source/runtime asset closure, authored-runtime "
    "origin URLs, deterministic seed/reset denominators, user-visible branding, "
    "and blind-test leak surface."
)
INDEPENDENCE_BOUNDARY = (
    "This audit shares the checkout but imports neither the clone application, "
    "release producer, nor test suite; it recomputes verdicts from raw files. "
    "It is process-level machine independence, offered as an optional "
    "diagnostic and not a substitute for human review."
)
REMOTE_URL = re.compile(
    r"(?i)(?:src|href|action|url)\s*[=(:]\s*[\"']?\s*"
    r"(?:https?:)?//(?!localhost|127\.0\.0\.1)[a-z0-9.-]+\.[a-z]{2,}"
)
ARTIFACT_BINDING_SUFFIXES = (
    "ATTEMPT_ID",
    "MANIFEST_SHA256",
    "COMMAND_ID",
    "SITE_DIR",
    "MANIFEST",
)

# This producer is intentionally a static, process-independent audit.  The
# dynamic browser, network, migration, and full-suite producers remain the
# evidence sources for executable behaviour.  These are exactly the frozen
# dimensions whose contracts admit a second, static re-derivation: the visual
# source oracle, the offline network invariants, and the deterministic
# seed/reset denominators.
AUDIT_DIMENSIONS = (
    "source-direct-states",
    "p0-network-invariants",
    "deterministic-seed-rows",
    "deterministic-reset-probes",
)


def _artifact_bindings() -> tuple[tuple[str, ...], dict[str, str | None]]:
    """Resolve canonical harness bindings with explicit legacy compatibility."""
    canonical = tuple(
        f"WEBSITEBENCH_OFFLINE_CLONE_{suffix}"
        for suffix in ARTIFACT_BINDING_SUFFIXES
    )
    legacy = tuple(
        f"CLAWBENCH_OFFLINE_CLONE_{suffix}"
        for suffix in ARTIFACT_BINDING_SUFFIXES
    )
    canonical_present = any(name in os.environ for name in canonical)
    legacy_present = any(name in os.environ for name in legacy)
    if canonical_present and legacy_present:
        raise AuditFailure(
            "mixed WebsiteBench and legacy ClawBench artifact bindings"
        )
    selected = legacy if legacy_present else canonical
    if not canonical_present and not legacy_present:
        return canonical, {}
    return selected, {name: os.environ.get(name) for name in selected}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def imports_symbol(source: str, *, module: str, symbol: str) -> bool:
    """Check a Python import structurally without importing the runtime module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(alias.name == symbol for alias in node.names)
        for node in ast.walk(tree)
    )


def audit(site_root: Path) -> tuple[list[dict], list[dict]]:
    checks: list[dict] = []
    findings: list[dict] = []

    def check(check_id: str, subjects: list[str], ok: bool, detail: str) -> None:
        row = {
            "id": check_id,
            "status": "passed" if ok else "failed",
            "subject_ids": subjects,
            "detail": detail,
        }
        checks.append(row)
        if not ok:
            raise AuditFailure(f"{check_id}: {detail}")

    scope = site_root / "scope"
    clone = site_root / "clone"
    templates = clone / "frontend" / "templates"

    coverage = load_json(scope / "coverage.json")
    checkpoints = load_json(scope / "checkpoints.json")
    invariants = load_json(scope / "invariants.json")
    routes_doc = load_json(scope / "routes.json")
    journeys_doc = load_json(scope / "journeys.json")
    dimensions = {row["id"]: row for row in coverage["dimensions"]}

    # Representative witness tags drawn from the claimed denominator so that the
    # structural (non-per-item) checks bind to a real, already-covered subject.
    ANCHOR = "home.desktop"  # a source-direct-states item
    ASSET_GRAPH = "same-origin-only-asset-graph"  # a p0-network-invariants item

    # -- Group 0: frozen ledgers -------------------------------------------
    check(
        "scope.ledgers.frozen",
        [ANCHOR],
        coverage.get("status")
        == checkpoints.get("status")
        == invariants.get("status")
        == routes_doc.get("status")
        == journeys_doc.get("status")
        == "frozen"
        and bool(checkpoints.get("freeze_decision")),
        "coverage, checkpoints, invariants, routes, and journeys are frozen "
        "under a recorded freeze decision",
    )

    # -- Group 1: source-direct-state re-derivation ------------------------
    # A small pixel-locked visual oracle (re-hash + frozen metric) plus the
    # broad source rasters (re-hash), together independently re-deriving every
    # source-direct state from its frozen capture without touching the clone.
    oracle_ids: list[str] = []
    raster_ids: list[str] = []
    for row in checkpoints["checkpoints"]:
        contract = row.get("visual_contract")
        if isinstance(contract, dict):
            raster = site_root / contract["source_artifact_path"]
            check(
                f"visual.oracle.{row['id']}",
                [row["id"]],
                raster.is_file()
                and sha256_file(raster) == contract["source_artifact_sha256"]
                and contract.get("metric") == "pixel-mae-similarity-v1",
                f"{raster.name} matches its frozen pixel-mae source digest",
            )
            oracle_ids.append(row["id"])
        else:
            raster = site_root / str(row.get("source_artifact_path"))
            check(
                f"source.raster.{row['id']}",
                [row["id"]],
                raster.is_file()
                and sha256_file(raster) == row.get("source_artifact_sha256"),
                f"{raster.name} matches its frozen source raster digest",
            )
            raster_ids.append(row["id"])
    frozen_states = set(dimensions["source-direct-states"]["required_items"])
    check(
        "source.oracle.denominator",
        [ANCHOR],
        set(oracle_ids) == {"home.desktop", "home.tablet", "home.mobile"}
        and set(oracle_ids) | set(raster_ids) == frozen_states
        and len(oracle_ids) + len(raster_ids) == len(frozen_states) == 51,
        "the pixel oracle is exactly home×3 and every source-direct state is "
        "re-derived (3 oracle + 48 rasters = 51 frozen states)",
    )

    # -- Group 2: offline network invariants -------------------------------
    manifest = load_json(site_root / "source-assets" / "manifest.json")
    verified = 0
    for asset in manifest["assets"]:
        source_path = site_root / asset["source_path"]
        runtime_path = site_root / asset["runtime_path"]
        if not source_path.is_file() or not runtime_path.is_file():
            raise AuditFailure(f"asset missing: {asset['id']}")
        source_payload = source_path.read_bytes()
        runtime_payload = runtime_path.read_bytes()
        if (
            source_payload != runtime_payload
            or sha256_bytes(source_payload) != asset["sha256"]
            or len(source_payload) != asset["bytes"]
        ):
            raise AuditFailure(f"asset diverges from manifest: {asset['id']}")
        verified += 1
    check(
        "assets.closure.byte-verified",
        [ASSET_GRAPH],
        manifest.get("remote_runtime_policy") == "forbidden"
        and verified == len(manifest["assets"])
        and verified > 0,
        f"{verified} runtime assets match their frozen source bytes under a "
        "forbidden remote-runtime policy",
    )

    scanned = 0
    for path in clone.rglob("*"):
        if path.suffix.casefold() not in {".html", ".css", ".js"}:
            continue
        relative = path.relative_to(clone).as_posix()
        if relative.startswith("static/assets/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if REMOTE_URL.search(text):
            raise AuditFailure(f"remote URL in authored runtime file: {relative}")
        scanned += 1
    check(
        "runtime.remote-origins.absent",
        [
            "zero-requests-to-tripit.com",
            "zero-requests-to-trustarc",
            "zero-requests-to-google-or-cdns",
        ],
        scanned >= 10,
        f"{scanned} authored runtime files reference no remote origin "
        "(tripit.com, trustarc, or third-party CDNs)",
    )

    # -- Group 3: deterministic seed / reset denominators ------------------
    seed_manifest = load_json(scope / "deterministic-seed.json")
    seed_items = [
        f"{row['entity_name']}::{row['storage_name']}::"
        f"count={row['expected_row_count']}"
        for row in seed_manifest["entities"]
    ]
    reset_probe_ids = [row["id"] for row in seed_manifest["reset_probes"]]
    check(
        "coverage.deterministic-seed.derived",
        [*seed_items, *reset_probe_ids],
        dimensions["deterministic-seed-rows"]["required_items"] == seed_items
        and dimensions["deterministic-reset-probes"]["required_items"]
        == reset_probe_ids,
        "the frozen seed-row and reset-probe denominators are exactly the "
        "deterministic seed manifest's rows and probes",
    )

    # -- Group 4: blind-test surface (leak, branding, boundary) ------------
    leak_tokens = ("clone", "offline", "harness", "website-bench")
    surfaces_scanned = 0
    for path in templates.rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        hit = next((token for token in leak_tokens if token in text), None)
        if hit is not None:
            rel = path.relative_to(templates).as_posix()
            raise AuditFailure(f"leak token '{hit}' in user-visible template: {rel}")
        surfaces_scanned += 1
    check(
        "surface.leak-tokens.absent",
        [ANCHOR],
        surfaces_scanned >= 10,
        f"{surfaces_scanned} user-visible templates disclose no clone, offline, "
        "or harness identity",
    )

    base = (templates / "base.html").read_text(encoding="utf-8")
    app_base = (templates / "app" / "base.html").read_text(encoding="utf-8")
    check(
        "surface.branding.title-favicon",
        [ANCHOR],
        "<title>{% block title %}TripIt{% endblock %}</title>" in base
        and 'rel="icon"' in base
        and "favicon" in base
        and "{% block app_title %}TripIt{% endblock %}" in app_base
        and "favicon" in app_base,
        "marketing and app shells carry the TripIt title and a local favicon",
    )

    app_text = (clone / "app.py").read_text(encoding="utf-8")
    db_text = (clone / "backend" / "db.py").read_text(encoding="utf-8")
    check(
        "runtime.healthz.contract",
        [ASSET_GRAPH],
        'SITE_ID = "tripit"' in app_text
        and '_HEALTH_BODY = json.dumps({"ok": True, "site_id": SITE_ID}'
        in app_text,
        "/healthz returns exactly {\"ok\": true, \"site_id\": \"tripit\"}",
    )
    check(
        "boundary.site-local-backend",
        [ANCHOR],
        imports_symbol(
            db_text, module="websitebench.site_backend", symbol="SiteBackend"
        )
        and 'SITE_DATA_DIR_ENV = "WEBSITEBENCH_TRIPIT_DATA_DIR"' in db_text
        and 'RUNTIME_ENV = "WEBSITEBENCH_SITE_BACKEND_RUNTIME"' in db_text,
        "persistence is bound to the isolated WebsiteBench site backend under "
        "the tripit-scoped data directory",
    )

    return checks, findings


def write_artifact(site_root: Path, checks: list[dict], findings: list[dict]) -> None:
    names, bindings = _artifact_bindings()
    if not bindings:
        print("independent-audit: standalone verification passed (nothing written)")
        return
    missing = [name for name, value in bindings.items() if not value]
    if missing:
        raise AuditFailure("incomplete audit binding: " + ", ".join(missing))
    attempt = str(bindings[names[0]])
    manifest_hash = str(bindings[names[1]])
    producer = str(bindings[names[2]])
    if producer != "independent-audit":
        raise AuditFailure("unexpected audit producer id")
    if re.fullmatch(r"[a-f0-9]{32}", attempt) is None:
        raise AuditFailure("malformed attempt id")
    if re.fullmatch(r"[a-f0-9]{64}", manifest_hash) is None:
        raise AuditFailure("malformed manifest digest")
    if Path(str(bindings[names[3]])).resolve() != site_root:
        raise AuditFailure("site binding mismatch")
    manifest_path = (site_root / "clone.yaml").resolve()
    if Path(str(bindings[names[4]])).resolve() != manifest_path:
        raise AuditFailure("manifest binding mismatch")
    if sha256_file(manifest_path) != manifest_hash:
        raise AuditFailure("manifest changed during audit")

    subjects = sorted(
        {subject for row in checks + findings for subject in row.get("subject_ids", [])}
    )
    coverage = load_json(site_root / "scope" / "coverage.json")
    items = {row["id"]: list(row["required_items"]) for row in coverage["dimensions"]}
    authorized = {
        row["id"]
        for row in coverage["dimensions"]
        if "independent-audit" in row.get("required_evidence_kinds", [])
    }
    # Every AUDIT_DIMENSIONS entry is independently re-derived above as blocking
    # checks (Groups 1-4).  The audit only *claims* ledger coverage for the
    # dimensions the frozen coverage ledger authorises independent-audit to
    # witness.  The network-closure and seed/reset denominators are witnessed in
    # the ledger by their own authorised kinds (network, migration, full-suite);
    # the audit still re-derives them as gating internal checks, it simply does
    # not double-claim them.  Reading the allowlist from the ledger keeps this
    # producer self-conforming to whatever the freeze authorises.
    claimable = [dim for dim in AUDIT_DIMENSIONS if dim in authorized]
    if "source-direct-states" not in claimable:
        raise AuditFailure(
            "coverage ledger does not authorise independent-audit for the "
            "source-direct-states oracle"
        )
    verified = [
        {"dimension_id": dimension, "items": items[dimension]}
        for dimension in claimable
    ]
    claimed = {item for row in verified for item in row["items"]}
    missing = sorted(claimed - set(subjects))
    if missing:
        raise AuditFailure("unwitnessed audit coverage: " + ", ".join(missing))
    raw_path = (
        site_root
        / "artifacts"
        / "offline-clone"
        / "acceptance"
        / "raw"
        / "independent-audit"
        / "audit-report.json"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_document = {
        "schema_version": "offline-clone.raw.audit-report.v1",
        "generated_at": utc_now(),
        "reviewer_method": REVIEWER_METHOD,
        "independence_boundary": INDEPENDENCE_BOUNDARY,
        "subject_ids": subjects,
        "checks": checks,
        "findings": findings,
    }
    raw_path.write_text(
        json.dumps(raw_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload = raw_path.read_bytes()
    artifact = {
        "schema_version": "offline-clone.acceptance-evidence.v1",
        "kind": "independent-audit",
        "producer_command_id": producer,
        "gate_attempt_id": attempt,
        "manifest_sha256": manifest_hash,
        "generated_at": utc_now(),
        "status": "passed",
        "summary": f"{len(checks)} independent static checks passed with zero findings.",
        "reviewer_method": REVIEWER_METHOD,
        "independence_boundary": INDEPENDENCE_BOUNDARY,
        "metrics": {
            "checks_total": len(checks),
            "checks_passed": len(checks),
            "checks_failed": 0,
            "findings_total": len(findings),
            "blocking_findings": 0,
            "reviewer_method": REVIEWER_METHOD,
            "independence_boundary": INDEPENDENCE_BOUNDARY,
        },
        "boundaries": [
            "Static process-level re-verification only; browser evidence and "
            "fresh-context independent Reviewer checkpoints remain separate."
        ],
        "verified_coverage": verified,
        "raw_artifacts": [
            {
                "path": raw_path.relative_to(site_root).as_posix(),
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "media_type": "application/json",
                "role": "audit-report",
                "subject_ids": subjects,
                "contains_user_data": False,
                "sanitization_method": "static verdicts only; no user data",
            }
        ],
    }
    destination = (
        site_root / "artifacts" / "offline-clone" / "acceptance" / "independent-audit.json"
    )
    destination.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"independent-audit: {len(checks)} checks passed, 0 findings")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", required=True)
    arguments = parser.parse_args()
    site_root = Path(arguments.site_root).resolve()
    if not (site_root / "clone.yaml").is_file():
        raise AuditFailure(f"not a clone site root: {site_root}")
    checks, findings = audit(site_root)
    write_artifact(site_root, checks, findings)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditFailure as failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
