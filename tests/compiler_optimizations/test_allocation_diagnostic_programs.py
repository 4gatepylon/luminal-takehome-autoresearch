"""Tests allocation diagnostic fixtures for correct execution under supported strategies.

Checks the machine contract and final memory, not heuristic address choices or scores.
"""

import unittest

from compiler import compiler
import machine
import score


class AllocationDiagnosticProgramTests(unittest.TestCase):
    def test_diagnostic_programs_with_each_supported_strategy(self):
        for filename in score.PROGRAM_GROUPS["allocation_diagnostics"]:
            program = machine.load_program(score.PROGRAM_DIR / filename)
            for strategy in (None, "first-fit", "disjoint"):
                with self.subTest(program=filename, strategy=strategy):
                    compilation = compiler.compile_program(program, scratch_allocation_strategy=strategy)
                    machine.check_compilation(program, compilation)
                    for case in program["cases"]:
                        machine.check_case(program, compilation, case)


if __name__ == "__main__":
    unittest.main()
