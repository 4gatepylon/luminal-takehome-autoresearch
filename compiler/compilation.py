"""Compile programs by scheduling operations and selecting scratch allocations."""

from __future__ import annotations

from typing import Optional, Literal

import machine

from .allocation import allocate_scratch_first_fit, allocate_unique_scratch, find_lifetimes
from .scheduling import find_issue_cycles, schedule_operations


ALLOCATION_NAME2ALLOCATOR_FN = {
    "first-fit": lambda program, value_name2lifetime_incl: allocate_scratch_first_fit(
        program, value_name2lifetime_incl, mode="default"
    ),
    "hierarchical-first-fit": lambda program, value_name2lifetime_incl: allocate_scratch_first_fit(
        program, value_name2lifetime_incl, mode="vectors_first"
    ),
}


def compile_program(program: dict, scratch_allocation_strategy: Optional[Literal["first-fit", "disjoint", "hierarchical-first-fit"]] = None) -> dict:
    """Schedule a validated program and choose the smallest successful allocation."""
    bundles = schedule_operations(program)
    op_id2issue_cycle = find_issue_cycles(program, bundles)
    value_name2lifetime_incl = find_lifetimes(program, op_id2issue_cycle)
    # Disjoint allocation must fit before any strategy is attempted.
    scratch_allocations = [allocate_unique_scratch(program)]
    if scratch_allocation_strategy not in (None, "disjoint"):
        try:
            scratch_allocations[0] = ALLOCATION_NAME2ALLOCATOR_FN[scratch_allocation_strategy](
                program, value_name2lifetime_incl
            )
        except machine.CompileError as error:
            raise RuntimeError(f"{scratch_allocation_strategy} allocation failed") from error
    elif scratch_allocation_strategy is None:
        for allocator_fn in ALLOCATION_NAME2ALLOCATOR_FN.values():
            try:
                scratch_allocations.append(allocator_fn(program, value_name2lifetime_incl))
            except machine.CompileError:
                continue
    value_name2scratch_address = min(
        scratch_allocations,
        key=lambda value_name2address: machine.scratch_footprint(program, {"scratch": value_name2address}),
    )
    return {"scratch": value_name2scratch_address, "bundles": bundles}
