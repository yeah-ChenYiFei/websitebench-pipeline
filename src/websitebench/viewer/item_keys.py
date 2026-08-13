"""Canonical Viewer item-key validation and compatibility migration."""

from __future__ import annotations

import re


CANONICAL_ITEM_KEY_PATTERN = (
    r"^(?:offlineclone|websitebench)--[a-z0-9]+(?:-[a-z0-9]+)*$"
)
CANONICAL_ITEM_KEY_RE = re.compile(CANONICAL_ITEM_KEY_PATTERN)
LEGACY_OFFLINE_PREFIX = "offline-clone--"
RETIRED_LEGACY_PREFIX = "legacy--"


class ItemKeyError(ValueError):
    pass


class RetiredItemKeyError(ItemKeyError):
    pass


def require_canonical_item_key(value: str) -> str:
    if not CANONICAL_ITEM_KEY_RE.fullmatch(value):
        raise ItemKeyError(
            "Viewer item keys must use offlineclone--<site-id> or "
            "websitebench--<site-id>"
        )
    return value


def migrate_item_key(value: str) -> str:
    """Map supported pre-v2 keys and reject retired legacy task adapters."""

    if CANONICAL_ITEM_KEY_RE.fullmatch(value):
        return value
    if value.startswith(LEGACY_OFFLINE_PREFIX):
        candidate = "offlineclone--" + value.removeprefix(LEGACY_OFFLINE_PREFIX)
        return require_canonical_item_key(candidate)
    if value.startswith(RETIRED_LEGACY_PREFIX):
        raise RetiredItemKeyError(
            f"retired legacy Viewer item has no migration target: {value}"
        )
    raise ItemKeyError(f"unsupported Viewer item key: {value}")
