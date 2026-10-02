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
                self.assertEqual(ssa.to_ssa(parsed), ssa_path.read_text())
                compilation = compiler.compile_program(parsed)
                for case in parsed["cases"]:
                    machine.check_case(parsed, compilation, case)

    def test_readable_syntax_maps_to_expected_operations(self):
        program = ssa.from_ssa(source_with("\n".join([
            "load {buff[data][0]} into {a}", "b = 0x10", "x = a + b", "y = x | a",
            "store {y} into {buff[out][0]}",
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
            "load {buff[data][0]} into {a}", "b = -1", "vload {buff[data][0]} into {v}",
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
        source = source_with("a = 1\nstore {a} into {buff[out][0]}")
        commented = "\n# initial comment\n" + "\n  # comment\n\n".join(source.splitlines())
        self.assertEqual(ssa.from_ssa(commented), ssa.from_ssa(source))

    def test_braced_memory_operands_allow_arbitrary_whitespace(self):
        source = source_with("\n".join([
            "load {buff[data][0]} into {a}",
            "store {a} into {buff[out][0]}",
            "vload {buff[data][0]} into {v}",
            "vstore {v} into {buff[out][0]}",
        ]))
        expected = ssa.from_ssa(source)
        for whitespace in ("", " ", "    ", "\t  "):
            padded = source.replace("{buff[", "{" + whitespace + "buff" + whitespace + "[")
            padded = padded.replace("{a}", "{" + whitespace + "a" + whitespace + "}")
            padded = padded.replace("{v}", "{" + whitespace + "v" + whitespace + "}")
            padded = padded.replace("]}", "]" + whitespace + "}")
            padded = padded.replace("[data][0]", "[ data ]  [ 0 ]")
            padded = "\n \t\n".join(padded.splitlines()) + "\n \t\n"
            with self.subTest(whitespace=whitespace):
                self.assertEqual(ssa.from_ssa(padded), expected)

    def test_memory_operands_require_braces(self):
        for body in [
            "load buff[data][0] into a", "load {buff[data][0]} into a",
            "vload buff[data][0] into {v}",
            "a = 1\nstore a into {buff[out][0]}",
            "a = 1\nstore {a} into buff[out][0]",
            "a = 1\nv = splat(a)\nvstore v into {buff[out][0]}",
        ]:
            with self.subTest(body=body), self.assertRaises(machine.ProgramError):
                ssa.from_ssa(source_with(body))

    def test_inline_comments_are_rejected_in_every_section(self):
        source = source_with("a = 1\nstore {a} into {buff[out][0]}")
        for line in source.splitlines():
            with self.subTest(line=line):
                with self.assertRaises(machine.ProgramError):
                    ssa.from_ssa(source.replace(line, line + " # forbidden", 1))

    def test_scalar_and_vector_conditional_selection(self):
        program = ssa.from_ssa(source_with("\n".join([
            "a = 10", "b = 20", "zero = 0", "nonzero = 7",
            "x = a if {  nonzero  } else b", "y = a if {zero} else b",
            "vload {buff[data][0]} into {conditions}",
            "va = splat(a)", "vb = splat(b)",
            "result = va if {conditions} else vb",
            "vstore {result} into {buff[out][0]}",
        ])))
        self.assertEqual(program["operations"][4], {
            "id": 4, "op": "select", "dest": "x", "args": ["nonzero", "a", "b"],
        })
        self.assertEqual(program["operations"][5]["args"], ["zero", "a", "b"])
        self.assertEqual(program["operations"][9], {
            "id": 9, "op": "vselect", "dest": "result", "args": ["conditions", "va", "vb"],
        })
        program["cases"][0]["data"] = [0, 1, 7, 0, 4294967295, 0, 2, 0]
        compilation = compiler.compile_program(program)
        machine.check_case(program, compilation, program["cases"][0])
        self.assertEqual(machine.run_reference(program, program["cases"][0])["out"],
                         [20, 10, 10, 20, 10, 20, 10, 20])
        self.assertEqual(ssa.from_ssa(ssa.to_ssa(program)), program)

    def test_invalid_identifiers_are_rejected(self):
        for name in ['"quoted"', "bad-name", "bad name", "1value", "if", "else", "True", "class"]:
            with self.subTest(name=name):
                with self.assertRaises(machine.ProgramError):
                    ssa.from_ssa(source_with(f"{name} = 1"))
                program = ssa.from_ssa(source_with("a = 1"))
                program["operations"][0]["dest"] = name
                with self.assertRaisesRegex(machine.ProgramError, "invalid identifier"):
                    ssa.to_ssa(program)
                program = ssa.from_ssa(source_with("a = 1"))
                program["buffers"][name] = program["buffers"].pop("data")
                program["cases"][0][name] = program["cases"][0].pop("data")
                with self.assertRaisesRegex(machine.ProgramError, "invalid identifier"):
                    ssa.to_ssa(program)
                source = source_with("a = 1").replace('"data"', json.dumps(name))
                with self.assertRaisesRegex(machine.ProgramError, "invalid identifier"):
                    ssa.from_ssa(source)

    def test_valid_identifiers_and_descriptive_program_name(self):
        program = ssa.from_ssa(source_with("_value2 = 1\nResult_3 = _value2 + _value2"))
        program["name"] = 'descriptive name # with "quotes"'
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
            "vload {buff[data][0]} into {v}\nb = v < v",
            "load {buff[data][8]} into {a}", "a = 1 + 2",
            "a = 1\nv = splat(a)\nx = a if {v} else a",
            "a = 1\nx = a if {missing} else a",
            "a = 1\nx = a if a < a else a",
            "a = 1\nx = select(a, a, a)",
            "a = 1\nv = splat(a)\nx = vselect(v, v, v)",
            '"a" = 1', 'a = 1\nx = "a" + a',
            'load {buff[data][0]} into {"a"}',
            'a = 1\nstore {"a"} into {buff[out][0]}',
            'load {buff["data"][0]} into {a}',
        ]:
            with self.subTest(body=body), self.assertRaises(machine.ProgramError):
                ssa.from_ssa(source_with(body))


if __name__ == "__main__":
    unittest.main()
