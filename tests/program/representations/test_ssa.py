"""SSA round trips using the existing codec and fixtures."""

from copy import deepcopy
from pathlib import Path
import unittest

from machine import load_program
from program.representations import Representation
from program.representations.ssa import SsaRepresentation


class SsaRepresentationTests(unittest.TestCase):
    def test_all_programs_match_existing_ssa_without_mutation(self):
        representation = SsaRepresentation()
        self.assertIsInstance(representation, Representation)
        paths = sorted(Path("programs/json").glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(program=path.name):
                program = load_program(path)
                before = deepcopy(program)
                text = representation.encode(program)
                expected = (Path("programs/ssa") / path.with_suffix(".ssa").name).read_text(encoding="utf-8")
                self.assertEqual(text, expected)
                self.assertEqual(representation.decode(text), before)
                self.assertEqual(program, before)

    def test_metadata_and_aliases_round_trip(self):
        representation = SsaRepresentation()
        program = load_program("programs/json/03_vector_axpy.json")
        program["metadata"] = {"unicode": "λ", "values": [None, True, 1.25]}
        program["operations"][0]["dest"] = "not an identifier"
        program["operations"][1]["args"] = ["not an identifier"]
        self.assertEqual(representation.decode(representation.encode(program)), program)

    def test_invalid_input_is_rejected(self):
        representation = SsaRepresentation()
        with self.assertRaises(ValueError):
            representation.decode("invalid SSA")
        with self.assertRaises(ValueError):
            representation.encode({})
