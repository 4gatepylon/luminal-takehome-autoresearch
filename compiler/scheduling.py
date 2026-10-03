"""Operation scheduling and issue-cycle analysis."""

from __future__ import annotations

import machine


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
