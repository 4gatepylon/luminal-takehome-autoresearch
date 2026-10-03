"""Compile programs by scheduling operations and selecting scratch allocations."""

from __future__ import annotations

import traceback
from typing import Any, Literal

import machine

from .allocation import (
    allocate_scratch_first_fit,
    allocate_unique_scratch,
    find_lifetimes,
)
from .reordering import reordered_program
from .scheduling import find_issue_cycles, schedule_operations


ALLOCATION_NAME2ALLOCATOR_FN = {
    "first-fit": lambda program, value_name2lifetime_incl: allocate_scratch_first_fit(
        program, value_name2lifetime_incl, mode="default"
    ),
    "hierarchical-first-fit": lambda program, value_name2lifetime_incl: allocate_scratch_first_fit(
        program, value_name2lifetime_incl, mode="vectors_first"
    ),
}


def compile_with_ordering(
    original_program: dict[str, Any],
    ordering: tuple[int, ...],
    scratch_allocation_strategy: Literal[
        "any", "first-fit", "disjoint", "hierarchical-first-fit"
    ] = "any",
    verbose: bool = False,
) -> dict[str, Any]:
    """Compile a valid ordering of original IDs; preserve the input and output IDs."""
    program = reordered_program(original_program, ordering)
    bundles_with_reordered_ids = schedule_operations(program)
    op_id2issue_cycle = find_issue_cycles(program, bundles_with_reordered_ids)
    value_name2lifetime_incl = find_lifetimes(program, op_id2issue_cycle)
    # NOTE: we use disjoint allocation always by default since it was originally used and is used by
    # our baseline. It can crash on memory-intensive programs that better allocators might not crash
    # on. However, we think it's worth keeping the exact same behavior.
    scratch_allocations = [allocate_unique_scratch(program)]
    if scratch_allocation_strategy not in ("any", "disjoint"):
        try:
            scratch_allocations[0] = ALLOCATION_NAME2ALLOCATOR_FN[
                scratch_allocation_strategy
            ](program, value_name2lifetime_incl)
        except machine.CompileError as error:
            raise RuntimeError(
                f"{scratch_allocation_strategy} allocation failed. However, it was required by user request. The compilation cannot proceed."
            ) from error
    elif scratch_allocation_strategy == "any":
        for allocator_fn in ALLOCATION_NAME2ALLOCATOR_FN.values():
            try:
                scratch_allocations.append(
                    allocator_fn(program, value_name2lifetime_incl)
                )
            except machine.CompileError as e:
                if verbose:
                    print("=" * 100)
                    print(
                        "WARNING: Allocation failed, but it was NOT required by user request. "
                        "Ignoring failure..."
                    )
                    traceback.print_exc()
                    print("=" * 100)
                continue
    value_name2scratch_address = min(
        scratch_allocations,
        key=lambda value_name2address: machine.scratch_footprint(
            program, {"scratch": value_name2address}
        ),
    )
    bundles_with_original_ids = [
        {
            engine: [ordering[op_id] for op_id in op_ids]
            for engine, op_ids in bundle.items()
        }
        for bundle in bundles_with_reordered_ids
    ]
    return {"scratch": value_name2scratch_address, "bundles": bundles_with_original_ids}


def compile_program(
    program: dict[str, Any],
    scratch_allocation_strategy: Literal[
        "any", "first-fit", "disjoint", "hierarchical-first-fit"
    ] = "any",
    verbose: bool = False,
) -> dict[str, Any]:
    """Compile in the program's original order using the requested scratch strategy."""
    ordering = tuple(range(len(program["operations"])))
    return compile_with_ordering(
        program, ordering, scratch_allocation_strategy, verbose
    )
