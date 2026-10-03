"""Compile programs by scheduling operations and selecting scratch allocations."""

from __future__ import annotations

from typing import Optional, Literal

import machine

from .allocation import allocate_scratch_first_fit, allocate_unique_scratch, find_lifetimes
from .scheduling import find_issue_cycles, schedule_operations


def compile_program(program: dict, scratch_allocation_strategy: Optional[Literal["first-fit", "disjoint", "hierarchical-first-fit"]] = None) -> dict:
    """Schedule a validated program and choose the smallest successful allocation."""
    if scratch_allocation_strategy == "hierarchical-first-fit":
        raise NotImplementedError("hierarchical-first-fit compiler integration is not implemented")
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
    return {"scratch": value_name2scratch_address, "bundles": bundles}
