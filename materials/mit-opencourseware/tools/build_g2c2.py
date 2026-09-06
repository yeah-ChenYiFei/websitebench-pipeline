"""Mechanically close the MIT OCW G2-C2 diagnostic scope.

The only route/state authority consumed here is the frozen business contract.
No visual or formal acceptance claim is created by this builder.
"""

from __future__ import annotations

import json
from pathlib import Path


SITE = Path(__file__).resolve().parents[1]
SCOPE = SITE / "scope"
CONTRACT_PATH = SCOPE / "business-contracts" / "route-state-contract.json"

STATE_DESTINATIONS = {
    "catalog.default": "/search/",
    "catalog.second-batch": "/search/?state=second-batch",
    "catalog.math": "/search/?state=math",
    "catalog.math-undergraduate": "/search/?state=math-undergraduate",
    "catalog.course-number": "/search/?state=course-number",
    "catalog.empty": "/search/?state=empty",
    "catalog.error": "/search/?state=error",
    "catalog.retry-stale": "/search/?state=retry-stale",
    "catalog.reload-recovered": "/search/?state=reload-recovered",
    "catalog.resources": "/search/?state=resources",
    "home.carousel-second-batches": "/?state=carousel-second-batches",
    "video.static-disabled": (
        "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
        "resources/mit14_129s25_lec01_1080p_mp4/"
    ),
    "external-boundary.default": "/external-boundary/",
    "data-boundary.default": "/data-boundary/",
}

LOCAL_ROUTE_STATES = {
    "home": ["default", "carousel-second-batches"],
    "catalog": [
        "default",
        "second-batch",
        "math",
        "math-undergraduate",
        "course-number",
        "loading",
        "empty",
        "error",
        "retry-stale",
        "reload-recovered",
        "resources",
    ],
    "video-resource": ["default", "static-disabled"],
}

STATE_EXPECTATIONS = {
    "catalog.second-batch": "[data-wb-component='catalog-results']",
    "catalog.math": "[data-wb-control='catalog-math-filter']:checked",
    "catalog.math-undergraduate": "[data-wb-control='catalog-undergraduate-filter']:checked",
    "catalog.course-number": "[data-wb-control='catalog-sort']",
    "catalog.empty": "[data-wb-component='catalog-empty']",
    "catalog.error": "[data-wb-component='catalog-error']",
    "catalog.retry-stale": "[data-wb-component='catalog-error']",
    "catalog.reload-recovered": "[data-wb-component='catalog-results']",
    "catalog.resources": "[data-wb-control='catalog-resource-tab']:checked",
    "home.carousel-second-batches": "[data-wb-control='featured-previous']",
    "video.static-disabled": "[data-wb-control='video-play']:disabled",
    "external-boundary.default": "[data-wb-component='external-boundary']",
    "data-boundary.default": "[data-wb-capability='data-boundary']",
}

JOURNEYS = [
    {
        "id": "home-discovery",
        "actor": "visitor",
        "kind": "success",
        "priority": "p0",
        "status": "draft",
        "steps": [
            "Open the frozen home page.",
            "Traverse both featured, new-course, and story carousel batches.",
            "Follow retained local course, collection, story, and information links.",
        ],
    },
    {
        "id": "catalog-state-recovery",
        "actor": "visitor",
        "kind": "success",
        "priority": "p0",
        "status": "draft",
        "steps": [
            "Open the 2,584-result catalog snapshot.",
            "Exercise both card batches, filters, sort, loading, resources, and empty states.",
            "Recover deterministically through error, stale retry, clear, and reload flows.",
        ],
    },
    {
        "id": "course-material-navigation",
        "actor": "visitor",
        "kind": "success",
        "priority": "p0",
        "status": "draft",
        "steps": [
            "Open retained course overview identities.",
            "Navigate distinct section, deep-link, resource-index, and resource-detail families.",
            "Preserve every captured heading, title, page identity, and local edge.",
        ],
    },
    {
        "id": "download-closure",
        "actor": "visitor",
        "kind": "success",
        "priority": "p0",
        "status": "draft",
        "steps": [
            "Select a captured course archive or attachment.",
            "Receive exact local headers and streamed bytes.",
            "Repeat the request and obtain the same length, filename, MIME type, and SHA-256.",
        ],
    },
    {
        "id": "collection-story-information",
        "actor": "visitor",
        "kind": "success",
        "priority": "p1",
        "status": "draft",
        "steps": [
            "Open collections, stories, about, educator, and get-started routes.",
            "Observe their distinct captured headings and link identities.",
        ],
    },
    {
        "id": "newsletter-boundary",
        "actor": "visitor",
        "kind": "boundary",
        "priority": "p1",
        "status": "draft",
        "steps": [
            "Open the newsletter route.",
            "Enter an email in the local form.",
            "Terminate at the branded local external boundary without a remote POST.",
        ],
    },
    {
        "id": "video-disabled",
        "actor": "visitor",
        "kind": "boundary",
        "priority": "p1",
        "status": "draft",
        "steps": [
            "Open the lecture gallery and first lecture resource.",
            "Observe retained static thumbnails.",
            "Confirm playback is visibly disabled and no media request is made.",
        ],
    },
    {
        "id": "navigation-boundaries",
        "actor": "visitor",
        "kind": "boundary",
        "priority": "p0",
        "status": "draft",
        "steps": [
            "Activate a retained external destination or catalog card beyond full-detail scope.",
            "Arrive at the matching local external or data boundary.",
            "Recover from the explicit HTTP-200 not-found route and an additional hard HTTP 404.",
        ],
    },
    {
        "id": "route-identity-closure",
        "actor": "visitor",
        "kind": "success",
        "priority": "p0",
        "status": "draft",
        "steps": [
            "Request every one of the 732 captured route paths.",
            "Match each frozen HTTP status, title, family, page id, and captured heading.",
        ],
    },
    {
        "id": "presentation-asset-closure",
        "actor": "visitor",
        "kind": "success",
        "priority": "p0",
        "status": "draft",
        "steps": [
            "Resolve every retained presentation URL to its local runtime copy.",
            "Verify 231 hashes and keep five exact source 404 identities unavailable.",
        ],
    },
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dimension(
    dimension_id: str,
    label: str,
    items: list[str],
    *,
    evidence: list[str],
    satisfied: bool = True,
    population_size: int | None = None,
    rationale: str | None = None,
) -> dict:
    value = {
        "id": dimension_id,
        "label": label,
        "unit": "contract-item",
        "category": "g2c2-diagnostic",
        "required_evidence_kinds": evidence,
        "required_items": items,
        "satisfied_items": list(items) if satisfied else [],
    }
    if population_size is not None:
        value["population_size"] = population_size
        value["sample_size"] = population_size if satisfied else 0
        value["sampling_method"] = "exhaustive deterministic local test"
    if rationale:
        value["rationale"] = rationale
    return value


def main() -> None:
    contract = read_json(CONTRACT_PATH)
    assert contract["status"] == "frozen"
    representatives = contract["representative_acceptance_routes"]
    state_rows = contract["state_checkpoints"]
    assert len(representatives) == 29
    assert len(state_rows) == len(STATE_DESTINATIONS) == 14
    assert {row["checkpoint_id"] for row in state_rows} == set(STATE_DESTINATIONS)

    representative_by_id = {row["route_id"]: row for row in representatives}
    representative_checkpoint_ids = [row["checkpoint_id"] for row in representatives]
    assert len(representative_by_id) == len(representative_checkpoint_ids) == 29

    checkpoints_by_id: dict[str, dict] = {}
    checkpoint_order: list[str] = []
    for row in representatives:
        checkpoint_id = row["checkpoint_id"]
        checkpoint_order.append(checkpoint_id)
        checkpoints_by_id[checkpoint_id] = {
            "id": checkpoint_id,
            "route_id": row["route_id"],
            "state": "default",
            "viewport": "desktop",
            "clone_path": row["path"],
            "priority": "p0",
            "evidence_kind": "current-direct",
            "verification_kind": "g2c2-local-diagnostic",
            "acceptance_eligible": False,
        }
    for row in state_rows:
        checkpoint_id = row["checkpoint_id"]
        if checkpoint_id not in checkpoints_by_id:
            checkpoint_order.append(checkpoint_id)
        checkpoints_by_id[checkpoint_id] = {
            "id": checkpoint_id,
            "route_id": row["route_id"],
            "state": row["state"],
            "viewport": "desktop",
            "clone_path": STATE_DESTINATIONS[checkpoint_id],
            "priority": "p0",
            "evidence_kind": "current-direct",
            "verification_kind": "g2c2-local-diagnostic",
            "acceptance_eligible": False,
        }
    assert len(checkpoint_order) == len(set(checkpoint_order)) == 40
    checkpoints = [checkpoints_by_id[checkpoint_id] for checkpoint_id in checkpoint_order]

    routes = []
    boundary_ids = {
        "source-legacy-boundary",
        "external-boundary",
        "data-boundary",
        "not-found",
    }
    secondary_ids = {"stories", "story-adrian", "about", "get-started", "educator", "newsletter"}
    for row in representatives:
        route_id = row["route_id"]
        routes.append({
            "id": route_id,
            "route_pattern": row["path"],
            "local_destination": True,
            "priority": "p0",
            "purpose_edge": (
                "boundary"
                if route_id in boundary_ids
                else "secondary"
                if route_id in secondary_ids
                else "primary"
            ),
            "states": LOCAL_ROUTE_STATES.get(route_id, ["default"]),
        })
    write_json(SCOPE / "routes.json", {
        "schema_version": "offline-clone.routes.v1",
        "routes": routes,
    })
    write_json(SCOPE / "checkpoints.json", {
        "schema_version": "offline-clone.checkpoints.v1",
        "status": "draft",
        "viewports": {"desktop": {"width": 1440, "height": 900}},
        "checkpoints": checkpoints,
    })

    verify_states: dict[str, list[dict[str, object]]] = {}
    state_row_ids = {row["checkpoint_id"] for row in state_rows}
    for checkpoint in checkpoints:
        key = f'{checkpoint["route_id"]}.{checkpoint["state"]}'
        steps: list[dict[str, object]] = []
        if checkpoint["id"] in state_row_ids and checkpoint["state"] != "default":
            steps.append({"goto": checkpoint["clone_path"]})
            expectation = STATE_EXPECTATIONS.get(checkpoint["id"])
            if expectation:
                steps.append({"expect": expectation})
        verify_states[key] = steps
    assert len(verify_states) == 40
    write_json(SCOPE / "verify.json", {
        "schema_version": "offline-clone.verify-driver.v1",
        "site_id": "mit-opencourseware",
        "note": (
            "G2-C2 diagnostic-only mapping for 29 representative routes and 40 "
            "frozen route-state checkpoints. Visual, blind, and formal acceptance are deferred."
        ),
        "boot": {
            "argv": [
                "{python}", "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
                "--port", "{port}", "--log-level", "warning",
            ],
            "cwd": "clone",
            "env": {},
            "read_paths": ["runtime-assets", "runtime-downloads"],
        },
        "prepare": [],
        "routes": {row["route_id"]: row["path"] for row in representatives},
        "states": verify_states,
        "status": {},
        "deferred": {},
    })

    write_json(SCOPE / "purpose.json", {
        "schema_version": "offline-clone.purpose.v1",
        "purpose_id": "mit-ocw-anonymous-public-mirror",
        "statement": (
            "Provide a deterministic anonymous public offline mirror of the frozen MIT "
            "OpenCourseWare capture, including home and catalog states, all 732 captured "
            "page identities across 11 families, 480 logical downloads, 231 retained "
            "presentation assets, and explicit local boundaries with zero runtime remote requests."
        ),
        "status": "draft",
        "primary_actor_ids": ["visitor"],
        "mainline_journey_ids": [
            "home-discovery",
            "catalog-state-recovery",
            "course-material-navigation",
            "download-closure",
            "route-identity-closure",
            "presentation-asset-closure",
        ],
        "boundary_journey_ids": [
            "newsletter-boundary",
            "video-disabled",
            "navigation-boundaries",
        ],
        "secondary_journey_ids": ["collection-story-information"],
        "out_of_scope": [
            "No account, authenticated workspace, or source mutation surface was observed.",
            "External destinations are represented only by exact identity and a branded local boundary.",
            "Remote video playback and newsletter submission are intentionally disabled at local boundaries.",
            "Formal visual fidelity scoring, blind evaluation, and acceptance-check remain deferred after G2-C2.",
        ],
    })
    write_json(SCOPE / "journeys.json", {
        "schema_version": "offline-clone.journeys.v1",
        "journeys": JOURNEYS,
    })

    invariant_specs = [
        ("runtime-network-closed", "Every rendered route, state, asset, download, video, and boundary attempts zero runtime remote requests.", "runtime-network-closure", ["home-discovery", "catalog-state-recovery", "navigation-boundaries"]),
        ("route-identity-exact", "All 732 captured paths retain their frozen HTTP status, title, family, page id, and captured identity.", "captured-route-instances", ["route-identity-closure"]),
        ("catalog-state-deterministic", "Catalog batches, filters, sort, tabs, loading, empty, error, retry, clear, and reload states are deterministic.", "catalog-local-states", ["catalog-state-recovery"]),
        ("home-content-denominators", "Home preserves 16 cards, 15 complete course expectations, 141 sections, 184 resources, and 13 story details.", "home-content", ["home-discovery"]),
        ("family-structures-distinct", "Each of the 11 captured route families renders its own page structure and identity.", "route-families", ["course-material-navigation", "collection-story-information"]),
        ("downloads-byte-exact", "All 480 logical downloads reconstruct 478 unique payload hashes and 1,551,223,348 logical bytes repeatably.", "download-closure", ["download-closure"]),
        ("presentation-assets-exact", "All 231 retained presentation URLs serve exact local bytes while five source 404 identities remain unavailable.", "presentation-assets", ["presentation-asset-closure"]),
        ("video-static-disabled", "Lecture video presentation is static and disabled without iframe, media, or remote playback.", "boundaries", ["video-disabled"]),
        ("local-boundaries-recoverable", "External, data, newsletter, explicit not-found, and hard-404 flows remain local and recoverable.", "boundaries", ["newsletter-boundary", "navigation-boundaries"]),
        ("immutable-restart", "The read-only route, asset, and download snapshot remains deterministic across restart and reset.", "captured-route-instances", ["route-identity-closure", "download-closure"]),
    ]
    write_json(SCOPE / "invariants.json", {
        "schema_version": "offline-clone.invariants.v1",
        "status": "draft",
        "invariants": [
            {
                "id": invariant_id,
                "priority": "p0",
                "statement": statement,
                "journey_ids": journey_ids,
                "coverage_dimension_ids": [coverage_id],
                "positive_test_refs": [
                    "clone/tests/test_c1_closure.py",
                    "clone/tests/test_downloads_streaming.py",
                ],
                "negative_test_refs": [
                    "clone/tests/test_smoke.py::test_boundaries_and_hard_404_recovery_are_local"
                ],
            }
            for invariant_id, statement, coverage_id, journey_ids in invariant_specs
        ],
    })

    family_items = [f"family-{family}" for family in sorted(contract["route_family_counts"])]
    dimensions = [
        dimension("representative-route-states", "Forty frozen representative route states", checkpoint_order, evidence=["browser", "full-suite"], population_size=40),
        dimension("captured-route-instances", "All captured page route identities", ["captured-routes-732"], evidence=["full-suite"], population_size=732),
        dimension("route-families", "Distinct captured route family structures", family_items, evidence=["full-suite"], population_size=11),
        dimension("home-content", "Frozen home content denominators", ["home-course-cards-16", "home-complete-course-details-15", "home-sections-141", "home-resources-184", "story-details-13"], evidence=["full-suite"]),
        dimension("catalog-content", "Frozen catalog content denominators", ["catalog-cards-20", "catalog-complete-details-10", "catalog-boundary-cards-10", "catalog-sections-69", "catalog-resources-235"], evidence=["full-suite"]),
        dimension("catalog-local-states", "All implemented catalog states", [f"catalog-state-{state}" for state in LOCAL_ROUTE_STATES["catalog"]], evidence=["browser", "full-suite"], population_size=11),
        dimension("download-closure", "Exact local download closure", ["logical-downloads-480", "unique-payloads-478", "logical-bytes-1551223348", "repeatable-streaming"], evidence=["full-suite"]),
        dimension("presentation-assets", "Presentation asset URL and source-404 closure", ["retained-assets-231", "retained-bytes-35298609", "unavailable-assets-5"], evidence=["full-suite"]),
        dimension("boundaries", "Local capability and recovery boundaries", ["external-boundary", "data-boundary", "newsletter-boundary", "video-disabled", "hard-404-recovery"], evidence=["browser", "full-suite"]),
        dimension("runtime-network-closure", "Runtime remote request closure", ["runtime-remote-requests-zero"], evidence=["network", "full-suite"]),
        dimension("visual-fidelity", "Formal source-to-clone visual fidelity", ["visual-checkpoints-40"], evidence=["visual"], satisfied=False, population_size=40, rationale="Deferred: G2-C2 creates no visual contracts and makes no visual acceptance claim."),
        dimension("blind-evaluation", "Independent blind evaluator result", ["blind-evaluation-pending"], evidence=["independent-audit"], satisfied=False, rationale="Deferred until the explicitly authorized blind-evaluation gate."),
    ]
    write_json(SCOPE / "coverage.json", {
        "schema_version": "offline-clone.coverage.v1",
        "status": "draft",
        "dimensions": dimensions,
    })

    site_data_path = SITE / "clone" / "site-data.json"
    site_data = read_json(site_data_path)
    site_data["phase"] = "g2c2-functional-data-scope-closed"
    site_data.pop("final_denominator_todo", None)
    site_data["final_denominator_status"] = {
        "status": "functional-data-scope-closed",
        "route_instances": 732,
        "route_families": 11,
        "representative_routes": 29,
        "diagnostic_checkpoints": 40,
        "logical_downloads": 480,
        "unique_download_hashes": 478,
        "download_bytes": 1_551_223_348,
        "presentation_assets": 231,
        "presentation_asset_bytes": 35_298_609,
        "unavailable_assets": 5,
        "runtime_remote_requests": 0,
        "deferred": ["visual-fidelity", "blind-evaluation", "formal-acceptance"],
    }
    write_json(site_data_path, site_data)

    print(json.dumps({
        "status": "g2c2-scope-materialized",
        "routes": len(routes),
        "checkpoints": len(checkpoints),
        "verify_states": len(verify_states),
        "journeys": len(JOURNEYS),
        "invariants": len(invariant_specs),
        "coverage_dimensions": len(dimensions),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
