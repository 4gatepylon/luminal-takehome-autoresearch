"""Luminal Compiler Take Home — Machine contract tests for compiler engineering."""

from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import patch

import machine


def micro_program() -> dict:
    return {
        "name": "micro",
        "buffers": {"out": 1},
        "operations": [
            {"id": 0, "op": "const", "dest": "a", "value": 6},
            {"id": 1, "op": "const", "dest": "b", "value": 7},
            {"id": 2, "op": "mul", "dest": "product", "args": ["a", "b"]},
            {
                "id": 3,
                "op": "store",
                "args": ["product"],
                "buffer": "out",
                "offset": 0,
            },
        ],
        "cases": [{"out": [0]}],
    }


class MachineTests(unittest.TestCase):
    def test_serial_compiler_executes_correctly(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        machine.check_case(program, compilation, program["cases"][0])
        self.assertEqual(
            machine.run_compilation(program, compilation, program["cases"][0])["out"],
            [42],
        )

    def test_rejects_consumer_before_result_latency(self):
        program = micro_program()
        compilation = {
            "scratch": {"a": 0, "b": 1, "product": 2},
            "bundles": [
                {"load": [0, 1], "scalar": [2]},
                {},
                {"store": [3]},
            ],
        }
        with self.assertRaisesRegex(machine.CompileError, "produces it in cycle"):
            machine.check_compilation(program, compilation)

    def test_rejects_engine_capacity_overflow(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        compilation["bundles"] = [
            {"load": [0, 1]},
            {"scalar": [2, 2, 2]},
            {},
            {"store": [3]},
        ]
        with self.assertRaisesRegex(machine.CompileError, "limit is 2"):
            machine.check_compilation(program, compilation)

    def test_rejects_overlapping_scratch_allocations(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        compilation["scratch"]["b"] = compilation["scratch"]["a"]
        with self.assertRaisesRegex(machine.CompileError, "overlap"):
            machine.check_compilation(program, compilation)

    def test_memory_predecessor_only_for_overlapping_range(self):
        program = {
            "name": "memory",
            "buffers": {"data": 16},
            "operations": [
                {"id": 0, "op": "vload", "dest": "first", "buffer": "data", "offset": 0},
                {"id": 1, "op": "vstore", "args": ["first"], "buffer": "data", "offset": 8},
                {"id": 2, "op": "vload", "dest": "second", "buffer": "data", "offset": 8},
            ],
            "cases": [{"data": list(range(16))}],
        }
        machine.validate_program(program)
        self.assertEqual(machine.memory_predecessors(program, 1), [])
        self.assertEqual(machine.memory_predecessors(program, 2), [1])

    def test_vector_allocation_requires_alignment(self):
        program = {
            "name": "vector",
            "buffers": {"data": 8},
            "operations": [
                {"id": 0, "op": "vload", "dest": "value", "buffer": "data", "offset": 0}
            ],
            "cases": [{"data": list(range(8))}],
        }
        compilation = {"scratch": {"value": 1}, "bundles": [{"load": [0]}]}
        with self.assertRaisesRegex(machine.CompileError, "aligned"):
            machine.check_compilation(program, compilation)


class ExpectedOutputTests(unittest.TestCase):
    def setUp(self):
        self.program = micro_program()
        self.compilation = machine.serial_compile(self.program)

    def case(self, mode, output=42):
        return {"inputs": {"out": [0]}, "expected": {"mode": mode, "buffers": {"out": [output]}}}

    def test_cases_without_expected_use_reference(self):
        for case in ({"out": [0]}, {"inputs": {"out": [0]}}):
            with self.subTest(case=case), patch("machine.run_reference", wraps=machine.run_reference) as reference:
                machine.check_case(self.program, self.compilation, case)
                reference.assert_called_once_with(self.program, case)
            with patch("machine.run_reference", return_value={"out": [43]}):
                with self.assertRaisesRegex(machine.CompileError, "reference output"):
                    machine.check_case(self.program, self.compilation, case)

    def test_agree_with_reference_compiler_requires_all_three_outputs_to_match(self):
        # Exercise each possible disagreement, including both executions agreeing
        # with each other but not with the hand-authored answer.
        for expected, reference, actual in ((42, 42, 42), (43, 42, 42), (42, 43, 42), (42, 42, 43)):
            case = self.case("agree_with_reference_compiler", expected)
            with self.subTest(expected=expected, reference=reference, actual=actual):
                with patch("machine.run_reference", return_value={"out": [reference]}) as run_reference:
                    with patch("machine.run_compilation", return_value={"out": [actual]}):
                        if expected == reference == actual:
                            machine.check_case(self.program, self.compilation, case)
                        else:
                            message = "reference output disagrees" if expected != reference else "incorrect final memory"
                            with self.assertRaisesRegex(machine.CompileError, message + ".*out"):
                                machine.check_case(self.program, self.compilation, case)
                    run_reference.assert_called_once_with(self.program, case)

    def test_ignore_reference_compiler_never_runs_reference_and_still_rejects_wrong_output(self):
        with patch("machine.run_reference", side_effect=AssertionError("must not run reference")):
            machine.check_case(self.program, self.compilation, self.case("ignore_reference_compiler"))
            with self.assertRaisesRegex(machine.CompileError, "out.*explicit expected output"):
                machine.check_case(self.program, self.compilation, self.case("ignore_reference_compiler", 43))

    def test_mixed_modes_do_not_mutate_cases(self):
        self.program["cases"] += [
            {"inputs": {"out": [99]}}, self.case("agree_with_reference_compiler"), self.case("ignore_reference_compiler"),
        ]
        before = deepcopy(self.program)
        for case in self.program["cases"]:
            machine.check_case(self.program, self.compilation, case)
        self.assertEqual(self.program, before)

    def test_words_wrap_and_omitted_read_only_buffers_remain_checked(self):
        self.program["buffers"]["untouched"] = 1
        self.program["cases"] = [{"out": [0], "untouched": [-1]}]
        for mode in ("agree_with_reference_compiler", "ignore_reference_compiler"):
            case = self.case(mode, 2**32 + 42)
            case["inputs"]["untouched"] = [-1]
            with self.subTest(mode=mode):
                machine.check_case(self.program, self.compilation, case)
                with patch("machine.run_compilation", return_value={"out": [42], "untouched": [0]}):
                    with self.assertRaisesRegex(machine.CompileError, "untouched"):
                        machine.check_case(self.program, self.compilation, case)
                case["expected"]["buffers"]["untouched"] = [2**32 - 1]
                machine.check_case(self.program, self.compilation, case)

    def test_partial_writes_require_complete_expected_buffer(self):
        self.program["buffers"]["out"] = 2
        self.program["cases"] = [{"out": [0, 7]}]
        case = self.case("ignore_reference_compiler")
        case["inputs"]["out"] = [0, 7]
        with self.assertRaisesRegex(machine.ProgramError, "expected.*2 words"):
            machine.check_case(self.program, self.compilation, case)
        case["expected"]["buffers"]["out"] = [42, 7]
        machine.check_case(self.program, self.compilation, case)

    def test_neither_mode_bypasses_schedule_validation(self):
        for mode in ("agree_with_reference_compiler", "ignore_reference_compiler"):
            with self.subTest(mode=mode), self.assertRaises(machine.CompileError):
                machine.check_case(self.program, {"scratch": {}, "bundles": []}, self.case(mode))

    def test_invalid_expected_schema_is_rejected(self):
        invalid = [None, [], {}, {"buffers": {"out": [42]}}, {"mode": "ignore_reference_compiler"}]
        for mode in (None, True, [], {}, "unknown"):
            invalid.append({"mode": mode, "buffers": {"out": [42]}})
        for buffers in (None, [], {}, {"out": []}, {"out": [True]}, {"out": [1.5]}, {"out": ["42"]},
                        {"out": [42], "unknown": [0]}):
            invalid.append({"mode": "ignore_reference_compiler", "buffers": buffers})
        invalid.append({"mode": "ignore_reference_compiler", "buffers": {"out": [42]}, "extra": True})
        for expected in invalid:
            case = {"inputs": {"out": [0]}, "expected": expected}
            with self.subTest(expected=expected), self.assertRaisesRegex(machine.ProgramError, "case 0 expected"):
                machine.validate_case(self.program, case, 0)

    def test_invalid_input_wrappers_are_rejected(self):
        for case in ({"inputs": None}, {"inputs": []}, {"inputs": {}}, {"expected": {}},
                     {"inputs": {"out": [0]}, "expectd": {}}):
            with self.subTest(case=case), self.assertRaisesRegex(machine.ProgramError, "case 0"):
                machine.validate_case(self.program, case, 0)

    def test_inputs_and_expected_remain_legal_buffer_names(self):
        self.program["buffers"].update(inputs=1, expected=1)
        memory = {"out": [0], "inputs": [3], "expected": [4]}
        case = self.case("ignore_reference_compiler")
        case["inputs"] = memory
        self.program["cases"] = [memory, case]
        for case in self.program["cases"]:
            machine.check_case(self.program, self.compilation, case)


class ScratchReuseTests(unittest.TestCase):
    def test_in_place_result_after_final_read(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        compilation['scratch']['product'] = compilation['scratch']['a']
        machine.check_case(program, compilation, program['cases'][0])
        self.assertEqual(machine.scratch_footprint(program, compilation), 2)

    def test_write_on_final_read_cycle_is_rejected(self):
        program = micro_program()
        program['operations'].insert(2, {'id': 2, 'op': 'const', 'dest': 'unused', 'value': 9})
        for i, op in enumerate(program['operations']):
            op['id'] = i
        compilation = {
            'scratch': {'a': 0, 'b': 1, 'unused': 0, 'product': 2},
            'bundles': [{'load': [0, 1]}, {'load': [2]}, {'scalar': [3]}, {}, {'store': [4]}],
        }
        with self.assertRaisesRegex(machine.CompileError, 'overlap while live'):
            machine.check_compilation(program, compilation)

    def test_pending_unused_write_clobbers_live_value(self):
        program = {
            'name': 'pending', 'buffers': {'data': 1, 'out': 1},
            'operations': [
                {'id': 0, 'op': 'load', 'dest': 'unused', 'buffer': 'data', 'offset': 0},
                {'id': 1, 'op': 'const', 'dest': 'a', 'value': 7},
                {'id': 2, 'op': 'store', 'args': ['a'], 'buffer': 'out', 'offset': 0},
            ], 'cases': [{'data': [9], 'out': [0]}],
        }
        compilation = {'scratch': {'unused': 0, 'a': 0},
                       'bundles': [{'load': [0]}, {'load': [1]}, {}, {}, {'store': [2]}]}
        with self.assertRaisesRegex(machine.CompileError, 'overlap while live'):
            machine.check_compilation(program, compilation)

    def test_partial_scalar_vector_reuse(self):
        program = {
            'name': 'partial', 'buffers': {'data': 8, 'out': 8},
            'operations': [
                {'id': 0, 'op': 'vload', 'dest': 'v', 'buffer': 'data', 'offset': 0},
                {'id': 1, 'op': 'vstore', 'args': ['v'], 'buffer': 'out', 'offset': 0},
                {'id': 2, 'op': 'const', 'dest': 's', 'value': 3},
                {'id': 3, 'op': 'store', 'args': ['s'], 'buffer': 'out', 'offset': 0},
            ], 'cases': [{'data': list(range(8)), 'out': [0] * 8}],
        }
        compilation = machine.serial_compile(program)
        compilation['scratch']['s'] = 3
        machine.check_case(program, compilation, program['cases'][0])
        self.assertEqual(machine.scratch_footprint(program, compilation), 8)
        compilation['bundles'] = [{'load': [0]}, {}, {}, {'load': [2]}, {'store': [1]}, {'store': [3]}]
        with self.assertRaisesRegex(machine.CompileError, 'overlap while live'):
            machine.check_compilation(program, compilation)


if __name__ == "__main__":
    unittest.main()
