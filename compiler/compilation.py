"""Compile programs by scheduling operations and selecting scratch allocations."""

from __future__ import annotations

from typing import Optional, Literal

import machine

from .allocation import (
    allocate_scratch_first_fit,
    allocate_scratch_hierarchical_first_fit,
    allocate_unique_scratch,
    find_lifetimes,
)
from .scheduling import find_issue_cycles, schedule_operations


def compile_program(
    program: dict,
    scratch_allocation_strategy: Optional[Literal["first-fit", "disjoint", "hierarchical-first-fit"]] = None,
) -> dict:
    """Use the requested allocator, or choose the smallest successful allocation."""
    bundles = schedule_operations(program)
    op_id2issue_cycle = find_issue_cycles(program, bundles)
    value_name2lifetime_incl = find_lifetimes(program, op_id2issue_cycle)
    # Preserve the original compiler's failure when disjoint allocation cannot fit,
    # even if a reuse strategy could succeed. This also applies to forced strategies.
    value_name2scratch_address = allocate_unique_scratch(program)
    for strategy_name, allocator in (
        ("first-fit", allocate_scratch_first_fit),
        ("hierarchical-first-fit", allocate_scratch_hierarchical_first_fit),
    ):
        if scratch_allocation_strategy not in (None, strategy_name):
            continue
        try:
            candidate_value_name2scratch_address = allocator(program, value_name2lifetime_incl)
        except machine.CompileError as error:
            if scratch_allocation_strategy == strategy_name:
                raise RuntimeError(f"{strategy_name} allocation failed by running out of space") from error
            continue
        if scratch_allocation_strategy == strategy_name:
            value_name2scratch_address = candidate_value_name2scratch_address
            break
        value_name2scratch_address = min(
            (value_name2scratch_address, candidate_value_name2scratch_address),
            key=lambda allocation: machine.scratch_footprint(program, {"scratch": allocation}),
        )
    return {"scratch": value_name2scratch_address, "bundles": bundles}
