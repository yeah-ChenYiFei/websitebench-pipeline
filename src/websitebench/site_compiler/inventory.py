"""Generic WebsiteBench platform inventory loading and lookup."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diagnostics import SiteCompilerError
from .schema import load_json_document

INVENTORY_SCHEMA = "offline-clone-platform-inventory.schema.json"


@dataclass(frozen=True)
class LoadedInventory:
    path: Path
    data: dict[str, Any]
    by_id: dict[int, dict[str, Any]]


def load_inventory(path: Path) -> LoadedInventory:
    resolved = path.resolve()
    value = load_json_document(resolved, INVENTORY_SCHEMA)
    by_id: dict[int, dict[str, Any]] = {}
    platform_names: set[str] = set()
    platform_keys: set[str] = set()
    sources = value["provenance"]["sources"]
    source_ids = [source["source_id"] for source in sources]
    duplicate_sources = sorted(
        source_id for source_id, count in Counter(source_ids).items() if count > 1
    )
    if duplicate_sources:
        raise SiteCompilerError(
            f"{resolved}: duplicate provenance source IDs: "
            + ", ".join(duplicate_sources)
        )
    known_source_ids = set(source_ids)
    used_source_ids: set[str] = set()
    for row in value["platforms"]:
        inventory_id = int(row["inventory_id"])
        if inventory_id in by_id:
            raise SiteCompilerError(f"{resolved}: duplicate inventory_id {inventory_id}")
        normalized_name = str(row["platform"]).casefold()
        if normalized_name in platform_names:
            raise SiteCompilerError(
                f"{resolved}: duplicate case-insensitive platform {row['platform']!r}"
            )
        platform_names.add(normalized_name)
        platform_key = str(row["platform_key"])
        if platform_key in platform_keys:
            raise SiteCompilerError(
                f"{resolved}: duplicate platform_key {platform_key!r}"
            )
        platform_keys.add(platform_key)
        unknown_sources = sorted(set(row["source_ids"]) - known_source_ids)
        if unknown_sources:
            raise SiteCompilerError(
                f"{resolved}: inventory_id {inventory_id} references unknown "
                f"source IDs: {', '.join(unknown_sources)}"
            )
        used_source_ids.update(row["source_ids"])
        by_id[inventory_id] = row
    unused_source_ids = sorted(known_source_ids - used_source_ids)
    if unused_source_ids:
        raise SiteCompilerError(
            f"{resolved}: unused provenance source IDs: "
            + ", ".join(unused_source_ids)
        )
    declared = value["summary"]["platform_count"]
    if declared != len(by_id):
        raise SiteCompilerError(
            f"{resolved}: summary.platform_count={declared} but "
            f"{len(by_id)} platform rows were loaded"
        )
    category_counts = Counter(row["category"] for row in value["platforms"])
    declared_category_counts = value["summary"]["category_counts"]
    if declared_category_counts != dict(sorted(category_counts.items())):
        raise SiteCompilerError(
            f"{resolved}: summary.category_counts does not match platform rows"
        )
    if value["summary"]["category_count"] != len(category_counts):
        raise SiteCompilerError(
            f"{resolved}: summary.category_count does not match platform rows"
        )
    invalid_count = sum(
        row["official_url_status"] != "valid" for row in value["platforms"]
    )
    if value["summary"]["invalid_source_url_count"] != invalid_count:
        raise SiteCompilerError(
            f"{resolved}: summary.invalid_source_url_count does not match "
            "platform rows"
        )
    return LoadedInventory(
        path=resolved,
        data=value,
        by_id=by_id,
    )
