"""Test DAG ordering dependencies, deterministic candidates, and latency priorities."""

from copy import deepcopy
import unittest

from compiler import compile_program
from compiler.custom_scheduling.dag_pressure_codex import dag_ordering, dag_orderings
from compiler.reordering import reorder_program
import machine


POLICIES = ("critical-path", "balanced", "pressure", "critical-first", "pressure-first")
DIRECTIONS = ("forward", "backward")


def make_program(operations):
    return {
        "name": "dag_ordering_contract",
        "buffers": {"data": 16, "out": 16},
        "operations": [dict(operation, id=index) for index, operation in enumerate(operations)],
        "cases": [{"data": list(range(16)), "out": [0] * 16}],
    }


class DagReorderingTests(unittest.TestCase):
    def assert_replays_original(self, program, ordering):
        self.assertIsInstance(ordering, tuple)
        self.assertEqual(sorted(ordering), list(range(len(program["operations"]))))
        positions = {op_id: index for index, op_id in enumerate(ordering)}
        producers = machine.producer_map(program)
        for operation in program["operations"]:
            predecessors = {producers[arg] for arg in operation.get("args", [])}
            predecessors.update(machine.memory_predecessors(program, operation["id"]))
            for predecessor in predecessors:
                self.assertLess(positions[predecessor], positions[operation["id"]])

        reordered = reorder_program(program, ordering)
        machine.validate_program(reordered)
        compilation = compile_program(reordered, scheduling_strategy="source")
        compilation["bundles"] = [
            {engine: [ordering[op_id] for op_id in op_ids] for engine, op_ids in bundle.items()}
            for bundle in compilation["bundles"]
        ]
        machine.check_compilation(program, compilation)
        for case in program["cases"]:
            machine.check_case(program, compilation, case)

    def test_policies_preserve_repeated_operands_and_unused_pending_writes(self):
        program = make_program([
            {"op": "load", "dest": "unused_scalar", "buffer": "data", "offset": 0},
            {"op": "const", "dest": "seed", "value": 7},
            {"op": "mul", "dest": "square", "args": ["seed", "seed"]},
            {"op": "vload", "dest": "unused_vector", "buffer": "data", "offset": 0},
            {"op": "splat", "dest": "broadcast", "args": ["square"]},
            {"op": "vmul", "dest": "product", "args": ["broadcast", "broadcast"]},
            {"op": "vstore", "args": ["product"], "buffer": "out", "offset": 0},
            {"op": "store", "args": ["seed"], "buffer": "out", "offset": 8},
        ])
        original = deepcopy(program)
        for policy in POLICIES:
            for direction in DIRECTIONS:
                with self.subTest(policy=policy, direction=direction):
                    ordering = dag_ordering(program, policy=policy, direction=direction)
                    self.assert_replays_original(program, ordering)
                    self.assertEqual(program, original)

    def test_policies_preserve_overlapping_scalar_and_vector_memory_accesses(self):
        program = make_program([
            {"op": "vload", "dest": "before", "buffer": "data", "offset": 0},
            {"op": "const", "dest": "replacement", "value": 23},
            {"op": "store", "args": ["replacement"], "buffer": "data", "offset": 3},
            {"op": "vload", "dest": "after", "buffer": "data", "offset": 0},
            {"op": "vstore", "args": ["before"], "buffer": "data", "offset": 2},
            {"op": "load", "dest": "last", "buffer": "data", "offset": 3},
            {"op": "vstore", "args": ["after"], "buffer": "out", "offset": 0},
            {"op": "store", "args": ["last"], "buffer": "out", "offset": 8},
        ])
        for policy in POLICIES:
            for direction in DIRECTIONS:
                with self.subTest(policy=policy, direction=direction):
                    self.assert_replays_original(
                        program, dag_ordering(program, policy=policy, direction=direction)
                    )

    def test_critical_path_can_prioritize_later_load_of_the_same_memory(self):
        program = make_program([
            {"op": "load", "dest": "short", "buffer": "data", "offset": 0},
            {"op": "load", "dest": "long", "buffer": "data", "offset": 0},
            {"op": "mul", "dest": "square", "args": ["long", "long"]},
            {"op": "mul", "dest": "fourth", "args": ["square", "square"]},
            {"op": "store", "args": ["short"], "buffer": "out", "offset": 0},
            {"op": "store", "args": ["fourth"], "buffer": "out", "offset": 1},
        ])
        ordering = dag_ordering(program, policy="critical-path", direction="forward")
        self.assertLess(ordering.index(1), ordering.index(0))
        self.assert_replays_original(program, ordering)

    def test_candidates_are_deterministic_unique_valid_and_leave_input_unchanged(self):
        program = make_program([
            {"op": "load", "dest": "a", "buffer": "data", "offset": 0},
            {"op": "mul", "dest": "square", "args": ["a", "a"]},
            {"op": "store", "args": ["square"], "buffer": "out", "offset": 0},
            {"op": "load", "dest": "b", "buffer": "data", "offset": 1},
            {"op": "store", "args": ["b"], "buffer": "out", "offset": 1},
        ])
        original = deepcopy(program)
        candidates = tuple(dag_orderings(program))
        self.assertTrue(candidates)
        self.assertEqual(candidates, tuple(dag_orderings(program)))
        self.assertEqual(len(candidates), len(set(candidates)))
        for ordering in candidates:
            self.assert_replays_original(program, ordering)
        self.assertEqual(program, original)

    def test_default_policy_and_direction_are_explicitly_selectable(self):
        program = make_program([{"op": "const", "dest": "unused", "value": 1}])
        self.assertEqual(
            dag_ordering(program),
            dag_ordering(program, policy="balanced", direction="forward"),
        )
        self.assert_replays_original(program, dag_ordering(program))

    def test_unknown_policy_or_direction_is_rejected(self):
        program = make_program([{"op": "const", "dest": "unused", "value": 1}])
        with self.assertRaises(ValueError):
            dag_ordering(program, policy="unknown")
        with self.assertRaises(ValueError):
            dag_ordering(program, direction="unknown")


if __name__ == "__main__":
    unittest.main()
