"""Command-line input validation and diagram file output."""

import argparse
from pathlib import Path
import subprocess
import sys

from machine import load_program
from visualize_ssa_as_dag._dot import program_dot
from visualize_ssa_as_dag._graphviz import render_svg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render SSA values and operation junctions as a Graphviz SVG."
    )
    parser.add_argument(
        "program", type=Path, help="program JSON in this repository's SSA format"
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        help="output .svg or .dot (default: <program>.svg)",
    )
    args = parser.parse_args()
    output = args.output or args.program.with_suffix(".svg")
    if output.suffix.lower() not in {".svg", ".dot"}:
        parser.error("output must have an .svg or .dot extension")
    dot_path = output.with_suffix(".dot")
    if args.program.resolve() in {output.resolve(), dot_path.resolve()}:
        parser.error("output must not overwrite the input program")
    try:
        source = program_dot(load_program(args.program))
        if output.suffix.lower() == ".svg":
            output.write_text(render_svg(source), encoding="utf-8")
        dot_path.write_text(source, encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"visualize_ssa_as_dag: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {output}" + (f" and {dot_path}" if output != dot_path else ""))
    return 0
