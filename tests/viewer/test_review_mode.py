from __future__ import annotations

from pathlib import Path

import pytest

from websitebench.viewer.review_mode import (
    ReviewModeConflict,
    ReviewModeError,
    ReviewSessionStore,
    empty_review_session,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ITEM_KEY = "offlineclone--amazon-shopping-mainline"


def finding_payload() -> dict:
    return {
        "severity": "p1",
        "category": "interaction",
        "target": {
            "checkpoint": "search-results",
            "viewport": "mobile",
            "route": "/search",
            "role": "anonymous",
            "state": "loaded",
        },
        "observation": "The filter closes before the selection is applied.",
        "expected": "The selected filter should remain visible.",
        "evidence_refs": ["artifacts/trajectory/search-mobile/actions.jsonl"],
    }


def test_session_isolated_by_item_key_and_revision(tmp_path: Path) -> None:
    store = ReviewSessionStore(tmp_path / "sessions", REPO_ROOT)

    empty = empty_review_session(ITEM_KEY)
    assert empty["revision"] == 0
    assert empty["session_id"].startswith("review-")

    saved = store.add_finding(
        ITEM_KEY,
        finding_payload(),
        expected_revision=0,
        reviewer="reviewer",
    )
    assert saved["revision"] == 1
    assert saved["findings"][0]["finding_id"].startswith("finding-")
    assert store.current(ITEM_KEY) == saved

    with pytest.raises(ReviewModeConflict):
        store.add_finding(
            ITEM_KEY,
            finding_payload(),
            expected_revision=0,
            reviewer="reviewer",
        )

def test_update_preserves_observation_and_exports_resolution(tmp_path: Path) -> None:
    store = ReviewSessionStore(tmp_path / "sessions", REPO_ROOT)
    saved = store.add_finding(
        ITEM_KEY,
        finding_payload(),
        expected_revision=0,
        reviewer="reviewer",
    )
    finding_id = saved["findings"][0]["finding_id"]
    updated = store.update_finding(
        ITEM_KEY,
        finding_id,
        {
            "status": "known_difference",
            "resolution": {
                "summary": "The source animation is unstable; retained as a known difference.",
                "evidence_refs": ["artifacts/visual/search-source-stability.json"],
            },
        },
        expected_revision=1,
    )
    assert updated["revision"] == 2
    assert updated["findings"][0]["observation"] == finding_payload()["observation"]
    assert updated["findings"][0]["status"] == "known_difference"

    bundle = store.export(item_key=ITEM_KEY)
    assert bundle["schema_version"] == "websitebench.viewer-review-session-export.v1"
    assert bundle["sessions"] == [updated]
    assert bundle["authority"] == "diagnostic-review-feedback-only"


def test_review_mode_rejects_sensitive_and_unknown_patch_content(tmp_path: Path) -> None:
    store = ReviewSessionStore(tmp_path / "sessions", REPO_ROOT)
    sensitive = finding_payload()
    sensitive["observation"] = "The test used password=super-secret-value."
    with pytest.raises(ReviewModeError, match="sensitive content"):
        store.add_finding(
            ITEM_KEY,
            sensitive,
            expected_revision=0,
            reviewer="reviewer",
        )

    saved = store.add_finding(
        ITEM_KEY,
        finding_payload(),
        expected_revision=0,
        reviewer="reviewer",
    )
    with pytest.raises(ReviewModeError, match="require a resolution summary"):
        store.update_finding(
            ITEM_KEY,
            saved["findings"][0]["finding_id"],
            {"status": "resolved"},
            expected_revision=1,
        )
    with pytest.raises(ReviewModeError, match="unsupported finding patch fields"):
        store.update_finding(
            ITEM_KEY,
            saved["findings"][0]["finding_id"],
            {"technical_gate": "passed"},
            expected_revision=1,
        )
