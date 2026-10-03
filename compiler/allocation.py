"""Value lifetime analysis and scratch allocation strategies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import machine


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


def make_allocation_sort_key(
    mode: Literal["vectors_first", "default"],
    value_name2width: dict[str, int],
    value_name2lifetime_incl: dict[str, tuple[int, int]],
) -> Callable[[str], tuple[bool, int, int, str]]:
    return lambda value_name: (
        # This will pick a constant if you are not doing vectors-first;
        # Otherwise, it will basically use the width below as a no-op.
        # When in vectors-first:
        # - Vectors have width != 1 so the value becomes 0, putting it earlier in the list
        # - Scalars have width == 1 so the value becomes 1, putting it later in the list
        int(mode == "vectors_first" and value_name2width[value_name] == 1),
        value_name2lifetime_incl[value_name][0],
        -value_name2width[value_name],
        value_name,
    )


def allocate_scratch_first_fit(
    program: dict,
    value_name2lifetime_incl: dict[str, tuple[int, int]],
    *, mode: Literal["vectors_first", "default"] = "default",
) -> dict[str, int]:
    """Place each value at the lowest width-aligned range with disjoint lifetimes.

    Conceptually:
    - "default" orders by (write_cycle_incl, -width, name)
    - "vectors_first" orders by (-width, write_cycle_incl, name).
    (read `make_allocation_sort_key` for exact details)

    These orders are traversed once and allocations occur when the instruction is reached
    at the earliest possible address (taking into account VLEN/alignement needs for vectors,
    lifespans, etc...). You can think of the memory space as being, conceptually, treated
    like a queue.
    
    Lifetimes [s, e] are inclusive: sharing a word requires e < other_s or other_e < s
    for every reserved interval. Every search starts at address 0, including gaps below
    earlier allocations. Raise CompileError when no range fits within scratch capacity.
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
        key=make_allocation_sort_key(mode, value_name2width, value_name2lifetime_incl),
    )
    scratch_address2lifetimes_incl: list[list[tuple[int, int]]] = [
        [] for _ in range(machine.SCRATCH_WORDS)
    ]
    value_name2scratch_address: dict[str, int] = {}
    for value_name in ordered_value_names:
        write_cycle_incl, last_live_cycle_incl = value_name2lifetime_incl[value_name]
        width = value_name2width[value_name]
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
