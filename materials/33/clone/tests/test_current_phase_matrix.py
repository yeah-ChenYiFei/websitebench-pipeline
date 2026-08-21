import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[2]
FROZEN_JOURNEYS_PATH = SITE_ROOT / "scope" / "journeys.json"
CURRENT_PHASE_PATH = SITE_ROOT / "scope" / "current-accessible-fullscreen-phase.json"
VERIFY_PATH = SITE_ROOT / "scope" / "verify.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_current_phase_covers_every_frozen_journey_once_at_fullscreen_viewport():
    frozen = _read_json(FROZEN_JOURNEYS_PATH)
    current = _read_json(CURRENT_PHASE_PATH)

    trace_journeys = [
        journey
        for journey in frozen["journeys"]
        if str(journey.get("human_trace_text_id", "")).startswith("trace-")
    ]
    expected_ids = {journey["id"] for journey in trace_journeys}
    coverage = current["coverage"]

    assert current["schema_version"] == "current-accessible-fullscreen-phase.v1"
    assert current["viewport"] == {"width": 1692, "height": 979}
    assert len(coverage) == len(trace_journeys)
    assert {entry["journey_id"] for entry in coverage} == expected_ids
    assert len({entry["journey_id"] for entry in coverage}) == len(coverage)
    assert all(entry["current_boundary"] for entry in coverage)
    assert all(entry["deferred_boundary"] for entry in coverage)

    implementation = current["clone_functional_implementation"]
    assert implementation["status"] == (
        "pre-enrollment-scope-implemented-post-enrollment-deferred"
    )
    assert implementation["source_evidence_status_is_independent"] is True
    assert len(implementation["journey_ids"]) == 14
    assert len(implementation["deferred_post_enrollment_journey_ids"]) == 9
    assert set(implementation["journey_ids"]) | set(
        implementation["deferred_post_enrollment_journey_ids"]
    ) == expected_ids
    assert set(implementation["journey_ids"]).isdisjoint(
        implementation["deferred_post_enrollment_journey_ids"]
    )
    assert "payment-credential-entry" in implementation["forbidden_external_effects"]
    assert implementation["local_only_mutations"] == ["registration", "onboarding"]


def test_current_phase_stops_sensitive_and_unobserved_journeys_at_the_agreed_boundary():
    current = _read_json(CURRENT_PHASE_PATH)
    coverage = {entry["journey_id"]: entry for entry in current["coverage"]}

    for journey_id in ("learning.lesson", "learning.quiz-feedback", "learning.progress"):
        assert coverage[journey_id]["phase_status"] == "deferred"

    for journey_id in (
        "enrollment.deep-learning-review",
        "enrollment.paid-review",
        "task265.deep-learning-review",
    ):
        assert coverage[journey_id]["stop_state"] == "empty-payment-fields"

    assert coverage["catalog.preview"]["phase_status"] == "conditional-source-observation"
    assert current["source_mutation_policy"] == {
        "public_methods": ["GET"],
        "authorized_navigation": "user-assisted-empty-payment-page-only",
        "forbidden_submissions": [
            "account-creation",
            "enrollment",
            "trial",
            "payment",
            "quiz",
            "review",
            "cancellation",
            "recovery-mail",
        ],
    }


def test_every_current_phase_result_has_resolvable_evidence_and_unobserved_states_are_honest():
    """Catch an inaccessible source state being described as directly observed."""

    current = _read_json(CURRENT_PHASE_PATH)
    coverage = {entry["journey_id"]: entry for entry in current["coverage"]}

    for entry in coverage.values():
        assert entry["evidence_refs"], entry["journey_id"]
        for reference in entry["evidence_refs"]:
            relative_path = reference.split("#", 1)[0]
            assert (SITE_ROOT / relative_path).is_file(), reference

    expected_authenticated_evidence = {
        "auth.login-dashboard": "captured-authenticated-empty-account-en",
        "learning.preferences": "captured-authenticated-account-settings-en",
        "history.seeded": "captured-authenticated-empty-purchases-en",
    }
    for journey_id, evidence_status in expected_authenticated_evidence.items():
        assert coverage[journey_id]["source_evidence_status"] == evidence_status
        assert "captured" in coverage[journey_id]["current_boundary"].lower()

    for journey_id in (
        "enrollment.deep-learning-review",
        "enrollment.track-selection",
        "enrollment.paid-review",
        "task265.deep-learning-review",
    ):
        assert "not-authorized" in coverage[journey_id]["source_evidence_status"]
        assert "signed-out" in coverage[journey_id]["current_boundary"].lower()
        assert "empty payment" in coverage[journey_id]["deferred_boundary"].lower()


def test_current_anonymous_diagnostic_excludes_deferred_learning_and_payment_review():
    """Catch historical compatibility recipes being presented as current fidelity."""

    driver = _read_json(VERIFY_PATH)

    assert "session" not in driver
    assert set(driver["routes"]).isdisjoint(
        {
            "my-learning",
            "lesson",
            "quiz",
            "account-history",
            "preferences",
            "checkout",
            "payments-checkout",
        }
    )
    assert set(driver["states"]).isdisjoint(
        {
            "my-learning.progress",
            "lesson.opened",
            "quiz.feedback",
            "account-history.seeded",
            "checkout.validation",
            "checkout.review",
        }
    )
    assert set(driver["deferred"]) == {
        "my-learning",
        "lesson",
        "quiz",
        "account-history",
        "checkout",
    }
    assert set(driver["states_out_of_scope"]) >= {
        "source-authenticated-empty-account",
        "source-enrolled-learning",
        "source-empty-payment",
        "source-payment-review-confirmation",
    }
