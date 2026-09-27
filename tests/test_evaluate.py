"""Check compiler file selection and reloading through the public API."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import evaluate
from compiler_loader import load_compiler


class CompilerPathTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.compiler_path = Path(directory.name) / "candidate.py"
        self.compiler_path.write_text(
            "import machine\n"
            "def compile_program(program: dict) -> dict:\n"
            "    result = machine.serial_compile(program)\n"
            "    result['bundles'].append({})\n"
            "    return result\n"
        )

    def test_default_compiler(self):
        self.assertTrue(evaluate.test(stream=io.StringIO()).wasSuccessful())
        self.assertEqual(evaluate.score()["combined_score"], 1.0)

    def test_custom_compiler_for_all_functions(self):
        self.assertTrue(evaluate.test(self.compiler_path, stream=io.StringIO()).wasSuccessful())
        metrics = evaluate.score(str(self.compiler_path))
        self.assertLess(metrics["combined_score"], 1.0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(evaluate.eval(compiler_path=self.compiler_path), metrics)

    def test_reload_and_stop_scoring_after_failure(self):
        self.assertTrue(evaluate.test(self.compiler_path, stream=io.StringIO()).wasSuccessful())
        self.compiler_path.write_text("def compile_program(program: dict) -> dict:\n    return {}\n")
        self.assertFalse(evaluate.test(self.compiler_path, stream=io.StringIO()).wasSuccessful())
        with redirect_stderr(io.StringIO()), patch("evaluate.score") as score:
            self.assertIsNone(evaluate.eval(self.compiler_path))
            score.assert_not_called()

    def test_missing_entry_point(self):
        self.compiler_path.write_text("compile_program = None\n")
        with self.assertRaisesRegex(TypeError, "must define a callable compile_program"):
            load_compiler(self.compiler_path)
