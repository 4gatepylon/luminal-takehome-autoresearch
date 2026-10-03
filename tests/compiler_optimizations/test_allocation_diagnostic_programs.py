"""Check these properties of the allocation diagnostic programs:

- The three capacity fixtures require exactly 256 disjoint scratch words.
- Automatic selection and each forced allocation strategy produce the same final
  buffers as the reference interpreter for every input case.
- Each compilation issues every operation exactly once, respects operand readiness,
  memory ordering and engine limits, and uses aligned, in-bounds scratch ranges
  that do not overlap for simultaneously live values.
"""

import unittest

from compiler import compile_program
import machine
import score


class AllocationDiagnosticProgramTests(unittest.TestCase):
    def test_extreme_programs_fill_disjoint_scratch_capacity(self):
        for filename in (
            "06_retained_vectors_16.json",
            "07_rolling_vectors_15_of_16.json",
            "08_pinned_vector_blocks.json",
        ):
            with self.subTest(program=filename):
                program = machine.load_program(score.PROGRAM_DIR / "allocation_diagnostics" / filename)
                baseline = machine.serial_compile(program)
                self.assertEqual(machine.scratch_footprint(program, baseline), machine.SCRATCH_WORDS)

    def test_diagnostic_programs_with_each_supported_strategy(self):
        for filename in score.PROGRAM_GROUPS["allocation_diagnostics"]:
            program = machine.load_program(score.PROGRAM_DIR / filename)
            for strategy in (None, "first-fit", "disjoint", "hierarchical-first-fit"):
                with self.subTest(program=filename, strategy=strategy):
                    compilation = compile_program(program, scratch_allocation_strategy=strategy)
                    machine.check_compilation(program, compilation)
                    for case in program["cases"]:
                        machine.check_case(program, compilation, case)


if __name__ == "__main__":
    unittest.main()
