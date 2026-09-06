"""Build the bounded G2-A fixture from immutable captured evidence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

from websitebench.offline_clone.assets import inspect_asset


SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parents[1]
CAPTURE_ID = "mit-opencourseware-20260903T032020Z"
CAPTURE = REPO / "artifacts" / "mit-opencourseware" / CAPTURE_ID
G1 = CAPTURE / "g1"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


summary = load(G1 / "frozen-inputs" / "source-current" / "g1-source-summary.json")
boundary = load(G1 / "business-contracts" / "scope-boundary-contract.json")
routes = boundary["full_route_instances"]
g2_paths = {
    row["path"]
    for row in routes
    if row["path"] in {"/", "/search/"}
    or row["path"].startswith("/courses/6-006-introduction-to-algorithms-fall-2011/")
}
pages = {
    row["path"]: {
        "title": row["title"],
        "status": row["http_status"],
        "family": row["family"],
        "source_url": row["source_url"],
        "page_id": row["page_id"],
    }
    for row in routes
    if row["path"] in g2_paths
}

catalog = summary["catalog_search"]["course_catalog"]
courses = []
for source in catalog["first_two_batches"]:
    item = dict(source)
    after_pipe = item["card_text"].split("|", 1)[-1].strip()
    item["level"] = after_pipe.split(item["title_link_text"], 1)[0].strip()
    courses.append(item)

matrix = load(G1 / "search-authorized-matrix" / "report.json")
captured_states = {
    f"{scenario['scenario_id']}:{state['state_id']}": {
        "results_total": state["results_total"],
        "cards": [card["text"] for card in state["cards"]],
        "screenshot": state["screenshot"],
        "visible_error_markers": state["visible_error_markers"],
    }
    for scenario in matrix["scenarios"]
    for state in scenario["states"]
}
states = {
    "default": {"total": 2584, "offset": 0, "limit": 10, "source": "default:batch-1"},
    "second-batch": {"total": 2584, "offset": 0, "limit": 20, "source": "default:batch-2"},
    "math": {"total": 199, "offset": 0, "limit": 10, "source": "filters-sort:department-mathematics", "checked": ["catalog-math-filter"]},
    "math-undergraduate": {"total": 110, "offset": 0, "limit": 10, "source": "filters-sort:combined-mathematics-undergraduate", "checked": ["catalog-math-filter", "catalog-undergraduate-filter"]},
    "course-number": {"total": 110, "offset": 0, "limit": 10, "source": "filters-sort:combined-filter-course-number-sort", "checked": ["catalog-math-filter", "catalog-undergraduate-filter"]},
    "empty": {"total": 0, "offset": 0, "limit": 0, "source": "empty-recovery:true-empty", "empty": True},
    "clear-recovered": {"total": 2584, "offset": 0, "limit": 10, "source": "empty-recovery:recovered-default"},
    "loading": {"total": 2584, "offset": 0, "limit": 0, "source": "default:batch-1", "loading": True},
    "error": {"total": 0, "offset": 0, "limit": 0, "source": "error-retry:controlled-api-error", "error": "Oops! Something went wrong."},
    "retry-stale": {"total": 2584, "offset": 0, "limit": 0, "source": "error-retry:retry-response", "error": "Oops! Something went wrong."},
    "reload-recovered": {"total": 2584, "offset": 0, "limit": 10, "source": "error-retry:reload-recovered-default"},
    "resources": {"total": 10000, "offset": 0, "limit": 10, "source": "resources:batch-1", "resources": True},
}
for value in states.values():
    value["captured"] = captured_states[value.pop("source")]
    if value.get("loading"):
        value["captured"] = {**value["captured"], "cards": []}

asset_report = load(G1 / "first-party-static-assets" / "report.json")
assets_by_url = {item["url"]: item for item in asset_report["items"] if item.get("status") == 200}
wanted = [("ocw-logo.svg", "https://ocw.mit.edu/static_shared/images/ocw_logo_white.cabdc9a745b03db3dad4.svg", ["global-header"])]
for course in courses:
    url = course["image_url"]
    if url in assets_by_url:
        name = f"catalog-{int(course['source_order']):02d}.jpg"
        wanted.append((name, url, ["home.default", "catalog.default", "catalog.second-batch"]))
        course["local_image"] = f"/assets/{name}"

source_dir = SITE / "source-assets" / "g2a"
runtime_dir = SITE / "runtime-assets" / "g2a"
source_dir.mkdir(parents=True, exist_ok=True)
runtime_dir.mkdir(parents=True, exist_ok=True)
manifest_assets = []
runtime_assets = {}
for name, url, refs in wanted:
    item = assets_by_url[url]
    evidence = G1 / "first-party-static-assets" / item["file"]
    source_path = source_dir / name
    runtime_path = runtime_dir / name
    shutil.copyfile(evidence, source_path)
    shutil.copyfile(evidence, runtime_path)
    observed = inspect_asset(runtime_path)
    manifest_assets.append({
        "id": f"asset-{item['sha256'][:20]}",
        "priority": "p0",
        "required": True,
        "source_path": source_path.relative_to(SITE).as_posix(),
        "runtime_path": runtime_path.relative_to(SITE).as_posix(),
        "bytes": item["bytes"],
        "sha256": item["sha256"],
        "mime_type": observed["mime_type"],
        "dimensions": observed["dimensions"],
        "referenced_by": refs,
        "evidence_kind": "current-direct",
        "source_url": url,
        "capture_id": CAPTURE_ID,
    })
    runtime_assets[name] = {
        "runtime_path": runtime_path.relative_to(SITE).as_posix(),
        "mime_type": observed["mime_type"],
        "sha256": item["sha256"],
    }

ea1 = load(CAPTURE / "ea1" / "summary.json")["download_evidence"]
pdf_source = CAPTURE / "ea1" / ea1["local_path"]
pdf_name = unquote(Path(urlsplit(ea1["url"]).path).name)
pdf_source_copy = source_dir / "problem-set-1.pdf"
pdf_runtime_copy = runtime_dir / "problem-set-1.pdf"
shutil.copyfile(pdf_source, pdf_source_copy)
shutil.copyfile(pdf_source, pdf_runtime_copy)
pdf_sha = __import__("hashlib").sha256(pdf_runtime_copy.read_bytes()).hexdigest()
manifest_assets.append({
    "id": f"asset-{pdf_sha[:20]}",
    "priority": "p0",
    "required": True,
    "source_path": pdf_source_copy.relative_to(SITE).as_posix(),
    "runtime_path": pdf_runtime_copy.relative_to(SITE).as_posix(),
    "bytes": ea1["content_length"],
    "sha256": pdf_sha,
    "mime_type": "application/pdf",
    "dimensions": None,
    "referenced_by": ["resource-problem-set.default", "course-download.default"],
    "evidence_kind": "current-direct",
    "source_url": ea1["url"],
    "capture_id": CAPTURE_ID,
    "resource_set_class": "logical-resource",
})

recipes = [load(path) for path in sorted((SITE / "scope" / "recipes").glob("*.json"))]
assertions = [
    {key: recipe[key] for key in ("checkpoint_id", "kind", "record_id", "selector", "expected_state", "expected_href") if key in recipe}
    for recipe in recipes
]

dump(SITE / "clone" / "site-data.json", {
    "capture_id": CAPTURE_ID,
    "phase": "g2a-bounded-not-full-denominator",
    "pages": pages,
    "catalog": {"reported_total": catalog["reported_total"], "courses": courses, "states": states},
    "pdf": {
        "path": urlsplit(ea1["url"]).path,
        "source_url": ea1["url"],
        "source_path": pdf_source_copy.relative_to(SITE).as_posix(),
        "runtime_path": pdf_runtime_copy.relative_to(SITE).as_posix(),
        "filename": pdf_name,
        "bytes": ea1["content_length"],
        "sha256": pdf_sha,
    },
    "assets": runtime_assets,
    "assertions": assertions,
    "final_denominator_todo": {
        "status": "not-yet-claimed",
        "route_instances": 732,
        "logical_downloads": 480,
        "unique_download_hashes": 478,
        "download_bytes": 1551223348,
    },
})
dump(SITE / "source-assets" / "manifest.json", {
    "schema_version": "offline-clone.assets.v1",
    "snapshot_id": "mit-opencourseware-g2a-20260903",
    "created_at": "2026-09-03T05:43:23Z",
    "remote_runtime_policy": "forbidden",
    "closure_status": "declared",
    "no_assets_reason": None,
    "assets": manifest_assets,
})

# G2-A is intentionally a draft/partial contract: it proves the two vertical
# slices without claiming the frozen 732-route / 480-download denominator.
route_states = {
    "home": ("/", ["default", "carousel-second-batches"]),
    "catalog": ("/search/", ["default", "second-batch", "math", "math-undergraduate", "course-number", "empty", "error", "retry-stale", "reload-recovered", "resources", "loading"]),
    "course-overview": ("/courses/6-006-introduction-to-algorithms-fall-2011/", ["default"]),
    "course-syllabus": ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/", ["default"]),
    "course-calendar": ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/calendar/", ["default"]),
    "course-readings": ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/", ["default"]),
    "course-reading-deep": ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/binary-search-trees/", ["default"]),
    "course-lecture-notes": ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-notes/", ["default"]),
    "course-assignments": ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/", ["default"]),
    "course-exams": ("/courses/6-006-introduction-to-algorithms-fall-2011/pages/exams/", ["default"]),
    "course-download": ("/courses/6-006-introduction-to-algorithms-fall-2011/download/", ["default"]),
    "resource-index": ("/courses/6-006-introduction-to-algorithms-fall-2011/resources/problem-sets/", ["default"]),
    "resource-problem-set": ("/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/", ["default"]),
    "resource-final-exam": ("/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_final/", ["default"]),
    "resource-lecture-note": ("/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec01/", ["default"]),
    "external-boundary": ("/external-boundary/", ["default"]),
    "data-boundary": ("/data-boundary/", ["default"]),
    "not-found": ("/not-in-scope", ["default"]),
}
dump(SITE / "scope" / "routes.json", {
    "schema_version": "offline-clone.routes.v1",
    "routes": [
        {"id": route_id, "route_pattern": pattern, "local_destination": True, "priority": "p0", "purpose_edge": "primary", "states": route_state_ids}
        for route_id, (pattern, route_state_ids) in route_states.items()
    ],
})
checkpoint_ids = [
    "home.default", "home.carousel-second-batches", "catalog.default", "catalog.second-batch",
    "catalog.math", "catalog.math-undergraduate", "catalog.course-number", "catalog.empty",
    "catalog.error", "catalog.retry-stale", "catalog.reload-recovered", "catalog.resources",
    "course-overview.default", "course-syllabus.default", "course-calendar.default",
    "course-readings.default", "course-reading-deep.default", "course-lecture-notes.default",
    "course-assignments.default", "course-exams.default", "course-download.default",
    "resource-index.default", "resource-problem-set.default", "external-boundary.default",
    "data-boundary.default", "not-found.default",
]
dump(SITE / "scope" / "checkpoints.json", {
    "schema_version": "offline-clone.checkpoints.v1",
    "status": "draft",
    "viewports": {"desktop": {"width": 1440, "height": 900}},
    "checkpoints": [
        {
            "id": checkpoint_id,
            "route_id": checkpoint_id.split(".", 1)[0],
            "state": checkpoint_id.split(".", 1)[1],
            "viewport": "desktop",
            "priority": "p0",
            "evidence_kind": "current-direct",
            "verification_kind": "g2a-local-diagnostic",
            "acceptance_eligible": False,
        }
        for checkpoint_id in checkpoint_ids
    ],
})
dump(SITE / "scope" / "journeys.json", {
    "schema_version": "offline-clone.journeys.v1",
    "journeys": [
        {"id": "home-catalog-mainline", "actor": "visitor", "kind": "success", "priority": "p0", "status": "draft", "steps": ["Open home.", "Search and filter the first two frozen catalog batches.", "Recover from empty and controlled-error states locally."]},
        {"id": "course-material-download", "actor": "visitor", "kind": "success", "priority": "p0", "status": "draft", "steps": ["Open the frozen 6.006 overview.", "Navigate retained course and resource pages.", "Download the exact local Problem Set 1 PDF."]},
    ],
})
dump(SITE / "scope" / "purpose.json", {
    "schema_version": "offline-clone.purpose.v1",
    "purpose_id": "mit-ocw-g2a-partial",
    "statement": "Verify the bounded home/catalog and 6.006 local-download vertical slices without claiming final denominators.",
    "status": "draft",
    "primary_actor_ids": ["visitor"],
    "mainline_journey_ids": ["home-catalog-mainline", "course-material-download"],
    "out_of_scope": ["G2-A does not yet claim the final 732 routes or 480 logical downloads."],
})
dump(SITE / "scope" / "invariants.json", {
    "schema_version": "offline-clone.invariants.v1",
    "status": "draft",
    "invariants": [
        {"id": "runtime-network-closed", "priority": "p0", "statement": "All runtime resources and downloads are served locally with zero remote requests.", "journey_ids": ["home-catalog-mainline", "course-material-download"], "coverage_dimension_ids": ["g2a-route-states"], "positive_test_refs": ["clone/tests/test_smoke.py::test_health_and_zero_remote_runtime_policy"], "negative_test_refs": ["clone/tests/test_smoke.py::test_boundaries_and_hard_404_recovery_are_local"]},
        {"id": "catalog-frozen-state", "priority": "p0", "statement": "The captured catalog identities, counts, controls, and recovery states remain deterministic.", "journey_ids": ["home-catalog-mainline"], "coverage_dimension_ids": ["g2a-route-states"], "positive_test_refs": ["clone/tests/test_smoke.py::test_catalog_filters_sort_tabs_and_checked_semantics"], "negative_test_refs": ["clone/tests/test_smoke.py::test_catalog_loading_empty_error_stale_retry_and_reload_recovery"]},
        {"id": "pdf-byte-exact", "priority": "p0", "statement": "The retained Problem Set 1 PDF is repeatable and byte exact.", "journey_ids": ["course-material-download"], "coverage_dimension_ids": ["g2a-route-states"], "positive_test_refs": ["clone/tests/test_smoke.py::test_exact_pdf_is_repeatable_and_source_runtime_are_ordinary_copies"], "negative_test_refs": ["clone/tests/test_smoke.py::test_boundaries_and_hard_404_recovery_are_local"]},
    ],
})
dump(SITE / "scope" / "coverage.json", {
    "schema_version": "offline-clone.coverage.v1",
    "status": "draft",
    "dimensions": [{
        "id": "g2a-route-states", "category": "reachability", "label": "Bounded G2-A route-state diagnostics",
        "unit": "route-state", "required_evidence_kinds": ["browser"],
        "required_items": checkpoint_ids, "satisfied_items": [],
    }],
})
print(json.dumps({"pages": len(pages), "catalog_cards": len(courses), "assets": len(manifest_assets), "pdf_sha256": pdf_sha}, indent=2))
