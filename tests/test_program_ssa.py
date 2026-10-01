"""Codec contract tests: round trips, authoring, validation, and file handling."""

import json
import tempfile
import unittest
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import machine
from program_ssa import SECTIONS, SSAError, format_program, main, parse_program


def scalar_program() -> dict:
    return {
        "name": "example",
        "buffers": {"a": 1, "out": 1},
        "operations": [
            {"id": 0, "op": "load", "dest": "a0", "buffer": "a", "offset": 0},
            {"id": 1, "op": "const", "dest": "factor", "value": 3},
            {"id": 2, "op": "mul", "dest": "result", "args": ["a0", "factor"]},
            {"id": 3, "op": "store", "args": ["result"], "buffer": "out", "offset": 0},
        ],
        "cases": [{"a": [7], "out": [0]}],
    }


def all_opcodes_program() -> dict:
    operations = []
    for dest, value in (("a", -1), ("b", 2**65 + 3), ("condition", 1)):
        operations.append({"id": len(operations), "op": "const", "dest": dest, "value": value})
    for dest, value in (("va", "a"), ("vb", "b"), ("vc", "condition")):
        operations.append({"id": len(operations), "op": "splat", "dest": dest, "args": [value]})
    for opcode, spec in machine.OP_SPECS.items():
        if opcode in {"const", "splat"}:
            continue
        operation = {"id": len(operations), "op": opcode}
        if spec["result"]:
            operation["dest"] = f"result_{opcode}"
        if opcode in machine.MEMORY_OPS:
            operation.update(buffer="data", offset=8 if opcode.startswith("v") else 1)
        if spec["args"]:
            operands = ["condition", "a", "b"] if len(spec["args"]) == 3 else ["a", "b"]
            if spec["args"][0] == "vector":
                operands = ["vc", "va", "vb"] if len(spec["args"]) == 3 else ["va", "vb"]
            operation["args"] = operands[: len(spec["args"])]
        operations.append(operation)
    return {"name": "all_opcodes", "buffers": {"data": 16}, "operations": operations, "cases": [{"data": list(range(16))}]}


class RoundTripTests(unittest.TestCase):
    def assert_round_trip(self, program: dict) -> str:
        before = deepcopy(program)
        source = format_program(program)
        decoded = parse_program(source)
        self.assertEqual(decoded, program)
        self.assertEqual(program, before, "formatting must not mutate its input")
        self.assertEqual(format_program(decoded), source)
        for marker in SECTIONS:
            self.assertEqual(source.count(marker), 1)
        return source

    def test_every_existing_json_program_and_checked_in_ssa(self) -> None:
        paths = sorted(Path("programs/json").glob("*.json"))
        self.assertTrue(paths, "no existing programs were tested")
        self.assertEqual(
            {path.stem for path in paths},
            {path.stem for path in Path("programs/ssa").glob("*.ssa")},
        )
        for path in paths:
            with self.subTest(program=path):
                original = json.loads(path.read_text(encoding="utf-8"))
                source = self.assert_round_trip(original)
                ssa_path = Path("programs/ssa") / path.with_suffix(".ssa").name
                self.assertEqual(ssa_path.read_text(encoding="utf-8"), source)
                self.assertEqual(parse_program(ssa_path.read_text(encoding="utf-8")), original)

    def test_all_supported_opcodes(self) -> None:
        program = all_opcodes_program()
        self.assertEqual({op["op"] for op in program["operations"]}, set(machine.OP_SPECS))
        source = self.assert_round_trip(program)
        self.assertIn("va = ...a", source)
        self.assertIn("result_select = a if { condition } else b", source)
        self.assertIn("result_vselect = va if { vc } else vb", source)

    def test_extra_fields_empty_args_and_multiple_cases(self) -> None:
        program = scalar_program()
        program["description"] = {"nested": [True, None, 1.25, "a\nb"], "operations": "metadata"}
        program["operations"][0]["args"] = []
        program["operations"][0]["note"] = {"keep": [1, 2]}
        # Even otherwise meaningful field names can be unused metadata on other opcodes.
        program["operations"][1]["buffer"] = "not a memory reference"
        program["operations"][2]["value"] = 42
        program["cases"].append({"a": [-1], "out": [2**64]})
        self.assert_round_trip(program)

    def test_aliases_unicode_quotes_and_delimiters(self) -> None:
        program = scalar_program()
        buffer_name = 'bad "buffer"\n' + SECTIONS[2]
        value_name = "bad... {value}"
        program["name"] = "\n".join(SECTIONS) + ' "quote" \\ café'
        program["buffers"][buffer_name] = program["buffers"].pop("a")
        program["cases"][0][buffer_name] = program["cases"][0].pop("a")
        program["operations"][0].update(buffer=buffer_name, dest=value_name)
        program["operations"][2]["args"][0] = value_name
        program["notes"] = {SECTIONS[0]: list(SECTIONS)}
        source = self.assert_round_trip(program)
        self.assertIn("aliases:", source)
        self.assertIn(r"\u003d", source)

    def test_aliases_avoid_existing_names_and_keywords(self) -> None:
        for name in ("value_0", "if", "const", "buff", "hello world", "a.b", "a{b}", "a...b", "λ", "e\u0301"):
            with self.subTest(name=name):
                program = scalar_program()
                program["operations"][0]["dest"] = name
                program["operations"][2]["args"][0] = name
                self.assert_round_trip(program)
        program = scalar_program()
        program["operations"][0]["dest"] = "value_0"
        program["operations"][1]["dest"] = "not valid"
        program["operations"][2]["args"] = ["value_0", "not valid"]
        self.assertIn('"value_1":"not valid"', self.assert_round_trip(program))


class AuthoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.program = scalar_program()
        self.source = format_program(self.program)

    def test_canonical_readable_output(self) -> None:
        self.assertEqual(
            self.source,
            """lang: ssa-v1
name: "example"

================ BUFFERS ================
{"a":1}
{"out":1}

================ PROGRAM ================
a0 = buff[a][0]
factor = const(3)
result = a0 * factor
buff[out][0] = result

================ CASES ================
{"a":[7],"out":[0]}
""",
        )

    def test_program_newlines_are_whitespace(self) -> None:
        before, rest = self.source.split(SECTIONS[1])
        program, after = rest.split(SECTIONS[2])
        for edited in (" ".join(program.split()), program.replace(" ", "\n\t"), program.replace("const(3)", "const\n(\n3\n)")):
            with self.subTest(edited=edited):
                source = before + SECTIONS[1] + "\n" + edited + "\n" + SECTIONS[2] + after
                self.assertEqual(parse_program(source), self.program)

    def test_blank_lines_indented_comments_and_crlf(self) -> None:
        source = "\n  # introductory comment\n" + self.source.replace("\n", "\n\n  # comment\n")
        self.assertEqual(parse_program(source), self.program)
        self.assertEqual(parse_program(source.replace("\n", "\r\n")), self.program)

    def test_hash_in_json_string_is_data(self) -> None:
        self.program["name"] = "# not a comment"
        self.program["operations"][0]["note"] = "# preserved"
        self.assertEqual(parse_program(format_program(self.program)), self.program)

    def test_editing_changes_only_the_corresponding_json_field(self) -> None:
        for old, new, index, key, value in (
            ("const(3)", "const(9)", 1, "value", 9),
            ("a0 * factor", "factor * a0", 2, "args", ["factor", "a0"]),
            ("buff[a][0]", "buff[out][0]", 0, "buffer", "out"),
        ):
            with self.subTest(edit=new):
                expected = deepcopy(self.program)
                expected["operations"][index][key] = value
                self.assertEqual(parse_program(self.source.replace(old, new)), expected)

    def test_splat_and_scalar_vector_selection_semantics(self) -> None:
        source = """lang: ssa-v1
name: "selection"
================ BUFFERS ================
{"gates":8}
{"out":18}
================ PROGRAM ================
yes = const(7)
no = const(9)
nonzero = const(2)
zero = const(0)
vy = ...yes
vn = ...no
conditions = buff[gates][0:8]
selected = vy if { conditions } else vn
scalar_yes = yes if { nonzero } else no
scalar_no = yes if { zero } else no
buff[out][0:8] = vy
buff[out][8:16] = selected
buff[out][16] = scalar_yes
buff[out][17] = scalar_no
================ CASES ================
"""
        case = {"gates": [0, 1, 0, 2, 0, 0, 99, 0], "out": [0] * 18}
        program = parse_program(source + json.dumps(case) + "\n")
        actual = machine.run_reference(program, case)
        self.assertEqual(actual["out"], [7] * 8 + [9, 7, 9, 7, 9, 9, 7, 9] + [7, 9])


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = format_program(scalar_program())

    def test_invalid_program_statements(self) -> None:
        edits = (
            ("factor = const(3)", "a0 = const(3)", "duplicate definition"),
            ("a0 * factor", "a0 * later", "undefined value"),
            ("a0 * factor", "a0 + factor * a0", "expected"),
            ("a0 * factor", "3 * a0", "identifier"),
            ("a0 * factor", "a0 if { factor } else 3", "identifier"),
            ("a0 * factor", "3 if { factor } else a0", "identifier"),
            ("a0 * factor", "a0 if { 1 } else factor", "identifier"),
            ("a0 * factor", "a0 if factor else a0", "expected"),
            ("const(3)", "const(3) # inline", "identifier"),
            ("const(3)", "const(1.5)", "expected"),
            ("const(3)", 'const(3) @ {"value":4}', "cannot override"),
            ("const(3)", "const(3) @ []", "JSON object"),
            ("const(3)", 'const(3) @ {"args":["a0"]}', "expects 0 arguments"),
            ("buff[a][0]", "buff[missing][0]", "unknown buffer"),
            ("buff[a][0]", "buff[a][-1]", "outside buffer"),
            ("buff[a][0]", "buff[a][1]", "outside buffer"),
            ("buff[a][0]", "buff[a][0:7]", "exactly 8"),
            ("result =", "a...b =", "expected"),
            ("result =", "a{b} =", "expected"),
            ("result =", "two words =", "expected"),
            ("result =", "if =", "identifier"),
        )
        for old, new, error in edits:
            with self.subTest(statement=new), self.assertRaisesRegex(SSAError, "line [0-9]+:.*" + error):
                parse_program(self.source.replace(old, new))

    def test_type_mismatches_and_unsupported_vector_comparisons(self) -> None:
        source = format_program(all_opcodes_program())
        for old, new in (
            ("va = ...a", "va = ...va"),
            ("vb = ...b", "vb = ...va"),
            ("result_add = a + b", "result_add = a + vb"),
            ("result_vadd = va + vb", "result_vadd = va == vb"),
            ("result_vadd = va + vb", "result_vadd = va < vb"),
            ("a if { condition } else b", "va if { condition } else b"),
            ("va if { vc } else vb", "va if { vc } else b"),
            ("buff[data][8:16] = va", "buff[data][8:16] = a"),
            ("buff[data][1] = a", "buff[data][1] = va"),
        ):
            with self.subTest(statement=new):
                self.assertIn(old, source)
                with self.assertRaises(SSAError):
                    parse_program(source.replace(old, new))

    def test_sections_headers_and_jsonl(self) -> None:
        edits = (
            ("lang: ssa-v1", "lang: ssa-v2"),
            ('name: "example"', "name: null"),
            ('name: "example"', 'name: "example"\nname: "again"'),
            (SECTIONS[0], SECTIONS[1]),
            (SECTIONS[2], ""),
            (SECTIONS[2], SECTIONS[2] + "\n" + SECTIONS[2]),
            ('{"a":1}', '{"a":1}\n{"a":1}'),
            ('{"a":1}', '{"a":1,"a":2}'),
            ('{"a":1}', '{"a":1,"b":1}'),
            ('{"a":1}', '{"a":0}'),
            ('{"a":1}', '{"a":true}'),
            ('{"a":1}', '{"bad name":1}'),
            ('{"a":1}', '{"a":\n1}'),
            ('{"a":[7],"out":[0]}', '{"a":[7],"out":[0]} # inline'),
            ('{"a":[7],"out":[0]}', '{"a":[7],\n"out":[0]}'),
            ('{"a":[7],"out":[0]}', '{"a":[7],"out":[0]} {}'),
            ('{"a":[7],"out":[0]}', '{"a":[NaN],"out":[0]}'),
            ('{"a":[7],"out":[0]}', '{"a":[7,8],"out":[0]}'),
            ('{"a":[7],"out":[0]}', '{"a":[7]}'),
            ('{"a":[7],"out":[0]}', "[]"),
            ('{"a":[7],"out":[0]}', ""),
        )
        for old, new in edits:
            with self.subTest(replacement=new), self.assertRaises(SSAError):
                parse_program(self.source.replace(old, new))

    def test_invalid_metadata_and_aliases(self) -> None:
        for header in (
            'metadata: {"cases":[]}',
            "metadata: []",
            "aliases: []",
            'aliases: {"unknown":{}}',
            'aliases: {"values":{"absent":"original"}}',
            'aliases: {"values":{"a0":"factor"}}',
            'aliases: {"values":{"a0":null}}',
            'aliases: {"buffers":{"a":"out"}}',
            f'metadata: {{"note":"{SECTIONS[0]}"}}',
        ):
            with self.subTest(header=header), self.assertRaises(SSAError):
                parse_program(self.source.replace("lang: ssa-v1", "lang: ssa-v1\n" + header))

    def test_store_cannot_acquire_a_destination_through_metadata(self) -> None:
        for dest in ('"extra"', "[]", "{}"):
            source = self.source.replace("buff[out][0] = result", 'buff[out][0] = result @ {"dest":' + dest + "}")
            with self.subTest(dest=dest), self.assertRaisesRegex(SSAError, "cannot have a dest"):
                parse_program(source)

    def test_error_line_counts_include_comments_and_blank_lines(self) -> None:
        source = self.source.replace("result = a0 * factor", "# comment\n\nresult = a0 * missing")
        expected_line = next(index for index, line in enumerate(source.splitlines(), 1) if "missing" in line)
        with self.assertRaisesRegex(SSAError, f"line {expected_line}: undefined value 'missing'"):
            parse_program(source)


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        Path(".context").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=".context")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.json_path = self.directory / "example.json"
        self.ssa_path = self.directory / "example.ssa"
        self.json_path.write_text(json.dumps(scalar_program()), encoding="utf-8")

    def test_file_round_trip(self) -> None:
        self.assertEqual(main(["json2ssa", str(self.json_path), "-o", str(self.ssa_path)]), 0)
        restored = self.directory / "restored.json"
        self.assertEqual(main(["ssa2json", str(self.ssa_path), "-o", str(restored)]), 0)
        self.assertEqual(json.loads(restored.read_text()), scalar_program())

    def test_stdout_and_error_exit(self) -> None:
        output = StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(main(["to-ssa", str(self.json_path)]), 0)
        self.assertEqual(parse_program(output.getvalue()), scalar_program())
        self.ssa_path.write_text(output.getvalue(), encoding="utf-8")
        restored = StringIO()
        with patch("sys.stdout", restored):
            self.assertEqual(main(["to-json", str(self.ssa_path)]), 0)
        self.assertEqual(json.loads(restored.getvalue()), scalar_program())
        self.ssa_path.write_text("invalid", encoding="utf-8")
        error = StringIO()
        output = StringIO()
        with patch("sys.stderr", error), patch("sys.stdout", output):
            self.assertEqual(main(["to-json", str(self.ssa_path)]), 1)
        self.assertIn(str(self.ssa_path), error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())
        self.assertEqual(output.getvalue(), "")

    def test_failed_conversion_preserves_existing_output(self) -> None:
        self.json_path.write_text("invalid", encoding="utf-8")
        self.ssa_path.write_text("keep me", encoding="utf-8")
        with patch("sys.stderr", StringIO()):
            self.assertEqual(main(["to-ssa", str(self.json_path), "-o", str(self.ssa_path)]), 1)
        self.assertEqual(self.ssa_path.read_text(), "keep me")

    def test_ssa_extensions_are_enforced(self) -> None:
        for arguments in (
            ["to-ssa", str(self.json_path), "-o", str(self.directory / "wrong.txt")],
            ["to-json", str(self.json_path)],
        ):
            with self.subTest(arguments=arguments), patch("sys.stderr", StringIO()) as error:
                self.assertEqual(main(arguments), 1)
                self.assertIn(".ssa", error.getvalue())


if __name__ == "__main__":
    unittest.main()
