"""Implemented by Codex (GPT-6).

Scoring library and CLI contract; public programs use the serial reference compiler.
"""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import score


class ScoreTests(unittest.TestCase):
    def test_library_returns_metrics_without_printing(self):
        output = StringIO()
        with patch.object(score.compiler, "compile_program", score.machine.serial_compile), redirect_stdout(output):
            metrics = score.score()
        self.assertEqual(metrics, {"cycle_speedup": 1.0, "scratch_reduction": 1.0, "combined_score": 1.0})
        self.assertEqual(output.getvalue(), "")

    def test_cli_keeps_formatted_summary(self):
        output = StringIO()
        with patch.object(score.compiler, "compile_program", score.machine.serial_compile), redirect_stdout(output):
            self.assertEqual(score.main(), 0)
        self.assertIn("Luminal Compiler Take Home", output.getvalue())
        self.assertEqual(
            output.getvalue().splitlines()[-3:],
            [
                "public geometric-mean speedup: 1.000x",
                "public geometric-mean scratch reduction: 1.000x",
                "public combined score: 1.000x",
            ],
        )

    def test_empty_program_directory_fails(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "No benchmark programs"):
            score.score(program_dir=Path(directory))
