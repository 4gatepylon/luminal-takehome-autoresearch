"""Exercise the package entry point and its file outputs."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from machine import load_program
from visualize_ssa_as_dag import program_dot


class CliTests(unittest.TestCase):
    def run_cli(self, output, *, env=None, explicit_command=False):
        return subprocess.run(
            [sys.executable, "-B", "-m", "visualize_ssa_as_dag",
             *(["image"] if explicit_command else []),
             "programs/json/03_vector_axpy.json", "-o", str(output)],
            text=True, capture_output=True, timeout=30, env=env,
        )

    def test_dot_output_without_graphviz(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "diagram.dot"
            result = self.run_cli(output, env={**os.environ, "PATH": ""})
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = program_dot(load_program("programs/json/03_vector_axpy.json"))
            self.assertEqual(output.read_text(encoding="utf-8"), expected)
            self.assertEqual(list(Path(directory).iterdir()), [output])

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_svg_and_dot_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "diagram.svg"
            result = self.run_cli(output, explicit_command=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(ET.parse(output).getroot().tag, "{http://www.w3.org/2000/svg}svg")
            self.assertTrue(output.with_suffix(".dot").is_file())

    def test_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "diagram.png"
            result = self.run_cli(output)
            self.assertEqual(result.returncode, 2)
            self.assertIn(".svg or .dot", result.stderr)
            self.assertFalse(output.exists())
