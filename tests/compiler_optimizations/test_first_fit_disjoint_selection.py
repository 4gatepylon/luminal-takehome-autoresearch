"""Tests "any" selection between first-fit and disjoint scratch allocations.

TODO(hadriano) no human has read these unit tests.
"""

import unittest
from unittest.mock import patch

from compiler import compile_program
from compiler.allocation import allocate_scratch_first_fit, find_lifetimes
from compiler.scheduling import find_issue_cycles, schedule_operations
import machine


class FirstFitDisjointSelectionTests(unittest.TestCase):
    def test_auto_chooses_disjoint_when_first_fit_fails_or_uses_more_space(self):
        program = {
            "name": "fragmentation", "buffers": {"data": 8, "out": 17},
            "operations": [
                {"id": 0, "op": "vload", "dest": "v", "buffer": "data", "offset": 0},
                {"id": 1, "op": "const", "dest": "a", "value": 7},
                {"id": 2, "op": "vload", "dest": "w", "buffer": "data", "offset": 0},
                {"id": 3, "op": "vstore", "args": ["w"], "buffer": "out", "offset": 0},
                {"id": 4, "op": "vstore", "args": ["v"], "buffer": "out", "offset": 8},
                {"id": 5, "op": "store", "args": ["a"], "buffer": "out", "offset": 16},
            ],
            "cases": [{"data": list(range(8)), "out": [0] * 17}],
        }
        bundles = schedule_operations(program)
        op_id2issue_cycle = find_issue_cycles(program, bundles)
        value_name2lifetime_incl = find_lifetimes(program, op_id2issue_cycle)
        for scratch_words in (17, 24):
            with self.subTest(scratch_words=scratch_words), patch.object(machine, "SCRATCH_WORDS", scratch_words):
                if scratch_words == 17:
                    with self.assertRaisesRegex(machine.CompileError, "no scratch space"):
                        allocate_scratch_first_fit(program, value_name2lifetime_incl)
                else:
                    self.assertEqual(
                        allocate_scratch_first_fit(program, value_name2lifetime_incl),
                        {"a": 0, "v": 8, "w": 16},
                    )
                compilation = compile_program(program, scratch_allocation_strategy="any")
                self.assertEqual(compilation["scratch"], {"v": 0, "w": 8, "a": 16})
                machine.check_compilation(program, compilation)
                machine.check_case(program, compilation, program["cases"][0])
        with patch.object(machine, "SCRATCH_WORDS", 16):
            with self.assertRaises(machine.CompileError):
                compile_program(program, scratch_allocation_strategy="any")

    def test_auto_preserves_disjoint_failure_and_selects_smaller_first_fit(self):
        program = {
            "name": "reuse", "buffers": {"out": 2},
            "operations": [
                {"id": 0, "op": "const", "dest": "a", "value": 7},
                {"id": 1, "op": "store", "args": ["a"], "buffer": "out", "offset": 0},
                {"id": 2, "op": "const", "dest": "b", "value": 9},
                {"id": 3, "op": "store", "args": ["b"], "buffer": "out", "offset": 1},
            ],
            "cases": [{"out": [0, 0]}],
        }
        for scratch_words in (1, 2):
            with self.subTest(scratch_words=scratch_words), patch.object(machine, "SCRATCH_WORDS", scratch_words):
                if scratch_words == 1:
                    with self.assertRaises(machine.CompileError):
                        machine.serial_compile(program)
                    with self.assertRaises(machine.CompileError):
                        compile_program(program, scratch_allocation_strategy="any")
                    continue
                first_fit = compile_program(program, scratch_allocation_strategy="first-fit")
                self.assertEqual(machine.scratch_footprint(program, first_fit), 1)
                compilation = compile_program(program, scratch_allocation_strategy="any")
                self.assertEqual(compilation["scratch"], first_fit["scratch"])
                machine.check_compilation(program, compilation)
                machine.check_case(program, compilation, program["cases"][0])


if __name__ == "__main__":
    unittest.main()
