"""Encode program data as SVG text using Graphviz."""

from program.core import Program, validate_program
from program.representations.base import Representation
from program.representations.graphviz._dot import program_dot
from program.representations.graphviz._graphviz import render_svg


class GraphvizRepresentation(Representation):
    """An SVG visualization; Graphviz must be installed to encode."""

    def encode(self, program: Program) -> str:
        validate_program(program)
        return render_svg(program_dot(program))

    def decode(self, text: str) -> Program:
        raise NotImplementedError("Graphviz SVG is a visualization and cannot be decoded into a program")
