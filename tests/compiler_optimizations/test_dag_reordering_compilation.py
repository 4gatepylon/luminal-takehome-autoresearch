"""Test DAG scheduler selection, score fallback, original IDs, and allocator options."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from compiler import compile_program
from compiler import compilation as compiler_compilation
from compiler.custom_scheduling import SCHEDULER_NAME2ORDERINGS_FN
from compiler.custom_scheduling.dag_pressure_codex import dag_orderings
from compiler.reordering import reordered_program
from compiler.scheduling import schedule_operations
import machine


PROGRAM_DIR = Path(__file__).parents[2] / "programs" / "original_programs"
STRATEGY = "dag-pressure-codex"


def independent_chains():
    operations = []
    for index in range(3):
        operations.extend([
            {"op": "load", "dest": f"x{index}", "buffer": "data", "offset": index},
            {"op": "mul", "dest": f"square{index}", "args": [f"x{index}", f"x{index}"]},
            {"op": "store", "args": [f"square{index}"], "buffer": "out", "offset": index},
        ])
    return {
        "name": "independent_load_multiply_chains",
        "buffers": {"data": 3, "out": 3},
        "operations": [dict(operation, id=index) for index, operation in enumerate(operations)],
        "cases": [{"data": [3, 5, 7], "out": [0, 0, 0]}],
    }


class DagReorderingCompilationTests(unittest.TestCase):
    def assert_valid(self, program, compilation):
        machine.check_compilation(program, compilation)
        for case in program["cases"]:
            machine.check_case(program, compilation, case)

    def test_public_programs_preserve_results_and_do_not_regress_cycle_scratch_product(self):
        paths = sorted(PROGRAM_DIR.glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(program=path.name):
                program = machine.load_program(path)
                original = deepcopy(program)
                source = compile_program(program, scheduling_strategy="source")
                reordered = compile_program(program, scheduling_strategy=STRATEGY)
                self.assert_valid(program, reordered)
                self.assertLessEqual(
                    len(reordered["bundles"]) * machine.scratch_footprint(program, reordered),
                    len(source["bundles"]) * machine.scratch_footprint(program, source),
                )
                self.assertEqual(program, original)

    def test_dag_strategy_hides_independent_chain_stalls(self):
        program = independent_chains()
        source = compile_program(program, "disjoint", scheduling_strategy="source")
        reordered = compile_program(program, "disjoint", scheduling_strategy=STRATEGY)
        self.assert_valid(program, reordered)
        self.assertLess(len(reordered["bundles"]), len(source["bundles"]))
        self.assertEqual(
            machine.scratch_footprint(program, reordered),
            machine.scratch_footprint(program, source),
        )

    def test_registry_candidates_are_compiled_with_original_operation_ids(self):
        program = independent_chains()
        self.assertIs(SCHEDULER_NAME2ORDERINGS_FN[STRATEGY], dag_orderings)
        candidate = (0, 3, 6, 1, 4, 7, 2, 5, 8)
        generator = Mock(return_value=[candidate])
        with patch.dict(SCHEDULER_NAME2ORDERINGS_FN, {STRATEGY: generator}):
            reordered = compile_program(program, "disjoint", scheduling_strategy=STRATEGY)
        generator.assert_called_once_with(program)
        self.assert_valid(program, reordered)
        source = compile_program(program, "disjoint", scheduling_strategy="source")
        self.assertLess(len(reordered["bundles"]), len(source["bundles"]))

    def test_selection_keeps_slower_source_when_it_has_better_cycle_scratch_product(self):
        program = {
            "name": "vector_overlap_tradeoff",
            "buffers": {"data": 16, "out": 16},
            "operations": [
                {"id": 0, "op": "vload", "dest": "a", "buffer": "data", "offset": 0},
                {"id": 1, "op": "vstore", "args": ["a"], "buffer": "out", "offset": 0},
                {"id": 2, "op": "vload", "dest": "b", "buffer": "data", "offset": 8},
                {"id": 3, "op": "vstore", "args": ["b"], "buffer": "out", "offset": 8},
            ],
            "cases": [{"data": list(range(16)), "out": [0] * 16}],
        }
        source = compile_program(program, "first-fit", scheduling_strategy="source")
        candidate = (0, 2, 1, 3)
        faster = compile_program(reordered_program(program, candidate), "first-fit")
        self.assertLess(len(faster["bundles"]), len(source["bundles"]))
        source_product = len(source["bundles"]) * machine.scratch_footprint(program, source)
        self.assertGreater(
            len(faster["bundles"]) * machine.scratch_footprint(program, faster), source_product
        )
        with patch.dict(SCHEDULER_NAME2ORDERINGS_FN, {STRATEGY: lambda _: [candidate]}):
            chosen = compile_program(program, "first-fit", scheduling_strategy=STRATEGY)
        self.assertEqual(
            len(chosen["bundles"]) * machine.scratch_footprint(program, chosen), source_product
        )
        self.assert_valid(program, chosen)

    def test_source_strategy_preserves_default_and_positional_call_compatibility(self):
        program = independent_chains()
        default = compile_program(program, "first-fit", False)
        source = compile_program(program, "first-fit", False, scheduling_strategy="source")
        self.assertEqual(default, source)
        self.assertEqual(source["bundles"], schedule_operations(program))
        self.assert_valid(program, source)

    def test_forced_scratch_strategy_is_used_for_dag_candidates(self):
        program = independent_chains()
        for strategy in ("disjoint", "first-fit", "hierarchical-first-fit"):
            allocators = {
                name: Mock(wraps=allocator)
                for name, allocator in compiler_compilation.ALLOCATION_NAME2ALLOCATOR_FN.items()
            }
            with self.subTest(strategy=strategy), patch.dict(
                compiler_compilation.ALLOCATION_NAME2ALLOCATOR_FN, allocators
            ):
                compilation = compile_program(program, strategy, scheduling_strategy=STRATEGY)
                self.assert_valid(program, compilation)
                for name, allocator in allocators.items():
                    if name == strategy:
                        self.assertTrue(allocator.called)
                    else:
                        allocator.assert_not_called()

    def test_registry_rejects_invalid_operation_permutations(self):
        program = independent_chains()
        source_order = tuple(range(len(program["operations"])))
        invalid_orderings = (
            (), source_order[:-1], source_order + (0,),
            (0,) + source_order[:-1], source_order[:-1] + (len(source_order),),
            (False,) + source_order[1:], ("0",) + source_order[1:],
        )
        for ordering in invalid_orderings:
            with self.subTest(ordering=ordering), patch.dict(
                SCHEDULER_NAME2ORDERINGS_FN, {STRATEGY: Mock(return_value=[ordering])}
            ):
                with self.assertRaises(machine.CompileError):
                    compile_program(program, scheduling_strategy=STRATEGY)

    def test_registry_rejects_data_and_original_memory_dependency_reversals(self):
        memory_program = {
            "name": "overlapping_stores",
            "buffers": {"out": 1},
            "operations": [
                {"id": 0, "op": "const", "dest": "a", "value": 2},
                {"id": 1, "op": "const", "dest": "b", "value": 3},
                {"id": 2, "op": "store", "args": ["a"], "buffer": "out", "offset": 0},
                {"id": 3, "op": "store", "args": ["b"], "buffer": "out", "offset": 0},
            ],
            "cases": [{"out": [0]}],
        }
        for program, ordering in (
            (independent_chains(), (1, 0, 2, 3, 4, 5, 6, 7, 8)),
            (memory_program, (0, 1, 3, 2)),
        ):
            with self.subTest(program=program["name"]), patch.dict(
                SCHEDULER_NAME2ORDERINGS_FN, {STRATEGY: Mock(return_value=[ordering])}
            ):
                with self.assertRaises(machine.CompileError):
                    compile_program(program, scheduling_strategy=STRATEGY)

    def test_unknown_scheduler_is_rejected(self):
        with self.assertRaises(ValueError):
            compile_program(independent_chains(), scheduling_strategy="unknown")

    def test_failed_forced_allocation_skips_candidate_and_keeps_source(self):
        program = independent_chains()
        ordering = (0, 3, 6, 1, 4, 7, 2, 5, 8)
        for strategy in ("first-fit", "hierarchical-first-fit"):
            source = compile_program(program, strategy, scheduling_strategy="source")
            allocator = Mock(side_effect=[source["scratch"], machine.CompileError("no space")])
            with (
                self.subTest(strategy=strategy),
                patch.dict(SCHEDULER_NAME2ORDERINGS_FN, {STRATEGY: Mock(return_value=[ordering])}),
                patch.dict(compiler_compilation.ALLOCATION_NAME2ALLOCATOR_FN, {strategy: allocator}),
            ):
                compilation = compile_program(program, strategy, scheduling_strategy=STRATEGY)
                self.assertEqual(compilation, source)
                self.assertEqual(allocator.call_count, 2)
                self.assert_valid(program, compilation)

    def test_forced_allocator_can_fit_candidate_after_source_allocation_fails(self):
        program = independent_chains()
        ordering = (0, 3, 6, 1, 4, 7, 2, 5, 8)
        for strategy in ("first-fit", "hierarchical-first-fit"):
            real_allocator = compiler_compilation.ALLOCATION_NAME2ALLOCATOR_FN[strategy]

            def allocate(candidate_program, lifetimes):
                if candidate_program["operations"] == program["operations"]:
                    raise machine.CompileError("source does not fit")
                return real_allocator(candidate_program, lifetimes)

            allocator = Mock(side_effect=allocate)
            with (
                self.subTest(strategy=strategy),
                patch.dict(SCHEDULER_NAME2ORDERINGS_FN, {STRATEGY: Mock(return_value=[ordering])}),
                patch.dict(compiler_compilation.ALLOCATION_NAME2ALLOCATOR_FN, {strategy: allocator}),
            ):
                compilation = compile_program(program, strategy, scheduling_strategy=STRATEGY)
                self.assertEqual(allocator.call_count, 2)
                self.assert_valid(program, compilation)

    def test_all_failed_forced_allocations_preserve_source_failure(self):
        program = independent_chains()
        ordering = (0, 3, 6, 1, 4, 7, 2, 5, 8)
        for strategy in ("first-fit", "hierarchical-first-fit"):
            source_failure = machine.CompileError("source does not fit")
            candidate_failure = machine.CompileError("candidate does not fit")
            allocator = Mock(side_effect=[source_failure, candidate_failure])
            with (
                self.subTest(strategy=strategy),
                patch.dict(SCHEDULER_NAME2ORDERINGS_FN, {STRATEGY: Mock(return_value=[ordering])}),
                patch.dict(compiler_compilation.ALLOCATION_NAME2ALLOCATOR_FN, {strategy: allocator}),
            ):
                with self.assertRaisesRegex(RuntimeError, f"{strategy} allocation failed") as raised:
                    compile_program(program, strategy, scheduling_strategy=STRATEGY)
                self.assertEqual(allocator.call_count, 2)
                self.assertIs(raised.exception.__cause__, source_failure)


if __name__ == "__main__":
    unittest.main()
