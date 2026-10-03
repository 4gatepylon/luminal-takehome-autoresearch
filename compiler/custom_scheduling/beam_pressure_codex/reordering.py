"""Bounded DAG beam search with latency-aware lower bounds on live scratch."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from math import ceil

import machine

from compiler.custom_scheduling.dag_pressure_codex import dag_orderings
from compiler.reordering import OperationDependencies


_ENGINES = tuple(machine.ENGINE_LIMITS)
_LIMITS = tuple(machine.ENGINE_LIMITS.values())


class _Graph:
    def __init__(self, program: dict) -> None:
        operations = program["operations"]
        self.size = len(operations)
        specs = [machine.OP_SPECS[op["op"]] for op in operations]
        self.engines = [spec["engine"] for spec in specs]
        self.widths = [
            machine.VLEN if spec["result"] == "vector" else int(spec["result"] is not None)
            for spec in specs
        ]
        producer = machine.producer_map(program)
        inputs = [{producer[arg] for arg in op.get("args", [])} for op in operations]
        dependencies = OperationDependencies(program)
        self.predecessors = [
            {
                pred["id"]: specs[pred["id"]]["latency"] if pred["id"] in inputs[op_id] else 1
                for pred in dependencies.op_id2prev_ops[op_id]
            }
            for op_id in range(self.size)
        ]
        self.consumers: list[set[int]] = [set() for _ in operations]
        for op_id, args in enumerate(inputs):
            for pred in args:
                self.consumers[pred].add(op_id)


@dataclass(frozen=True)
class _State:
    order: tuple[int, ...]
    issued: int
    issue_cycles: tuple[int, ...]
    cycle: int
    slots: tuple[int, ...]


class _Search:
    def __init__(self, program: dict) -> None:
        self.graph = _Graph(program)
        self.latencies = [machine.OP_SPECS[op["op"]]["latency"] for op in program["operations"]]
        self.engines = [_ENGINES.index(engine) for engine in self.graph.engines]
        self.prerequisites = [sum(1 << pred for pred in preds) for preds in self.graph.predecessors]
        self.users = [sum(1 << user for user in users) for users in self.graph.consumers]

    def append(self, state: _State, op_id: int) -> _State:
        graph = self.graph
        engine = self.engines[op_id]
        issue = max(state.cycle, max(
            (state.issue_cycles[pred] + delay for pred, delay in graph.predecessors[op_id].items()),
            default=0,
        ))
        if issue == state.cycle and state.slots[engine] == _LIMITS[engine]:
            issue += 1
        slots = list(state.slots) if issue == state.cycle else [0] * len(_ENGINES)
        slots[engine] += 1
        issues = state.issue_cycles[:op_id] + (issue,) + state.issue_cycles[op_id + 1:]
        return _State(state.order + (op_id,), state.issued | (1 << op_id), issues, issue, tuple(slots))

    def rank(self, state: _State) -> tuple[int, int, int, int]:
        graph = self.graph
        earliest = list(state.issue_cycles)
        remaining = [0] * len(_ENGINES)
        for op_id in range(graph.size):
            if earliest[op_id] >= 0:
                continue
            engine = self.engines[op_id]
            earliest[op_id] = max(state.cycle, max(
                (earliest[pred] + delay for pred, delay in graph.predecessors[op_id].items()),
                default=0,
            ))
            if earliest[op_id] == state.cycle and state.slots[engine] == _LIMITS[engine]:
                earliest[op_id] += 1
            remaining[engine] += 1
        cycles = max(earliest) + 1
        for engine, count in enumerate(remaining):
            if count:
                cycles = max(cycles, state.cycle + ceil((state.slots[engine] + count) / _LIMITS[engine]))

        # Issued values have fixed write times. Each must survive through the
        # earliest possible issue of every consumer, including unscheduled ones.
        # Unused results occupy their write cycle, even after the last bundle.
        events: dict[int, int] = {}
        frontier_words = 0
        area = 0
        for op_id, issue in enumerate(state.issue_cycles):
            width = graph.widths[op_id]
            if issue < 0 or width == 0:
                continue
            start = issue + self.latencies[op_id]
            end = max(start, max((earliest[user] for user in graph.consumers[op_id]), default=0))
            if self.users[op_id] & ~state.issued:
                frontier_words += width
            events[start] = events.get(start, 0) + width
            events[end + 1] = events.get(end + 1, 0) - width
            area += (end - start + 1) * width
        active = peak = 0
        for cycle in sorted(events):
            active += events[cycle]
            peak = max(peak, active)
        return cycles * peak, frontier_words, area, state.cycle


def beam_orderings(
    program: dict, *, beam_width: int = 64, max_expansions: int = 20_000,
) -> Iterator[tuple[int, ...]]:
    """Yield complete legal orders from a deterministic bounded beam search.

    Exhausting the expansion budget before completion yields no candidates.
    Each expansion appends one dependency-ready operation to one partial state.
    """
    if type(beam_width) is not int or beam_width < 1:
        raise ValueError("beam_width must be a positive integer")
    if type(max_expansions) is not int or max_expansions < 0:
        raise ValueError("max_expansions must be a nonnegative integer")
    search = _Search(program)
    size = search.graph.size
    states = [_State((), 0, (-1,) * size, 0, (0,) * len(_ENGINES))]
    expansions = 0
    for _ in range(size):
        candidates = {}
        for state in states:
            for op_id, prerequisites in enumerate(search.prerequisites):
                if state.issued & (1 << op_id) or prerequisites & state.issued != prerequisites:
                    continue
                if expansions == max_expansions:
                    return
                expansions += 1
                candidate = search.append(state, op_id)
                # All historical issue times determine lifetimes and the packer
                # state. Different histories remain distinct search candidates.
                signature = candidate.issue_cycles, candidate.slots
                if signature not in candidates:
                    candidates[signature] = search.rank(candidate), candidate
        ranked = sorted(candidates.values(), key=lambda item: item[0])
        by_frontier: dict[int, list[tuple[tuple[int, ...], _State]]] = {}
        for pair in ranked:
            by_frontier.setdefault(pair[1].issued, []).append(pair)
        # Reserve breadth for different sets of issued operations. This is a
        # heuristic beam quota, not a dominance assertion about partial states.
        quota = max(1, beam_width // min(len(by_frontier), 32))
        shortlisted = [pair for group in by_frontier.values() for pair in group[:quota]]
        states = [state for _, state in sorted(shortlisted, key=lambda item: item[0])[:beam_width]]
    for state in states:
        yield state.order


def candidate_orderings(program: dict) -> Iterator[tuple[int, ...]]:
    """Yield DAG-policy incumbents and complete orders from bounded beam search.

    Partial states rank by a cycles-times-live-words lower bound. Complete
    candidates are allocated and selected by the compilation pipeline. Search
    width decreases for larger DAGs; operation and expansion bounds keep the
    candidate generator deterministic and bounded.
    """
    seen = set()
    for order in dag_orderings(program):
        seen.add(order)
        yield order
    size = len(program["operations"])
    if size > 64:
        return
    for order in beam_orderings(
        program, beam_width=512 if size <= 24 else 32, max_expansions=100_000,
    ):
        if order not in seen:
            seen.add(order)
            yield order
