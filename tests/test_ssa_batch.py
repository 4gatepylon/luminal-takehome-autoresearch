"""Batch conversion must detect drift without changing existing files."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ssa
from tests.test_ssa import source_with


class BatchConversionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.program = ssa.from_ssa(source_with("a = 1"))

    def write(self, format, stem, program=None, *, decorated=False):
        program = self.program if program is None else program
        path = self.root / format / f"{stem}.{format}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if format == "json":
            output = json.dumps(program, sort_keys=decorated, indent=4 if decorated else None)
        else:
            output = ssa.to_ssa(program)
            if decorated:
                output = "# preserved comment\n\n" + output.replace("a = 1", "  a   =   1  ")
        path.write_text(output, encoding="utf-8")
        return path

    def snapshot(self):
        return {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def test_creates_all_missing_files_in_both_directions(self):
        for direction, source, target in (("to-ssa", "json", "ssa"), ("to-json", "ssa", "json")):
            with self.subTest(direction=direction):
                for stem in ("first", "second"):
                    self.write(source, stem)
                    (self.root / target / f"{stem}.{target}").unlink(missing_ok=True)
                self.assertEqual(ssa.convert_all(direction, self.root), (2, 0))
                for path in (self.root / target).glob(f"*.{target}"):
                    parsed = json.loads(path.read_text()) if target == "json" else ssa.from_ssa(path.read_text())
                    self.assertEqual(parsed, self.program)

    def test_equivalent_files_are_untouched_even_with_clobber(self):
        self.write("json", "example", decorated=True)
        self.write("ssa", "example", decorated=True)
        before = self.snapshot()
        for direction in ("to-ssa", "to-json"):
            for clobber in (False, True):
                with self.subTest(direction=direction, clobber=clobber):
                    self.assertEqual(ssa.convert_all(direction, self.root, clobber=clobber), (0, 1))
                    self.assertEqual(self.snapshot(), before)

    def test_nested_groups_preserve_paths_in_both_directions(self):
        self.write("json", "first/example")
        changed = {**self.program, "name": "second"}
        self.write("json", "second/example", changed)
        self.assertEqual(ssa.convert_all("to-ssa", self.root), (2, 0))
        for group, expected in (("first", self.program), ("second", changed)):
            path = self.root / "ssa" / group / "example.ssa"
            self.assertEqual(ssa.from_ssa(path.read_text()), expected)
            (self.root / "json" / group / "example.json").unlink()
        self.assertEqual(ssa.convert_all("to-json", self.root), (2, 0))
        for group, expected in (("first", self.program), ("second", changed)):
            path = self.root / "json" / group / "example.json"
            self.assertEqual(json.loads(path.read_text()), expected)

    def test_conflicts_prevent_all_writes_and_clobber_resolves_them(self):
        for direction, source, target in (("to-ssa", "json", "ssa"), ("to-json", "ssa", "json")):
            with self.subTest(direction=direction):
                self.write(source, "a_missing")
                (self.root / target / f"a_missing.{target}").unlink(missing_ok=True)
                self.write(source, "b_conflict")
                changed = {**self.program, "name": "different"}
                conflict = self.write(target, "b_conflict", changed)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "out of sync") as caught:
                    ssa.convert_all(direction, self.root)
                self.assertIn(str(conflict), str(caught.exception))
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(ssa.convert_all(direction, self.root, clobber=True), (2, 0))
                self.assertEqual(ssa.convert_all(direction, self.root), (0, 2))

    def test_invalid_destination_requires_clobber(self):
        for direction, source, target in (("to-ssa", "json", "ssa"), ("to-json", "ssa", "json")):
            with self.subTest(direction=direction):
                self.write(source, "example")
                destination = self.write(target, "example")
                destination.write_text("invalid content")
                with self.assertRaisesRegex(ValueError, "out of sync"):
                    ssa.convert_all(direction, self.root)
                self.assertEqual(destination.read_text(), "invalid content")
                self.assertEqual(ssa.convert_all(direction, self.root, clobber=True), (1, 0))

    def test_invalid_source_prevents_all_writes_even_with_clobber(self):
        for direction, source in (("to-ssa", "json"), ("to-json", "ssa")):
            with self.subTest(direction=direction):
                self.write(source, "a_valid")
                self.write(source, "z_invalid").write_text("invalid content")
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    ssa.convert_all(direction, self.root, clobber=True)
                self.assertEqual(self.snapshot(), before)

    def test_cli_success_conflict_and_clobber(self):
        self.write("json", "example")
        with patch.object(ssa, "PROGRAM_DIR", self.root), redirect_stdout(io.StringIO()) as stdout:
            with redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(ssa.main(["to-ssa", "all"]), 0)
            self.assertIn("1 written", stderr.getvalue())
            self.write("ssa", "example", {**self.program, "name": "different"})
            with redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(ssa.main(["to-ssa", "all"]), 1)
            self.assertIn("out of sync", stderr.getvalue())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(ssa.main(["to-ssa", "all", "--clobber"]), 0)
            self.assertEqual(stdout.getvalue(), "")

    def test_empty_source_and_single_file_clobber_are_errors(self):
        with self.assertRaisesRegex(ValueError, "no .json files"):
            ssa.convert_all("to-ssa", self.root)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            ssa.main(["to-ssa", "example.json", "--clobber"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
