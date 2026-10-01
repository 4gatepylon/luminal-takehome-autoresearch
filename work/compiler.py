#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering candidate implementation.

Input: JSON-compatible dict of buffers, test inputs, and typed operations.
    SSA = each result defined once; list order defines semantics. Pseudocode:
    a0 = load x[0]       # op 0
    b0 = a0 + a0        # op 1
    store out[0] = b0   # op 2

Output: dict with two fields; an execution plan used with the original program.
    scratch: {"a0": 0, "b0": 1}  # result names -> temporary storage word addresses
    bundles: [{"load": [0]}, {}, {}, {"scalar": [1]}, {"store": [2]}]
    Bundle index = cycle; engine -> IDs of ops starting together; {} = stall.
    Engines are execution units; issue = start; result ready at issue + latency.

Goal: reduce cycles and scratch footprint; keep final buffer contents identical.
    Issue every original op once; obey dependencies, memory order, machine limits.
    Reuse scratch when value lifetimes do not overlap; keep the input/output API.
Starter: separate storage per value, at most one operation per bundle.
"""

from __future__ import annotations

import json
import sys

import machine


def compile_program(program: dict) -> dict:
    """Compile one validated IR program into scratch allocations and bundles."""

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

    # Serial, source-order scheduling with explicit latency stalls. This is a
    # correct baseline, but it leaves almost all VLIW slots empty.
    bundles: list[dict[str, list[int]]] = []
    issue_cycle: dict[int, int] = {}
    producer = machine.producer_map(program)

    for operation in operations:
        spec = machine.OP_SPECS[operation["op"]]
        earliest = len(bundles)

        for arg in operation.get("args", []):
            pred_id = producer[arg]
            pred = operations[pred_id]
            earliest = max(
                earliest,
                issue_cycle[pred_id] + machine.OP_SPECS[pred["op"]]["latency"],
            )

        for pred_id in machine.memory_predecessors(program, operation["id"]):
            earliest = max(earliest, issue_cycle[pred_id] + 1)

        while len(bundles) < earliest:
            bundles.append({})

        bundles.append({spec["engine"]: [operation["id"]]})
        issue_cycle[operation["id"]] = earliest

    return {"scratch": scratch, "bundles": bundles}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 -m work.compiler <program.json>", file=sys.stderr)
        return 2

    program = machine.load_program(argv[0])
    compilation = compile_program(program)
    machine.check_compilation(program, compilation)
    json.dump(compilation, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
