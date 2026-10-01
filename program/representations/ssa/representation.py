"""Adapt the existing lossless SSA codec to the representation contract."""

from program.core import Program
from program.representations.base import Representation
from program_ssa import format_program, parse_program


class SsaRepresentation(Representation):
    """Encode canonical ssa-v1 text and decode authored SSA with validation."""

    def encode(self, program: Program) -> str:
        return format_program(program)

    def decode(self, text: str) -> Program:
        return parse_program(text)
