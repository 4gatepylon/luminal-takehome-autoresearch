"""Check that JSON/SSA chains preserve program data and canonical text."""

from copy import deepcopy
from pathlib import Path
import unittest

from machine import load_program
from program.representations.json import JsonRepresentation
from program.representations.ssa import SsaRepresentation


class RepresentationChainTests(unittest.TestCase):
    def assert_representation_chains(self, program):
        expected = deepcopy(program)
        json = JsonRepresentation()
        ssa = SsaRepresentation()
        for first, second in ((json, ssa), (ssa, json)):
            with self.subTest(first=type(first).__name__):
                initial_text = first.encode(program)
                intermediate = first.decode(initial_text)
                self.assertEqual(program, expected, "Original program changed")
                self.assertEqual(intermediate, expected, "First round trip changed the program")

                final = second.decode(second.encode(intermediate))
                self.assertEqual(final, expected, "Second round trip changed the program")
                self.assertEqual(first.encode(final), initial_text, "Canonical text changed")

                # All three program objects must remain equal, including after encoding.
                self.assertEqual(program, expected, "Original program was mutated")
                self.assertEqual(intermediate, expected, "Intermediate program was mutated")
                self.assertEqual(final, expected, "Final program was mutated")

    def test_all_programs_in_both_directions(self):
        paths = sorted(Path("programs/json").glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(program=path.name):
                self.assert_representation_chains(load_program(path))

    def test_chain_preserves_metadata_and_aliased_names(self):
        program = load_program("programs/json/03_vector_axpy.json")
        program["metadata"] = {"unicode": "λ", "values": [None, True, 1.25]}
        program["operations"][0]["note"] = {"nested": ["quoted \"text\"", "a\nb"]}
        program["operations"][0]["dest"] = "not an identifier"
        program["operations"][1]["args"] = ["not an identifier"]
        self.assert_representation_chains(program)
