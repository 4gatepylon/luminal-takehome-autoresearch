"""Examples of scheduled lifetimes and scratch allocation rules."""

import unittest
from pathlib import Path
from unittest.mock import patch

import compiler
import machine


class CompilerTests(unittest.TestCase):
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
                    "scratch": compiler.allocate_scratch(program, value_name2lifetime_incl),
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

    def test_allocation_order_and_reuse(self):
        # Each value is (name, width, write_cycle_incl, last_live_cycle_incl).
        examples = [
            ("time before width", [("z", 8, 4, 6), ("a", 1, 1, 6)], {"a": 0, "z": 8}, 256),
            ("width before name", [("a", 1, 4, 6), ("z", 8, 4, 6)], {"z": 0, "a": 8}, 256),
            ("name before source order", [("z", 1, 1, 2), ("a", 1, 1, 2)], {"a": 0, "z": 1}, 256),
            ("reuse after final read", [("input", 8, 4, 5), ("output", 1, 6, 6)], {"input": 0, "output": 0}, 256),
            ("no reuse on final read", [("input", 8, 4, 5), ("output", 1, 5, 5)], {"input": 0, "output": 8}, 256),
            ("simultaneous unused writes", [("a", 1, 3, 3), ("b", 1, 3, 3)], {"a": 0, "b": 1}, 256),
            (
                "scalars fill alignment holes below a later vector",
                [("vec1", 8, 1, 9), ("scalar1", 1, 2, 9), ("vec2", 8, 3, 9)]
                + [(f"scalar{index}", 1, 4, 9) for index in range(2, 9)],
                {"vec1": 0, "vec2": 16}
                | {f"scalar{index}": 7 + index for index in range(1, 9)},
                256,
            ),
        ]
        for name, values, expected_value_name2scratch_address, scratch_words in examples:
            with self.subTest(name=name), patch.object(machine, "SCRATCH_WORDS", scratch_words):
                program = {"operations": [
                    {"dest": value_name, "op": "vload" if width == 8 else "const"}
                    for value_name, width, _, _ in values
                ]}
                value_name2lifetime_incl = {
                    value_name: (write_cycle_incl, last_live_cycle_incl)
                    for value_name, _, write_cycle_incl, last_live_cycle_incl in values
                }
                self.assertEqual(
                    compiler.allocate_scratch(program, value_name2lifetime_incl),
                    expected_value_name2scratch_address,
                )

    def test_hierarchical_allocation(self):
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
                    compiler.allocate_hierarchical_scratch(program, value_name2lifetime_incl),
                    expected_value_name2scratch_address,
                )

    def test_compiler_selects_hierarchical_when_smaller_or_only_strategy_that_fits(self):
        program = {
            "name": "hierarchical", "buffers": {"data": 8, "out": 25},
            "operations": [
                {"id": 0, "op": "vload", "dest": "v", "buffer": "data", "offset": 0},
                {"id": 1, "op": "const", "dest": "a", "value": 7},
                {"id": 2, "op": "vload", "dest": "w", "buffer": "data", "offset": 0},
                {"id": 3, "op": "vstore", "args": ["w"], "buffer": "out", "offset": 0},
                {"id": 4, "op": "vstore", "args": ["v"], "buffer": "out", "offset": 8},
                {"id": 5, "op": "vload", "dest": "u", "buffer": "data", "offset": 0},
                {"id": 6, "op": "vstore", "args": ["u"], "buffer": "out", "offset": 16},
                {"id": 7, "op": "store", "args": ["a"], "buffer": "out", "offset": 24},
            ],
            "cases": [{"data": list(range(8)), "out": [0] * 25}],
        }
        bundles = compiler.schedule_operations(program)
        op_id2issue_cycle = compiler.find_issue_cycles(program, bundles)
        value_name2lifetime_incl = compiler.find_lifetimes(program, op_id2issue_cycle)
        self.assertEqual(compiler.allocate_scratch(program, value_name2lifetime_incl),
                         {"a": 0, "v": 8, "w": 16, "u": 8})
        self.assertEqual(compiler.allocate_unique_scratch(program),
                         {"v": 0, "w": 8, "u": 16, "a": 24})
        strategy_name2expected_scratch = {
            None: {"v": 0, "w": 8, "u": 0, "a": 16},
            "hierarchical": {"v": 0, "w": 8, "u": 0, "a": 16},
            "first-fit": {"a": 0, "v": 8, "w": 16, "u": 8},
            "disjoint": {"v": 0, "w": 8, "u": 16, "a": 24},
        }
        for scratch_words in (16, 17, 256):
            for strategy_name, expected_value_name2scratch_address in strategy_name2expected_scratch.items():
                with self.subTest(scratch_words=scratch_words, strategy=strategy_name), patch.object(machine, "SCRATCH_WORDS", scratch_words):
                    if scratch_words == 16 or (scratch_words == 17 and strategy_name in ("first-fit", "disjoint")):
                        with self.assertRaises(machine.CompileError):
                            compiler.compile_program(program, scratch_allocation_strategy=strategy_name)
                        continue
                    compilation = compiler.compile_program(program, scratch_allocation_strategy=strategy_name)
                    self.assertEqual(compilation["scratch"], expected_value_name2scratch_address)
                    machine.check_compilation(program, compilation)
                    machine.check_case(program, compilation, program["cases"][0])
        with patch.object(machine, "SCRATCH_WORDS", 16):
            with self.assertRaisesRegex(machine.CompileError, "no scratch space"):
                compiler.allocate_hierarchical_scratch(program, value_name2lifetime_incl)

    def test_forced_hierarchical_on_public_programs(self):
        with (
            patch.object(compiler, "allocate_scratch", side_effect=AssertionError("unexpected first-fit")),
            patch.object(compiler, "allocate_unique_scratch", side_effect=AssertionError("unexpected disjoint")),
        ):
            for path in sorted((Path(__file__).parents[1] / "programs").glob("*.json")):
                with self.subTest(program=path.name):
                    program = machine.load_program(path)
                    compilation = compiler.compile_program(program, scratch_allocation_strategy="hierarchical")
                    machine.check_compilation(program, compilation)
                    for case in program["cases"]:
                        machine.check_case(program, compilation, case)

    def test_compiler_chooses_unique_when_first_fit_fails_or_uses_more_space(self):
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
        bundles = compiler.schedule_operations(program)
        op_id2issue_cycle = compiler.find_issue_cycles(program, bundles)
        value_name2lifetime_incl = compiler.find_lifetimes(program, op_id2issue_cycle)
        for scratch_words in (17, 24):
            with self.subTest(scratch_words=scratch_words), patch.object(machine, "SCRATCH_WORDS", scratch_words):
                if scratch_words == 17:
                    with self.assertRaisesRegex(machine.CompileError, "no scratch space"):
                        compiler.allocate_scratch(program, value_name2lifetime_incl)
                else:
                    self.assertEqual(
                        compiler.allocate_scratch(program, value_name2lifetime_incl),
                        {"a": 0, "v": 8, "w": 16},
                    )
                compilation = compiler.compile_program(program)
                self.assertEqual(compilation["scratch"], {"v": 0, "w": 8, "a": 16})
                machine.check_compilation(program, compilation)
                machine.check_case(program, compilation, program["cases"][0])
        with patch.object(machine, "SCRATCH_WORDS", 16):
            with self.assertRaises(machine.CompileError):
                compiler.compile_program(program)

    def test_compiler_chooses_reuse_when_unique_fails_or_uses_more_space(self):
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
                compilation = compiler.compile_program(program)
                self.assertEqual(compilation["scratch"], {"a": 0, "b": 0})
                machine.check_compilation(program, compilation)
                machine.check_case(program, compilation, program["cases"][0])


if __name__ == "__main__":
    unittest.main()
