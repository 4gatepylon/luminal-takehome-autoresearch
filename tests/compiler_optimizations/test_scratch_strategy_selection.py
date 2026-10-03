"""Check allocator selection with controlled allocator results:

- The "any" strategy chooses the smallest successful footprint.
- Forcing a strategy invokes that allocator and returns its allocation.
- Disjoint allocation failure stops compilation; forced reuse failure raises RuntimeError.

TODO(hadriano) no human has read this.
"""

import unittest
from unittest.mock import patch

from compiler import compilation as compiler_compilation
import machine


class ScratchStrategySelectionTests(unittest.TestCase):
    def setUp(self):
        self.program = {
            "name": "selection", "buffers": {"out": 1},
            "operations": [
                {"id": 0, "op": "const", "dest": "a", "value": 7},
                {"id": 1, "op": "store", "args": ["a"], "buffer": "out", "offset": 0},
            ],
            "cases": [{"out": [0]}],
        }

    def test_selects_requested_strategy_or_smallest_successful_footprint(self):
        exhausted = machine.CompileError("out of space")
        # Strategy, disjoint result, first-fit result, hierarchical result, chosen result.
        examples = [
            ("any", {"a": 2}, {"a": 1}, {"a": 0}, {"a": 0}),
            ("any", {"a": 2}, {"a": 0}, {"a": 1}, {"a": 0}),
            ("any", {"a": 0}, {"a": 1}, {"a": 2}, {"a": 0}),
            ("any", {"a": 2}, exhausted, {"a": 0}, {"a": 0}),
            ("any", {"a": 2}, {"a": 0}, exhausted, {"a": 0}),
            ("any", {"a": 2}, exhausted, exhausted, {"a": 2}),
            ("disjoint", {"a": 2}, {"a": 0}, {"a": 1}, {"a": 2}),
            ("first-fit", {"a": 0}, {"a": 2}, {"a": 1}, {"a": 2}),
            ("hierarchical-first-fit", {"a": 0}, {"a": 1}, {"a": 2}, {"a": 2}),
        ]
        for strategy, disjoint_result, first_fit_result, hierarchical_result, expected_result in examples:
            def allocate(program, value_name2lifetime_incl, *, mode="default"):
                result = {"default": first_fit_result, "vectors_first": hierarchical_result}[mode]
                if isinstance(result, Exception):
                    raise result
                return result

            with (
                self.subTest(strategy=strategy, results=(disjoint_result, first_fit_result, hierarchical_result)),
                patch.object(compiler_compilation, "allocate_unique_scratch", side_effect=[disjoint_result]) as disjoint,
                patch.object(compiler_compilation, "allocate_scratch_first_fit", side_effect=allocate) as first_fit,
            ):
                compilation = compiler_compilation.compile_program(self.program, scratch_allocation_strategy=strategy, n_optimization_iterations=0)
                self.assertEqual(compilation["scratch"], expected_result)
                disjoint.assert_called_once()
                expected_modes = {
                    "any": ["default", "vectors_first"], "disjoint": [],
                    "first-fit": ["default"], "hierarchical-first-fit": ["vectors_first"],
                }[strategy]
                self.assertEqual(
                    sorted(call.kwargs.get("mode", "default") for call in first_fit.call_args_list),
                    expected_modes,
                )
                machine.check_compilation(self.program, compilation)
                machine.check_case(self.program, compilation, self.program["cases"][0])

    def test_disjoint_failure_stops_every_strategy_before_reuse(self):
        for strategy in ("any", "disjoint", "first-fit", "hierarchical-first-fit"):
            with (
                self.subTest(strategy=strategy),
                patch.object(compiler_compilation, "allocate_unique_scratch", side_effect=machine.CompileError("baseline full")),
                patch.object(compiler_compilation, "allocate_scratch_first_fit") as first_fit,
            ):
                with self.assertRaisesRegex(machine.CompileError, "baseline full"):
                    compiler_compilation.compile_program(self.program, scratch_allocation_strategy=strategy, n_optimization_iterations=0)
                first_fit.assert_not_called()

    def test_forced_reuse_failure_does_not_fall_back(self):
        for strategy in ("first-fit", "hierarchical-first-fit"):
            with self.subTest(strategy=strategy), patch.object(
                compiler_compilation, "allocate_scratch_first_fit", side_effect=machine.CompileError("out of space")
            ):
                with self.assertRaisesRegex(RuntimeError, f"{strategy} allocation failed") as raised:
                    compiler_compilation.compile_program(self.program, scratch_allocation_strategy=strategy, n_optimization_iterations=0)
                self.assertIsInstance(raised.exception.__cause__, machine.CompileError)


if __name__ == "__main__":
    unittest.main()
