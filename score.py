#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering public benchmark."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from compiler import compile_program
import machine


PROGRAM_DIR = Path(__file__).parent / "programs"
# Filenames are relative to PROGRAM_DIR. The special "all" group is discovered.
PROGRAM_GROUPS = {
    "original": [
        "original_programs/01_scalar_pipeline.json",
        "original_programs/02_scalar_dual_chain.json",
        "original_programs/03_vector_axpy.json",
        "original_programs/04_vector_bitmix.json",
        "original_programs/05_mixed_broadcast.json",
        "original_programs/06_parallel_memory.json",
        "original_programs/07_scalar_selects.json",
        "original_programs/08_vector_reduction.json",
    ],
    "allocation_diagnostics": [
        "allocation_diagnostics/01_alignment_holes.json",
        "allocation_diagnostics/02_vector_block_migration.json",
        "allocation_diagnostics/03_vector_lifetime_gaps.json",
        "allocation_diagnostics/04_scalar_tail_reuse.json",
        "allocation_diagnostics/05_inclusive_boundary.json",
        "allocation_diagnostics/06_retained_vectors_16.json",
        "allocation_diagnostics/07_rolling_vectors_15_of_16.json",
        "allocation_diagnostics/08_pinned_vector_blocks.json",
    ],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allocation-strategy",
        choices=("any", "first-fit", "disjoint", "hierarchical-first-fit"),
        default="any",
        help="scratch allocator; any tries every allocator and keeps the smallest footprint",
    )
    parser.add_argument(
        "--sample-strategy", choices=("uniform_at_random", "softmax"),
        default="uniform_at_random", help="distribution for sampling previous orderings",
    )
    parser.add_argument("--temperature", type=float, default=1.0, help="softmax sampling temperature")
    args = parser.parse_args(argv)
    group_name2filenames = {
        **PROGRAM_GROUPS,
        "all": sorted(path.relative_to(PROGRAM_DIR).as_posix() for path in PROGRAM_DIR.rglob("*.json")),
    }
    for group_name, filenames in group_name2filenames.items():
        missing_filenames = set(filenames) - set(group_name2filenames["all"])
        if missing_filenames:
            raise ValueError(f"group {group_name!r} has missing programs: {sorted(missing_filenames)}")

    print("Luminal Compiler Take Home — compiler engineering public benchmark")
    print(f"scratch allocation strategy: {args.allocation_strategy}")
    print(f"ordering sample strategy: {args.sample_strategy}")
    if args.sample_strategy == "softmax":
        print(f"softmax temperature: {args.temperature}")
    filename2speedup_and_scratch_reduction: dict[str, tuple[float, float]] = {}
    print(f"{'program':30} {'cycles':>8} {'baseline':>9} {'speedup':>9} {'scratch':>8} {'reduction':>10}")
    print("-" * 60)
    for filename in group_name2filenames["all"]:
        program = machine.load_program(PROGRAM_DIR / filename)
        compilation = compile_program(
            program, scratch_allocation_strategy=args.allocation_strategy,
            sample_strategy=args.sample_strategy,
            sample_strategy_kwargs={"temperature": args.temperature},
        )
        cycles = machine.check_compilation(program, compilation)
        for case in program["cases"]:
            machine.check_case(program, compilation, case)
        baseline_compilation = machine.serial_compile(program)
        baseline = machine.check_compilation(program, baseline_compilation)
        speedup = baseline / cycles
        words = machine.scratch_footprint(program, compilation)
        baseline_words = machine.scratch_footprint(program, baseline_compilation)
        reduction = baseline_words / words
        filename2speedup_and_scratch_reduction[filename] = (speedup, reduction)
        print(f"{program['name']:30} {cycles:8d} {baseline:9d} {speedup:8.3f}x {words:8d} {reduction:9.3f}x")

    for group_name, filenames in group_name2filenames.items():
        print(f"\naggregate for {group_name} ({len(filenames)} programs):")
        if not filenames:
            print("no programs")
            continue
        speedups, reductions = zip(*(filename2speedup_and_scratch_reduction[name] for name in filenames))
        geometric_mean = math.prod(speedups) ** (1 / len(speedups))
        scratch_mean = math.prod(reductions) ** (1 / len(reductions))
        print(f"geometric-mean speedup: {geometric_mean:.3f}x")
        print(f"geometric-mean scratch reduction: {scratch_mean:.3f}x")
        print(f"combined score: {math.sqrt(geometric_mean * scratch_mean):.3f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
