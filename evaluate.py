"""Test and score a compiler filepath; execute its JSON CLI only inside sandbox.py.

The parent validates schedules and computes scores with the trusted machine.
Candidate imports, compilation, and CLI execution stay in a separate process.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Final, TextIO
import unittest

import machine
from sandbox import run_in_sandbox


COMPILER_PATH: Final[Path] = Path("work/compiler.py")
PROGRAM_DIR: Final[Path] = Path("programs")


def _compile_and_check(program_path: Path, compiler_filepath: str | Path) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Run one compiler CLI with a 20-second limit and validate its JSON in the parent."""
    program = machine.load_program(program_path)
    result = run_in_sandbox(
        [sys.executable, "-B", str(Path(compiler_filepath).resolve()), str(program_path.resolve())],
        timeout=20,
    )
    if result.returncode:
        raise ValueError(f"{program_path.name}: compiler exited with {result.returncode}: {result.stderr[-4000:]}")
    compilation = json.loads(result.stdout)
    cycles = machine.check_compilation(program, compilation)
    for case in program["cases"]:
        machine.check_case(program, compilation, case)
    return program, compilation, cycles


class PublicProgramTests(unittest.TestCase):
    """Apply the public correctness checks to the selected sandboxed compiler."""

    def __init__(self, methodName: str = "test_compiler_on_all_public_programs", *, compiler_filepath: str | Path = COMPILER_PATH) -> None:
        super().__init__(methodName)
        self.compiler_filepath = compiler_filepath

    def test_compiler_on_all_public_programs(self) -> None:
        program_paths = sorted(PROGRAM_DIR.glob("*.json"))
        self.assertEqual(len(program_paths), 9)
        for program_path in program_paths:
            with self.subTest(program=program_path.name):
                _compile_and_check(program_path, self.compiler_filepath)


def test(*, compiler_filepath: str | Path = COMPILER_PATH, verbosity: int = 2, stream: TextIO | None = None) -> unittest.TestResult:
    """Run trusted machine tests and public correctness checks for this compiler."""
    suite = unittest.TestLoader().loadTestsFromName("tests.test_machine")
    suite.addTest(PublicProgramTests(compiler_filepath=compiler_filepath))
    return unittest.TextTestRunner(stream=stream, verbosity=verbosity).run(suite)


def score(*, compiler_filepath: str | Path = COMPILER_PATH, program_dir: Path = PROGRAM_DIR, verbose: bool = False) -> dict[str, float]:
    """Validate sandboxed compiler output and return unrounded score multipliers."""
    speedups: list[float] = []
    reductions: list[float] = []
    if verbose:
        print("Luminal Compiler Take Home — compiler engineering public benchmark")
        print(f"{'program':30} {'cycles':>8} {'baseline':>9} {'speedup':>9} {'scratch':>8} {'reduction':>10}")
        print("-" * 60)
    for program_path in sorted(program_dir.glob("*.json")):
        program, compilation, cycles = _compile_and_check(program_path, compiler_filepath)
        baseline_compilation = machine.serial_compile(program)
        baseline = machine.check_compilation(program, baseline_compilation)
        speedup = baseline / cycles
        speedups.append(speedup)
        words = machine.scratch_footprint(program, compilation)
        baseline_words = machine.scratch_footprint(program, baseline_compilation)
        reduction = baseline_words / words
        reductions.append(reduction)
        if verbose:
            print(f"{program['name']:30} {cycles:8d} {baseline:9d} {speedup:8.3f}x {words:8d} {reduction:9.3f}x")

    if not speedups:
        raise ValueError(f"No benchmark programs found in {program_dir}")
    geometric_mean = math.prod(speedups) ** (1 / len(speedups))
    scratch_mean = math.prod(reductions) ** (1 / len(reductions))
    metrics = {
        "cycle_speedup": geometric_mean,
        "scratch_reduction": scratch_mean,
        "combined_score": math.sqrt(geometric_mean * scratch_mean),
    }
    if verbose:
        print("-" * 60)
        print(f"public geometric-mean speedup: {metrics['cycle_speedup']:.3f}x")
        print(f"public geometric-mean scratch reduction: {metrics['scratch_reduction']:.3f}x")
        print(f"public combined score: {metrics['combined_score']:.3f}x")
    return metrics


def eval(*, compiler_filepath: str | Path = COMPILER_PATH, verbose: bool = False, stream: TextIO | None = None) -> dict[str, float] | None:
    """Run tests, then score the selected compiler; return None if tests fail."""
    if not test(compiler_filepath=compiler_filepath, stream=stream).wasSuccessful():
        return None
    return score(compiler_filepath=compiler_filepath, verbose=verbose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("test", "score", "eval"))
    parser.add_argument("--compiler-filepath", type=Path, default=COMPILER_PATH)
    args = parser.parse_args(argv)
    if args.command == "test":
        return 0 if test(compiler_filepath=args.compiler_filepath).wasSuccessful() else 1
    if args.command == "eval":
        return 0 if eval(compiler_filepath=args.compiler_filepath, verbose=True) is not None else 1
    score(compiler_filepath=args.compiler_filepath, verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
