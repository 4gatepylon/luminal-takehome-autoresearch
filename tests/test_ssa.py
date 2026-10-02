"""SSA syntax, round-trip fidelity, and checked-in fixture parity."""

import json
from pathlib import Path
import unittest

import compiler
import machine
import ssa


PROGRAM_DIR = Path(__file__).parents[1] / "programs"


def source_with(body: str) -> str:
    return "\n".join([
        ssa.SECTIONS[0], 'name "example"', 'buffers {"data": 8, "out": 8}',
        ssa.SECTIONS[1], body, ssa.SECTIONS[2],
        '{"data": [1, 2, 3, 4, 5, 6, 7, 8], "out": [0, 0, 0, 0, 0, 0, 0, 0]}',
    ])


class SSATests(unittest.TestCase):
    def test_public_files_are_one_to_one_and_execute(self):
        json_paths = sorted((PROGRAM_DIR / "json").glob("*.json"))
        ssa_paths = sorted((PROGRAM_DIR / "ssa").glob("*.ssa"))
        self.assertEqual(len(json_paths), 8)
        self.assertEqual([p.stem for p in json_paths], [p.stem for p in ssa_paths])
        for json_path, ssa_path in zip(json_paths, ssa_paths):
            with self.subTest(program=json_path.stem):
                original = json.loads(json_path.read_text())
                parsed = ssa.from_ssa(ssa_path.read_text())
                self.assertEqual(parsed, original)
                self.assertEqual(ssa.from_ssa(ssa.to_ssa(original)), original)
                compilation = compiler.compile_program(parsed)
                for case in parsed["cases"]:
                    machine.check_case(parsed, compilation, case)

    def test_readable_syntax_maps_to_expected_operations(self):
        program = ssa.from_ssa(source_with("\n".join([
            "load buff[data][0] into a", "b = 0x10", "x = a + b", "y = x | a",
            "store y into buff[out][0]",
        ])))
        self.assertEqual(program["operations"], [
            {"id": 0, "op": "load", "dest": "a", "buffer": "data", "offset": 0},
            {"id": 1, "op": "const", "dest": "b", "value": 16},
            {"id": 2, "op": "add", "dest": "x", "args": ["a", "b"]},
            {"id": 3, "op": "or", "dest": "y", "args": ["x", "a"]},
            {"id": 4, "op": "store", "args": ["y"], "buffer": "out", "offset": 0},
        ])
        self.assertEqual(machine.run_reference(program, program["cases"][0])["out"][0], 17)

    def test_every_opcode_round_trips(self):
        program = ssa.from_ssa(source_with("\n".join([
            "load buff[data][0] into a", "b = -1", "vload buff[data][0] into v",
            "w = splat(b)",
        ])))
        for opcode, spec in machine.OP_SPECS.items():
            if opcode in {"load", "const", "vload", "splat"}:
                continue
            operation = {"id": len(program["operations"]), "op": opcode}
            operation["args"] = [
                ("a" if i % 2 == 0 else "b") if kind == "scalar"
                else ("v" if i % 2 == 0 else "w")
                for i, kind in enumerate(spec["args"])
            ]
            if spec["result"] is not None:
                operation["dest"] = "result_" + opcode
            else:
                operation.update(buffer="out", offset=0)
            program["operations"].append(operation)
        self.assertEqual({op["op"] for op in program["operations"]}, set(machine.OP_SPECS))
        self.assertEqual(ssa.from_ssa(ssa.to_ssa(program)), program)

    def test_full_line_comments_and_blank_lines(self):
        source = source_with("a = 1\nstore a into buff[out][0]")
        commented = "\n# initial comment\n" + "\n  # comment\n\n".join(source.splitlines())
        self.assertEqual(ssa.from_ssa(commented), ssa.from_ssa(source))

    def test_inline_comments_are_rejected_in_every_section(self):
        source = source_with("a = 1\nstore a into buff[out][0]")
        for line in source.splitlines():
            with self.subTest(line=line):
                with self.assertRaises(machine.ProgramError):
                    ssa.from_ssa(source.replace(line, line + " # forbidden", 1))

    def test_quoted_names_preserve_special_characters(self):
        program = ssa.from_ssa(source_with('"a # quoted" = -1\nstore "a # quoted" into buff[out][0]'))
        program["name"] = 'name # with "quotes"'
        program["buffers"]["data # with spaces"] = program["buffers"].pop("data")
        for case in program["cases"]:
            case["data # with spaces"] = case.pop("data")
        program["operations"].insert(0, {
            "op": "load", "dest": "loaded value", "buffer": "data # with spaces", "offset": 0,
        })
        for op_id, operation in enumerate(program["operations"]):
            operation["id"] = op_id
        self.assertEqual(ssa.from_ssa(ssa.to_ssa(program)), program)

    def test_sections_must_appear_exactly_once_in_order(self):
        source = source_with("a = 1")
        invalid = [
            source.replace(ssa.SECTIONS[0], ""),
            source.replace(ssa.SECTIONS[1], ssa.SECTIONS[2]),
            source + "\n" + ssa.SECTIONS[2],
            source.split(ssa.SECTIONS[2])[0],
        ]
        for text in invalid:
            with self.subTest(source=text), self.assertRaises(machine.ProgramError):
                ssa.from_ssa(text)

    def test_invalid_ssa_and_types_are_rejected(self):
        for body in [
            "a = missing + missing", "a = 1\na = 2",
            "a = 1\nv = splat(a)\nb = a + v",
            "vload buff[data][0] into v\nb = v < v",
            "load buff[data][8] into a", "a = 1 + 2",
        ]:
            with self.subTest(body=body), self.assertRaises(machine.ProgramError):
                ssa.from_ssa(source_with(body))


if __name__ == "__main__":
    unittest.main()
