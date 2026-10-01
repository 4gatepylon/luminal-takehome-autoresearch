"""Test and score a compiler filepath; execute its JSON CLI only inside sandbox.py.

The parent validates schedules and computes scores with the trusted machine.
Candidate imports, compilation, and CLI execution stay in a separate process.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Set
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Final, TextIO
import unittest

import machine
from program_ssa import parse_program
from sandbox import run_in_sandbox


COMPILER_PATH: Final[Path] = Path("work/compiler.py")
PROGRAM_DIR: Final[Path] = Path("programs")
EXPECTED_PROGRAM_COUNT: Final[int] = 29
ORIGINAL_PROGRAM_FILENAMES: Final[frozenset[str]] = frozenset({
    "01_scalar_pipeline.json",
    "02_scalar_dual_chain.json",
    "03_vector_axpy.json",
    "04_vector_bitmix.json",
    "05_mixed_broadcast.json",
    "06_parallel_memory.json",
    "07_scalar_selects.json",
    "08_vector_reduction.json",
})
EXPECTED_FAILURE_PROGRAM_FILENAMES: Final[frozenset[str]] = frozenset({
    "18_copy_propagation.json",
    "19_interleaved_vector_reductions.json",
    "24_pairwise_vector_reduction.json",
    "25_sum_217_vectors.json",
    "26_sum_31_vectors.json",
})
# Reporting groups overlap; expected failures are excluded from every group.
PROGRAM_GROUPS: Final[Mapping[str, frozenset[str]]] = {
    "original": ORIGINAL_PROGRAM_FILENAMES,
    # At least eight memory loads, accounting for at least one third of operations.
    "load_heavy": frozenset({
        "06_parallel_memory.json", "07_scalar_selects.json", "08_vector_reduction.json",
        "20_vectorization_factoring.json", "21_scalar_vector_sum.json",
        "27_sum_17_scalars.json", "28_sum_16_scalars.json", "29_sum_64_scalars.json",
    }),
    # Repeated expressions, constant folding, identities, and distributive factoring.
    "algebraic_simplification": frozenset({
        "10_repeated_addition.json", "11_repeated_multiplication.json", "12_algebraic_associativity.json",
        "13_constant_condition.json", "15_power_of_two_multiplication.json", "16_algebraic_identities.json",
        "17_non_power_of_two_factoring.json", "20_vectorization_factoring.json", "22_constant_folding.json",
    }),
}


def _identify_program_groups(program_paths: list[Path], program_groups: Mapping[str, Set[str]]) -> dict[str, frozenset[str]]:
    """Validate program expectations and inventory, then define reporting groups."""
    filenames = frozenset(path.name for path in program_paths)
    # The original eight programs are individually required to succeed.
    conflicts = ORIGINAL_PROGRAM_FILENAMES & EXPECTED_FAILURE_PROGRAM_FILENAMES
    if conflicts:
        raise ValueError(f"Programs required to both fail and succeed: {', '.join(sorted(conflicts))}")
    missing = (ORIGINAL_PROGRAM_FILENAMES | EXPECTED_FAILURE_PROGRAM_FILENAMES) - filenames
    if missing:
        raise ValueError(f"Missing required programs: {', '.join(sorted(missing))}")
    if len(program_paths) != EXPECTED_PROGRAM_COUNT:
        raise ValueError(f"Expected {EXPECTED_PROGRAM_COUNT} program files, found {len(program_paths)}")
    groups = {"all programs": filenames - EXPECTED_FAILURE_PROGRAM_FILENAMES}
    for group_name, members in program_groups.items():
        if group_name == "all programs":
            raise ValueError("The 'all programs' group is automatic and cannot be redefined")
        missing = members - filenames
        if missing:
            raise ValueError(f"Group {group_name!r} references missing programs: {', '.join(sorted(missing))}")
        groups[group_name] = frozenset(members) - EXPECTED_FAILURE_PROGRAM_FILENAMES
    return groups


def _validate_ssa_equivalents(program_paths: list[Path]) -> None:
    """Require a matching SSA file for every JSON program, before compilation."""
    for program_path in program_paths:
        ssa_path = program_path.with_suffix(".ssa")
        try:
            program = machine.load_program(program_path)
            restored = parse_program(ssa_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"{program_path}: cannot validate SSA equivalent {ssa_path}: {error}") from error
        if restored != program:
            raise ValueError(f"{ssa_path}: decoded program does not exactly match {program_path}")


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
        self.assertTrue(program_paths, "No public programs found")
        _validate_ssa_equivalents(program_paths)
        for program_path in program_paths:
            with self.subTest(program=program_path.name):
                _compile_and_check(program_path, self.compiler_filepath)


def test(*, compiler_filepath: str | Path = COMPILER_PATH, verbosity: int = 2, stream: TextIO | None = None) -> unittest.TestResult:
    """Run trusted machine tests and public correctness checks for this compiler."""
    suite = unittest.TestLoader().loadTestsFromName("tests.test_machine")
    suite.addTest(PublicProgramTests(compiler_filepath=compiler_filepath))
    return unittest.TextTestRunner(stream=stream, verbosity=verbosity).run(suite)


def _aggregate_scores(results: list[tuple[float, float]]) -> dict[str, float] | None:
    """Compute geometric means over a successful subset, or None if it is empty."""
    if not results:
        return None
    reductions, speedups = zip(*results)
    cycle_mean = math.prod(speedups) ** (1 / len(speedups))
    scratch_mean = math.prod(reductions) ** (1 / len(reductions))
    return dict(cycle_speedup=cycle_mean, scratch_reduction=scratch_mean, combined_score=math.sqrt(cycle_mean * scratch_mean))


def _calculate_reduction_and_speedup(program_path: Path, compiler_filepath: str | Path, *, verbose: bool = False) -> tuple[float, float]:
    """Compile and validate once, then return scratch reduction and cycle speedup."""
    program, compilation, cycles = _compile_and_check(program_path, compiler_filepath)
    baseline_compilation = machine.serial_compile(program)
    baseline = machine.check_compilation(program, baseline_compilation)
    words = machine.scratch_footprint(program, compilation)
    baseline_words = machine.scratch_footprint(program, baseline_compilation)
    reduction = baseline_words / words
    speedup = baseline / cycles
    if verbose:
        print(f"{program_path.name:40} {cycles:8d} {baseline:9d} {speedup:8.3f}x {words:8d} {reduction:9.3f}x")
    return reduction, speedup


def score(*, compiler_filepath: str | Path = COMPILER_PATH, program_dir: Path = PROGRAM_DIR,
    verbose: bool = False, program_groups: Mapping[str, Set[str]] = PROGRAM_GROUPS,
) -> dict[str, float]:
    """Evaluate each program once, enforce its expected outcome, and report overlapping groups."""
    program_paths = sorted(path for path in program_dir.glob("*.json") if path.is_file())
    groups = _identify_program_groups(program_paths, program_groups)
    # Keep data-integrity failures outside the expected compiler-failure handling.
    _validate_ssa_equivalents(program_paths)
    results: dict[str, tuple[float, float]] = {}
    if verbose:
        print("Luminal Compiler Take Home — compiler engineering public benchmark")
        print(f"{'program':40} {'cycles':>8} {'baseline':>9} {'speedup':>9} {'scratch':>8} {'reduction':>10}")
        print("-" * 99)
    for program_path in program_paths:
        must_fail = program_path.name in EXPECTED_FAILURE_PROGRAM_FILENAMES
        try:
            result = _calculate_reduction_and_speedup(program_path, compiler_filepath, verbose=verbose)
        except (ValueError, subprocess.TimeoutExpired):
            if verbose:
                print(f"{program_path.name:40} {'ERROR':>8}")
            if not must_fail:
                raise
        else:
            if must_fail:
                raise ValueError(f"{program_path.name}: expected failure, but evaluation succeeded")
            results[program_path.name] = result

    group_metrics = {
        name: _aggregate_scores([results[filename] for filename in sorted(members) if filename in results])
        for name, members in groups.items()
    }
    if verbose:
        print("-" * 99)
        failures = len(program_paths) - len(results)
        if failures:
            print(f"{failures} program(s) failed; excluded from all scores.")
        for group_name, metrics in group_metrics.items():
            print(f"{group_name} ({len(groups[group_name])} successful programs):")
            if metrics is None:
                print("  Score unavailable: no successful programs.")
            else:
                print(f"  geometric-mean speedup: {metrics['cycle_speedup']:.3f}x")
                print(f"  geometric-mean scratch reduction: {metrics['scratch_reduction']:.3f}x")
                print(f"  combined score: {metrics['combined_score']:.3f}x")
    return group_metrics["all programs"]


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
