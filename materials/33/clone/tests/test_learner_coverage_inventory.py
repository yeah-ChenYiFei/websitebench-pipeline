from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source_inventory import VALID_STATUSES, iter_entries, load_inventory


SITE_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = SITE_ROOT / "scope" / "learner-coverage.json"
JOURNEYS_PATH = SITE_ROOT / "scope" / "journeys.json"


def _frozen_journey_ids() -> set[str]:
    import json

    return {entry["id"] for entry in json.loads(JOURNEYS_PATH.read_text())["journeys"]}


def test_inventory_has_unique_entries_and_represents_every_frozen_journey() -> None:
    inventory = load_inventory(INVENTORY_PATH)
    entries = iter_entries(inventory)
    ids = [entry["id"] for entry in entries]

    assert inventory["schema_version"] == "websitebench.learner-coverage.v1"
    assert inventory["site_id"] == "33"
    assert len(ids) == len(set(ids))
    assert {entry["baseline_journey_id"] for entry in entries if entry["baseline_journey_id"]} == _frozen_journey_ids()


def test_inventory_entries_have_explicit_routes_evidence_status_and_test_contract() -> None:
    inventory = load_inventory(INVENTORY_PATH)
    required = {
        "id",
        "surface",
        "source_route",
        "local_route",
        "state",
        "evidence_status",
        "core",
        "backend_capability",
        "test_modules",
        "status",
    }

    for entry in iter_entries(inventory):
        assert required <= entry.keys(), entry["id"]
        assert entry["source_route"].startswith("/"), entry["id"]
        assert entry["local_route"].startswith("/"), entry["id"]
        assert entry["status"] in VALID_STATUSES, entry["id"]
        assert isinstance(entry["test_modules"], list) and entry["test_modules"], entry["id"]
        if entry["core"]:
            assert entry["backend_capability"], entry["id"]


def test_direct_source_complete_entries_point_to_existing_evidence() -> None:
    inventory = load_inventory(INVENTORY_PATH)
    for entry in iter_entries(inventory):
        if entry["status"] != "direct-source-complete":
            continue
        for reference in entry["evidence_refs"]:
            assert (SITE_ROOT / reference.split("#", 1)[0]).is_file(), entry["id"]


def test_inventory_rejects_unknown_statuses(tmp_path: Path) -> None:
    import json

    source = {
        "schema_version": "websitebench.learner-coverage.v1",
        "site_id": "33",
        "entries": [{"id": "bad", "status": "invented"}],
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(source))

    with pytest.raises(ValueError, match="unknown status"):
        load_inventory(path)
