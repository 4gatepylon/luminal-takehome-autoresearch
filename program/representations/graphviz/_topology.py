"""Stable topological layers for directed acyclic graphs."""

from collections.abc import Hashable, Iterable
from typing import TypeVar


Node = TypeVar("Node", bound=Hashable)


def topological_layers(
    nodes: Iterable[Node], edges: Iterable[tuple[Node, Node]]
) -> list[list[Node]]:
    """Group nodes by longest-path depth, preserving input order within a layer.

    Edges are (parent, child) pairs. Duplicate edges and nodes are harmless.
    Unknown endpoints and cycles raise ValueError. Empty graphs return [].
    Time and space are O(V + E).
    """
    ordered = list(dict.fromkeys(nodes))
    children: dict[Node, list[Node]] = {node: [] for node in ordered}
    indegree = dict.fromkeys(ordered, 0)
    seen = set()
    for parent, child in edges:
        if parent not in children or child not in children:
            raise ValueError(f"unknown edge endpoint: {(parent, child)!r}")
        if (parent, child) not in seen:
            seen.add((parent, child))
            children[parent].append(child)
            indegree[child] += 1

    ready = [node for node in ordered if indegree[node] == 0]
    depth = dict.fromkeys(ordered, 0)
    visited = 0
    while ready:
        following = []
        for parent in ready:
            visited += 1
            for child in children[parent]:
                depth[child] = max(depth[child], depth[parent] + 1)
                indegree[child] -= 1
                if indegree[child] == 0:
                    following.append(child)
        ready = following
    if visited != len(ordered):
        raise ValueError("graph contains a cycle")

    layers: list[list[Node]] = []
    for node in ordered:
        while len(layers) <= depth[node]:
            layers.append([])
        layers[depth[node]].append(node)
    return layers
