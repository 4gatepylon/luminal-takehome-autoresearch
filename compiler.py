#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering candidate implementation.

The compiler greedily packs operations into bundles in source order, then
reuses scratch for values whose scheduled lifetimes do not overlap.
"""

from __future__ import annotations
from typing import Optional, Literal
import json
import sys

import machine


def allocate_unique_scratch(program: dict) -> dict[str, int]:
    """Assign disjoint ranges, prioritizing vectors before scalars."""

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


def find_issue_cycles(
    program: dict,
    bundles: list[dict[str, list[int]]],
) -> dict[int, int]:
    """Return op_id2issue_cycle; require each ID in range(len(ops)) exactly once."""
    op_id2issue_cycle: dict[int, int] = {}
    for issue_cycle, engine2op_ids in enumerate(bundles):
        for op_ids in engine2op_ids.values():
            for op_id in op_ids:
                if op_id in op_id2issue_cycle:
                    raise machine.CompileError(f"operation {op_id} appears more than once")
                op_id2issue_cycle[op_id] = issue_cycle
    if set(op_id2issue_cycle) != set(range(len(program["operations"]))):
        raise machine.CompileError(
            f"schedule operation IDs must cover exactly range({len(program['operations'])})"
        )
    return op_id2issue_cycle


def find_lifetimes(
    program: dict,
    op_id2issue_cycle: dict[int, int],
) -> dict[str, tuple[int, int]]:
    """Return value_name2lifetime_incl for a valid schedule.

    Each interval is (write_cycle_incl, last_live_cycle_incl). The start is
    the producer's issue cycle plus latency; the end is the maximum of that
    start and every consumer's issue cycle. Unused results occupy their write
    cycle, even when that write is after the final bundle.
    """
    value_name2lifetime_incl: dict[str, tuple[int, int]] = {}
    # Initialize the lifetime dict with each value's write cycle as both endpoints.
    for operation in program["operations"]:
        spec = machine.OP_SPECS[operation["op"]]
        if spec["result"] is not None:
            write_cycle_incl = op_id2issue_cycle[operation["id"]] + spec["latency"]
            value_name2lifetime_incl[operation["dest"]] = (
                write_cycle_incl, write_cycle_incl
            )

    # Extend lifetimes to the last read; max makes traversal order irrelevant.
    for operation in program["operations"]:
        for value_name in operation.get("args", []):
            write_cycle_incl, last_live_cycle_incl = value_name2lifetime_incl[value_name]
            value_name2lifetime_incl[value_name] = (
                write_cycle_incl,
                max(last_live_cycle_incl, op_id2issue_cycle[operation["id"]]),
            )
    return value_name2lifetime_incl


def allocate_scratch(
    program: dict,
    value_name2lifetime_incl: dict[str, tuple[int, int]],
) -> dict[str, int]:
    """Return value_name2scratch_address using aligned first-fit.

    For lifetime [s_v, e_v] (both inclusive) and width w_v (VLEN or 1),
    process values by ascending (s_v, -w_v, name_v). Vectors precede scalars
    only for equal write cycles; equal-width ties use Python string ordering.
    Source order and operand position have no separate precedence.

    Choose the smallest a >= 0 with a % w_v == 0 and a + w_v <= SCRATCH_WORDS
    such that every word x in [a, a + w_v) has last_live_cycle_incl[x] < s_v.
    Initialize these last-live cycles to -1, then set allocated words to e_v.
    Processing by start time makes this exclude all overlapping lifetimes.
    Strict inequality is necessary because writes happen before reads.
    EVERY value searches again from address 0, not from the previous allocation's
    end. Alignment holes remain free: placing a vector at a higher address does
    not claim the gap below it. Only the chosen words are reserved, through e_v.

    Raise CompileError if no aligned range fits; first-fit does not guarantee
    minimum footprint.
    """
    value_name2width = {
        operation["dest"]: (
            machine.VLEN if machine.OP_SPECS[operation["op"]]["result"] == "vector" else 1
        )
        for operation in program["operations"]
        if machine.OP_SPECS[operation["op"]]["result"] is not None
    }
    ordered_value_names = sorted(
        value_name2lifetime_incl,
        key=lambda value_name: (
            value_name2lifetime_incl[value_name][0],
            -value_name2width[value_name],
            value_name,
        ),
    )
    scratch_address2last_live_cycle_incl = [-1] * machine.SCRATCH_WORDS
    value_name2scratch_address: dict[str, int] = {}
    for value_name in ordered_value_names:
        write_cycle_incl, last_live_cycle_incl = value_name2lifetime_incl[value_name]
        width = value_name2width[value_name]
        for scratch_start_incl in range(0, machine.SCRATCH_WORDS - width + 1, width):
            scratch_end_excl = scratch_start_incl + width
            if all(
                scratch_address2last_live_cycle_incl[scratch_address] < write_cycle_incl
                for scratch_address in range(scratch_start_incl, scratch_end_excl)
            ):
                value_name2scratch_address[value_name] = scratch_start_incl
                scratch_address2last_live_cycle_incl[scratch_start_incl:scratch_end_excl] = (
                    [last_live_cycle_incl] * width
                )
                break
        else:
            raise machine.CompileError(f"no scratch space for {value_name!r}")
    return value_name2scratch_address


def allocate_hierarchical_scratch(
    program: dict,
    value_name2lifetime_incl: dict[str, tuple[int, int]],
) -> dict[str, int]:
    """First-fit all vectors, then all scalars, by (write_cycle_incl, name).

    Each value searches from address 0, aligned to its width. A range fits iff
    its lifetime [s, e] and EVERY reserved lifetime [s_other, e_other] in those
    words satisfy e < s_other or e_other < s (all endpoints inclusive).
    Thus scalars can reuse vector words before, between, or after vector
    lifetimes, and share scalar words when lifetimes do not overlap. Only if
    no earlier range fits do they extend the footprint. Raise CompileError
    when no range fits within scratch capacity.
    """
    value_name2kind = machine.result_kinds(program)
    ordered_value_names = sorted(
        value_name2lifetime_incl,
        key=lambda value_name: (
            value_name2kind[value_name] != "vector",
            value_name2lifetime_incl[value_name][0],
            value_name,
        ),
    )
    # Keep every interval: the scalar pass can go back in time after vectors.
    scratch_address2lifetimes_incl: list[list[tuple[int, int]]] = [
        [] for _ in range(machine.SCRATCH_WORDS)
    ]
    value_name2scratch_address: dict[str, int] = {}
    for value_name in ordered_value_names:
        write_cycle_incl, last_live_cycle_incl = value_name2lifetime_incl[value_name]
        width = machine.VLEN if value_name2kind[value_name] == "vector" else 1
        for scratch_start_incl in range(0, machine.SCRATCH_WORDS - width + 1, width):
            scratch_end_excl = scratch_start_incl + width
            if all(
                last_live_cycle_incl < other_write_cycle_incl
                or other_last_live_cycle_incl < write_cycle_incl
                for scratch_address in range(scratch_start_incl, scratch_end_excl)
                for other_write_cycle_incl, other_last_live_cycle_incl
                in scratch_address2lifetimes_incl[scratch_address]
            ):
                value_name2scratch_address[value_name] = scratch_start_incl
                for scratch_address in range(scratch_start_incl, scratch_end_excl):
                    scratch_address2lifetimes_incl[scratch_address].append(
                        (write_cycle_incl, last_live_cycle_incl)
                    )
                break
        else:
            raise machine.CompileError(f"no scratch space for {value_name!r}")
    return value_name2scratch_address


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


def schedule_operations(program: dict) -> list[dict[str, list[int]]]:
    """Greedily fill bundles in source order, stalling when necessary."""
    operations = program["operations"]

    bundles: list[dict[str, list[int]]] = []
    curr_bundle: dict[str, list[int]] = {}
    issue_cycle: dict[int, int] = {}
    producer = machine.producer_map(program)

    for operation in operations:
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


def compile_program(
    program: dict,
    scratch_allocation_strategy: Optional[Literal["first-fit", "disjoint", "hierarchical"]] = None,
) -> dict:
    """Use the requested allocator, or choose the smallest successful allocation."""
    bundles = schedule_operations(program)
    op_id2issue_cycle = find_issue_cycles(program, bundles)
    value_name2lifetime_incl = find_lifetimes(program, op_id2issue_cycle)
    scratch_candidates = []
    for strategy_name, allocator, arguments in (
        ("first-fit", allocate_scratch, (program, value_name2lifetime_incl)),
        ("disjoint", allocate_unique_scratch, (program,)),
        ("hierarchical", allocate_hierarchical_scratch, (program, value_name2lifetime_incl)),
    ):
        if scratch_allocation_strategy not in (None, strategy_name):
            continue
        try:
            scratch_candidates.append(allocator(*arguments))
        except machine.CompileError:
            if scratch_allocation_strategy is not None:
                raise
            continue
    if not scratch_candidates:
        raise machine.CompileError("no scratch allocation strategy fits within capacity")
    value_name2scratch_address = min(
        scratch_candidates,
        key=lambda candidate_value_name2scratch_address: machine.scratch_footprint(
            program, {"scratch": candidate_value_name2scratch_address}
        ),
    )
    return {"scratch": value_name2scratch_address, "bundles": bundles}


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
