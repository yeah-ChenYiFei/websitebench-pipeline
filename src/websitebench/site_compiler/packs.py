"""Capability-pack loading, dependency resolution, and conflict checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diagnostics import SiteCompilerError
from .schema import load_json_document

PACK_SCHEMA = "offline-clone-capability-pack.schema.json"


@dataclass(frozen=True)
class LoadedPack:
    path: Path
    data: dict[str, Any]

    @property
    def pack_id(self) -> str:
        return str(self.data["pack_id"])


def load_pack_directory(root: Path) -> dict[str, LoadedPack]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise SiteCompilerError(f"capability pack root is unavailable: {resolved}")
    packs: dict[str, LoadedPack] = {}
    for path in sorted(resolved.glob("*/pack.json"), key=lambda item: item.as_posix()):
        value = load_json_document(path, PACK_SCHEMA)
        pack = LoadedPack(path=path.resolve(), data=value)
        if pack.pack_id in packs:
            raise SiteCompilerError(
                f"duplicate capability pack id {pack.pack_id!r}: "
                f"{packs[pack.pack_id].path} and {pack.path}"
            )
        if path.parent.name != pack.pack_id:
            raise SiteCompilerError(
                f"{path}: parent directory must equal pack_id {pack.pack_id!r}"
            )
        packs[pack.pack_id] = pack
    if not packs:
        raise SiteCompilerError(f"no */pack.json capability packs found in {resolved}")
    return packs


def resolve_packs(
    available: dict[str, LoadedPack],
    requested: list[str],
) -> list[LoadedPack]:
    missing = sorted(set(requested) - set(available))
    if missing:
        raise SiteCompilerError(
            "unknown requested capability packs: " + ", ".join(missing)
        )

    selected: set[str] = set()

    def collect(pack_id: str, stack: tuple[str, ...]) -> None:
        if pack_id in stack:
            cycle = " -> ".join((*stack, pack_id))
            raise SiteCompilerError(f"capability pack dependency cycle: {cycle}")
        if pack_id in selected:
            return
        pack = available.get(pack_id)
        if pack is None:
            raise SiteCompilerError(
                f"capability pack {stack[-1]!r} requires unknown pack {pack_id!r}"
            )
        for dependency in pack.data["requires"]:
            collect(dependency, (*stack, pack_id))
        selected.add(pack_id)

    for pack_id in requested:
        collect(pack_id, ())

    problems: list[str] = []
    for pack_id in sorted(selected):
        conflicts = set(available[pack_id].data["conflicts"]) & selected
        for other in sorted(conflicts):
            if pack_id < other:
                problems.append(
                    f"capability packs {pack_id!r} and {other!r} conflict"
                )
    if problems:
        raise SiteCompilerError(problems)

    ordered: list[LoadedPack] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(pack_id: str) -> None:
        if pack_id in visited:
            return
        if pack_id in visiting:
            raise SiteCompilerError(f"capability pack dependency cycle at {pack_id}")
        visiting.add(pack_id)
        for dependency in sorted(available[pack_id].data["requires"]):
            if dependency in selected:
                visit(dependency)
        visiting.remove(pack_id)
        visited.add(pack_id)
        ordered.append(available[pack_id])

    for pack_id in sorted(selected):
        visit(pack_id)
    return ordered
