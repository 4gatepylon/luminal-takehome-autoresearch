"""Construct forward and backward orders with latency and pressure priorities."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

import machine

from ...reordering import OperationDependencies


Policy = Literal["critical-path", "balanced", "pressure", "critical-first", "pressure-first"]
Direction = Literal["forward", "backward"]
_POLICIES = ("critical-path", "balanced", "pressure", "critical-first", "pressure-first")


class _Graph:
    """Weighted prerequisites, successors, and distinct SSA consumers."""

    def __init__(self, program: dict) -> None:
        operations = program["operations"]
        self.size = len(operations)
        specs = [machine.OP_SPECS[op["op"]] for op in operations]
        self.engines = [spec["engine"] for spec in specs]
        self.widths = [
            machine.VLEN if spec["result"] == "vector" else int(spec["result"] is not None)
            for spec in specs
        ]
        producer = machine.producer_map(program)
        self.inputs = [
            {producer[arg] for arg in op.get("args", [])} for op in operations
        ]
        self.consumers: list[set[int]] = [set() for _ in operations]
        self.predecessors: list[dict[int, int]] = []
        self.successors: list[dict[int, int]] = [{} for _ in operations]
        dependencies = OperationDependencies(program)
        for op_id, inputs in enumerate(self.inputs):
            predecessors = {
                pred["id"]: specs[pred["id"]]["latency"] if pred["id"] in inputs else 1
                for pred in dependencies.op_id2prev_ops[op_id]
            }
            self.predecessors.append(predecessors)
            for pred, delay in predecessors.items():
                self.successors[pred][op_id] = delay
            for pred in inputs:
                self.consumers[pred].add(op_id)

        # Edge delays constrain issue times; a terminal operation needs one
        # issue cycle, regardless of when its unused result eventually writes.
        self.height = [1] * self.size
        self.depth = [1] * self.size
        for op_id in range(self.size):
            self.depth[op_id] = max(
                (self.depth[pred] + delay for pred, delay in self.predecessors[op_id].items()),
                default=1,
            )
        for op_id in reversed(range(self.size)):
            self.height[op_id] = max(
                (self.height[succ] + delay for succ, delay in self.successors[op_id].items()),
                default=1,
            )


def _order(graph: _Graph, policy: Policy, direction: Direction) -> tuple[int, ...]:
    backward = direction == "backward"
    prerequisites = graph.successors if backward else graph.predecessors
    dependents = graph.predecessors if backward else graph.successors
    rank = graph.depth if backward else graph.height
    remaining = [len(preds) for preds in prerequisites]
    available = {op_id for op_id, count in enumerate(remaining) if count == 0}
    release = [0] * graph.size
    remaining_uses = [len(consumers) for consumers in graph.consumers]
    frontier: set[int] = set()
    ordering = []
    cycle = 0
    slots: dict[str, int] = {}

    while available:
        def priority(op_id: int) -> tuple:
            engine = graph.engines[op_id]
            issue = max(cycle, release[op_id])
            if issue == cycle and slots.get(engine, 0) == machine.ENGINE_LIMITS[engine]:
                issue += 1
            gap = issue - cycle
            if backward:
                added = sum(graph.widths[pred] for pred in graph.inputs[op_id] - frontier)
                removed = graph.widths[op_id] if op_id in frontier else 0
            else:
                added = graph.widths[op_id] if graph.consumers[op_id] else 0
                removed = sum(
                    graph.widths[pred] for pred in graph.inputs[op_id]
                    if remaining_uses[pred] == 1
                )
            delta = added - removed
            if policy == "critical-path":
                return gap, -rank[op_id], delta, op_id
            if policy == "balanced":
                return gap, delta, -rank[op_id], op_id
            if policy == "critical-first":
                return -rank[op_id], gap, delta, op_id
            if policy == "pressure-first":
                return delta, gap, -rank[op_id], op_id
            # Waiting for a consumer can close a wide live frontier before
            # opening another chain. This is a pressure proxy: actual scheduled
            # lifetimes, including pending and unused writes, are allocated later.
            return delta + machine.VLEN * gap, -rank[op_id], gap, op_id

        op_id = min(available, key=priority)
        engine = graph.engines[op_id]
        issue = max(cycle, release[op_id])
        if issue == cycle and slots.get(engine, 0) == machine.ENGINE_LIMITS[engine]:
            issue += 1
        if issue != cycle:
            cycle = issue
            slots = {}
        slots[engine] = slots.get(engine, 0) + 1
        ordering.append(op_id)
        available.remove(op_id)

        if backward:
            frontier.discard(op_id)
            frontier.update(graph.inputs[op_id])
        else:
            for pred in graph.inputs[op_id]:
                remaining_uses[pred] -= 1
        for succ, delay in dependents[op_id].items():
            remaining[succ] -= 1
            release[succ] = max(release[succ], cycle + delay)
            if remaining[succ] == 0:
                available.add(succ)

    if len(ordering) != graph.size:
        raise machine.CompileError("operation dependencies contain a cycle")
    return tuple(reversed(ordering)) if backward else tuple(ordering)


def dag_ordering(
    program: dict, *, policy: Policy = "balanced", direction: Direction = "forward"
) -> tuple[int, ...]:
    """Return original IDs in a valid order using a selected DAG priority.

    Forward construction simulates the source-order packer's issue decisions.
    Backward construction schedules the reversed dependency graph and reverses
    its order; the normal packer determines the resulting forward issue times.
    """
    if policy not in _POLICIES:
        raise ValueError(f"unknown DAG policy: {policy!r}")
    if direction not in ("forward", "backward"):
        raise ValueError(f"unknown scheduling direction: {direction!r}")
    return _order(_Graph(program), policy, direction)


def dag_orderings(program: dict) -> Iterator[tuple[int, ...]]:
    """Yield distinct forward/backward candidates, sharing dependency analysis."""
    graph = _Graph(program)
    seen: set[tuple[int, ...]] = set()
    for direction in ("forward", "backward"):
        for policy in _POLICIES:
            ordering = _order(graph, policy, direction)
            if ordering not in seen:
                seen.add(ordering)
                yield ordering
