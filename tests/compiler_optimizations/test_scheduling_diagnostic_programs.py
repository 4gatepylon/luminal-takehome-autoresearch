"""Check scheduling diagnostic programs against the machine and reference interpreter."""

import unittest

from compiler import compile_program
from compiler.custom_scheduling import SCHEDULER_NAME2ORDERINGS_FN
import machine
import score


class SchedulingDiagnosticProgramTests(unittest.TestCase):
    def test_diagnostic_programs_with_registered_schedulers_and_allocators(self):
        for filename in score.PROGRAM_GROUPS["scheduling_diagnostics"]:
            program = machine.load_program(score.PROGRAM_DIR / filename)
            for scheduler in ("source", *SCHEDULER_NAME2ORDERINGS_FN):
                for allocator in ("any", "disjoint", "first-fit", "hierarchical-first-fit"):
                    with self.subTest(program=filename, scheduler=scheduler, allocator=allocator):
                        compilation = compile_program(
                            program, allocator, scheduling_strategy=scheduler
                        )
                        machine.check_compilation(program, compilation)
                        for case in program["cases"]:
                            machine.check_case(program, compilation, case)


if __name__ == "__main__":
    unittest.main()
