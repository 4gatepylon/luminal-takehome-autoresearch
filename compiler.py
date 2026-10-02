#!/usr/bin/env python3
"""Latency-aware VLIW scheduling with lifetime-based scratch allocation."""

from __future__ import annotations

import json
import sys

import machine


def _dependency_graph(
    program: dict,
) -> tuple[list[dict[int, int]], list[dict[int, int]]]:
    """Build edges carrying the minimum separation between issue cycles."""
    operations = program["operations"]
    producers = machine.producer_map(program)
    predecessors: list[dict[int, int]] = [{} for _ in operations]
    successors: list[dict[int, int]] = [{} for _ in operations]
    for operation in operations:
        op_id = operation["id"]
        deps = predecessors[op_id]
        for pred_id in machine.memory_predecessors(program, op_id):
            deps[pred_id] = 1
        for arg in operation.get("args", []):
            pred_id = producers[arg]
            latency = machine.OP_SPECS[operations[pred_id]["op"]]["latency"]
            # A data edge can also be a memory edge, and operands can repeat.
            deps[pred_id] = max(deps.get(pred_id, 0), latency)
        for pred_id, delay in deps.items():
            successors[pred_id][op_id] = delay
    return predecessors, successors


def _schedule(
    operations: list[dict], edges: list[dict[int, int]], backwards: bool
) -> list[dict[str, list[int]]]:
    """List-schedule in either direction, prioritizing the longest remaining path.

    Reverse scheduling places producers near their consumers, often shortening
    lifetimes. Its edge delays still use the original producer's latency.
    """
    count = len(operations)
    remaining = [0] * count
    priority = [1] * count
    # SSA and memory edges both follow source order in the original graph.
    order = range(count) if backwards else range(count - 1, -1, -1)
    for op_id in order:
        for successor, delay in edges[op_id].items():
            remaining[successor] += 1
            priority[op_id] = max(priority[op_id], delay + priority[successor])

    ready = {op_id for op_id in range(count) if remaining[op_id] == 0}
    earliest = [0] * count
    bundles: list[dict[str, list[int]]] = []
    while ready:
        cycle = len(bundles)
        candidates = sorted(
            (op_id for op_id in ready if earliest[op_id] <= cycle),
            key=lambda op_id: (-priority[op_id], op_id),
        )
        if not candidates:
            next_cycle = min(earliest[op_id] for op_id in ready)
            bundles.extend({} for _ in range(next_cycle - cycle))
            continue

        bundle: dict[str, list[int]] = {}
        for op_id in candidates:
            engine = machine.OP_SPECS[operations[op_id]["op"]]["engine"]
            slots = bundle.setdefault(engine, [])
            if len(slots) == machine.ENGINE_LIMITS[engine]:
                continue
            slots.append(op_id)
            ready.remove(op_id)
            for successor, delay in edges[op_id].items():
                earliest[successor] = max(earliest[successor], cycle + delay)
                remaining[successor] -= 1
                if remaining[successor] == 0:
                    ready.add(successor)
        bundles.append(bundle)

    if backwards:
        bundles.reverse()
    return bundles


def _allocate(
    operations: list[dict], bundles: list[dict[str, list[int]]]
) -> dict[str, int]:
    """Pack inclusive write-to-last-read intervals into aligned scratch ranges."""
    issue = {
        op_id: cycle
        for cycle, bundle in enumerate(bundles)
        for op_ids in bundle.values()
        for op_id in op_ids
    }
    starts: dict[str, int] = {}
    widths: dict[str, int] = {}
    for operation in operations:
        spec = machine.OP_SPECS[operation["op"]]
        if spec["result"] is not None:
            name = operation["dest"]
            starts[name] = issue[operation["id"]] + spec["latency"]
            widths[name] = machine.VLEN if spec["result"] == "vector" else 1
    ends = starts.copy()
    for operation in operations:
        for arg in operation.get("args", []):
            ends[arg] = max(ends[arg], issue[operation["id"]])

    # Place vectors first to preserve aligned blocks. Scalars can then use any
    # individual word in those blocks during gaps in the vector lifetimes.
    names = sorted(starts, key=lambda name: (-widths[name], starts[name], ends[name]))
    allocated: list[tuple[int, int, int]] = []
    scratch: dict[str, int] = {}
    for name in names:
        start, end, width = starts[name], ends[name], widths[name]
        occupied = 0
        for other_start, other_end, mask in allocated:
            # Equality conflicts: writes happen before reads in the same cycle.
            # Unused results also retain their one-cycle write interval.
            if start <= other_end and other_start <= end:
                occupied |= mask
        mask = (1 << width) - 1
        for base in range(0, machine.SCRATCH_WORDS - width + 1, width):
            if not occupied & (mask << base):
                scratch[name] = base
                allocated.append((start, end, mask << base))
                break
        else:
            raise machine.CompileError("scheduled lifetimes exceed scratch capacity")
    return scratch


def compile_program(program: dict) -> dict:
    """Compile a validated SSA program without changing any input operations."""
    operations = program["operations"]
    predecessors, successors = _dependency_graph(program)
    best = None
    best_cost = None
    for backwards, edges in ((False, successors), (True, predecessors)):
        bundles = _schedule(operations, edges, backwards)
        scratch = _allocate(operations, bundles)
        compilation = {"scratch": scratch, "bundles": bundles}
        words = machine.scratch_footprint(program, compilation)
        # The score weights cycles and scratch equally in log space. Minimize
        # their product; prefer fewer cycles when products tie.
        cost = (len(bundles) * words, len(bundles), words)
        if best_cost is None or cost < best_cost:
            best, best_cost = compilation, cost
    return best


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 compiler.py <program.json>", file=sys.stderr)
        return 2

    program = machine.load_program(argv[0])
    compilation = compile_program(program)
    machine.check_compilation(program, compilation)
    json.dump(compilation, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
