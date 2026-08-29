from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_site_registry_covers_catalog_and_matches_status_snapshot() -> None:
    registry = json.loads((ROOT / "sites" / "registry.json").read_text(encoding="utf-8"))
    sites = registry["sites"]

    assert registry["catalog_site_count"] == 331
    assert len(sites) == 331
    assert len({site["id"] for site in sites}) == 331
    assert len({site["catalog"]["id"] for site in sites}) == 331
    assert len({site["catalog"]["domain"] for site in sites}) == 331
    assert Counter(site["branch_status"] for site in sites) == {
        "final": 69,
        "review": 53,
        "review-required": 1,
        "planned": 208,
    }

    for site in sites:
        site_id = site["id"]
        assert site["branch"] == f"sites/{site_id}"
        assert site["material_path"].startswith("materials/")
        assert site["component_paths"][0] == site["material_path"]
        if site["branch_status"] == "planned":
            assert site["snapshot"] == {}
        else:
            assert site["snapshot"].get("sha")

    with (ROOT / "sites" / "status.tsv").open(encoding="utf-8", newline="") as handle:
        status_rows = list(csv.DictReader(handle, delimiter="\t"))

    assert len(status_rows) == 331
    assert {row["Site"] for row in status_rows} == {site["id"] for site in sites}
    assert sum(bool(row["Pipeline_PR"]) for row in status_rows) == 106
    assert Counter(row["Final_Status"] for row in status_rows) == {
        "final": 69,
        "not-final": 262,
    }
