#!/usr/bin/env python3
"""Command-line interface for compiling a program to a JSON schedule."""

from __future__ import annotations

import argparse
import json
import sys

import machine

from .compilation import compile_program


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program")
    parser.add_argument("--n-optimization-iterations", type=int, default=128)
    parser.add_argument("--max-inner-iterations", type=int, default=32)
    parser.add_argument("--crash-on-sampling-failure", action="store_true")
    parser.add_argument("--sample-strategy", choices=("uniform_at_random", "softmax", "power"), default="uniform_at_random")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--cutoff", type=float, default=0.0, help="score cutoff for power sampling")
    parser.add_argument("--power", type=float, default=2.0, help="exponent for power sampling")
    args = parser.parse_args(argv)

    program = machine.load_program(args.program)
    compilation = compile_program(
        program, n_optimization_iterations=args.n_optimization_iterations,
        max_inner_iterations=args.max_inner_iterations,
        crash_on_sampling_failure=args.crash_on_sampling_failure,
        sample_strategy=args.sample_strategy,
        sample_strategy_kwargs={"temperature": args.temperature, "cutoff": args.cutoff, "power": args.power},
    )
    machine.check_compilation(program, compilation)
    json.dump(compilation, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
