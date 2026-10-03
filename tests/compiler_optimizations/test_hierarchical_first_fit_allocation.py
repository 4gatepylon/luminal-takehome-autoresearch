"""Check hierarchical first-fit allocation:

- Vectors are placed first; each value uses the lowest aligned range with disjoint lifetimes.
- Exhausted scratch raises CompileError.
- Forced allocation executes the original programs correctly using this allocator.
- The pinned-block fixture uses 128 words, compared with chronological first-fit's 240.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from compiler import compilation as compiler_compilation
from compiler.allocation import allocate_scratch_hierarchical_first_fit
import machine


class HierarchicalFirstFitTests(unittest.TestCase):
    def test_hierarchical_first_fit_allocation(self):
        # Each value is (name, width, write_cycle_incl, last_live_cycle_incl).
        examples = [
            (
                "vectors precede an earlier scalar",
                [("a", 1, 1, 9), ("v", 8, 4, 6), ("w", 8, 5, 7)],
                {"v": 0, "w": 8, "a": 16},
            ),
            (
                "reuse before between and after vectors; endpoints still conflict",
                [("v", 8, 4, 5), ("w", 8, 8, 9), ("before", 1, 1, 3),
                 ("between", 1, 6, 7), ("after", 1, 10, 11),
                 ("touch_v", 1, 5, 6), ("touch_w", 1, 7, 8)],
                {"v": 0, "w": 0, "before": 0, "between": 0, "after": 0,
                 "touch_v": 8, "touch_w": 8},
            ),
            (
                "all vector reservations matter, not just the latest",
                [("v", 8, 4, 5), ("w", 8, 8, 9), ("a", 1, 1, 6)],
                {"v": 0, "w": 0, "a": 8},
            ),
            (
                "scalar uses a free higher vector block before extending footprint",
                [("v", 8, 1, 9), ("w", 8, 5, 6), ("a", 1, 3, 4)],
                {"v": 0, "w": 8, "a": 8},
            ),
            (
                "scalars share tail words unless simultaneously live",
                [("v", 8, 1, 9), ("a", 1, 2, 3), ("b", 1, 4, 5), ("c", 1, 4, 5)],
                {"v": 0, "a": 8, "b": 8, "c": 9},
            ),
            ("scalars only", [("a", 1, 1, 2), ("b", 1, 3, 4)], {"a": 0, "b": 0}),
            ("vectors only", [("v", 8, 1, 2), ("w", 8, 3, 4)], {"v": 0, "w": 0}),
        ]
        for name, values, expected_value_name2scratch_address in examples:
            with self.subTest(name=name):
                program = {"operations": [
                    {"dest": value_name, "op": "vload" if width == 8 else "const"}
                    for value_name, width, _, _ in values
                ]}
                value_name2lifetime_incl = {
                    value_name: (write_cycle_incl, last_live_cycle_incl)
                    for value_name, _, write_cycle_incl, last_live_cycle_incl in values
                }
                self.assertEqual(
                    allocate_scratch_hierarchical_first_fit(program, value_name2lifetime_incl),
                    expected_value_name2scratch_address,
                )

    def test_raises_when_no_range_fits(self):
        program = {"operations": [
            {"op": "vload", "dest": "v"}, {"op": "const", "dest": "a"},
        ]}
        with patch.object(machine, "SCRATCH_WORDS", 8):
            with self.assertRaisesRegex(machine.CompileError, "no scratch space"):
                allocate_scratch_hierarchical_first_fit(
                    program, {"v": (1, 3), "a": (2, 2)}
                )

    def test_forced_hierarchical_first_fit_on_public_programs(self):
        paths = sorted((Path(__file__).parents[2] / "programs" / "original_programs").glob("*.json"))
        self.assertTrue(paths)
        with patch.object(compiler_compilation, "allocate_scratch_first_fit", side_effect=AssertionError("unexpected first-fit")):
            for path in paths:
                with self.subTest(program=path.name):
                    program = machine.load_program(path)
                    compilation = compiler_compilation.compile_program(
                        program, scratch_allocation_strategy="hierarchical-first-fit"
                    )
                    machine.check_compilation(program, compilation)
                    for case in program["cases"]:
                        machine.check_case(program, compilation, case)

    def test_pinned_vector_blocks_footprint(self):
        program = machine.load_program(
            Path(__file__).parents[2] / "programs" / "allocation_diagnostics" / "08_pinned_vector_blocks.json"
        )
        for strategy, expected_words in (("first-fit", 240), ("hierarchical-first-fit", 128)):
            with self.subTest(strategy=strategy):
                compilation = compiler_compilation.compile_program(program, scratch_allocation_strategy=strategy)
                self.assertEqual(machine.scratch_footprint(program, compilation), expected_words)


if __name__ == "__main__":
    unittest.main()
