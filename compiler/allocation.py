"""Value lifetime analysis and scratch allocation strategies."""

from __future__ import annotations

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


def allocate_scratch_first_fit(
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
