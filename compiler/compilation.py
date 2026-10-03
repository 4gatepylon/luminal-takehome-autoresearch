"""Compile programs by scheduling operations and selecting scratch allocations."""

from __future__ import annotations

from typing import Any, Optional, Literal

import machine

from .allocation import allocate_scratch_first_fit, allocate_unique_scratch, find_lifetimes
from .reordering import reorder_program
from .scheduling import find_issue_cycles, schedule_operations


def compile_with_ordering(
    program: dict[str, Any],
    ordering: tuple[int, ...],
    scratch_allocation_strategy: Optional[Literal["first-fit", "disjoint"]] = None,
) -> dict[str, Any]:
    """Compile a valid ordering of original IDs; preserve the input and output IDs."""
    program = reorder_program(program, ordering)
    bundles = schedule_operations(program)
    op_id2issue_cycle = find_issue_cycles(program, bundles)
    value_name2lifetime_incl = find_lifetimes(program, op_id2issue_cycle)
    # NOTE: we want to run this disjoint allocation first to fail in the same was as the original compiler.
    # for programs that COULD be fit more efficiently, but the original compiler failed, this maintains the
    # exact same behavior. However, we may change this once we have more deeply validated the compiler.
    value_name2scratch_address = allocate_unique_scratch(program)
    if scratch_allocation_strategy != "disjoint":
        try:
            unique_value_name2scratch_address = allocate_scratch_first_fit(program, value_name2lifetime_incl)
            # Overwrite only if needed (force-using first-fit is possible)
            if scratch_allocation_strategy == "first-fit":
                value_name2scratch_address = unique_value_name2scratch_address
            else:
                assert scratch_allocation_strategy != "disjoint"
                value_name2scratch_address = min(
                    (value_name2scratch_address, unique_value_name2scratch_address),
                    key=lambda candidate_value_name2scratch_address: machine.scratch_footprint(
                        program, {"scratch": candidate_value_name2scratch_address}
                    ),
                )
        except machine.CompileError as e:
            if scratch_allocation_strategy == "first-fit":
                raise RuntimeError(f"first-fit allocation failed by running out of space and therefore cannot occur!") from e
    bundles = [
        {engine: [ordering[op_id] for op_id in op_ids] for engine, op_ids in bundle.items()}
        for bundle in bundles
    ]
    return {"scratch": value_name2scratch_address, "bundles": bundles}


def compile_program(
    program: dict[str, Any],
    scratch_allocation_strategy: Optional[Literal["first-fit", "disjoint"]] = None,
) -> dict[str, Any]:
    """Compile in the program's original order using the requested scratch strategy."""
    ordering = tuple(range(len(program["operations"])))
    return compile_with_ordering(program, ordering, scratch_allocation_strategy)
