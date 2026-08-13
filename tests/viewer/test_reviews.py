from __future__ import annotations

import json
from pathlib import Path

import pytest

from websitebench.viewer.reviews import (
    DIMENSIONS,
    ReviewConflict,
    ReviewError,
    ReviewStore,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def payload(*, decision: str = "approve", visibility: str = "internal") -> dict:
    return {
        "reviewer": "reviewer",
        "decision": decision,
        "visibility": visibility,
        "dimensions": {
            name: {"rating": "pass", "notes": "checked", "evidence_refs": []}
            for name in DIMENSIONS
        },
        "notes": "reviewed",
        "evidence_refs": [],
    }


def test_atomic_save_revision_conflict_and_restart_persistence(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    key = "offlineclone--amazon-shopping-mainline"
    store = ReviewStore(root, REPO_ROOT)
    saved = store.save(
        key,
        payload(),
        expected_revision=0,
    )
    assert saved["revision"] == 1
    with pytest.raises(ReviewConflict):
        store.save(
            key,
            payload(),
            expected_revision=0,
        )
    restarted = ReviewStore(root, REPO_ROOT)
    assert restarted.load(key) == saved


def test_import_conflict_rejects_entire_batch(tmp_path: Path) -> None:
    key = "offlineclone--amazon-shopping-mainline"
    existing = ReviewStore(tmp_path / "reviews", REPO_ROOT)
    saved = existing.save(key, payload(), expected_revision=0)
    second_store = ReviewStore(tmp_path / "source", REPO_ROOT)
    second = second_store.save(
        "websitebench--second-site",
        payload(),
        expected_revision=0,
    )
    bundle = {
        "schema_version": "websitebench.viewer-review-export.v3",
        "exported_at": saved["updated_at"],
        "reviews": [saved, second],
    }
    with pytest.raises(ReviewConflict):
        existing.import_batch(bundle)
    assert existing.load(second["item_key"]) is None


def test_public_review_rejects_private_evidence_reference(tmp_path: Path) -> None:
    value = payload(visibility="public")
    value["evidence_refs"] = ["judge/fixtures/9101.json"]
    with pytest.raises(ValueError, match="private fixture"):
        ReviewStore(tmp_path, REPO_ROOT).save(
            "offlineclone--amazon-shopping-mainline",
            value,
            expected_revision=0,
        )


def test_v1_import_migrates_supported_offline_clone_key(tmp_path: Path) -> None:
    source = ReviewStore(tmp_path / "source", REPO_ROOT)
    review = source.save(
        "offlineclone--amazon-shopping-mainline",
        payload(),
        expected_revision=0,
    )
    review["schema_version"] = "websitebench.viewer-review.v1"
    review["item_key"] = "offline-clone--amazon-shopping-mainline"
    review["artifact_fingerprint"] = "a" * 64
    review["gate"] = review.pop("decision")
    bundle = {
        "schema_version": "websitebench.viewer-review-export.v1",
        "exported_at": review["updated_at"],
        "reviews": [review],
    }

    destination = ReviewStore(tmp_path / "destination", REPO_ROOT)
    imported = destination.import_batch(
        bundle,
        known_item_keys={"offlineclone--amazon-shopping-mainline"},
    )

    assert imported[0]["schema_version"] == "websitebench.viewer-review.v3"
    assert imported[0]["item_key"] == "offlineclone--amazon-shopping-mainline"
    assert destination.load(imported[0]["item_key"]) == imported[0]


def test_v1_import_rejects_retired_legacy_key(tmp_path: Path) -> None:
    source = ReviewStore(tmp_path / "source", REPO_ROOT)
    review = source.save(
        "offlineclone--amazon-shopping-mainline",
        payload(),
        expected_revision=0,
    )
    review["schema_version"] = "websitebench.viewer-review.v1"
    review["item_key"] = "legacy--dev-115-freshdesk-invoice-dispute-ticket"
    review["artifact_fingerprint"] = "a" * 64
    review["gate"] = review.pop("decision")
    bundle = {
        "schema_version": "websitebench.viewer-review-export.v1",
        "exported_at": review["updated_at"],
        "reviews": [review],
    }

    with pytest.raises(ReviewError, match="no migration target"):
        ReviewStore(tmp_path / "destination", REPO_ROOT).import_batch(bundle)


def test_v2_review_is_parsed_without_rewriting_the_historical_file(
    tmp_path: Path,
) -> None:
    key = "offlineclone--amazon-shopping-mainline"
    root = tmp_path / "reviews"
    store = ReviewStore(root, REPO_ROOT)
    current = store.save(key, payload(), expected_revision=0)
    historical = {
        **current,
        "schema_version": "websitebench.viewer-review.v2",
        "artifact_fingerprint": "b" * 64,
        "gate": current["decision"],
    }
    historical.pop("decision")
    path = root / f"{key}.json"
    path.write_text(json.dumps(historical), encoding="utf-8")

    loaded = store.load(key)

    assert loaded is not None
    assert loaded["schema_version"] == "websitebench.viewer-review.v3"
    assert loaded["decision"] == "approve"
    assert "artifact_fingerprint" not in loaded
    assert json.loads(path.read_text(encoding="utf-8")) == historical
