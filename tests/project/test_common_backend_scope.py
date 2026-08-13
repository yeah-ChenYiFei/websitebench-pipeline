from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from websitebench.offline_clone.backend_model import load_backend_model


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def require_site(site_id: str) -> Path:
    """The site's material, or a skip when this checkout does not carry it."""
    site = REPOSITORY_ROOT / "materials" / site_id
    if not (site / "clone.yaml").is_file():
        pytest.skip(f"{site_id} material is absent from this checkout")
    return site


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_edx_direct_home_checkpoint_does_not_promote_local_course_tuple() -> None:
    site = require_site("edx")
    routes = _json(site / "scope" / "routes.json")["routes"]
    checkpoints = _json(site / "scope" / "checkpoints.json")["checkpoints"]
    route_by_id = {route["id"]: route for route in routes}

    home = route_by_id["home"]
    for state in ("loaded", "promo-banner"):
        assert home["state_variants"][state] == [
            {
                "id": "source.home-generic",
                "simulation": False,
                "source_evidence_kind": "direct",
                "source_boundary": (
                    "The screenshot proves the generic public home state only; "
                    "benchmark-local course_id/run_id assignments remain "
                    "unavailable as source facts."
                ),
            }
        ]

    home_checkpoints = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint["route_id"] == "home"
    ]
    assert len(home_checkpoints) == 9
    assert {
        checkpoint["variant_id"] for checkpoint in home_checkpoints
    } == {"source.home-generic", "source.home-mega-current"}
    assert {
        checkpoint["evidence_kind"] for checkpoint in home_checkpoints
    } == {"direct", "unavailable"}
    generic_home_checkpoints = [
        checkpoint
        for checkpoint in home_checkpoints
        if checkpoint["variant_id"] == "source.home-generic"
    ]
    assert len(generic_home_checkpoints) == 8
    assert all(
        checkpoint["evidence_kind"] == "direct"
        and checkpoint["acceptance_eligible"] is True
        for checkpoint in generic_home_checkpoints
        if checkpoint["viewport"] == "desktop"
    )
    assert all(
        checkpoint["evidence_kind"] == "unavailable"
        and checkpoint["acceptance_eligible"] is False
        and checkpoint["verification_kind"]
        == "source-limited-scroll-restored-structural-only"
        for checkpoint in generic_home_checkpoints
        if checkpoint["viewport"] != "desktop"
    )
    menu_checkpoint = next(
        checkpoint
        for checkpoint in home_checkpoints
        if checkpoint["variant_id"] == "source.home-mega-current"
    )
    assert menu_checkpoint["state"] == "learn-menu-open"
    assert menu_checkpoint["viewport"] == "desktop-wide"
    assert menu_checkpoint["evidence_kind"] == "direct"
    assert menu_checkpoint["acceptance_eligible"] is True

    local_cs50_variants = [
        variant
        for variants in home["state_variants"].values()
        for variant in variants
        if variant.get("id") == "cs50-harvardx-cs50x-2026"
    ]
    assert local_cs50_variants
    assert {
        variant["local_identity_evidence_tier"]
        for variant in local_cs50_variants
    } == {"structural-only"}
    assert {
        variant["source_evidence_kind"] for variant in local_cs50_variants
    } == {"unavailable"}


def test_edx_local_only_states_are_explicit_simulations() -> None:
    routes = _json(require_site("edx") / "scope" / "routes.json")["routes"]
    route_by_id = {route["id"]: route for route in routes}
    expected_states = {
        "home": {"search-focused"},
        "course-search": {"loading", "empty", "error"},
        "cs50-landing": {"synthetic-local-return"},
        "mit-ml-landing": {
            "synthetic-open-run-local",
            "synthetic-open-run-local-authenticated",
        },
        "ucsd-algorithms-landing": {
            "loaded",
            "enroll-cta",
            "synthetic-local-return",
        },
        "ibm-python-basics-landing": {
            "loaded",
            "enroll-cta",
            "synthetic-local-return",
        },
        "signin": {
            "synthetic-identity-disclosure",
            "signed-in",
            "unauthorized",
        },
        "track-select": {
            "audit-offered",
            "certificate-separated",
            "unauthorized",
            "closed-run-rejected",
            "illegal-track-rejected",
        },
        "dashboard": {
            "enrolled-course-row",
            "empty",
            "refresh-deterministic",
            "unauthorized",
        },
        "course-shell": {
            "frozen-shell",
            "unauthorized",
            "foreign-owner-denied",
        },
    }
    for route_id, state_ids in expected_states.items():
        state_variants = route_by_id[route_id]["state_variants"]
        for state_id in state_ids:
            variants = state_variants[state_id]
            assert variants, f"{route_id}.{state_id} must have variants"
            assert all(variant["simulation"] is True for variant in variants)
            assert {
                variant["source_evidence_kind"] for variant in variants
            } == {"unavailable"}
            assert {
                variant["boundary_kind"] for variant in variants
            } == {"explicit-local-simulation"}


def test_edx_mit_disclosure_and_mobile_auth_affordance_boundaries() -> None:
    site = require_site("edx")
    routes = _json(site / "scope" / "routes.json")["routes"]
    invariants = _json(site / "scope" / "invariants.json")["invariants"]
    model = load_backend_model(
        site / "backend" / "model.json",
        expected_site_id="edx",
    )

    mit_invariant_id = "course.mitml.synthetic-run-disclosure"
    generic_capabilities = {
        capability["id"]: capability
        for capability in model["capabilities"]
        if capability["id"] in {"session-lifecycle", "course-enrollment"}
    }
    assert set(generic_capabilities) == {
        "session-lifecycle",
        "course-enrollment",
    }
    assert all(
        mit_invariant_id not in capability["invariant_ids"]
        for capability in generic_capabilities.values()
    )
    mit_invariant = next(
        invariant
        for invariant in invariants
        if invariant["id"] == mit_invariant_id
    )
    assert mit_invariant["journey_ids"]
    assert all(
        journey_id.startswith("enroll.mit-ml.")
        for journey_id in mit_invariant["journey_ids"]
    )

    signin = next(route for route in routes if route["id"] == "signin")
    mobile_auth_links = [
        affordance
        for affordance in signin["affordances"]
        if affordance.get("state_ids") == ["form-shell"]
        and affordance.get("viewports") == ["mobile"]
        and affordance.get("label", "").casefold()
        in {"register tab", "forgot password"}
    ]
    assert {
        affordance["label"].casefold() for affordance in mobile_auth_links
    } == {"register tab", "forgot password"}
    assert all(
        affordance["source_evidence_kind"] == "direct"
        and affordance["destination_evidence_kind"] == "structural-only"
        and affordance["variant_ids"] == ["source.generic-login"]
        for affordance in mobile_auth_links
    )


def test_etsy_verified_auth_entity_axes_and_capture_quarantine() -> None:
    site = require_site("etsy")
    purpose = _json(site / "scope" / "purpose.json")
    journeys = _json(site / "scope" / "journeys.json")["journeys"]
    routes = _json(site / "scope" / "routes.json")["routes"]
    coverage = _json(site / "scope" / "coverage.json")
    checkpoints = _json(site / "scope" / "checkpoints.json")[
        "checkpoints"
    ]

    assert {
        "shopper.local-account-a",
        "shopper.local-account-b",
    } <= set(purpose["primary_actor_ids"])
    assert not any(
        "shopper.synthetic-local-account" in actor_id
        for actor_id in purpose["primary_actor_ids"]
    )
    assert {
        "seller.shop-owner",
        "marketplace.operator",
    } <= set(purpose["secondary_actor_ids"])
    mapping_by_actor = {
        row["canonical_actor_id"]: row
        for row in purpose["actor_identity_mappings"]
    }
    assert mapping_by_actor["shopper.local-account-a"][
        "auth_actor_id"
    ] == "auth.local-account"
    assert mapping_by_actor["shopper.local-account-b"][
        "owner_id"
    ] != mapping_by_actor["shopper.local-account-a"]["owner_id"]

    favorite_success = next(
        row for row in journeys if row["id"] == "favorite.success"
    )
    assert favorite_success["actor"] == "shopper.local-account-a"
    favorite_steps = " ".join(favorite_success["steps"]).casefold()
    assert "verified" in favorite_steps
    assert "/fixture/session" not in favorite_steps

    signin = next(
        route for route in routes if route["id"] == "sign-in-boundary"
    )
    assert signin["route_pattern"].startswith("/auth/login")
    assert "/fixture/session" not in json.dumps(signin)
    assert "local-auth-disclosure" in signin["states"]
    assert "synthetic-identity-disclosure" not in signin["states"]

    class_rows = {
        (row["entity"], row["capability"]): row
        for row in coverage["entity_capability_rows"]
        if str(row.get("id", "")).startswith("etsy-class.")
    }
    expected_classes = {
        "known",
        "reachable",
        "rich",
        "actionable/purchasable",
        "comparable",
        "source-verified",
        "locally-simulated",
    }
    for entity in {
        "wallet-fixture",
        "collar-fixture",
        "vase-fixture",
        "bookshelf-fixture",
        "listing-offer",
        "cart-line",
        "favorite",
        "local-account",
    }:
        assert {
            capability
            for candidate_entity, capability in class_rows
            if candidate_entity == entity
        } == expected_classes

    home_direct = [
        row
        for row in checkpoints
        if row.get("route_id") == "home"
        and row.get("state") == "loaded"
        and row.get("evidence_kind") == "direct"
        and row.get("viewport") in {"desktop", "tablet", "mobile"}
        and row.get("source_artifact_path")
    ]
    assert {row["viewport"] for row in home_direct} == {
        "desktop",
        "tablet",
        "mobile",
    }
    for checkpoint in home_direct:
        source = site / checkpoint["source_artifact_path"]
        with Image.open(source) as image:
            image.verify()

    legacy_capture = _json(
        site
        / "source-current"
        / "2026-07-25"
        / "capture-consolidated.json"
    )
    assert legacy_capture["authority_status"] == "superseded-quarantined"
    assert legacy_capture["admissible_for_direct_claims"] is False
    claims = [
        json.loads(line)
        for line in (
            site / "scope" / "claims.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hash_claim = next(
        row for row in claims if row["id"] == "source.capture.hash-closure"
    )
    assert "quarantined" in hash_claim["claim"].casefold()
    assert "immutable history" in hash_claim["limitations"].casefold()


def test_imdb_exact_source_tuples_p1_and_task_semantics() -> None:
    site = require_site("imdb")
    routes = _json(site / "scope" / "routes.json")["routes"]
    checkpoints = _json(site / "scope" / "checkpoints.json")[
        "checkpoints"
    ]
    journeys = _json(site / "scope" / "journeys.json")["journeys"]
    coverage = _json(site / "scope" / "coverage.json")
    model = load_backend_model(
        site / "backend" / "model.json",
        expected_site_id="imdb",
    )

    home = next(route for route in routes if route["id"] == "home")
    assert home["viewport_state_evidence"]["desktop"]["loaded"][
        "evidence_kind"
    ] == "direct"
    assert {
        home["viewport_state_evidence"][viewport]["loaded"][
            "evidence_kind"
        ]
        for viewport in ("tablet", "mobile")
    } == {"direct"}
    assert not any(
        row.get("route_id") == "home"
        and row.get("viewport") == "desktop"
        and row.get("evidence_kind") == "direct"
        for row in checkpoints
    )
    for checkpoint in checkpoints:
        assert checkpoint["state"] in next(
            route["states"]
            for route in routes
            if route["id"] == checkpoint["route_id"]
        )
        if checkpoint["evidence_kind"] == "direct":
            source = site / checkpoint["source_artifact_path"]
            with Image.open(source) as image:
                image.verify()

    p1_dimension = next(
        row
        for row in coverage["dimensions"]
        if row["id"] == "p1-interaction-rows"
    )
    assert len(p1_dimension["required_items"]) == 69
    assert {
        item.split(".", 1)[0] for item in p1_dimension["required_items"]
    } == {
        "chart-moviemeter",
        "chart-top",
        "find-search",
        "find-suggest",
        "home",
        "list-detail",
        "list-edit",
        "name-person",
        "title-episode",
        "title-media",
        "title-reviews",
        "title-series",
    }

    exact_tokens = {
        "watchlist-dark-knight": "tt0468569",
        "rate-interstellar": "tt0816692",
        "remove-rating-interstellar": "tt0816692",
        "create-list": "My Sci-Fi Favorites",
        "add-pulp-fiction-to-list": "tt0110912",
    }
    for family, token in exact_tokens.items():
        rows = [
            row
            for row in journeys
            if row.get("journey_family") == family
        ]
        assert rows
        assert all(
            token.casefold()
            in " ".join(row["steps"]).casefold()
            for row in rows
        )
        assert all(
            row.get("initial_state") and row.get("terminal_state")
            for row in rows
        )

    invariant_ids = {
        capability["id"]: set(capability["invariant_ids"])
        for capability in model["capabilities"]
    }
    assert "rating.validated.deletable" not in invariant_ids["watchlist"]
    assert "list.private-titles.membership" not in invariant_ids["rating"]
    assert "watchlist.idempotent.owned" not in invariant_ids[
        "private-lists"
    ]
