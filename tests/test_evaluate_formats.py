"""Evaluation must reject missing, malformed, or stale SSA before compilation."""

import tempfile
import unittest
from copy import deepcopy
from io import StringIO
from pathlib import Path
from shutil import copy2
from unittest.mock import patch

import evaluate
import machine
from program_ssa import format_program


class EvaluationFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        Path(".context").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=".context")
        self.addCleanup(temporary.cleanup)
        self.program_dir = Path(temporary.name) / "json"
        self.ssa_dir = Path(temporary.name) / "ssa"
        self.program_dir.mkdir()
        self.ssa_dir.mkdir()
        for source in sorted(Path("programs/json").glob("*.json")):
            copy2(source, self.program_dir / source.name)
            ssa_name = source.with_suffix(".ssa").name
            copy2(Path("programs/ssa") / ssa_name, self.ssa_dir / ssa_name)

    def assert_rejected_before_compilation(self, filename: str, message: str) -> None:
        with patch("evaluate.PROGRAM_DIR", self.program_dir), patch("evaluate.run_in_sandbox") as compiler:
            with self.assertRaisesRegex(ValueError, message) as error:
                evaluate.score(program_dir=self.program_dir)
            self.assertIn(filename, str(error.exception))
            diagnostics = StringIO()
            self.assertFalse(evaluate.test(stream=diagnostics).wasSuccessful())
            self.assertIn(filename, diagnostics.getvalue())
            self.assertIn(message, diagnostics.getvalue())
            diagnostics = StringIO()
            with patch("evaluate.score") as score:
                self.assertIsNone(evaluate.eval(stream=diagnostics))
            score.assert_not_called()
            compiler.assert_not_called()

    def test_every_repository_program_has_an_exact_ssa_equivalent(self) -> None:
        evaluate._validate_ssa_equivalents(sorted(Path("programs/json").glob("*.json")))

    def test_missing_ssa_blocks_all_entry_points_before_compilation(self) -> None:
        # Removing the last file verifies that the whole inventory is checked first.
        path = max(self.ssa_dir.glob("*.ssa"))
        path.unlink()
        self.assert_rejected_before_compilation(path.name, "cannot validate SSA equivalent")

    def test_malformed_ssa_blocks_all_entry_points_before_compilation(self) -> None:
        path = self.ssa_dir / "01_scalar_pipeline.ssa"
        path.write_text("invalid SSA", encoding="utf-8")
        self.assert_rejected_before_compilation(path.name, "cannot validate SSA equivalent")

    def test_exact_match_includes_names_operations_buffers_cases_and_metadata(self) -> None:
        json_path = self.program_dir / "01_scalar_pipeline.json"
        original = machine.load_program(json_path)
        for field in ("name", "operations", "buffers", "cases", "metadata"):
            with self.subTest(field=field):
                changed = deepcopy(original)
                if field == "name":
                    changed["name"] += "_edited"
                elif field == "operations":
                    operation = next(op for op in changed["operations"] if op["op"] == "const")
                    operation["value"] += 1
                elif field == "buffers":
                    buffer = next(iter(changed["buffers"]))
                    changed["buffers"][buffer] += 1
                    for case in changed["cases"]:
                        case[buffer].append(0)
                elif field == "cases":
                    next(iter(changed["cases"][0].values()))[0] += 1
                else:
                    changed["note"] = "extra field"
                ssa_path = self.ssa_dir / json_path.with_suffix(".ssa").name
                ssa_path.write_text(format_program(changed), encoding="utf-8")
                self.assert_rejected_before_compilation(ssa_path.name, "does not exactly match")

    def test_expected_compiler_failures_cannot_hide_ssa_mismatches(self) -> None:
        filename = min(evaluate.EXPECTED_FAILURE_PROGRAM_FILENAMES)
        json_path = self.program_dir / filename
        program = machine.load_program(json_path)
        program["name"] += "_edited"
        ssa_path = self.ssa_dir / json_path.with_suffix(".ssa").name
        ssa_path.write_text(format_program(program), encoding="utf-8")
        self.assert_rejected_before_compilation(ssa_path.name, "does not exactly match")

    def test_comments_and_layout_do_not_change_program_equality(self) -> None:
        path = self.ssa_dir / "01_scalar_pipeline.ssa"
        source = path.read_text(encoding="utf-8")
        path.write_text("# handwritten comment\n\n" + source, encoding="utf-8")
        evaluate._validate_ssa_equivalents(sorted(self.program_dir.glob("*.json")))


if __name__ == "__main__":
    unittest.main()
