"""Readable JSON encoding and decoding using the standard library."""

import json

from program.core import Program, validate_program
from program.representations._json import DECODER
from program.representations.base import Representation


class JsonRepresentation(Representation):
    """Preserve the full program, including test cases and extra metadata."""

    def encode(self, program: Program) -> str:
        validate_program(program)
        return json.dumps(program, ensure_ascii=True, allow_nan=False, indent=2) + "\n"

    def decode(self, text: str) -> Program:
        program = DECODER.decode(text)
        validate_program(program)
        return program
