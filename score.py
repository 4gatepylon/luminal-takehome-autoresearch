#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering public benchmark."""

from __future__ import annotations

import math
from pathlib import Path

import machine
from compiler_loader import DEFAULT_COMPILER_PATH, load_compiler

PROGRAM_DIR = Path(__file__).parent / "programs"


def score(compiler_path: str | Path = DEFAULT_COMPILER_PATH, *, program_dir: Path = PROGRAM_DIR, verbose: bool = False) -> dict[str, float]:
    """Validate the public programs and return unrounded score multipliers."""
    compile_fn = load_compiler(compiler_path)
    speedups = []
    reductions = []
    if verbose:
        print("Luminal Compiler Take Home — compiler engineering public benchmark")
        print(f"{'program':30} {'cycles':>8} {'baseline':>9} {'speedup':>9} {'scratch':>8} {'reduction':>10}")
        print("-" * 60)
    for path in sorted(program_dir.glob("*.json")):
        program = machine.load_program(path)
        compilation = compile_fn(program)
        cycles = machine.check_compilation(program, compilation)
        for case in program["cases"]:
            machine.check_case(program, compilation, case)
        baseline = machine.check_compilation(program, machine.serial_compile(program))
        speedup = baseline / cycles
        speedups.append(speedup)
        words = machine.scratch_footprint(program, compilation)
        baseline_words = machine.scratch_footprint(program, machine.serial_compile(program))
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


def main() -> int:
    score(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
