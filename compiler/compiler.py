#!/usr/bin/env python3
"""Command-line interface for compiling a program to a JSON schedule."""

from __future__ import annotations

import argparse
import json
import sys

import machine

from .compilation import compile_program
from .custom_scheduling import SCHEDULER_NAME2ORDERINGS_FN


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", help="input program JSON")
    parser.add_argument("--scheduler", choices=("source", *SCHEDULER_NAME2ORDERINGS_FN), default="source")
    args = parser.parse_args(argv)
    program = machine.load_program(args.program)
    compilation = compile_program(program, scheduling_strategy=args.scheduler)
    machine.check_compilation(program, compilation)
    json.dump(compilation, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
