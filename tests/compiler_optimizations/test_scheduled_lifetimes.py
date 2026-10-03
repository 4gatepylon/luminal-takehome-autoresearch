"""Tests issue-cycle ID coverage and inclusive value lifetimes for supplied schedules.

TODO(hadriano) no human has read these unit tests.
"""

import unittest

import compiler
import machine


class ScheduledLifetimeTests(unittest.TestCase):
    def test_issue_cycles_and_lifetimes(self):
        examples = [
            (
                "multiply latency and repeated operand",
                [
                    {"id": 0, "op": "const", "dest": "a", "value": 7},
                    {"id": 1, "op": "mul", "dest": "square", "args": ["a", "a"]},
                    {"id": 2, "op": "store", "args": ["square"], "buffer": "out", "offset": 0},
                    {"id": 3, "op": "store", "args": ["a"], "buffer": "out", "offset": 1},
                ],
                [{"load": [0]}, {"scalar": [1]}, {}, {"store": [2]}, {"store": [3]}],
                {0: 0, 1: 1, 2: 3, 3: 4},
                {"a": (1, 4), "square": (3, 3)},
            ),
            (
                "unused pending write overlaps a live scalar",
                [
                    {"id": 0, "op": "load", "dest": "unused", "buffer": "data", "offset": 0},
                    {"id": 1, "op": "const", "dest": "a", "value": 7},
                    {"id": 2, "op": "store", "args": ["a"], "buffer": "out", "offset": 0},
                ],
                [{"load": [0, 1]}, {}, {}, {}, {"store": [2]}],
                {0: 0, 1: 0, 2: 4},
                {"unused": (3, 3), "a": (1, 4)},
            ),
            (
                "reordered vector load, mixed engines, and write after final bundle",
                [
                    {"id": 0, "op": "vload", "dest": "v", "buffer": "data", "offset": 0},
                    {"id": 1, "op": "const", "dest": "a", "value": 2},
                    {"id": 2, "op": "splat", "dest": "broadcast", "args": ["a"]},
                    {"id": 3, "op": "vadd", "dest": "sum", "args": ["v", "broadcast"]},
                    {"id": 4, "op": "vstore", "args": ["sum"], "buffer": "out", "offset": 0},
                    {"id": 5, "op": "const", "dest": "unused", "value": 9},
                ],
                [
                    {"load": [1]}, {"load": [0], "vector": [2]}, {}, {}, {},
                    {"vector": [3]}, {}, {"store": [4], "load": [5]},
                ],
                {0: 1, 1: 0, 2: 1, 3: 5, 4: 7, 5: 7},
                {"v": (5, 5), "a": (1, 1), "broadcast": (2, 5), "sum": (6, 7), "unused": (8, 8)},
            ),
        ]
        for name, operations, bundles, expected_op_id2issue_cycle, expected_value_name2lifetime_incl in examples:
            with self.subTest(name=name):
                program = {
                    "name": name, "operations": operations,
                    "buffers": {"data": 8, "out": 8},
                    "cases": [{"data": list(range(8)), "out": [0] * 8}],
                }
                op_id2issue_cycle = compiler.find_issue_cycles(program, bundles)
                self.assertEqual(op_id2issue_cycle, expected_op_id2issue_cycle)
                value_name2lifetime_incl = compiler.find_lifetimes(program, op_id2issue_cycle)
                self.assertEqual(value_name2lifetime_incl, expected_value_name2lifetime_incl)
                compilation = {
                    "scratch": compiler.allocate_scratch_first_fit(program, value_name2lifetime_incl),
                    "bundles": bundles,
                }
                machine.check_compilation(program, compilation)
                machine.check_case(program, compilation, program["cases"][0])

    def test_issue_cycles_require_all_program_ids(self):
        program = {"operations": [{"id": op_id} for op_id in range(3)]}
        for op_ids in ([], [0, 1], [0, 2], [1, 2], [1, 2, 3], [-1, 0, 1], [0, 1, 2, 3]):
            with self.subTest(op_ids=op_ids):
                bundles = [{"load": [op_id]} for op_id in op_ids]
                with self.assertRaisesRegex(machine.CompileError, "must cover exactly"):
                    compiler.find_issue_cycles(program, bundles)

    def test_issue_cycles_reject_duplicate_ids(self):
        program = {"operations": [{"id": op_id} for op_id in range(3)]}
        examples = [
            ("within engine", [{"load": [0, 0]}, {"scalar": [1, 2]}]),
            ("across engines", [{"load": [0, 1], "scalar": [0, 2]}]),
            ("across cycles", [{"load": [0, 1]}, {"scalar": [2]}, {"load": [0]}]),
        ]
        for name, bundles in examples:
            with self.subTest(name=name):
                with self.assertRaisesRegex(machine.CompileError, "operation 0 appears more than once"):
                    compiler.find_issue_cycles(program, bundles)


if __name__ == "__main__":
    unittest.main()
