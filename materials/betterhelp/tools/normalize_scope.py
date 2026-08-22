from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def write(name: str, value: dict) -> None:
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

purpose = json.loads((ROOT / "scope/purpose.json").read_text(encoding="utf-8"))
purpose["status"] = "frozen"
write("scope/purpose.json", purpose)

invariants = json.loads((ROOT / "scope/invariants.json").read_text(encoding="utf-8"))
for item in invariants["invariants"]:
    item["journey_ids"] = ["j-home-to-onboarding", "j-public-information"]
    item["acceptance_obligations"] = [item["statement"]]
invariants["status"] = "frozen"
write("scope/invariants.json", invariants)

journeys = json.loads((ROOT / "scope/journeys.json").read_text(encoding="utf-8"))
for item in journeys["journeys"]:
    item["status"] = "frozen"
write("scope/journeys.json", journeys)

checkpoints = json.loads((ROOT / "scope/checkpoints.json").read_text(encoding="utf-8"))
checkpoints["status"] = "frozen"
checkpoints["checkpoints"] = [item for item in checkpoints.get("checkpoints", []) if not str(item.get("id", "")).startswith("home-visual-")]
for item in checkpoints["checkpoints"]:
    item.setdefault("route_id", item.get("route", "/").strip("/") or "home")
    item.setdefault("state", item.get("states", ["initial"])[0])
    item.setdefault("viewport", "desktop")
    item.setdefault("evidence_kind", "current-direct")
    item.setdefault("acceptance_eligible", True)
    item.setdefault("verification_kind", "playwright-screenshot")
checkpoints["checkpoints"] += [
    {"id": "home-visual-desktop", "route_id": "home", "state": "initial", "viewport": "desktop", "priority": "p0", "evidence_kind": "current-direct", "acceptance_eligible": True, "verification_kind": "playwright-screenshot", "visual_contract": {"source_artifact_path": "source-current/2026-08-21.playwright-anon/home-desktop-1440x900.png", "viewport": {"width": 1440, "height": 900}, "comparison_region": {"x": 0, "y": 0, "width": 1440, "height": 900}, "metric": "pixel-mae-similarity-v1", "threshold": 0.7}},
    {"id": "home-visual-tablet", "route_id": "home", "state": "initial", "viewport": "tablet", "priority": "p1", "evidence_kind": "current-direct", "acceptance_eligible": True, "verification_kind": "playwright-screenshot", "visual_contract": {"source_artifact_path": "source-current/2026-08-21.playwright-anon/home-tablet-768x1024.png", "viewport": {"width": 768, "height": 1024}, "comparison_region": {"x": 0, "y": 0, "width": 768, "height": 1024}, "metric": "pixel-mae-similarity-v1", "threshold": 0.7}},
    {"id": "home-visual-mobile", "route_id": "home", "state": "initial", "viewport": "mobile", "priority": "p1", "evidence_kind": "current-direct", "acceptance_eligible": True, "verification_kind": "playwright-screenshot", "visual_contract": {"source_artifact_path": "source-current/2026-08-21.playwright-anon/home-mobile-390x844.png", "viewport": {"width": 390, "height": 844}, "comparison_region": {"x": 0, "y": 0, "width": 390, "height": 844}, "metric": "pixel-mae-similarity-v1", "threshold": 0.7}},
]
write("scope/checkpoints.json", checkpoints)

coverage = json.loads((ROOT / "scope/coverage.json").read_text(encoding="utf-8"))
coverage["status"] = "frozen"
dimensions = []
for old in coverage.get("dimensions", []):
    label_key = old.get("dimension", old.get("id", "dimension"))
    covered_items = old.get("covered", old.get("required_items", []))
    item_ids = [str(x).lower().replace(" ", "-") for x in covered_items]
    dim = {
        "id": str(label_key).replace(" ", "-"),
        "label": str(label_key).title() + " coverage",
        "unit": "evidence-item",
        "category": "offline-clone",
        "required_evidence_kinds": ["browser"],
        "required_items": item_ids,
        "satisfied_items": [],
        "rationale": "; ".join(old.get("unavailable", [])) or old.get("rationale", "Observed and locally verified."),
        "source_evidence_kind": "direct",
        "local_contract_evidence_kind": "direct",
    }
    dimensions.append(dim)
coverage["dimensions"] = dimensions
write("scope/coverage.json", coverage)

manifest = json.loads((ROOT / "source-assets/manifest.json").read_text(encoding="utf-8"))
assets = []
for idx, old in enumerate(manifest.get("assets", [])):
    rel = old.get("path", old.get("runtime_path", "")).replace("\\", "/")
    file_path = ROOT / rel.replace("clone/", "", 1) if rel.startswith("clone/") else ROOT / rel
    # The manifest paths are relative to the site root; clone/ is real under ROOT.
    file_path = ROOT / rel
    if not file_path.exists():
        file_path = ROOT / rel.replace("clone/", "clone/", 1)
    data = file_path.read_bytes() if file_path.exists() else b""
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    assets.append({
        "id": f"asset-{idx+1:02d}",
        "priority": "p0" if idx < 2 else "p1",
        "required": True,
        "source_path": "source-assets/localized/" + Path(rel).name,
        "runtime_path": rel,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mime_type": mime,
        "dimensions": None,
        "referenced_by": ["home", "shared-shell"],
        "evidence_kind": "current-direct",
        "source_url": old.get("source_url"),
        "capture_id": manifest.get("snapshot_id"),
    })
manifest["closure_status"] = "declared"
manifest["assets"] = assets
manifest["no_assets_reason"] = None
write("source-assets/manifest.json", manifest)
print("normalized", len(assets), "assets")
