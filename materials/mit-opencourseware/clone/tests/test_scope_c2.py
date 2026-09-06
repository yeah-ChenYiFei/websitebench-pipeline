from __future__ import annotations

import json
from pathlib import Path

from app import ASSET_URL_MAP, DATA, DOWNLOADS, PAGES, SITE_ROOT, UNAVAILABLE_ASSETS
from websitebench.offline_clone.manifest import load_manifest
from websitebench.offline_clone.verify_driver import load_verify_driver


SCOPE_ROOT = SITE_ROOT / "scope"


def read_json(name: str) -> dict:
    return json.loads((SCOPE_ROOT / name).read_text(encoding="utf-8"))


CONTRACT = read_json("business-contracts/route-state-contract.json")
ROUTES = read_json("routes.json")
CHECKPOINTS = read_json("checkpoints.json")
VERIFY = read_json("verify.json")
PURPOSE = read_json("purpose.json")
JOURNEYS = read_json("journeys.json")
INVARIANTS = read_json("invariants.json")
COVERAGE = read_json("coverage.json")


def test_routes_are_the_exact_29_frozen_representatives() -> None:
    frozen = CONTRACT["representative_acceptance_routes"]
    actual = ROUTES["routes"]
    assert len(frozen) == len(actual) == 29
    assert [row["id"] for row in actual] == [row["route_id"] for row in frozen]
    assert [row["route_pattern"] for row in actual] == [row["path"] for row in frozen]
    assert all(row["local_destination"] is True for row in actual)
    by_id = {row["id"]: row for row in actual}
    assert by_id["not-found"]["route_pattern"] == "/not-found/"
    assert by_id["home"]["states"] == ["default", "carousel-second-batches"]
    assert by_id["catalog"]["states"] == [
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
    ]


def test_checkpoints_are_the_40_unique_frozen_route_state_union() -> None:
    representative_ids = {
        row["checkpoint_id"] for row in CONTRACT["representative_acceptance_routes"]
    }
    state_ids = {row["checkpoint_id"] for row in CONTRACT["state_checkpoints"]}
    actual = CHECKPOINTS["checkpoints"]
    assert len(representative_ids) == 29
    assert len(CONTRACT["state_checkpoints"]) == 14
    assert len(representative_ids | state_ids) == len(actual) == 40
    assert {row["id"] for row in actual} == representative_ids | state_ids
    assert CHECKPOINTS["status"] == "frozen"
    visual = {row["id"]: row for row in actual if "visual_contract" in row}
    ineligible = {
        row["id"] for row in actual if row["acceptance_eligible"] is False
    }
    assert len(visual) == 35
    assert set(visual) == {
        row["id"] for row in actual if row["acceptance_eligible"] is True
    }
    assert ineligible == {
        "source-legacy-boundary.default",
        "external-boundary.default",
        "data-boundary.default",
        "not-found.default",
        "home.carousel-second-batches",
    }
    assert visual["home.default"]["route_id"] == "home"
    assert visual["home.default"]["visual_contract"]["source_artifact_path"].endswith(
        "/home-default-1440xfull.png"
    )
    assert visual["course-overview.default"]["route_id"] == "course-overview"
    assert visual["course-overview.default"]["visual_contract"]["source_artifact_path"].endswith(
        "/course-overview-default-1440xfull.png"
    )
    assert all(
        row["verification_kind"] == "g3c-exact-fullpage-visual-diagnostic"
        for row in visual.values()
    )
    assert sum("visual_contract" not in row for row in actual) == 5
    assert all(
        row.get("visual_unavailable_reason")
        for row in actual
        if row["id"] in ineligible
    )
    for row in visual.values():
        contract = row["visual_contract"]
        assert contract["metric"] == "pixel-mae-similarity-v1"
        assert contract["threshold"] == contract["full_page_threshold"] == 0.94
        assert (SITE_ROOT / contract["source_artifact_path"]).is_file()

    state_by_id = {row["checkpoint_id"]: row for row in CONTRACT["state_checkpoints"]}
    for checkpoint in actual:
        frozen_state = state_by_id.get(checkpoint["id"])
        if frozen_state:
            assert checkpoint["state"] == frozen_state["state"]


def test_verify_maps_all_routes_and_checkpoint_states_to_real_local_destinations() -> None:
    representatives = CONTRACT["representative_acceptance_routes"]
    assert VERIFY["routes"] == {row["route_id"]: row["path"] for row in representatives}
    assert len(VERIFY["routes"]) == 29
    assert len(VERIFY["states"]) == 40
    assert VERIFY["boot"]["read_paths"] == ["runtime-assets", "runtime-downloads", "runtime-content"]
    assert VERIFY["routes"]["not-found"] == "/not-found/"

    for checkpoint in CHECKPOINTS["checkpoints"]:
        recipe_key = f'{checkpoint["route_id"]}.{checkpoint["state"]}'
        assert checkpoint["route_id"] in VERIFY["routes"]
        assert recipe_key in VERIFY["states"]
        goto_steps = [step["goto"] for step in VERIFY["states"][recipe_key] if "goto" in step]
        destination = goto_steps[-1] if goto_steps else VERIFY["routes"][checkpoint["route_id"]]
        assert checkpoint["clone_path"] == destination
    assert VERIFY["states"]["home.all-home-carousels-second-batch"][0] == {
        "goto": "/?state=carousel-second-batches"
    }


def test_scope_references_and_schema_loaders_are_valid() -> None:
    journey_ids = {row["id"] for row in JOURNEYS["journeys"]}
    dimension_ids = {row["id"] for row in COVERAGE["dimensions"]}
    route_ids = {row["id"] for row in ROUTES["routes"]}
    assert len(journey_ids) == len(JOURNEYS["journeys"]) == 10
    assert len(INVARIANTS["invariants"]) == 10
    assert len(dimension_ids) == len(COVERAGE["dimensions"]) == 13
    assert set(PURPOSE["mainline_journey_ids"]) <= journey_ids
    assert set(PURPOSE["boundary_journey_ids"]) <= journey_ids
    assert set(PURPOSE["secondary_journey_ids"]) <= journey_ids
    for invariant in INVARIANTS["invariants"]:
        assert set(invariant["journey_ids"]) <= journey_ids
        assert set(invariant["coverage_dimension_ids"]) <= dimension_ids
        for ref in invariant["positive_test_refs"] + invariant["negative_test_refs"]:
            path_text = ref.split("::", 1)[0]
            assert (SITE_ROOT / path_text).is_file(), ref
    assert {row["route_id"] for row in CHECKPOINTS["checkpoints"]} <= route_ids
    for dimension in COVERAGE["dimensions"]:
        assert set(dimension["satisfied_items"]) <= set(dimension["required_items"])
    frozen = {row["id"]: row for row in COVERAGE["dimensions"]}
    visual_ids = {
        row["id"] for row in CHECKPOINTS["checkpoints"] if "visual_contract" in row
    }
    gap_ids = {
        row["id"]
        for row in CHECKPOINTS["checkpoints"]
        if row["acceptance_eligible"] is False
    }
    assert set(frozen["visual-fidelity"]["required_items"]) == visual_ids
    assert set(frozen["semantic-only-visual-input-gaps"]["required_items"]) == gap_ids
    assert frozen["blind-evaluation"]["required_items"] == ["blind-review-p0-p1"]
    assert all(row["satisfied_items"] == [] for row in COVERAGE["dimensions"])
    assert PURPOSE["status"] == INVARIANTS["status"] == COVERAGE["status"] == "frozen"
    assert all(row["status"] == "frozen" for row in JOURNEYS["journeys"])
    assert PURPOSE["purpose_id"] == "mit-ocw-anonymous-public-mirror"

    loaded = load_manifest(SITE_ROOT / "clone.yaml")
    assert loaded.data["site_id"] == "mit-opencourseware"
    assert loaded.data["source"]["baseline"]["delivery_region"] == "CA"
    assert loaded.data["source"]["baseline"]["timezone"] == "America/Toronto"
    driver = load_verify_driver(SCOPE_ROOT / "verify.json", site_id="mit-opencourseware")
    assert len(driver["routes"]) == 29 and len(driver["states"]) == 40


def test_closed_functional_data_denominators_match_runtime_indexes() -> None:
    assert len(PAGES) == 732
    assert len(set(row["family"] for row in PAGES.values())) == 11
    assert len(DOWNLOADS) == 480
    assert len({row["sha256"] for row in DOWNLOADS.values()}) == 478
    assert sum(int(row["bytes"]) for row in DOWNLOADS.values()) == 1_551_223_348
    assert len(ASSET_URL_MAP) == 231
    assert sum(int(row["bytes"]) for row in DATA["presentation_assets"].values()) == 35_298_609
    assert len(UNAVAILABLE_ASSETS) == 5
    status = DATA["final_denominator_status"]
    assert status["status"] == "g4-candidate-frozen-for-g5"
    assert status["presentation_assets"] == 288
    assert status["presentation_asset_bytes"] == 50_418_009
    assert status["unavailable_assets"] == 9
    assert status["formal_visual_checkpoints"] == 35
    assert status["semantic_only_visual_input_gaps"] == 5
    assert status["controls"] == 30
    assert status["local_capabilities"] == 7
    assert status["p0_p1_journeys"] == 10
    assert status["supplementary_course_archives"] == 1
    assert status["supplementary_course_archive_bytes"] == 173_887_153
    assert status["deferred"] == [
        "five-semantic-only-visual-input-gaps",
        "blind-evaluation",
        "formal-acceptance",
    ]
    assert "/not-in-scope" not in VERIFY["routes"].values()


def test_all_boot_read_paths_remain_inside_the_site_root() -> None:
    for value in VERIFY["boot"]["read_paths"]:
        relative = Path(value)
        assert not relative.is_absolute()
        resolved = (SITE_ROOT / relative).resolve()
        resolved.relative_to(SITE_ROOT.resolve())
        assert resolved.is_dir()
