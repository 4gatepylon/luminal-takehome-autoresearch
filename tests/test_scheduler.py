"""Regression tests for greedy source-order scheduling."""

import unittest

import compiler
import machine


class SchedulerTests(unittest.TestCase):
    def check_schedule(self, operations, expected):
        program = {
            "name": "scheduler",
            "buffers": {"data": 1},
            "operations": [dict(operation, id=i) for i, operation in enumerate(operations)],
            "cases": [{"data": [7]}],
        }
        machine.validate_program(program)
        compilation = compiler.compile_program(program)
        self.assertEqual(compilation["bundles"], expected)
        machine.check_case(program, compilation, program["cases"][0])

    def test_packs_multiple_engines_and_advances_when_slots_are_full(self):
        self.check_schedule(
            [
                {"op": "const", "dest": "a", "value": 2},
                {"op": "const", "dest": "b", "value": 3},
                {"op": "const", "dest": "c", "value": 4},
                {"op": "add", "dest": "sum", "args": ["a", "b"]},
                {"op": "sub", "dest": "difference", "args": ["a", "b"]},
                {"op": "xor", "dest": "bits", "args": ["a", "b"]},
            ],
            [
                {"load": [0, 1]},
                {"load": [2], "scalar": [3, 4]},
                {"scalar": [5]},
            ],
        )

    def test_stalls_for_latency_without_skipping_a_blocked_instruction(self):
        self.check_schedule(
            [
                {"op": "load", "dest": "a", "buffer": "data", "offset": 0},
                {"op": "add", "dest": "sum", "args": ["a", "a"]},
                {"op": "const", "dest": "b", "value": 3},
                {"op": "store", "args": ["sum"], "buffer": "data", "offset": 0},
            ],
            [
                {"load": [0]},
                {},
                {},
                {"scalar": [1], "load": [2]},
                {"store": [3]},
            ],
        )

    def test_keeps_overlapping_memory_operations_in_separate_cycles(self):
        self.check_schedule(
            [
                {"op": "const", "dest": "a", "value": 2},
                {"op": "store", "args": ["a"], "buffer": "data", "offset": 0},
                {"op": "load", "dest": "b", "buffer": "data", "offset": 0},
                {"op": "store", "args": ["a"], "buffer": "data", "offset": 0},
            ],
            [{"load": [0]}, {"store": [1]}, {"load": [2]}, {"store": [3]}],
        )


if __name__ == "__main__":
    unittest.main()
