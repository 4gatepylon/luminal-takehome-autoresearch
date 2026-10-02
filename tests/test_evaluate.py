"""Regression checks for filepath selection and the compiler/grader boundary."""

from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import evaluate
import machine
from tests.test_machine import micro_program


class DefaultCompilerTests(unittest.TestCase):
    def test_default_compiler_correctness_and_no_regression(self) -> None:
        diagnostics = StringIO()
        metrics = evaluate.eval(stream=diagnostics)
        self.assertIsNotNone(metrics, diagnostics.getvalue())
        for metric_name in ("cycle_speedup", "scratch_reduction", "combined_score"):
            with self.subTest(metric=metric_name):
                self.assertGreaterEqual(metrics[metric_name], 1.0)


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        output_dir = Path(".autoresearch-openevolve")
        output_dir.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=output_dir)
        self.addCleanup(self.temp_dir.cleanup)
        self.compiler_path = Path(self.temp_dir.name) / "candidate.py"

    def test_alternate_cli_and_all_public_apis(self) -> None:
        # No compile_program function: the contract is the JSON CLI alone.
        self.compiler_path.write_text(
            "import json\nimport sys\nimport machine\n"
            "json.dump(machine.serial_compile(machine.load_program(sys.argv[1])), sys.stdout)\n"
        )
        diagnostics = StringIO()
        self.assertTrue(evaluate.test(compiler_filepath=self.compiler_path, stream=diagnostics).wasSuccessful())
        expected = {"cycle_speedup": 1.0, "scratch_reduction": 1.0, "combined_score": 1.0}
        self.assertEqual(evaluate.score(compiler_filepath=self.compiler_path), expected)
        self.assertEqual(evaluate.eval(compiler_filepath=self.compiler_path, stream=diagnostics), expected)

    def test_candidate_cannot_replace_parent_validation(self) -> None:
        self.compiler_path.write_text(
            "import machine\nmachine.check_compilation = lambda *args: 1\n"
            "print('{\"scratch\": {}, \"bundles\": []}')\n"
        )
        with self.assertRaises(machine.CompileError):
            evaluate.score(compiler_filepath=self.compiler_path)

    def test_sandboxed_compiler_respects_both_expected_output_modes(self) -> None:
        self.compiler_path.write_text(
            "import json\nimport sys\nimport machine\n"
            "json.dump(machine.serial_compile(machine.load_program(sys.argv[1])), sys.stdout)\n"
        )
        path = self.compiler_path.with_name("program.json")
        for mode in ("agree_with_reference_compiler", "ignore_reference_compiler"):
            with self.subTest(mode=mode):
                program = micro_program()
                expectation = {"mode": mode, "buffers": {"out": [42]}}
                program["cases"].append({"inputs": {"out": [0]}, "expected": expectation})
                path.write_text(json.dumps(program))
                evaluate._compile_and_check(path, self.compiler_path)
                expectation["buffers"]["out"] = [43]
                path.write_text(json.dumps(program))
                with self.assertRaisesRegex(machine.CompileError, "explicit expected output"):
                    evaluate._compile_and_check(path, self.compiler_path)

    def test_failed_tests_prevent_scoring_and_preserve_diagnostics(self) -> None:
        self.compiler_path.write_text("raise RuntimeError('candidate failure detail')\n")
        diagnostics = StringIO()
        with patch("evaluate.score") as score:
            self.assertIsNone(evaluate.eval(compiler_filepath=self.compiler_path, stream=diagnostics))
        score.assert_not_called()
        self.assertIn("candidate failure detail", diagnostics.getvalue())

    def test_sandbox_blocks_writes_network_and_forks(self) -> None:
        forbidden_path = self.compiler_path.with_name("forbidden").resolve()
        attempts = [
            f"open({str(forbidden_path)!r}, 'w')",
            "socket.socket().connect(('127.0.0.1', 9))",
            "os.fork()",
        ]
        for attempt in attempts:
            with self.subTest(attempt=attempt):
                self.compiler_path.write_text(f"import os\nimport socket\n{attempt}\n")
                with self.assertRaisesRegex(ValueError, "Operation not permitted"):
                    evaluate.score(compiler_filepath=self.compiler_path)
        self.assertFalse(forbidden_path.exists())

    def test_invalid_json_and_timeout_are_evaluation_errors(self) -> None:
        self.compiler_path.write_text("print('not JSON')\n")
        with self.assertRaises(ValueError):
            evaluate.score(compiler_filepath=self.compiler_path)
        with patch("evaluate.run_in_sandbox", side_effect=subprocess.TimeoutExpired("candidate", 20)) as sandbox:
            with self.assertRaises(subprocess.TimeoutExpired):
                evaluate.score(compiler_filepath=self.compiler_path)
        self.assertEqual(sandbox.call_args.kwargs["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
