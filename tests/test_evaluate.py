"""Regression checks for filepath selection and the compiler/grader boundary."""

from contextlib import redirect_stdout
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


class ScoreReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.program_dir = Path(self.temp_dir.name)
        for name in ("01_first", "08_second", "09_third"):
            program = micro_program()
            program["name"] = name
            (self.program_dir / f"{name}.json").write_text(json.dumps(program))
        self.compilation = machine.serial_compile(micro_program())
        self.valid = subprocess.CompletedProcess([], 0, json.dumps(self.compilation), "")

    def test_report_continues_after_compiler_errors_without_tracebacks(self) -> None:
        failures = (
            subprocess.CompletedProcess([], 1, "", "Traceback: compiler failure detail"),
            subprocess.CompletedProcess([], 0, "not JSON", ""),
            subprocess.CompletedProcess([], 0, '{"scratch": {}, "bundles": []}', ""),
            subprocess.TimeoutExpired("candidate", 20),
        )
        for failure in failures:
            with self.subTest(failure=failure):
                output = StringIO()
                with patch("evaluate.run_in_sandbox", side_effect=[self.valid, failure, self.valid]) as sandbox, redirect_stdout(output):
                    metrics = evaluate.score(program_dir=self.program_dir, verbose=True, continue_on_error=True)
                self.assertIsNone(metrics)
                self.assertEqual(sandbox.call_count, 3)
                report = output.getvalue()
                self.assertRegex(report, r"first\s+\d+")
                self.assertRegex(report, r"second\s+ERROR\n")
                self.assertRegex(report, r"third\s+\d+")
                self.assertNotIn("Traceback", report)
                self.assertNotIn("compiler failure detail", report)
                self.assertIn("all programs (2/3 successful):", report)
                self.assertIn("original programs 1-8 (1/2 successful):", report)
                self.assertEqual(report.count("combined score: 1.000x"), 2)
                self.assertIn("1 program(s) failed; scores exclude failed programs.", report)

    def test_report_continues_after_baseline_failure(self) -> None:
        output = StringIO()
        with (
            patch("evaluate.run_in_sandbox", return_value=self.valid) as sandbox,
            patch("evaluate.machine.serial_compile", side_effect=[self.compilation, machine.CompileError("baseline failure"), self.compilation]),
            redirect_stdout(output),
        ):
            self.assertIsNone(evaluate.score(program_dir=self.program_dir, verbose=True, continue_on_error=True))
        self.assertEqual(sandbox.call_count, 3)
        self.assertRegex(output.getvalue(), r"second\s+ERROR\n09_third\s+\d+")
        self.assertIn("all programs (2/3 successful):", output.getvalue())
        self.assertIn("original programs 1-8 (1/2 successful):", output.getvalue())

    def test_report_handles_all_failures(self) -> None:
        output = StringIO()
        with patch("evaluate.run_in_sandbox", side_effect=ValueError("failure")) as sandbox, redirect_stdout(output):
            self.assertIsNone(evaluate.score(program_dir=self.program_dir, verbose=True, continue_on_error=True))
        self.assertEqual(sandbox.call_count, 3)
        self.assertEqual(output.getvalue().count("ERROR"), 3)
        self.assertIn("all programs (0/3 successful):", output.getvalue())
        self.assertIn("original programs 1-8 (0/2 successful):", output.getvalue())
        self.assertEqual(output.getvalue().count("Score unavailable: no successful programs."), 2)

    def test_successful_report_preserves_scores(self) -> None:
        output = StringIO()
        with patch("evaluate.run_in_sandbox", return_value=self.valid), redirect_stdout(output):
            metrics = evaluate.score(program_dir=self.program_dir, verbose=True, continue_on_error=True)
        self.assertEqual(metrics, {"cycle_speedup": 1.0, "scratch_reduction": 1.0, "combined_score": 1.0})
        self.assertEqual(output.getvalue().count("combined score: 1.000x"), 2)
        self.assertNotIn("ERROR", output.getvalue())

    def test_subsets_use_separate_geometric_means(self) -> None:
        # Delay two valid schedules to distinguish subset selection and averaging.
        slower = dict(self.compilation, bundles=[{}] * len(self.compilation["bundles"]) + self.compilation["bundles"])
        slowest = dict(self.compilation, bundles=[{}] * (3 * len(self.compilation["bundles"])) + self.compilation["bundles"])
        results = [
            subprocess.CompletedProcess([], 0, json.dumps(slower), ""),
            self.valid,
            subprocess.CompletedProcess([], 0, json.dumps(slowest), ""),
        ]
        output = StringIO()
        with patch("evaluate.run_in_sandbox", side_effect=results), redirect_stdout(output):
            metrics = evaluate.score(program_dir=self.program_dir, verbose=True, continue_on_error=True)
        self.assertAlmostEqual(metrics["cycle_speedup"], 0.5)
        self.assertAlmostEqual(metrics["combined_score"], 0.5 ** 0.5)
        self.assertIn(
            "all programs (3/3 successful):\n"
            "  geometric-mean speedup: 0.500x\n"
            "  geometric-mean scratch reduction: 1.000x\n"
            "  combined score: 0.707x",
            output.getvalue(),
        )
        self.assertIn(
            "original programs 1-8 (2/2 successful):\n"
            "  geometric-mean speedup: 0.707x\n"
            "  geometric-mean scratch reduction: 1.000x\n"
            "  combined score: 0.841x",
            output.getvalue(),
        )

    def test_original_subset_can_fail_while_later_programs_score(self) -> None:
        output = StringIO()
        with (
            patch("evaluate.run_in_sandbox", side_effect=[ValueError("failure"), ValueError("failure"), self.valid]),
            redirect_stdout(output),
        ):
            self.assertIsNone(evaluate.score(program_dir=self.program_dir, verbose=True, continue_on_error=True))
        self.assertIn("all programs (1/3 successful):", output.getvalue())
        self.assertIn("combined score: 1.000x", output.getvalue())
        self.assertIn("original programs 1-8 (0/2 successful):\n  Score unavailable: no successful programs.", output.getvalue())

    def test_missing_original_programs_have_no_score(self) -> None:
        (self.program_dir / "01_first.json").unlink()
        (self.program_dir / "08_second.json").unlink()
        output = StringIO()
        with patch("evaluate.run_in_sandbox", return_value=self.valid), redirect_stdout(output):
            metrics = evaluate.score(program_dir=self.program_dir, verbose=True, continue_on_error=True)
        self.assertEqual(metrics["combined_score"], 1.0)
        self.assertIn("original programs 1-8 (0/0 successful):\n  Score unavailable: no successful programs.", output.getvalue())


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
