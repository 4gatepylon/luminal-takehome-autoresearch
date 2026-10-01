"""Command-line input validation and diagram file output."""

import argparse
from pathlib import Path
import subprocess
import sys

from machine import load_program
from visualize_ssa_as_dag._dot import program_dot
from visualize_ssa_as_dag._gallery import write_gallery
from visualize_ssa_as_dag._graphviz import render_svg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render an SSA diagram or build an offline gallery of programs."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    image = commands.add_parser("image", help="render one program as SVG or DOT")
    image.add_argument(
        "program", type=Path, help="program JSON in this repository's SSA format"
    )
    image.add_argument(
        "-o", "--output", type=Path,
        help="output .svg or .dot (default: <program>.svg)",
    )
    gallery = commands.add_parser("gallery", help="build a local webpage of all diagrams")
    gallery.add_argument(
        "--programs-dir", type=Path, default=Path("programs"),
        help="directory of program JSON files (default: programs)",
    )
    gallery.add_argument(
        "-o", "--output", type=Path, default=Path("dag-gallery"),
        help="gallery directory (default: dag-gallery, gitignored)",
    )
    gallery.add_argument(
        "--clobber", "--c", "-c", action="store_true",
        help="overwrite generated files in an existing gallery",
    )
    argv = sys.argv[1:]
    # Keep the original positional program invocation working.
    if argv and argv[0] not in {"image", "gallery", "-h", "--help"}:
        argv = ["image", *argv]
    args = parser.parse_args(argv)
    if args.command == "gallery":
        try:
            output = write_gallery(args.programs_dir, args.output, clobber=args.clobber)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"visualize_ssa_as_dag: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote {output}; double-click it to open the gallery in your browser.")
        return 0
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
