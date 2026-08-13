"""Stable artifact dependency graph for compiled site plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .diagnostics import SiteCompilerError


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str
    invalidates_from: str
    input_ids: tuple[str, ...]
    payload: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "invalidates_from": self.invalidates_from,
            "input_ids": list(self.input_ids),
            "payload": self.payload,
        }


class ArtifactGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}

    def add(
        self,
        node_id: str,
        *,
        kind: str,
        invalidates_from: str,
        inputs: tuple[str, ...] = (),
        payload: Any,
    ) -> GraphNode:
        if node_id in self._nodes:
            raise SiteCompilerError(f"duplicate compiler graph node: {node_id}")
        missing = [item for item in inputs if item not in self._nodes]
        if missing:
            raise SiteCompilerError(
                f"graph node {node_id!r} references unknown inputs: "
                + ", ".join(missing)
            )
        node = GraphNode(
            node_id=node_id,
            kind=kind,
            invalidates_from=invalidates_from,
            input_ids=inputs,
            payload=payload,
        )
        self._nodes[node_id] = node
        return node

    def as_list(self) -> list[dict[str, Any]]:
        return [node.as_dict() for node in self._nodes.values()]
