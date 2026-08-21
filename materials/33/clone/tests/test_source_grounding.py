from __future__ import annotations

import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[2]


def test_known_differences_records_authenticated_source_limitations() -> None:
    """Prevent local simulations from being described as direct source evidence."""

    text = (SITE_ROOT / "KNOWN_DIFFERENCES.md").read_text(encoding="utf-8")

    assert "authenticated source" in text
    assert "not directly verified" in text


def test_scope_does_not_claim_authenticated_source_visuals_are_directly_verified() -> None:
    """The frozen coverage scope must keep direct and local-only evidence distinct."""

    coverage = json.loads(
        (SITE_ROOT / "scope" / "coverage.json").read_text(encoding="utf-8")
    )
    dimensions = {item["id"]: item for item in coverage["dimensions"]}

    assert dimensions["authenticated-simulation"]["source_evidence_kind"] == (
        "unavailable"
    )
    assert dimensions["checkout-local-sandbox"]["source_evidence_kind"] == (
        "unavailable"
    )
    assert dimensions["public-desktop-visual-oracles"]["source_evidence_kind"] == (
        "direct"
    )
    assert all(
        "authenticated" not in item
        for item in dimensions["public-desktop-visual-oracles"]["required_items"]
    )


def test_coverage_structures_retained_source_artifact_scope() -> None:
    """Catch authenticated or payment source states entering public visual oracles."""

    coverage = json.loads(
        (SITE_ROOT / "scope" / "coverage.json").read_text(encoding="utf-8")
    )
    dimensions = {item["id"]: item for item in coverage["dimensions"]}
    scope = dimensions["retained-source-artifact-scope"]
    rows = {item["id"]: item for item in scope["denominator_rows"]}

    public_rows = {
        item["checkpoint"]: item
        for item in rows.values()
        if item["actor"] == "anonymous"
    }
    assert set(public_rows) == set(
        dimensions["public-desktop-visual-oracles"]["required_items"]
    )
    assert all(
        item["retained_source_artifact"] is True
        and item["artifact_scope"] == "public-visual-oracle"
        for item in public_rows.values()
    )

    restricted_rows = [item for item in rows.values() if item["actor"] == "authenticated"]
    assert {item["id"] for item in restricted_rows} == {
        "authenticated-account-learning",
        "authenticated-recovery",
        "authenticated-checkout-display",
    }
    assert all(item["retained_source_artifact"] is False for item in restricted_rows)
    assert rows["authenticated-checkout-display"]["display_facts_observed"] is True


def test_task3_reconstruction_maps_assets_layout_and_copy_to_current_ea_evidence() -> (
    None
):
    observations_path = SITE_ROOT / "source-evidence" / "task3-ea-observations.json"
    provenance_path = SITE_ROOT / "source-evidence" / "task3-provenance.json"
    assert observations_path.is_file()
    assert provenance_path.is_file()

    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    evidence_ids = {item["id"] for item in observations["observations"]}
    assert {item["explorer"] for item in observations["observations"]} == {
        "EA1",
        "EA2",
    }
    assert all(item["sanitized"] is True for item in observations["observations"])

    manifest = json.loads(
        (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
    )
    task3_assets = [
        item for item in manifest["assets"] if item["id"].startswith("task3-")
    ]
    runtime_assets = {item["runtime_path"] for item in task3_assets}
    assert {item["evidence_kind"] for item in task3_assets} == {"synthetic"}
    direct_public_assets = [
        item for item in manifest["assets"] if item["evidence_kind"] == "current-direct"
    ]
    legacy_public_ids = {
        "current-live-home-promo-plus",
        "current-live-home-promo-teams",
        "current-live-home-promo-third",
        "current-live-home-promo-barriers",
        "current-live-home-promo-teams-small",
        "task7-home-career-promo",
        "task7-home-google-promo",
        "task7-home-trend-google-ai",
        "task7-home-trend-google-analytics",
        "task7-home-trend-microsoft-qa",
    }
    # The owner-authorized real CSS layer adds more current-direct assets; the
    # pre-existing public collection must remain fully present.
    assert legacy_public_ids <= {item["id"] for item in direct_public_assets}
    assert any(item["id"].startswith("coursera-") for item in direct_public_assets)
    legacy_direct = [
        item for item in direct_public_assets if item["id"] in legacy_public_ids
    ]
    assert all(item["source_url"] == "https://www.coursera.org/" for item in legacy_direct)
    assert {"public-home-desktop", "coursera-home-login-current-state-open-home"} <= {
        item["capture_id"] for item in legacy_direct
    }
    asset_provenance = {
        item["runtime_path"]: item for item in provenance["runtime_assets"]
    }
    assert asset_provenance.keys() == runtime_assets
    for mapping in asset_provenance.values():
        assert mapping["reconstruction_kind"] == "synthetic-reconstruction"
        assert mapping["grounded_by"]
        assert set(mapping["grounded_by"]) <= evidence_ids
        assert mapping["source_material_status"] in {
            "reconstructed-from-current-observation",
            "source-asset-unavailable-synthetic-stand-in",
        }

    expected_choices = {
        "layout-shared-chrome",
        "layout-home-hero-cards",
        "layout-browse-categories",
        "layout-search-filter-results",
        "layout-specialization-series",
        "layout-course-detail",
        "layout-auth-entry",
        "layout-support-contact",
        "layout-not-found-recovery",
        "copy-source-observed-labels",
        "copy-offline-disclosures",
    }
    choices = {item["id"]: item for item in provenance["choices"]}
    assert choices.keys() == expected_choices
    for mapping in choices.values():
        assert mapping["grounded_by"]
        assert set(mapping["grounded_by"]) <= evidence_ids

    unavailable = provenance["unavailable_source_material"]
    assert {item["kind"] for item in unavailable} == {
        "third-party-fonts-and-css",
        "third-party-images-and-media",
    }
    assert all(item["status"] == "unavailable" for item in unavailable)


def test_retained_visual_oracle_matches_selected_ea2_route_and_explorer() -> None:
    """Catch retained EA2 browse bytes being attributed to the EA1 explorer."""

    observations = json.loads(
        (SITE_ROOT / "source-evidence" / "task3-ea-observations.json").read_text(
            encoding="utf-8"
        )
    )["observations"]
    selected = json.loads(
        (SITE_ROOT / "scope" / "derived-task-brief.json").read_text(encoding="utf-8")
    )["evidence"]["selected_visual_oracle"]
    artifact = selected.removeprefix("source-evidence/")
    matches = [item for item in observations if item["capture_artifact"] == artifact]

    assert matches == [
        {
            "id": "ea2-browse-retained",
            "explorer": "EA2",
            "route": "/browse",
            "sanitized": True,
            "capture_artifact": "browse.desktop.png",
            "observed": [
                "Explore Categories heading",
                "11 direct subject links",
                "Most popular course-card composition",
                "shared footer",
            ],
        }
    ]


def test_claims_resolve_to_committed_sanitized_observations() -> None:
    """Catch source claims depending on machine-local scratch evidence."""

    observations = json.loads(
        (SITE_ROOT / "source-evidence" / "task3-ea-observations.json").read_text(
            encoding="utf-8"
        )
    )["observations"]
    observation_ids = {item["id"] for item in observations if item["sanitized"]}
    capture_observations = json.loads(
        (SITE_ROOT / "source-evidence" / "desktop-public-captures.json").read_text(
            encoding="utf-8"
        )
    )["observations"]
    capture_ids = {item["id"] for item in capture_observations if item["sanitized"]}
    claims = [
        json.loads(line)
        for line in (SITE_ROOT / "scope" / "claims.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]

    for claim in claims:
        assert claim["evidence_refs"]
        for reference in claim["evidence_refs"]:
            task3_prefix = "source-evidence/task3-ea-observations.json#observation:"
            captures_prefix = (
                "source-evidence/desktop-public-captures.json#observation:"
            )
            if reference.startswith(task3_prefix):
                assert reference.removeprefix(task3_prefix) in observation_ids
            else:
                assert reference.startswith(captures_prefix)
                assert reference.removeprefix(captures_prefix) in capture_ids


def test_current_verify_contract_defers_source_inaccessible_learning_states() -> None:
    """Catch clone-local compatibility states being presented as source fidelity."""

    routes = json.loads(
        (SITE_ROOT / "scope" / "routes.json").read_text(encoding="utf-8")
    )["routes"]
    route_by_id = {item["id"]: item for item in routes}
    assert route_by_id["my-learning"]["route_pattern"] == "/my-learning"
    assert route_by_id["lesson"]["route_pattern"] == (
        "/learn/neural-networks-deep-learning/lesson/{lesson_id}"
    )
    assert route_by_id["quiz"]["route_pattern"] == "/learning/quizzes/{quiz_id}"

    driver = json.loads(
        (SITE_ROOT / "scope" / "verify.json").read_text(encoding="utf-8")
    )
    assert "session" not in driver
    assert {"my-learning", "lesson", "quiz", "account-history", "preferences"}.isdisjoint(
        driver["routes"]
    )
    assert {
        "my-learning.progress",
        "lesson.opened",
        "quiz.feedback",
        "account-history.seeded",
    }.isdisjoint(driver["states"])
    assert {"my-learning", "lesson", "quiz", "account-history"} <= set(
        driver["deferred"]
    )
    assert "source-enrolled-learning" in driver["states_out_of_scope"]


def test_current_verify_contract_does_not_claim_unobserved_payment_review() -> None:
    """Catch a clone-local sandbox review being presented as current source evidence."""

    driver = json.loads(
        (SITE_ROOT / "scope" / "verify.json").read_text(encoding="utf-8")
    )
    assert "session" not in driver
    assert {"checkout", "payments-checkout"}.isdisjoint(driver["routes"])
    assert {"checkout.validation", "checkout.review"}.isdisjoint(driver["states"])
    assert "checkout" in driver["deferred"]
    assert "source-empty-payment" in driver["states_out_of_scope"]
    assert "source-payment-review-confirmation" in driver["states_out_of_scope"]


def test_task3_css_identity_is_unchanged_and_checkout_css_is_task5_owned() -> None:
    """Catch checkout styling being folded into the historical Task 3 asset."""

    manifest = json.loads(
        (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
    )
    assets = {item["id"]: item for item in manifest["assets"]}
    task3 = assets["task3-components-css"]
    assert task3["source_path"] == "source-assets/task3/components.css"
    assert task3["runtime_path"] == "clone/static/components.css"
    assert task3["bytes"] == 3181
    task3_source = (SITE_ROOT / task3["source_path"]).read_bytes()
    task3_runtime = (SITE_ROOT / task3["runtime_path"]).read_bytes()
    assert task3_source == task3_runtime
    assert len(task3_source) == 3181
    assert b"checkout-shell" not in task3_source

    task5 = assets["task5-checkout-css"]
    assert task5["source_path"] == "source-assets/task5/checkout.css"
    assert task5["runtime_path"] == "clone/static/checkout.css"
    task5_source = (SITE_ROOT / task5["source_path"]).read_bytes()
    task5_runtime = (SITE_ROOT / task5["runtime_path"]).read_bytes()
    assert task5_source == task5_runtime
    assert len(task5_source) == task5["bytes"]
    assert b"checkout-shell" in task5_source

    provenance = json.loads(
        (SITE_ROOT / "source-evidence" / "task5-provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["runtime_assets"] == [
        {
            "asset_id": "task5-checkout-css",
            "runtime_path": "clone/static/checkout.css",
            "reconstruction_kind": "synthetic-reconstruction",
            "grounded_by": ["task5-safe-local-checkout-design"],
            "source_material_status": "task5-owned-synthetic-offline-style",
        }
    ]


def test_asset_manifest_records_task7_public_desktop_collection_identity() -> None:
    """Catch current public evidence being attributed to the pre-Task-7 collection."""

    manifest = json.loads(
        (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["snapshot_id"] == "33-task7-public-desktop-evidence"
    assert manifest["created_at"] == "2026-08-17T00:00:00Z"
    legacy_ids = {
        "current-live-home-promo-plus",
        "current-live-home-promo-teams",
        "current-live-home-promo-third",
        "current-live-home-promo-barriers",
        "current-live-home-promo-teams-small",
        "task3-site-css",
        "task3-components-css",
        "task3-auth-css",
        "task3-hero-learning",
        "task3-deep-learning-mark",
        "task5-checkout-css",
        "task7-home-career-promo",
        "task7-home-google-promo",
        "task7-home-trend-google-ai",
        "task7-home-trend-google-analytics",
        "task7-home-trend-microsoft-qa",
    }
    ids = {item["id"] for item in manifest["assets"]}
    # The authorized real CSS layer extends the manifest; the pre-existing
    # public collection must stay fully attributed to the Task-7 snapshot.
    assert legacy_ids <= ids
    assert any(item["id"].startswith("coursera-") for item in manifest["assets"])


def test_current_verify_has_no_authenticated_fixture_or_credentials() -> None:
    """Catch current anonymous diagnostics retaining a compatibility login fixture."""

    verify_path = SITE_ROOT / "scope" / "verify.json"
    raw = verify_path.read_text(encoding="utf-8")
    driver = json.loads(raw)

    assert "session" not in driver
    assert "Empty-Learner-33" not in raw
    assert "progress-learner" not in raw
