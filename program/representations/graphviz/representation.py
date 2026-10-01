"""Encode program data as SVG or DOT text."""

from typing import Literal

from program.core import Program, validate_program
from program.representations.base import Representation
from program.representations.graphviz._dot import program_dot
from program.representations.graphviz._graphviz import render_svg


class GraphvizRepresentation(Representation):
    """SVG by default; DOT output does not require Graphviz to be installed."""

    def __init__(self, *, format: Literal["svg", "dot"] = "svg") -> None:
        if format not in {"svg", "dot"}:
            raise ValueError("Graphviz format must be 'svg' or 'dot'")
        self.format = format

    def encode(self, program: Program) -> str:
        validate_program(program)
        source = program_dot(program)
        return render_svg(source) if self.format == "svg" else source

    def decode(self, text: str) -> Program:
        raise NotImplementedError("Graphviz output is a visualization and cannot be decoded into a program")
