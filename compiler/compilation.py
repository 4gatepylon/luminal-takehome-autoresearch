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
from .custom_scheduling import SCHEDULER_NAME2ORDERINGS_FN
from .reordering import OperationDependencies, reorder_program
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
    program: dict[str, Any],
    ordering: tuple[int, ...],
    scratch_allocation_strategy: Literal[
        "any", "first-fit", "disjoint", "hierarchical-first-fit"
    ] = "any",
    verbose: bool = False,
) -> dict[str, Any]:
    """Compile a valid ordering of original IDs; preserve the input and output IDs."""
    program = reorder_program(program, ordering)
    bundles = schedule_operations(program)
    op_id2issue_cycle = find_issue_cycles(program, bundles)
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
    bundles = [
        {engine: [ordering[op_id] for op_id in op_ids] for engine, op_ids in bundle.items()}
        for bundle in bundles
    ]
    return {"scratch": value_name2scratch_address, "bundles": bundles}


def compile_program(
    program: dict[str, Any],
    scratch_allocation_strategy: Literal[
        "any", "first-fit", "disjoint", "hierarchical-first-fit"
    ] = "any",
    verbose: bool = False,
    *,
    scheduling_strategy: str = "source",
) -> dict[str, Any]:
    """Choose a compilation by cycles times scratch, preserving original IDs.

    Custom schedulers supply legal operation permutations. Source order remains
    a candidate and the default strategy; scratch allocation uses the requested
    strategy independently for each candidate.
    """
    if scheduling_strategy != "source" and scheduling_strategy not in SCHEDULER_NAME2ORDERINGS_FN:
        raise ValueError(f"unknown scheduling strategy: {scheduling_strategy!r}")
    source_order = tuple(range(len(program["operations"])))
    if scheduling_strategy == "source":
        return compile_with_ordering(program, source_order, scratch_allocation_strategy, verbose)

    allocation_error = None
    try:
        best = compile_with_ordering(program, source_order, scratch_allocation_strategy, verbose)
    except RuntimeError as error:
        if not isinstance(error.__cause__, machine.CompileError):
            raise
        # A forced allocator may fit another ordering even when source fails.
        allocation_error = error
        best = None

    def cost(compilation: dict) -> tuple[int, int, int]:
        cycles = len(compilation["bundles"])
        words = machine.scratch_footprint(program, compilation)
        return cycles * words, cycles, words

    best_cost = cost(best) if best is not None else None
    seen = {source_order}
    dependencies = OperationDependencies(program)
    for ordering in SCHEDULER_NAME2ORDERINGS_FN[scheduling_strategy](program):
        ordering = tuple(ordering)
        if (len(ordering) != len(source_order)
                or any(type(op_id) is not int for op_id in ordering)
                or set(ordering) != set(source_order)):
            raise machine.CompileError("custom scheduler must return a permutation of operation IDs")
        if ordering in seen:
            continue
        seen.add(ordering)
        positions = {op_id: index for index, op_id in enumerate(ordering)}
        if any(
            positions[pred["id"]] >= positions[op_id]
            for op_id, preds in dependencies.op_id2prev_ops.items() for pred in preds
        ):
            raise machine.CompileError("custom scheduler ordering violates operation dependencies")
        try:
            candidate = compile_with_ordering(program, ordering, scratch_allocation_strategy, verbose)
        except RuntimeError as error:
            # A forced allocator can fail for one schedule while succeeding on
            # the incumbent. Keep its forcing semantics for every candidate.
            if not isinstance(error.__cause__, machine.CompileError):
                raise
            continue
        candidate_cost = cost(candidate)
        if best_cost is None or candidate_cost < best_cost:
            best, best_cost = candidate, candidate_cost
    if best is None:
        assert allocation_error is not None
        raise allocation_error
    return best
