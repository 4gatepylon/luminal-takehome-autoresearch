"""Luminal Compiler Take Home — Public compiler correctness tests for compiler engineering."""

from __future__ import annotations

import unittest
from pathlib import Path

import machine
from compiler_loader import DEFAULT_COMPILER_PATH, load_compiler

PROGRAM_DIR = Path(__file__).parents[1] / "programs"


class PublicProgramTests(unittest.TestCase):
    compiler_path = DEFAULT_COMPILER_PATH

    def test_compiler_on_all_public_programs(self):
        compile_fn = load_compiler(self.compiler_path)
        paths = sorted(PROGRAM_DIR.glob("*.json"))
        self.assertEqual(len(paths), 8)
        for path in paths:
            with self.subTest(program=path.name):
                program = machine.load_program(path)
                compilation = compile_fn(program)
                machine.check_compilation(program, compilation)
                for case in program["cases"]:
                    machine.check_case(program, compilation, case)


if __name__ == "__main__":
    unittest.main()
