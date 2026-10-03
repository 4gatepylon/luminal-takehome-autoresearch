"""Test beam reordering against exhaustive tiny-DAG costs and machine contracts."""

from copy import deepcopy
from itertools import islice
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from compiler import compile_program
from compiler.compilation import compile_with_ordering
from compiler.custom_scheduling import SCHEDULER_NAME2ORDERINGS_FN
from compiler.custom_scheduling.beam_pressure_codex import beam_orderings, candidate_orderings
from compiler.custom_scheduling.dag_pressure_codex import dag_orderings
import machine


PROGRAM_DIR = Path(__file__).parents[2] / "programs"
DIAGNOSTIC_PATHS = tuple(
    PROGRAM_DIR / "scheduling_diagnostics" / name
    for name in (
        "01_shared_roots_fanout.json",
        "02_shared_value_branches.json",
        "03_mixed_width_overlap.json",
        "04_partial_overlap_barrier.json",
    )
)


def prerequisites(program):
    producers = machine.producer_map(program)
    return [
        {producers[arg] for arg in operation.get("args", [])}
        | set(machine.memory_predecessors(program, operation["id"]))
        for operation in program["operations"]
    ]


def legal_orders(program):
    dependencies = prerequisites(program)

    def visit(order, completed):
        if len(order) == len(dependencies):
            yield order
            return
        for op_id, predecessors in enumerate(dependencies):
            if op_id not in completed and predecessors <= completed:
                yield from visit(order + (op_id,), completed | {op_id})

    yield from visit((), set())


def cost(program, compilation):
    return len(compilation["bundles"]) * machine.scratch_footprint(program, compilation)


def contract_program():
    operations = [
        {"op": "vload", "dest": "before", "buffer": "data", "offset": 0},
        {"op": "const", "dest": "seed", "value": 7},
        {"op": "mul", "dest": "square", "args": ["seed", "seed"]},
        {"op": "store", "args": ["square"], "buffer": "data", "offset": 3},
        {"op": "vload", "dest": "after", "buffer": "data", "offset": 0},
        {"op": "vstore", "args": ["before"], "buffer": "data", "offset": 2},
        {"op": "load", "dest": "unused_scalar", "buffer": "data", "offset": 3},
        {"op": "vmul", "dest": "unused_vector", "args": ["after", "after"]},
        {"op": "vstore", "args": ["after"], "buffer": "out", "offset": 0},
    ]
    return {
        "name": "beam_memory_and_pending_writes",
        "buffers": {"data": 16, "out": 8},
        "operations": [dict(operation, id=index) for index, operation in enumerate(operations)],
        "cases": [{"data": list(range(16)), "out": [0] * 8}],
    }


class BeamSchedulingTests(unittest.TestCase):
    def assert_valid_order(self, program, ordering):
        self.assertIsInstance(ordering, tuple)
        self.assertTrue(all(type(op_id) is int for op_id in ordering))
        self.assertEqual(sorted(ordering), list(range(len(program["operations"]))))
        positions = {op_id: index for index, op_id in enumerate(ordering)}
        for op_id, predecessors in enumerate(prerequisites(program)):
            for predecessor in predecessors:
                self.assertLess(positions[predecessor], positions[op_id])
        compilation = compile_with_ordering(program, ordering, "first-fit")
        machine.check_compilation(program, compilation)
        for case in program["cases"]:
            machine.check_case(program, compilation, case)
        return compilation

    def test_raw_beam_matches_exhaustive_topological_order_cost(self):
        for path in DIAGNOSTIC_PATHS:
            with self.subTest(program=path.name):
                program = machine.load_program(path)
                exhaustive = list(islice(legal_orders(program), 201))
                self.assertTrue(exhaustive)
                self.assertLessEqual(len(exhaustive), 200)
                optimum = min(
                    cost(program, self.assert_valid_order(program, ordering))
                    for ordering in exhaustive
                )
                candidates = tuple(beam_orderings(program, beam_width=512, max_expansions=20000))
                self.assertTrue(candidates)
                self.assertEqual(
                    min(
                        cost(program, self.assert_valid_order(program, ordering))
                        for ordering in candidates
                    ),
                    optimum,
                )

    def test_raw_beam_is_deterministic_preserves_input_and_machine_contracts(self):
        program = contract_program()
        original = deepcopy(program)
        candidates = tuple(beam_orderings(program, beam_width=16, max_expansions=2000))
        self.assertTrue(candidates)
        self.assertEqual(
            candidates, tuple(beam_orderings(program, beam_width=16, max_expansions=2000))
        )
        for ordering in candidates:
            self.assert_valid_order(program, ordering)
        self.assertEqual(program, original)

    def test_budget_too_small_to_complete_an_order_yields_no_candidates(self):
        program = contract_program()
        original = deepcopy(program)
        # One expansion appends one operation, so these budgets cannot finish
        # this multi-operation program even along a single search path.
        for budget in (0, 1):
            with self.subTest(budget=budget):
                self.assertEqual(
                    tuple(beam_orderings(program, beam_width=1, max_expansions=budget)), ()
                )
        self.assertEqual(program, original)

    def test_invalid_search_bounds_are_rejected(self):
        program = contract_program()
        for options in (
            {"beam_width": 0}, {"beam_width": -1}, {"beam_width": True},
            {"beam_width": 1.5}, {"max_expansions": -1}, {"max_expansions": True},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                tuple(beam_orderings(program, **options))

    def test_portfolio_keeps_dag_candidates_when_raw_search_has_no_result(self):
        program = contract_program()
        module = sys.modules[candidate_orderings.__module__]
        with patch.object(module, "beam_orderings", return_value=iter(())) as raw_search:
            candidates = tuple(candidate_orderings(program))
        raw_search.assert_called_once()
        self.assertTrue(set(dag_orderings(program)) <= set(candidates))
        for ordering in candidates:
            self.assert_valid_order(program, ordering)

    def test_registered_portfolio_preserves_results_and_dag_objective(self):
        self.assertIs(SCHEDULER_NAME2ORDERINGS_FN["beam-pressure-codex"], candidate_orderings)
        paths = sorted((PROGRAM_DIR / "original_programs").glob("*.json")) + list(DIAGNOSTIC_PATHS)
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(program=path.name):
                program = machine.load_program(path)
                dag = compile_program(program, "first-fit", scheduling_strategy="dag-pressure-codex")
                beam = compile_program(program, "first-fit", scheduling_strategy="beam-pressure-codex")
                machine.check_compilation(program, beam)
                for case in program["cases"]:
                    machine.check_case(program, beam, case)
                self.assertLessEqual(cost(program, beam), cost(program, dag))


if __name__ == "__main__":
    unittest.main()
