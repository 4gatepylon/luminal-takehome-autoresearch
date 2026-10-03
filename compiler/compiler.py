#!/usr/bin/env python3
"""Command-line interface for compiling a program to a JSON schedule."""

from __future__ import annotations

import json
import sys

import machine

from .compilation import compile_program


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 -m compiler.compiler <program.json>", file=sys.stderr)
        return 2

    program = machine.load_program(argv[0])
    compilation = compile_program(program)
    machine.check_compilation(program, compilation)
    json.dump(compilation, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
