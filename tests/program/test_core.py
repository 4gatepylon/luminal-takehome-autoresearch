"""Shared validation and representation contract tests."""

from copy import deepcopy
import unittest

from machine import load_program
from program.core import ProgramError, validate_program
from program.representations import Representation


class CoreTests(unittest.TestCase):
    def test_validation_preserves_program_and_metadata(self):
        program = load_program("programs/json/03_vector_axpy.json")
        program["note"] = {"labels": ["example", None]}
        before = deepcopy(program)
        validate_program(program)
        self.assertEqual(program, before)

    def test_validation_rejects_undefined_operand(self):
        program = load_program("programs/json/03_vector_axpy.json")
        program["operations"][1]["args"] = ["undefined"]
        with self.assertRaises(ProgramError):
            validate_program(program)

    def test_representation_requires_both_methods(self):
        class EncodeOnly(Representation):
            def encode(self, program):
                return ""

        with self.assertRaises(TypeError):
            Representation()
        with self.assertRaises(TypeError):
            EncodeOnly()
