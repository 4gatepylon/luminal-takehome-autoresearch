"""Dependency queries and utilities for valid operation orderings."""

from __future__ import annotations

from typing import Any

import machine


# Operation fields: id/value/offset are ints, op/dest/buffer are strings,
# and args is a list of SSA value names (strings).
Operation = dict[str, int | str | list[str]]


class OperationDependencies:
    """Data and memory prerequisites for a validated program."""

    def __init__(self, program: dict[str, Any]) -> None:
        self.program = program
        operations: list[Operation] = program["operations"]
        value_name2producer_id: dict[str, int] = machine.producer_map(program)
        # Each operation ID maps to its prerequisite operation dictionaries.
        self.op_id2prev_ops: dict[int, list[Operation]] = {}
        for operation in operations:
            data_predecessor_ids: list[int] = [
                value_name2producer_id[arg] for arg in operation.get("args", [])
            ]
            memory_predecessor_ids: list[int] = machine.memory_predecessors(
                program, operation["id"]
            )
            predecessor_ids: list[int] = data_predecessor_ids + memory_predecessor_ids
            assert all(type(pred_id) is int for pred_id in predecessor_ids)
            self.op_id2prev_ops[operation["id"]] = [
                operations[pred_id] for pred_id in sorted(set(predecessor_ids))
            ]

    def latest_dependency(
        self, operation: Operation, ordering: tuple[int, ...] | None = None
    ) -> int:
        """Return the latest prerequisite's index in the ordering, or -1."""
        if ordering is None:
            ordering = tuple(range(len(self.op_id2prev_ops)))
        assert all(type(op_id) is int for op_id in ordering)
        # No transitive search is needed: each indirect prerequisite precedes
        # one of these direct prerequisites in any valid ordering.
        return max(
            (ordering.index(pred["id"]) for pred in self.op_id2prev_ops[operation["id"]]),
            default=-1,
        )


def reorder_program(
    program: dict[str, Any], ordering: tuple[int, ...]
) -> dict[str, Any]:
    """Copy a valid operation ordering into a program with consecutive new IDs.

    Ordering contains original operation IDs and must preserve dependencies.
    The input is unchanged; SSA names and buffer accesses are preserved.
    """
    return {
        **program,
        "operations": [
            dict(program["operations"][op_id], id=op_index)
            for op_index, op_id in enumerate(ordering)
        ],
    }
