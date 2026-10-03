#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering candidate implementation.

The compiler allocates every SSA value once and greedily packs operations into
bundles in the supplied order. Improve compile_program without
changing its input or output contract. Reuse scratch for values whose scheduled
lifetimes do not overlap to improve the scratch-footprint component of the score.
"""

from __future__ import annotations

import json
import sys

import machine


class OperationDependencies:
    """Data and memory prerequisites for a validated program."""

    def __init__(self, program: dict):
        self.program = program
        operations = program["operations"]
        producer = machine.producer_map(program)
        self.dependencies: dict[int, list[dict]] = {}
        for operation in operations:
            data = [producer[arg] for arg in operation.get("args", [])]
            memory = machine.memory_predecessors(program, operation["id"])
            predecessors = data + memory
            assert all(type(pred_id) is int for pred_id in predecessors)
            self.dependencies[operation["id"]] = [
                operations[pred_id] for pred_id in sorted(set(predecessors))
            ]

    def latest_dependency(
        self, operation: dict, ordering: tuple[int, ...] | None = None
    ) -> dict | None:
        """Return the latest prerequisite in a valid ordering, or None."""
        if ordering is None:
            ordering = tuple(range(len(self.dependencies)))
        assert all(type(op_id) is int for op_id in ordering)
        # No transitive search is needed: each indirect prerequisite precedes
        # one of these direct prerequisites in any valid ordering.
        return max(
            self.dependencies[operation["id"]],
            key=lambda pred: ordering.index(pred["id"]),
            default=None,
        )


def allocate_scratch(program: dict) -> dict[str, int]:
    """Assign scratch addresses to every SSA result."""

    # A simple non-overlapping allocation. Vectors are placed first so their
    # alignment does not create holes between scalar values.
    scratch: dict[str, int] = {}
    cursor = 0
    operations = program["operations"]

    for result_kind in ("vector", "scalar"):
        for operation in operations:
            spec = machine.OP_SPECS[operation["op"]]
            if spec["result"] != result_kind:
                continue
            dest = operation["dest"]
            if result_kind == "vector":
                cursor = machine.align_up(cursor, machine.VLEN)
                scratch[dest] = cursor
                cursor += machine.VLEN
            else:
                scratch[dest] = cursor
                cursor += 1

    if cursor > machine.SCRATCH_WORDS:
        raise machine.CompileError(
            f"program requires {cursor} scratch words, limit is {machine.SCRATCH_WORDS}"
        )

    return scratch


def earliest_issue_cycle(
    program: dict,
    operation: dict,
    producer: dict[str, int],
    issue_cycle: dict[int, int],
) -> int:
    """Find the earliest cycle allowed by data dependencies and memory ordering."""
    operations = program["operations"]
    earliest = 0

    for arg in operation.get("args", []):
        pred_id = producer[arg]
        pred = operations[pred_id]
        earliest = max(
            earliest,
            issue_cycle[pred_id] + machine.OP_SPECS[pred["op"]]["latency"],
        )

    for pred_id in machine.memory_predecessors(program, operation["id"]):
        earliest = max(earliest, issue_cycle[pred_id] + 1)

    return earliest


def schedule_operations(
    program: dict, ordering: tuple[int, ...] | None = None
) -> list[dict[str, list[int]]]:
    """Greedily fill bundles in the given order, stalling when necessary."""
    operations = program["operations"]
    if ordering is None:
        ordering = tuple(range(len(operations)))

    bundles: list[dict[str, list[int]]] = []
    curr_bundle: dict[str, list[int]] = {}
    issue_cycle: dict[int, int] = {}
    producer = machine.producer_map(program)

    for op_id in ordering:
        operation = operations[op_id]
        engine = machine.OP_SPECS[operation["op"]]["engine"]
        earliest = earliest_issue_cycle(program, operation, producer, issue_cycle)

        # Flush the current bundle, then emit empty stalls until this op is ready.
        while (
            len(bundles) < earliest
            or len(curr_bundle.get(engine, [])) >= machine.ENGINE_LIMITS[engine]
        ):
            bundles.append(curr_bundle)
            curr_bundle = {}

        curr_bundle.setdefault(engine, []).append(operation["id"])
        issue_cycle[operation["id"]] = len(bundles)

    if curr_bundle:
        bundles.append(curr_bundle)

    return bundles


def compile_program(program: dict, ordering: tuple[int, ...] | None = None) -> dict:
    """Compile one validated IR program into scratch allocations and bundles."""
    scratch = allocate_scratch(program)
    bundles = schedule_operations(program, ordering)
    return {"scratch": scratch, "bundles": bundles}


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
