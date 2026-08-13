"""Declarative site profile loading and inventory binding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diagnostics import SiteCompilerError
from .inventory import LoadedInventory
from .schema import load_json_document

PROFILE_SCHEMA = "offline-clone-site-profile.schema.json"


@dataclass(frozen=True)
class LoadedProfile:
    path: Path
    data: dict[str, Any]
    inventory_row: dict[str, Any]


def load_profile(path: Path, inventory: LoadedInventory) -> LoadedProfile:
    resolved = path.resolve()
    value = load_json_document(resolved, PROFILE_SCHEMA)
    inventory_id = int(value["inventory_id"])
    row = inventory.by_id.get(inventory_id)
    if row is None:
        raise SiteCompilerError(
            f"{resolved}: inventory_id {inventory_id} is not present in "
            f"{inventory.path}"
        )

    comparisons = {
        "display_name": "platform",
        "official_url": "official_url",
    }
    problems: list[str] = []
    for profile_field, inventory_field in comparisons.items():
        if value[profile_field] != row[inventory_field]:
            problems.append(
                f"{resolved}:{profile_field} does not match inventory "
                f"{inventory_field}: {value[profile_field]!r} != "
                f"{row[inventory_field]!r}"
            )
    metadata = value["inventory_metadata"]
    for field in (
        "category",
        "topdown_category",
        "source_provenance",
        "frontend_complexity",
        "backend_statefulness",
        "authentication",
        "agent_task_family",
    ):
        if field in row and metadata.get(field) != row[field]:
            problems.append(
                f"{resolved}:inventory_metadata.{field} does not match inventory"
            )

    source_status = value["source_origin_status"]
    source_origins = value["source_origins"]
    if source_status == "valid":
        expected_origins = row.get("first_party_origins", [row["official_url"]])
        if source_origins != expected_origins:
            problems.append(
                f"{resolved}: valid source profile must preserve all inventory "
                "first-party origins in canonical order"
            )
    elif source_origins:
        problems.append(
            f"{resolved}: invalid inventory source URL must not be guessed into "
            "source_origins"
        )
    if problems:
        raise SiteCompilerError(problems)
    return LoadedProfile(
        path=resolved,
        data=value,
        inventory_row=row,
    )
